"""Contract version history and vendor contract-line endpoints."""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_current_user, get_db_session
from zellovest_procurement.schemas.contracts import (
    ContractHistoryResponse,
    ContractTermResponse,
    ContractVersionResponse,
    VendorContractLineResponse,
)
from zellovest_shared.db.models import (
    Contract as ContractRow,
    ContractTermsVersion as ContractTermsVersionRow,
    ContractVersion as ContractVersionRow,
    Document as DocumentRow,
    Vendor,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/contracts", tags=["contracts"])
vendor_router = APIRouter(prefix="/vendors", tags=["contracts"])


def _term_response(term: ContractTermsVersionRow) -> ContractTermResponse:
    """Convert a persisted term row to its stable wire representation."""
    return ContractTermResponse(
        id=term.id,
        contract_line_id=term.contract_line_id,
        line_no=term.line_no,
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
        effective_from=term.effective_from,
        effective_to=term.effective_to,
    )


@router.get("/{contract_id}/history", response_model=ContractHistoryResponse)
async def get_contract_history(
    contract_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ContractHistoryResponse:
    """Return contract versions, source documents, and terms for one tenant."""
    contract = await session.scalar(
        select(ContractRow).where(
            ContractRow.id == contract_id,
            ContractRow.tenant_id == user.tenant_id,
        )
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")
    vendor = await session.scalar(
        select(Vendor).where(
            Vendor.id == contract.vendor_id,
            Vendor.tenant_id == user.tenant_id,
        )
    )
    versions = (
        await session.scalars(
            select(ContractVersionRow)
            .where(
                ContractVersionRow.contract_id == contract.id,
                ContractVersionRow.tenant_id == user.tenant_id,
            )
            .order_by(ContractVersionRow.version_no)
        )
    ).all()
    version_numbers = {version.id: version.version_no for version in versions}
    response_versions: list[ContractVersionResponse] = []
    for version in versions:
        terms = (
            await session.scalars(
                select(ContractTermsVersionRow)
                .where(
                    ContractTermsVersionRow.contract_version_id == version.id,
                    ContractTermsVersionRow.tenant_id == user.tenant_id,
                )
                .order_by(ContractTermsVersionRow.line_no, ContractTermsVersionRow.effective_from)
            )
        ).all()
        source = (
            await session.get(DocumentRow, version.source_document_id)
            if version.source_document_id
            else None
        )
        response_versions.append(
            ContractVersionResponse(
                id=version.id,
                version_no=version.version_no,
                change_type=version.change_type.value,
                source_document_id=version.source_document_id,
                source_filename=source.filename if source else None,
                source_upload_id=source.upload_id if source else None,
                parent_version_id=version.parent_version_id,
                parent_version_no=version_numbers.get(version.parent_version_id),
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                title=version.title,
                contract_start_date=version.contract_start_date,
                contract_end_date=version.contract_end_date,
                renewal_date=version.renewal_date,
                notice_period_days=version.notice_period_days,
                auto_renew=version.auto_renew,
                termination_clause=version.termination_clause,
                terms=[_term_response(term) for term in terms],
            )
        )
    logger.info(
        "contract_history_read",
        tenant_id=user.tenant_id,
        contract_id=str(contract.id),
        version_count=len(response_versions),
    )
    return ContractHistoryResponse(
        contract_id=contract.id,
        vendor_id=contract.vendor_id,
        vendor_name=vendor.name if vendor else "Unknown vendor",
        contract_number=contract.contract_number,
        title=(response_versions[-1].title if response_versions else contract.title),
        versions=response_versions,
    )


@vendor_router.get("/{vendor_id}/contracts", response_model=list[VendorContractLineResponse])
async def list_vendor_contract_lines(
    vendor_id: UUID,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[VendorContractLineResponse]:
    """List the latest version's terms for each contract owned by a vendor."""
    contracts = (
        await session.scalars(
            select(ContractRow)
            .where(
                ContractRow.vendor_id == vendor_id,
                ContractRow.tenant_id == user.tenant_id,
            )
            .order_by(ContractRow.contract_number)
        )
    ).all()
    response: list[VendorContractLineResponse] = []
    today = date.today()
    for contract in contracts:
        version = await session.scalar(
            select(ContractVersionRow)
            .where(
                ContractVersionRow.contract_id == contract.id,
                ContractVersionRow.tenant_id == user.tenant_id,
            )
            .order_by(ContractVersionRow.version_no.desc())
            .limit(1)
        )
        if version is None:
            continue
        terms = (
            await session.scalars(
                select(ContractTermsVersionRow)
                .where(
                    ContractTermsVersionRow.contract_version_id == version.id,
                    ContractTermsVersionRow.tenant_id == user.tenant_id,
                )
                .order_by(ContractTermsVersionRow.line_no)
            )
        ).all()
        for term in terms:
            active = term.effective_from <= today and (
                term.effective_to is None or term.effective_to >= today
            )
            source = (
                await session.get(DocumentRow, version.source_document_id)
                if version.source_document_id
                else None
            )
            response.append(
                VendorContractLineResponse(
                    id=term.id,
                    contract_id=contract.id,
                    vendor_id=contract.vendor_id,
                    contract_number=contract.contract_number,
                    title=version.title or contract.title,
                    product=term.description or term.product_code or "Contract term",
                    unit_price=term.unit_price,
                    currency=term.currency,
                    uom=term.uom,
                    qty_min=term.qty_min,
                    qty_max=term.qty_max,
                    quantity=term.qty_max or term.qty_min,
                    effective_from=term.effective_from,
                    effective_to=term.effective_to,
                    version=version.version_no,
                    amendment_of_id=version.parent_version_id,
                    status="active" if active and contract.status.value == "active" else "expired",
                    payment_terms=term.payment_terms,
                    price_escalation=term.escalation_pct,
                    renewal_date=version.renewal_date or contract.renewal_date,
                    auto_renewal=version.auto_renew,
                    notice_period_days=version.notice_period_days,
                    source_document_id=version.source_document_id,
                    source_upload_id=source.upload_id if source else None,
                    created_at=term.created_at,
                    updated_at=term.created_at,
                )
            )
    return response
