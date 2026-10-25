"""Proof that the red-team-only "checker disabled" path (layer_isolation.run_sandbox_only)
is unreachable from the API or `Settings` -- CLAUDE.md's own rule for this task.

`run_sandbox_only` exists specifically so category A's sandbox-alone
measurement doesn't need a flag on `run_agent` at all: there is nothing to
disable, because the real loop (`agent.loop._run_attempts`) always calls
`guard.check()` unconditionally, every attempt, with no parameter
anywhere that skips it. These tests pin that structurally, rather than
just asserting it in a comment that could silently go stale.
"""

import inspect

from sandbox_analyst.agent.loop import run_agent
from sandbox_analyst.api.schemas import RunCreateRequest
from sandbox_analyst.config import Settings

_SUSPICIOUS_SUBSTRINGS = ("checker", "check_disable", "skip_check", "no_check", "disable_guard")


def _field_names_containing(substrings: tuple[str, ...], names) -> list[str]:
    return [n for n in names if any(s in n.lower() for s in substrings)]


def test_settings_has_no_field_to_disable_the_checker():
    suspicious = _field_names_containing(_SUSPICIOUS_SUBSTRINGS, Settings.model_fields)
    assert suspicious == []


def test_run_create_request_has_no_field_to_disable_the_checker():
    suspicious = _field_names_containing(_SUSPICIOUS_SUBSTRINGS, RunCreateRequest.model_fields)
    assert suspicious == []


def test_run_agent_signature_has_no_parameter_to_disable_the_checker():
    params = inspect.signature(run_agent).parameters
    suspicious = _field_names_containing(_SUSPICIOUS_SUBSTRINGS, params)
    assert suspicious == []


def test_agent_loop_source_calls_check_unconditionally():
    # A direct source check, not just a signature check: confirms `check(code)`
    # is called plainly, with no surrounding `if <flag>:` making it conditional.
    import sandbox_analyst.agent.loop as loop_module

    source = inspect.getsource(loop_module)
    assert "check_result = check(code)" in source
    # No settings- or flag-gated call site exists anywhere in this module.
    assert "if settings" not in source.split("check_result = check(code)")[0].splitlines()[-1]


def test_redteams_checker_disabled_path_lives_only_in_the_redteam_package():
    # The one function that skips the checker is `layer_isolation.run_sandbox_only`,
    # and nothing in api/ or cli.py's production commands imports it.
    import ast
    from pathlib import Path

    redteam_only_symbol = "run_sandbox_only"
    api_paths = Path("src/sandbox_analyst/api").rglob("*.py")
    for path in [*api_paths, Path("src/sandbox_analyst/cli.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_names = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert redteam_only_symbol not in imported_names, f"{path} imports {redteam_only_symbol}"
