from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    app_name: str = "Tatparya API"
    app_env: str = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    console_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    sql_log_level: Literal["WARNING", "ERROR", "CRITICAL"] = "WARNING"
    log_dir: Path = Path("logs")
    log_max_bytes: int = Field(default=5_000_000, gt=0)
    log_backup_count: int = Field(default=5, ge=1, le=20)
    sql_echo: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: PostgresDsn
    frontend_url: str = "http://localhost:5173"
    admin_emails: str = ""
    langsmith_project_url: str = ""
    google_client_id: str = ""
    langsmith_enabled: bool = False
    default_llm_provider: Literal["gemini", "groq", "openai", "anthropic"] = "gemini"
    langsmith_detail_mode: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "insightforge"
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)
    refresh_token_expire_days: int = Field(default=7, gt=0)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, gt=0)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from_email: str = ""
    smtp_from_name: str = "Tatparya"
    support_email: str = ""
    smtp_use_tls: bool = True
    cloudinary_cloud_name: str = Field(min_length=1)
    cloudinary_api_key: SecretStr = Field(min_length=1)
    cloudinary_api_secret: SecretStr = Field(min_length=1)
    max_upload_size_mb: int = Field(default=25, gt=0)
    max_profile_rows: int = Field(default=500_000, gt=0)
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    groq_api_key: SecretStr | None = None
    groq_model: str | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None
    anthropic_max_tokens: int = Field(default=8192, gt=0, le=64_000)
    razorpay_key_id: str = ""
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_request_timeout_seconds: int = Field(default=15, gt=0, le=60)
    llm_request_timeout_seconds: int = Field(default=60, gt=0, le=300)
    max_expanded_file_mb: int = Field(default=100, gt=0, le=512)
    max_dataset_columns: int = Field(default=200, gt=0, le=1000)

    @model_validator(mode="after")
    def production_safety(self):
        if self.app_env.lower() in {"production", "prod"}:
            if self.debug or self.sql_echo or self.langsmith_detail_mode:
                raise ValueError("Production requires DEBUG, SQL_ECHO and LANGSMITH_DETAIL_MODE=false.")
            if not self.frontend_url.startswith("https://"):
                raise ValueError("Production FRONTEND_URL must use HTTPS.")
            if "change" in self.jwt_secret_key.get_secret_value().lower():
                raise ValueError("Replace the example JWT secret before deployment.")
        return self

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg_driver(cls, value: object) -> object:
        """Accept managed Postgres URLs while keeping sync and async SQLAlchemy compatible."""
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
