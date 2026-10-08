"""Central application settings loaded from environment.

All secrets are fail-fast validated at startup via pydantic-settings.
Single-tenant isolation: each deployment owns its database; ``tenant_id``
uniqueness guards against duplicate rows within the instance.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for all microservices."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment
    environment: str = Field(default="local")

    # Database
    database_url: str = Field(alias="DATABASE_URL")
    async_database_url: str = Field(alias="ASYNC_DATABASE_URL")

    # Redis / Celery
    redis_url: str = Field(alias="REDIS_URL")
    celery_queue: str = Field(default="integration_tasks", alias="CELERY_QUEUE")

    # Ramp OAuth / API
    ramp_client_id: str = Field(alias="RAMP_CLIENT_ID")
    ramp_client_secret: str = Field(alias="RAMP_CLIENT_SECRET")
    ramp_auth_url: str = Field(alias="RAMP_AUTH_URL")
    ramp_token_url: str = Field(alias="RAMP_TOKEN_URL")
    ramp_api_base_url: str = Field(alias="RAMP_API_BASE_URL")
    ramp_redirect_uri: str = Field(alias="RAMP_REDIRECT_URI")
    ramp_webhook_secret: str = Field(alias="RAMP_WEBHOOK_SECRET")
    ramp_webhook_signature_header: str = Field(
        default="X-Ramp-Signature", alias="RAMP_WEBHOOK_SIGNATURE_HEADER"
    )

    # Okta API
    okta_domain: str = Field(default="", alias="OKTA_DOMAIN")
    okta_api_token: str = Field(default="", alias="OKTA_API_TOKEN")
    # Okta OAuth app (per-tenant Connect flow; also used by workers to
    # refresh expiring Bearer tokens without asking the user to reconnect).
    okta_client_id: str = Field(default="", alias="OKTA_CLIENT_ID")
    okta_client_secret: str = Field(default="", alias="OKTA_CLIENT_SECRET")

    # Token encryption: base64-encoded 32-byte key for AES-256-GCM.
    credentials_encryption_key: str = Field(alias="CREDENTIALS_ENCRYPTION_KEY")

    # OAuth state TTL (seconds)
    oauth_state_ttl_seconds: int = Field(default=600, alias="OAUTH_STATE_TTL_SECONDS")

    # Object storage — S3 bronze lake (legacy, kept for backward compat
    # with workers/tests referencing `settings.s3_raw_bucket`).
    s3_raw_bucket: str = Field(default="tenant-bucket", alias="S3_RAW_BUCKET")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # Object storage — GCS raw bucket (signed-URL direct upload path).
    gcs_raw_bucket: str = Field(default="", alias="GCS_RAW_BUCKET")
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    gcs_signed_url_expiry_secs: int = Field(
        default=900, alias="GCS_SIGNED_URL_EXPIRY_SECS"
    )
    gcs_max_upload_bytes: int = Field(
        default=52428800, alias="GCS_MAX_UPLOAD_BYTES"
    )
    google_application_credentials: str | None = Field(
        default=None, alias="GOOGLE_APPLICATION_CREDENTIALS"
    )

    # Vector DB
    vector_db_url: str = Field(default="", alias="VECTOR_DB_URL")
    vector_db_api_key: str = Field(default="", alias="VECTOR_DB_API_KEY")

    # LLM / AI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    llm_model: str = Field(default="gpt-4-turbo", alias="LLM_MODEL")

    # Document AI
    document_ai_project_id: str = Field(default="", alias="DOCUMENT_AI_PROJECT_ID")
    document_ai_location: str = Field(default="us", alias="DOCUMENT_AI_LOCATION")
    document_ai_processor_id: str = Field(default="", alias="DOCUMENT_AI_PROCESSOR_ID")

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

    @field_validator("credentials_encryption_key")
    @classmethod
    def _validate_key_length(cls, value: str) -> str:
        """Ensure the decoded key is exactly 32 bytes (AES-256)."""
        import base64

        try:
            raw = base64.b64decode(value)
        except Exception as exc:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY must be valid base64") from exc
        if len(raw) != 32:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY must decode to 32 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance (fail-fast on missing secrets)."""
    return Settings()  # type: ignore[call-arg]
