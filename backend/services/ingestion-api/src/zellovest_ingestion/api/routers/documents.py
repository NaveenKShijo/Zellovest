"""Document Explorer read endpoints over uploads + extraction artifacts.

Surface for the front-end Document Explorer:
- ``GET  /documents`` — paginated inventory with type/status/vendor/search filters.
- ``GET  /documents/{id}`` — detail (properties + parsed extraction artifact).
- ``GET  /documents/{id}/file`` — short-lived V4 GET signed URL for inline preview.
- ``POST /documents/{id}/review/commit`` — verify and commit contract terms.

Data sources: the ``uploads`` lease is the inventory of every object in the
tenant's GCS raw bucket (manual + Drive). The ``extraction_artifacts`` row
carries the persisted pipeline output metadata; the bulky payload
(entities/pages/tables/provenance) is read from GCS on detail only. Typed
invoice, purchase-order, and contract values are read from the procurement
ledger and returned with the detail record as structured data.
Mirrors the uploads router: JWT auth, tenant fixed to the deployment
tenant (V1), snake_case wire, fakes for tests.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, select
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
from zellovest_ingestion.schemas.documents import (
    DocumentDetailResponse,
    DocumentFileResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentStatus,
    ContractReviewCommitRequest,
    ContractReviewCommitResponse,
    EXTRACTED_CONFIDENCE_THRESHOLD,
    derived_status,
    normalized_doc_types,
)
from zellovest_ingestion.schemas.uploads import DEFAULT_TENANT_ID
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.models import (
    Contract as ContractRow,
    ContractTermsVersion as ContractTermsVersionRow,
    Document as DocumentRow,
    ExtractionArtifact,
    ExtractionProvenance,
    Invoice as InvoiceRow,
    InvoiceLineItem as InvoiceLineItemRow,
    POLineItem as POLineItemRow,
    PurchaseOrder as PurchaseOrderRow,
)
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
        status=derived_status(
            row.status.value,
            artifact.extraction_confidence if artifact else None,
            artifact.review_status if artifact else None,
        ),
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
    review_pending = ExtractionArtifact.review_status == "pending"
    review_committed = ExtractionArtifact.review_status == "committed"
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
            filters.append(
                or_(
                    review_committed,
                    and_(
                        artifact_conf >= EXTRACTED_CONFIDENCE_THRESHOLD,
                        or_(ExtractionArtifact.review_status.is_(None), ~review_pending),
                    ),
                )
            )
        else:  # review_needed: human review is pending or confidence is low
            filters.append(UploadRow.status == DbUploadStatus.COMPLETED)
            filters.append(
                or_(
                    review_pending,
                    and_(
                        or_(
                            ExtractionArtifact.review_status.is_(None),
                            ~review_committed,
                        ),
                        artifact_conf < EXTRACTED_CONFIDENCE_THRESHOLD,
                    ),
                )
            )

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


async def _load_structured_data(
    *,
    document_id: uuid.UUID | None,
    document_type: str,
    tenant_id: str,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Read typed extraction results already promoted into the procurement ledger.

    Args:
        document_id: Structured ``documents`` row id associated with the upload.
        document_type: Normalized invoice, purchase order, contract, or amendment type.
        tenant_id: Tenant whose structured rows may be returned.
        session: Active async database session.

    Returns:
        Structured header and line data when a typed record exists, else ``None``.
    """
    if document_id is None:
        return None

    if document_type == "invoice":
        invoice = await session.scalar(
            select(InvoiceRow)
            .where(
                InvoiceRow.document_id == document_id,
                InvoiceRow.tenant_id == tenant_id,
            )
            .order_by(InvoiceRow.created_at.desc())
            .limit(1)
        )
        if invoice is None:
            return None
        line_items = (
            await session.scalars(
                select(InvoiceLineItemRow)
                .where(
                    InvoiceLineItemRow.invoice_id == invoice.id,
                    InvoiceLineItemRow.tenant_id == tenant_id,
                )
                .order_by(InvoiceLineItemRow.line_no)
            )
        ).all()
        vendor_name = await session.scalar(
            select(Vendor.name).where(
                Vendor.id == invoice.vendor_id,
                Vendor.tenant_id == tenant_id,
            )
        )
        return {
            "invoice_number": invoice.invoice_number,
            "vendor_name": vendor_name,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "currency": invoice.currency,
            "subtotal": invoice.subtotal,
            "tax_amount": invoice.tax_amount,
            "total_amount": invoice.total_amount,
            "line_items": [
                {
                    "description": item.description,
                    "product_code": item.product_code,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total": item.total,
                }
                for item in line_items
            ],
        }

    if document_type == "purchase_order":
        purchase_order = await session.scalar(
            select(PurchaseOrderRow)
            .where(
                PurchaseOrderRow.source_document_id == document_id,
                PurchaseOrderRow.tenant_id == tenant_id,
            )
            .order_by(PurchaseOrderRow.created_at.desc())
            .limit(1)
        )
        if purchase_order is None:
            return None
        line_items = (
            await session.scalars(
                select(POLineItemRow)
                .where(
                    POLineItemRow.po_id == purchase_order.id,
                    POLineItemRow.tenant_id == tenant_id,
                )
                .order_by(POLineItemRow.line_no)
            )
        ).all()
        vendor_name = await session.scalar(
            select(Vendor.name).where(
                Vendor.id == purchase_order.vendor_id,
                Vendor.tenant_id == tenant_id,
            )
        )
        return {
            "po_number": purchase_order.po_number,
            "vendor_name": vendor_name,
            "order_date": purchase_order.order_date,
            "expected_date": purchase_order.expected_date,
            "currency": purchase_order.currency,
            "subtotal": purchase_order.subtotal,
            "tax_amount": purchase_order.tax_amount,
            "total_amount": purchase_order.total_amount,
            "line_items": [
                {
                    "description": item.description,
                    "product_code": item.product_code,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total": item.total,
                }
                for item in line_items
            ],
        }

    if document_type in {"contract", "amendment"}:
        contract = await session.scalar(
            select(ContractRow)
            .where(
                ContractRow.document_id == document_id,
                ContractRow.tenant_id == tenant_id,
            )
            .order_by(ContractRow.created_at.desc())
            .limit(1)
        )
        if contract is None:
            return None
        terms = (
            await session.scalars(
                select(ContractTermsVersionRow)
                .where(
                    ContractTermsVersionRow.amendment_document_id == document_id,
                    ContractTermsVersionRow.tenant_id == tenant_id,
                )
                .order_by(
                    ContractTermsVersionRow.version_no,
                    ContractTermsVersionRow.line_no,
                )
            )
        ).all()
        vendor_name = await session.scalar(
            select(Vendor.name).where(
                Vendor.id == contract.vendor_id,
                Vendor.tenant_id == tenant_id,
            )
        )
        return {
            "contract_number": contract.contract_number,
            "vendor_name": vendor_name,
            "title": contract.title,
            "start_date": contract.start_date,
            "end_date": contract.end_date,
            "renewal_date": contract.renewal_date,
            "notice_period_days": contract.notice_period_days,
            "auto_renew": contract.auto_renew,
            "termination_clause": contract.termination_clause,
            "terms": [
                {
                    "product_code": term.product_code,
                    "description": term.description,
                    "unit_price": term.unit_price,
                    "currency": term.currency,
                    "uom": term.uom,
                    "qty_min": term.qty_min,
                    "qty_max": term.qty_max,
                    "discount_pct": term.discount_pct,
                    "effective_from": term.effective_from,
                    "effective_to": term.effective_to,
                    "escalation_pct": term.escalation_pct,
                    "payment_terms": term.payment_terms,
                    "freight_terms": term.freight_terms,
                    "tax_rule": term.tax_rule,
                }
                for term in terms
            ],
        }

    return None


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
    structured_document = await session.scalar(
        select(DocumentRow).where(
            DocumentRow.upload_id == row.id,
            DocumentRow.tenant_id == row.tenant_id,
        )
    )
    structured_data = await _load_structured_data(
        document_id=structured_document.id if structured_document else None,
        document_type=(
            structured_document.document_type.value
            if structured_document is not None
            else row.document_type
        ),
        tenant_id=row.tenant_id,
        session=session,
    )
    return DocumentDetailResponse(
        **item.model_dump(),
        classification=artifact.classification if artifact else None,
        artifact=artifact_payload,
        review=artifact.review_data if artifact else None,
        structured_data=structured_data,
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


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: uuid.UUID,
    user: Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: IngestionAPISettings = Depends(get_app_settings),
    reader=Depends(get_gcs_reader_dep),  # type: ignore[no-untyped-def]
) -> Response:
    """Return the authenticated source file for same-origin PDF/image preview.

    The browser preview uses this endpoint instead of fetching a signed GCS
    URL directly, avoiding cross-origin restrictions while retaining the same
    tenant and user authorization as the document detail endpoint.

    Args:
        document_id: Upload lease id.
        user: Authenticated procurement member (JWT).
        session: Async DB session.
        settings: Service settings (GCS bucket).
        reader: GCS object reader.

    Returns:
        File bytes with the stored MIME type and private cache headers.

    Raises:
        HTTPException: 404 when the document or object is missing; 503 when
            storage is not configured.
    """
    del user
    if not settings.gcs_raw_bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="storage not configured",
        )
    row = await _load_lease(document_id, session)
    try:
        content = reader.download_bytes(bucket=settings.gcs_raw_bucket, key=row.gcs_key)
    except Exception as exc:
        logger.error(
            "document_content_read_failed",
            upload_id=str(row.id),
            gcs_key=row.gcs_key,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="document file could not be read from storage",
        ) from exc
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document file not found")

    return Response(
        content=content,
        media_type=row.mime_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{document_id}/review/commit",
    response_model=ContractReviewCommitResponse,
)
async def commit_contract_review(
    document_id: uuid.UUID,
    body: ContractReviewCommitRequest,
    user: Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ContractReviewCommitResponse:
    """Commit human-verified contract terms into the versioned ledger.

    The endpoint only accepts a document with a pending review record. It
    writes a contract header, one version containing the reviewed pricing
    lines, field-level human verification provenance, and a review receipt in
    a single database transaction.

    Args:
        document_id: Upload lease id shown by the Document Explorer.
        body: User-corrected contract header and commercial terms.
        user: Authenticated reviewer whose identity is written to the receipt.
        session: Async database session.

    Returns:
        IDs for the committed contract and pricing-version rows.

    Raises:
        HTTPException: When review is absent, already committed, or conflicts
            with an existing contract number.
    """
    upload = await _load_lease(document_id, session)
    artifact = (
        await session.execute(
            select(ExtractionArtifact)
            .where(ExtractionArtifact.upload_id == document_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if artifact is None or artifact.review_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document has no pending human review.",
        )

    document = (
        await session.execute(
            select(DocumentRow).where(
                DocumentRow.upload_id == upload.id,
                DocumentRow.tenant_id == upload.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The structured document record is not available yet.",
        )
    document_type = document.document_type.value
    if document_type not in {"contract", "amendment"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Human commercial-term review is available for contracts and amendments.",
        )

    normalized_vendor_name = body.vendor_name.strip()
    vendor = (
        await session.execute(
            select(Vendor)
            .where(
                Vendor.tenant_id == upload.tenant_id,
                func.lower(Vendor.name) == normalized_vendor_name.lower(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if vendor is None:
        vendor = Vendor(
            id=uuid.uuid4(),
            tenant_id=upload.tenant_id,
            name=normalized_vendor_name,
            status="active",
            is_active=True,
        )
        session.add(vendor)
        await session.flush()
    document.vendor_id = vendor.id
    upload.vendor_id = str(vendor.id)

    existing_contract = (
        await session.execute(
            select(ContractRow)
            .where(
                ContractRow.tenant_id == upload.tenant_id,
                ContractRow.contract_number == body.contract_number.strip(),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        existing_contract is not None
        and document_type != "amendment"
        and existing_contract.document_id != document.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contract with this number is already in the ledger.",
        )

    if existing_contract is None:
        contract = ContractRow(
            id=uuid.uuid4(),
            tenant_id=upload.tenant_id,
            vendor_id=vendor.id,
            document_id=document.id,
            contract_number=body.contract_number.strip(),
            title=body.title,
            status="active",
            start_date=body.start_date,
            end_date=body.end_date,
            renewal_date=body.renewal_date,
            notice_period_days=body.notice_period_days,
            auto_renew=body.auto_renew,
            termination_clause=body.termination_clause,
        )
        session.add(contract)
        await session.flush()
    else:
        contract = existing_contract
        # An amendment updates the current header snapshot. Its submitted
        # values remain attached to this document's immutable review receipt.
        contract.vendor_id = vendor.id
        contract.start_date = body.start_date
        contract.title = body.title
        contract.end_date = body.end_date
        contract.renewal_date = body.renewal_date
        contract.notice_period_days = body.notice_period_days
        contract.auto_renew = body.auto_renew
        contract.termination_clause = body.termination_clause

    max_version = await session.scalar(
        select(func.max(ContractTermsVersionRow.version_no)).where(
            ContractTermsVersionRow.tenant_id == upload.tenant_id,
            ContractTermsVersionRow.contract_id == contract.id,
        )
    )
    version_no = int(max_version or 0) + 1
    term_ids: list[uuid.UUID] = []
    for line_no, term in enumerate(body.terms, start=1):
        term_id = uuid.uuid4()
        term_ids.append(term_id)
        session.add(
            ContractTermsVersionRow(
                id=term_id,
                tenant_id=upload.tenant_id,
                contract_id=contract.id,
                version_no=version_no,
                line_no=line_no,
                product_code=term.product_code,
                description=term.description,
                unit_price=float(term.unit_price),
                currency=term.currency,
                uom=term.uom,
                qty_min=float(term.qty_min) if term.qty_min is not None else None,
                qty_max=float(term.qty_max) if term.qty_max is not None else None,
                discount_pct=(
                    float(term.discount_pct) if term.discount_pct is not None else None
                ),
                escalation_pct=(
                    float(term.escalation_pct) if term.escalation_pct is not None else None
                ),
                payment_terms=term.payment_terms,
                freight_terms=term.freight_terms,
                tax_rule=term.tax_rule,
                effective_from=term.effective_from,
                effective_to=term.effective_to,
                amendment_document_id=document.id,
            )
        )

    header_values = {
        "contract_number": body.contract_number.strip(),
        "vendor_name": normalized_vendor_name,
        "title": body.title or "",
        "start_date": body.start_date.isoformat(),
        "end_date": body.end_date.isoformat() if body.end_date else "",
        "renewal_date": body.renewal_date.isoformat() if body.renewal_date else "",
        "notice_period_days": (
            str(body.notice_period_days) if body.notice_period_days is not None else ""
        ),
        "auto_renew": str(body.auto_renew).lower(),
        "termination_clause": body.termination_clause or "",
    }
    for field_name, field_value in header_values.items():
        session.add(
            ExtractionProvenance(
                id=uuid.uuid4(),
                tenant_id=upload.tenant_id,
                document_id=document.id,
                entity_type="contract",
                entity_id=contract.id,
                field_name=field_name,
                field_value_text=field_value,
                confidence=1.0,
                extraction_method="human_verified",
            )
        )
    for line_no, term in enumerate(body.terms, start=1):
        term_id = term_ids[line_no - 1]
        term_values = {
            "unit_price": str(term.unit_price),
            "effective_from": term.effective_from.isoformat(),
            "effective_to": term.effective_to.isoformat() if term.effective_to else "",
            "qty_min": str(term.qty_min) if term.qty_min is not None else "",
            "qty_max": str(term.qty_max) if term.qty_max is not None else "",
            "discount_pct": (
                str(term.discount_pct) if term.discount_pct is not None else ""
            ),
            "escalation_pct": (
                str(term.escalation_pct) if term.escalation_pct is not None else ""
            ),
            "payment_terms": term.payment_terms or "",
            "freight_terms": term.freight_terms or "",
            "tax_rule": term.tax_rule or "",
        }
        for field_name, field_value in term_values.items():
            session.add(
                ExtractionProvenance(
                    id=uuid.uuid4(),
                    tenant_id=upload.tenant_id,
                    document_id=document.id,
                    entity_type="contract_term",
                    entity_id=term_id,
                    field_name=f"term_{line_no}_{field_name}",
                    field_value_text=field_value,
                    confidence=1.0,
                    extraction_method="human_verified",
                )
            )

    reviewed_at = datetime.now(UTC)
    review_receipt = dict(artifact.review_data or {})
    review_receipt.update(
        {
            "status": "committed",
            "reviewed_at": reviewed_at.isoformat(),
            "reviewer_id": str(
                (user.get("id") or user.get("sub", ""))
                if isinstance(user, dict)
                else getattr(user, "id", "")
            ),
            "reviewer_email": str(
                user.get("email", "")
                if isinstance(user, dict)
                else getattr(user, "email", "")
            ),
            "contract_id": str(contract.id),
            "term_version_ids": [str(term_id) for term_id in term_ids],
            "verified_data": body.model_dump(mode="json"),
        }
    )
    artifact.review_status = "committed"
    artifact.review_data = review_receipt
    document.status = "extracted"

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.warning(
            "contract_review_commit_conflict",
            tenant_id=upload.tenant_id,
            document_id=str(document.id),
            contract_number=body.contract_number,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="These terms overlap an existing ledger version or conflict with an existing contract.",
        ) from exc

    logger.info(
        "contract_review_committed",
        tenant_id=upload.tenant_id,
        document_id=str(document.id),
        contract_id=str(contract.id),
        reviewer_id=str(
            (user.get("id") or user.get("sub", ""))
            if isinstance(user, dict)
            else getattr(user, "id", "")
        ),
        term_count=len(term_ids),
    )
    return ContractReviewCommitResponse(
        document_id=document_id,
        contract_id=contract.id,
        term_version_ids=term_ids,
        review_status="committed",
        reviewed_at=reviewed_at,
    )
