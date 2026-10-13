"""Manual upload endpoints: direct-to-GCS signed-URL leases + lease CRUD.

Flow: ``POST /uploads/init`` with file metadata (no bytes) → server
validates + inserts a ``pending`` lease row → returns a V4 PUT signed
URL → frontend PUTs bytes directly to GCS → ``POST /uploads/{id}/complete``
verifies the bytes, flips ``pending -> staged``, and enqueues the
document worker. ``GET``/``DELETE`` cover queue polling and cancel.
"""

import os
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import (
    get_app_settings,
    get_current_user,
    get_db_session,
    get_gcs_reader_dep,
    get_gcs_signer_dep,
)
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.schemas.uploads import (
    ALLOWED_MIMES_V1,
    DEFAULT_TENANT_ID,
    UploadCompleteResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadListResponse,
    UploadResponse,
    UploadStatus,
)
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus as DbUploadStatus
from zellovest_shared.db.models import User
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_client import GcsObjectReader, GcsSigner

logger = get_logger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"])

_SAFE_BASENAME_MAX_LEN = 180
_FALLBACK_FILENAME = "upload.bin"


def sanitize_filename(raw: str) -> str:
    """Strip path traversal, control chars, excess whitespace.

    Truncates to 180 chars preserving the extension; falls back to
    ``upload.bin`` when nothing usable remains.
    """
    base = os.path.basename(raw.strip())
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not base or base in {".", ".."}:
        return _FALLBACK_FILENAME
    if len(base) > _SAFE_BASENAME_MAX_LEN:
        name, dot, ext = base.rpartition(".")
        if dot and name and len(ext) <= 16:
            keep = _SAFE_BASENAME_MAX_LEN - len(ext) - 1
            base = name[:keep].rstrip() + dot + ext
        else:
            base = base[:_SAFE_BASENAME_MAX_LEN].rstrip()
    return base or _FALLBACK_FILENAME


@router.post("/init", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
async def init_upload(
    body: UploadInitRequest,
    user: User = Depends(get_current_user),  # JWT, 401 even in local dev
    settings: IngestionAPISettings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    signer: GcsSigner = Depends(get_gcs_signer_dep),  # FakeGcsSigner in tests
) -> UploadInitResponse:
    # 503 — bucket missing (startup fail-fast covers real deploys)
    if not settings.gcs_raw_bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="storage not configured",
        )
    # 413 — over GCS_MAX_UPLOAD_BYTES
    if body.size_bytes > settings.gcs_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="file too large",
        )
    # 415 — schema normalizes case; router owns the allowlist decision
    if body.mime_type not in ALLOWED_MIMES_V1:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported media type",
        )

    safe_filename = sanitize_filename(body.filename)

    # Sign a key, then persist the lease. Retry once on uuid collision.
    for attempt in (1, 2):
        upload_id = uuid4()
        gcs_key = f"uploads/{body.tenant_id}/{body.document_type}/{upload_id.hex}/{safe_filename}"
        signed_url, expires_at = signer.generate_upload_url(
            bucket=settings.gcs_raw_bucket,
            key=gcs_key,
            content_type=body.mime_type,
            expires_secs=settings.gcs_signed_url_expiry_secs,
        )
        row = UploadRow(
            id=upload_id,
            tenant_id=body.tenant_id,
            vendor_id=body.vendor_id,  # None at init — unknown until classification
            filename=safe_filename,
            gcs_key=gcs_key,
            mime_type=body.mime_type,
            size_expected=body.size_bytes,
            document_type=body.document_type,
            status=DbUploadStatus.PENDING,
            expires_at=expires_at,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning("upload_init_key_collision", tenant_id=body.tenant_id, attempt=attempt)
            if attempt == 2:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="upload key collision, retry"
                )
            continue
        break

    logger.info(
        "upload_init",
        upload_id=str(upload_id),
        tenant_id=body.tenant_id,
        gcs_key=gcs_key,
        mime_type=body.mime_type,
        size_expected=body.size_bytes,
        user_id=str(user.id),
    )
    return UploadInitResponse(
        upload_id=upload_id, gcs_key=gcs_key, signed_url=signed_url, expires_at=expires_at
    )


def _enqueue_stage_document(
    *, tenant_id: str, gcs_key: str, upload_id: str, hint: str | None
) -> str:
    """Enqueue the document staging worker (lazy import: no control/worker cycle).

    Args:
        tenant_id: Owning tenant (from the lease row, never the client).
        gcs_key: Verified object key (from the lease row).
        upload_id: Lease row id.
        hint: Uploader-supplied document type hint.

    Returns:
        Celery task id.
    """
    from zellovest_workers.tasks.document_ocr import stage_document

    return str(
        stage_document.delay(
            tenant_id=tenant_id,
            gcs_key=gcs_key,
            upload_id=upload_id,
            document_type_hint=hint,
        ).id
    )


def _to_upload_response(row: UploadRow) -> UploadResponse:
    """Map a lease row to the wire response.

    Args:
        row: Upload ORM row.

    Returns:
        UploadResponse for the row.
    """
    return UploadResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        filename=row.filename,
        document_type=row.document_type,
        status=UploadStatus(row.status.value),
        gcs_key=row.gcs_key,
        size_expected=row.size_expected,
        mime_type=row.mime_type,
        vendor_id=row.vendor_id,
        error=row.error,
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{upload_id}/complete", response_model=UploadCompleteResponse)
async def complete_upload(
    upload_id: UUID,
    user: User = Depends(get_current_user),
    settings: IngestionAPISettings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    reader: GcsObjectReader = Depends(get_gcs_reader_dep),
) -> UploadCompleteResponse:
    """Verify PUT bytes and promote a lease to staged + enqueue the worker.

    Uses only the stored ``gcs_key``/``tenant_id`` from the lease row —
    never client-supplied keys. Repeating ``complete`` on a staged lease
    is idempotent (returns current state, no duplicate enqueue).

    Args:
        upload_id: Lease row id from ``init``.
        user: Authenticated procurement member (JWT).
        settings: Service settings (GCS bucket).
        session: Async DB session.
        reader: GCS object reader (fake in tests).

    Returns:
        Completion result with actual byte size and worker task id.

    Raises:
        HTTPException: 404 unknown lease, 410 expired lease, 422 bytes
            missing/mismatched, 409 already beyond staged, 503 no bucket.
    """
    row = await session.get(UploadRow, upload_id)
    if row is None or row.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    if row.status == DbUploadStatus.STAGED:
        logger.info("upload_complete_idempotent", upload_id=str(upload_id))
        return UploadCompleteResponse(
            upload_id=row.id,
            gcs_key=row.gcs_key,
            status=UploadStatus.STAGED,
            size_actual=row.size_expected,
            task_id=None,
        )
    if row.status != DbUploadStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"upload already {row.status.value}",
        )
    now = datetime.now(UTC)
    expires_at = row.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            row.status = DbUploadStatus.FAILED
            row.error = "lease expired before complete"
            await session.commit()
            logger.info("upload_complete_expired", upload_id=str(upload_id))
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="upload lease expired")
    if not settings.gcs_raw_bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="storage not configured"
        )
    info = reader.get_object_info(bucket=settings.gcs_raw_bucket, key=row.gcs_key)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="bytes not uploaded yet: PUT to the signed URL first",
        )
    if info.size != row.size_expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"size mismatch: expected {row.size_expected}, found {info.size}",
        )
    if info.content_type.lower() != row.mime_type.lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"content-type mismatch: expected {row.mime_type}, found {info.content_type}",
        )
    row.status = DbUploadStatus.STAGED
    await session.commit()
    task_id = _enqueue_stage_document(
        tenant_id=row.tenant_id,
        gcs_key=row.gcs_key,
        upload_id=str(row.id),
        hint=row.document_type,
    )
    logger.info(
        "upload_complete",
        upload_id=str(row.id),
        tenant_id=row.tenant_id,
        gcs_key=row.gcs_key,
        size_actual=info.size,
        task_id=task_id,
        user_id=str(user.id),
    )
    return UploadCompleteResponse(
        upload_id=row.id,
        gcs_key=row.gcs_key,
        status=UploadStatus.STAGED,
        size_actual=info.size,
        task_id=task_id,
    )


@router.get("", response_model=UploadListResponse)
async def list_uploads(
    status: UploadStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UploadListResponse:
    """List upload leases for the tenant (newest first, paginated).

    Args:
        status: Optional status filter.
        page: 1-based page number.
        page_size: Rows per page (max 100).
        user: Authenticated procurement member (JWT).
        session: Async DB session.

    Returns:
        Paginated lease list.
    """
    del user
    filters = [UploadRow.tenant_id == DEFAULT_TENANT_ID]
    if status is not None:
        filters.append(UploadRow.status == DbUploadStatus(status.value))
    stmt = (
        select(UploadRow)
        .where(*filters)
        .order_by(UploadRow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    count_stmt = select(func.count()).select_from(UploadRow).where(*filters)
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(count_stmt)).scalar_one()
    return UploadListResponse(
        uploads=[_to_upload_response(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{upload_id}", response_model=UploadResponse)
async def get_upload(
    upload_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UploadResponse:
    """Fetch one upload lease by id.

    Args:
        upload_id: Lease row id.
        user: Authenticated procurement member (JWT).
        session: Async DB session.

    Returns:
        The lease.

    Raises:
        HTTPException: 404 unknown lease.
    """
    del user
    row = await session.get(UploadRow, upload_id)
    if row is None or row.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    return _to_upload_response(row)


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    upload_id: UUID,
    user: User = Depends(get_current_user),
    settings: IngestionAPISettings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    reader: GcsObjectReader = Depends(get_gcs_reader_dep),
) -> None:
    """Cancel a pending lease: best-effort GCS delete, then drop the row.

    Only ``pending`` leases may be cancelled; anything the worker may
    already own is rejected with 409.

    Args:
        upload_id: Lease row id.
        user: Authenticated procurement member (JWT).
        settings: Service settings (GCS bucket).
        session: Async DB session.
        reader: GCS object reader (fake in tests).

    Raises:
        HTTPException: 404 unknown lease, 409 non-pending lease.
    """
    row = await session.get(UploadRow, upload_id)
    if row is None or row.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    if row.status != DbUploadStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot cancel upload in status {row.status.value}",
        )
    if settings.gcs_raw_bucket:
        try:
            reader.delete_object(bucket=settings.gcs_raw_bucket, key=row.gcs_key)
        except Exception as exc:
            logger.warning(
                "upload_cancel_blob_cleanup_failed",
                upload_id=str(upload_id),
                error_class=type(exc).__name__,
            )
    await session.delete(row)
    await session.commit()
    logger.info("upload_cancelled", upload_id=str(upload_id), user_id=str(user.id))
