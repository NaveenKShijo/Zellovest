"""Configuration for the three logical Zellovest MCP servers.

Each server runs as its own process (ports 8101/8102/8103) and reads the same
``backend/.env`` as the other services. Deployment-specific values are
overridable per container.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


class McpServerSettings(BaseSettings):
    """Shared settings for MCP-1, MCP-2, and MCP-3."""

    model_config = SettingsConfigDict(
        env_file=(str(_BACKEND_ENV_FILE), ".env"), extra="ignore"
    )

    # Service identity and transport
    service_name: str = Field(default="mcp-server", alias="SERVICE_NAME")
    service_port: int = Field(default=8101, alias="SERVICE_PORT")
    host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Inbound authentication (the host is the only expected caller)
    service_token: str = Field(default="dev-internal-token", alias="MCP_SERVICE_TOKEN")
    allow_anonymous: bool = Field(default=False, alias="MCP_ALLOW_ANONYMOUS")
    default_tenant_id: str = Field(default="default-org", alias="MCP_DEFAULT_TENANT")
    default_role: str = Field(default="procurement_member", alias="MCP_DEFAULT_ROLE")

    # High-risk confirmation signing
    confirmation_secret: str = Field(default="", alias="MCP_CONFIRMATION_SECRET")

    # Guardrails
    max_result_bytes: int = Field(default=200_000, alias="MCP_MAX_RESULT_BYTES")
    max_page_text_chars: int = Field(default=120_000, alias="MCP_MAX_PAGE_TEXT_CHARS")
    audit_db_enabled: bool = Field(default=True, alias="MCP_AUDIT_DB_ENABLED")
    audit_timeout_seconds: float = Field(default=2.0, alias="MCP_AUDIT_TIMEOUT_SECONDS")

    # MCP-1 / MCP-2 dependencies (shared settings also read these)
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    gcs_raw_bucket: str = Field(default="", alias="GCS_RAW_BUCKET")
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")

    # MCP-3 external integrations (all optional; absence is reported honestly)
    erp_base_url: str = Field(default="", alias="ERP_BASE_URL")
    erp_api_token: str = Field(default="", alias="ERP_API_TOKEN")
    erp_timeout_seconds: float = Field(default=15.0, alias="ERP_TIMEOUT_SECONDS")
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")
    slack_search_token: str = Field(default="", alias="SLACK_SEARCH_TOKEN")
    slack_default_channel: str = Field(default="", alias="SLACK_DEFAULT_CHANNEL")
    slack_timeout_seconds: float = Field(default=10.0, alias="SLACK_TIMEOUT_SECONDS")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from_address: str = Field(default="", alias="SMTP_FROM_ADDRESS")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_timeout_seconds: float = Field(default=15.0, alias="SMTP_TIMEOUT_SECONDS")


@lru_cache(maxsize=1)
def get_mcp_settings() -> McpServerSettings:
    """Return the process-wide MCP settings (cached)."""
    return McpServerSettings()  # type: ignore[call-arg]
