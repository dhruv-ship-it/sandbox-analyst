"""The agent loop: write -> check -> run -> answer -> evidence-check -> repair.

One ATTEMPT = one code generation. `run_agent` runs at most `MAX_ATTEMPTS`
of them in a single sandbox (uploaded once, run repeatedly -- see D-006:
freshness-per-run already happens inside a real backend's own `run()`),
emitting one `AgentEvent` per step through `on_event`. The TraceWriter (or
any other subscriber) is attached by the caller, not here.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from sandbox_analyst.guard import Violation, check
from sandbox_analyst.llm import (
    LLMClient,
    LLMConfigError,
    LLMResponse,
    LLMUnavailable,
    Message,
    RateLimitExhausted,
)
from sandbox_analyst.sandbox import (
    ExecError,
    ExecResult,
    Sandbox,
    SandboxCrashed,
    SandboxUnavailable,
)

from . import prompts
from .answer import AnswerItem, AnswerParseError, FinalAnswer, parse_final_answer
from .codeparse import extract_code
from .events import EventEmitter, OnEvent, new_run_id
from .evidence import EvidenceResult, all_evidenced, check_evidence
from .profile import profile_csv, to_prompt_text

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

MAX_ATTEMPTS = 4
TOKEN_BUDGET = 60_000
TIME_BUDGET_S = 300.0
DEFAULT_ARTIFACTS_DIR = Path("runs/artifacts")

_NUMBER_NORM_RE = re.compile(r"\d+(?:\.\d+)?")
_QUOTE_NORM_RE = re.compile(r"(['\"]).*?\1")


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    code: str | None
    check_ok: bool | None
    check_violations: tuple[Violation, ...]
    exec_result: ExecResult | None
    observation: str | None
    answer: FinalAnswer | None
    evidence: tuple[EvidenceResult, ...]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    status: str
    answers: list[AnswerItem]
    explanation: str
    code: str
    stdout: str
    images: list[str]
    evidence: list[EvidenceResult]
    attempts: list[AttemptRecord]
    total_prompt_tokens: int
    total_completion_tokens: int
    total_latency_ms: int
    sandbox_usd: float


class _StopRun(Exception):
    """Raised internally to end the attempt loop; always caught in `run_agent`."""

    def __init__(
        self,
        status: str,
        *,
        final: FinalAnswer | None = None,
        exec_result: ExecResult | None = None,
        code: str | None = None,
        evidence_results: tuple[EvidenceResult, ...] = (),
        image_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(status)
        self.status = status
        self.final = final
        self.exec_result = exec_result
        self.code = code
        self.evidence_results = evidence_results
        self.image_paths = image_paths


@dataclass
class _RunState:
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_latency_ms: int = 0
    total_sandbox_usd: float = 0.0
    seen_codes: set[str] = field(default_factory=set)
    last_exec_error_signature: str | None = None
    consecutive_crashes: int = 0
    attempts: list[AttemptRecord] = field(default_factory=list)

    def add_llm_usage(self, response: LLMResponse) -> None:
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        self.total_latency_ms += response.latency_ms


def _error_signature(name: str, value: str) -> str:
    normalized = _QUOTE_NORM_RE.sub("<str>", value)
    normalized = _NUMBER_NORM_RE.sub("<num>", normalized)
    return f"{name}:{normalized}"


def _check_token_budget(state: _RunState) -> None:
    if state.total_prompt_tokens + state.total_completion_tokens >= TOKEN_BUDGET:
        raise _StopRun("budget_exceeded")


def _write_artifacts(run_id: str, attempt_n: int, images: list[bytes]) -> list[str]:
    if not images:
        return []
    run_dir = DEFAULT_ARTIFACTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, data in enumerate(images):
        path = run_dir / f"attempt{attempt_n}_{i}.png"
        path.write_bytes(data)
        paths.append(str(path))
    return paths


def _violation_payload(v: Violation) -> dict[str, object]:
    return {"rule_id": v.rule_id, "line": v.line, "col": v.col, "message": v.message}


def _exec_error_payload(error: ExecError) -> dict[str, object]:
    return {"name": error.name, "value": error.value, "traceback": error.traceback}


def _exec_result_payload(result: ExecResult, image_paths: list[str]) -> dict[str, object]:
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "error": None if result.error is None else _exec_error_payload(result.error),
        "images": image_paths,
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
        "truncated": result.truncated,
    }


def _answer_payload(final: FinalAnswer) -> dict[str, object]:
    return {
        "answers": [{"name": a.name, "value": a.value} for a in final.answers],
        "explanation": final.explanation,
    }


def _evidence_payload(results: list[EvidenceResult]) -> dict[str, object]:
    return {
        "results": [
            {"name": r.name, "value": r.value, "passed": r.passed, "reason": r.reason}
            for r in results
        ]
    }


def _messages_payload(messages: list[Message]) -> dict[str, object]:
    return {"messages": [{"role": m.role, "content": m.content} for m in messages]}


def _response_payload(response: LLMResponse) -> dict[str, object]:
    return {
        "text": response.text,
        "reasoning": response.reasoning,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "latency_ms": response.latency_ms,
        "finish_reason": response.finish_reason,
    }


def _make_attempt_record(
    attempt_n: int,
    code: str | None,
    response: LLMResponse,
    *,
    check_ok: bool | None = None,
    check_violations: tuple[Violation, ...] = (),
    exec_result: ExecResult | None = None,
    observation_text: str | None,
    answer: FinalAnswer | None = None,
    evidence: tuple[EvidenceResult, ...] = (),
) -> AttemptRecord:
    return AttemptRecord(
        attempt=attempt_n,
        code=code,
        check_ok=check_ok,
        check_violations=check_violations,
        exec_result=exec_result,
        observation=observation_text,
        answer=answer,
        evidence=evidence,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        latency_ms=response.latency_ms,
    )


def _call_llm(
    llm: LLMClient, messages: list[Message], emitter: EventEmitter, attempt_n: int
) -> LLMResponse:
    emitter.emit("llm_request", attempt_n, _messages_payload(messages))
    try:
        response = llm.complete(messages)
    except (RateLimitExhausted, LLMUnavailable, LLMConfigError) as exc:
        emitter.emit("observation", attempt_n, {"text": f"llm_error: {exc}"})
        raise _StopRun("llm_error") from exc
    emitter.emit("llm_response", attempt_n, _response_payload(response))
    return response


def _run_answer_step(
    llm: LLMClient,
    question: str,
    code: str,
    stdout: str,
    constraints: str | None,
    answer_format: str | None,
    emitter: EventEmitter,
    attempt_n: int,
    state: _RunState,
) -> FinalAnswer | None:
    answer_messages = [
        Message("system", prompts.ANSWER_SYSTEM_PROMPT),
        Message(
            "user",
            prompts.build_answer_message(
                question, code, stdout, constraints=constraints, answer_format=answer_format
            ),
        ),
    ]
    response = _call_llm(llm, answer_messages, emitter, attempt_n)
    state.add_llm_usage(response)
    _check_token_budget(state)

    try:
        return parse_final_answer(response.text, answer_format)
    except AnswerParseError as exc:
        retry_messages = [
            Message("system", prompts.ANSWER_SYSTEM_PROMPT),
            Message("user", prompts.build_answer_retry_message(response.text, str(exc))),
        ]
        retry_response = _call_llm(llm, retry_messages, emitter, attempt_n)
        state.add_llm_usage(retry_response)
        _check_token_budget(state)
        try:
            return parse_final_answer(retry_response.text, answer_format)
        except AnswerParseError:
            return None


def _run_attempts(
    *,
    run_id: str,
    preview_text: str,
    question: str,
    constraints: str | None,
    answer_format: str | None,
    file_name: str,
    llm: LLMClient,
    sandbox: Sandbox,
    settings: "Settings",
    emitter: EventEmitter,
    clock: Callable[[], float],
    start_time: float,
    state: _RunState,
) -> NoReturn:
    previous_code: str | None = None
    observation: str | None = None

    for attempt_n in range(1, MAX_ATTEMPTS + 1):
        if clock() - start_time >= TIME_BUDGET_S:
            raise _StopRun("budget_exceeded")
        _check_token_budget(state)

        if attempt_n == 1:
            user_text = prompts.build_user_message(
                preview_text, question, constraints=constraints, answer_format=answer_format
            )
        else:
            user_text = prompts.build_repair_message(previous_code, observation or "")

        messages = [
            Message("system", prompts.code_system_prompt(file_name)),
            Message("user", user_text),
        ]
        response = _call_llm(llm, messages, emitter, attempt_n)
        state.add_llm_usage(response)
        _check_token_budget(state)

        code = extract_code(response.text)
        emitter.emit("code", attempt_n, {"code": code})

        if code is None:
            observation = prompts.observation_no_code_block()
            previous_code = None
            state.consecutive_crashes = 0
            state.last_exec_error_signature = None
            state.attempts.append(
                _make_attempt_record(attempt_n, code, response, observation_text=observation)
            )
            emitter.emit("observation", attempt_n, {"text": observation})
            continue

        if code in state.seen_codes:
            state.attempts.append(
                _make_attempt_record(
                    attempt_n,
                    code,
                    response,
                    observation_text="repeated_failure: identical code resubmitted",
                )
            )
            raise _StopRun("repeated_failure", code=code)
        state.seen_codes.add(code)

        check_result = check(code)
        emitter.emit(
            "static_check",
            attempt_n,
            {
                "ok": check_result.ok,
                "violations": [_violation_payload(v) for v in check_result.violations],
            },
        )
        if not check_result.ok:
            observation = prompts.observation_for_checker_violations(check_result.violations)
            previous_code = code
            state.consecutive_crashes = 0
            state.last_exec_error_signature = None
            state.attempts.append(
                _make_attempt_record(
                    attempt_n,
                    code,
                    response,
                    check_ok=False,
                    check_violations=tuple(check_result.violations),
                    observation_text=observation,
                )
            )
            emitter.emit("observation", attempt_n, {"text": observation})
            continue

        emitter.emit("exec_started", attempt_n, {"timeout_s": settings.run_timeout_s})
        try:
            exec_result = sandbox.run(code, timeout_s=settings.run_timeout_s)
        except SandboxCrashed as exc:
            state.consecutive_crashes += 1
            state.last_exec_error_signature = None
            state.total_sandbox_usd += sandbox.last_run_cost_usd
            emitter.emit("exec_result", attempt_n, {"crashed": True, "error": str(exc)})
            observation = prompts.observation_for_crash()
            if state.consecutive_crashes >= 2:
                state.attempts.append(
                    _make_attempt_record(
                        attempt_n, code, response, check_ok=True, observation_text=observation
                    )
                )
                raise _StopRun("tool_failure", code=code) from exc
            previous_code = code
            state.attempts.append(
                _make_attempt_record(
                    attempt_n, code, response, check_ok=True, observation_text=observation
                )
            )
            emitter.emit("observation", attempt_n, {"text": observation})
            continue
        except SandboxUnavailable as exc:
            emitter.emit("exec_result", attempt_n, {"unavailable": True, "error": str(exc)})
            state.attempts.append(
                _make_attempt_record(
                    attempt_n, code, response, check_ok=True, observation_text=str(exc)
                )
            )
            raise _StopRun("tool_failure", code=code) from exc

        state.consecutive_crashes = 0
        image_paths = _write_artifacts(run_id, attempt_n, exec_result.images)
        state.total_sandbox_usd += sandbox.last_run_cost_usd
        emitter.emit("exec_result", attempt_n, _exec_result_payload(exec_result, image_paths))

        if exec_result.timed_out:
            observation = prompts.observation_for_timeout()
            previous_code = code
            state.last_exec_error_signature = None
            state.attempts.append(
                _make_attempt_record(
                    attempt_n,
                    code,
                    response,
                    check_ok=True,
                    exec_result=exec_result,
                    observation_text=observation,
                )
            )
            emitter.emit("observation", attempt_n, {"text": observation})
            continue

        if exec_result.error is not None:
            error = exec_result.error
            signature = _error_signature(error.name, error.value)
            observation = prompts.observation_for_exec_error(error, exec_result.stdout)
            state.attempts.append(
                _make_attempt_record(
                    attempt_n,
                    code,
                    response,
                    check_ok=True,
                    exec_result=exec_result,
                    observation_text=observation,
                )
            )
            if signature == state.last_exec_error_signature:
                raise _StopRun("repeated_failure", code=code, exec_result=exec_result)
            state.last_exec_error_signature = signature
            previous_code = code
            emitter.emit("observation", attempt_n, {"text": observation})
            continue

        state.last_exec_error_signature = None
        final = _run_answer_step(
            llm,
            question,
            code,
            exec_result.stdout,
            constraints,
            answer_format,
            emitter,
            attempt_n,
            state,
        )

        if final is None:
            observation = "the answer step failed to produce valid JSON even after a retry"
            previous_code = code
            state.attempts.append(
                _make_attempt_record(
                    attempt_n,
                    code,
                    response,
                    check_ok=True,
                    exec_result=exec_result,
                    observation_text=observation,
                )
            )
            emitter.emit("observation", attempt_n, {"text": observation})
            continue

        emitter.emit("answer", attempt_n, _answer_payload(final))
        evidence_results = check_evidence(final.answers, exec_result.stdout)
        emitter.emit("evidence", attempt_n, _evidence_payload(evidence_results))
        state.attempts.append(
            _make_attempt_record(
                attempt_n,
                code,
                response,
                check_ok=True,
                exec_result=exec_result,
                observation_text=None,
                answer=final,
                evidence=tuple(evidence_results),
            )
        )

        if all_evidenced(evidence_results):
            raise _StopRun(
                "answered",
                final=final,
                exec_result=exec_result,
                code=code,
                evidence_results=tuple(evidence_results),
                image_paths=tuple(image_paths),
            )

        observation = prompts.observation_for_evidence_failure(evidence_results)
        previous_code = code
        emitter.emit("observation", attempt_n, {"text": observation})
        if attempt_n == MAX_ATTEMPTS:
            raise _StopRun(
                "failed",
                final=final,
                exec_result=exec_result,
                code=code,
                evidence_results=tuple(evidence_results),
                image_paths=tuple(image_paths),
            )

    raise _StopRun("failed")


def run_agent(
    csv_bytes: bytes,
    file_name: str,
    question: str,
    *,
    llm: LLMClient,
    sandbox_factory: Callable[[], Sandbox],
    settings: "Settings",
    on_event: OnEvent | None = None,
    constraints: str | None = None,
    answer_format: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AgentResult:
    """Run the write -> check -> run -> answer -> evidence-check loop for one question.

    `sandbox_factory` is called once; the returned sandbox is used as a
    context manager for the whole run (the CSV is uploaded once, then
    `.run()` is called once per attempt -- a real backend's `run()`
    already spins up and tears down a fresh sandbox internally, see D-006).
    """
    run_id = new_run_id()
    emitter = EventEmitter(run_id, on_event)
    start_time = clock()

    emitter.emit(
        "run_started",
        0,
        {
            "prompt_version": prompts.PROMPT_VERSION,
            "file_name": file_name,
            "question": question,
            "constraints": constraints,
            "answer_format": answer_format,
        },
    )

    profile = profile_csv(csv_bytes, file_name)
    preview_text = to_prompt_text(profile)
    emitter.emit(
        "profile",
        0,
        {"file_name": file_name, "n_rows": profile.n_rows, "n_cols": profile.n_cols},
    )

    state = _RunState()
    sandbox = sandbox_factory()

    with sandbox:
        sandbox.upload(file_name, csv_bytes)
        try:
            _run_attempts(
                run_id=run_id,
                preview_text=preview_text,
                question=question,
                constraints=constraints,
                answer_format=answer_format,
                file_name=file_name,
                llm=llm,
                sandbox=sandbox,
                settings=settings,
                emitter=emitter,
                clock=clock,
                start_time=start_time,
                state=state,
            )
        except _StopRun as exc:
            stop = exc

    answers = stop.final.answers if stop.final is not None else []
    explanation = stop.final.explanation if stop.final is not None else ""
    code = stop.code or ""
    stdout = stop.exec_result.stdout if stop.exec_result is not None else ""
    images = list(stop.image_paths)
    evidence_results = list(stop.evidence_results)

    emitter.emit(
        "run_finished",
        MAX_ATTEMPTS,
        {
            "status": stop.status,
            "total_prompt_tokens": state.total_prompt_tokens,
            "total_completion_tokens": state.total_completion_tokens,
            "total_latency_ms": state.total_latency_ms,
            "sandbox_usd": state.total_sandbox_usd,
        },
    )

    return AgentResult(
        run_id=run_id,
        status=stop.status,
        answers=answers,
        explanation=explanation,
        code=code,
        stdout=stdout,
        images=images,
        evidence=evidence_results,
        attempts=state.attempts,
        total_prompt_tokens=state.total_prompt_tokens,
        total_completion_tokens=state.total_completion_tokens,
        total_latency_ms=state.total_latency_ms,
        sandbox_usd=state.total_sandbox_usd,
    )
