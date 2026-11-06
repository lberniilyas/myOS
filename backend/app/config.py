import os
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def sqlalchemy_url(url: str) -> str:
    """Accept the plain postgres:// URLs that hosting providers (Neon, Supabase...) hand out."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    # Vercel's Neon integration sets DATABASE_URL; other integrations set POSTGRES_URL.
    database_url: str = Field(
        default="postgresql+psycopg://personal_os:personal_os@localhost:5433/personal_os",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )
    test_database_url: str = (
        "postgresql+psycopg://personal_os:personal_os@localhost:5433/personal_os_test"
    )

    # Comma-separated emails allowed to create an account. In production, sign-up is closed
    # to everyone else, so nobody who finds the URL can use your AI key.
    allowed_emails: str | None = None

    access_token_ttl_minutes: int = 60
    # Sliding: every refresh extends it, so the installed app stays signed in while it's used.
    refresh_token_ttl_days: int = 365

    # "gemini", "anthropic", or "none" (captures are stored but not processed).
    ai_provider: str = "gemini"
    # Per model call; with one fallback model a capture stays well under Vercel's 300 s limit.
    ai_timeout_seconds: float = 45.0

    gemini_api_key: str | None = None
    gemini_extraction_model: str = "gemini-3.5-flash-lite"
    gemini_assistant_model: str = "gemini-3.5-flash-lite"
    # Used once when the main model is rate limited or overloaded (common on the free tier).
    gemini_fallback_model: str | None = "gemini-3.1-flash-lite"
    gemini_thinking_level: str | None = None

    anthropic_api_key: str | None = None
    ai_extraction_model: str = "claude-opus-5-5"
    ai_extraction_effort: str = "low"
    ai_assistant_model: str = "claude-opus-5-5"
    ai_assistant_effort: str = "medium"
    ai_server_fallback: bool = True

    _normalize_urls = field_validator("database_url", "test_database_url")(sqlalchemy_url)

    @property
    def is_production(self) -> bool:
        # Vercel and Render set these in every deployment, so a forgotten APP_ENV can't leave
        # sign-up open or the API docs visible on the internet.
        return (
            self.app_env == "production"
            or bool(os.environ.get("VERCEL"))
            or bool(os.environ.get("RENDER"))
        )

    @property
    def serverless(self) -> bool:
        return bool(os.environ.get("VERCEL"))

    def may_register(self, email: str) -> bool:
        if not (self.allowed_emails or "").strip():
            return not self.is_production
        allowed = {item.strip().lower() for item in self.allowed_emails.split(",") if item.strip()}
        return email.strip().lower() in allowed


@lru_cache
def get_settings() -> Settings:
    return Settings()
