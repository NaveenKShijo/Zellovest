"""Procurement Core Service configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to backend/.env so the service boots regardless of the
# process working directory (uvicorn CWD varies between local runs).
_BACKEND_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class ProcurementCoreSettings(BaseSettings):
    """Settings for Procurement Core Service."""

    model_config = SettingsConfigDict(
        env_file=(str(_BACKEND_ENV_FILE), ".env"), extra="ignore"
    )

    # Service
    service_name: str = Field(default="procurement-core", alias="SERVICE_NAME")
    service_port: int = Field(default=8001, alias="SERVICE_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Database (inherited from shared)
    database_url: str = Field(alias="DATABASE_URL")
    async_database_url: str = Field(alias="ASYNC_DATABASE_URL")

    # Redis
    redis_url: str = Field(alias="REDIS_URL")

    # JWT
    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")

    # API
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")


def get_procurement_core_settings() -> ProcurementCoreSettings:
    """Get cached settings instance."""
    return ProcurementCoreSettings()  # type: ignore[call-arg]