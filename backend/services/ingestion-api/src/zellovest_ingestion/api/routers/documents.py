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
from datetime import UTC, date, datetime, time, timedelta
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
    ContractCandidate,
    ContractCandidateTerm,
    ContractCandidatesResponse,
    DocumentDetailResponse,
    DocumentFileResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentStatus,
    ContractReviewCommitRequest,
    ContractReviewCommitResponse,
    EXTRACTED_CONFIDENCE_THRESHOLD,
    InvoiceReviewCommitRequest,
    InvoiceReviewCommitResponse,
    derived_status,
    normalized_doc_types,
)
from zellovest_ingestion.schemas.uploads import DEFAULT_TENANT_ID
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.models import (
    Contract as ContractRow,
    ContractChangeType,
    ContractLine as ContractLineRow,
    ContractTermsVersion as ContractTermsVersionRow,
    ContractVersion as ContractVersionRow,
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
from zellovest_shared.contract_versioning import (
    AmbiguousContractLineError,
    match_contract_line,
    normalize_contract_number,
)
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


def _review_is_open(artifact: ExtractionArtifact | None) -> bool:
    """Whether a human may still verify and commit this extraction.

    A committed review is immutable. A pending review is always open. A
    missing review state is open only when the extraction itself is low
    confidence (or has no confidence at all), which covers documents that
    entered the explorer before the review workflow existed.

    Args:
        artifact: Matching extraction artifact row, if any.

    Returns:
        ``True`` when a reviewer can commit corrected values.
    """
    if artifact is None or artifact.review_status == "committed":
        return False
    if artifact.review_status == "pending":
        return True
    confidence = artifact.extraction_confidence
    if confidence is None:
        return True
    try:
        return float(confidence) < EXTRACTED_CONFIDENCE_THRESHOLD
    except (TypeError, ValueError):
        return False


def _reviewer_identity(user: Any) -> tuple[str, str]:
    """Extract the reviewer id and email from a dict or ORM user."""
    if isinstance(user, dict):
        return str(user.get("id") or user.get("sub", "")), str(user.get("email", ""))
    return str(getattr(user, "id", "")), str(getattr(user, "email", ""))


def _as_utc_datetime(value: date | None) -> datetime | None:
    """Convert a wire ``date`` into a timezone-aware midnight datetime."""
    return datetime.combine(value, time.min, tzinfo=UTC) if value is not None else None


def _term_values(term: Any) -> dict[str, Any]:
    """Copy the commercial values needed to create a snapshot term row."""
    return {
        "product_code": term.product_code,
        "description": term.description,
        "unit_price": term.unit_price,
        "currency": term.currency,
        "uom": term.uom,
        "qty_min": term.qty_min,
        "qty_max": term.qty_max,
        "discount_pct": term.discount_pct,
        "tax_rule": term.tax_rule,
        "payment_terms": term.payment_terms,
        "freight_terms": term.freight_terms,
        "escalation_pct": term.escalation_pct,
    }


async def _append_contract_version(
    session: AsyncSession,
    *,
    tenant_id: str,
    contract: ContractRow,
    document: DocumentRow,
    document_type: str,
    change_type: str,
    title: str | None,
    start_date: date,
    end_date: date | None,
    renewal_date: date | None,
    notice_period_days: int | None,
    auto_renew: bool,
    termination_clause: str | None,
    terms: list[Any],
    removed_line_ids: list[uuid.UUID],
) -> tuple[ContractVersionRow, list[uuid.UUID]]:
    """Append a full effective snapshot while retaining prior term values."""
    latest = await session.scalar(
        select(ContractVersionRow)
        .where(
            ContractVersionRow.tenant_id == tenant_id,
            ContractVersionRow.contract_id == contract.id,
        )
        .order_by(ContractVersionRow.version_no.desc())
        .limit(1)
        .with_for_update()
    )
    version_start = min(term.effective_from for term in terms)
    if latest is not None and version_start <= latest.effective_from:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A new contract version must take effect after the latest version; review or rebase this backdated change.",
        )

    version_no = (latest.version_no if latest else 0) + 1
    version = ContractVersionRow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        contract_id=contract.id,
        version_no=version_no,
        source_document_id=document.id,
        parent_version_id=latest.id if latest else None,
        change_type=ContractChangeType(change_type),
        effective_from=version_start,
        title=title,
        contract_start_date=start_date,
        contract_end_date=end_date,
        renewal_date=renewal_date,
        notice_period_days=notice_period_days,
        auto_renew=auto_renew,
        termination_clause=termination_clause,
    )
    session.add(version)
    await session.flush()

    parent_terms: list[ContractTermsVersionRow] = []
    if latest is not None:
        if latest.effective_from < version_start:
            latest.effective_to = version_start - timedelta(days=1)
        parent_terms = list(
            (
                await session.scalars(
                    select(ContractTermsVersionRow)
                    .where(
                        ContractTermsVersionRow.tenant_id == tenant_id,
                        ContractTermsVersionRow.contract_version_id == latest.id,
                    )
                    .order_by(ContractTermsVersionRow.line_no)
                    .with_for_update()
                )
            ).all()
        )

    by_line_id = {str(term.contract_line_id): term for term in parent_terms}
    removed = {str(line_id) for line_id in removed_line_ids}
    if not removed.issubset(by_line_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A removed product line does not belong to the selected parent version.",
        )

    matched: dict[str, Any] = {}
    assignments: list[tuple[Any, ContractTermsVersionRow | None, uuid.UUID]] = []
    for term in terms:
        try:
            match = match_contract_line(term.model_dump(), parent_terms)
        except AmbiguousContractLineError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        if match is not None:
            line_id = match.contract_line_id
            if str(line_id) in removed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="A product line cannot be both changed and removed.",
                )
            if str(line_id) in matched:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Two extracted terms map to the same contract product line.",
                )
            matched[str(line_id)] = term
        else:
            line = ContractLineRow(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                contract_id=contract.id,
                legacy_line_no=None,
                initial_document_id=document.id,
            )
            session.add(line)
            await session.flush()
            line_id = line.id
        assignments.append((term, match, line_id))

    next_line_no = max((old.line_no for old in parent_terms), default=0) + 1
    for old in parent_terms:
        old_line_id = str(old.contract_line_id)
        if old.effective_to is not None and old.effective_to < version_start:
            continue
        if old.effective_from > version_start:
            future_change = matched.get(old_line_id)
            if future_change is not None:
                changed_from = future_change.effective_from
                if changed_from < old.effective_from:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="A changed product line cannot take effect before its scheduled start.",
                    )
                close_date = changed_from - timedelta(days=1)
                old.effective_to = min(old.effective_to or close_date, close_date)
            # A separately scheduled future line remains valid as authored.
            continue
        old_effective_to = old.effective_to
        if old_line_id in removed:
            close_date = version_start - timedelta(days=1)
            old.effective_to = min(old.effective_to or close_date, close_date)
            continue

        changed_term = matched.get(old_line_id)
        if changed_term is None:
            close_date = version_start - timedelta(days=1)
            old.effective_to = min(old.effective_to or close_date, close_date)
            session.add(
                ContractTermsVersionRow(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    contract_id=contract.id,
                    contract_version_id=version.id,
                    contract_line_id=old.contract_line_id,
                    version_no=version_no,
                    line_no=old.line_no,
                    **_term_values(old),
                    effective_from=version_start,
                    effective_to=old_effective_to,
                    amendment_document_id=document.id,
                )
            )
            continue

        line_effective_from = changed_term.effective_from
        if line_effective_from <= old.effective_from:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A changed product line cannot take effect before its existing line; review or rebase this amendment.",
            )
        close_date = line_effective_from - timedelta(days=1)
        old.effective_to = min(old.effective_to or close_date, close_date)
        if line_effective_from > version_start:
            carry_to = line_effective_from - timedelta(days=1)
            carry_end = min(old_effective_to or carry_to, carry_to)
            if old.effective_from <= carry_end:
                session.add(
                    ContractTermsVersionRow(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        contract_id=contract.id,
                        contract_version_id=version.id,
                        contract_line_id=old.contract_line_id,
                        version_no=version_no,
                        line_no=next_line_no,
                        **_term_values(old),
                        effective_from=version_start,
                        effective_to=carry_end,
                        amendment_document_id=document.id,
                    )
                )
                next_line_no += 1

    new_term_ids: list[uuid.UUID] = []
    for term, old, line_id in assignments:
        term_id = uuid.uuid4()
        new_term_ids.append(term_id)
        if old is not None:
            line_no = old.line_no
        else:
            line_no = next_line_no
            next_line_no += 1
        session.add(
            ContractTermsVersionRow(
                id=term_id,
                tenant_id=tenant_id,
                contract_id=contract.id,
                contract_version_id=version.id,
                contract_line_id=line_id,
                version_no=version_no,
                line_no=line_no,
                product_code=term.product_code,
                description=term.description,
                unit_price=term.unit_price,
                currency=term.currency,
                uom=term.uom,
                qty_min=term.qty_min,
                qty_max=term.qty_max,
                discount_pct=term.discount_pct,
                tax_rule=term.tax_rule,
                payment_terms=term.payment_terms,
                freight_terms=term.freight_terms,
                escalation_pct=term.escalation_pct,
                effective_from=term.effective_from,
                effective_to=term.effective_to,
                amendment_document_id=document.id,
            )
        )
    return version, new_term_ids


async def _resolve_or_create_vendor(
    session: AsyncSession, *, tenant_id: str, vendor_name: str
) -> tuple[Vendor, str]:
    """Resolve a vendor by case-insensitive name or insert a new one.

    Args:
        session: Active async database session.
        tenant_id: Owning tenant.
        vendor_name: Reviewer-corrected vendor name.

    Returns:
        The existing or newly created vendor and its normalized name.
    """
    normalized_name = vendor_name.strip()
    vendor = (
        await session.execute(
            select(Vendor)
            .where(
                Vendor.tenant_id == tenant_id,
                func.lower(Vendor.name) == normalized_name.lower(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if vendor is None:
        vendor = Vendor(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=normalized_name,
            status="active",
            is_active=True,
        )
        session.add(vendor)
        await session.flush()
    return vendor, normalized_name


async def _is_reupload_of_invoice(
    session: AsyncSession,
    *,
    upload: UploadRow,
    conflicting_invoice: InvoiceRow,
) -> bool:
    """Whether an invoice-number conflict comes from re-uploading this file.

    Reviewers often upload the same PDF twice before the first one has been
    verified. The second lease has no invoice row of its own, so committing its
    review would hit the tenant-wide invoice-number uniqueness constraint.
    When the conflict's source upload has the same file name and byte size as
    the lease under review, the two documents are treated as the same invoice:
    the reviewer updates the existing ledger record instead of creating a
    duplicate.

    Args:
        session: Active async database session.
        upload: Upload lease currently under review.
        conflicting_invoice: Ledger invoice already using the reviewed number.

    Returns:
        ``True`` when the conflict's source document is a re-upload of the
        same file, ``False`` otherwise.
    """
    if conflicting_invoice.document_id is None:
        return False
    duplicate_source = (
        await session.execute(
            select(UploadRow.id)
            .join(DocumentRow, DocumentRow.upload_id == UploadRow.id)
            .where(
                DocumentRow.id == conflicting_invoice.document_id,
                UploadRow.tenant_id == upload.tenant_id,
                func.lower(UploadRow.filename) == upload.filename.strip().lower(),
                UploadRow.size_expected == upload.size_expected,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return duplicate_source is not None


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


@router.get(
    "/{document_id}/contract-candidates",
    response_model=ContractCandidatesResponse,
)
async def get_contract_candidates(
    document_id: uuid.UUID,
    query: str | None = Query(default=None, max_length=256),
    user: Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ContractCandidatesResponse:
    """List tenant-scoped contracts a reviewer can select as an amendment parent."""
    del user
    upload = await _load_lease(document_id, session)
    document = (
        await session.execute(
            select(DocumentRow).where(
                DocumentRow.upload_id == upload.id,
                DocumentRow.tenant_id == upload.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if document is None or document.document_type.value not in {"contract", "amendment"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Parent-contract selection is available for contract documents.",
        )

    contracts = (
        await session.scalars(
            select(ContractRow)
            .where(ContractRow.tenant_id == upload.tenant_id)
            .order_by(ContractRow.contract_number)
            .limit(100)
        )
    ).all()
    document_vendor = (
        await session.get(Vendor, document.vendor_id) if document.vendor_id else None
    )
    normalized_query = normalize_contract_number(query) if query else ""
    candidates: list[ContractCandidate] = []
    for contract in contracts:
        vendor = await session.get(Vendor, contract.vendor_id)
        vendor_name = vendor.name if vendor else "Unknown vendor"
        searchable = " ".join(
            (contract.contract_number, contract.title or "", vendor_name)
        ).casefold()
        if normalized_query and normalized_query not in normalize_contract_number(searchable):
            continue
        version = await session.scalar(
            select(ContractVersionRow)
            .where(
                ContractVersionRow.tenant_id == upload.tenant_id,
                ContractVersionRow.contract_id == contract.id,
            )
            .order_by(ContractVersionRow.version_no.desc())
            .limit(1)
        )
        terms = []
        if version is not None:
            terms = (
                await session.scalars(
                    select(ContractTermsVersionRow)
                    .where(
                        ContractTermsVersionRow.tenant_id == upload.tenant_id,
                        ContractTermsVersionRow.contract_version_id == version.id,
                        or_(
                            ContractTermsVersionRow.effective_to.is_(None),
                            ContractTermsVersionRow.effective_to >= date.today(),
                        ),
                    )
                    .order_by(ContractTermsVersionRow.line_no)
                )
            ).all()
        candidates.append(
            ContractCandidate(
                contract_id=contract.id,
                contract_number=contract.contract_number,
                title=version.title if version and version.title else contract.title,
                vendor_name=vendor_name,
                latest_version_no=version.version_no if version else None,
                terms=[
                    ContractCandidateTerm(
                        contract_line_id=term.contract_line_id,
                        product_code=term.product_code,
                        description=term.description,
                        unit_price=term.unit_price,
                        currency=term.currency,
                        uom=term.uom,
                        qty_min=term.qty_min,
                        qty_max=term.qty_max,
                        effective_from=term.effective_from,
                        effective_to=term.effective_to,
                    )
                    for term in terms
                ],
            )
        )
    candidates.sort(
        key=lambda candidate: (
            candidate.vendor_name.casefold()
            != (document_vendor.name.casefold() if document_vendor else ""),
            normalize_contract_number(candidate.contract_number)
            != normalize_contract_number(query),
            candidate.contract_number.casefold(),
        )
    )
    return ContractCandidatesResponse(document_id=document.id, candidates=candidates)


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
    if artifact is None or not _review_is_open(artifact):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document has no open human review.",
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
    vendor, normalized_vendor_name = await _resolve_or_create_vendor(
        session,
        tenant_id=upload.tenant_id,
        vendor_name=normalized_vendor_name,
    )
    document.vendor_id = vendor.id
    upload.vendor_id = str(vendor.id)

    tenant_contracts = (
        await session.scalars(
            select(ContractRow)
            .where(
                ContractRow.tenant_id == upload.tenant_id,
                ContractRow.vendor_id == vendor.id,
            )
            .with_for_update()
        )
    ).all()
    normalized_contract_number = normalize_contract_number(body.contract_number)
    exact_matches = [
        candidate
        for candidate in tenant_contracts
        if normalize_contract_number(candidate.contract_number) == normalized_contract_number
    ]
    change_type = body.change_type or (
        "amendment" if document_type == "amendment" else "original"
    )
    if document_type == "amendment" and change_type == "original":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An amendment must be recorded as an amendment, renewal, or price revision.",
        )
    if body.parent_contract_id is not None and change_type == "original":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A selected parent contract requires amendment, renewal, or price revision as the change type.",
        )

    contract: ContractRow | None = None
    if body.parent_contract_id is not None:
        contract = next(
            (candidate for candidate in tenant_contracts if candidate.id == body.parent_contract_id),
            None,
        )
        if contract is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The selected parent contract is not available in this tenant for this vendor.",
            )
        if normalize_contract_number(contract.contract_number) != normalized_contract_number:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The selected parent contract number does not match the reviewed document.",
            )
    elif change_type != "original":
        if len(exact_matches) != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Select the parent contract before committing this amendment.",
            )
        contract = exact_matches[0]
    elif exact_matches:
        same_document = next(
            (candidate for candidate in exact_matches if candidate.document_id == document.id),
            None,
        )
        if same_document is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A contract with this vendor and number is already in the ledger.",
            )
        contract = same_document

    if contract is None:
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

    try:
        version, term_ids = await _append_contract_version(
            session,
            tenant_id=upload.tenant_id,
            contract=contract,
            document=document,
            document_type=document_type,
            change_type=change_type,
            title=body.title,
            start_date=body.start_date,
            end_date=body.end_date,
            renewal_date=body.renewal_date,
            notice_period_days=body.notice_period_days,
            auto_renew=body.auto_renew,
            termination_clause=body.termination_clause,
            terms=body.terms,
            removed_line_ids=body.removed_contract_line_ids,
        )
    except HTTPException:
        await session.rollback()
        raise
    version_no = version.version_no

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
    reviewer_id, reviewer_email = _reviewer_identity(user)
    review_receipt = dict(artifact.review_data or {})
    review_receipt.update(
        {
            "status": "committed",
            "reviewed_at": reviewed_at.isoformat(),
            "reviewer_id": reviewer_id,
            "reviewer_email": reviewer_email,
            "reviewer_notes": body.reviewer_notes or "",
            "contract_id": str(contract.id),
            "contract_version_id": str(version.id),
            "version_no": version_no,
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
        reviewer_id=reviewer_id,
        term_count=len(term_ids),
    )
    return ContractReviewCommitResponse(
        document_id=document_id,
        contract_id=contract.id,
        contract_version_id=version.id,
        version_no=version_no,
        term_version_ids=term_ids,
        review_status="committed",
        reviewed_at=reviewed_at,
    )


@router.post(
    "/{document_id}/review/commit-invoice",
    response_model=InvoiceReviewCommitResponse,
)
async def commit_invoice_review(
    document_id: uuid.UUID,
    body: InvoiceReviewCommitRequest,
    user: Any = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceReviewCommitResponse:
    """Commit human-verified invoice fields into the operational ledger.

    Low-confidence invoice extractions can be opened in the exception drawer
    even when the pipeline already wrote a provisional invoice. This endpoint
    updates or creates the invoice header and line items, records
    ``human_verified`` provenance for every corrected field, and writes a
    review receipt in one transaction.

    Args:
        document_id: Upload lease id shown by the Document Explorer.
        body: Reviewer-corrected invoice header and line items.
        user: Authenticated reviewer whose identity is written to the receipt.
        session: Async database session.

    Returns:
        The committed invoice id and review timestamp.

    Raises:
        HTTPException: When the document is not an invoice, the review is
            already committed, or the invoice number conflicts with another
            document.
    """
    upload = await _load_lease(document_id, session)
    artifact = (
        await session.execute(
            select(ExtractionArtifact)
            .where(ExtractionArtifact.upload_id == document_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if artifact is None or not _review_is_open(artifact):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document has no open human review.",
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
    if document.document_type.value != "invoice":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Human invoice review is available for invoices only.",
        )

    vendor, normalized_vendor_name = await _resolve_or_create_vendor(
        session,
        tenant_id=upload.tenant_id,
        vendor_name=body.vendor_name,
    )
    document.vendor_id = vendor.id
    upload.vendor_id = str(vendor.id)

    invoice_number = body.invoice_number.strip()
    invoice = (
        await session.execute(
            select(InvoiceRow)
            .where(
                InvoiceRow.document_id == document.id,
                InvoiceRow.tenant_id == upload.tenant_id,
            )
            .order_by(InvoiceRow.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    conflicting_invoice = (
        await session.execute(
            select(InvoiceRow)
            .where(
                InvoiceRow.tenant_id == upload.tenant_id,
                InvoiceRow.invoice_number == invoice_number,
                InvoiceRow.document_id != document.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if conflicting_invoice is not None:
        # A re-uploaded copy of the same PDF has no invoice row of its own.
        # Adopt the existing ledger record so the reviewer clears the duplicate
        # instead of being blocked by the invoice-number constraint.
        if invoice is not None or not await _is_reupload_of_invoice(
            session,
            upload=upload,
            conflicting_invoice=conflicting_invoice,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An invoice with this number is already in the ledger.",
            )
        invoice = conflicting_invoice

    invoice_date = _as_utc_datetime(body.invoice_date)
    if invoice_date is None:  # pragma: no cover - required wire field
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invoice_date is required",
        )
    due_date = _as_utc_datetime(body.due_date)
    invoice_values = {
        "vendor_id": vendor.id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "currency": body.currency,
        "subtotal": float(body.subtotal),
        "tax_amount": float(body.tax_amount),
        "total_amount": float(body.total_amount),
    }
    if invoice is None:
        invoice = InvoiceRow(
            id=uuid.uuid4(),
            tenant_id=upload.tenant_id,
            document_id=document.id,
            status="pending",
            **invoice_values,
        )
        session.add(invoice)
        await session.flush()
    else:
        for field_name, field_value in invoice_values.items():
            setattr(invoice, field_name, field_value)
    invoice_metadata = dict(invoice.extra or {})
    invoice_metadata.pop("commercial_reconciled_at", None)
    invoice_metadata.pop("commercial_review_reason", None)
    invoice_metadata.pop("commercial_exception_count", None)
    invoice.extra = invoice_metadata

    existing_lines = (
        (
            await session.execute(
                select(InvoiceLineItemRow)
                .where(
                    InvoiceLineItemRow.invoice_id == invoice.id,
                    InvoiceLineItemRow.tenant_id == upload.tenant_id,
                )
                .order_by(InvoiceLineItemRow.line_no)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    lines_by_number = {line.line_no: line for line in existing_lines}
    line_rows: list[tuple[int, uuid.UUID]] = []
    for line_no, line in enumerate(body.line_items, start=1):
        existing_line = lines_by_number.get(line_no)
        line_total = (
            line.total
            if line.total is not None
            else (line.quantity * line.unit_price)
        )
        if existing_line is None:
            existing_line = InvoiceLineItemRow(
                id=uuid.uuid4(),
                tenant_id=upload.tenant_id,
                invoice_id=invoice.id,
                line_no=line_no,
                description=line.description or "",
                product_code=line.product_code,
                quantity=float(line.quantity),
                unit_price=float(line.unit_price),
                total=float(line_total),
            )
            session.add(existing_line)
        else:
            existing_line.description = line.description or ""
            existing_line.product_code = line.product_code
            existing_line.quantity = float(line.quantity)
            existing_line.unit_price = float(line.unit_price)
            existing_line.total = float(line_total)
        line_rows.append((line_no, existing_line.id))
    for line_no, line in lines_by_number.items():
        if line_no > len(body.line_items):
            await session.delete(line)

    header_values = {
        "invoice_number": invoice_number,
        "vendor_name": normalized_vendor_name,
        "invoice_date": invoice_date.isoformat(),
        "due_date": due_date.isoformat() if due_date else "",
        "currency": body.currency,
        "subtotal": str(body.subtotal),
        "tax_amount": str(body.tax_amount),
        "total_amount": str(body.total_amount),
    }
    for field_name, field_value in header_values.items():
        session.add(
            ExtractionProvenance(
                id=uuid.uuid4(),
                tenant_id=upload.tenant_id,
                document_id=document.id,
                entity_type="invoice",
                entity_id=invoice.id,
                field_name=field_name,
                field_value_text=field_value,
                confidence=1.0,
                extraction_method="human_verified",
            )
        )
    for line_no, line in enumerate(body.line_items, start=1):
        line_total = (
            line.total
            if line.total is not None
            else (line.quantity * line.unit_price)
        )
        term_values = {
            "description": line.description or "",
            "product_code": line.product_code or "",
            "quantity": str(line.quantity),
            "unit_price": str(line.unit_price),
            "total": str(line_total),
        }
        entity_id = line_rows[line_no - 1][1]
        for field_name, field_value in term_values.items():
            session.add(
                ExtractionProvenance(
                    id=uuid.uuid4(),
                    tenant_id=upload.tenant_id,
                    document_id=document.id,
                    entity_type="invoice_line_item",
                    entity_id=entity_id,
                    field_name=f"line_{line_no}_{field_name}",
                    field_value_text=field_value,
                    confidence=1.0,
                    extraction_method="human_verified",
                )
            )

    reviewed_at = datetime.now(UTC)
    reviewer_id, reviewer_email = _reviewer_identity(user)
    review_receipt = dict(artifact.review_data or {})
    review_receipt.update(
        {
            "status": "committed",
            "document_type": "invoice",
            "reviewed_at": reviewed_at.isoformat(),
            "reviewer_id": reviewer_id,
            "reviewer_email": reviewer_email,
            "reviewer_notes": body.reviewer_notes or "",
            "invoice_id": str(invoice.id),
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
            "invoice_review_commit_conflict",
            tenant_id=upload.tenant_id,
            document_id=str(document.id),
            invoice_number=invoice_number,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invoice number or line numbering conflicts with the ledger.",
        ) from exc

    logger.info(
        "invoice_review_committed",
        tenant_id=upload.tenant_id,
        document_id=str(document.id),
        invoice_id=str(invoice.id),
        reviewer_id=reviewer_id,
        line_count=len(body.line_items),
    )
    try:
        from zellovest_workers.tasks.ap_audit import reconcile_invoice

        task_result = reconcile_invoice.delay(
            tenant_id=upload.tenant_id,
            invoice_id=str(invoice.id),
        )
        logger.info(
            "invoice_reconciliation_enqueued",
            tenant_id=upload.tenant_id,
            invoice_id=str(invoice.id),
            task_id=str(task_result.id),
        )
    except Exception as exc:
        logger.warning(
            "invoice_reconciliation_enqueue_failed",
            tenant_id=upload.tenant_id,
            invoice_id=str(invoice.id),
            error_class=type(exc).__name__,
        )
    return InvoiceReviewCommitResponse(
        document_id=document_id,
        invoice_id=invoice.id,
        review_status="committed",
        reviewed_at=reviewed_at,
    )
