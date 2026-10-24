"""Construct an LLMClient from configuration."""

from typing import TYPE_CHECKING

from .base import LLMClient, LLMConfigError
from .fake import FakeLLM
from .openai_compat import PROVIDER_BASE_URLS, OpenAICompatClient

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings


def make_llm(settings: "Settings") -> LLMClient:
    """Build the LLM backend selected by `settings.sa_llm_provider`.

    "fake" returns an empty-script FakeLLM, useful for wiring (tests
    that need specific scripted responses should construct FakeLLM
    directly). "nim"/"groq" build the real OpenAI-compatible client,
    raising LLMConfigError if the required model/key isn't configured.
    """
    if settings.sa_llm_provider == "fake":
        return FakeLLM()

    if settings.sa_llm_provider not in PROVIDER_BASE_URLS:
        raise ValueError(f"unknown llm provider: {settings.sa_llm_provider!r}")

    if not settings.sa_llm_model:
        raise LLMConfigError("SA_LLM_MODEL must be set when SA_LLM_PROVIDER is not 'fake'")

    if settings.sa_llm_provider == "nim":
        api_key, rpm = settings.nim_api_key, settings.llm_rpm_nim
    else:
        api_key, rpm = settings.groq_api_key, settings.llm_rpm_groq
    # An unset env var and an env var set to an empty string both end up
    # here (pydantic-settings parses "FOO=" as SecretStr("")), so both
    # must be treated as "not configured".
    if api_key is None or not api_key.get_secret_value():
        raise LLMConfigError(f"{settings.sa_llm_provider.upper()}_API_KEY must be set")

    return OpenAICompatClient(
        provider=settings.sa_llm_provider,
        model=settings.sa_llm_model,
        api_key=api_key.get_secret_value(),
        base_url=PROVIDER_BASE_URLS[settings.sa_llm_provider],
        rpm=rpm,
        timeout_s=settings.llm_timeout_s,
        default_temperature=settings.llm_temperature,
        default_top_p=settings.llm_top_p,
        default_max_tokens=settings.llm_max_tokens,
        default_reasoning_effort=settings.llm_reasoning_effort,
    )
