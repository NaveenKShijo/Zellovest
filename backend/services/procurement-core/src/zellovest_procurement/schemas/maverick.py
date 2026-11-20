"""Pydantic schemas for Maverick Spend Alerts and KPIs (matches frontend data contracts)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JevDecisionScoresSchema(BaseModel):
    isSaasScore: float = Field(
        default=0.0, description="Calibrated probability p(is_unmanaged_saas)"
    )
    warrantsReviewScore: float = Field(
        default=0.0, description="Calibrated probability p(warrants_review)"
    )


class SoftwareOverlapSchema(BaseModel):
    unmanagedTool: str
    unmanagedCategory: str
    approvedAlternative: str
    approvedContractId: str
    approvedVendorName: str
    cosineSimilarity: float
    sharedCapabilities: list[str] = Field(default_factory=list)
    recommendedAction: str
    employeeEmail: str
    employeeName: str
    annualizedSavingsOpportunity: float = 0.0


class MaverickAlertItemSchema(BaseModel):
    id: str
    transactionId: str
    merchantName: str
    amount: float
    currency: str
    cadenceDays: int
    cadenceDescription: str
    cardLast4: str
    employeeId: str
    employeeName: str
    employeeEmail: str
    department: str
    transactionDate: str
    jevScores: JevDecisionScoresSchema
    status: Literal["open", "notified", "migrated", "dismissed"]
    overlap: SoftwareOverlapSchema | None = None


class MaverickSpendKPIsSchema(BaseModel):
    totalUnmanagedSpend: float = 0.0
    activeAlertsCount: int = 0
    potentialAnnualSavings: float = 0.0
    avgOverlapSimilarity: float = 0.0


class MaverickSpendFeedResponse(BaseModel):
    alerts: list[MaverickAlertItemSchema]
    kpis: MaverickSpendKPIsSchema


class UpdateAlertStatusRequest(BaseModel):
    status: Literal["open", "notified", "migrated", "dismissed"]


class ContractProductReindexRequest(BaseModel):
    """Request a tenant-scoped refresh of approved contract-product vectors."""

    tenant_id: str = Field(min_length=1)


class ContractProductReindexStatusSchema(BaseModel):
    """Celery status and summary for an approved-product index refresh."""

    task_id: str
    status: str
    summary: dict[str, int] | None = None
    error: str | None = None


class TriggerDetectionRequest(BaseModel):
    """Trigger payload for batch or GCS-backed maverick detection."""

    tenant_id: str
    lookback_days: int = 90
    source: Literal["gcs", "db"] = Field(
        default="db",
        description=(
            "``gcs`` scans the Ramp bronze lake (promote + identify). "
            "``db`` scans only transactions already in card_transactions (default)."
        ),
    )
    gcs_key: str | None = Field(
        default=None,
        description=(
            "Exact bronze-lake object to scan, e.g. "
            "raw/ramp_card_transactions/sync=<id>/cursor-final.jsonl.gz"
        ),
    )
    sync_id: str | None = Field(
        default=None,
        description="Ingestion sync ticket; scans every object under that sync partition.",
    )
    prefix: str | None = Field(
        default=None,
        description="Alternative GCS prefix for ad-hoc backfills.",
    )
    run_inline: bool = Field(
        default=True,
        description=(
            "Run Jev/catalog identification inside the scan task so alerts are persisted "
            "before it returns. False dispatches one analytics task per transaction."
        ),
    )
