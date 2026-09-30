"""Analytics schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class SpendByVendor(BaseModel):
    """Spend aggregated by vendor."""

    vendor_id: str
    vendor_name: str
    total_spend: Decimal
    invoice_count: int
    avg_invoice_amount: Decimal


class SpendByCategory(BaseModel):
    """Spend aggregated by category."""

    category: str
    total_spend: Decimal
    transaction_count: int


class SpendTrend(BaseModel):
    """Spend trend over time."""

    period: str  # YYYY-MM
    total_spend: Decimal
    transaction_count: int


class SpendAnalyticsResponse(BaseModel):
    """Complete spend analytics response."""

    tenant_id: str
    period_start: datetime
    period_end: datetime
    total_spend: Decimal
    by_vendor: list[SpendByVendor]
    by_category: list[SpendByCategory]
    trend: list[SpendTrend]
    generated_at: datetime


class VendorSpendDetail(BaseModel):
    """Detailed spend for a specific vendor."""

    vendor_id: str
    vendor_name: str
    total_spend: Decimal
    invoice_count: int
    contract_count: int
    avg_invoice_amount: Decimal
    largest_invoice: Decimal
    spend_by_category: list[SpendByCategory]
    trend: list[SpendTrend]