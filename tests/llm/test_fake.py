import pytest

from sandbox_analyst.llm.base import LLMResponse, Message
from sandbox_analyst.llm.fake import FakeLLM


def _msg(content: str) -> list[Message]:
    return [Message(role="user", content=content)]


def test_string_items_are_wrapped_with_plausible_token_counts():
    llm = FakeLLM(["4"])
    response = llm.complete(_msg("what is 2 + 2?"))
    assert response.text == "4"
    assert response.finish_reason == "stop"
    assert response.reasoning is None
    assert response.prompt_tokens >= 1
    assert response.completion_tokens >= 1


def test_llm_response_items_are_returned_as_is():
    scripted = LLMResponse(
        text="truncated",
        reasoning=None,
        prompt_tokens=10,
        completion_tokens=4096,
        latency_ms=500,
        provider="fake",
        model="fake-model",
        finish_reason="length",
    )
    llm = FakeLLM([scripted])
    assert llm.complete(_msg("x")) is scripted


def test_exception_items_are_raised():
    llm = FakeLLM([RuntimeError("boom"), "after"])
    with pytest.raises(RuntimeError, match="boom"):
        llm.complete(_msg("x"))
    assert llm.complete(_msg("x")).text == "after"


def test_exhausted_queue_raises():
    llm = FakeLLM(["only one"])
    llm.complete(_msg("x"))
    with pytest.raises(RuntimeError, match="exhausted"):
        llm.complete(_msg("x"))


def test_respond_callable_overrides_the_queue():
    def respond(messages, **kwargs):
        return LLMResponse(
            text=f"echo:{messages[0].content}",
            reasoning=None,
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=0,
            provider="fake",
            model="fake-model",
            finish_reason="stop",
        )

    llm = FakeLLM(respond=respond)
    assert llm.complete(_msg("hi")).text == "echo:hi"


def test_every_call_is_recorded():
    llm = FakeLLM(["a", "b"])
    llm.complete(_msg("first"), reasoning_effort="low")
    llm.complete(_msg("second"), max_tokens=10)
    assert len(llm.calls) == 2
    assert llm.calls[0]["reasoning_effort"] == "low"
    assert llm.calls[1]["max_tokens"] == 10
