from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "TeleCloud Vault"
    app_env: str = "development"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/telecloud_vault"
    jwt_secret_key: str = "unsafe-development-secret-change-before-deploying"
    jwt_access_token_expire_minutes: int = 30
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_session_path: str = "./telegram"
    telegram_storage_channel_id: int | None = None
    max_upload_size_mb: int = 50
    upload_timeout_seconds: int = 300
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("telegram_api_id", "telegram_storage_channel_id", mode="before")
    @classmethod
    def empty_optional_telegram_ids_are_unset(cls, value):
        # .env.example intentionally leaves these fields blank until configured.
        return None if value == "" else value

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_setting(cls, value):
        # Some Windows environments export DEBUG=release/production rather
        # than a boolean. Treat deployment labels as disabled debug mode.
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod", "false", "0", "no", "off"}:
                return False
            if normalized in {"development", "dev", "true", "1", "yes", "on"}:
                return True
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def use_async_postgres_driver(cls, value):
        # SQLAlchemy's async engine needs asyncpg, even when a common
        # postgresql:// URL was copied into .env.
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("postgres://"):
                return "postgresql+asyncpg://" + value.removeprefix("postgres://")
            if value.startswith("postgresql://"):
                return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

settings = Settings()
