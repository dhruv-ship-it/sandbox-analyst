from sandbox_analyst.agent.loop import AgentResult
from sandbox_analyst.redteam.canary import generate_canary
from sandbox_analyst.redteam.layer_isolation import (
    every_generated_code,
    load_known_bad_snippets,
    run_checker_only,
    run_sandbox_only,
    run_sandbox_only_layer,
)
from sandbox_analyst.sandbox import ExecResult, FakeSandbox, SandboxCrashed, SandboxUnavailable


def _agent_result(run_id: str, attempts: list) -> AgentResult:
    return AgentResult(
        run_id=run_id,
        status="answered",
        answers=[],
        explanation="",
        code="",
        stdout="",
        images=[],
        evidence=[],
        attempts=attempts,
        total_prompt_tokens=0,
        total_completion_tokens=0,
        total_latency_ms=0,
        sandbox_usd=0.0,
    )


class _Attempt:
    def __init__(self, attempt: int, code: str | None):
        self.attempt = attempt
        self.code = code


def _ok(stdout: str) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        error=None,
        images=[],
        duration_ms=1,
        timed_out=False,
        truncated=False,
    )


# ---- the known-bad corpus ----


def test_known_bad_snippets_corpus_has_44_entries():
    # Exactly the checker's own malicious-case corpus (tests/guard/test_malicious.py),
    # kept in sync deliberately, not padded to any externally-assumed number (D-101).
    assert len(load_known_bad_snippets()) == 44


def test_every_known_bad_snippet_has_id_and_code():
    for snippet in load_known_bad_snippets():
        assert snippet["id"]
        assert snippet["code"]


# ---- checker-only pass (never executes anything) ----


def test_run_checker_only_blocks_every_known_bad_snippet():
    snippets = [(s["id"], s["code"]) for s in load_known_bad_snippets()]
    blocked = run_checker_only(snippets)
    assert all(blocked.values()), [k for k, v in blocked.items() if not v]


def test_run_checker_only_passes_benign_code():
    blocked = run_checker_only([("benign", "import pandas as pd\ndf = pd.DataFrame()\n")])
    assert blocked == {"benign": False}


def test_every_generated_code_collects_only_attempts_with_code():
    results = [
        _agent_result("run1", [_Attempt(1, "print(1)"), _Attempt(2, None)]),
        _agent_result("run2", [_Attempt(1, "print(2)")]),
    ]
    collected = every_generated_code(results)
    assert collected == [("run1#1", "print(1)"), ("run2#1", "print(2)")]


# ---- sandbox-only (checker disabled), structurally isolated ----


def test_run_sandbox_only_calls_sandbox_run_directly_no_checker_involved():
    # "import os" would be blocked by the checker -- this function never calls it.
    sandbox = FakeSandbox([_ok("sandbox ran it\n")])
    result = run_sandbox_only("import os\nprint('sandbox ran it')\n", sandbox)
    assert result.stdout == "sandbox ran it\n"


def test_sandbox_only_layer_handled_when_no_canary_leak():
    canary = generate_canary()
    results = [_agent_result("run1", [_Attempt(1, "print(1)")])]
    outcomes = run_sandbox_only_layer(results, lambda: FakeSandbox([_ok("1\n")]), canary)
    assert len(outcomes) == 1
    assert outcomes[0].handled
    assert outcomes[0].category == "A-sandbox-only"


def test_sandbox_only_layer_not_handled_when_the_canary_leaks():
    canary = generate_canary()
    results = [_agent_result("run1", [_Attempt(1, "print(1)")])]
    outcomes = run_sandbox_only_layer(results, lambda: FakeSandbox([_ok(f"{canary}\n")]), canary)
    assert not outcomes[0].handled
    assert outcomes[0].canary_leaked


def test_sandbox_only_layer_treats_a_sandbox_crash_as_contained():
    canary = generate_canary()
    results = [_agent_result("run1", [_Attempt(1, "print(1)")])]
    outcomes = run_sandbox_only_layer(results, lambda: FakeSandbox([SandboxCrashed("oom")]), canary)
    assert outcomes[0].handled
    assert "contained" in outcomes[0].reason


def test_sandbox_only_layer_treats_sandbox_unavailable_as_contained():
    canary = generate_canary()
    results = [_agent_result("run1", [_Attempt(1, "print(1)")])]
    outcomes = run_sandbox_only_layer(
        results, lambda: FakeSandbox([SandboxUnavailable("budget exhausted")]), canary
    )
    assert outcomes[0].handled
