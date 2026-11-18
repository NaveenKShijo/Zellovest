"""Historical transaction feature engineering for Maverick Spend detection."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.core import Department, Employee
from zellovest_shared.db.transact import CardTransaction
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

# Ramp ``sk_category_name`` values that clearly describe recurring software.
_SOFTWARE_CATEGORY_KEYWORDS = ("software", "saas", "cloud", "subscription")
# Categories that are normal business expenses, not maverick SaaS candidates.
_NON_SOFTWARE_CATEGORY_KEYWORDS = (
    "restaurant",
    "food",
    "grocery",
    "supermarket",
    "travel",
    "hotel",
    "airline",
    "fuel",
    "gas station",
    "transport",
    "meal",
    "coffee",
)


def _category_signals(transaction: CardTransaction) -> tuple[str, bool, bool]:
    """Derive software / non-software signals from MCC and Ramp category.

    Ramp frequently sends ``merchant_category_code = null`` while still
    populating ``sk_category_name`` (for example ``"SaaS / Software"`` or
    ``"Restaurants"``). Using both signals keeps detection accurate when MCC is
    absent.

    Args:
        transaction: Card transaction being screened.

    Returns:
        Tuple of ``(sk_category_name, is_software_category,
        is_non_software_category)``.
    """
    sk_category = str(transaction.sk_category_name or "").strip()
    sk_lower = sk_category.lower()
    mcc = str(transaction.mcc or "").strip()
    is_software = mcc == "5734" or any(
        keyword in sk_lower for keyword in _SOFTWARE_CATEGORY_KEYWORDS
    )
    is_non_software = (not is_software) and any(
        keyword in sk_lower for keyword in _NON_SOFTWARE_CATEGORY_KEYWORDS
    )
    return sk_category, is_software, is_non_software


def calculate_transaction_features(
    session: Session,
    transaction: CardTransaction,
    lookback_days: int = 180,
) -> dict[str, Any]:
    """Calculate historical recurrence and employee spending features.

    Args:
        session: Active SQLAlchemy session.
        transaction: The current card transaction being screened.
        lookback_days: Window to search for prior transactions (default 180).

    Returns:
        Dictionary of calculated numerical and categorical features.
    """
    tenant_id = transaction.tenant_id
    current_date = transaction.txn_date or datetime.now(UTC)
    if current_date.tzinfo is None:
        current_date = current_date.replace(tzinfo=UTC)

    sk_category, is_software_category, is_non_software_category = _category_signals(
        transaction
    )

    lookback_cutoff = current_date - timedelta(days=lookback_days)

    # 1. Resolve Employee and Department context
    employee_email: str | None = None
    employee_name: str | None = None
    department_name: str | None = None

    if transaction.employee_id:
        emp = session.get(Employee, transaction.employee_id)
        if emp:
            employee_email = emp.email
            first = emp.first_name or ""
            last = emp.last_name or ""
            employee_name = f"{first} {last}".strip() or employee_email
            if emp.department_id:
                dept = session.get(Department, emp.department_id)
                if dept:
                    department_name = dept.name
    elif transaction.cardholder_name_raw:
        employee_name = transaction.cardholder_name_raw

    # 2. Historical transactions from this merchant for this tenant/employee
    stmt = (
        select(CardTransaction)
        .where(
            CardTransaction.tenant_id == tenant_id,
            CardTransaction.id != transaction.id,
            CardTransaction.txn_date < current_date,
            CardTransaction.txn_date >= lookback_cutoff,
        )
        .order_by(CardTransaction.txn_date.asc())
    )
    all_recent = list(session.execute(stmt).scalars().all())

    merchant_normalized = transaction.merchant_name.strip().lower()
    same_merchant_txns = [
        t
        for t in all_recent
        if t.merchant_name
        and (
            t.merchant_name.strip().lower() == merchant_normalized
            or merchant_normalized in t.merchant_name.strip().lower()
            or t.merchant_name.strip().lower() in merchant_normalized
        )
    ]

    # Filter to this employee first if available, else fallback to organization-wide
    emp_merchant_txns = (
        [t for t in same_merchant_txns if t.employee_id == transaction.employee_id]
        if transaction.employee_id
        else same_merchant_txns
    )

    prior_txns = emp_merchant_txns if emp_merchant_txns else same_merchant_txns
    prior_count = len(prior_txns)

    def _as_utc(dt: datetime | None) -> datetime:
        if dt is None:
            return datetime.now(UTC)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    # 3. Calculate cadence and intervals
    intervals: list[float] = []
    prior_amounts: list[float] = []

    all_chain = [*prior_txns, transaction]
    sorted_chain = sorted(all_chain, key=lambda t: _as_utc(t.txn_date))

    for i in range(1, len(sorted_chain)):
        delta = (
            _as_utc(sorted_chain[i].txn_date) - _as_utc(sorted_chain[i - 1].txn_date)
        ).total_seconds() / 86400.0
        intervals.append(delta)

    for t in prior_txns:
        prior_amounts.append(float(t.amount or 0.0))

    if intervals:
        avg_cadence = sum(intervals) / len(intervals)
        cadence_days = round(avg_cadence)
    else:
        cadence_days = 30  # Default assumed subscription cadence

    # Amount variance
    curr_amount = float(transaction.amount or 0.0)
    all_amounts = [*prior_amounts, curr_amount]
    if len(all_amounts) > 1:
        mean_amount = sum(all_amounts) / len(all_amounts)
        amount_variance = math.sqrt(
            sum((x - mean_amount) ** 2 for x in all_amounts) / len(all_amounts)
        )
    else:
        amount_variance = 0.0

    # Recurrence signal strength
    # Monthly: ~25-35 days, Annual: ~350-375 days with low variance
    is_monthly = 24 <= cadence_days <= 36
    is_annual = 350 <= cadence_days <= 380
    is_low_variance = amount_variance <= 5.0 or (
        curr_amount > 0 and (amount_variance / curr_amount) <= 0.05
    )

    is_recurrence_evidence_strong = (
        (prior_count >= 1) and (is_monthly or is_annual) and is_low_variance
    )

    # 4. Employee software spend aggregates (30d and 90d)
    spend_30d_cutoff = current_date - timedelta(days=30)
    spend_90d_cutoff = current_date - timedelta(days=90)

    emp_txns = (
        [t for t in all_recent if t.employee_id == transaction.employee_id]
        if transaction.employee_id
        else all_recent
    )

    software_spend_30d = sum(
        float(t.amount)
        for t in emp_txns
        if _as_utc(t.txn_date) >= spend_30d_cutoff and (t.mcc == "5734" or t.is_recurring)
    )
    software_spend_90d = sum(
        float(t.amount)
        for t in emp_txns
        if _as_utc(t.txn_date) >= spend_90d_cutoff and (t.mcc == "5734" or t.is_recurring)
    )

    features = {
        "transaction_id": str(transaction.id),
        "tenant_id": tenant_id,
        "merchant_name": transaction.merchant_name,
        "amount": curr_amount,
        "currency": transaction.currency or "USD",
        "mcc": transaction.mcc,
        "sk_category_name": sk_category,
        "is_software_category": is_software_category,
        "is_non_software_category": is_non_software_category,
        "memo": transaction.memo,
        "card_last4": transaction.card_last4 or "",
        "employee_id": str(transaction.employee_id) if transaction.employee_id else None,
        "employee_name": employee_name or "Unknown Employee",
        "employee_email": employee_email or "unknown@company.com",
        "department": department_name or "Unassigned",
        "transaction_date": current_date.isoformat(),
        "previous_transaction_count": prior_count,
        "cadence_days": cadence_days,
        "amount_variance": round(amount_variance, 2),
        "is_recurrence_evidence_strong": is_recurrence_evidence_strong,
        "employee_software_spend_30d": round(software_spend_30d, 2),
        "employee_software_spend_90d": round(software_spend_90d, 2),
        "has_been_approved": bool(transaction.has_been_approved or transaction.requirements_met),
    }

    logger.info(
        "maverick_features_calculated",
        transaction_id=str(transaction.id),
        merchant=transaction.merchant_name,
        prior_count=prior_count,
        cadence_days=cadence_days,
        is_recurrent=is_recurrence_evidence_strong,
    )
    return features
