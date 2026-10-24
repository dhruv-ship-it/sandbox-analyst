"""Application settings, loaded from the environment and .env."""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. Unknown keys in .env are ignored."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Sandbox backend selection and budget.
    sa_sandbox: Literal["modal", "fake"] = "fake"
    sa_sandbox_budget_usd: float = 0.80  # lifetime total, not monthly

    # Sandbox resource reservations (bursting above these is allowed by Modal).
    sandbox_cpu: float = 0.25
    sandbox_memory_mib: int = 1024
    sandbox_memory_hard_limit_mib: int = 2048
    sandbox_lifetime_s: int = 120
    run_timeout_s: int = 30
    max_upload_mb: int = 25

    # Modal's published Sandbox rates (1 core = 2 vCPU), used to estimate cost.
    usd_per_core_second: float = 0.00003942
    usd_per_gib_second: float = 0.00000667

    # LLM provider configuration. Not yet consumed by any code in this repo;
    # the keys are modeled here so they are never accidentally stored or
    # logged as plain strings once the LLM layer is built.
    sa_llm_provider: str | None = None
    sa_llm_model: str | None = None
    nim_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
