"""Ramp/Okta webhook receivers: HMAC verify → enqueue → ack.

Performs zero data extraction and no S3 I/O. Only the event envelope
(``tenant_id``, ``event_id``, ``object_id``) crosses into Redis; the
Celery data plane re-fetches bytes from the source API.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_app_settings, get_db_session
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.services.dispatcher import dispatch_okta_webhook, dispatch_ramp_webhook
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.webhooks import RampWebhookEnvelope, WebhookAck
from zellovest_shared.security.webhook import InvalidSignatureError, verify_signature

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/ramp", response_model=WebhookAck, status_code=200)
async def ramp_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: IngestionAPISettings = Depends(get_app_settings),
) -> WebhookAck:
    """Receive a Ramp pushed event with HMAC verification.

    Raises:
        HTTPException: 401 on bad signature, 400 on malformed JSON.
    """
    raw_body = await request.body()
    signature = request.headers.get(settings.ramp_webhook_signature_header) or request.headers.get(
        settings.ramp_webhook_signature_header.lower()
    )
    try:
        verify_signature(settings.ramp_webhook_secret, raw_body, signature)
    except InvalidSignatureError as exc:
        logger.warning("webhook_bad_signature")
        raise HTTPException(status_code=401, detail="invalid webhook signature") from exc

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="malformed JSON body") from exc
    envelope = RampWebhookEnvelope.from_raw(payload if isinstance(payload, dict) else {})

    # Single-tenant deployments may omit tenant binding in the event; fall
    # back to an explicit header or the default tenant id.
    tenant_id = (
        request.headers.get("X-Tenant-Id")
        or (payload.get("tenant_id") if isinstance(payload, dict) else None)
        or "default"
    )
    sync_id, _task_id, created = await dispatch_ramp_webhook(
        session,
        tenant_id=str(tenant_id),
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        object_id=envelope.object_id,
    )
    await session.commit()
    logger.info(
        "webhook_accepted", tenant_id=str(tenant_id), event_id=envelope.event_id, created=created
    )
    return WebhookAck(received=True, sync_id=str(sync_id), deduped=not created)


@router.post("/okta", response_model=WebhookAck, status_code=202)
async def okta_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> WebhookAck:
    """Handle Okta webhook events (user lifecycle, app assignments)."""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        logger.error("okta_webhook_invalid_payload", error_class=type(exc).__name__)
        raise HTTPException(status_code=400, detail="malformed JSON body") from exc

    tenant_id = (
        request.headers.get("X-Tenant-Id")
        or (payload.get("tenant_id") if isinstance(payload, dict) else None)
        or "default"
    )
    sync_id, _task_id, created = await dispatch_okta_webhook(
        session, tenant_id=str(tenant_id), payload=payload
    )
    await session.commit()
    logger.info("okta_webhook_accepted", event_type=payload.get("eventType"), created=created)
    return WebhookAck(received=True, sync_id=str(sync_id), deduped=not created)
