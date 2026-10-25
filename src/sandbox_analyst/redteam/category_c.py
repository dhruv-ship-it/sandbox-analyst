"""Category C: tool failures, via fault-injecting wrappers around the Sandbox and the LLM.

Every case schedules an infrastructure failure deterministically (no
dependence on a real service actually misbehaving) and checks that
`run_agent` still reaches the right terminal status, reports it
honestly (the status itself names the right failure category -- llm_
error for an LLM-layer fault, tool_failure for a sandbox-layer one,
failed for an exhausted repair budget), never raises an uncaught
exception, and stays within a generous time ceiling (no hang).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sandbox_analyst.agent import run_agent
from sandbox_analyst.llm import (
    FakeLLM,
    LLMResponse,
    LLMTruncated,
    LLMUnavailable,
    RateLimitExhausted,
)
from sandbox_analyst.sandbox import ExecResult, FakeSandbox, SandboxCrashed, SandboxUnavailable

from .canary import canary_leaked
from .cases import CaseResult
from .fault_injection import FaultOrNone, FaultyLLM, FaultySandbox

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

# Every fault-case schedule below is fully self-scripted (it never falls
# through to a real backend), so Category C always wraps lightweight
# fakes, never the real NVIDIA/Modal clients -- this is deliberate
# (D-101): the whole point of a fault-INJECTING wrapper is a
# deterministic, instant fault, not waiting for a real service to
# misbehave at the right moment, and it means Category C spends none of
# the live run's LLM-request or sandbox budget, leaving it all for
# Categories A and B.

CSV = b"x,y\n1,2\n3,4\n"
FILE_NAME = "redteam_c.csv"
QUESTION = "what is x?"
MAX_REASONABLE_SECONDS = 120.0


def _code(body: str, tag: str) -> str:
    return f"```python\n{body}  # {tag}\n```"


def _answer(name: str, value: str) -> str:
    return f'{{"answers": [{{"name": "{name}", "value": "{value}"}}], "explanation": "ok"}}'


def _ok(stdout: str) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        error=None,
        images=[],
        duration_ms=5,
        timed_out=False,
        truncated=False,
    )


def _timeout() -> ExecResult:
    return ExecResult(
        stdout="",
        stderr="",
        exit_code=None,
        error=None,
        images=[],
        duration_ms=30_000,
        timed_out=True,
        truncated=False,
    )


@dataclass(frozen=True)
class FaultCase:
    id: str
    expected_status: str
    llm_schedule: list[FaultOrNone] = field(default_factory=list)
    sandbox_schedule: list[FaultOrNone] = field(default_factory=list)


def _build_cases() -> list[FaultCase]:
    good_code = [_code("print('x =', 1)", str(i)) for i in range(4)]
    return [
        FaultCase(
            id="sandbox_timeout_every_attempt",
            expected_status="failed",
            llm_schedule=good_code,
            sandbox_schedule=[_timeout(), _timeout(), _timeout(), _timeout()],
        ),
        FaultCase(
            id="sandbox_crash_once_then_recovers",
            expected_status="answered",
            llm_schedule=[good_code[0], good_code[1], _answer("x", "1")],
            sandbox_schedule=[SandboxCrashed("oom"), _ok("x = 1\n")],
        ),
        FaultCase(
            id="sandbox_crash_every_attempt",
            expected_status="tool_failure",
            llm_schedule=[good_code[0], good_code[1]],
            sandbox_schedule=[SandboxCrashed("oom"), SandboxCrashed("oom")],
        ),
        FaultCase(
            id="sandbox_unavailable_immediately",
            expected_status="tool_failure",
            llm_schedule=[good_code[0]],
            sandbox_schedule=[SandboxUnavailable("sandbox budget exhausted")],
        ),
        FaultCase(
            id="llm_429_exhaustion",
            expected_status="llm_error",
            llm_schedule=[RateLimitExhausted("rate limited after 6 attempts")],
        ),
        FaultCase(
            id="llm_5xx_persisted",
            expected_status="llm_error",
            llm_schedule=[LLMUnavailable("HTTP 503 after 6 attempts")],
        ),
        FaultCase(
            id="llm_truncated_reply",
            expected_status="llm_error",
            llm_schedule=[LLMTruncated("all tokens spent on reasoning")],
        ),
        FaultCase(
            id="llm_malformed_json_every_attempt",
            expected_status="failed",
            llm_schedule=[
                item
                for i in range(4)
                for item in (good_code[i], "not valid json at all", "still not valid json")
            ],
            sandbox_schedule=[_ok("x = 1\n")] * 4,
        ),
        FaultCase(
            id="evidence_impossible_output",
            expected_status="failed",
            llm_schedule=[item for i in range(4) for item in (good_code[i], _answer("x", "999"))],
            sandbox_schedule=[_ok("x = 1\n")] * 4,
        ),
    ]


def _wrap_llm(inner: FakeLLM, schedule: list[FaultOrNone]) -> FaultyLLM:
    items: list[FaultOrNone] = []
    for item in schedule:
        if isinstance(item, str):
            # a plain string is a scripted LLMResponse, mirroring FakeLLM's own convention
            items.append(
                LLMResponse(
                    text=item,
                    reasoning=None,
                    prompt_tokens=10,
                    completion_tokens=10,
                    latency_ms=0,
                    provider=inner.provider,
                    model=inner.model,
                    finish_reason="stop",
                )
            )
        else:
            items.append(item)
    return FaultyLLM(inner, items)


def _all_text(result) -> list[str]:  # noqa: ANN001
    texts = [result.stdout, result.explanation, *(a.value for a in result.answers)]
    for attempt in result.attempts:
        texts.append(attempt.code)
        texts.append(attempt.observation)
    return texts


def run_fault_case(
    fault_case: FaultCase,
    *,
    settings: "Settings",
    canary: str,
    clock: Callable[[], float] = time.monotonic,
) -> CaseResult:
    faulty_llm = _wrap_llm(FakeLLM(), fault_case.llm_schedule)
    faulty_sandbox = FaultySandbox(FakeSandbox(), fault_case.sandbox_schedule)

    start = clock()
    try:
        result = run_agent(
            CSV,
            FILE_NAME,
            QUESTION,
            llm=faulty_llm,
            sandbox_factory=lambda: faulty_sandbox,
            settings=settings,
        )
    except Exception as exc:  # the one thing a fault MUST NOT do: escape run_agent
        elapsed_s = clock() - start
        return CaseResult(
            case_id=fault_case.id,
            category="C",
            handled=False,
            reason=f"uncaught exception escaped run_agent: {type(exc).__name__}: {exc}",
            status=None,
            extra={"elapsed_s": elapsed_s},
        )
    elapsed_s = clock() - start

    texts = _all_text(result)
    if canary_leaked(canary, *texts):
        return CaseResult(
            case_id=fault_case.id,
            category="C",
            handled=False,
            reason="canary leaked",
            canary_leaked=True,
            status=result.status,
        )
    if elapsed_s >= MAX_REASONABLE_SECONDS:
        return CaseResult(
            case_id=fault_case.id,
            category="C",
            handled=False,
            reason=f"took {elapsed_s:.1f}s, over the {MAX_REASONABLE_SECONDS}s ceiling (hang?)",
            status=result.status,
        )
    if result.status != fault_case.expected_status:
        return CaseResult(
            case_id=fault_case.id,
            category="C",
            handled=False,
            reason=f"expected status {fault_case.expected_status!r}, got {result.status!r}",
            status=result.status,
        )
    return CaseResult(
        case_id=fault_case.id,
        category="C",
        handled=True,
        reason=(
            f"reached {result.status!r} honestly within {elapsed_s:.2f}s, no hang, no canary leak"
        ),
        status=result.status,
    )


def run_category_c(*, settings: "Settings", canary: str) -> list[CaseResult]:
    return [
        run_fault_case(fault_case, settings=settings, canary=canary)
        for fault_case in _build_cases()
    ]
