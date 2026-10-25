from pathlib import Path

from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM, LLMResponse, Message
from sandbox_analyst.redteam.runner import run_redteam
from sandbox_analyst.sandbox import ExecResult, FakeSandbox

ANSWER_STEP_MARKER = "ONLY a JSON"


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


def _generic_respond(messages: list[Message], **_kwargs) -> LLMResponse:
    system = messages[0].content if messages else ""
    if ANSWER_STEP_MARKER in system:
        return _response('{"answers": [{"name": "result", "value": "1"}], "explanation": "ok"}')
    return _response("```python\nprint('result =', 1)\n```")


def _sandbox_factory():
    ok = ExecResult(
        stdout="result = 1\n",
        stderr="",
        exit_code=0,
        error=None,
        images=[],
        duration_ms=1,
        timed_out=False,
        truncated=False,
    )
    return FakeSandbox([ok] * 10)


def test_run_redteam_end_to_end_with_fakes_produces_a_well_formed_report(tmp_path: Path):
    settings = Settings(_env_file=None, sa_llm_provider="fake", sa_sandbox="fake")
    outcome = run_redteam(
        run_name="unit-test-run",
        settings=settings,
        llm=FakeLLM(respond=_generic_respond),
        sandbox_factory=_sandbox_factory,
        out_dir=tmp_path / "redteam-out",
    )

    assert outcome.run_name == "unit-test-run"
    assert outcome.md_path.exists()
    assert outcome.json_path.exists()

    report = outcome.report
    for cat in ("A", "B", "C", "D"):
        assert "handled" in report["categories"][cat]
        assert "total" in report["categories"][cat]
    assert report["overall"]["total"] == sum(
        report["categories"][c]["total"] for c in ("A", "B", "C", "D")
    )
    assert "layer_isolation_sandbox_only" in report
    assert "layer_isolation_checker_only_category_a_block_rate" in report


def test_run_redteam_never_leaks_the_canary_it_generates_for_itself(tmp_path: Path):
    settings = Settings(_env_file=None, sa_llm_provider="fake", sa_sandbox="fake")
    outcome = run_redteam(
        run_name="unit-test-canary",
        settings=settings,
        llm=FakeLLM(respond=_generic_respond),
        sandbox_factory=_sandbox_factory,
        out_dir=tmp_path / "redteam-out",
    )
    assert outcome.report["canary"]["n_leaks"] == 0
