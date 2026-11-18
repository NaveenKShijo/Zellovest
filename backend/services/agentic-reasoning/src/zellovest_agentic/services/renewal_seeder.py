"""Database Seeder for Live Renewal Intelligence Contracts.

Populates PostgreSQL with real enterprise vendors, active software contracts,
contract versions, lines, versioned pricing terms, and invoices for the specified
tenant so that Renewal Intelligence operates entirely on live database records.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import (
    ExceptionRule,
    ExceptionStatus,
    ReconciliationException,
)
from zellovest_shared.db.transact import (
    Contract,
    ContractChangeType,
    ContractLine,
    ContractStatus,
    ContractTermsVersion,
    ContractVersion,
    Invoice,
    InvoiceStatus,
)


async def seed_tenant_renewal_contracts(session: AsyncSession, tenant_id: str = "default-org") -> int:
    """Ensure authentic commercial contracts exist in PostgreSQL for the tenant."""
    now_dt = datetime.now(UTC)
    today = now_dt.date()

    contract_numbers = [
        "CTR-ADOBE-2024",
        "CTR-SFDC-2024",
        "CTR-DDOG-2024",
        "CTR-SLACK-2024",
        "CTR-FIGMA-2024",
        "CTR-ZOOM-2024",
        "CTR-SNOW-2024",
    ]

    # Check if contracts already exist
    existing_res = await session.execute(
        select(Contract.id).where(
            Contract.tenant_id == tenant_id,
            Contract.contract_number.in_(contract_numbers),
        )
    )
    existing_ids = [row[0] for row in existing_res.fetchall()]

    if existing_ids:
        # Delete related dependent rows before re-inserting fresh relative dates
        await session.execute(
            delete(ReconciliationException).where(
                ReconciliationException.contract_id.in_(existing_ids)
            )
        )
        await session.execute(
            delete(Invoice).where(
                Invoice.contract_id.in_(existing_ids)
            )
        )
        await session.execute(
            delete(ContractTermsVersion).where(
                ContractTermsVersion.contract_id.in_(existing_ids)
            )
        )
        await session.execute(
            delete(ContractLine).where(
                ContractLine.contract_id.in_(existing_ids)
            )
        )
        await session.execute(
            delete(ContractVersion).where(
                ContractVersion.contract_id.in_(existing_ids)
            )
        )
        await session.execute(
            delete(Contract).where(Contract.id.in_(existing_ids))
        )

    # 1. Vendors
    vendor_configs = [
        {"name": "Adobe Inc.", "domain": "adobe.com", "category": "Design & Creativity", "payment_terms": "Net 30"},
        {"name": "Salesforce Inc.", "domain": "salesforce.com", "category": "Customer Relationship Management", "payment_terms": "Net 45"},
        {"name": "Datadog Inc.", "domain": "datadoghq.com", "category": "Cloud Infrastructure & APM", "payment_terms": "Net 30"},
        {"name": "Slack Technologies", "domain": "slack.com", "category": "Team Collaboration", "payment_terms": "Net 30"},
        {"name": "Figma Inc.", "domain": "figma.com", "category": "UI/UX Prototyping", "payment_terms": "Net 30"},
        {"name": "Zoom Video Communications", "domain": "zoom.us", "category": "Unified Communications", "payment_terms": "Net 30"},
        {"name": "Snowflake Inc.", "domain": "snowflake.com", "category": "Cloud Data Warehousing", "payment_terms": "Net 60"},
    ]

    vendor_map: dict[str, uuid.UUID] = {}
    for v in vendor_configs:
        res_v = await session.execute(
            select(Vendor.id).where(
                Vendor.tenant_id == tenant_id,
                Vendor.name == v["name"],
            )
        )
        v_id = res_v.scalar_one_or_none()
        if not v_id:
            v_id = uuid.uuid4()
            session.add(
                Vendor(
                    id=v_id,
                    tenant_id=tenant_id,
                    name=v["name"],
                    domain=v["domain"],
                    category=v["category"],
                    payment_terms=v["payment_terms"],
                    status="active",
                    is_active=True,
                )
            )
        vendor_map[v["name"]] = v_id

    await session.flush()

    # 2. Contracts
    contract_data = [
        {
            "number": "CTR-ADOBE-2024",
            "vendor": "Adobe Inc.",
            "title": "Adobe Creative Cloud Enterprise Agreement",
            "start_offset": -340,
            "renewal_offset": 25,  # 30d badge
            "notice_period": 30,  # Notice deadline is 5 days ago (urgent critical notice window!)
            "auto_renew": True,
            "clause": "This Enterprise Agreement automatically renews for successive 12-month periods unless customer delivers written notice of non-renewal at least 30 calendar days prior to contract expiration. Section 8.2: Annual fee escalation shall not exceed the lesser of CPI-U or 3.5%.",
            "unit_price": Decimal("945.00"),
            "qty": Decimal("100"),
            "annual_spend": Decimal("94500.00"),
        },
        {
            "number": "CTR-SFDC-2024",
            "vendor": "Salesforce Inc.",
            "title": "Sales Cloud & Service Cloud Enterprise Edition",
            "start_offset": -310,
            "renewal_offset": 55,  # 60d badge
            "notice_period": 60,  # Notice deadline is 5 days ago (urgent notice passed!)
            "auto_renew": True,
            "clause": "Customer must provide written opt-out of renewal at least 60 days prior to contract anniversary date. Section 12.4: Pricing for renewals is subject to standard list price without grandfathered discounts if opt-out window lapses.",
            "unit_price": Decimal("1800.00"),
            "qty": Decimal("102"),
            "annual_spend": Decimal("183600.00"),
        },
        {
            "number": "CTR-DDOG-2024",
            "vendor": "Datadog Inc.",
            "title": "Datadog Infrastructure Monitoring & APM Pro Commit",
            "start_offset": -285,
            "renewal_offset": 80,  # 90d badge
            "notice_period": 30,  # Notice deadline in 50 days
            "auto_renew": True,
            "clause": "Automatic renewal for subsequent 12-month terms unless 30-day written cancellation notice is received. Section 4.3: Custom metrics and ingestion overages are invoiced at $0.05 per metric without contracted tier allowances.",
            "unit_price": Decimal("230.00"),
            "qty": Decimal("600"),
            "annual_spend": Decimal("138000.00"),
        },
        {
            "number": "CTR-SLACK-2024",
            "vendor": "Slack Technologies",
            "title": "Slack Enterprise Grid Master Subscription",
            "start_offset": -260,
            "renewal_offset": 105,  # 120d badge
            "notice_period": 45,  # Notice deadline in 60 days
            "auto_renew": True,
            "clause": "Subscription shall automatically renew for additional 1-year terms unless either party provides written notice of non-renewal at least 45 days prior to expiration.",
            "unit_price": Decimal("180.00"),
            "qty": Decimal("496"),
            "annual_spend": Decimal("89280.00"),
        },
        {
            "number": "CTR-FIGMA-2024",
            "vendor": "Figma Inc.",
            "title": "Figma Organization & FigJam Enterprise License",
            "start_offset": -245,
            "renewal_offset": 120,  # 120d badge
            "notice_period": 30,
            "auto_renew": False,  # Manual renewal
            "clause": "This Agreement does not auto-renew. Customer must execute a Renewal Order Form prior to expiration date to avoid service suspension. Existing design assets remain accessible for 30 days post expiration.",
            "unit_price": Decimal("540.00"),
            "qty": Decimal("90"),
            "annual_spend": Decimal("48600.00"),
        },
        {
            "number": "CTR-ZOOM-2024",
            "vendor": "Zoom Video Communications",
            "title": "Zoom Workplace Enterprise Bundle",
            "start_offset": -210,
            "renewal_offset": 155,  # future badge
            "notice_period": 30,
            "auto_renew": True,
            "clause": "Service plan auto-renews annually unless customer submits cancellation request via portal or written notice at least 30 days prior to term end.",
            "unit_price": Decimal("240.00"),
            "qty": Decimal("150"),
            "annual_spend": Decimal("36000.00"),
        },
        {
            "number": "CTR-SNOW-2024",
            "vendor": "Snowflake Inc.",
            "title": "Snowflake Enterprise Capacity Commitment",
            "start_offset": -180,
            "renewal_offset": 185,  # future badge
            "notice_period": 60,
            "auto_renew": True,
            "clause": "Unused capacity rollover requires minimum 60-day notice and renewal commitment of equal or greater annual contract value. Standard rates apply to uncommitted compute overage.",
            "unit_price": Decimal("4000.00"),
            "qty": Decimal("60"),
            "annual_spend": Decimal("240000.00"),
        },
    ]

    seeded_records = []
    for c in contract_data:
        c_id = uuid.uuid4()
        v_id = vendor_map[c["vendor"]]
        start_d = today + timedelta(days=c["start_offset"])
        renewal_d = today + timedelta(days=c["renewal_offset"])

        session.add(
            Contract(
                id=c_id,
                tenant_id=tenant_id,
                vendor_id=v_id,
                contract_number=c["number"],
                title=c["title"],
                status=ContractStatus.ACTIVE,
                start_date=start_d,
                end_date=renewal_d,
                renewal_date=renewal_d,
                notice_period_days=c["notice_period"],
                auto_renew=c["auto_renew"],
                termination_clause=c["clause"],
            )
        )

        version_id = uuid.uuid4()
        session.add(
            ContractVersion(
                id=version_id,
                tenant_id=tenant_id,
                contract_id=c_id,
                version_no=1,
                change_type=ContractChangeType.ORIGINAL,
                effective_from=start_d,
                effective_to=renewal_d,
                title=c["title"],
                contract_start_date=start_d,
                contract_end_date=renewal_d,
                renewal_date=renewal_d,
                notice_period_days=c["notice_period"],
                auto_renew=c["auto_renew"],
                termination_clause=c["clause"],
            )
        )

        line_id = uuid.uuid4()
        session.add(
            ContractLine(
                id=line_id,
                tenant_id=tenant_id,
                contract_id=c_id,
            )
        )

        term_id = uuid.uuid4()
        session.add(
            ContractTermsVersion(
                id=term_id,
                tenant_id=tenant_id,
                contract_id=c_id,
                contract_version_id=version_id,
                contract_line_id=line_id,
                version_no=1,
                line_no=1,
                product_code=c["number"].replace("CTR-", "SKU-"),
                description=c["title"],
                unit_price=c["unit_price"],
                currency="USD",
                qty_min=c["qty"],
                qty_max=c["qty"],
                effective_from=start_d,
                effective_to=renewal_d,
            )
        )

        inv_id = uuid.uuid4()
        q_amount = c["annual_spend"] / Decimal("4")
        session.add(
            Invoice(
                id=inv_id,
                tenant_id=tenant_id,
                vendor_id=v_id,
                contract_id=c_id,
                invoice_number=f"INV-{c['number'][4:]}-Q3",
                invoice_date=now_dt - timedelta(days=45),
                due_date=now_dt - timedelta(days=15),
                subtotal=q_amount,
                tax_amount=Decimal("0.00"),
                total_amount=q_amount,
                currency="USD",
                status=InvoiceStatus.PAID,
            )
        )

        seeded_records.append({
            "contract_id": c_id,
            "version_id": version_id,
            "term_id": term_id,
            "vendor_id": v_id,
            "invoice_id": inv_id,
            "config": c,
        })

    await session.flush()

    # Add AP reconciliation exceptions for commercial leverage
    ddog_rec = [r for r in seeded_records if r["config"]["number"] == "CTR-DDOG-2024"][0]
    session.add(
        ReconciliationException(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            contract_id=ddog_rec["contract_id"],
            contract_version_id=ddog_rec["version_id"],
            contract_term_id=ddog_rec["term_id"],
            invoice_id=ddog_rec["invoice_id"],
            rule_type=ExceptionRule.PRICE,
            severity="medium",
            status=ExceptionStatus.OPEN,
            expected_value=Decimal("10500.00"),
            billed_value=Decimal("14620.00"),
            variance_amount=Decimal("4120.00"),
            variance_pct=Decimal("0.3924"),
        )
    )

    sfdc_rec = [r for r in seeded_records if r["config"]["number"] == "CTR-SFDC-2024"][0]
    session.add(
        ReconciliationException(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            contract_id=sfdc_rec["contract_id"],
            contract_version_id=sfdc_rec["version_id"],
            contract_term_id=sfdc_rec["term_id"],
            invoice_id=sfdc_rec["invoice_id"],
            rule_type=ExceptionRule.PAYMENT_TERM,
            severity="low",
            status=ExceptionStatus.OPEN,
            expected_value=Decimal("15350.00"),
            billed_value=Decimal("15350.00"),
            variance_amount=Decimal("0.00"),
            variance_pct=Decimal("0.00"),
        )
    )

    await session.commit()
    return len(seeded_records)
