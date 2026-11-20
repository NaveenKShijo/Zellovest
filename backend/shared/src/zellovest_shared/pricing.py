"""Deterministic commercial arithmetic shared by MCP-1 and the AP-audit worker.

Every function here uses :class:`decimal.Decimal`; floats never participate in
financial math. Keeping the implementation in ``shared`` guarantees the agent's
invoice comparison and the asynchronous reconciliation engine cannot diverge.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

PRICE_TOLERANCE = Decimal("0.01")

_NET_DAYS = re.compile(r"\bnet\s+(\d{1,3})\b", re.IGNORECASE)
_PERCENT_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def to_decimal(value: Any) -> Decimal:
    """Convert a database or wire numeric value to Decimal without float math."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value if value not in (None, "") else 0))


def optional_decimal(value: Any) -> Decimal | None:
    """Return a Decimal for a present value, or None when absent/invalid."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalize_text(value: str | None) -> str:
    """Normalize identifiers and descriptions for exact matching."""
    return " ".join((value or "").split()).casefold()


def compare_unit_price(
    contract_price: Decimal,
    invoice_price: Decimal,
    *,
    tolerance: Decimal = PRICE_TOLERANCE,
) -> dict[str, Any]:
    """Return deterministic unit-price variance values for one invoice line.

    Args:
        contract_price: Effective contract unit price.
        invoice_price: Billed unit price.
        tolerance: Absolute difference treated as compliant.

    Returns:
        Dictionary with both prices, variance percentage (None when the
        contract price is zero), absolute variance, and an exception flag.
    """
    variance_amount = invoice_price - contract_price
    variance_pct: float | None
    if contract_price == 0:
        variance_pct = None
    else:
        variance_pct = float((variance_amount / contract_price) * Decimal("100"))
    return {
        "contract_price": str(contract_price),
        "invoice_price": str(invoice_price),
        "variance_amount": str(variance_amount),
        "variance_pct": variance_pct,
        "exception": abs(variance_amount) > tolerance,
    }


def compute_escalated_price(
    base_price: Decimal,
    escalation_pct: Decimal | None,
    start_date: date,
    invoice_date: date,
) -> Decimal:
    """Calculate the escalation-cap ceiling using exact Decimal math.

    Args:
        base_price: Contract base unit price.
        escalation_pct: Maximum annual escalation percentage (e.g. ``5`` = 5%).
        start_date: Effective contract/term start.
        invoice_date: Invoice date.

    Returns:
        Base price compounded once per elapsed 365-day period, rounded to cents.
    """
    if not escalation_pct or escalation_pct <= Decimal("0"):
        return base_price
    years_elapsed = max(0, (invoice_date - start_date).days // 365)
    if years_elapsed == 0:
        return base_price
    multiplier = (Decimal("1") + (escalation_pct / Decimal("100"))) ** years_elapsed
    return (base_price * multiplier).quantize(Decimal("0.01"))


def within_quantity(minimum: Any, maximum: Any, quantity: Decimal) -> bool:
    """Return True when quantity is inside the optional tier bounds."""
    lower = optional_decimal(minimum)
    upper = optional_decimal(maximum)
    return (lower is None or quantity >= lower) and (upper is None or quantity <= upper)


def payment_term_days(value: str | None) -> int | None:
    """Extract a simple Net-N payment period from contract text."""
    match = _NET_DAYS.search(value or "")
    return int(match.group(1)) if match else None


def tax_rate(value: str | None) -> Decimal | None:
    """Parse an explicit tax percentage or recognized exempt rule as a fraction."""
    normalized = normalize_text(value).replace("-", " ")
    if "exempt" in normalized or "zero rated" in normalized or "tax free" in normalized:
        return Decimal("0")
    matches = _PERCENT_RATE.findall(value or "")
    if len(matches) != 1:
        return None
    rate = Decimal(matches[0]) / Decimal("100")
    return rate if Decimal("0") <= rate <= Decimal("1") else None


def severity_for_variance(variance_pct: float | None) -> str:
    """Classify a variance magnitude as high, medium, or low severity."""
    magnitude = abs(variance_pct or 0)
    if magnitude >= 10:
        return "high"
    if magnitude >= 2:
        return "medium"
    return "low"
