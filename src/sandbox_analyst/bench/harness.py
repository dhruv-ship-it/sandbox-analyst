"""The resumable DABench evaluation harness: `uv run sa eval`.

Runs `run_agent` across a split's questions through a thread pool that
shares ONE LLM client (and therefore one rate limiter -- Modal sandboxes
are independent per question, created fresh per call). Each finished
question is appended to `runs/eval/<run-name>/results.jsonl`; a restart
reads that file back and skips every id already recorded there, except
ids recorded as "infra_error" (provider/sandbox trouble, not a model
mistake), which are always re-queued. A clean stop (token budget, the
sandbox ledger guard, or 3 consecutive infra errors) stops submitting
new work, lets in-flight questions finish, writes everything done so
far, prints the counts and the exact resume command, and exits non-zero
(see D-059/D-061).
"""

import hashlib
import json
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sandbox_analyst.agent import AgentEvent, AgentResult, TraceWriter, run_agent
from sandbox_analyst.bench.dabench import Question, load_questions
from sandbox_analyst.bench.download import PINNED_REVISION
from sandbox_analyst.bench.split import DEFAULT_QUESTIONS_PATH, DEFAULT_SPLIT_PATH, GitRunner
from sandbox_analyst.bench.split import load_split as _load_split
from sandbox_analyst.llm import LLMClient, make_llm
from sandbox_analyst.sandbox import Sandbox, make_sandbox
from sandbox_analyst.sandbox.ledger import DEFAULT_LEDGER_PATH, ledger_total_usd
from sandbox_analyst.sandbox.modal_image import PINNED_PACKAGES

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

DEFAULT_EVAL_DIR = Path("runs/eval")
DEFAULT_TABLES_DIR = Path("data/dabench/da-dev-tables")
DEFAULT_TOKEN_BUDGET = 1_500_000
CONSECUTIVE_INFRA_ERROR_LIMIT = 3
INFRA_STATUSES = frozenset({"llm_error", "tool_failure"})


class HeldOutRunRequired(Exception):
    """Raised when --split test is requested without --final-held-out-run."""


# ---- per-attempt / per-question result shape ----


@dataclass(frozen=True)
class AttemptSummary:
    attempt: int
    code_hash: str | None
    check_ok: bool | None
    exec_outcome: str
    error_type: str | None
    evidenced_answers: list[dict[str, str]]
    unverified_answers: list[dict[str, str]]


@dataclass(frozen=True)
class QuestionResult:
    id: int
    level: str | None
    status: str
    infra_cause: str | None
    attempts: list[AttemptSummary]
    final_answers: list[dict[str, str]]
    prompt_tokens: int
    completion_tokens: int
    total_latency_ms: int
    wall_time_ms: int
    sandbox_usd: float
    llm_request_count: int
    trace_path: str


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _exec_outcome(payload: dict) -> tuple[str, str | None]:
    if payload.get("crashed"):
        return "crashed", "SandboxCrashed"
    if payload.get("unavailable"):
        return "unavailable", "SandboxUnavailable"
    if payload.get("timed_out"):
        return "timeout", None
    error = payload.get("error")
    if error:
        return "error", error["name"]
    return "ok", None


_ATTEMPT_SCOPED_EVENT_TYPES = frozenset({"code", "static_check", "exec_result", "evidence"})


class _AttemptCollector:
    """Builds AttemptSummary rows and an LLM-request count from one run's AgentEvent stream.

    Only the event types that actually carry a field this module reads create a row
    -- notably NOT "observation", whose payload is never used here, so a run that
    fails before any code is even generated (e.g. an `llm_error`) correctly produces
    zero attempt rows rather than one empty one. Also NOT "run_started"/"profile"/
    "run_finished", which are run-level: checking `event.type` here rather than
    `event.attempt == 0` matters because `run_finished` is (surprisingly) emitted
    with `attempt=MAX_ATTEMPTS`, not 0.
    """

    def __init__(self) -> None:
        self._by_attempt: dict[int, dict] = {}
        self.llm_request_count = 0

    def __call__(self, event: AgentEvent) -> None:
        if event.type == "llm_request":
            self.llm_request_count += 1
            return
        if event.type not in _ATTEMPT_SCOPED_EVENT_TYPES:
            return
        row = self._by_attempt.setdefault(event.attempt, {})
        if event.type == "code":
            code = event.payload.get("code")
            row["code_hash"] = _hash_code(code) if isinstance(code, str) else None
        elif event.type == "static_check":
            row["check_ok"] = event.payload["ok"]
        elif event.type == "exec_result":
            row["exec_outcome"], row["error_type"] = _exec_outcome(event.payload)
        elif event.type == "evidence":
            results = event.payload["results"]
            row["evidenced"] = [
                {"name": r["name"], "value": r["value"]} for r in results if r["passed"]
            ]
            row["unverified"] = [
                {"name": r["name"], "value": r["value"]} for r in results if not r["passed"]
            ]

    def summaries(self) -> list[AttemptSummary]:
        return [
            AttemptSummary(
                attempt=attempt,
                code_hash=row.get("code_hash"),
                check_ok=row.get("check_ok"),
                exec_outcome=row.get("exec_outcome", "no_exec"),
                error_type=row.get("error_type"),
                evidenced_answers=row.get("evidenced", []),
                unverified_answers=row.get("unverified", []),
            )
            for attempt, row in sorted(self._by_attempt.items())
        ]


class _LazyTraceAndCollect:
    """on_event subscriber: writes a trace (keyed by the run's own run_id, D-053) AND collects."""

    def __init__(self, collector: _AttemptCollector) -> None:
        self._collector = collector
        self._writer: TraceWriter | None = None
        self.trace_path: Path | None = None

    def __call__(self, event: AgentEvent) -> None:
        if self._writer is None:
            self._writer = TraceWriter(event.run_id)
            self.trace_path = self._writer.path
        self._writer(event)
        self._collector(event)


def _build_question_result(
    question: Question,
    result: AgentResult,
    collector: _AttemptCollector,
    wall_time_ms: int,
    trace_path: Path | None,
) -> QuestionResult:
    is_infra = result.status in INFRA_STATUSES
    return QuestionResult(
        id=question.id,
        level=question.level,
        status="infra_error" if is_infra else result.status,
        infra_cause=result.status if is_infra else None,
        attempts=collector.summaries(),
        final_answers=[{"name": a.name, "value": a.value} for a in result.answers],
        prompt_tokens=result.total_prompt_tokens,
        completion_tokens=result.total_completion_tokens,
        total_latency_ms=result.total_latency_ms,
        wall_time_ms=wall_time_ms,
        sandbox_usd=result.sandbox_usd,
        llm_request_count=collector.llm_request_count,
        trace_path=str(trace_path) if trace_path is not None else "",
    )


def run_one_question(
    question: Question,
    csv_bytes: bytes,
    llm: LLMClient,
    sandbox: Sandbox,
    settings: "Settings",
    clock: Callable[[], float] = time.monotonic,
) -> QuestionResult:
    """Run one question end to end and build its QuestionResult."""
    collector = _AttemptCollector()
    subscriber = _LazyTraceAndCollect(collector)

    start = clock()
    result = run_agent(
        csv_bytes,
        question.file_name,
        question.question,
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=settings,
        on_event=subscriber,
        constraints=question.constraints,
        answer_format=question.format,
        clock=clock,
    )
    wall_time_ms = int((clock() - start) * 1000)
    return _build_question_result(question, result, collector, wall_time_ms, subscriber.trace_path)


# ---- resumable results.jsonl ----


class ResultsWriter:
    """Thread-safe, append-only results.jsonl writer that also reads itself back for resume."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, result: QuestionResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(result))
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_latest(self) -> dict[int, dict]:
        """The latest row per question id -- a re-queued retry supersedes an earlier one."""
        if not self.path.exists():
            return {}
        latest: dict[int, dict] = {}
        with self.path.open(encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if raw_line:
                    row = json.loads(raw_line)
                    latest[row["id"]] = row
        return latest


def done_ids(latest: dict[int, dict]) -> set[int]:
    """ids that don't need to be re-run -- i.e. every id NOT recorded as infra_error."""
    return {qid for qid, row in latest.items() if row["status"] != "infra_error"}


# ---- test-split gating ----


def load_questions_for_split(
    split: str,
    final_held_out_run: bool,
    split_path: Path = DEFAULT_SPLIT_PATH,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    git_run: GitRunner | None = None,
) -> list[Question]:
    """Load one split's questions. "test" refuses without BOTH gates (D-059):

    this flag AND bench.split.load_split's own clean-tree + frozen-*-tag check.
    """
    if split == "test" and not final_held_out_run:
        raise HeldOutRunRequired(
            "loading the test split requires --final-held-out-run (and a clean, "
            "frozen-*-tagged working tree); refusing"
        )
    kwargs = {} if git_run is None else {"git_run": git_run}
    side = _load_split(split, split_path, **kwargs)
    all_questions = load_questions(questions_path)
    ids = set(side["question_ids"])
    return [q for q in all_questions if q.id in ids]


# ---- manifest ----


@dataclass(frozen=True)
class Manifest:
    run_name: str
    split: str
    date: str
    git_sha: str
    prompt_version: str
    provider: str
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    reasoning_effort: str
    llm_timeout_s: float
    sandbox_image_pins: list[str]
    dabench_revision: str
    split_hash: str
    concurrency: int
    run_timeout_s: int
    token_budget: int


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _split_hash(split_path: Path = DEFAULT_SPLIT_PATH) -> str:
    if not split_path.exists():
        return "unknown"
    return hashlib.sha256(split_path.read_bytes()).hexdigest()


def build_manifest(
    *,
    run_name: str,
    split: str,
    settings: "Settings",
    concurrency: int,
    token_budget: int,
    git_sha: str | None = None,
    split_path: Path = DEFAULT_SPLIT_PATH,
) -> Manifest:
    return Manifest(
        run_name=run_name,
        split=split,
        date=datetime.now(UTC).isoformat(),
        git_sha=git_sha if git_sha is not None else _git_sha(),
        prompt_version=settings.sa_prompt_version,
        provider=settings.sa_llm_provider,
        model=settings.sa_llm_model or "",
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        max_tokens=settings.llm_max_tokens,
        reasoning_effort=settings.llm_reasoning_effort,
        llm_timeout_s=settings.llm_timeout_s,
        sandbox_image_pins=list(PINNED_PACKAGES),
        dabench_revision=PINNED_REVISION,
        split_hash=_split_hash(split_path),
        concurrency=concurrency,
        run_timeout_s=settings.run_timeout_s,
        token_budget=token_budget,
    )


def write_manifest(manifest: Manifest, run_dir: Path) -> Path:
    path = run_dir / "manifest.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True), encoding="utf-8")
    return path


# ---- orchestration ----


@dataclass(frozen=True)
class HarnessOutcome:
    run_name: str
    run_dir: Path
    total: int
    n_done: int
    n_answered: int
    n_infra_errors: int
    n_remaining: int
    stopped_clean: bool
    stop_reason: str | None
    resume_command: str | None


def _resume_command(
    split: str, run_name: str, concurrency: int, limit: int | None, token_budget: int
) -> str:
    parts = [
        "uv run sa eval",
        f"--split {split}",
        f"--run-name {run_name}",
        f"--concurrency {concurrency}",
        f"--token-budget {token_budget}",
    ]
    if limit is not None:
        parts.append(f"--limit {limit}")
    return " ".join(parts)


@dataclass
class _Totals:
    tokens_used: int = 0
    infra_streak: int = 0
    stop_reason: str | None = None


def run_eval(
    *,
    split: str,
    run_name: str,
    settings: "Settings",
    concurrency: int = 6,
    limit: int | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    final_held_out_run: bool = False,
    run_dir: Path | None = None,
    questions: list[Question] | None = None,
    csv_loader: Callable[[Question], bytes] | None = None,
    llm: LLMClient | None = None,
    sandbox_factory: Callable[[Question], Sandbox] | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    clock: Callable[[], float] = time.monotonic,
) -> HarnessOutcome:
    """Run `split`'s questions through a thread pool, resumably. See module docstring."""
    if questions is None:
        questions = load_questions_for_split(split, final_held_out_run)
    if limit is not None:
        questions = questions[:limit]

    run_dir = run_dir or (DEFAULT_EVAL_DIR / run_name)
    writer = ResultsWriter(run_dir / "results.jsonl")
    latest = writer.load_latest()
    skip_ids = done_ids(latest)
    pending = [q for q in questions if q.id not in skip_ids]

    write_manifest(
        build_manifest(
            run_name=run_name,
            split=split,
            settings=settings,
            concurrency=concurrency,
            token_budget=token_budget,
        ),
        run_dir,
    )

    shared_llm = llm if llm is not None else make_llm(settings)
    build_sandbox = (
        sandbox_factory if sandbox_factory is not None else (lambda q: make_sandbox(settings))
    )
    load_csv = (
        csv_loader
        if csv_loader is not None
        else (lambda q: (DEFAULT_TABLES_DIR / q.file_name).read_bytes())
    )

    totals = _Totals(
        tokens_used=sum(
            row.get("prompt_tokens", 0) + row.get("completion_tokens", 0) for row in latest.values()
        )
    )

    def worker(question: Question) -> QuestionResult:
        csv_bytes = load_csv(question)
        sandbox = build_sandbox(question)
        return run_one_question(question, csv_bytes, shared_llm, sandbox, settings, clock=clock)

    pending_iter = iter(pending)
    in_flight: dict[Future, Question] = {}

    def submit_next(pool: ThreadPoolExecutor) -> bool:
        nxt = next(pending_iter, None)
        if nxt is None:
            return False
        in_flight[pool.submit(worker, nxt)] = nxt
        return True

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for _ in range(concurrency):
            if not submit_next(pool):
                break

        while in_flight:
            done_futures, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for fut in done_futures:
                in_flight.pop(fut)
                result = fut.result()
                writer.append(result)

                totals.tokens_used += result.prompt_tokens + result.completion_tokens
                if result.status == "infra_error":
                    totals.infra_streak += 1
                else:
                    totals.infra_streak = 0

                if totals.stop_reason is None:
                    if totals.tokens_used >= token_budget:
                        totals.stop_reason = "token_budget"
                    elif totals.infra_streak >= CONSECUTIVE_INFRA_ERROR_LIMIT:
                        totals.stop_reason = "consecutive_infra_errors"
                    elif ledger_total_usd(ledger_path) >= settings.sa_sandbox_budget_usd:
                        totals.stop_reason = "sandbox_budget"

            if totals.stop_reason is None:
                for _ in range(len(done_futures)):
                    if not submit_next(pool):
                        break

    final_latest = writer.load_latest()
    n_answered = sum(1 for row in final_latest.values() if row["status"] == "answered")
    n_infra = sum(1 for row in final_latest.values() if row["status"] == "infra_error")
    n_done_non_infra = len(done_ids(final_latest))
    n_remaining = len(questions) - n_done_non_infra

    stopped_clean = totals.stop_reason is not None
    return HarnessOutcome(
        run_name=run_name,
        run_dir=run_dir,
        total=len(questions),
        n_done=len(final_latest),
        n_answered=n_answered,
        n_infra_errors=n_infra,
        n_remaining=n_remaining,
        stopped_clean=stopped_clean,
        stop_reason=totals.stop_reason,
        resume_command=(
            _resume_command(split, run_name, concurrency, limit, token_budget)
            if stopped_clean
            else None
        ),
    )
