"""Google Drive push-channel bookkeeping (Redis).

Drive push notifications carry no tenant identifier — only
``X-Goog-Channel-ID``. At watch-creation time (OAuth callback) we persist two
mappings so the webhook can route back to the owning tenant and the status
endpoint can report watch health:

- ``drive:watch:{channel_id}`` -> ``tenant_id`` (webhook routing).
- ``drive:channel:{tenant_id}`` -> JSON ``{channel_id, resource_id,
  expiration}`` (watch health for status).

Drive caps push-channel lifetime, so entries expire (``WATCH_TTL_SECONDS``);
re-running OAuth (or a renewal job) re-establishes the channel.
"""

from __future__ import annotations

import json
import uuid
from typing import Callable

import redis

from zellovest_ingestion.services.drive_client import (
    GoogleDriveClient,
    GoogleDriveError,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

DRIVE_PROVIDER = "google_drive"

WATCH_TTL_SECONDS = 30 * 24 * 3600


def _watch_key(channel_id: str) -> str:
    """Redis key routing a channel id back to its tenant."""
    return f"drive:watch:{channel_id}"


def _tenant_key(tenant_id: str) -> str:
    """Redis key holding a tenant's active watch description."""
    return f"drive:channel:{tenant_id}"


def _decode(raw: object) -> str | None:
    """Decode a Redis payload to str."""
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def resolve_watch_tenant(redis_client: redis.Redis, channel_id: str) -> str | None:
    """Return the tenant owning a watch channel, if mapped.

    Args:
        redis_client: Redis client.
        channel_id: ``X-Goog-Channel-ID`` from the webhook.

    Returns:
        Tenant id, or None when the channel is unknown (expired/never mapped).
    """
    return _decode(redis_client.get(_watch_key(channel_id)))


def get_drive_watch(redis_client: redis.Redis, tenant_id: str) -> dict | None:
    """Return the tenant's recorded watch description, if any.

    Args:
        redis_client: Redis client.
        tenant_id: Tenant to inspect.

    Returns:
        Dict with ``channel_id``/``resource_id``/``expiration``, or None.
    """
    raw = _decode(redis_client.get(_tenant_key(tenant_id)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("drive_watch_state_corrupt", tenant_id=tenant_id)
        return None
    return data if isinstance(data, dict) else None


def ensure_drive_watch(
    redis_client: redis.Redis,
    *,
    tenant_id: str,
    access_token: str,
    webhook_callback_url: str,
    webhook_token: str | None = None,
    client_factory: Callable[[str], GoogleDriveClient] | None = None,
) -> dict | None:
    """Create a ``changes.watch`` push channel and persist the routing mapping.

    Best-effort: any Drive/Redis failure is logged and returns None — OAuth
    stays connected and pull sync (``POST /sync/google-drive``) keeps working.

    Args:
        redis_client: Redis client for the channel mappings.
        tenant_id: Owning tenant.
        access_token: Fresh Drive OAuth access token (never logged/stored).
        webhook_callback_url: Public ``.../api/v1/webhooks/google-drive`` URL.
        webhook_token: Shared secret echoed as the watch ``token``.
        client_factory: Injectable ``access_token -> client`` factory (tests).

    Returns:
        Watch description dict, or None when setup was skipped/failed.
    """
    if not webhook_callback_url:
        logger.warning("drive_watch_skipped_no_callback", tenant_id=tenant_id)
        return None
    factory = client_factory or (lambda token: GoogleDriveClient(access_token=token))
    try:
        client = factory(access_token)
        start_token = client.get_start_page_token()
        channel_id = uuid.uuid4().hex
        watch = client.watch_changes(
            channel_id=channel_id,
            webhook_url=webhook_callback_url,
            page_token=start_token,
            token=webhook_token or None,
        )
    except GoogleDriveError as exc:
        logger.warning("drive_watch_setup_failed", tenant_id=tenant_id, error=str(exc))
        return None
    description = {
        "channel_id": watch.get("id", channel_id),
        "resource_id": watch.get("resourceId"),
        "expiration": watch.get("expiration"),
        "start_page_token": start_token,
    }
    try:
        pipe = redis_client.pipeline()
        pipe.setex(_watch_key(description["channel_id"]), WATCH_TTL_SECONDS, tenant_id)
        pipe.setex(_tenant_key(tenant_id), WATCH_TTL_SECONDS, json.dumps(description))
        pipe.execute()
    except Exception as exc:
        logger.warning(
            "drive_watch_persist_failed",
            tenant_id=tenant_id,
            error_class=type(exc).__name__,
        )
        return None
    logger.info("drive_watch_created", tenant_id=tenant_id, channel_id=channel_id)
    return description
