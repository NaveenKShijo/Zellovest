"""Auth schemas for the ingestion gateway (mirrors procurement-core)."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Authenticate with email + password."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    """Public user profile (never includes the password hash)."""

    id: str
    email: str
    name: str
    role: str
    tenant_id: str


class AuthResponse(BaseModel):
    """Login success envelope: JWT + profile."""

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserResponse


class InviteCreateRequest(BaseModel):
    """Invite a teammate by email (authenticated members only)."""

    email: str = Field(min_length=3, max_length=320)


class InviteResponse(BaseModel):
    """Created invitation: raw token shown to the inviter exactly once."""

    email: str
    invite_token: str
    expires_at: str


class InviteValidateResponse(BaseModel):
    """Public validity check for an invite link."""

    email: str
    expires_at: str


class InviteAcceptRequest(BaseModel):
    """Claim an invitation: token + chosen name + password."""

    token: str = Field(min_length=16, max_length=128)
    name: str = Field(default="", max_length=256)
    password: str = Field(min_length=8, max_length=128)
