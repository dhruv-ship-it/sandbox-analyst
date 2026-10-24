"""Live tests against real NVIDIA NIM / Groq endpoints.

These make real network calls through the actual OpenAICompatClient end
to end -- no mocked transport. Excluded by default; run with:

    uv run pytest -m live -v tests/llm/test_llm_live.py

Capped at ~6 requests total (a: 1, b: 4, c: 0-1) to stay well inside
this task's live-LLM request budget. If anything here fails for a
key/model/account reason, stop and report the exact failure rather
than retrying.
"""

import statistics

import pytest

from sandbox_analyst.config import Settings
from sandbox_analyst.llm.base import Message
from sandbox_analyst.llm.factory import make_llm

pytestmark = pytest.mark.live

QUESTION = "What is 15 + 27? Answer with just the number."


@pytest.fixture
def nim_llm():
    settings = Settings(sa_llm_provider="nim")
    if settings.nim_api_key is None or not settings.nim_api_key.get_secret_value():
        pytest.skip("NIM_API_KEY not set")
    if not settings.sa_llm_model:
        pytest.skip("SA_LLM_MODEL not set")
    return make_llm(settings)


def test_a_one_nim_call(nim_llm):
    response = nim_llm.complete([Message(role="user", content=QUESTION)])
    print(  # noqa: T201
        f"\nnim: latency_ms={response.latency_ms} prompt_tokens={response.prompt_tokens} "
        f"completion_tokens={response.completion_tokens} finish_reason={response.finish_reason} "
        f"reasoning_returned={response.reasoning is not None}"
    )
    assert response.finish_reason in ("stop", "length")
    assert response.prompt_tokens > 0


def test_b_reasoning_effort_low_vs_high(nim_llm):
    low = [
        nim_llm.complete(
            [Message(role="user", content=QUESTION)], reasoning_effort="low"
        ).completion_tokens
        for _ in range(2)
    ]
    high = [
        nim_llm.complete(
            [Message(role="user", content=QUESTION)], reasoning_effort="high"
        ).completion_tokens
        for _ in range(2)
    ]
    mean_low = statistics.mean(low)
    mean_high = statistics.mean(high)
    print(f"\nnim reasoning_effort completion tokens: low={mean_low} high={mean_high}")  # noqa: T201
    assert mean_low > 0
    assert mean_high > 0


def test_c_groq_call_skipped_if_no_key():
    settings = Settings(sa_llm_provider="groq")
    if settings.groq_api_key is None or not settings.groq_api_key.get_secret_value():
        pytest.skip("GROQ_API_KEY not set")
    llm = make_llm(settings)
    response = llm.complete([Message(role="user", content=QUESTION)])
    print(  # noqa: T201
        f"\ngroq: latency_ms={response.latency_ms} finish_reason={response.finish_reason}"
    )
    assert response.finish_reason in ("stop", "length")
