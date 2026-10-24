import json

from sandbox_analyst.llm.usage import append_usage, make_entry


def test_append_usage_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "usage.jsonl"
    append_usage(make_entry(provider="fake", model="m", ok=True), path=path)
    assert path.exists()


def test_append_and_read_back_entries(tmp_path):
    path = tmp_path / "usage.jsonl"
    append_usage(
        make_entry(
            provider="nim",
            model="gpt-oss-20b",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=123,
            finish_reason="stop",
            ok=True,
        ),
        path=path,
    )
    append_usage(
        make_entry(provider="nim", model="gpt-oss-20b", ok=False, error_type="RateLimitError"),
        path=path,
    )
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["ok"] is True
    assert first["prompt_tokens"] == 10
    assert first["completion_tokens"] == 5
    assert first["finish_reason"] == "stop"

    second = json.loads(lines[1])
    assert second["ok"] is False
    assert second["error_type"] == "RateLimitError"
