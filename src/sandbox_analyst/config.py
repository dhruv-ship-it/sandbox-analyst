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

    # LLM provider configuration.
    sa_llm_provider: Literal["nim", "groq", "fake"] = "fake"
    sa_llm_model: str | None = None
    nim_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None

    # Which prompt-text version agent/prompts.py builds (see D-095). Default
    # is the latest ("v2"); "v1" reproduces the exact prompts dev-v1-r1/r2 used.
    sa_prompt_version: Literal["v1", "v2"] = "v2"

    # LLM sampling defaults, fixed for every headline number (see D-036).
    llm_temperature: float = 1.0
    llm_top_p: float = 1.0
    llm_max_tokens: int = 4096
    llm_reasoning_effort: str = "medium"
    # max(45, ceil(2 * p95)) over successful calls in runs/llm_usage.jsonl
    # as of the P2 session (n=20, p95=70.57s) -- see D-056.
    llm_timeout_s: float = 142

    # Client-side request spacing, per provider (requests/minute).
    llm_rpm_nim: float = 30
    llm_rpm_groq: float = 25

    # --- Public API (see docs/api.md) ---
    port: int = 8000
    app_version: str | None = None  # falls back to the current git SHA if unset
    sa_data_dir: str = "data/api"  # run store traces/artifacts; /home/sa-data in production
    sa_trust_proxy: bool = False  # true behind Azure App Service's own front end

    # Upload validation for POST /api/datasets -- separate from max_upload_mb
    # above (which guards what reaches the sandbox), since this guards the
    # host-side CSV profiling step itself (see D-070).
    api_max_upload_mb: float = 5.0
    api_max_rows: int = 200_000
    api_max_cols: int = 100
    api_upload_ttl_s: int = 3600

    # Public-safety limits (see D-071).
    sa_rate_limit_per_ip_hour: int = 5
    sa_rate_limit_per_ip_day: int = 20
    sa_rate_limit_global_day: int = 50
    sa_max_concurrent_runs: int = 2
