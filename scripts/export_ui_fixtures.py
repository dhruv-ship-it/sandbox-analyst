"""Export AgentEvent sequences from the real agent loop as UI test fixtures.

Runs `run_agent` with `FakeLLM` + `FakeSandbox` (no network, no real
sandbox -- CLAUDE.md rule 1) for a handful of named scenarios and writes
each one's exact event sequence to `web/src/fixtures/<name>.json`. Driving
the real loop (rather than hand-writing fixture JSON) means the UI's
reducer tests exercise the exact same event shapes the backend actually
emits, so the two sides can't silently drift apart (see DECISIONS.md).

Usage (from the repo root):
    uv run python scripts/export_ui_fixtures.py
"""

import json
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path

from sandbox_analyst.agent import AgentEvent
from sandbox_analyst.agent import loop as loop_module
from sandbox_analyst.agent.loop import run_agent
from sandbox_analyst.config import Settings
from sandbox_analyst.llm import FakeLLM, LLMResponse
from sandbox_analyst.sandbox import ExecError, ExecResult, FakeSandbox, SandboxCrashed

OUT_DIR = Path(__file__).resolve().parent.parent / "web" / "src" / "fixtures"
CSV = b"region,units,unit_price\nNorth,10,5.0\nSouth,20,4.5\n"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _code(body: str) -> str:
    return f"```python\n{body}\n```"


def _answer(name: str, value: str, explanation: str = "computed from stdout") -> str:
    return (
        f'{{"answers": [{{"name": "{name}", "value": "{value}"}}], "explanation": "{explanation}"}}'
    )


def _ok(stdout: str, images: list[bytes] | None = None) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        error=None,
        images=images or [],
        duration_ms=120,
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
        duration_ms=90,
        timed_out=False,
        truncated=False,
    )


def _event_to_jsonable(event: AgentEvent) -> dict:
    payload = asdict(event) if is_dataclass(event) else vars(event)
    return payload


def _run(name: str, question: str, llm: FakeLLM, sandbox: FakeSandbox) -> None:
    events: list[AgentEvent] = []
    run_agent(
        CSV,
        "sales.csv",
        question,
        llm=llm,
        sandbox_factory=lambda: sandbox,
        settings=_settings(),
        on_event=events.append,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{name}.json"
    out_path.write_text(
        json.dumps([_event_to_jsonable(e) for e in events], indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path} ({len(events)} events)")


def scenario_happy_path() -> None:
    llm = FakeLLM([_code("print('mean_units =', 15.0)"), _answer("mean_units", "15.0")])
    sandbox = FakeSandbox([_ok("mean_units = 15.0\n")])
    _run("happy_path", "What is the mean of units?", llm, sandbox)


def scenario_error_repair_success() -> None:
    llm = FakeLLM([_code("raise KeyError('region')"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([_err("KeyError", "'region'"), _ok("x = 1\n")])
    _run("error_repair_success", "What is x?", llm, sandbox)


def scenario_checker_block_repair() -> None:
    llm = FakeLLM(
        [
            _code("import os\nprint(os.getcwd())"),
            _code("print('ok =', 1)"),
            _answer("ok", "1"),
        ]
    )
    sandbox = FakeSandbox([_ok("ok = 1\n")])
    _run("checker_block_repair", "What directory are we in?", llm, sandbox)


def scenario_crash_repair() -> None:
    llm = FakeLLM([_code("x = [0] * 10**9"), _code("print('x =', 1)"), _answer("x", "1")])
    sandbox = FakeSandbox([SandboxCrashed("out of memory"), _ok("x = 1\n")])
    _run("crash_repair", "What is x?", llm, sandbox)


def scenario_tool_failure() -> None:
    llm = FakeLLM([_code("a = 1"), _code("b = 2")])
    sandbox = FakeSandbox([SandboxCrashed("oom1"), SandboxCrashed("oom2")])
    _run("tool_failure", "What is a + b?", llm, sandbox)


def scenario_budget_exceeded() -> None:
    big_response = LLMResponse(
        text=_code("print(1)"),
        reasoning=None,
        prompt_tokens=10,
        completion_tokens=70_000,
        latency_ms=1200,
        provider="fake",
        model="fake-model",
        finish_reason="stop",
    )
    llm = FakeLLM([big_response])
    sandbox = FakeSandbox([])
    _run("budget_exceeded", "Summarize everything about this dataset.", llm, sandbox)


def scenario_chart_run() -> None:
    png_bytes = b"\x89PNG\r\n\x1a\nFAKE-PNG-FOR-FIXTURES-ONLY"
    llm = FakeLLM(
        [
            _code(
                "import matplotlib.pyplot as plt\n"
                "plt.bar(['North', 'South'], [10, 20])\n"
                "plt.savefig('/work/out/chart.png')\n"
                "print('chart saved')"
            ),
            _answer("status", "chart saved"),
        ]
    )
    sandbox = FakeSandbox([_ok("chart saved\n", images=[png_bytes])])
    with tempfile.TemporaryDirectory() as tmp_dir:
        original_dir = loop_module.DEFAULT_ARTIFACTS_DIR
        loop_module.DEFAULT_ARTIFACTS_DIR = Path(tmp_dir)
        try:
            _run("chart_run", "Plot total units sold per region as a bar chart.", llm, sandbox)
        finally:
            loop_module.DEFAULT_ARTIFACTS_DIR = original_dir


SCENARIOS = [
    scenario_happy_path,
    scenario_error_repair_success,
    scenario_checker_block_repair,
    scenario_crash_repair,
    scenario_tool_failure,
    scenario_budget_exceeded,
    scenario_chart_run,
]


def main() -> int:
    for scenario in SCENARIOS:
        scenario()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
