"""Integration/OAuth API request/response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class IntegrationStatus(BaseModel):
    """Current integration connection status."""

    tenant_id: str
    provider: str
    connected: bool
    connection_status: Literal["ACTIVE", "EXPIRED", "REVOKED", "DISCONNECTED"]
    token_expires_at: str | None = None
    scopes: list[str] | None = None
    last_error: str | None = None
    updated_at: str | None = None


class OAuthStartRequest(BaseModel):
    """Request to start OAuth flow."""

    tenant_id: str = Field(..., min_length=1, max_length=128)
    provider: Literal["ramp", "okta", "google_drive", "dropbox"] = "ramp"
    redirect_uri: str | None = None
    scopes: list[str] | None = None


class OAuthStartResponse(BaseModel):
    """Response with OAuth authorization URL."""

    authorization_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    """OAuth callback parameters."""

    code: str
    state: str


class ConnectRequest(BaseModel):
    """Manual connect request binding the OAuth flow to a tenant."""

    tenant_id: str = Field(default="default-org", min_length=1, max_length=128)
    scopes: list[str] | None = None


class ConnectResponse(BaseModel):
    """Authorization URL + CSRF state for the caller to redirect."""

    authorization_url: str
    state: str
    expires_in: int


class TokenExchangeResult(BaseModel):
    """Normalized OAuth token endpoint response (never logged in full)."""

    access_token: str = Field(min_length=1)
    refresh_token: str = Field(default="")
    expires_in: int = Field(default=3600)
    scopes: list[str] = Field(default_factory=list)
