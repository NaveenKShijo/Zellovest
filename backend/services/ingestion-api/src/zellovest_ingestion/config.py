"""Ingestion API configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionAPISettings(BaseSettings):
    """Settings for Ingestion & Document Ingress API."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service
    service_name: str = Field(default="ingestion-api", alias="SERVICE_NAME")
    service_port: int = Field(default=8003, alias="SERVICE_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")

    # Database
    database_url: str = Field(alias="DATABASE_URL")
    async_database_url: str = Field(alias="ASYNC_DATABASE_URL")

    # Redis / Celery
    redis_url: str = Field(alias="REDIS_URL")
    celery_queue: str = Field(default="integration_tasks", alias="CELERY_QUEUE")

    # Ramp OAuth / API
    ramp_client_id: str = Field(alias="RAMP_CLIENT_ID")
    ramp_client_secret: str = Field(alias="RAMP_CLIENT_SECRET")
    ramp_auth_url: str = Field(default="https://demo.ramp.com/v1/authorize")
    ramp_token_url: str = Field(default="https://demo-api.ramp.com/developer/v1/token")
    ramp_api_base_url: str = Field(default="https://demo-api.ramp.com")
    ramp_redirect_uri: str = Field(default="http://localhost:8003/api/v1/integrations/ramp/callback")
    ramp_webhook_secret: str = Field(alias="RAMP_WEBHOOK_SECRET")
    ramp_webhook_signature_header: str = Field(default="X-Ramp-Signature")

    # Okta API
    okta_domain: str = Field(default="", alias="OKTA_DOMAIN")
    okta_api_token: str = Field(default="", alias="OKTA_API_TOKEN")

    # Cloud Drive Connectors
    google_drive_client_id: str = Field(default="", alias="GOOGLE_DRIVE_CLIENT_ID")
    google_drive_client_secret: str = Field(default="", alias="GOOGLE_DRIVE_CLIENT_SECRET")
    google_drive_redirect_uri: str = Field(default="", alias="GOOGLE_DRIVE_REDIRECT_URI")
    dropbox_client_id: str = Field(default="", alias="DROPBOX_CLIENT_ID")
    dropbox_client_secret: str = Field(default="", alias="DROPBOX_CLIENT_SECRET")

    # Token encryption
    credentials_encryption_key: str = Field(alias="CREDENTIALS_ENCRYPTION_KEY")

    # OAuth state TTL (seconds)
    oauth_state_ttl_seconds: int = Field(default=600, alias="OAUTH_STATE_TTL_SECONDS")

    # S3
    s3_raw_bucket: str = Field(alias="S3_RAW_BUCKET")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # Ingestion tuning
    poll_batch_size: int = Field(default=100, alias="POLL_BATCH_SIZE")
    rate_limit_rps: float = Field(default=5.0, alias="RATE_LIMIT_RPS")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")

    # JWT
    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")


def get_ingestion_api_settings() -> IngestionAPISettings:
    """Get cached settings instance."""
    return IngestionAPISettings()  # type: ignore[call-arg]
