"""Vendor management router for Procurement Core Service."""

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_procurement.api.deps import get_db_session
from zellovest_procurement.schemas.vendors import (
    PrimaryContact,
    VendorCreate,
    VendorListResponse,
    VendorResponse,
    VendorUpdate,
)
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/vendors", tags=["vendors"])


def _map_vendor_row(row: dict[str, Any]) -> VendorResponse:
    """Map database row with metrics to VendorResponse."""
    raw_status = (row.get("status") or "active").lower()
    if raw_status == "active":
        mapped_status = "compliant"
    elif raw_status in {"compliant", "variance_flagged", "up_for_renewal", "maverick_detected", "inactive"}:
        mapped_status = raw_status
    else:
        mapped_status = "compliant"

    db_category = row.get("category")
    meta = row.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    categories: list[str] = []
    if meta.get("categories") and isinstance(meta["categories"], list):
        categories = [str(c) for c in meta["categories"] if c]
    elif db_category:
        categories = [db_category]
    else:
        categories = ["Other"]

    contact_data = meta.get("primaryContact") or meta.get("primary_contact")
    primary_contact: PrimaryContact | None = None
    if isinstance(contact_data, dict):
        primary_contact = PrimaryContact(
            name=contact_data.get("name"),
            email=contact_data.get("email"),
            phone=contact_data.get("phone"),
        )

    db_terms = row.get("payment_terms") or "net_30"
    std_terms = {"net_30", "net_45", "net_60", "custom"}
    payment_terms = db_terms if db_terms in std_terms else "custom"
    custom_payment_terms = db_terms if payment_terms == "custom" else None

    created_dt = row.get("created_at")
    updated_dt = row.get("updated_at")
    created_str = created_dt.isoformat() if hasattr(created_dt, "isoformat") else str(created_dt or "")
    updated_str = updated_dt.isoformat() if hasattr(updated_dt, "isoformat") else str(updated_dt or "")

    vendor_name = row.get("name") or "Unnamed Vendor"

    return VendorResponse(
        id=str(row["id"]),
        tenant_id=row.get("tenant_id"),
        name=vendor_name,
        canonicalName=vendor_name,
        domain=row.get("domain"),
        primaryContact=primary_contact,
        paymentTerms=payment_terms,
        customPaymentTerms=custom_payment_terms,
        categories=categories,
        category=db_category or (categories[0] if categories else None),
        annualSpend=float(row.get("annual_spend") or 0.0),
        currency=row.get("currency") or "USD",
        status=mapped_status,
        contractCount=int(row.get("contract_count") or 0),
        invoiceCount=int(row.get("invoice_count") or 0),
        transactionCount=int(row.get("transaction_count") or 0),
        metadata=meta,
        createdAt=created_str,
        updatedAt=updated_str,
        created_at=created_dt if isinstance(created_dt, datetime) else None,
        updated_at=updated_dt if isinstance(updated_dt, datetime) else None,
    )


@router.post("", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: VendorCreate,
    session: AsyncSession = Depends(get_db_session),
) -> VendorResponse:
    """Create a new vendor in the database."""
    eff_tenant = body.tenant_id or "default-org"
    name = (body.name or body.canonicalName or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vendor name is required")

    category = body.category or (body.categories[0] if body.categories else None)
    payment_terms = body.payment_terms or body.paymentTerms or body.customPaymentTerms or "net_30"
    status_val = body.status or "active"

    meta: dict[str, Any] = body.metadata or {}
    if body.primaryContact:
        meta["primaryContact"] = body.primaryContact.model_dump()
    if body.categories:
        meta["categories"] = body.categories

    new_id = uuid.uuid4()
    now = datetime.now(UTC)

    insert_sql = text("""
        INSERT INTO vendors (id, tenant_id, name, domain, category, payment_terms, status, metadata, is_active, created_at, updated_at)
        VALUES (:id, :tenant_id, :name, :domain, :category, :payment_terms, :status, CAST(:meta AS json), true, :created_at, :updated_at)
        RETURNING id, tenant_id, name, domain, category, payment_terms, status, metadata, created_at, updated_at
    """)

    import json
    try:
        res = await session.execute(
            insert_sql,
            {
                "id": new_id,
                "tenant_id": eff_tenant,
                "name": name,
                "domain": body.domain,
                "category": category,
                "payment_terms": payment_terms,
                "status": status_val,
                "meta": json.dumps(meta),
                "created_at": now,
                "updated_at": now,
            },
        )
        await session.commit()
        created_row = dict(res.mappings().first() or {})
        created_row["contract_count"] = 0
        created_row["invoice_count"] = 0
        created_row["transaction_count"] = 0
        created_row["annual_spend"] = 0.0
        logger.info("vendor_created", vendor_id=str(new_id), name=name, tenant_id=eff_tenant)
        return _map_vendor_row(created_row)
    except Exception as exc:
        await session.rollback()
        logger.error("vendor_create_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to create vendor: {exc}")


@router.get("", response_model=VendorListResponse)
async def list_vendors(
    tenant_id: str = Query("default-org", min_length=1),
    search: str | None = Query(None),
    categories: list[str] | None = Query(None),
    statuses: list[str] | None = Query(None),
    min_spend: float | None = Query(None, alias="min_spend"),
    min_spend_camel: float | None = Query(None, alias="minSpend"),
    max_spend: float | None = Query(None, alias="max_spend"),
    max_spend_camel: float | None = Query(None, alias="maxSpend"),
    sort_by: str | None = Query(None, alias="sort_by"),
    sort_by_camel: str | None = Query(None, alias="sortBy"),
    sort_order: str | None = Query(None, alias="sort_order"),
    sort_order_camel: str | None = Query(None, alias="sortOrder"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    page_size_camel: int | None = Query(None, alias="pageSize"),
    session: AsyncSession = Depends(get_db_session),
) -> VendorListResponse:
    """List vendors for a tenant with pagination and aggregation."""
    limit = page_size_camel or page_size
    offset = (page - 1) * limit

    eff_min_spend = min_spend_camel if min_spend_camel is not None else min_spend
    eff_max_spend = max_spend_camel if max_spend_camel is not None else max_spend
    eff_sort_by = sort_by_camel or sort_by or "annualSpend"
    eff_sort_order = (sort_order_camel or sort_order or "desc").lower()

    where_clauses = ["v.tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "limit": limit,
        "offset": offset,
    }

    if search and search.strip():
        search_token = f"%{search.strip().lower()}%"
        where_clauses.append(
            "(LOWER(v.name) LIKE :search OR LOWER(COALESCE(v.domain, '')) LIKE :search OR LOWER(CAST(COALESCE(v.metadata, '{}') AS TEXT)) LIKE :search)"
        )
        params["search"] = search_token

    parsed_cats: list[str] = []
    if categories:
        for c in categories:
            parsed_cats.extend([item.strip() for item in c.split(",") if item.strip()])
    if parsed_cats:
        cat_conditions = []
        regular_cats = [c for c in parsed_cats if c != "Other"]
        if regular_cats:
            cat_conditions.append("v.category = ANY(:regular_cats)")
            params["regular_cats"] = regular_cats
        if "Other" in parsed_cats:
            cat_conditions.append("(v.category IS NULL OR v.category = '' OR v.category = 'Other')")
        if cat_conditions:
            where_clauses.append(f"({' OR '.join(cat_conditions)})")

    parsed_stats: list[str] = []
    if statuses:
        for s in statuses:
            parsed_stats.extend([item.strip().lower() for item in s.split(",") if item.strip()])
    if parsed_stats:
        status_conditions = []
        direct_stats = [s for s in parsed_stats if s not in {"compliant", "active"}]
        if "compliant" in parsed_stats or "active" in parsed_stats:
            status_conditions.append("LOWER(v.status) IN ('compliant', 'active')")
        if direct_stats:
            status_conditions.append("LOWER(v.status) = ANY(:direct_stats)")
            params["direct_stats"] = direct_stats
        if status_conditions:
            where_clauses.append(f"({' OR '.join(status_conditions)})")

    outer_where: list[str] = []
    if eff_min_spend is not None:
        outer_where.append("annual_spend >= :min_spend")
        params["min_spend"] = float(eff_min_spend)
    if eff_max_spend is not None:
        outer_where.append("annual_spend <= :max_spend")
        params["max_spend"] = float(eff_max_spend)

    outer_clause = f" WHERE {' AND '.join(outer_where)}" if outer_where else ""

    order_clause = "annual_spend DESC, name ASC"
    if eff_sort_by in {"canonicalName", "name"}:
        order_clause = f"name {eff_sort_order.upper()}"
    elif eff_sort_by == "annualSpend":
        order_clause = f"annual_spend {eff_sort_order.upper()}, name ASC"
    elif eff_sort_by == "createdAt":
        order_clause = f"created_at {eff_sort_order.upper()}"
    elif eff_sort_by == "updatedAt":
        order_clause = f"updated_at {eff_sort_order.upper()}"

    sql = f"""
        WITH vendor_agg AS (
            SELECT
                v.id,
                v.tenant_id,
                v.name,
                v.domain,
                v.category,
                v.payment_terms,
                v.status,
                v.metadata,
                v.created_at,
                v.updated_at,
                COALESCE(c.contract_count, 0) AS contract_count,
                COALESCE(i.invoice_count, 0) AS invoice_count,
                COALESCE(t.transaction_count, 0) AS transaction_count,
                CAST((COALESCE(i.invoice_spend, 0) + COALESCE(t.transaction_spend, 0)) AS FLOAT) AS annual_spend
            FROM vendors v
            LEFT JOIN (
                SELECT vendor_id, COUNT(*) AS contract_count
                FROM contracts
                WHERE tenant_id = :tenant_id
                GROUP BY vendor_id
            ) c ON c.vendor_id = v.id
            LEFT JOIN (
                SELECT vendor_id, COUNT(*) AS invoice_count, SUM(total_amount) AS invoice_spend
                FROM invoices
                WHERE tenant_id = :tenant_id
                GROUP BY vendor_id
            ) i ON i.vendor_id = v.id
            LEFT JOIN (
                SELECT vendor_id, COUNT(*) AS transaction_count, SUM(amount) AS transaction_spend
                FROM card_transactions
                WHERE tenant_id = :tenant_id
                GROUP BY vendor_id
            ) t ON t.vendor_id = v.id
            WHERE {' AND '.join(where_clauses)}
        )
        SELECT *, COUNT(*) OVER() AS total_count
        FROM vendor_agg
        {outer_clause}
        ORDER BY {order_clause}
        LIMIT :limit OFFSET :offset
    """

    result = await session.execute(text(sql), params)
    raw_rows = [dict(r) for r in result.mappings().all()]

    if raw_rows:
        total = int(raw_rows[0].get("total_count") or 0)
    else:
        count_sql = f"""
            WITH vendor_agg AS (
                SELECT
                    v.id,
                    CAST((COALESCE(i.invoice_spend, 0) + COALESCE(t.transaction_spend, 0)) AS FLOAT) AS annual_spend
                FROM vendors v
                LEFT JOIN (
                    SELECT vendor_id, SUM(total_amount) AS invoice_spend
                    FROM invoices
                    WHERE tenant_id = :tenant_id
                    GROUP BY vendor_id
                ) i ON i.vendor_id = v.id
                LEFT JOIN (
                    SELECT vendor_id, SUM(amount) AS transaction_spend
                    FROM card_transactions
                    WHERE tenant_id = :tenant_id
                    GROUP BY vendor_id
                ) t ON t.vendor_id = v.id
                WHERE {' AND '.join(where_clauses)}
            )
            SELECT COUNT(*) FROM vendor_agg {outer_clause}
        """
        count_res = await session.execute(text(count_sql), params)
        total = int(count_res.scalar() or 0)

    total_pages = math.ceil(total / limit) if total > 0 else 1
    vendors = [_map_vendor_row(r) for r in raw_rows]

    logger.info("vendors_listed", tenant_id=tenant_id, count=len(vendors), total=total)
    return VendorListResponse(
        vendors=vendors,
        total=total,
        page=page,
        pageSize=limit,
        page_size=limit,
        totalPages=total_pages,
    )


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: str,
    tenant_id: str = Query("default-org", min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> VendorResponse:
    """Get a specific vendor with metrics."""
    try:
        v_uuid = uuid.UUID(vendor_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid vendor ID format")

    sql = text("""
        SELECT
            v.id,
            v.tenant_id,
            v.name,
            v.domain,
            v.category,
            v.payment_terms,
            v.status,
            v.metadata,
            v.created_at,
            v.updated_at,
            COALESCE(c.contract_count, 0) AS contract_count,
            COALESCE(i.invoice_count, 0) AS invoice_count,
            COALESCE(t.transaction_count, 0) AS transaction_count,
            CAST((COALESCE(i.invoice_spend, 0) + COALESCE(t.transaction_spend, 0)) AS FLOAT) AS annual_spend
        FROM vendors v
        LEFT JOIN (
            SELECT vendor_id, COUNT(*) AS contract_count
            FROM contracts
            WHERE tenant_id = :tenant_id
            GROUP BY vendor_id
        ) c ON c.vendor_id = v.id
        LEFT JOIN (
            SELECT vendor_id, COUNT(*) AS invoice_count, SUM(total_amount) AS invoice_spend
            FROM invoices
            WHERE tenant_id = :tenant_id
            GROUP BY vendor_id
        ) i ON i.vendor_id = v.id
        LEFT JOIN (
            SELECT vendor_id, COUNT(*) AS transaction_count, SUM(amount) AS transaction_spend
            FROM card_transactions
            WHERE tenant_id = :tenant_id
            GROUP BY vendor_id
        ) t ON t.vendor_id = v.id
        WHERE v.id = :vendor_id AND v.tenant_id = :tenant_id
    """)

    result = await session.execute(sql, {"vendor_id": v_uuid, "tenant_id": tenant_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vendor {vendor_id} not found")

    return _map_vendor_row(dict(row))


@router.patch("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: str,
    body: VendorUpdate,
    tenant_id: str = Query("default-org", min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> VendorResponse:
    """Update vendor information."""
    try:
        v_uuid = uuid.UUID(vendor_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid vendor ID format")

    fetch_sql = text("SELECT * FROM vendors WHERE id = :id AND tenant_id = :tenant_id")
    res = await session.execute(fetch_sql, {"id": v_uuid, "tenant_id": tenant_id})
    existing = res.mappings().first()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vendor {vendor_id} not found")

    existing_dict = dict(existing)
    name = body.name or body.canonicalName or existing_dict["name"]
    domain = body.domain if body.domain is not None else existing_dict.get("domain")
    category = body.category or (body.categories[0] if body.categories else existing_dict.get("category"))
    payment_terms = body.payment_terms or body.paymentTerms or body.customPaymentTerms or existing_dict.get("payment_terms")
    status_val = body.status or existing_dict.get("status")

    meta = existing_dict.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    if body.metadata:
        meta.update(body.metadata)
    if body.primaryContact:
        meta["primaryContact"] = body.primaryContact.model_dump()
    if body.categories:
        meta["categories"] = body.categories

    import json
    now = datetime.now(UTC)
    update_sql = text("""
        UPDATE vendors
        SET name = :name,
            domain = :domain,
            category = :category,
            payment_terms = :payment_terms,
            status = :status,
            metadata = CAST(:meta AS json),
            updated_at = :updated_at
        WHERE id = :id AND tenant_id = :tenant_id
    """)

    await session.execute(
        update_sql,
        {
            "id": v_uuid,
            "tenant_id": tenant_id,
            "name": name,
            "domain": domain,
            "category": category,
            "payment_terms": payment_terms,
            "status": status_val,
            "meta": json.dumps(meta),
            "updated_at": now,
        },
    )
    await session.commit()
    return await get_vendor(vendor_id, tenant_id=tenant_id, session=session)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vendor(
    vendor_id: str,
    tenant_id: str = Query("default-org", min_length=1),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a vendor."""
    try:
        v_uuid = uuid.UUID(vendor_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid vendor ID format")

    delete_sql = text("DELETE FROM vendors WHERE id = :id AND tenant_id = :tenant_id")
    res = await session.execute(delete_sql, {"id": v_uuid, "tenant_id": tenant_id})
    if res.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vendor {vendor_id} not found")
    await session.commit()
    logger.info("vendor_deleted", vendor_id=vendor_id, tenant_id=tenant_id)
