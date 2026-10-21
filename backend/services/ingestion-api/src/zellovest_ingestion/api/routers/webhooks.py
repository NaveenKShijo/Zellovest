"""Webhook receivers: Ramp/Okta (HMAC) + Google Drive push notifications.

- Ramp/Okta: HMAC verify -> enqueue -> ack. Zero data extraction and no GCS
  I/O on the control plane.
- Google Drive: ``changes.watch`` callback. Verifies ``X-Goog-*`` headers,
  acks ``sync`` handshakes immediately, resolves the owning tenant from the
  watch-channel mapping recorded at OAuth connect time, and enqueues a
  background pull (checkpoint + ``sync_drive_changes`` task). Always responds
  200 within 500ms; heavy work happens after the response via
  ``BackgroundTasks``.
"""

import json

import redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio
import redis.asyncio as aredis
from zellovest_ingestion.services.webhook_debounce import DebounceAction, WebhookDebounce

from zellovest_ingestion.api.deps import get_app_settings, get_db_session, get_redis_client
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.services.dispatcher import dispatch_ramp_webhook
from zellovest_ingestion.services.drive_watch import resolve_watch_tenant
from zellovest_shared.db.session import async_session_scope
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.webhooks import (
    RampWebhookEnvelope,
    WebhookAck,
    # OktaEventHookEnvelope,
)
from zellovest_shared.security.webhook import InvalidSignatureError, verify_signature
from zellovest_ingestion.services.dispatcher import dispatch_okta_signal
from zellovest_ingestion.services.okta_events import extract_okta_signal

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_ALLOWED_DRIVE_STATES = frozenset(
    {"sync", "add", "change", "update", "trash", "untrash", "delete", "move", "exists"}
)

_DEFAULT_TENANT = "default-org"
DEBOUNCE_WINDOW_SECONDS = 5.0

async def process_google_drive_notification(
    channel_id: str,
    resource_state: str,
    tenant_id: str = _DEFAULT_TENANT,
    async_database_url: str | None = None,
) -> None:
    """Background pull for a Drive push notification.

    Args:
        channel_id: ``X-Goog-Channel-ID`` owning the watch channel.
        resource_state: ``X-Goog-Resource-State`` (skips ``sync`` handshakes).
        tenant_id: Owning tenant resolved from the watch mapping at request
            time (single-tenant fallback when unmapped).
        async_database_url: DB URL for opening a fresh session. When None
            (unit tests), the pull is skipped with a warning.
    """
    from zellovest_ingestion.services.sync_dispatcher import dispatch_drive_sync

    if not async_database_url:
        logger.warning("drive_webhook_no_database", channel_id=channel_id, tenant_id=tenant_id)
        return
    try:
        async for session in async_session_scope(async_database_url):
            await dispatch_drive_sync(session, tenant_id=tenant_id)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
            break
        logger.info(
            "drive_webhook_processed",
            channel_id=channel_id,
            resource_state=resource_state,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(
            "drive_webhook_background_failed",
            channel_id=channel_id,
            error_class=type(exc).__name__,
        )

@router.post("/ramp", response_model=WebhookAck, status_code=200)
async def ramp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
    settings: IngestionAPISettings = Depends(get_app_settings),
) -> WebhookAck:
    """Receive a Ramp pushed event with HMAC verification.

       Webhooks are treated as change-detection triggers, not as events to store.
       The first webhook opens a five-second debounce window; subsequent webhooks
       during that window are acknowledged but not persisted. When the window
       closes, a single pull-sync fires for ``card_transactions`` and ``bills``.
       While a sync is running, new webhooks are ignored.

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

    tenant_id = _DEFAULT_TENANT
    # try:
    #     payload = json.loads(raw_body.decode("utf-8") or "{}")
    # except (ValueError, UnicodeDecodeError) as exc:
    #     raise HTTPException(status_code=400, detail="malformed JSON body") from exc
    # envelope = RampWebhookEnvelope.from_raw(payload if isinstance(payload, dict) else {})

    # An envelope is a wrapper/container that normalizes raw webhook 
    # payloads from different providers into one common shape.

    # Single-tenant deployments may omit tenant binding in the event; fall
    # back to an explicit header or the default tenant id.

    # As first version is single tenant
    # tenant_id = (
    #     request.headers.get("X-Tenant-Id")
    #     or (payload.get("tenant_id") if isinstance(payload, dict) else None)
    #     or "default-org"
    # )

    # sync_id, _task_id, created = await dispatch_ramp_webhook(
    #     session,
    #     tenant_id=str(tenant_id),
    #     event_id=envelope.event_id,
    #     event_type=envelope.event_type,
    #     object_id=envelope.object_id,
    # )
    # await session.commit()

    # logger.info(
    #     "webhook_accepted", tenant_id=str(tenant_id), event_id=envelope.event_id, created=created
    # )
    #

    # --- Debounce gate ---

    # async_redis = aredis.Redis.from_url(settings.redis_url, decode_responses=False)
    # debounce = WebhookDebounce(async_redis)
    redis_client = request.app.state.redis
    debounce = WebhookDebounce(redis_client)
    result = await debounce.check("ramp", tenant_id)

    if result.action == DebounceAction.IGNORE:
        logger.info("ramp_webhook_ignored", tenant_id=tenant_id, reason="sync_in_progress")
        # return WebhookAck(received=True, sync_id=None, deduped=True)
        return WebhookAck(received=True)

    if result.action == DebounceAction.JOIN_WINDOW:
        logger.info(
            "ramp_webhook_joined_window",
            tenant_id=tenant_id,
            trigger_count=result.trigger_count,
        )
        # return WebhookAck(received=True, sync_id=None, deduped=True)
        return WebhookAck(received=True)

    # OPEN_WINDOW: schedule one sync after the 5s window.
    async def _fire_ramp_sync() -> None:
        import asyncio
        from zellovest_shared.db.session import async_session_scope
        from zellovest_ingestion.services.sync_dispatcher import dispatch_sync_task

        await asyncio.sleep(DEBOUNCE_WINDOW_SECONDS)   # <-- wait 5 seconds

        await debounce.begin_sync("ramp", tenant_id)
        try:
            async for db_session in async_session_scope(settings.async_database_url):
                await dispatch_sync_task(
                    db_session,
                    tenant_id=tenant_id,
                    source="ramp",
                    entity="card_transactions",
                )
                await dispatch_sync_task(
                    db_session,
                    tenant_id=tenant_id,
                    source="ramp",
                    entity="bills",
                )
                await db_session.commit()
                break
        except Exception as exc:
            logger.error(
                "ramp_debounce_sync_failed",
                tenant_id=tenant_id,
                error_class=type(exc).__name__,
            )
        finally:
            await debounce.end_sync("ramp", tenant_id)
    background_tasks.add_task(_fire_ramp_sync)


    logger.info("Ramp Webhook window opened")

    # return WebhookAck(received=True, sync_id=str(sync_id), deduped=not created)
    return WebhookAck(received = True)


# @router.post("/okta", status_code=204, response_class=Response)
# async def okta_webhook(
#     request: Request,
#     session: AsyncSession = Depends(get_db_session),
#     settings: IngestionAPISettings = Depends(get_app_settings),
# ) -> Response:
#     """Okta Event Hook delivery. Verifies secret → validates envelope → fans out by event.eventType.
#     Returns empty 204."""
#     # 1. secret (same header GET verify uses)
#     expected = (settings.okta_webhook_secret or "").strip()
#     if expected and request.headers.get("X-Okta-Hook-Secret") != expected:
#         raise HTTPException(status_code=401, detail="invalid hook secret")
#     # 2. envelope validation (422 on malformed, not 400)
#     try:
#         envelope = OktaEventHookEnvelope.model_validate(await request.json())
#     except Exception as exc:
#         raise RequestValidationError(errors=[{"loc": ("body",),
#             "msg": str(exc), "type": "value_error"}])
#     # 3. tenant
#     tenant_id = str(request.headers.get("X-Tenant-Id") or "default")
#     # 4. per-type fan-out
#     processed, deduped, unsupported = 0, 0, 0
#     for event in envelope.data.events:
#         signal = extract_okta_signal(event)
#         if signal is None:
#             unsupported += 1
#             logger.info("okta_event_unsupported", event_type=event.eventType, uuid=event.uuid)
#             continue
#         _, _, created = await dispatch_okta_signal(session, tenant_id=tenant_id, signal=signal)
#         processed += created; deduped += (not created)
#     await session.commit()
#     logger.info("okta_webhook_accepted", tenant_id=tenant_id,
#         processed=processed, deduped=deduped, unsupported=unsupported)
#     return Response(status_code=204)

@router.post("/okta", status_code=204, response_class=Response)
async def okta_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: IngestionAPISettings = Depends(get_app_settings),
) -> Response:
    """Okta Event Hook delivery.

    Treats webhooks as pure change-detection triggers — no per-event
    checkpoint is stored. The first webhook opens a five-second debounce
    window; subsequent webhooks during that window are acknowledged (204)
    but not persisted. When the window closes, a single Okta batch pull-sync
    fires for users, apps, and logs. While a sync is running, new webhooks
    are ignored.

    Okta does not send X-Tenant-Id on POST event delivery, so all Okta
    webhooks resolve to _DEFAULT_TENANT unless you introduce your own
    event-hook-source-to-tenant mapping.
    """
    # Tenant: Okta sends no X-Tenant-Id header on POST; use default.
    tenant_id = _DEFAULT_TENANT

    # Debounce gate via Redis (app.state.redis is set in main.py lifespan)
    redis_client = request.app.state.redis
    if redis_client is not None:
        debounce = WebhookDebounce(redis_client)
        result = await debounce.check("okta", tenant_id)

        if result.action == DebounceAction.IGNORE:
            logger.info(
                "okta_webhook_ignored",
                tenant_id=tenant_id,
                reason="sync_in_progress",
            )
            return Response(status_code=204)

        if result.action == DebounceAction.JOIN_WINDOW:
            logger.info(
                "okta_webhook_joined_window",
                tenant_id=tenant_id,
                trigger_count=result.trigger_count,
            )
            return Response(status_code=204)

    # OPEN_WINDOW: schedule one Okta sync after the 5s window.
    async def _fire_okta_sync() -> None:
        await asyncio.sleep(5.0)

        debounce = WebhookDebounce(redis_client) if redis_client is not None else None
        if debounce is not None:
            await debounce.begin_sync("okta", tenant_id)
        try:
            from zellovest_shared.db.session import async_session_scope
            from zellovest_ingestion.services.sync_dispatcher import dispatch_okta_sync

            async for db_session in async_session_scope(
                settings.async_database_url
            ):
                await dispatch_okta_sync(
                    db_session,
                    tenant_id=tenant_id,
                    entities=["users", "apps", "logs"],
                )
                await db_session.commit()
                break
        except Exception as exc:
            logger.error(
                "okta_debounce_sync_failed",
                tenant_id=tenant_id,
                error_class=type(exc).__name__,
            )
        finally:
            if debounce is not None:
                await debounce.end_sync("okta", tenant_id)

    background_tasks.add_task(_fire_okta_sync)

    logger.info("okta_webhook_window_opened", tenant_id=tenant_id)
    return Response(status_code=204)


@router.get("/okta")
async def verify_okta_webhook(request: Request,
    settings: IngestionAPISettings = Depends(get_app_settings)) -> dict:
    """One-time Okta Event Hook ownership verification.

    Okta calls GET /api/v1/webhooks/okta once when you click Verify,
    with header X-Okta-Verification-Challenge. Echo it back as
    {"verification": "<challenge>"} with 200 OK.

    Ongoing event delivery always uses POST /webhooks/okta; this GET handler is only for
    verification.

    Raises:
        HTTPException: 400 if challenge header missing, 401 on bad hook secret.
    """

    # 1. Optional shared-secret check (only if you configured OKTA_WEBHOOK_SECRET).
    #    Okta sends this same header on both GET verify and POST events.
    expected = (settings.okta_webhook_secret or "").strip() if hasattr(settings,
        "okta_webhook_secret") else ""
    if expected:
        provided = request.headers.get("X-Okta-Hook-Secret")
        if provided != expected:
            logger.warning("okta_verify_bad_secret")
            raise HTTPException(status_code=401, detail="invalid hook secret")

    # 2. Extract challenge (Starlette headers are case-insensitive).
    challenge = request.headers.get("x-okta-verification-challenge")
    if not challenge:
        logger.warning("okta_verify_missing_challenge")
        raise HTTPException(status_code=400, detail="missing verification challenge")
    # 3. Echo back verbatim — Okta marks hook VERIFIED on exact match.
    logger.info("okta_verify_ok")
    return {"verification": challenge}


@router.post("/google-drive", status_code=200)
async def google_drive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: IngestionAPISettings = Depends(get_app_settings),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> dict:
    """Receive a Google Drive push notification (``changes.watch`` callback).

    Verifies ``X-Goog-Channel-ID`` / ``X-Goog-Channel-Token`` /
    ``X-Goog-Resource-State``. ``sync`` handshakes are acked immediately;
    change events resolve the owning tenant from the watch mapping recorded
    at OAuth connect time, enqueue a background pull, and return 200 within
    500ms.

    Raises:
        HTTPException: 400 on missing/invalid Goog headers, 401 on bad channel token.
    """
    channel_id = request.headers.get("X-Goog-Channel-ID")
    channel_token = request.headers.get("X-Goog-Channel-Token")
    resource_state = (request.headers.get("X-Goog-Resource-State") or "").lower()
    resource_id = request.headers.get("X-Goog-Resource-ID")
    message_number = request.headers.get("X-Goog-Message-Number")

    if not channel_id:
        logger.warning("drive_webhook_missing_channel")
        raise HTTPException(status_code=400, detail="missing X-Goog-Channel-ID")
    if not resource_state or resource_state not in _ALLOWED_DRIVE_STATES:
        logger.warning("drive_webhook_bad_state", resource_state=resource_state)
        raise HTTPException(
            status_code=400,
            detail=f"invalid X-Goog-Resource-State: {resource_state or '<missing>'}",
        )

    expected_token = (settings.google_drive_webhook_token or "").strip()
    if expected_token:
        if not channel_token or channel_token != expected_token:
            logger.warning("drive_webhook_bad_token", channel_id=channel_id)
            raise HTTPException(status_code=401, detail="invalid channel token")

    # Drain body (Drive posts an empty body); do not block on it.
    try:
        await request.body()
    except Exception:
        pass

    if resource_state == "sync":
        logger.info(
            "drive_webhook_sync_ack",
            channel_id=channel_id,
            resource_id=resource_id,
        )
        return {"received": True, "channel_id": channel_id, "resource_state": "sync"}

    try:
        tenant_id = resolve_watch_tenant(redis_client, channel_id) or _DEFAULT_TENANT
    except Exception as exc:
        logger.warning(
            "drive_watch_lookup_failed",
            channel_id=channel_id,
            error_class=type(exc).__name__,
        )
        tenant_id = _DEFAULT_TENANT

    background_tasks.add_task(
        process_google_drive_notification,
        channel_id,
        resource_state,
        tenant_id,
        settings.async_database_url if hasattr(settings, "async_database_url") else None,
    )
    logger.info(
        "drive_webhook_enqueued",
        channel_id=channel_id,
        resource_state=resource_state,
        message_number=message_number,
        tenant_id=tenant_id,
    )
    return {"received": True, "channel_id": channel_id, "resource_state": resource_state}
