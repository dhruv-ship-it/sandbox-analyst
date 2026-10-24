"""Unit tests for OpenAICompatClient, entirely offline.

No real network call is ever made here: every request is intercepted
by an httpx2.MockTransport handler, which lets these tests exercise the
retry/backoff policy deterministically (sleep is injected and captured,
never actually slept).
"""

import httpx2
import pytest

from sandbox_analyst.llm.base import (
    LLMConfigError,
    LLMResponse,
    LLMTruncated,
    LLMUnavailable,
    Message,
    RateLimitExhausted,
)
from sandbox_analyst.llm.openai_compat import OpenAICompatClient


def _completion_body(
    *,
    content: str,
    reasoning_content: str | None = None,
    finish_reason: str = "stop",
    completion_tokens: int = 5,
    prompt_tokens: int = 10,
) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-oss-20b",
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason, "logprobs": None}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _error_body(message: str) -> dict:
    return {"error": {"message": message, "type": "invalid_request_error"}}


def _make_client(
    handler,
    tmp_path,
    *,
    sleeps: list[float] | None = None,
    random_fn=lambda: 0.0,
    api_key: str = "test-key",
) -> OpenAICompatClient:
    sleeps = [] if sleeps is None else sleeps
    return OpenAICompatClient(
        provider="nim",
        model="gpt-oss-20b",
        api_key=api_key,
        base_url="https://example.test/v1",
        rpm=float("inf"),  # zero spacing, so only backoff sleeps show up below
        timeout_s=5,
        default_temperature=1.0,
        default_top_p=1.0,
        default_max_tokens=4096,
        default_reasoning_effort=None,
        usage_log_path=tmp_path / "usage.jsonl",
        sleep=sleeps.append,
        random_fn=random_fn,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


def _msg(content: str) -> list[Message]:
    return [Message(role="user", content=content)]


def test_retries_a_429_then_succeeds(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, json=_error_body("rate limited"))
        return httpx2.Response(200, json=_completion_body(content="4"))

    sleeps: list[float] = []
    client = _make_client(handler, tmp_path, sleeps=sleeps)
    response = client.complete(_msg("2 + 2?"))

    assert response.text == "4"
    assert calls["n"] == 2
    assert len(sleeps) == 1


def test_retry_after_header_is_honored(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, headers={"retry-after": "7"}, json=_error_body("slow down"))
        return httpx2.Response(200, json=_completion_body(content="ok"))

    sleeps: list[float] = []
    client = _make_client(handler, tmp_path, sleeps=sleeps)
    client.complete(_msg("x"))

    assert sleeps == [7.0]


def test_rate_limit_exhaustion_raises_rate_limit_exhausted(tmp_path):
    def handler(request):
        return httpx2.Response(429, json=_error_body("still limited"))

    client = _make_client(handler, tmp_path)
    with pytest.raises(RateLimitExhausted):
        client.complete(_msg("x"))


def test_5xx_exhaustion_raises_llm_unavailable(tmp_path):
    def handler(request):
        return httpx2.Response(503, json=_error_body("service unavailable"))

    client = _make_client(handler, tmp_path)
    with pytest.raises(LLMUnavailable):
        client.complete(_msg("x"))


def test_timeout_then_success_is_retried(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx2.TimeoutException("timed out")
        return httpx2.Response(200, json=_completion_body(content="ok"))

    sleeps: list[float] = []
    client = _make_client(handler, tmp_path, sleeps=sleeps)
    response = client.complete(_msg("x"))

    assert response.text == "ok"
    assert len(sleeps) == 1


def test_non_retryable_4xx_raises_immediately_with_provider_message(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx2.Response(401, json=_error_body("invalid api key"))

    client = _make_client(handler, tmp_path)
    with pytest.raises(LLMConfigError, match="invalid api key"):
        client.complete(_msg("x"))

    assert calls["n"] == 1


def test_410_is_not_retried_either(tmp_path):
    """The model-retirement case that motivated this split (see DECISIONS.md)."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx2.Response(410, json=_error_body("model has been retired"))

    client = _make_client(handler, tmp_path)
    with pytest.raises(LLMConfigError, match="retired"):
        client.complete(_msg("x"))

    assert calls["n"] == 1


def test_reasoning_is_captured_separately_from_text(tmp_path):
    def handler(request):
        body = _completion_body(content="4", reasoning_content="2 + 2 = 4")
        return httpx2.Response(200, json=body)

    client = _make_client(handler, tmp_path)
    response = client.complete(_msg("2 + 2?"))

    assert response.text == "4"
    assert response.reasoning == "2 + 2 = 4"


def test_no_reasoning_field_means_reasoning_is_none(tmp_path):
    def handler(request):
        return httpx2.Response(200, json=_completion_body(content="4"))

    client = _make_client(handler, tmp_path)
    response = client.complete(_msg("2 + 2?"))

    assert response.reasoning is None


def test_truncated_with_empty_content_raises_llm_truncated(tmp_path):
    def handler(request):
        return httpx2.Response(
            200, json=_completion_body(content="", finish_reason="length", completion_tokens=4096)
        )

    client = _make_client(handler, tmp_path)
    with pytest.raises(LLMTruncated):
        client.complete(_msg("x"))


def test_length_finish_reason_with_content_is_not_treated_as_truncated(tmp_path):
    def handler(request):
        body = _completion_body(content="partial answer", finish_reason="length")
        return httpx2.Response(200, json=body)

    client = _make_client(handler, tmp_path)
    response = client.complete(_msg("x"))

    assert response.text == "partial answer"
    assert response.finish_reason == "length"


def test_usage_log_records_successes_and_failures(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, json=_error_body("rate limited"))
        return httpx2.Response(200, json=_completion_body(content="ok"))

    client = _make_client(handler, tmp_path)
    client.complete(_msg("x"))

    lines = (tmp_path / "usage.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2  # one failed attempt, one success


def test_api_key_never_appears_in_repr_or_str(tmp_path):
    def handler(request):
        return httpx2.Response(200, json=_completion_body(content="ok"))

    client = _make_client(handler, tmp_path, api_key="super-secret-nim-key")

    assert "super-secret-nim-key" not in repr(client)
    assert "super-secret-nim-key" not in str(client)


def test_response_returns_llm_response_instance(tmp_path):
    def handler(request):
        return httpx2.Response(200, json=_completion_body(content="ok"))

    client = _make_client(handler, tmp_path)
    response = client.complete(_msg("x"))

    assert isinstance(response, LLMResponse)
    assert response.provider == "nim"
    assert response.model == "gpt-oss-20b"
