"""Document Explorer read endpoints over uploads + extraction artifacts.

Read-only surface for the front-end Document Explorer:
- ``GET  /documents`` — paginated inventory with type/status/vendor/search filters.
- ``GET  /documents/{id}`` — detail (properties + parsed extraction artifact).
- ``GET  /documents/{id}/file`` — short-lived V4 GET signed URL for inline preview.

Data sources: the ``uploads`` lease is the inventory of every object in the
tenant's GCS raw bucket (manual + Drive). The ``extraction_artifacts`` row
carries the persisted pipeline output metadata; the bulky payload
(entities/pages/tables/provenance) is read from GCS on detail only.
Mirrors the uploads router: JWT auth, tenant fixed to the deployment
tenant (V1), snake_case wire, fakes for tests.
"""

import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import (
    get_app_settings,
    get_current_user,
    get_db_session,
    get_gcs_reader_dep,
    get_gcs_signer_dep,
)
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.schemas.documents import (
    DocumentDetailResponse,
    DocumentFileResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentStatus,
    derived_status,
    normalized_doc_types,
)
from zellovest_ingestion.schemas.uploads import DEFAULT_TENANT_ID
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.models import ExtractionArtifact
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.models import UploadStatus as DbUploadStatus
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

_PROCESSING_STATUSES = (
    DbUploadStatus.PENDING,
    DbUploadStatus.STAGED,
    DbUploadStatus.PROCESSING,
)


def _escaped_like(term: str) -> str:
    """Escape LIKE wildcards so user search matches literals only."""
    return f"%{term.replace('%', r'\%').replace('_', r'\_')}%"


async def _resolve_vendor_filter(
    session: AsyncSession, value: str
) -> Any:
    """Build the vendor_id filter for one user-supplied vendor token.

    User-facing semantics: the token may be a vendor *name* (expected in the
    UI), a vendor UUID (deep links), or a raw string tag (e.g. Ramp ids).

    Resolution order:
    1. UUID → filter by that id directly.
    2. Name substring match (case-insensitive) against ``vendors.name`` →
       filter by the union of matching ids (plus the raw token for legacy
       rows whose ``vendor_id`` is a human-readable tag).
    3. No name matches → filter by raw equality (yields an empty page).

    Args:
        session: Async DB session.
        value: User-supplied vendor token.

    Returns:
        A SQLAlchemy boolean expression for ``uploads.vendor_id``.
    """
    try:
        return UploadRow.vendor_id == str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        pass
    stmt = select(Vendor.id).where(
        Vendor.name.ilike(_escaped_like(value), escape="\\")
    )
    rows = (await session.execute(stmt)).all()
    matching_ids = [str(row[0]) for row in rows]
    return or_(
        UploadRow.vendor_id.in_(matching_ids),
        UploadRow.vendor_id == value,
    )


async def _vendor_names(
    session: AsyncSession, vendor_ids: set[str]
) -> dict[str, str]:
    """Resolve ``uploads.vendor_id`` strings to vendor display names.

    Vendor ids are stored as opaque strings; when one is a UUID matching a
    ``vendors.id`` row the canonical name is returned. Anything else is
    passed through untouched (raw tag) for display.

    Args:
        session: Async DB session.
        vendor_ids: Distinct non-empty vendor ids from the page rows.

    Returns:
        Map of raw vendor_id to display name (no entry when unresolved).
    """
    if not vendor_ids:
        return {}
    parseable: list[uuid.UUID] = []
    for raw in vendor_ids:
        try:
            parseable.append(uuid.UUID(raw))
        except (ValueError, AttributeError):
            continue
    if not parseable:
        return {}
    stmt = select(Vendor.id, Vendor.name).where(Vendor.id.in_(parseable))
    rows = (await session.execute(stmt)).all()
    return {str(vendor_id): name for vendor_id, name in rows}


def _to_document_item(
    row: UploadRow, artifact: ExtractionArtifact | None, vendor_name: str | None
) -> DocumentItem:
    """Map one lease (+ optional artifact) to an explorer list item.

    Args:
        row: Upload lease row.
        artifact: Matching extraction artifact row, when persisted.
        vendor_name: Resolved vendor display name, when resolvable.

    Returns:
        DocumentItem for the explorer list/detail payload.
    """
    item_vendor_name = vendor_name
    if item_vendor_name is None and row.vendor_id:
        # Non-UUID vendor ids surface as their own tag (e.g. Ramp id).
        item_vendor_name = row.vendor_id
    return DocumentItem(
        id=row.id,
        tenant_id=row.tenant_id,
        filename=row.filename,
        document_type=row.document_type,
        document_type_confidence=row.document_type_confidence,
        classification_method=row.classification_method,
        status=derived_status(row.status.value, artifact.extraction_confidence if artifact else None),
        upload_status=row.status.value,
        vendor_id=row.vendor_id,
        vendor_name=item_vendor_name,
        gcs_key=row.gcs_key,
        mime_type=row.mime_type,
        size_bytes=row.size_expected,
        page_count=None,
        error=row.error,
        has_artifact=artifact is not None,
        artifact_gcs_key=artifact.artifact_gcs_key if artifact else None,
        route=artifact.route if artifact else None,
        file_type=artifact.file_type if artifact else None,
        extraction_method=artifact.extraction_method if artifact else None,
        extraction_confidence=(
            float(artifact.extraction_confidence) if artifact and artifact.extraction_confidence is not None else None
        ),
        text_chars=artifact.text_chars if artifact else None,
        uploaded_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    document_type: str | None = Query(default=None, max_length=32),
    document_types: str | None = Query(default=None, max_length=128),
    status_filter: DocumentStatus | None = Query(default=None, alias="status"),
    vendor_id: str | None = Query(default=None, max_length=128),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: Any = Depends(get_current_user),  # JWT, 401 even in local dev
    session: AsyncSession = Depends(get_db_session),
) -> DocumentListResponse:
    """List the tenant's documents (explorer inventory, newest first).

    Args:
        document_type: Exact doc-type filter (lowercase wire value).
        document_types: Comma-separated doc types for multi-type tabs,
            e.g. ``policy,other`` (``document_type`` wins when both set).
        status_filter: Derived pill filter (extracted/review_needed/failed/processing).
        vendor_id: Vendor tag filter.
        search: Literal substring match on filename.
        page: 1-based page number.
        page_size: Rows per page (max 100).
        user: Authenticated procurement member (JWT).
        session: Async DB session.

    Returns:
        Paginated document list with derived statuses and vendor tags.
    """
    del user
    filters = [UploadRow.tenant_id == DEFAULT_TENANT_ID]
    artifact_conf = func.coalesce(
        ExtractionArtifact.extraction_confidence, -1.0
    )
    if document_type:
        normalized = document_type.strip().lower()
        filters.append(func.lower(UploadRow.document_type) == normalized)
    elif document_types:
        allowed = normalized_doc_types(document_types)
        if allowed:
            filters.append(func.lower(UploadRow.document_type).in_(allowed))
    if vendor_id:
        filters.append(await _resolve_vendor_filter(session, vendor_id))
    if search:
        filters.append(UploadRow.filename.ilike(_escaped_like(search), escape="\\"))
    if status_filter is not None:
        if status_filter == DocumentStatus.FAILED:
            filters.append(UploadRow.status == DbUploadStatus.FAILED)
        elif status_filter == DocumentStatus.PROCESSING:
            filters.append(UploadRow.status.in_(_PROCESSING_STATUSES))
        elif status_filter == DocumentStatus.EXTRACTED:
            filters.append(UploadRow.status == DbUploadStatus.COMPLETED)
            filters.append(artifact_conf >= 0.70)
        else:  # review_needed: completed but low/missing extraction confidence
            filters.append(UploadRow.status == DbUploadStatus.COMPLETED)
            filters.append(artifact_conf < 0.70)

    stmt = (
        select(UploadRow, ExtractionArtifact)
        .outerjoin(ExtractionArtifact, ExtractionArtifact.upload_id == UploadRow.id)
        .where(*filters)
        .order_by(UploadRow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await session.execute(stmt)).all()
    count_stmt = select(func.count()).select_from(UploadRow).outerjoin(
        ExtractionArtifact, ExtractionArtifact.upload_id == UploadRow.id
    ).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    vendor_ids = {row.vendor_id for row, _ in rows if row.vendor_id}
    names = await _vendor_names(session, vendor_ids)

    return DocumentListResponse(
        documents=[
            _to_document_item(
                row,
                artifact,
                names.get(row.vendor_id) if row.vendor_id else None,
            )
            for row, artifact in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _load_lease(
    document_id: uuid.UUID, session: AsyncSession
) -> UploadRow:
    """Load one upload lease for detail endpoints (tenant-scoped).

    Args:
        document_id: Upload lease id (the explorer identifies documents by
            their lease row — one row per bucket file).
        session: Async DB session.

    Returns:
        The upload lease row.

    Raises:
        HTTPException: 404 when the lease does not exist (tenant-scoped).
    """
    row = await session.get(UploadRow, document_id)
    if row is None or row.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return row


async def _load_document(
    document_id: uuid.UUID, session: AsyncSession
) -> tuple[UploadRow, ExtractionArtifact | None]:
    """Load one lease + optional artifact for detail endpoints.

    Args:
        document_id: Upload lease id (the explorer identifies documents by
            their lease row — one row per bucket file).
        session: Async DB session.

    Returns:
        Tuple of (upload row, artifact row or None).

    Raises:
        HTTPException: 404 when the lease does not exist (tenant-scoped).
    """
    row = await _load_lease(document_id, session)
    artifact = (
        await session.execute(
            select(ExtractionArtifact).where(ExtractionArtifact.upload_id == document_id)
        )
    ).scalar_one_or_none()
    return row, artifact


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: uuid.UUID,
    user: Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    reader=Depends(get_gcs_reader_dep),  # type: ignore[no-untyped-def]
    settings: IngestionAPISettings = Depends(get_app_settings),
) -> DocumentDetailResponse:
    """Fetch one document: properties + provenance + extraction payload.

    The bulky extraction payload (entities/pages/tables, PRD §8 provenance
    chain) is read from GCS ``artifact_gcs_key`` when persisted; legacy
    rows without an artifact return properties only.

    Args:
        document_id: Upload lease id.
        user: Authenticated procurement member (JWT).
        session: Async DB session.
        reader: GCS object reader (fake in tests).
        settings: Service settings (GCS bucket).

    Returns:
        Detail payload with parsed artifact when available.

    Raises:
        HTTPException: 404 unknown document, 503 bucket unconfigured.
    """
    del user
    if not settings.gcs_raw_bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="storage not configured",
        )
    row, artifact = await _load_document(document_id, session)
    names = await _vendor_names(session, {row.vendor_id} if row.vendor_id else set())

    artifact_payload: dict[str, Any] | None = None
    if artifact and artifact.artifact_gcs_key:
        try:
            raw = reader.download_bytes(
                bucket=settings.gcs_raw_bucket,
                key=artifact.artifact_gcs_key,
            )
            if raw:
                artifact_payload = json.loads(raw)
        except Exception as exc:
            # Artifact unreadable → properties still render; UI shows the
            # "extraction pending" state instead of failing the request.
            logger.warning(
                "document_artifact_read_failed",
                upload_id=str(document_id),
                artifact_key=artifact.artifact_gcs_key,
                error_class=type(exc).__name__,
            )

    item = _to_document_item(row, artifact, names.get(row.vendor_id) if row.vendor_id else None)
    return DocumentDetailResponse(
        **item.model_dump(),
        classification=artifact.classification if artifact else None,
        artifact=artifact_payload,
    )


@router.get("/{document_id}/file", response_model=DocumentFileResponse)
async def get_document_file(
    document_id: uuid.UUID,
    user: Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: IngestionAPISettings = Depends(get_app_settings),
    signer=Depends(get_gcs_signer_dep),  # type: ignore[no-untyped-def]
) -> DocumentFileResponse:
    """Mint a short-lived signed GET URL for inline preview / download.

    Args:
        document_id: Upload lease id.
        user: Authenticated procurement member (JWT).
        session: Async DB session.
        settings: Service settings (GCS bucket + URL expiry).
        signer: GCS V4 signer (fake in tests).

    Returns:
        Signed URL + expiry for the stored bytes (source file, not artifact).

    Raises:
        HTTPException: 404 unknown document, 503 storage unconfigured.
    """
    del user
    if not settings.gcs_raw_bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="storage not configured",
        )
    row = await _load_lease(document_id, session)
    signed_url, expires_at = signer.generate_download_url(
        bucket=settings.gcs_raw_bucket,
        key=row.gcs_key,
        expires_secs=settings.gcs_signed_url_expiry_secs,
    )
    logger.info(
        "document_file_url_issued",
        tenant_id=row.tenant_id,
        upload_id=str(row.id),
        gcs_key=row.gcs_key,
        expires_secs=settings.gcs_signed_url_expiry_secs,
    )
    return DocumentFileResponse(document_id=row.id, url=signed_url, expires_at=expires_at)
