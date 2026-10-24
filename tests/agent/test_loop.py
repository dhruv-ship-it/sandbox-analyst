from pathlib import Path

import pytest

from sandbox_analyst.agent.loop import run_agent
from sandbox_analyst.agent.profile import DELIM_END, DELIM_START
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM, LLMConfigError, LLMResponse
from sandbox_analyst.sandbox import (
    ExecError,
    ExecResult,
    FakeSandbox,
    SandboxCrashed,
    SandboxUnavailable,
)

CSV = b"x,y\n1,2\n3,4\n"
FORBIDDEN_SUBSTRINGS = ["attempt", "remaining", "last chance", "retries", "tries"]


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _ok(stdout: str, images: list[bytes] | None = None) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        error=None,
        images=images or [],
        duration_ms=5,
        timed_out=False,
        truncated=False,
    )


def _err(
    name: str, value: str, traceback: str = "Traceback (most recent call last):\n"
) -> ExecResult:
    return ExecResult(
        stdout="",
        stderr="",
        exit_code=1,
        error=ExecError(name=name, value=value, traceback=traceback + f"{name}: {value}"),
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
        duration_ms=30000,
        timed_out=True,
        truncated=False,
    )


def _code(body: str) -> str:
    return f"```python\n{body}\n```"


def _answer(name: str, value: str, explanation: str = "computed from stdout") -> str:
    return (
        f'{{"answers": [{{"name": "{name}", "value": "{value}"}}], "explanation": "{explanation}"}}'
    )


# ---- happy path ----


def test_happy_path_in_one_attempt():
    llm = FakeLLM([_code("print('mean_x =', 2.0)"), _answer("mean_x", "2.0")])
    sandbox = FakeSandbox([_ok("mean_x = 2.0\n")])
    result = run_agent(
        CSV,
        "data.csv",
        "what is mean_x?",
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
    )
    assert result.status == "answered"
    assert len(result.attempts) == 1
    assert result.answers[0].name == "mean_x"
    assert result.answers[0].value == "2.0"
    assert result.code == "print('mean_x =', 2.0)"


# ---- sandbox cost accounting (D-054): the ledger is the source of truth ----


def test_sandbox_usd_sums_the_sandboxs_last_run_cost_usd_across_attempts():
    llm = FakeLLM([_code("raise KeyError('bad')"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox(
        [_err("KeyError", "'bad'"), _ok("x = 1\n")],
        run_cost_usd=0.0005,
    )
    result = run_agent(
        CSV,
        "data.csv",
        "what is x?",
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
    )
    assert result.status == "answered"
    assert result.sandbox_usd == pytest.approx(0.001)


def test_sandbox_usd_counts_a_crashed_attempts_recorded_cost():
    llm = FakeLLM([_code("x = [0] * 10**9"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox(
        [SandboxCrashed("oom"), _ok("x = 1\n")],
        run_cost_usd=0.0007,
    )
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert result.sandbox_usd == pytest.approx(0.0014)


# ---- error -> repair -> success ----


def test_python_error_then_repair_then_success():
    llm = FakeLLM([_code("raise KeyError('bad')"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_err("KeyError", "'bad'"), _ok("x = 1\n")])
    result = run_agent(
        CSV,
        "data.csv",
        "what is x?",
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2
    assert result.attempts[0].observation is not None
    assert "KeyError" in result.attempts[0].observation


# ---- checker violation -> repair ----


def test_checker_violation_then_repair():
    llm = FakeLLM(
        [_code("import os\nprint(os.getcwd())"), _code("print('ok =', 1)"), _answer("ok", "1")]
    )
    sandbox = FakeSandbox([_ok("ok = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2
    assert result.attempts[0].check_ok is False
    assert len(sandbox.runs) == 1  # the rejected attempt never reached the sandbox


# ---- timeout -> repair ----


def test_timeout_then_repair_then_success():
    llm = FakeLLM([_code("while True: pass"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_timeout(), _ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2
    assert "timeout" in result.attempts[0].observation.lower()


# ---- crash -> repair -> success ----


def test_crash_then_repair_then_success():
    llm = FakeLLM([_code("x = [0] * 10**9"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([SandboxCrashed("oom"), _ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2
    assert "memory" in result.attempts[0].observation.lower()


# ---- two crashes in a row -> tool_failure ----


def test_two_crashes_in_a_row_is_tool_failure():
    llm = FakeLLM([_code("a = 1"), _code("b = 2")])
    sandbox = FakeSandbox([SandboxCrashed("oom1"), SandboxCrashed("oom2")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "tool_failure"
    assert len(result.attempts) == 2


# ---- SandboxUnavailable -> immediate tool_failure ----


def test_sandbox_unavailable_is_immediate_tool_failure():
    llm = FakeLLM([_code("a = 1")])
    sandbox = FakeSandbox([SandboxUnavailable("budget exhausted")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "tool_failure"
    assert len(result.attempts) == 1


# ---- identical code -> repeated_failure ----


def test_identical_code_resubmitted_is_repeated_failure():
    same_code = _code("raise KeyError('bad')")
    llm = FakeLLM([same_code, same_code])
    sandbox = FakeSandbox([_err("KeyError", "'bad'")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "repeated_failure"
    assert len(result.attempts) == 2
    assert len(sandbox.runs) == 1  # the identical resubmission was never executed


# ---- same error signature twice (consecutive) -> repeated_failure ----


def test_same_error_signature_twice_in_a_row_is_repeated_failure():
    llm = FakeLLM([_code("raise KeyError('foo')"), _code("raise KeyError('bar')")])
    sandbox = FakeSandbox([_err("KeyError", "'foo'"), _err("KeyError", "'bar'")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "repeated_failure"
    assert len(result.attempts) == 2


def test_different_error_types_do_not_trigger_repeated_failure():
    llm = FakeLLM(
        [
            _code("raise KeyError('foo')"),
            _code("raise ValueError('bar')"),
            _code("print('x =', 1)"),
            _answer("x", "1"),
        ]
    )
    sandbox = FakeSandbox([_err("KeyError", "'foo'"), _err("ValueError", "'bar'"), _ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 3


# ---- 4 failures without an evidenced answer -> failed ----


def test_four_failing_attempts_is_failed():
    llm = FakeLLM(
        [
            _code("import os"),
            _code("import sys"),
            _code("import socket"),
            _code("import shutil"),
        ]
    )
    sandbox = FakeSandbox([])  # none of these ever reach the sandbox
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "failed"
    assert len(result.attempts) == 4
    assert len(sandbox.runs) == 0


# ---- invalid answer JSON -> one retry -> ok ----


def test_invalid_answer_json_gets_one_retry_then_succeeds():
    llm = FakeLLM([_code("print('x =', 1)"), "not valid json at all", _answer("x", "1")])
    sandbox = FakeSandbox([_ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 1  # the answer-JSON retry does not count as an attempt
    assert len(llm.calls) == 3


def test_invalid_answer_json_twice_does_not_crash_and_repairs():
    llm = FakeLLM(
        [
            _code("print('x =', 1)"),
            "not valid json",
            "still not valid json",
            _code("print('x =', 1)  # second"),
            _answer("x", "1"),
        ]
    )
    sandbox = FakeSandbox([_ok("x = 1\n"), _ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2


# ---- evidence failure -> repair -> evidenced ----


def test_evidence_failure_then_repair_then_evidenced():
    llm = FakeLLM(
        [
            _code("print('x =', 1)"),
            _answer("x", "999"),
            _code("print('x =', 1)  # second"),
            _answer("x", "1"),
        ]
    )
    sandbox = FakeSandbox([_ok("x = 1\n"), _ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2
    assert not result.attempts[0].evidence[0].passed
    assert result.attempts[1].evidence[0].passed


def test_evidence_failure_on_the_last_attempt_records_the_unverified_answer():
    llm = FakeLLM(
        [
            _code("import os"),
            _code("import sys"),
            _code("import socket"),
            _code("print('x =', 1)"),
            _answer("x", "999"),
        ]
    )
    sandbox = FakeSandbox([_ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "failed"
    assert result.answers[0].value == "999"  # recorded even though evidence failed
    assert not result.evidence[0].passed


# ---- no code block ----


def test_no_code_block_found_then_repair_then_success():
    llm = FakeLLM(["I believe the answer is 42.", _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 2
    assert result.attempts[0].code is None
    assert result.attempts[0].observation == "no python code block found"


# ---- llm_error ----


def test_llm_config_error_is_reported_as_llm_error_status():
    llm = FakeLLM([LLMConfigError("bad api key")])
    sandbox = FakeSandbox([])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "llm_error"
    assert result.attempts == []


# ---- budgets ----


def test_token_budget_exceeded_stops_the_run():
    big_response = LLMResponse(
        text=_code("print(1)"),
        reasoning=None,
        prompt_tokens=10,
        completion_tokens=70_000,
        latency_ms=5,
        provider="fake",
        model="fake-model",
        finish_reason="stop",
    )
    llm = FakeLLM([big_response])
    sandbox = FakeSandbox([])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "budget_exceeded"
    assert result.total_completion_tokens >= 60_000
    assert result.attempts == []


def test_time_budget_exceeded_stops_before_a_new_attempt():
    times = iter([0.0, 0.0, 301.0])

    def clock() -> float:
        return next(times)

    llm = FakeLLM([_code("raise KeyError('x')")])
    sandbox = FakeSandbox([_err("KeyError", "'x'")])
    result = run_agent(
        CSV,
        "data.csv",
        "q?",
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
        clock=clock,
    )
    assert result.status == "budget_exceeded"
    assert len(result.attempts) == 1


# ---- data never leaked beyond the sampled preview rows ----


def test_a_row_past_the_sampled_preview_never_appears_in_any_message():
    rows = "\n".join(f"{i},row-marker-{i}" for i in range(100))
    csv = f"idx,label\n{rows}\n".encode()
    marker = "row-marker-49"

    llm = FakeLLM([_code("import os"), _code("print('n =', 100)"), _answer("n", "100")])
    sandbox = FakeSandbox([_ok("n = 100\n")])
    run_agent(
        csv,
        "data.csv",
        "how many rows?",
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
    )

    for call in llm.calls:
        for message in call["messages"]:
            assert marker not in message.content


def test_preview_delimiters_are_present_in_the_first_user_message():
    llm = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_ok("x = 1\n")])
    run_agent(CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings())

    first_messages = llm.calls[0]["messages"]
    user_message = next(m for m in first_messages if m.role == "user")
    assert DELIM_START in user_message.content
    assert DELIM_END in user_message.content


# ---- event sequence and usage totals ----


def test_event_sequence_and_usage_totals_are_correct():
    llm = FakeLLM([_code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_ok("x = 1\n")])
    events = []
    result = run_agent(
        CSV,
        "data.csv",
        "q?",
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
        on_event=events.append,
    )

    assert [e.seq for e in events] == list(range(len(events)))
    assert all(e.run_id == result.run_id for e in events)
    assert events[0].type == "run_started"
    assert events[-1].type == "run_finished"

    response_events = [e for e in events if e.type == "llm_response"]
    assert result.total_prompt_tokens == sum(e.payload["prompt_tokens"] for e in response_events)
    assert result.total_completion_tokens == sum(
        e.payload["completion_tokens"] for e in response_events
    )

    finished_payload = events[-1].payload
    assert finished_payload["status"] == "answered"
    assert finished_payload["total_prompt_tokens"] == result.total_prompt_tokens


# ---- image artifacts ----


def test_images_are_written_as_artifact_file_paths(tmp_path, monkeypatch):
    import sandbox_analyst.agent.loop as loop_module

    monkeypatch.setattr(loop_module, "DEFAULT_ARTIFACTS_DIR", tmp_path)

    png_bytes = b"\x89PNG\r\n\x1a\nFAKE"
    llm = FakeLLM([_code("print('done')"), _answer("status", "done")])
    sandbox = FakeSandbox([_ok("done\n", images=[png_bytes])])
    result = run_agent(
        CSV, "data.csv", "plot it", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )

    assert result.status == "answered"
    assert len(result.images) == 1
    image_path = Path(result.images[0])
    assert image_path.exists()
    assert image_path.read_bytes() == png_bytes


# ---- the no-attempt-count rule, across a full multi-observation run ----


def test_no_message_ever_reveals_attempt_count_across_a_full_run():
    llm = FakeLLM(
        [
            "I think the answer is 42.",  # no code block
            _code("import os\nprint(os.getcwd())"),  # checker violation
            _code("raise KeyError('x')"),  # exec error
            _code("print('x =', 1)"),  # success
            _answer("x", "1"),
        ]
    )
    sandbox = FakeSandbox([_err("KeyError", "'x'"), _ok("x = 1\n")])
    result = run_agent(
        CSV, "data.csv", "q?", llm=llm, sandbox_factory=lambda: sandbox, settings=_settings()
    )
    assert result.status == "answered"
    assert len(result.attempts) == 4

    for call in llm.calls:
        for message in call["messages"]:
            lowered = message.content.lower()
            for forbidden in FORBIDDEN_SUBSTRINGS:
                assert forbidden not in lowered, f"found {forbidden!r} in: {message.content!r}"
