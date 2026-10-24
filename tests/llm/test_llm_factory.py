import pytest

from sandbox_analyst.config import Settings
from sandbox_analyst.llm.base import LLMConfigError
from sandbox_analyst.llm.factory import make_llm
from sandbox_analyst.llm.fake import FakeLLM
from sandbox_analyst.llm.openai_compat import OpenAICompatClient


def test_fake_provider_returns_fake_llm():
    settings = Settings(_env_file=None, sa_llm_provider="fake")
    assert isinstance(make_llm(settings), FakeLLM)


def test_nim_provider_builds_openai_compat_client():
    settings = Settings(
        _env_file=None,
        sa_llm_provider="nim",
        sa_llm_model="openai/gpt-oss-20b",
        nim_api_key="test-nim-key",
    )
    llm = make_llm(settings)
    assert isinstance(llm, OpenAICompatClient)
    assert llm.provider == "nim"
    assert llm.model == "openai/gpt-oss-20b"


def test_groq_provider_builds_openai_compat_client():
    settings = Settings(
        _env_file=None,
        sa_llm_provider="groq",
        sa_llm_model="openai/gpt-oss-20b",
        groq_api_key="test-groq-key",
    )
    llm = make_llm(settings)
    assert isinstance(llm, OpenAICompatClient)
    assert llm.provider == "groq"


def test_nim_without_model_raises_config_error():
    settings = Settings(_env_file=None, sa_llm_provider="nim", nim_api_key="test-key")
    with pytest.raises(LLMConfigError, match="SA_LLM_MODEL"):
        make_llm(settings)


def test_nim_without_api_key_raises_config_error():
    settings = Settings(_env_file=None, sa_llm_provider="nim", sa_llm_model="m")
    with pytest.raises(LLMConfigError, match="NIM_API_KEY"):
        make_llm(settings)


def test_nim_with_empty_string_api_key_raises_config_error():
    """An env var set to an empty string ("FOO=") parses as SecretStr(""), not None."""
    settings = Settings(_env_file=None, sa_llm_provider="nim", sa_llm_model="m", nim_api_key="")
    with pytest.raises(LLMConfigError, match="NIM_API_KEY"):
        make_llm(settings)
