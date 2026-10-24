from sandbox_analyst.sandbox.base import (
    MAX_IMAGE_BYTES,
    ExecError,
    ExecResult,
    cap_exec_result,
)


def _result(**overrides) -> ExecResult:
    defaults = dict(
        stdout="",
        stderr="",
        exit_code=0,
        error=None,
        images=[],
        duration_ms=10,
        timed_out=False,
        truncated=False,
    )
    defaults.update(overrides)
    return ExecResult(**defaults)


def test_short_stdout_and_stderr_are_untouched():
    result = cap_exec_result(_result(stdout="hello", stderr="oops"))
    assert result.stdout == "hello"
    assert result.stderr == "oops"
    assert result.truncated is False


def test_long_stdout_is_capped_to_head_and_tail():
    long_text = "a" * 10_000 + "b" * 10_000 + "c" * 10_000
    result = cap_exec_result(_result(stdout=long_text))
    assert result.truncated is True
    assert result.stdout.startswith("a" * 10_000)
    assert result.stdout.endswith("c" * 10_000)
    assert "..." in result.stdout
    assert len(result.stdout) < len(long_text)


def test_long_stderr_is_capped_the_same_way():
    long_text = "x" * 25_000
    result = cap_exec_result(_result(stderr=long_text))
    assert result.truncated is True
    assert len(result.stderr) < len(long_text)


def test_short_traceback_is_untouched():
    error = ExecError(name="ValueError", value="bad", traceback="line1\nline2")
    result = cap_exec_result(_result(error=error))
    assert result.error.traceback == "line1\nline2"
    assert result.truncated is False


def test_long_traceback_keeps_only_last_30_lines():
    lines = [f"line {i}" for i in range(50)]
    error = ExecError(name="ValueError", value="bad", traceback="\n".join(lines))
    result = cap_exec_result(_result(error=error))
    assert result.truncated is True
    capped_lines = result.error.traceback.splitlines()
    assert len(capped_lines) == 30
    assert capped_lines == lines[-30:]


def test_up_to_five_small_images_are_kept():
    images = [b"x" * 100 for _ in range(5)]
    result = cap_exec_result(_result(images=images))
    assert result.images == images
    assert result.truncated is False


def test_sixth_image_is_dropped_and_marked_truncated():
    images = [b"x" * 100 for _ in range(6)]
    result = cap_exec_result(_result(images=images))
    assert len(result.images) == 5
    assert result.truncated is True


def test_oversized_image_is_dropped_and_marked_truncated():
    images = [b"x" * (MAX_IMAGE_BYTES + 1)]
    result = cap_exec_result(_result(images=images))
    assert result.images == []
    assert result.truncated is True


def test_oversized_image_does_not_consume_a_slot_other_images_still_kept():
    oversized = b"x" * (MAX_IMAGE_BYTES + 1)
    small = [b"y" * 100 for _ in range(5)]
    result = cap_exec_result(_result(images=[oversized, *small]))
    assert result.images == small
    assert result.truncated is True


def test_preexisting_truncated_flag_is_preserved():
    result = cap_exec_result(_result(truncated=True))
    assert result.truncated is True
