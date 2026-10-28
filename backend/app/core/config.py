"""Application settings from environment variables or backend/.env.

Shared by every backend module. Fields change only through the integration owner;
names match backend/.env.example. Secrets are SecretStr so they never print by accident.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # hide_input_in_errors: a validation error at startup must never echo a provider key into the logs.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    frontend_origins: str = "http://localhost:3000"

    auth_mode: Literal["supabase", "dev"] = "dev"
    supabase_url: str | None = None
    supabase_jwt_secret: SecretStr | None = None
    # Server-side Storage credential (ASSET_STORAGE_BACKEND=supabase). Never sent to the browser or logged.
    supabase_secret_key: SecretStr | None = None

    database_url: str = "sqlite+aiosqlite:///./nativeproof.db"

    llm_primary_provider: Literal["nebius"] = "nebius"
    nebius_api_key: SecretStr | None = None
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    nebius_default_model: str | None = None
    nebius_fast_model: str | None = None
    nebius_reasoning_model: str | None = None
    llm_fallback_enabled: bool = False
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str | None = None
    openrouter_default_model: str | None = None
    llm_request_timeout_seconds: float = 60
    llm_max_retries: int = 2

    qloo_api_key: SecretStr | None = None
    # Unset = the official default host (https://api.qloo.com). Set it only when the event key belongs to another
    # Qloo host, e.g. https://hackathon.api.qloo.com (docs/04 A.9).
    qloo_base_url: str | None = None
    # auto (unset) = the official harness (`qloo exec`) when Node and the pinned harness exist, else direct REST.
    qloo_transport: Literal["auto", "harness", "rest"] | None = None
    qloo_bin: str = "qloo"
    qloo_timeout_seconds: float = 30

    # Capability routing (docs/15_MODEL_SELECTION.md). Model ids must be verified by real inference first.
    embedding_provider: Literal["nebius", "openrouter"] = "nebius"
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    vision_provider: Literal["nebius", "openrouter"] = "nebius"
    vision_model: str | None = None
    rerank_provider: Literal["nebius", "openrouter"] | None = None
    rerank_model: str | None = None

    # Uploaded assets (contracts/README section 13)
    # database: bytes in a table (local development and tests); supabase: a private Supabase Storage bucket
    asset_storage_backend: Literal["database", "supabase"] = "database"
    max_image_bytes: int = 5 * 1024 * 1024  # migration 0006 sets the bucket's file_size_limit to the same value

    max_active_runs_per_user: int = 2
    # Work limit for one population study run; a larger request is refused with 422, never silently reduced.
    population_max_participants: int = 600

    @field_validator(
        "supabase_url",
        "supabase_jwt_secret",
        "supabase_secret_key",
        "nebius_api_key",
        "nebius_default_model",
        "nebius_fast_model",
        "nebius_reasoning_model",
        "openrouter_api_key",
        "openrouter_base_url",
        "openrouter_default_model",
        "qloo_api_key",
        "qloo_base_url",
        "qloo_transport",
        "embedding_model",
        "embedding_dimensions",
        "vision_model",
        "rerank_model",
        "rerank_provider",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `NEBIUS_API_KEY=` in a .env file means "not configured", not an empty credential.
        return None if isinstance(value, str) and not value.strip() else value

    # A field validator, not a model validator: its error input is just the auth mode, never the full settings
    # input (which holds provider keys), so even `ValidationError.errors()` cannot leak a secret.
    @field_validator("auth_mode")
    @classmethod
    def _dev_auth_outside_production_only(cls, value: str, info: ValidationInfo) -> str:
        if value == "dev" and info.data.get("app_env") == "production":
            raise ValueError("AUTH_MODE=dev is refused when APP_ENV=production.")
        return value

    # Fail at startup, naming only the missing settings (the key is declared above, so info.data holds it).
    @field_validator("asset_storage_backend")
    @classmethod
    def _supabase_storage_needs_credentials(cls, value: str, info: ValidationInfo) -> str:
        if value == "supabase" and not (info.data.get("supabase_url") and info.data.get("supabase_secret_key")):
            raise ValueError("ASSET_STORAGE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SECRET_KEY.")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
