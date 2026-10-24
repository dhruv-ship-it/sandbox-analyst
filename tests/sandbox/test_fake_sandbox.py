import pytest

from sandbox_analyst.sandbox.base import ExecResult, SandboxCrashed, SandboxUnavailable
from sandbox_analyst.sandbox.fake import FakeSandbox


def _ok_result(stdout: str = "") -> ExecResult:
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


def test_run_returns_scripted_results_in_order():
    sandbox = FakeSandbox([_ok_result("first"), _ok_result("second")])
    assert sandbox.run("print(1)").stdout == "first"
    assert sandbox.run("print(2)").stdout == "second"


def test_run_raises_scripted_exceptions():
    sandbox = FakeSandbox([RuntimeError("boom"), _ok_result("after")])
    with pytest.raises(RuntimeError, match="boom"):
        sandbox.run("whatever")
    assert sandbox.run("whatever").stdout == "after"


def test_run_raises_sandbox_unavailable_when_script_exhausted():
    sandbox = FakeSandbox([_ok_result()])
    sandbox.run("code")
    with pytest.raises(SandboxUnavailable):
        sandbox.run("code")


def test_run_records_the_code_it_was_given():
    sandbox = FakeSandbox([_ok_result(), _ok_result()])
    sandbox.run("a = 1")
    sandbox.run("b = 2")
    assert sandbox.runs == ["a = 1", "b = 2"]


def test_upload_records_bytes_and_returns_remote_path():
    sandbox = FakeSandbox()
    path = sandbox.upload("data.csv", b"a,b\n1,2\n")
    assert path == "/work/data/data.csv"
    assert sandbox.uploads["data.csv"] == b"a,b\n1,2\n"


def test_upload_validates_the_name():
    sandbox = FakeSandbox()
    with pytest.raises(ValueError):
        sandbox.upload("../escape.csv", b"x")


def test_upload_validates_the_size():
    sandbox = FakeSandbox(max_upload_mb=1)
    too_big = b"x" * (2 * 1024 * 1024)
    with pytest.raises(ValueError):
        sandbox.upload("big.csv", too_big)


def test_context_manager_closes_on_exit():
    with FakeSandbox() as sandbox:
        assert not sandbox.closed
    assert sandbox.closed


def test_backend_attribute_is_fake():
    assert FakeSandbox().backend == "fake"


def test_fake_sandbox_never_executes_code(tmp_path):
    """The defining safety property: FakeSandbox must not run `code`."""
    marker = tmp_path / "pwned.txt"
    payload = f"open(r{str(marker)!r}, 'w').write('pwned')"

    sandbox = FakeSandbox([_ok_result()])
    sandbox.run(payload)

    assert not marker.exists()


# ---- last_run_cost_usd (D-054) ----


def test_last_run_cost_usd_defaults_to_zero():
    sandbox = FakeSandbox([_ok_result()])
    assert sandbox.last_run_cost_usd == 0.0


def test_last_run_cost_usd_set_after_a_successful_run():
    sandbox = FakeSandbox([_ok_result(), _ok_result()], run_cost_usd=0.001)
    sandbox.run("code")
    assert sandbox.last_run_cost_usd == 0.001
    sandbox.run("code")
    assert sandbox.last_run_cost_usd == 0.001


def test_last_run_cost_usd_set_even_when_the_run_crashes():
    sandbox = FakeSandbox([SandboxCrashed("oom")], run_cost_usd=0.002)
    with pytest.raises(SandboxCrashed):
        sandbox.run("code")
    assert sandbox.last_run_cost_usd == 0.002


def test_last_run_cost_usd_unchanged_when_unavailable_before_a_sandbox_is_created():
    sandbox = FakeSandbox([], run_cost_usd=0.002)
    with pytest.raises(SandboxUnavailable):
        sandbox.run("code")
    assert sandbox.last_run_cost_usd == 0.0
