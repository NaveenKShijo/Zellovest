"""Maverick Spend Detection Pipeline orchestrator (Stages 1 through 5)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.config import get_settings
from zellovest_shared.db.intelligence import AlertStatus, MaverickAlert
from zellovest_shared.db.transact import CardTransaction
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.maverick.catalog_matcher import find_approved_alternatives
from zellovest_shared.maverick.feature_engineering import calculate_transaction_features
from zellovest_shared.maverick.groq_vendor import resolve_merchant_product
from zellovest_shared.maverick.jev_client import (
    evaluate_stage1_screening,
    evaluate_stage4_assessment,
)

logger = get_logger(__name__)


def process_transaction_maverick_spend(
    session: Session,
    tenant_id: str,
    transaction_id: str | uuid.UUID,
    settings: Any = None,
) -> dict[str, Any]:
    """Execute the complete 5-stage Maverick Spend detection workflow on a single transaction.

    Stages:
        Stage 1: Feature Engineering & Preliminary Jev AI Screening
        Stage 2: Merchant & Product Context Resolution (Groq JSON + Cache)
        Stage 3: Approved Software Capability Retrieval (Qdrant + License Check)
        Stage 4: Final Maverick Spend Assessment (Deterministic Policy + Jev AI)
        Stage 5: Alert Generation & Persistence (MaverickAlert)
    """
    settings = settings or get_settings()
    txn_uuid = uuid.UUID(str(transaction_id)) if isinstance(transaction_id, str) else transaction_id

    # 0. Load canonical transaction
    txn = session.get(CardTransaction, txn_uuid)
    if not txn or txn.tenant_id != tenant_id:
        logger.warning(
            "maverick_pipeline_txn_not_found",
            transaction_id=str(transaction_id),
            tenant_id=tenant_id,
        )
        return {"status": "not_found", "transaction_id": str(transaction_id)}

    # Skip non-positive or declined transactions
    if float(txn.amount or 0.0) <= 0.0 or str(txn.state or "").upper() == "DECLINED":
        logger.info(
            "maverick_pipeline_skip_non_positive",
            transaction_id=str(transaction_id),
            amount=float(txn.amount),
        )
        return {"status": "skipped_non_positive", "transaction_id": str(transaction_id)}

    # Stage 1: Feature Engineering & Preliminary Screening
    features = calculate_transaction_features(session, txn)
    stage1 = evaluate_stage1_screening(features, settings=settings)

    if not stage1.get("proceed_to_stage2", False):
        logger.info(
            "maverick_pipeline_stage1_exit", transaction_id=str(transaction_id), scores=stage1
        )
        return {
            "status": "stage1_filtered_out",
            "transaction_id": str(transaction_id),
            "stage1_scores": stage1,
        }

    # Stage 2: Merchant & Product Context Resolution (Groq)
    product_profile = resolve_merchant_product(
        session=session,
        tenant_id=tenant_id,
        merchant_name=txn.merchant_name,
        memo=txn.memo,
        mcc=txn.mcc,
        settings=settings,
    )

    product_name = product_profile.get("product_name") or txn.merchant_name
    category = product_profile.get("category") or "Software"
    capabilities = product_profile.get("capabilities", [])

    # Stage 3: Approved Software Capability Retrieval (Qdrant + License Availability)
    alternatives = find_approved_alternatives(
        session=session,
        tenant_id=tenant_id,
        product_name=product_name,
        capabilities=capabilities,
        category=category,
        settings=settings,
    )

    top_alt = alternatives[0] if alternatives else None
    has_alt = top_alt is not None and top_alt["similarity_score"] >= 0.70

    # Stage 4: Final Maverick Spend Assessment (Policy + Jev)
    decision_state = {
        "merchant_name": txn.merchant_name,
        "product_name": product_name,
        "amount": float(txn.amount),
        "currency": txn.currency or "USD",
        "cadence_days": features.get("cadence_days", 30),
        "is_subscription": stage1.get("is_subscription_score", 0.5) >= 0.60
        or features.get("is_recurrence_evidence_strong", False),
        "requires_procurement_approval": True,
        "has_been_approved": features.get("has_been_approved", False),
        "has_approved_alternative": has_alt,
        "approved_alternative_name": top_alt["name"] if top_alt else None,
        "overlap_score": top_alt["similarity_score"] if top_alt else 0.0,
        "unused_licenses": top_alt["unused_licenses"] if top_alt else 0,
        "department": features.get("department", "Unknown"),
    }

    stage4 = evaluate_stage4_assessment(decision_state, settings=settings)
    prob_maverick = stage4.get("potential_maverick_probability", 0.0)
    outcome = stage4.get("assessment_outcome", "insufficient_evidence")

    # Stage 5: Alert Generation & Persistence
    is_flagged = (prob_maverick >= 0.70 or outcome == "potential_maverick") and not features.get(
        "has_been_approved", False
    )

    if not is_flagged:
        logger.info(
            "maverick_pipeline_compliant_or_insufficient",
            transaction_id=str(transaction_id),
            outcome=outcome,
            p=prob_maverick,
        )
        return {
            "status": "not_maverick",
            "transaction_id": str(transaction_id),
            "probability": prob_maverick,
            "outcome": outcome,
        }

    # Construct recommendation text
    employee_name = features.get("employee_name", "the employee")
    employee_email = features.get("employee_email", "")
    department = features.get("department", "their department")

    if top_alt and top_alt.get("license_available"):
        rec_action = (
            f"Notify {employee_name} ({employee_email}) in {department}. "
            f"The company already maintains enterprise agreement for {top_alt['name']} "
            f"with {top_alt['unused_licenses']} unused seats available."
        )
    elif top_alt:
        rec_action = (
            f"Procurement review recommended. Employee {employee_name} purchased "
            f"{product_name}, which overlaps with approved software {top_alt['name']}, "
            "but all enterprise seats are currently assigned."
        )
    else:
        rec_action = (
            f"Unmanaged recurring SaaS subscription detected for {product_name}. "
            f"Contact {employee_name} ({employee_email}) for procurement review."
        )

    # Evidence payload
    decision_evidence = {
        "features": features,
        "stage1_screening": stage1,
        "product_profile": product_profile,
        "retrieved_alternatives": alternatives,
        "stage4_assessment": stage4,
        "has_approved_alternative": has_alt,
        "alternative_licenses_available": top_alt.get("license_available", False)
        if top_alt
        else False,
    }

    # Upsert MaverickAlert
    alert_stmt = select(MaverickAlert).where(
        MaverickAlert.tenant_id == tenant_id,
        MaverickAlert.transaction_id == txn_uuid,
    )
    existing_alert = session.execute(alert_stmt).scalars().first()

    catalog_fk = (
        uuid.UUID(top_alt["catalog_id"]) if (top_alt and top_alt.get("catalog_id")) else None
    )

    if existing_alert:
        existing_alert.jev_is_saas_score = stage1.get("is_software_score")
        existing_alert.jev_review_score = prob_maverick
        existing_alert.capability_text = f"{product_name} ({category}): {', '.join(capabilities)}"
        existing_alert.overlap_catalog_id = catalog_fk
        existing_alert.overlap_score = top_alt["similarity_score"] if top_alt else None
        existing_alert.recommended_action = rec_action
        existing_alert.decision_evidence = decision_evidence
        existing_alert.assessment_outcome = outcome
        alert = existing_alert
    else:
        alert = MaverickAlert(
            tenant_id=tenant_id,
            transaction_id=txn_uuid,
            employee_id=txn.employee_id,
            merchant_name=txn.merchant_name,
            jev_is_saas_score=stage1.get("is_software_score"),
            jev_review_score=prob_maverick,
            status=AlertStatus.OPEN,
            capability_text=f"{product_name} ({category}): {', '.join(capabilities)}",
            overlap_catalog_id=catalog_fk,
            overlap_score=top_alt["similarity_score"] if top_alt else None,
            recommended_action=rec_action,
            decision_evidence=decision_evidence,
            assessment_outcome=outcome,
        )
        session.add(alert)

    session.commit()
    logger.info(
        "maverick_alert_persisted",
        alert_id=str(alert.id),
        merchant=txn.merchant_name,
        p=prob_maverick,
    )

    return {
        "status": "alert_created",
        "alert_id": str(alert.id),
        "transaction_id": str(transaction_id),
        "merchant_name": txn.merchant_name,
        "probability": prob_maverick,
        "outcome": outcome,
        "recommended_action": rec_action,
    }
