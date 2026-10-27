from pathlib import Path

from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM, LLMResponse
from sandbox_analyst.redteam.canary import generate_canary
from sandbox_analyst.redteam.category_c import run_category_c
from sandbox_analyst.redteam.fault_injection import FaultyLLM, FaultySandbox
from sandbox_analyst.sandbox import FakeSandbox
from sandbox_analyst.sandbox.base import ExecResult


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        reasoning=None,
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=0,
        provider="fake",
        model="fake-model",
        finish_reason="stop",
    )


# ---- FaultyLLM / FaultySandbox wrappers, in isolation ----


def test_faulty_llm_raises_a_scheduled_exception_then_delegates_to_inner():
    inner = FakeLLM([_response("from inner")])
    faulty = FaultyLLM(inner, [RuntimeError("boom")])
    try:
        faulty.complete([])
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")
    assert faulty.complete([]).text == "from inner"


def test_faulty_llm_returns_a_scheduled_response_without_touching_inner():
    inner = FakeLLM([])  # empty queue -- would raise if ever actually called
    faulty = FaultyLLM(inner, [_response("scripted")])
    assert faulty.complete([]).text == "scripted"


def test_faulty_sandbox_raises_a_scheduled_exception_then_delegates_to_inner():
    ok = ExecResult(
        stdout="ok\n",
        stderr="",
        exit_code=0,
        error=None,
        images=[],
        duration_ms=1,
        timed_out=False,
        truncated=False,
    )
    inner = FakeSandbox([ok])
    faulty = FaultySandbox(inner, [RuntimeError("sandbox boom")])
    try:
        faulty.run("print(1)")
    except RuntimeError as exc:
        assert str(exc) == "sandbox boom"
    else:
        raise AssertionError("expected RuntimeError")
    assert faulty.run("print(1)").stdout == "ok\n"


# ---- the 9 built-in fault cases, end to end ----


def _result_for(results, case_id: str):
    return next(r for r in results if r.case_id == case_id)


def test_at_least_8_category_c_cases():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    assert len(results) >= 8


def test_sandbox_timeout_every_attempt_fails_cleanly_not_a_hang():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "sandbox_timeout_every_attempt")
    assert result.handled
    assert result.status == "failed"


def test_sandbox_crash_once_then_recovers_still_answers():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "sandbox_crash_once_then_recovers")
    assert result.handled
    assert result.status == "answered"


def test_sandbox_crash_every_attempt_is_tool_failure():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "sandbox_crash_every_attempt")
    assert result.handled
    assert result.status == "tool_failure"


def test_sandbox_unavailable_immediately_is_tool_failure():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "sandbox_unavailable_immediately")
    assert result.handled
    assert result.status == "tool_failure"


def test_llm_429_exhaustion_is_llm_error():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "llm_429_exhaustion")
    assert result.handled
    assert result.status == "llm_error"


def test_llm_5xx_persisted_is_llm_error():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "llm_5xx_persisted")
    assert result.handled
    assert result.status == "llm_error"


def test_llm_truncated_reply_is_llm_error_not_an_uncaught_crash():
    # This is exactly the gap found and fixed in agent/loop.py this session
    # (LLMTruncated wasn't in _call_llm's caught exception tuple).
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "llm_truncated_reply")
    assert result.handled
    assert result.status == "llm_error"


def test_llm_malformed_json_every_attempt_fails_cleanly():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "llm_malformed_json_every_attempt")
    assert result.handled
    assert result.status == "failed"


def test_evidence_impossible_output_fails_cleanly():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    result = _result_for(results, "evidence_impossible_output")
    assert result.handled
    assert result.status == "failed"


def test_every_case_result_is_category_c():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    assert all(r.category == "C" for r in results)


# ---- trace saving: every case gets a persisted record of its own run ----


def test_every_category_c_case_records_a_trace_file():
    results = run_category_c(settings=_settings(), canary=generate_canary())
    for result in results:
        assert result.trace_path, result.case_id
        assert Path(result.trace_path).exists()
