import pytest

from sandbox_analyst.sandbox.base import ExecError, ExecResult
from sandbox_analyst.sandbox.fake import FakeSandbox
from sandbox_analyst.sandbox.record import RecordingSandbox, ReplaySandbox, SandboxCassetteMiss


def _result(stdout: str, images: list[bytes] | None = None) -> ExecResult:
    return ExecResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        error=None,
        images=images or [],
        duration_ms=10,
        timed_out=False,
        truncated=False,
    )


def test_record_then_replay_round_trip(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeSandbox([_result("42")])
    recorder = RecordingSandbox(real, cassette_path=cassette)
    recorder.upload("data.csv", b"a,b\n1,2\n")

    recorded = recorder.run("print(42)")

    replay = ReplaySandbox(cassette)
    replay.upload("data.csv", b"a,b\n1,2\n")
    replayed = replay.run("print(42)")

    assert replayed == recorded
    assert replayed.stdout == "42"


def test_record_then_replay_round_trip_with_images(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeSandbox([_result("done", images=[b"fake-png-bytes"])])
    recorder = RecordingSandbox(real, cassette_path=cassette)
    recorder.upload("data.csv", b"x")

    recorded = recorder.run("plot()")

    replay = ReplaySandbox(cassette)
    replay.upload("data.csv", b"x")
    replayed = replay.run("plot()")

    assert replayed.images == [b"fake-png-bytes"]
    assert replayed == recorded


def test_record_then_replay_round_trip_with_error(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    error = ExecError(name="ValueError", value="bad", traceback="line 1\nline 2")
    raw = ExecResult(
        stdout="",
        stderr="",
        exit_code=1,
        error=error,
        images=[],
        duration_ms=5,
        timed_out=False,
        truncated=False,
    )
    real = FakeSandbox([raw])
    recorder = RecordingSandbox(real, cassette_path=cassette)
    recorder.upload("data.csv", b"x")

    recorded = recorder.run("raise ValueError('bad')")

    replay = ReplaySandbox(cassette)
    replay.upload("data.csv", b"x")
    replayed = replay.run("raise ValueError('bad')")

    assert replayed == recorded


def test_replay_miss_on_different_code(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeSandbox([_result("42")])
    recorder = RecordingSandbox(real, cassette_path=cassette)
    recorder.upload("data.csv", b"x")
    recorder.run("print(42)")

    replay = ReplaySandbox(cassette)
    replay.upload("data.csv", b"x")
    with pytest.raises(SandboxCassetteMiss):
        replay.run("print('a completely different script')")


def test_replay_miss_on_different_upload_size_same_code(tmp_path):
    """The cassette key covers upload name+size, not just the code."""
    cassette = tmp_path / "cassette.jsonl"
    real = FakeSandbox([_result("42")])
    recorder = RecordingSandbox(real, cassette_path=cassette)
    recorder.upload("data.csv", b"x")
    recorder.run("print(42)")

    replay = ReplaySandbox(cassette)
    replay.upload("data.csv", b"a different, longer payload")
    with pytest.raises(SandboxCassetteMiss):
        replay.run("print(42)")


def test_replay_miss_against_an_empty_cassette_file(tmp_path):
    cassette = tmp_path / "does_not_exist.jsonl"
    replay = ReplaySandbox(cassette)
    with pytest.raises(SandboxCassetteMiss):
        replay.run("anything")


def test_recording_sandbox_forwards_last_run_cost(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeSandbox([_result("42")], run_cost_usd=0.01)
    recorder = RecordingSandbox(real, cassette_path=cassette)
    recorder.upload("data.csv", b"x")
    recorder.run("print(42)")
    assert recorder.last_run_cost_usd == 0.01
