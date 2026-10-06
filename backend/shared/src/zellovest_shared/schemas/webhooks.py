"""Minimal webhook envelopes (validated after HMAC check)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

class RampWebhookEnvelope(BaseModel):
    """Smallest viable Ramp event envelope; extra fields are ignored."""

    event_id: str = Field(min_length=1, max_length=256)
    event_type: str = Field(min_length=1, max_length=128, default="unknown")
    object_id: str | None = Field(default=None, max_length=256)
    entity: str = Field(default="events", max_length=64)
    occurred_at: str | None = Field(default=None)
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, payload: dict[str, Any]) -> "RampWebhookEnvelope":
        """Tolerantly map Ramp's varied event shapes onto the envelope."""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        event_id = (
            payload.get("event_id")
            or payload.get("id")
            or (data.get("id") if data else None)
            or "unknown"
        )
        return cls(
            event_id=str(event_id),
            event_type=str(payload.get("event_type") or payload.get("type") or "unknown"),
            object_id=(
                str(data.get("id"))
                if data and data.get("id")
                else (str(payload.get("object_id")) if payload.get("object_id") else None)
            ),
            entity=str(payload.get("entity") or "events"),
            occurred_at=payload.get("occurred_at") or payload.get("created_at"),
            data=data or {},
        )


class WebhookAck(BaseModel):
    """Immediate webhook acknowledgement (no payload echo)."""

    received: bool = True
    sync_id: str | None = None
    deduped: bool = False

class OktaActor(BaseModel):
    """Who performed the action."""
    id: str | None = None
    type: str = "User"
    alternateId: str | None = None
    displayName: str | None = None
    model_config = ConfigDict(extra="allow")

class OktaTarget(BaseModel):
    """Who/what the event acted on — user login lives here."""
    id: str | None = None
    type: str = "User"
    alternateId: str | None = None
    displayName: str | None = None
    model_config = ConfigDict(extra="allow")

class OktaEvent(BaseModel):
    """Single LogEvent inside data.events[]. eventType is the discriminator."""
    uuid: str = Field(min_length=1)
    eventType: str = Field(min_length=1)  # e.g. user.lifecycle.deactivate, user.session.start, app.user_management.*
    published: datetime
    displayMessage: str | None = None
    actor: OktaActor | None = None
    target: list[OktaTarget] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")

class OktaEventsData(BaseModel):
    events: list[OktaEvent] = Field(min_length=1)

class OktaEventHookEnvelope(BaseModel):
    """Outer POST body. Inner list holds the real events."""
    eventType: str  # always "com.okta.event_hook"
    eventId: str
    data: OktaEventsData
    model_config = ConfigDict(extra="allow")

class OktaSignal(BaseModel):
    """Normalized output consumed by M6/M2 — worker/S3 never sees raw LogEvent."""
    signal: str  # USER_LIFECYCLE | USER_LOGIN | APP_ASSIGNMENT | GROUP_MEMBERSHIP | UNSUPPORTED
    raw_event_type: str
    event_uuid: str
    occurred_at: datetime
    user_id: str | None = None
    user_login: str | None = None
    app_id: str | None = None
