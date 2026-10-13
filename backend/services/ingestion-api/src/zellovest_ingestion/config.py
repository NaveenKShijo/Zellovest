"""Ingestion API configuration."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to backend/.env so the service boots regardless of the
# process working directory (uvicorn CWD varies between local runs).
_BACKEND_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class IngestionAPISettings(BaseSettings):
    """Settings for Ingestion & Document Ingress API."""

    model_config = SettingsConfigDict(
        env_file=(str(_BACKEND_ENV_FILE), ".env"), extra="ignore"
    )

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
    okta_webhook_secret: str = Field(alias="OKTA_WEBHOOK_SECRET")

    # Okta OAuth (per-tenant Connect button, mirrors Ramp groups).
    # Endpoints are derived from OKTA_DOMAIN against the ORG authorization
    # server (https://{domain}/oauth2/v1/...) — Okta API scopes
    # (okta.users.read, ...) only mint there, never on a custom
    # (/oauth2/default/...) authorization server.
    okta_client_id: str = Field(default="", alias="OKTA_CLIENT_ID")
    okta_client_secret: str = Field(default="", alias="OKTA_CLIENT_SECRET")
    okta_redirect_uri: str = Field(
        default="http://localhost:8003/api/v1/integrations/okta/callback",
        alias="OKTA_REDIRECT_URI",
    )

    # Google Drive ingestion: OAuth (polling setup), push webhook, pull sync.
    # Mirrors the Ramp endpoint groups (integrations / webhooks / sync).
    google_drive_client_id: str = Field(default="", alias="GOOGLE_DRIVE_CLIENT_ID")
    google_drive_client_secret: str = Field(default="", alias="GOOGLE_DRIVE_CLIENT_SECRET")
    google_drive_auth_url: str = Field(
        default="https://accounts.google.com/o/oauth2/v2/auth",
        alias="GOOGLE_DRIVE_AUTH_URL",
    )
    google_drive_token_url: str = Field(
        default="https://oauth2.googleapis.com/token", alias="GOOGLE_DRIVE_TOKEN_URL"
    )
    google_drive_redirect_uri: str = Field(default="", alias="GOOGLE_DRIVE_REDIRECT_URI")
    google_drive_webhook_token: str = Field(default="", alias="GOOGLE_DRIVE_WEBHOOK_TOKEN")
    google_drive_webhook_callback_url: str = Field(
        default="", alias="GOOGLE_DRIVE_WEBHOOK_CALLBACK_URL"
    )

    # Token encryption
    credentials_encryption_key: str = Field(alias="CREDENTIALS_ENCRYPTION_KEY")

    # OAuth state TTL (seconds)
    oauth_state_ttl_seconds: int = Field(default=600, alias="OAUTH_STATE_TTL_SECONDS")

    # GCS credentials (GCP-only storage). Fail-fast: the bucket is required,
    # so the service refuses to boot without its isolated instance bucket.
    gcs_raw_bucket: str = Field(alias="GCS_RAW_BUCKET")
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    gcs_signed_url_expiry_secs: int = Field(default=900, alias="GCS_SIGNED_URL_EXPIRY_SECS")
    gcs_max_upload_bytes: int = Field(default=52428800, alias="GCS_MAX_UPLOAD_BYTES")
    google_application_credentials: str | None = Field(
        default=None, alias="GOOGLE_APPLICATION_CREDENTIALS"
    )


    # Ingestion tuning
    poll_batch_size: int = Field(default=100, alias="POLL_BATCH_SIZE")
    rate_limit_rps: float = Field(default=5.0, alias="RATE_LIMIT_RPS")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")

    # JWT
    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=60, alias="JWT_EXPIRE_MINUTES")

    @field_validator("gcs_signed_url_expiry_secs")
    @classmethod
    def _validate_expiry_secs(cls, value: int) -> int:
        """Ensure signed-URL expiry is a positive duration."""
        if value <= 0:
            raise ValueError("GCS_SIGNED_URL_EXPIRY_SECS must be positive")
        return value

    @field_validator("gcs_max_upload_bytes")
    @classmethod
    def _validate_max_upload_bytes(cls, value: int) -> int:
        """Ensure max upload size is a positive byte count."""
        if value <= 0:
            raise ValueError("GCS_MAX_UPLOAD_BYTES must be positive")
        return value


def get_ingestion_api_settings() -> IngestionAPISettings:
    """Get cached settings instance."""
    return IngestionAPISettings()  # type: ignore[call-arg]
