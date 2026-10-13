"""Process-level configuration and secrets, read from the environment.

Operational configuration that administrators change at runtime (document types, rules,
requirements, watcher folder, processing toggles) lives in the database instead; see
app/settings_store.py. Nothing here is ever sent to the desktop client.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field("development", alias="APP_ENV")
    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")

    jwt_secret: str = Field(..., alias="JWT_SECRET", min_length=32)
    session_hours: int = Field(10, alias="SESSION_HOURS")

    storage_dir: Path = Field(Path("/data/documents"), alias="STORAGE_DIR")
    storage_encryption_key: str = Field(..., alias="STORAGE_ENCRYPTION_KEY")

    max_upload_mb: int = Field(25, alias="MAX_UPLOAD_MB")
    max_pages: int = Field(15, alias="MAX_PAGES")
    render_dpi: int = Field(200, alias="RENDER_DPI")

    ocr_provider: str = Field("tesseract", alias="OCR_PROVIDER")
    tesseract_lang: str = Field("por", alias="TESSERACT_LANG")
    azure_di_endpoint: str | None = Field(None, alias="AZURE_DI_ENDPOINT")
    azure_di_key: str | None = Field(None, alias="AZURE_DI_KEY")

    ai_provider: str = Field("none", alias="AI_PROVIDER")
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    ai_model: str = Field("claude-opus-5-5", alias="AI_MODEL")
    ai_timeout_seconds: float = Field(120.0, alias="AI_TIMEOUT_SECONDS")
    ai_allow_images: bool = Field(False, alias="AI_ALLOW_IMAGES")

    watch_allowed_roots: str = Field("/watch", alias="WATCH_ALLOWED_ROOTS")

    cors_origins: str = Field(
        "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://localhost:1420",
        alias="CORS_ORIGINS",
    )

    bootstrap_admin_email: str | None = Field(None, alias="BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_password: str | None = Field(None, alias="BOOTSTRAP_ADMIN_PASSWORD")

    pipeline_version: str = "2026.10.1"

    @field_validator("ocr_provider")
    @classmethod
    def _ocr(cls, v: str) -> str:
        if v not in {"tesseract", "azure"}:
            raise ValueError("OCR_PROVIDER must be 'tesseract' or 'azure'")
        return v

    @field_validator("ai_provider")
    @classmethod
    def _ai(cls, v: str) -> str:
        if v not in {"none", "anthropic"}:
            raise ValueError("AI_PROVIDER must be 'none' or 'anthropic'")
        return v

    @property
    def allowed_watch_roots(self) -> list[Path]:
        return [Path(p).resolve() for p in self.watch_allowed_roots.split(",") if p.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        return self.ai_provider == "anthropic" and bool(self.anthropic_api_key)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
