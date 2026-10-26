"""Ingestion data-plane tasks: Ramp polling + webhooks, Okta sync, Drive.

Task signatures carry metadata IDs only (``tenant_id``, ``cursor``,
``event_id``, ``sync_id``). Workers fetch bytes from source APIs directly and
stream gzipped JSONL into the partitioned GCS bronze lake. Raw payloads
never touch Redis.
"""

import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from celery import Task
from sqlalchemy import select
from zellovest_shared.config import get_settings
from zellovest_shared.db.models import (
    ConnectionStatus,
    EntityType,
    IngestionSyncCheckpoint,
    SyncStatus,
    TenantIntegration,
    is_integration_token_expired,
)
from zellovest_shared.db.models import (
    Upload as UploadRow,
)
from zellovest_shared.db.models import (
    UploadStatus as DbUploadStatus,
)
from zellovest_shared.db.repository import (
    mark_checkpoint,
    mark_integration_status_sync,
    upsert_integration_sync,
)
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.webhooks import OktaSignal
from zellovest_shared.security.crypto import decrypt_token, encrypt_token, generate_nonce
from zellovest_shared.workers.drive_client import (
    DriveAuthError,
    DriveCursorExpiredError,
    DriveTokenRefreshError,
    GoogleDriveClient,
    GoogleDriveError,
    refresh_drive_access_token,
)
from zellovest_shared.workers.gcs_writer import ENTITY_FOLDERS, write_bytes, write_records_gz
from zellovest_shared.workers.okta_client import (
    OktaClient,
    PermanentOktaError,
    TransientOktaError,
    refresh_access_token,
)
from zellovest_shared.workers.okta_client import (
    RateLimitError as OktaRateLimitError,
)
from zellovest_shared.workers.ramp_client import (
    PermanentRampError,
    RampClient,
    RateLimitError,
    TransientRampError,
    refresh_ramp_access_token,
)
from zellovest_shared.workers.ramp_client import (
    is_auth_failure as is_ramp_auth_failure,
)

from zellovest_workers.celery_app import QUEUE_INGESTION, celery_app

logger = get_logger(__name__)


class PermanentDriveError(RuntimeError):
    """Drive auth/config failure that retries cannot fix (reconnect needed)."""


_RETRY_KWARGS: dict[str, Any] = {
    "autoretry_for": (
        TransientRampError,
        RateLimitError,
        TransientOktaError,
        OktaRateLimitError,
        GoogleDriveError,
        httpx.TimeoutException,
        httpx.ConnectError,
    ),
    "max_retries": 5,
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
}

_OKTA_ENTITIES = ("users", "apps", "logs")
_OKTA_GCS_FOLDERS = {"users": "okta_users", "apps": "okta_apps", "logs": "okta_logs"}

_DRIVE_PROVIDER = "google_drive"
_DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
_DRIVE_PROCESSABLE_MIMES = ("application/pdf", "image/")
_DRIVE_FILENAME_MAX_LEN = 180


def _raw_bucket(settings: Any) -> str:
    """Resolve the GCS raw bucket """
    # if settings is None:
    #     return ""
    return (
        getattr(settings, "gcs_raw_bucket", "")
    )


def _gcp_project(settings: Any) -> str | None:
    """Resolve the GCP project id (None uses default credentials)."""
    # if settings is None:
    #     return None
    return getattr(settings, "google_cloud_project", "") or None


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


def _mark_provider_status(
    session: Any,
    tenant_id: str,
    provider: str,
    status: ConnectionStatus,
    error: str,
) -> None:
    """Persist an OAuth lifecycle transition best-effort (never fails the task).

    Args:
        session: Sync DB session (committed here on success).
        tenant_id: Tenant owning the integration row.
        provider: Provider key (``ramp`` / ``okta``).
        status: Target lifecycle state (EXPIRED or REVOKED).
        error: Short, secret-free reason stored as ``last_error``.
    """
    try:
        mark_integration_status_sync(
            session,
            tenant_id=tenant_id,
            provider=provider,
            status=status,
            error=error,
        )
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    logger.warning(
        "integration_marked_needs_reconnect",
        tenant_id=tenant_id,
        provider=provider,
        status=status.value,
    )


def _resolve_ramp_auth(session: Any, tenant_id: str, settings: Any) -> dict[str, Any]:
    """Resolve full Ramp OAuth material for a tenant.

    Args:
        session: Sync DB session.
        tenant_id: Tenant owning the ``ramp`` integration row.
        settings: Worker settings (encryption key).

    Returns:
        Mapping with ``token``, ``refresh_token``, ``expires_at`` and
        ``scopes``.

    Raises:
        ValueError: When no Ramp integration row exists for the tenant.
    """
    row = session.execute(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == "ramp",
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"no ramp integration for tenant {tenant_id}")
    key = settings.credentials_encryption_key if settings else ""
    token = decrypt_token(row.encrypted_access_token, row.access_nonce, key)
    refresh_token = ""
    if row.encrypted_refresh_token and row.refresh_nonce:
        try:
            refresh_token = decrypt_token(
                row.encrypted_refresh_token,
                row.refresh_nonce,
                key,
            )
        except Exception:
            refresh_token = ""
    return {
        "token": token,
        "refresh_token": refresh_token,
        "expires_at": row.token_expires_at,
        "scopes": list(row.scopes or []),
    }


def _refresh_ramp_token(
    session: Any, tenant_id: str, settings: Any, auth: dict[str, Any]
) -> str:
    """Renew an expired Ramp access token and persist the rotated pair.

    Args:
        session: Sync DB session (committed here on success).
        tenant_id: Tenant owning the ``ramp`` integration row.
        settings: Worker settings (needs the Ramp OAuth app credentials).
        auth: Mapping from :func:`_resolve_ramp_auth` with a refresh token.

    Returns:
        The fresh access token.

    Raises:
        PermanentRampError: When refresh is impossible (no app configured
            or grant revoked) — the tenant must reconnect; do not retry.
    """
    token_url = getattr(settings, "ramp_token_url", "") if settings else ""
    client_id = getattr(settings, "ramp_client_id", "") if settings else ""
    client_secret = getattr(settings, "ramp_client_secret", "") if settings else ""
    if not token_url or not client_id or not client_secret or not auth["refresh_token"]:
        _mark_provider_status(
            session,
            tenant_id,
            "ramp",
            ConnectionStatus.EXPIRED,
            "Ramp access token expired — reconnect the integration",
        )
        raise PermanentRampError("Ramp access token expired — reconnect the integration")
    try:
        tokens = refresh_ramp_access_token(
            token_url, client_id, client_secret, auth["refresh_token"]
        )
    except PermanentRampError as exc:
        _mark_provider_status(
            session,
            tenant_id,
            "ramp",
            ConnectionStatus.REVOKED,
            f"Ramp refresh rejected — reconnect required ({exc})",
        )
        raise PermanentRampError(
            "Ramp refresh rejected — reconnect the integration in /integrations"
        ) from exc
    new_refresh = str(tokens.get("refresh_token") or "") or auth["refresh_token"]
    key = settings.credentials_encryption_key
    access_nonce = generate_nonce()
    access_ct, _ = encrypt_token(str(tokens["access_token"]), key, access_nonce)
    refresh_ct, refresh_nonce = encrypt_token(new_refresh, key)
    upsert_integration_sync(
        session,
        tenant_id=tenant_id,
        provider="ramp",
        encrypted_access_token=access_ct,
        encrypted_refresh_token=refresh_ct,
        access_nonce=access_nonce,
        refresh_nonce=refresh_nonce,
        token_expires_at=datetime.now(UTC) + timedelta(seconds=int(tokens["expires_in"])),
        scopes=auth["scopes"] or None,
    )
    session.commit()
    logger.info("ramp_token_refreshed", tenant_id=tenant_id)
    return str(tokens["access_token"])


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
        raise ValueError(
            f"Okta credentials missing for tenant {tenant_id} (need OKTA_DOMAIN + token)"
        )
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


def _refresh_okta_bearer_token(
    session: Any, tenant_id: str, settings: Any, auth: dict[str, Any]
) -> str:
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
        _mark_provider_status(
            session,
            tenant_id,
            "okta",
            ConnectionStatus.EXPIRED,
            "Okta access token expired — reconnect the integration",
        )
        raise PermanentOktaError("Okta Bearer token expired — Reconnect the integration")
    try:
        tokens = refresh_access_token(
            auth["domain"], client_id, client_secret, auth["refresh_token"]
        )
    except PermanentOktaError as exc:
        _mark_provider_status(
            session,
            tenant_id,
            "okta",
            ConnectionStatus.REVOKED,
            f"Okta refresh rejected — reconnect required ({exc})",
        )
        raise PermanentOktaError(
            "Okta refresh rejected — reconnect the integration in /integrations"
        ) from exc
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


def _drive_folder_ids(settings: Any) -> list[str]:
    """Return configured Drive folder ids (comma-separated env value)."""
    raw = getattr(settings, "google_drive_folder_ids", "") if settings else ""
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _safe_drive_filename(raw: str) -> str:
    """Sanitize a Drive file name for use in a GCS object key.

    Args:
        raw: Drive ``name`` field (may contain slashes/control chars).

    Returns:
        A safe basename, truncated to preserve the extension when possible.
    """
    base = str(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not base or base in {".", ".."}:
        return "drive-file"
    if len(base) > _DRIVE_FILENAME_MAX_LEN:
        stem, dot, ext = base.rpartition(".")
        if dot and stem and len(ext) <= 16:
            keep = _DRIVE_FILENAME_MAX_LEN - len(ext) - 1
            base = stem[:keep].rstrip() + dot + ext
        else:
            base = base[:_DRIVE_FILENAME_MAX_LEN].rstrip()
    return base or "drive-file"


def _is_drive_folder(file: dict[str, Any]) -> bool:
    """Return True when a Drive list entry is a folder (not a document)."""
    return str(file.get("mimeType") or "") == _DRIVE_FOLDER_MIME


def _is_processable_drive_file(file: dict[str, Any]) -> bool:
    """Return True for PDF/image files the OCR worker can consume."""
    mime_type = str(file.get("mimeType") or "")
    return bool(file.get("id")) and mime_type.startswith(_DRIVE_PROCESSABLE_MIMES)


def _drive_change_record(
    *,
    tenant_id: str,
    sync_id: str | None,
    file: dict[str, Any],
    removed: bool,
    change_time: str | None,
) -> dict[str, Any]:
    """Build one tenant-tagged bronze record for a Drive file/change."""
    record: dict[str, Any] = {
        "tenant_id": tenant_id,
        "source": _DRIVE_PROVIDER,
        "sync_id": sync_id,
        "removed": removed,
        "change_time": change_time,
    }
    record.update(file)
    return record


def _resolve_drive_auth(session: Any, tenant_id: str, settings: Any) -> dict[str, Any]:
    """Resolve full Google Drive OAuth material for a tenant.

    Args:
        session: Sync DB session.
        tenant_id: Tenant owning the ``google_drive`` integration row.
        settings: Worker settings (encryption key).

    Returns:
        Mapping with ``token``, ``refresh_token``, ``expires_at`` and
        ``scopes``.

    Raises:
        ValueError: When no Drive integration row exists for the tenant.
    """
    row = session.execute(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == _DRIVE_PROVIDER,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"no {_DRIVE_PROVIDER} integration for tenant {tenant_id}")
    key = settings.credentials_encryption_key if settings else ""
    token = decrypt_token(row.encrypted_access_token, row.access_nonce, key)
    refresh_token = ""
    if row.encrypted_refresh_token and row.refresh_nonce:
        try:
            refresh_token = decrypt_token(
                row.encrypted_refresh_token,
                row.refresh_nonce,
                key,
            )
        except Exception:
            refresh_token = ""
    return {
        "token": token,
        "refresh_token": refresh_token,
        "expires_at": row.token_expires_at,
        "scopes": list(row.scopes or []),
    }


def _refresh_drive_token(
    session: Any, tenant_id: str, settings: Any, auth: dict[str, Any]
) -> str:
    """Renew an expired Drive access token and persist the rotated pair.

    Args:
        session: Sync DB session (committed here on success).
        tenant_id: Tenant owning the ``google_drive`` integration row.
        settings: Worker settings (needs the Google OAuth app credentials).
        auth: Mapping from :func:`_resolve_drive_auth` with a refresh token.

    Returns:
        The fresh access token.

    Raises:
        PermanentDriveError: When refresh is impossible (no app configured
            or the grant was revoked) — the tenant must reconnect.
    """
    token_url = (
        getattr(settings, "google_drive_token_url", "") if settings else ""
    ) or "https://oauth2.googleapis.com/token"
    client_id = getattr(settings, "google_drive_client_id", "") if settings else ""
    client_secret = getattr(settings, "google_drive_client_secret", "") if settings else ""
    if not client_id or not client_secret or not auth["refresh_token"]:
        _mark_provider_status(
            session,
            tenant_id,
            _DRIVE_PROVIDER,
            ConnectionStatus.EXPIRED,
            "Google Drive access token expired — reconnect the integration",
        )
        raise PermanentDriveError(
            "Google Drive access token expired — reconnect the integration"
        )
    try:
        tokens = refresh_drive_access_token(
            token_url,
            client_id,
            client_secret,
            auth["refresh_token"],
        )
    except DriveTokenRefreshError as exc:
        _mark_provider_status(
            session,
            tenant_id,
            _DRIVE_PROVIDER,
            ConnectionStatus.REVOKED,
            f"Google Drive refresh rejected — reconnect required ({exc})",
        )
        raise PermanentDriveError(
            "Google Drive refresh rejected — reconnect the integration in /integrations"
        ) from exc

    new_refresh = str(tokens.get("refresh_token") or "") or auth["refresh_token"]
    key = settings.credentials_encryption_key
    access_nonce = generate_nonce()
    access_ct, _ = encrypt_token(str(tokens["access_token"]), key, access_nonce)
    refresh_ct, refresh_nonce = encrypt_token(new_refresh, key)
    upsert_integration_sync(
        session,
        tenant_id=tenant_id,
        provider=_DRIVE_PROVIDER,
        encrypted_access_token=access_ct,
        encrypted_refresh_token=refresh_ct,
        access_nonce=access_nonce,
        refresh_nonce=refresh_nonce,
        token_expires_at=datetime.now(UTC)
        + timedelta(seconds=int(tokens.get("expires_in") or 3600)),
        scopes=auth["scopes"] or None,
    )
    session.commit()
    logger.info("drive_token_refreshed", tenant_id=tenant_id)
    return str(tokens["access_token"])


def _drive_gcs_key(tenant_id: str, file: dict[str, Any]) -> str:
    """Build the tenant-isolated GCS key for one Drive file."""
    file_id = str(file.get("id") or "unknown")
    filename = _safe_drive_filename(str(file.get("name") or file_id))
    return f"drive/{tenant_id}/{file_id}/{filename}"


def _fan_out_drive_file(
    session: Any,
    client: GoogleDriveClient,
    settings: Any,
    *,
    tenant_id: str,
    file: dict[str, Any],
    force_reprocess: bool = False,
) -> bool:
    """Copy one Drive file to GCS and enqueue OCR/extraction.

    The upload lease is flipped to ``processing`` before the document task is
    enqueued (mirrors ``stage_document``) so duplicate change records cannot
    double-process a file.

    Args:
        force_reprocess: When True, ignore the existing PENDING/PROCESSING
            lease and re-download + re-upload + re-enqueue the file. Used by
            full backfills so a previously-stuck file is not skipped forever.

    Returns:
        True when a new processing task was enqueued.
    """
    if not _is_processable_drive_file(file):
        logger.debug(
            "drive_file_not_processable",
            tenant_id=tenant_id,
            file_id=str(file.get("id") or ""),
            mime_type=str(file.get("mimeType") or ""),
        )
        return False
    file_id = str(file.get("id") or "")
    mime_type = str(file.get("mimeType") or "application/octet-stream")
    filename = _safe_drive_filename(str(file.get("name") or file_id))
    gcs_key = _drive_gcs_key(tenant_id, file)
    row = session.execute(
        select(UploadRow).where(UploadRow.gcs_key == gcs_key)
    ).scalar_one_or_none()
    if (
        not force_reprocess
        and row is not None
        and row.status in (DbUploadStatus.PENDING, DbUploadStatus.PROCESSING)
    ):
        logger.info("drive_file_already_processing", tenant_id=tenant_id, file_id=file_id)
        return False

    # Download with retry for transient transport/API errors. Full backfills
    # page through potentially large file sets; a single flaky download must
    # not silently skip every remaining document.
    data: bytes | None = None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            data = client.download_file(file_id)
            break
        except DriveAuthError:
            raise
        except GoogleDriveError as exc:
            last_exc = exc
            logger.warning(
                "drive_file_download_failed",
                tenant_id=tenant_id,
                file_id=file_id,
                attempt=attempt + 1,
                error_class=type(exc).__name__,
            )
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
    if data is None:
        logger.warning(
            "drive_file_download_failed_all_retries",
            tenant_id=tenant_id,
            file_id=file_id,
            error_class=type(last_exc).__name__ if last_exc else "unknown",
        )
        return False
    if not data:
        logger.warning("drive_file_empty", tenant_id=tenant_id, file_id=file_id)
        return False
    try:
        write_bytes(
            data,
            bucket=_raw_bucket(settings),
            key=gcs_key,
            content_type=mime_type,
            project=_gcp_project(settings),
        )
    except Exception as exc:
        logger.warning(
            "drive_file_gcs_write_failed",
            tenant_id=tenant_id,
            file_id=file_id,
            error_class=type(exc).__name__,
        )
        return False

    if row is None:
        row = UploadRow(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            filename=filename,
            gcs_key=gcs_key,
            mime_type=mime_type,
            size_expected=len(data),
            document_type="other",
            status=DbUploadStatus.PROCESSING,
            expires_at=None,
        )
        session.add(row)
    else:
        row.filename = filename
        row.mime_type = mime_type
        row.size_expected = len(data)
        row.status = DbUploadStatus.PROCESSING
        row.error = None
    session.commit()

    try:
        from zellovest_workers.tasks.document_ocr import process_document

        process_document.delay(
            tenant_id=tenant_id,
            gcs_key=gcs_key,
            document_type_hint=None,
            upload_id=str(row.id),
        )
    except Exception as exc:
        row.status = DbUploadStatus.FAILED
        row.error = f"enqueue failed: {type(exc).__name__}"
        session.commit()
        raise
    logger.info("drive_file_fanned_out", tenant_id=tenant_id, file_id=file_id, gcs_key=gcs_key)
    return True


def _write_drive_records(
    records: list[dict[str, Any]],
    settings: Any,
    *,
    sync_id: str | None,
    suffix: str,
) -> str | None:
    """Write a Drive metadata batch to the bronze lake (no-op when empty)."""
    if not records:
        return None
    return write_records_gz(
        records,
        bucket=_raw_bucket(settings),
        entity_folder=ENTITY_FOLDERS["documents"],
        sync_id=sync_id or "no-sync",
        suffix=suffix,
        project=_gcp_project(settings),
    )


def _sync_drive_full(
    session: Any,
    client: GoogleDriveClient,
    settings: Any,
    *,
    tenant_id: str,
    sync_id: str | None,
    page_size: int,
) -> tuple[str, int, int, int, list[str], dict[str, Any]]:
    """Run a full Drive backfill and return the cursor for later increments.

    Every discovered file is recorded to the bronze lake. Processable files
    (PDF/image) are downloaded to GCS and fanned out to OCR. Per-file
    failures are logged and skipped so one bad file cannot abort the entire
    backfill.

    Returns:
        Tuple of (start cursor, pages, records, processed, keys, stats).
    """
    start_token = client.get_start_page_token()
    folder_ids = _drive_folder_ids(settings)
    targets: list[str | None] = list(folder_ids) if folder_ids else [None]
    seen: set[str] = set()
    pages = 0
    total_records = 0
    total_processed = 0
    total_skipped = 0
    keys: list[str] = []
    for target_index, folder_id in enumerate(targets):
        page_token: str | None = None
        while True:
            files, page_token = client.list_files(
                folder_id=folder_id,
                page_size=page_size,
                page_token=page_token,
            )
            pages += 1
            records: list[dict[str, Any]] = []
            for file in files:
                file_id = str(file.get("id") or "")
                if file_id and file_id in seen:
                    continue
                if file_id:
                    seen.add(file_id)
                records.append(
                    _drive_change_record(
                        tenant_id=tenant_id,
                        sync_id=sync_id,
                        file=file,
                        removed=False,
                        change_time=None,
                    )
                )
                if _is_drive_folder(file):
                    total_skipped += 1
                    continue
                try:
                    fanned = _fan_out_drive_file(
                        session,
                        client,
                        settings,
                        tenant_id=tenant_id,
                        file=file,
                        force_reprocess=True,
                    )
                except Exception as exc:
                    logger.exception(
                        "drive_full_sync_file_failed",
                        tenant_id=tenant_id,
                        file_id=file_id,
                        file_name=str(file.get("name") or ""),
                        error_class=type(exc).__name__,
                    )
                    total_skipped += 1
                    continue
                if fanned:
                    total_processed += 1
                else:
                    total_skipped += 1
            key = _write_drive_records(
                records,
                settings,
                sync_id=sync_id,
                suffix=f"drive-full-{target_index}-page-{pages}",
            )
            if key:
                keys.append(key)
            total_records += len(records)
            if not page_token:
                break
    logger.info(
        "drive_full_sync_summary",
        tenant_id=tenant_id,
        sync_id=sync_id,
        pages=pages,
        records=total_records,
        processed=total_processed,
        skipped=total_skipped,
        folders=folder_ids or ["*"],
    )
    if total_records > 0 and total_processed == 0:
        logger.warning(
            "drive_full_sync_no_files_processed",
            tenant_id=tenant_id,
            sync_id=sync_id,
            records=total_records,
            folders=folder_ids or ["*"],
        )
    return start_token, pages, total_records, total_processed, keys, {
        "mode": "full",
        "folders": folder_ids or ["*"],
    }


def _sync_drive_changes(
    session: Any,
    client: GoogleDriveClient,
    settings: Any,
    checkpoint: IngestionSyncCheckpoint | None,
    *,
    tenant_id: str,
    cursor: str,
    sync_id: str | None,
    page_size: int,
) -> tuple[str, int, int, int, list[str], dict[str, Any]]:
    """Page ``changes.list`` from a cursor, writing records and fanning out.

    Every discovered change is recorded to the bronze lake. Processable files
    (PDF/image) are downloaded to GCS and fanned out to OCR. Per-file
    failures are logged and skipped so one bad file cannot abort the sync.

    Returns:
        Tuple of (next cursor, pages, records, processed, keys, stats).
    """
    token = cursor
    pages = 0
    total_records = 0
    total_processed = 0
    total_skipped = 0
    keys: list[str] = []
    processed_ids: set[str] = set()
    while True:
        changes, next_page, new_start = client.list_changes_page(
            token,
            page_size=page_size,
        )
        pages += 1
        records: list[dict[str, Any]] = []
        for change in changes:
            file = change.get("file") or {}
            file_id = str(change.get("fileId") or file.get("id") or "")
            removed = bool(change.get("removed"))
            records.append(
                _drive_change_record(
                    tenant_id=tenant_id,
                    sync_id=sync_id,
                    file=file or {"id": file_id},
                    removed=removed,
                    change_time=str(change.get("time") or "") or None,
                )
            )
            if (
                file_id not in processed_ids
                and not removed
                and not file.get("trashed")
                and not _is_drive_folder(file)
            ):
                processed_ids.add(file_id)
                try:
                    fanned = _fan_out_drive_file(
                        session, client, settings, tenant_id=tenant_id, file=file
                    )
                except Exception as exc:
                    logger.exception(
                        "drive_inc_sync_file_failed",
                        tenant_id=tenant_id,
                        file_id=file_id,
                        file_name=str(file.get("name") or ""),
                        error_class=type(exc).__name__,
                    )
                    total_skipped += 1
                    continue
                if fanned:
                    total_processed += 1
                else:
                    total_skipped += 1
            else:
                total_skipped += 1
        key = _write_drive_records(
            records,
            settings,
            sync_id=sync_id,
            suffix=f"drive-changes-page-{pages}",
        )
        if key:
            keys.append(key)
        total_records += len(records)
        next_cursor = next_page or new_start
        if checkpoint is not None and next_cursor:
            mark_checkpoint(
                session,
                checkpoint,
                status=SyncStatus.RUNNING,
                cursor_token=next_cursor,
            )
            session.commit()
        if next_page:
            token = next_page
            continue
        token = new_start or token
        break
    logger.info(
        "drive_inc_sync_summary",
        tenant_id=tenant_id,
        sync_id=sync_id,
        pages=pages,
        records=total_records,
        processed=total_processed,
        skipped=total_skipped,
        cursor=token,
    )
    return token, pages, total_records, total_processed, keys, {"mode": "incremental"}


def _mark_drive_checkpoint_failed(
    session: Any,
    checkpoint: IngestionSyncCheckpoint | None,
    error_log: str,
) -> None:
    """Best-effort FAILED transition for a Drive checkpoint."""
    if checkpoint is None:
        return
    try:
        mark_checkpoint(session, checkpoint, status=SyncStatus.FAILED, error_log=error_log)
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass


def _sync_drive(
    self: Task,
    *,
    tenant_id: str,
    cursor: str | None,
    sync_id: str | None,
    page_size: int,
) -> dict[str, Any]:
    """Shared Drive pull-sync engine: auth -> pages -> GCS -> OCR fan-out."""
    del self  # bound task unused beyond retry config
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
    try:
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()
        if not tenant_id:
            raise ValueError("drive task missing tenant_id")

        auth = _resolve_drive_auth(session, tenant_id, settings)
        access_token = auth["token"]
        if is_integration_token_expired(auth["expires_at"]):
            if not auth["refresh_token"]:
                _mark_provider_status(
                    session,
                    tenant_id,
                    _DRIVE_PROVIDER,
                    ConnectionStatus.EXPIRED,
                    "Google Drive access token expired — reconnect the integration",
                )
                raise PermanentDriveError(
                    "Google Drive access token expired — reconnect the integration"
                )
            access_token = _refresh_drive_token(session, tenant_id, settings, auth)

        client = GoogleDriveClient(access_token=access_token)
        try:
            if cursor:
                try:
                    result = _sync_drive_changes(
                        session,
                        client,
                        settings,
                        checkpoint,
                        tenant_id=tenant_id,
                        cursor=cursor,
                        sync_id=sync_id,
                        page_size=page_size,
                    )
                except DriveCursorExpiredError:
                    logger.warning(
                        "drive_cursor_expired_reseeding",
                        tenant_id=tenant_id,
                        sync_id=sync_id,
                    )
                    result = _sync_drive_full(
                        session,
                        client,
                        settings,
                        tenant_id=tenant_id,
                        sync_id=sync_id,
                        page_size=page_size,
                    )
            else:
                result = _sync_drive_full(
                    session,
                    client,
                    settings,
                    tenant_id=tenant_id,
                    sync_id=sync_id,
                    page_size=page_size,
                )
        finally:
            client.close()

        final_cursor, pages, total_records, total_processed, keys, stats = result
        if checkpoint is not None:
            mark_checkpoint(
                session,
                checkpoint,
                status=SyncStatus.SUCCESS,
                cursor_token=final_cursor,
            )
            session.commit()
        logger.info(
            "drive_sync_complete",
            tenant_id=tenant_id,
            sync_id=sync_id,
            pages=pages,
            records=total_records,
            processed=total_processed,
            **stats,
        )
        return {
            "sync_id": sync_id,
            "cursor": final_cursor,
            "pages": pages,
            "records": total_records,
            "processed": total_processed,
            "keys": keys,
            **stats,
        }
    except DriveAuthError as exc:
        # Google rejected the access token. Before forcing a reconnect,
        # attempt a refresh-token grant so the user does not have to
        # re-authorize when only the short-lived access token lapsed.
        if auth.get("refresh_token"):
            try:
                refreshed = _refresh_drive_token(
                    session, tenant_id, settings, auth
                )
                client = GoogleDriveClient(access_token=refreshed)
                try:
                    if cursor:
                        try:
                            result = _sync_drive_changes(
                                session,
                                client,
                                settings,
                                checkpoint,
                                tenant_id=tenant_id,
                                cursor=cursor,
                                sync_id=sync_id,
                                page_size=page_size,
                            )
                        except DriveCursorExpiredError:
                            logger.warning(
                                "drive_cursor_expired_reseeding",
                                tenant_id=tenant_id,
                                sync_id=sync_id,
                            )
                            result = _sync_drive_full(
                                session,
                                client,
                                settings,
                                tenant_id=tenant_id,
                                sync_id=sync_id,
                                page_size=page_size,
                            )
                    else:
                        result = _sync_drive_full(
                            session,
                            client,
                            settings,
                            tenant_id=tenant_id,
                            sync_id=sync_id,
                            page_size=page_size,
                        )
                finally:
                    client.close()

                final_cursor, pages, total_records, total_processed, keys, stats = result
                if checkpoint is not None:
                    mark_checkpoint(
                        session,
                        checkpoint,
                        status=SyncStatus.SUCCESS,
                        cursor_token=final_cursor,
                    )
                    session.commit()
                logger.info(
                    "drive_sync_complete_after_refresh",
                    tenant_id=tenant_id,
                    sync_id=sync_id,
                    pages=pages,
                    records=total_records,
                    processed=total_processed,
                    **stats,
                )
                return {
                    "sync_id": sync_id,
                    "cursor": final_cursor,
                    "pages": pages,
                    "records": total_records,
                    "processed": total_processed,
                    "keys": keys,
                    **stats,
                }
            except (PermanentDriveError, DriveTokenRefreshError) as refresh_exc:
                logger.warning(
                    "drive_refresh_failed_forcing_reconnect",
                    tenant_id=tenant_id,
                    sync_id=sync_id,
                    error_class=type(refresh_exc).__name__,
                )
        _mark_provider_status(
            session,
            tenant_id,
            _DRIVE_PROVIDER,
            ConnectionStatus.REVOKED,
            f"Google Drive auth rejected — reconnect required ({exc})",
        )
        _mark_drive_checkpoint_failed(
            session,
            checkpoint,
            "Google Drive auth rejected — reconnect the integration in /integrations",
        )
        raise PermanentDriveError(
            "Google Drive access token expired or revoked — "
            "reconnect the integration in /integrations"
        ) from exc
    except PermanentDriveError as exc:
        _mark_drive_checkpoint_failed(session, checkpoint, str(exc))
        raise
    except Exception as exc:
        _mark_drive_checkpoint_failed(
            session,
            checkpoint,
            f"{type(exc).__name__}: {exc}",
        )
        logger.error(
            "drive_sync_failed",
            tenant_id=tenant_id,
            sync_id=sync_id,
            error_class=type(exc).__name__,
        )
        raise
    finally:
        session.close()


def _poll_entity(
    self: Task,
    *,
    tenant_id: str,
    entity: str,
    cursor: str | None,
    sync_id: str | None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Shared keyset-polling engine: paginate Ramp -> gzip batches -> GCS."""
    settings = _settings()
    factory = get_session_factory()
    session = factory()
    checkpoint = _get_checkpoint(session, sync_id or "") if sync_id else None
    try:
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.RUNNING)
            session.commit()

        auth = _resolve_ramp_auth(session, tenant_id, settings)
        access_token = auth["token"]
        if auth["refresh_token"] and is_integration_token_expired(auth["expires_at"]):
            # Hourly OAuth token lapsed — renew in place so the sync proceeds.
            access_token = _refresh_ramp_token(session, tenant_id, settings, auth)
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
                    entity, cursor=next_cursor, page_size=batch_size,
                    start_date=date_from, end_date=date_to
                )
            except RateLimitError as exc:
                logger.warning("poll_rate_limited", tenant_id=tenant_id, entity=entity)
                raise self.retry(exc=exc, countdown=exc.retry_after_seconds)
            if not records:
                break
            key = write_records_gz(
                records,
                bucket=_raw_bucket(settings),
                entity_folder=ENTITY_FOLDERS.get(entity, entity),
                sync_id=sync_id or "no-sync",
                suffix=f"cursor-{next_cursor or 'final'}",
                project=_gcp_project(settings),
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
    except PermanentRampError as exc:
        if is_ramp_auth_failure(exc):
            _mark_provider_status(
                session,
                tenant_id,
                "ramp",
                ConnectionStatus.REVOKED,
                f"Ramp auth rejected — reconnect required ({exc})",
            )
            if checkpoint is not None:
                try:
                    mark_checkpoint(
                        session,
                        checkpoint,
                        status=SyncStatus.FAILED,
                        error_log="Ramp auth rejected — reconnect the integration in /integrations",
                    )
                    session.commit()
                except Exception:
                    session.rollback()
            raise PermanentRampError(
                "Ramp access token expired or revoked — "
                "reconnect the integration in /integrations"
            ) from exc
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
    self: Task, tenant_id: str, cursor: str | None = None, sync_id: str | None = None,
    date_from: str | None = None, date_to: str | None = None
) -> dict[str, Any]:
    """Poll Ramp card transactions (backfill/incremental/scheduled)."""
    return _poll_entity(
        self,
        tenant_id=tenant_id,
        entity=EntityType.CARD_TRANSACTIONS.value,
        cursor=cursor,
        sync_id=sync_id,
        date_from = date_from, date_to=date_to
    )


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_ramp_bills",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_ramp_bills(
    self: Task, tenant_id: str, cursor: str | None = None, sync_id: str | None = None,
    date_from: str | None = None, date_to: str | None = None
) -> dict[str, Any]:
    """Poll Ramp bills (backfill/incremental/scheduled)."""
    return _poll_entity(
        self, tenant_id=tenant_id, entity=EntityType.BILLS.value, cursor=cursor, sync_id=sync_id,
        date_from=date_from, date_to=date_to
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
    """Handle one Ramp pushed event: validate -> fetch -> gzip -> GCS."""
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

        auth = _resolve_ramp_auth(session, tenant_id, settings)
        access_token = auth["token"]
        if auth["refresh_token"] and is_integration_token_expired(auth["expires_at"]):
            access_token = _refresh_ramp_token(session, tenant_id, settings, auth)
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
            bucket=_raw_bucket(settings),
            entity_folder=ENTITY_FOLDERS["events"],
            sync_id=sync_id or "no-sync",
            suffix=f"event-{event_id}",
            project=_gcp_project(settings),
        )
        if checkpoint is not None:
            mark_checkpoint(session, checkpoint, status=SyncStatus.SUCCESS)
            session.commit()
        logger.info("webhook_handled", tenant_id=tenant_id, event_id=event_id)
        return {"sync_id": sync_id, "event_id": event_id, "key": key}
    except (TransientRampError, RateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except PermanentRampError as exc:
        if is_ramp_auth_failure(exc):
            _mark_provider_status(
                session,
                tenant_id,
                "ramp",
                ConnectionStatus.REVOKED,
                f"Ramp auth rejected — reconnect required ({exc})",
            )
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session,
                    checkpoint,
                    status=SyncStatus.FAILED,
                    error_log="Ramp auth rejected — reconnect the integration in /integrations",
                )
                session.commit()
            except Exception:
                session.rollback()
        raise PermanentRampError(
            "Ramp access token expired or revoked — "
            "reconnect the integration in /integrations"
        ) from exc
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
    payloads. Writes normalized usage snapshots to GCS for the Zombie License
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
        bucket=_raw_bucket(settings),
        entity_folder="events",
        sync_id=sync_id or "no-sync",
        suffix="okta-usage",
        project=_gcp_project(settings),
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
    streams each page as gzipped JSONL to GCS (``okta_users/``, ``okta_apps/``,
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
        if (
            scheme == "Bearer"
            and auth["refresh_token"]
            and _okta_bearer_expired(auth["expires_at"])
        ):
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
                        logger.warning(
                            "okta_batch_rate_limited", tenant_id=tenant_id, entity=entity
                        )
                        raise self.retry(exc=exc, countdown=exc.retry_after_seconds)
                    if not records:
                        break
                    key = write_records_gz(
                        records,
                        bucket=_raw_bucket(settings),
                        entity_folder=_OKTA_GCS_FOLDERS[entity],
                        sync_id=sync_id or "no-sync",
                        suffix=f"okta-{entity}-cursor-{next_cursor or 'final'}",
                        project=_gcp_project(settings),
                    )
                    if key:
                        keys.append(key)
                    entity_records += len(records)
                    if checkpoint is not None and entity == "logs" and next_cursor:
                        last_cursor = next_cursor
                        mark_checkpoint(
                            session,
                            checkpoint,
                            status=SyncStatus.RUNNING,
                            cursor_token=next_cursor,
                        )
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
            return {
                "sync_id": sync_id,
                "records": total_records,
                "per_entity": per_entity,
                "keys": keys,
            }
        finally:
            client.close()
    except (TransientOktaError, OktaRateLimitError, httpx.TimeoutException, httpx.ConnectError):
        raise
    except PermanentOktaError as exc:
        _mark_provider_status(
            session,
            tenant_id,
            "okta",
            ConnectionStatus.REVOKED,
            f"Okta auth rejected — reconnect required ({exc})",
        )
        if checkpoint is not None:
            try:
                mark_checkpoint(
                    session, checkpoint, status=SyncStatus.FAILED,
                    error_log="Okta auth rejected — reconnect the integration in /integrations",
                )
                session.commit()
            except Exception:
                session.rollback()
        raise PermanentOktaError(
            "Okta access token expired or revoked — "
            "reconnect the integration in /integrations"
        ) from exc
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


@celery_app.task(
    name="zellovest.workers.tasks.ingestion.sync_drive_changes",
    bind=True,
    queue=QUEUE_INGESTION,
    **_RETRY_KWARGS,
)
def sync_drive_changes(
    self: Task,
    tenant_id: str,
    cursor: str | None = None,
    sync_id: str | None = None,
    page_size: int = 100,
) -> dict[str, Any]:
    """Pull Google Drive changes into the bronze lake and fan out documents.

    Triggered by ``POST /api/v1/sync/google-drive`` and Drive push
    notifications. With no cursor (first connect / full import) the worker
    seeds ``changes.getStartPageToken`` and pages ``files.list``; subsequent
    runs page ``changes.list`` from the checkpoint cursor. PDFs/images are
    copied to GCS and enqueued on ``document_tasks`` for OCR/extraction.

    Args:
        tenant_id: Tenant owning the ``google_drive`` integration.
        cursor: ``changes.list`` pageToken override; None means full import.
        sync_id: Checkpoint ticket id for resumable cursor bookkeeping.
        page_size: Drive page size (1-1000).

    Returns:
        Summary dict with cursor, page/record counts, and GCS keys.
    """
    return _sync_drive(
        self,
        tenant_id=tenant_id,
        cursor=cursor,
        sync_id=sync_id,
        page_size=min(max(int(page_size or 100), 1), 1000),
    )
