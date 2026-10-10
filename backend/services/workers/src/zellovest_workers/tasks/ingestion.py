"""Ingestion data-plane tasks: Ramp polling + webhook handlers, Okta sync.

Task signatures carry metadata IDs only (``tenant_id``, ``cursor``,
``event_id``, ``sync_id``). Workers fetch bytes from source APIs directly and
stream gzipped JSONL into the partitioned S3 bronze lake. Raw payloads
never touch Redis.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from celery import Task
from sqlalchemy import select
from zellovest_shared.config import get_settings
from zellovest_shared.db.models import (
    EntityType,
    IngestionSyncCheckpoint,
    SyncStatus,
    TenantIntegration,
)
from zellovest_shared.db.repository import mark_checkpoint, upsert_integration_sync
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.webhooks import OktaSignal
from zellovest_shared.security.crypto import decrypt_token, encrypt_token, generate_nonce
from zellovest_shared.workers.okta_client import (
    OktaClient,
    PermanentOktaError,
    TransientOktaError,
    refresh_access_token,
)
from zellovest_shared.workers.okta_client import (
    RateLimitError as OktaRateLimitError,
)
from zellovest_shared.workers.ramp_client import RampClient, RateLimitError, TransientRampError
from zellovest_shared.workers.s3_writer import ENTITY_FOLDERS, write_records_gz

from zellovest_workers.celery_app import QUEUE_INGESTION, celery_app

logger = get_logger(__name__)

_RETRY_KWARGS: dict[str, Any] = {
    "autoretry_for": (
        TransientRampError,
        RateLimitError,
        TransientOktaError,
        OktaRateLimitError,
        httpx.TimeoutException,
        httpx.ConnectError,
    ),
    "max_retries": 5,
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
}

_OKTA_ENTITIES = ("users", "apps", "logs")
_OKTA_S3_FOLDERS = {"users": "okta_users", "apps": "okta_apps", "logs": "okta_logs"}


def _settings() -> Any:
    """Return settings, tolerating missing env in unit-test contexts."""
    try:
        return get_settings()
    except Exception:  # pragma: no cover - tests inject fakes
        return None


def _load_access_token(session: Any, tenant_id: str, key_b64: str, provider: str = "ramp") -> str:
    """Load and decrypt the tenant's access token for one provider (in-memory only)."""
    row = session.execute(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == provider,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"no {provider} integration for tenant {tenant_id}")
    return decrypt_token(row.encrypted_access_token, row.access_nonce, key_b64)


def _load_okta_credentials(session: Any, tenant_id: str, settings: Any) -> tuple[str, str]:
    """Resolve (domain, api_token) for a tenant: per-tenant row first, env fallback.

    Kept for backward compatibility; new code should prefer
    :func:`_resolve_okta_auth`, which additionally reports the auth scheme
    (SSWS vs OAuth Bearer) and refresh material.
    """
    auth = _resolve_okta_auth(session, tenant_id, settings)
    return auth["domain"], auth["token"]


def _resolve_okta_auth(session: Any, tenant_id: str, settings: Any) -> dict[str, Any]:
    """Resolve full Okta auth material for a tenant.

    Scheme marker convention (no migration): an ``okta`` integration row
    whose stored scopes include ``offline_access`` came from the OAuth
    Connect flow and holds a short-lived Bearer token; anything else
    (SSWS API-token row, or the ``OKTA_API_TOKEN`` env fallback) uses SSWS.
    The domain always comes from deployment settings (``OKTA_DOMAIN``).

    Returns:
        Mapping with ``domain``, ``token``, ``scheme`` (``"SSWS"`` or
        ``"Bearer"``), ``refresh_token`` (possibly empty), ``scopes`` and
        ``expires_at`` (possibly None).

    Raises:
        ValueError: When domain or token cannot be resolved.
    """
    domain = (settings.okta_domain if settings else "") or ""
    token, scheme, refresh_token, expires_at, scopes = "", "SSWS", "", None, []
    row = session.execute(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == "okta",
        )
    ).scalar_one_or_none()
    if row is not None and settings is not None:
        token = decrypt_token(
            row.encrypted_access_token, row.access_nonce, settings.credentials_encryption_key
        )
        if token and "offline_access" in (row.scopes or []):
            scheme = "Bearer"
        # Pre-0009 rows have refresh_nonce NULL (nonce was discarded at
        # connect time): their refresh token is unrecoverable → Reconnect.
        if row.encrypted_refresh_token and row.refresh_nonce:
            try:
                refresh_token = decrypt_token(
                    row.encrypted_refresh_token,
                    row.refresh_nonce,
                    settings.credentials_encryption_key,
                )
            except Exception:
                refresh_token = ""
        expires_at = row.token_expires_at
        scopes = list(row.scopes or [])
    if not token and settings is not None:
        token = settings.okta_api_token or ""
        scheme = "SSWS"
    if not domain or not token:
        raise ValueError(f"Okta credentials missing for tenant {tenant_id} (need OKTA_DOMAIN + token)")
    return {
        "domain": domain,
        "token": token,
        "scheme": scheme,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "scopes": scopes,
    }


def _okta_bearer_expired(expires_at: Any, skew_seconds: int = 60) -> bool:
    """True when a Bearer token expiry timestamp has passed (with clock skew)."""
    if expires_at is None:
        return False
    aware = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    return aware <= datetime.now(UTC) + timedelta(seconds=skew_seconds)


def _refresh_okta_bearer_token(session: Any, tenant_id: str, settings: Any, auth: dict[str, Any]) -> str:
    """Renew an expired OAuth Bearer token and persist the rotated pair.

    Args:
        session: Sync DB session (committed here on success).
        tenant_id: Tenant owning the ``okta`` integration row.
        settings: Worker settings (needs the OAuth app credentials).
        auth: Mapping from :func:`_resolve_okta_auth` with a refresh token.

    Returns:
        The fresh access token.

    Raises:
        PermanentOktaError: When refresh is impossible (no app configured
            or grant revoked) — the tenant must Reconnect; do not retry.
    """
    client_id = getattr(settings, "okta_client_id", "") if settings else ""
    client_secret = getattr(settings, "okta_client_secret", "") if settings else ""
    if not client_id or not client_secret or not auth["refresh_token"]:
        raise PermanentOktaError("Okta Bearer token expired — Reconnect the integration")
    tokens = refresh_access_token(
        auth["domain"], client_id, client_secret, auth["refresh_token"]
    )
    new_refresh = tokens["refresh_token"] or auth["refresh_token"]
    key = settings.credentials_encryption_key
    access_nonce = generate_nonce()
    access_ct, _ = encrypt_token(tokens["access_token"], key, access_nonce)
    refresh_ct, refresh_nonce = encrypt_token(new_refresh, key)
    upsert_integration_sync(
        session,
        tenant_id=tenant_id,
        provider="okta",
        encrypted_access_token=access_ct,
        encrypted_refresh_token=refresh_ct,
        access_nonce=access_nonce,
        refresh_nonce=refresh_nonce,
        token_expires_at=datetime.now(UTC) + timedelta(seconds=tokens["expires_in"]),
        scopes=auth["scopes"] or None,
    )
    session.commit()
    logger.info("okta_bearer_refreshed", tenant_id=tenant_id)
    return tokens["access_token"]


def _get_checkpoint(session: Any, sync_id: str) -> IngestionSyncCheckpoint | None:
    """Fetch the checkpoint ticket for this task, if it still exists."""
    try:
        wanted = uuid.UUID(sync_id)
    except ValueError:
        return None
    return session.execute(
        select(IngestionSyncCheckpoint).where(IngestionSyncCheckpoint.sync_id == wanted)
    ).scalar_one_or_none()


def _poll_entity(
    self: Task,
    *,
    tenant_id: str,
    entity: str,
    cursor: str | None,
    sync_id: str | None,
) -> dict[str, Any]:
    """Shared keyset-polling engine: paginate Ramp -> gzip batches -> S3."""
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
    try:
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()

        access_token = _load_access_token(
            session, tenant_id, settings.credentials_encryption_key if settings else ""
        )
        client = RampClient(
            settings.ramp_api_base_url if settings else "https://api.ramp.com", access_token
        )
        batch_size = settings.poll_batch_size if settings else 100

        next_cursor = cursor
        pages = 0
        total_records = 0
        keys: list[str] = []
        while True:
            try:
                records, next_cursor = client.fetch_page(
                    entity, cursor=next_cursor, page_size=batch_size
                )
            except RateLimitError as exc:
                logger.warning("poll_rate_limited", tenant_id=tenant_id, entity=entity)
                raise self.retry(exc=exc, countdown=exc.retry_after_seconds)
            if not records:
                break
            key = write_records_gz(
                records,
                bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
                entity_folder=ENTITY_FOLDERS.get(entity, entity),
                sync_id=sync_id or "no-sync",
                suffix=f"cursor-{next_cursor or 'final'}",
                endpoint_url=settings.s3_endpoint_url if settings else None,
                region=settings.aws_region if settings else "us-east-1",
            )
            keys.append(key)
            total_records += len(records)
            pages += 1
            if checkpoint is not None:
                mark_checkpoint(
                    session, checkpoint, status=SyncStatus.RUNNING, cursor_token=next_cursor
                )
                session.commit()
            if not next_cursor:
                break

        if checkpoint is not None:
            mark_checkpoint(
                session, checkpoint, status=SyncStatus.SUCCESS, cursor_token=next_cursor
            )
            session.commit()
        logger.info(
            "poll_complete", tenant_id=tenant_id, entity=entity, pages=pages, records=total_records
        )
        return {"sync_id": sync_id, "pages": pages, "records": total_records, "keys": keys}
    except (TransientRampError, RateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except Exception as exc:
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session,
                    checkpoint,
                    status=SyncStatus.FAILED,
                    error_log=f"{type(exc).__name__}: {exc}",
                )
                session.commit()
            except Exception:
                session.rollback()
        logger.error(
            "poll_failed", tenant_id=tenant_id, entity=entity, error_class=type(exc).__name__
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_ramp_card_transactions",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_ramp_card_transactions(
    self: Task, tenant_id: str, cursor: str | None = None, sync_id: str | None = None
) -> dict[str, Any]:
    """Poll Ramp card transactions (backfill/incremental/scheduled)."""
    return _poll_entity(
        self,
        tenant_id=tenant_id,
        entity=EntityType.CARD_TRANSACTIONS.value,
        cursor=cursor,
        sync_id=sync_id,
    )


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_ramp_bills",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_ramp_bills(
    self: Task, tenant_id: str, cursor: str | None = None, sync_id: str | None = None
) -> dict[str, Any]:
    """Poll Ramp bills (backfill/incremental/scheduled)."""
    return _poll_entity(
        self, tenant_id=tenant_id, entity=EntityType.BILLS.value, cursor=cursor, sync_id=sync_id
    )


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.handle_ramp_webhook_event",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def handle_ramp_webhook_event(
    self: Task,
    tenant_id: str,
    event_id: str,
    event_type: str = "unknown",
    object_id: str | None = None,
    sync_id: str | None = None,
) -> dict[str, Any]:
    """Handle one Ramp pushed event: validate -> fetch -> gzip -> S3."""
    del self  # bound task unused beyond retry config
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
    try:
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()

        if not event_id or not tenant_id:
            raise ValueError("webhook task missing tenant_id/event_id")

        access_token = _load_access_token(
            session, tenant_id, settings.credentials_encryption_key if settings else ""
        )
        client = RampClient(
            settings.ramp_api_base_url if settings else "https://api.ramp.com", access_token
        )

        if object_id:
            record = client.fetch_object("events", object_id)
            record.setdefault("event_id", event_id)
            record.setdefault("event_type", event_type)
            records = [record]
        else:
            records = [{"event_id": event_id, "event_type": event_type, "object_id": object_id}]

        key = write_records_gz(
            records,
            bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
            entity_folder=ENTITY_FOLDERS["events"],
            sync_id=sync_id or "no-sync",
            suffix=f"event-{event_id}",
            endpoint_url=settings.s3_endpoint_url if settings else None,
            region=settings.aws_region if settings else "us-east-1",
        )
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.SUCCESS)
            session.commit()
        logger.info("webhook_handled", tenant_id=tenant_id, event_id=event_id)
        return {"sync_id": sync_id, "event_id": event_id, "key": key}
    except (TransientRampError, RateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except Exception as exc:
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session,
                    checkpoint,
                    status=SyncStatus.FAILED,
                    error_log=f"{type(exc).__name__}: {exc}",
                )
                session.commit()
            except Exception:
                session.rollback()
        logger.error(
            "webhook_failed", tenant_id=tenant_id, event_id=event_id, error_class=type(exc).__name__
        )
        raise
    finally:
        session.close()


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_okta_license_usage",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_okta_license_usage(
    self: Task,
    tenant_id: str,
    cursor: str | None = None,
    sync_id: str | None = None,
    payload: str | None = None,
) -> dict[str, Any]:
    """Sync Okta app assignments / user activity into the bronze lake.

    Supports both scheduled polling (cursor) and webhook-triggered single
    payloads. Writes normalized usage snapshots to S3 for the Zombie License
    engine to consume deterministically.
    """
    del self
    settings = _settings()
    records: list[dict[str, Any]] = []
    if payload:
        try:
            signal = OktaSignal.model_validate_json(payload)
            records = [signal.model_dump(mode="json")] if isinstance(payload, str) else [payload]
        except Exception:
            records = [{"raw": payload}]
    else:
        # TODO: implement Okta System Log / Apps API pagination with cursor.
        logger.info("okta_sync_stub", tenant_id=tenant_id, cursor=cursor)
        return {"sync_id": sync_id, "records": 0, "keys": [], "note": "okta pagination TODO"}

    key = write_records_gz(
        records,
        bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
        entity_folder="events",
        sync_id=sync_id or "no-sync",
        suffix="okta-usage",
        endpoint_url=settings.s3_endpoint_url if settings else None,
        region=settings.aws_region if settings else "us-east-1",
    )
    logger.info("okta_sync_complete", tenant_id=tenant_id, records=len(records))
    return {"sync_id": sync_id, "records": len(records), "keys": [key] if key else []}


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_okta_batch",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_okta_batch(
    self: Task,
    tenant_id: str,
    entities: list[str] | None = None,
    cursor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    page_size: int = 200,
    sync_id: str | None = None,
) -> dict[str, Any]:
    """Batch-pull Okta collections into the bronze lake (triggered by POST /sync/okta).

    Pages ``/users``, ``/apps`` and/or ``/logs`` via ``after`` cursors and
    streams each page as gzipped JSONL to S3 (``okta_users/``, ``okta_apps/``,
    ``okta_logs/``). The System Log ``after`` cursor is stored on the
    checkpoint so the next incremental run resumes where this one stopped.

    Raises:
        ValueError: On unknown entity names or missing Okta credentials.
    """
    wanted = entities or ["users", "apps", "logs"]
    unknown = [e for e in wanted if e not in _OKTA_ENTITIES]
    if unknown:
        raise ValueError(f"Unknown Okta entities: {unknown}")
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    try:
        checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()

        if not tenant_id:
            raise ValueError("batch task missing tenant_id")
        auth = _resolve_okta_auth(session, tenant_id, settings)
        domain, api_token, scheme = auth["domain"], auth["token"], auth["scheme"]
        if scheme == "Bearer" and auth["refresh_token"] and _okta_bearer_expired(auth["expires_at"]):
            # Hourly OAuth token lapsed — renew in place so the sync proceeds.
            api_token = _refresh_okta_bearer_token(session, tenant_id, settings, auth)
        client = OktaClient(domain, api_token, scheme=scheme)  # type: ignore[arg-type]
        try:
            total_records = 0
            keys: list[str] = []
            per_entity: dict[str, int] = {}
            last_cursor: str | None = None
            for entity in wanted:
                entity_records = 0
                next_cursor = cursor
                while True:
                    try:
                        records, next_cursor = client.fetch_page(
                            entity,
                            cursor=next_cursor,
                            page_size=page_size,
                            since=since if entity == "logs" else None,
                            until=until if entity == "logs" else None,
                        )
                    except OktaRateLimitError as exc:
                        logger.warning("okta_batch_rate_limited", tenant_id=tenant_id, entity=entity)
                        raise self.retry(exc=exc, countdown=exc.retry_after_seconds)
                    if not records:
                        break
                    key = write_records_gz(
                        records,
                        bucket=settings.s3_raw_bucket if settings else "tenant-bucket",
                        entity_folder=_OKTA_S3_FOLDERS[entity],
                        sync_id=sync_id or "no-sync",
                        suffix=f"okta-{entity}-cursor-{next_cursor or 'final'}",
                        endpoint_url=settings.s3_endpoint_url if settings else None,
                        region=settings.aws_region if settings else "us-east-1",
                    )
                    if key:
                        keys.append(key)
                    entity_records += len(records)
                    if checkpoint is not None and entity == "logs" and next_cursor:
                        last_cursor = next_cursor
                        mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING, cursor_token=next_cursor)
                        session.commit()
                    if not next_cursor:
                        break
                per_entity[entity] = entity_records
                total_records += entity_records

            if checkpoint is not None:
                mark_checkpoint(
                    session, checkpoint, status=SyncStatus.SUCCESS,
                    cursor_token=last_cursor or checkpoint.cursor_token,
                )
                session.commit()
            logger.info(
                "okta_batch_complete", tenant_id=tenant_id,
                records=total_records, per_entity=per_entity,
            )
            return {"sync_id": sync_id, "records": total_records, "per_entity": per_entity, "keys": keys}
        finally:
            client.close()
    except (TransientOktaError, OktaRateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except Exception as exc:
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session, checkpoint, status=SyncStatus.FAILED,
                    error_log=f"{type(exc).__name__}: {exc}",
                )
                session.commit()
            except Exception:
                session.rollback()
        logger.error(
            "okta_batch_failed", tenant_id=tenant_id, error_class=type(exc).__name__
        )
        raise
    finally:
        session.close()
