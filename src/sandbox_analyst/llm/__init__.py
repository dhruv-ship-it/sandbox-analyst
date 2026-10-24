"""Provider-agnostic LLM client: types, FakeLLM, record/replay, and the backend factory."""

from .base import (
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMResponse,
    LLMTruncated,
    LLMUnavailable,
    Message,
    RateLimitExhausted,
    Role,
)
from .factory import make_llm
from .fake import FakeLLM
from .openai_compat import OpenAICompatClient
from .record import CassetteMiss, RecordingLLM, ReplayLLM

__all__ = [
    "Role",
    "Message",
    "LLMResponse",
    "LLMClient",
    "LLMError",
    "RateLimitExhausted",
    "LLMUnavailable",
    "LLMConfigError",
    "LLMTruncated",
    "OpenAICompatClient",
    "FakeLLM",
    "RecordingLLM",
    "ReplayLLM",
    "CassetteMiss",
    "make_llm",
]
