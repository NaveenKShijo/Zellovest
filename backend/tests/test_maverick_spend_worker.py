"""Comprehensive test suite for the Maverick Spend Detection Worker and API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from zellovest_procurement.main import create_app
from zellovest_shared.db.base import Base
from zellovest_shared.db.core import Department, Employee, MerchantProfile, SoftwareCatalog, Vendor
from zellovest_shared.db.intelligence import AlertStatus, MaverickAlert, OktaApp
from zellovest_shared.db.transact import CardTransaction
from zellovest_shared.maverick.catalog_matcher import (
    find_approved_alternatives,
)
from zellovest_shared.maverick.feature_engineering import calculate_transaction_features
from zellovest_shared.maverick.groq_vendor import resolve_merchant_product
from zellovest_shared.maverick.jev_client import (
    evaluate_stage1_screening,
    evaluate_stage4_assessment,
)
from zellovest_shared.maverick.pipeline import process_transaction_maverick_spend
from zellovest_workers.tasks.ingestion import promote_ramp_card_transactions
from zellovest_workers.tasks.maverick_spend import (
    _resolve_scan_keys,
    scan_maverick_spend_from_gcs,
)


@pytest.fixture
def sqlite_session():
    """In-memory SQLite session with all models created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_feature_engineering_monthly_cadence(sqlite_session: Session) -> None:
    """Verifies that consecutive monthly payments produce ~30-day cadence and strong recurrence."""
    tenant_id = "test-org"
    emp = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        first_name="Jane",
        last_name="Doe",
        email="jane@company.com",
    )
    sqlite_session.add(emp)
    sqlite_session.flush()

    base_time = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)

    # Historical monthly transactions: Aug, Sep, Oct
    for i in range(3):
        prior = CardTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            employee_id=emp.id,
            merchant_name="Cursor",
            amount=30.00,
            currency="USD",
            mcc="5734",
            txn_date=base_time + timedelta(days=30 * i),
            external_id=f"prior_{i}",
        )
        sqlite_session.add(prior)

    # Current transaction in Nov
    current = CardTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        employee_id=emp.id,
        merchant_name="Cursor",
        amount=30.00,
        currency="USD",
        mcc="5734",
        txn_date=base_time + timedelta(days=90),
        external_id="current_txn",
    )
    sqlite_session.add(current)
    sqlite_session.commit()

    features = calculate_transaction_features(sqlite_session, current)

    assert features["merchant_name"] == "Cursor"
    assert features["previous_transaction_count"] == 3
    assert 28 <= features["cadence_days"] <= 32
    assert features["amount_variance"] == 0.0
    assert features["is_recurrence_evidence_strong"] is True
    assert features["employee_email"] == "jane@company.com"


def test_stage1_screening_filtering() -> None:
    """Verifies that restaurants are filtered out early while software transactions proceed."""
    # 1. Restaurant purchase
    restaurant_features = {
        "merchant_name": "Joe's Burger Bar",
        "amount": 24.50,
        "currency": "USD",
        "mcc": "5812",  # Eating places
        "is_recurrence_evidence_strong": False,
        "previous_transaction_count": 0,
    }
    stage1_rest = evaluate_stage1_screening(restaurant_features)
    assert stage1_rest["proceed_to_stage2"] is False
    assert stage1_rest["is_software_score"] < 0.20

    # 2. Software purchase
    saas_features = {
        "merchant_name": "Cursor",
        "amount": 30.00,
        "currency": "USD",
        "mcc": "5734",  # Computer software
        "is_recurrence_evidence_strong": True,
        "previous_transaction_count": 2,
    }
    stage1_saas = evaluate_stage1_screening(saas_features)
    assert stage1_saas["proceed_to_stage2"] is True
    assert stage1_saas["is_software_score"] >= 0.60


def test_groq_vendor_context_resolution_and_caching(sqlite_session: Session) -> None:
    """Verifies that merchant resolution extracts capabilities and caches to MerchantProfile."""
    tenant_id = "test-org"

    # First call: cache miss, extracts via heuristic/Groq
    profile = resolve_merchant_product(
        session=sqlite_session,
        tenant_id=tenant_id,
        merchant_name="Cursor",
        mcc="5734",
    )
    assert "Cursor" in profile["product_name"]
    assert profile["category"] is not None
    assert len(profile["capabilities"]) >= 2

    # Verify cached in database
    cached_row = sqlite_session.query(MerchantProfile).filter_by(tenant_id=tenant_id, merchant_name="Cursor").first()
    assert cached_row is not None
    assert "Cursor" in cached_row.product_name

    # Second call: cache hit
    profile2 = resolve_merchant_product(
        session=sqlite_session,
        tenant_id=tenant_id,
        merchant_name="Cursor",
    )
    assert profile2.get("cached") is True


def test_stage3_catalog_matching_and_license_availability(sqlite_session: Session) -> None:
    """Verifies that unmanaged Cursor matches approved GitHub Copilot with license availability."""
    tenant_id = "test-org"

    # 1. Setup approved software vendor and catalog item
    vendor = Vendor(id=uuid.uuid4(), tenant_id=tenant_id, name="GitHub")
    sqlite_session.add(vendor)
    sqlite_session.flush()

    app = OktaApp(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        okta_app_id="okta_app_gh_123",
        name="GitHub Enterprise",
        label="GitHub Enterprise",
    )
    sqlite_session.add(app)
    sqlite_session.flush()

    catalog_item = SoftwareCatalog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="GitHub Copilot Enterprise",
        vendor_id=vendor.id,
        okta_app_id=app.id,
        category="AI coding assistant",
        capability_text="AI code completion, generation, refactoring, codebase search",
    )
    sqlite_session.add(catalog_item)
    sqlite_session.commit()

    # 2. Search approved alternatives for newly purchased Cursor
    alternatives = find_approved_alternatives(
        session=sqlite_session,
        tenant_id=tenant_id,
        product_name="Cursor AI Code Editor",
        capabilities=["Code completion", "Code generation", "Refactoring"],
        category="AI coding assistant",
    )

    assert len(alternatives) >= 1
    top = alternatives[0]
    assert top["name"] == "GitHub Copilot Enterprise"
    assert top["similarity_score"] >= 0.85
    assert top["total_licenses"] == 100
    assert top["assigned_licenses"] == 88
    assert top["unused_licenses"] == 12
    assert top["license_available"] is True


def test_stage4_final_maverick_assessment() -> None:
    """Verifies that approval records prevent maverick flagging, while unapproved SaaS flags maverick."""
    # Case A: Has prior approval
    state_approved = {
        "merchant_name": "Cursor",
        "has_been_approved": True,
        "has_approved_alternative": True,
    }
    eval_appr = evaluate_stage4_assessment(state_approved)
    assert eval_appr["assessment_outcome"] == "not_maverick"
    assert eval_appr["potential_maverick_probability"] < 0.10

    # Case B: Unapproved with available alternative seats
    state_unapproved = {
        "merchant_name": "Cursor",
        "has_been_approved": False,
        "has_approved_alternative": True,
        "overlap_score": 0.91,
        "unused_licenses": 12,
    }
    eval_unappr = evaluate_stage4_assessment(state_unapproved)
    assert eval_unappr["assessment_outcome"] == "potential_maverick"
    assert eval_unappr["potential_maverick_probability"] >= 0.80
    assert eval_unappr["review_priority"] in ("medium", "high", "critical")


def test_end_to_end_maverick_detection_pipeline(sqlite_session: Session) -> None:
    """Full 5-stage pipeline run on a $30 Cursor card transaction creating a MaverickAlert."""
    tenant_id = "test-org"

    dept = Department(id=uuid.uuid4(), tenant_id=tenant_id, name="Engineering")
    sqlite_session.add(dept)
    sqlite_session.flush()

    emp = Employee(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        department_id=dept.id,
        first_name="John",
        last_name="Smith",
        email="john@company.com",
    )
    sqlite_session.add(emp)
    sqlite_session.flush()

    # Seed approved software alternative
    cat = SoftwareCatalog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="GitHub Copilot Enterprise",
        category="AI coding assistant",
        capability_text="AI code completion, code generation, refactoring",
    )
    sqlite_session.add(cat)
    sqlite_session.flush()

    # Cleared unmanaged card transaction
    txn = CardTransaction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        employee_id=emp.id,
        merchant_name="Cursor",
        amount=30.00,
        currency="USD",
        mcc="5734",
        state="CLEARED",
        txn_date=datetime.now(UTC),
        external_id="txn_cursor_001",
    )
    sqlite_session.add(txn)
    sqlite_session.commit()

    result = process_transaction_maverick_spend(
        session=sqlite_session,
        tenant_id=tenant_id,
        transaction_id=txn.id,
    )

    assert result["status"] == "alert_created"
    assert result["merchant_name"] == "Cursor"
    assert result["probability"] >= 0.70

    # Verify alert row in database
    alert = sqlite_session.query(MaverickAlert).filter_by(transaction_id=txn.id).first()
    assert alert is not None
    assert alert.status == AlertStatus.OPEN
    assert alert.overlap_score is not None
    assert alert.overlap_score >= 0.85
    assert alert.overlap_catalog_id == cat.id
    assert "GitHub Copilot Enterprise" in alert.recommended_action
    assert "john@company.com" in alert.recommended_action
    assert alert.decision_evidence is not None


def test_promote_ramp_card_transactions_task(sqlite_session: Session) -> None:
    """Verifies that GCS bronze JSONL batch is read, normalized, and promoted into CardTransaction."""
    tenant_id = "test-org"
    mock_records = [
        {
            "id": "ramp_txn_999",
            "amount": 45.00,
            "currency": "USD",
            "merchant_name": "Figma",
            "merchant_category_code": "5734",
            "state": "CLEARED",
            "user_transaction_time": "2026-11-14T10:00:00Z",
            "memo": "Design team license",
        },
        {
            "id": "ramp_txn_998",
            "amount": 12.50,
            "currency": "USD",
            "merchant_name": "Starbucks",
            "merchant_category_code": "5814",
            "state": "CLEARED",
            "user_transaction_time": "2026-11-14T11:00:00Z",
        },
    ]

    with patch("zellovest_workers.tasks.ingestion.read_records_gz", return_value=mock_records), \
         patch("zellovest_workers.tasks.ingestion.get_session_factory", return_value=lambda: sqlite_session), \
         patch("zellovest_workers.tasks.maverick_spend.detect_maverick_spend_for_transaction.delay") as mock_delay:

        # Run task
        res = promote_ramp_card_transactions(tenant_id=tenant_id, keys=["raw/batch_001.jsonl.gz"])
        assert res["promoted"] == 2
        assert res["cleared_candidates"] == 2
        assert mock_delay.call_count == 2


@pytest.mark.asyncio
async def test_maverick_spend_api_feed() -> None:
    """Verifies GET /api/v1/maverick-spend and PATCH status update endpoint."""
    app = create_app()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result

    async def _fake_session():
        yield mock_db

    from zellovest_procurement.api.deps import get_db_session
    app.dependency_overrides[get_db_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Fetch feed
        resp = await client.get("/api/v1/maverick-spend?tenant_id=default-org")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "kpis" in data
        assert "totalUnmanagedSpend" in data["kpis"]
        assert "activeAlertsCount" in data["kpis"]
        assert "potentialAnnualSavings" in data["kpis"]
        assert "avgOverlapSimilarity" in data["kpis"]

        # 2. Trigger batch detection
        with patch(
            "zellovest_procurement.api.routers.maverick._dispatch_task",
            return_value="task_123",
        ) as mock_dispatch:
            trig_resp = await client.post(
                "/api/v1/maverick-spend/trigger",
                json={"tenant_id": "default-org", "lookback_days": 30},
            )
            assert trig_resp.status_code == 202
            trig_data = trig_resp.json()
            assert trig_data["status"] == "queued"
            assert trig_data["mode"] == "db_batch"
            assert mock_dispatch.call_args.args[0].endswith("detect_maverick_spend")

        # 3. Trigger a GCS-backed scan for one specific bronze object
        with patch(
            "zellovest_procurement.api.routers.maverick._dispatch_task",
            return_value="task_gcs",
        ) as mock_dispatch_gcs:
            gcs_resp = await client.post(
                "/api/v1/maverick-spend/trigger",
                json={
                    "tenant_id": "default-org",
                    "source": "gcs",
                    "gcs_key": (
                        "raw/ramp_card_transactions/sync=53486a04-c158-4538-87c7-"
                        "4476e9e1dcf0/cursor-final.jsonl.gz"
                    ),
                },
            )
            assert gcs_resp.status_code == 202
            gcs_data = gcs_resp.json()
            assert gcs_data["mode"] == "gcs_scan"
            assert gcs_data["gcs_key"].endswith("cursor-final.jsonl.gz")
            task_name, task_kwargs = mock_dispatch_gcs.call_args.args[0:2]
            assert task_name.endswith("scan_maverick_spend_from_gcs")
            assert task_kwargs["run_inline"] is True


def test_ingestion_gateway_exposes_maverick_trigger() -> None:
    """The frontend proxies /api/v1 to ingestion-api, so the route must exist there."""
    from zellovest_ingestion.main import create_app as create_ingestion_app

    paths = set(create_ingestion_app().openapi()["paths"])
    assert "/api/v1/maverick-spend" in paths
    assert "/api/v1/maverick-spend/trigger" in paths


def test_scan_maverick_spend_from_gcs(sqlite_session: Session) -> None:
    """GCS scan: normalize Ramp JSONL, link cardholders, and persist alerts."""
    tenant_id = "test-org"
    gcs_key = "raw/ramp_card_transactions/sync=abc/cursor-final.jsonl.gz"
    mock_records = [
        {
            "id": "ramp_scan_saas_1",
            "amount": 218.08,
            "currency_code": "USD",
            "merchant_name": "Adobe",
            "sk_category_name": "SaaS / Software",
            "merchant_category_code": None,
            "state": "CLEARED",
            "user_transaction_time": "2026-11-16T10:00:00Z",
            "settlement_date": "2026-11-18T10:00:00Z",
            "card_holder": {
                "user_id": "ramp-user-1",
                "first_name": "David",
                "last_name": "Wallace",
                "department_name": "Executive",
                "department_id": "ramp-dept-1",
            },
            "all_requirements_met_and_approved": False,
        },
        {
            "id": "ramp_scan_meal_1",
            "amount": 42.10,
            "currency_code": "USD",
            "merchant_name": "Pret A Manger",
            "sk_category_name": "Restaurants",
            "merchant_category_code": None,
            "state": "CLEARED",
            "user_transaction_time": "2026-11-16T12:00:00Z",
        },
    ]

    fake_settings = MagicMock()
    fake_settings.gcs_raw_bucket = "test-bucket"
    fake_settings.google_cloud_project = None

    def _fake_stage1(features: dict, settings=None) -> dict:
        if features.get("is_non_software_category"):
            return {
                "is_software_score": 0.05,
                "is_subscription_score": 0.10,
                "warrants_investigation_score": 0.05,
                "proceed_to_stage2": False,
                "method": "rule_early_exit",
            }
        return {
            "is_software_score": 0.95,
            "is_subscription_score": 0.62,
            "warrants_investigation_score": 0.95,
            "proceed_to_stage2": True,
            "method": "rule_fallback",
        }

    with patch(
        "zellovest_workers.tasks.maverick_spend.get_settings",
        return_value=fake_settings,
    ), patch(
        "zellovest_workers.tasks.maverick_spend.read_records_gz",
        return_value=mock_records,
    ), patch(
        "zellovest_workers.tasks.maverick_spend.get_session_factory",
        return_value=lambda: sqlite_session,
    ), patch(
        "zellovest_shared.maverick.pipeline.evaluate_stage1_screening",
        side_effect=_fake_stage1,
    ), patch(
        "zellovest_shared.maverick.pipeline.resolve_merchant_product",
        return_value={
            "product_name": "Adobe Creative Cloud",
            "category": "Design software",
            "capabilities": ["Photo editing", "Design systems"],
        },
    ), patch(
        "zellovest_shared.maverick.pipeline.find_approved_alternatives",
        return_value=[],
    ), patch(
        "zellovest_shared.maverick.pipeline.evaluate_stage4_assessment",
        return_value={
            "potential_maverick_probability": 0.78,
            "assessment_outcome": "potential_maverick",
            "review_priority": "medium",
            "method": "rule_fallback",
        },
    ):
        result = scan_maverick_spend_from_gcs(
            tenant_id=tenant_id,
            gcs_key=gcs_key,
            run_inline=True,
        )

    assert result["status"] == "completed"
    assert result["keys"] == [gcs_key]
    assert result["promoted"] == 2
    assert result["cleared"] == 2
    assert result["flagged"] == 1

    txn = (
        sqlite_session.query(CardTransaction)
        .filter_by(tenant_id=tenant_id, external_id="ramp_scan_saas_1")
        .one()
    )
    assert txn.cardholder_name_raw == "David Wallace"
    assert txn.currency == "USD"
    assert txn.sk_category_name == "SaaS / Software"
    assert txn.cleared_at is not None

    alert = sqlite_session.query(MaverickAlert).filter_by(transaction_id=txn.id).one()
    assert alert.merchant_name == "Adobe"
    assert alert.assessment_outcome == "potential_maverick"

    meal = (
        sqlite_session.query(CardTransaction)
        .filter_by(tenant_id=tenant_id, external_id="ramp_scan_meal_1")
        .one()
    )
    assert (
        sqlite_session.query(MaverickAlert).filter_by(transaction_id=meal.id).first() is None
    )


def test_resolve_scan_keys_prefers_explicit_target() -> None:
    """Explicit gcs_key/sync_id/prefix resolve to the right bronze objects."""
    # 1. An explicit key is returned verbatim without touching GCS.
    assert _resolve_scan_keys(
        bucket="b",
        project=None,
        gcs_key="raw/ramp_card_transactions/sync=abc/cursor-final.jsonl.gz",
        sync_id=None,
        prefix=None,
        lookback_days=90,
    ) == ["raw/ramp_card_transactions/sync=abc/cursor-final.jsonl.gz"]

    # 2. A sync id expands to that sync partition.
    with patch(
        "zellovest_workers.tasks.maverick_spend.list_object_keys",
        return_value=["raw/ramp_card_transactions/sync=abc/part-0.jsonl.gz"],
    ) as mock_list:
        keys = _resolve_scan_keys(
            bucket="b",
            project="p",
            gcs_key=None,
            sync_id="abc",
            prefix=None,
            lookback_days=90,
        )
    assert keys == ["raw/ramp_card_transactions/sync=abc/part-0.jsonl.gz"]
    assert mock_list.call_args.kwargs["prefix"] == "raw/ramp_card_transactions/sync=abc/"

    # 3. With no target, the whole card-transaction prefix is discovered.
    with patch(
        "zellovest_workers.tasks.maverick_spend.list_object_keys",
        return_value=["raw/ramp_card_transactions/sync=xyz/cursor-final.jsonl.gz"],
    ) as mock_list:
        keys = _resolve_scan_keys(
            bucket="b",
            project=None,
            gcs_key=None,
            sync_id=None,
            prefix=None,
            lookback_days=0,
        )
    assert keys == ["raw/ramp_card_transactions/sync=xyz/cursor-final.jsonl.gz"]
    assert mock_list.call_args.kwargs["prefix"] == "raw/ramp_card_transactions/"
    assert mock_list.call_args.kwargs["modified_since"] is None


def test_scan_maverick_spend_from_gcs_no_data() -> None:
    """An empty bronze preview returns no_data instead of raising."""
    fake_settings = MagicMock()
    fake_settings.gcs_raw_bucket = "test-bucket"
    fake_settings.google_cloud_project = None

    with patch(
        "zellovest_workers.tasks.maverick_spend.get_settings",
        return_value=fake_settings,
    ), patch(
        "zellovest_workers.tasks.maverick_spend.list_object_keys",
        return_value=[],
    ):
        result = scan_maverick_spend_from_gcs(tenant_id="test-org", sync_id="missing")

    assert result["status"] == "no_data"
    assert result["keys"] == []
    assert result["promoted"] == 0
    assert result["flagged"] == 0

