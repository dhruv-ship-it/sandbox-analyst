"""The `sa` command-line entry point: `sa ask` and `sa dabench-smoke`.

`dabench-smoke` only ever loads the DEV split (`load_dev_questions`
below never calls `load_split("test")`) -- it structurally cannot touch
the held-out test split, per CLAUDE.md's test-set-discipline rule. It is
a human-eyeball smoke check, not a grader: it prints predicted vs. label
answer tags side by side and leaves scoring to a later task.
"""

import argparse
import logging
import random
import sys
from pathlib import Path

from sandbox_analyst.agent import TraceWriter, run_agent
from sandbox_analyst.agent.events import AgentEvent
from sandbox_analyst.bench.dabench import Question, load_labels, load_questions
from sandbox_analyst.bench.harness import DEFAULT_TOKEN_BUDGET, HeldOutRunRequired, run_eval
from sandbox_analyst.bench.report import write_report
from sandbox_analyst.bench.split import DEFAULT_QUESTIONS_PATH, SplitLockedError, load_split
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import LLMConfigError, make_llm
from sandbox_analyst.llm.usage import DEFAULT_USAGE_LOG_PATH
from sandbox_analyst.redteam import run_redteam
from sandbox_analyst.replay import run_record_replay, scan_cassette_files
from sandbox_analyst.sandbox import make_sandbox

LEVEL_ORDER = ["easy", "medium", "hard"]
DEFAULT_LABELS_PATH = Path("data/dabench/da-dev-labels.jsonl")
DEFAULT_TABLES_DIR = Path("data/dabench/da-dev-tables")


class _LazyTraceWriter:
    """An on_event subscriber that writes a trace, keyed by the run_id in the first event."""

    def __init__(self) -> None:
        self._writer: TraceWriter | None = None

    @property
    def path(self) -> Path | None:
        return self._writer.path if self._writer is not None else None

    def __call__(self, event: AgentEvent) -> None:
        if self._writer is None:
            self._writer = TraceWriter(event.run_id)
        self._writer(event)


class _TracingPrinter(_LazyTraceWriter):
    """Writes the trace AND prints a readable step-by-step timeline as events arrive."""

    def __call__(self, event: AgentEvent) -> None:
        super().__call__(event)
        _print_event(event)


def _print_event(event: AgentEvent) -> None:
    p = event.payload
    if event.type == "run_started":
        print(f"run {event.run_id} ({p['prompt_version']}): {p['question']}")  # noqa: T201
    elif event.type == "code":
        code = p.get("code")
        if code is None:
            print(f"  attempt {event.attempt}: generate -> no code block found")  # noqa: T201
        else:
            n_lines = len(str(code).splitlines())
            print(f"  attempt {event.attempt}: generate -> {n_lines} line(s) of code")  # noqa: T201
    elif event.type == "static_check":
        status = "ok" if p["ok"] else f"FAILED ({len(p['violations'])} violation(s))"
        print(f"  attempt {event.attempt}: check -> {status}")  # noqa: T201
    elif event.type == "exec_result":
        print(f"  attempt {event.attempt}: exec -> {_exec_summary(p)}")  # noqa: T201
    elif event.type == "answer":
        names = ", ".join(a["name"] for a in p["answers"])
        print(f"  attempt {event.attempt}: answer -> {names}")  # noqa: T201
    elif event.type == "evidence":
        results = p["results"]
        n_passed = sum(1 for r in results if r["passed"])
        print(f"  attempt {event.attempt}: evidence -> {n_passed}/{len(results)} passed")  # noqa: T201
    elif event.type == "observation":
        first_line = str(p["text"]).splitlines()[0] if p.get("text") else ""
        print(f"  attempt {event.attempt}: observation -> {first_line}")  # noqa: T201
    elif event.type == "run_finished":
        print(f"run finished: status={p['status']}")  # noqa: T201


def _exec_summary(payload: dict) -> str:
    if payload.get("crashed"):
        return "CRASHED"
    if payload.get("unavailable"):
        return "UNAVAILABLE"
    if payload.get("timed_out"):
        return "TIMEOUT"
    error = payload.get("error")
    if error:
        return f"ERROR {error['name']}: {error['value']}"
    return f"ok ({payload.get('duration_ms', 0)}ms)"


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def cmd_ask(csv_path: str, question: str) -> int:
    settings = Settings()
    try:
        llm = make_llm(settings)
    except LLMConfigError as exc:
        print(f"LLM configuration error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    sandbox = make_sandbox(settings)
    path = Path(csv_path)
    csv_bytes = path.read_bytes()

    tracer = _TracingPrinter()
    result = run_agent(
        csv_bytes,
        path.name,
        question,
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=settings,
        on_event=tracer,
    )

    if result.status == "llm_error":
        print(file=sys.stderr)  # noqa: T201
        print("stopped: an external LLM service failure occurred.", file=sys.stderr)  # noqa: T201
        print(f"resume with: uv run sa ask {csv_path} {question!r}", file=sys.stderr)  # noqa: T201

    print()  # noqa: T201
    print(f"status: {result.status}")  # noqa: T201
    for answer in result.answers:
        print(f"  @{answer.name}[{answer.value}]")  # noqa: T201
    if result.explanation:
        print(f"explanation: {result.explanation}")  # noqa: T201
    print()  # noqa: T201
    print("code:")  # noqa: T201
    print(result.code)  # noqa: T201
    if result.images:
        print("images:")  # noqa: T201
        for image_path in result.images:
            print(f"  {image_path}")  # noqa: T201
    print(  # noqa: T201
        f"tokens: prompt={result.total_prompt_tokens} completion={result.total_completion_tokens} "
        f"latency_ms={result.total_latency_ms} sandbox_usd=${result.sandbox_usd:.4f}"
    )
    if tracer.path is not None:
        print(f"trace: {tracer.path}")  # noqa: T201

    return 0 if result.status == "answered" else 1


def _level_counts(n: int) -> dict[str, int]:
    """Spread n across LEVEL_ORDER as evenly as possible, extra items to earlier levels first."""
    base, remainder = divmod(n, len(LEVEL_ORDER))
    counts = {level: base for level in LEVEL_ORDER}
    for level in LEVEL_ORDER[:remainder]:
        counts[level] += 1
    return counts


def select_smoke_questions(questions: list[Question], n: int, seed: int) -> list[Question]:
    """Deterministically pick n questions with a seeded spread across difficulty levels."""
    counts = _level_counts(n)
    by_level: dict[str, list[Question]] = {level: [] for level in LEVEL_ORDER}
    for q in questions:
        if q.level in by_level:
            by_level[q.level].append(q)

    selected: list[Question] = []
    for level in LEVEL_ORDER:
        pool = sorted(by_level[level], key=lambda q: q.id)
        random.Random(seed).shuffle(pool)
        count = counts[level]
        if len(pool) < count:
            raise ValueError(f"not enough {level!r} dev questions: need {count}, have {len(pool)}")
        selected.extend(pool[:count])
    return selected


def load_dev_questions() -> list[Question]:
    """DEV-only, by construction: this never calls load_split("test")."""
    dev = load_split("dev")
    all_questions = load_questions(DEFAULT_QUESTIONS_PATH)
    dev_ids = set(dev["question_ids"])
    return [q for q in all_questions if q.id in dev_ids]


def cmd_dabench_smoke(n: int, seed: int) -> int:
    settings = Settings()
    try:
        llm = make_llm(settings)
    except LLMConfigError as exc:
        print(f"LLM configuration error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    dev_questions = load_dev_questions()
    selected = select_smoke_questions(dev_questions, n, seed)
    labels_by_id = {label.id: label for label in load_labels(DEFAULT_LABELS_PATH)}

    requests_before = _count_lines(DEFAULT_USAGE_LOG_PATH)

    print(f"{'id':>5}  {'level':<6} {'status':<16} {'attempts':>8}  predicted | label")  # noqa: T201
    token_totals: list[int] = []
    latency_totals: list[int] = []
    sandbox_usd_total = 0.0
    n_answered = 0

    for q in selected:
        csv_bytes = (DEFAULT_TABLES_DIR / q.file_name).read_bytes()
        sandbox = make_sandbox(settings)
        tracer = _LazyTraceWriter()
        result = run_agent(
            csv_bytes,
            q.file_name,
            q.question,
            llm=llm,
            sandbox_factory=lambda sb=sandbox: sb,
            settings=settings,
            on_event=tracer,
            constraints=q.constraints,
            answer_format=q.format,
        )

        predicted = " ".join(f"@{a.name}[{a.value}]" for a in result.answers) or "(none)"
        label = labels_by_id.get(q.id)
        expected = " ".join(f"@{name}[{value}]" for name, value in label.answers) if label else "?"
        print(  # noqa: T201
            f"{q.id:>5}  {q.level or '?':<6} {result.status:<16} {len(result.attempts):>8}  "
            f"{predicted} | {expected}"
        )

        if result.status == "answered":
            n_answered += 1
        token_totals.append(result.total_prompt_tokens + result.total_completion_tokens)
        latency_totals.append(result.total_latency_ms)
        sandbox_usd_total += result.sandbox_usd

    requests_after = _count_lines(DEFAULT_USAGE_LOG_PATH)
    mean_tokens = sum(token_totals) / len(token_totals) if token_totals else 0.0
    mean_latency = sum(latency_totals) / len(latency_totals) if latency_totals else 0.0

    print()  # noqa: T201
    print(  # noqa: T201
        f"answered {n_answered}/{len(selected)}  mean_tokens={mean_tokens:.0f}  "
        f"mean_latency_ms={mean_latency:.0f}  sandbox_usd=${sandbox_usd_total:.4f}  "
        f"llm_requests_used={requests_after - requests_before}"
    )
    return 0


def cmd_eval(
    split: str,
    run_name: str,
    concurrency: int,
    limit: int | None,
    token_budget: int,
    final_held_out_run: bool,
) -> int:
    settings = Settings()
    try:
        outcome = run_eval(
            split=split,
            run_name=run_name,
            settings=settings,
            concurrency=concurrency,
            limit=limit,
            token_budget=token_budget,
            final_held_out_run=final_held_out_run,
        )
    except (HeldOutRunRequired, SplitLockedError) as exc:
        print(f"refused: {exc}", file=sys.stderr)  # noqa: T201
        return 2

    print(  # noqa: T201
        f"run {outcome.run_name}: {outcome.n_done}/{outcome.total} done "
        f"({outcome.n_answered} answered, {outcome.n_infra_errors} infra_error, "
        f"{outcome.n_remaining} remaining)"
    )
    if outcome.stopped_clean:
        print(f"stopped cleanly: {outcome.stop_reason}", file=sys.stderr)  # noqa: T201
        print(f"resume with: {outcome.resume_command}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def cmd_report(run_names: list[str]) -> int:
    md_path, json_path, failure_paths = write_report(run_names)
    print(f"wrote {md_path}")  # noqa: T201
    print(f"wrote {json_path}")  # noqa: T201
    for path in failure_paths:
        print(f"wrote {path}")  # noqa: T201
    return 0


def cmd_redteam(run_name: str, concurrency: int) -> int:
    settings = Settings()
    outcome = run_redteam(run_name=run_name, settings=settings, concurrency=concurrency)
    overall = outcome.report["overall"]
    print(  # noqa: T201
        f"redteam {outcome.run_name}: handled {overall['handled']} of {overall['total']}"
    )
    for cat in ("A", "B", "C", "D"):
        block = outcome.report["categories"][cat]
        print(f"  category {cat}: handled {block['handled']} of {block['total']}")  # noqa: T201
    n_leaks = outcome.report["canary"]["n_leaks"]
    print(f"  canary leaks: {n_leaks}")  # noqa: T201
    print(f"wrote {outcome.md_path}")  # noqa: T201
    print(f"wrote {outcome.json_path}")  # noqa: T201
    return 1 if n_leaks > 0 else 0


def cmd_record_replay() -> int:
    """LIVE: record the replay regression cassettes (real LLM + real sandbox, costs money)."""
    settings = Settings()
    try:
        outcome = run_record_replay(settings=settings)
    except LLMConfigError as exc:
        print(f"LLM configuration error: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    leaks = scan_cassette_files([outcome.llm_cassette_path, outcome.sandbox_cassette_path])
    if leaks:
        print(  # noqa: T201
            "refusing: credential-shaped strings found in the recorded cassette(s):",
            file=sys.stderr,
        )
        for leak in leaks:
            print(f"  {leak}", file=sys.stderr)  # noqa: T201
        return 1

    for r in outcome.results:
        print(f"  {r.task_id}: status={r.status} attempts={r.n_attempts}")  # noqa: T201
    print(  # noqa: T201
        f"{outcome.n_needed_repair}/{len(outcome.results)} tasks needed at least one repair"
    )
    print(f"wrote {outcome.llm_cassette_path}")  # noqa: T201
    print(f"wrote {outcome.sandbox_cassette_path}")  # noqa: T201
    print(f"wrote {outcome.recorded_results_path}")  # noqa: T201
    return 0


def configure_app_logging() -> None:
    """Send this project's own loggers (`sandbox_analyst.*`) to stdout.

    Independent of uvicorn's own log config, which `uvicorn.run()` applies
    via `logging.config.dictConfig` after this is called -- that dict sets
    `disable_existing_loggers: False` and never names `sandbox_analyst`, so
    it cannot remove or disable the handler added here. uvicorn's own
    "default" handler goes to stderr; this one is explicitly stdout, which
    is the stream App Service's log stream is documented to follow.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app_logger = logging.getLogger("sandbox_analyst")
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)
    app_logger.propagate = False


def cmd_serve() -> int:
    """Run the public API with uvicorn, honoring Settings.port (the PORT env var)."""
    import uvicorn

    from sandbox_analyst.api import build_app

    configure_app_logging()
    settings = Settings()
    app = build_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sa", description="Sandbox Analyst CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="ask a question about a CSV file")
    ask_parser.add_argument("csv_path", help="path to a local CSV file")
    ask_parser.add_argument("question", help="the question to ask about the CSV")

    smoke_parser = subparsers.add_parser(
        "dabench-smoke",
        help="run a small DEV-split smoke check (never touches the held-out test split)",
    )
    smoke_parser.add_argument("--n", type=int, default=5, help="number of DEV questions to run")
    smoke_parser.add_argument(
        "--seed", type=int, default=2026, help="seed for deterministic question selection"
    )

    eval_parser = subparsers.add_parser(
        "eval", help="run the resumable evaluation harness over a DABench split"
    )
    eval_parser.add_argument("--split", choices=["dev", "test"], default="dev")
    eval_parser.add_argument("--run-name", required=True)
    eval_parser.add_argument("--concurrency", type=int, default=6)
    eval_parser.add_argument("--limit", type=int, default=None)
    eval_parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    eval_parser.add_argument(
        "--final-held-out-run",
        action="store_true",
        help="required (alongside a clean, frozen-*-tagged tree) to load --split test",
    )

    report_parser = subparsers.add_parser(
        "report", help="build a combined metrics report from one or more eval runs"
    )
    report_parser.add_argument("run_names", nargs="+", metavar="run-name")

    subparsers.add_parser("serve", help="run the public API (uvicorn, host 0.0.0.0, PORT env var)")

    redteam_parser = subparsers.add_parser(
        "redteam", help="run the red-team suite (categories A-D + layer isolation)"
    )
    redteam_parser.add_argument("--run-name", required=True)
    redteam_parser.add_argument("--concurrency", type=int, default=1)

    subparsers.add_parser(
        "record-replay",
        help="LIVE: record the replay regression cassettes (real LLM + real sandbox, costs money)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ask":
        return cmd_ask(args.csv_path, args.question)
    if args.command == "dabench-smoke":
        return cmd_dabench_smoke(args.n, args.seed)
    if args.command == "eval":
        return cmd_eval(
            args.split,
            args.run_name,
            args.concurrency,
            args.limit,
            args.token_budget,
            args.final_held_out_run,
        )
    if args.command == "report":
        return cmd_report(args.run_names)
    if args.command == "serve":
        return cmd_serve()
    if args.command == "redteam":
        return cmd_redteam(args.run_name, args.concurrency)
    if args.command == "record-replay":
        return cmd_record_replay()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
