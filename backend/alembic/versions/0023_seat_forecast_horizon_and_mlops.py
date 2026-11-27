"""Add horizon uniqueness to seat_forecasts and create MLOps tables.

Revision ID: 0023_seat_forecast_horizon_and_mlops
Revises: 0022_savings_ledger_idempotency
Create Date: 2026-11-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023_seat_forecast_horizon_and_mlops"
down_revision = "0022_savings_ledger_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add horizon/growth columns to seat_forecasts and create MLOps telemetry tables."""
    op.add_column(
        "seat_forecasts",
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="90"),
    )
    op.add_column(
        "seat_forecasts",
        sa.Column("renewal_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "seat_forecasts",
        sa.Column("headcount_growth_seats", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE seat_forecasts
        SET horizon_days = CAST(retention_curve->>'horizon_days' AS INTEGER)
        WHERE retention_curve IS NOT NULL
          AND retention_curve->>'horizon_days' ~ '^[0-9]+$'
        """
    )
    op.drop_constraint("uq_forecast_tenant_vendor_dept_date", "seat_forecasts", type_="unique")
    op.create_unique_constraint(
        "uq_forecast_tenant_vendor_dept_date_horizon",
        "seat_forecasts",
        ["tenant_id", "vendor_id", "department", "forecast_date", "horizon_days"],
    )

    op.create_table(
        "ml_model_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        sa.Column("segment_type", sa.String(32), nullable=False, server_default="overall"),
        sa.Column("segment_value", sa.String(128), nullable=False, server_default="all"),
        sa.Column("evaluated_seats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cohort_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("roc_auc", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("ece", sa.Float(), nullable=True),
        sa.Column("f1", sa.Float(), nullable=True),
        sa.Column("realized_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("naive_baseline_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("oracle_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("realized_savings_vs_naive", sa.Numeric(14, 2), nullable=True),
        sa.Column("financial_regret", sa.Numeric(14, 2), nullable=True),
        sa.Column("trueup_incident_rate", sa.Float(), nullable=True),
        sa.Column("evaluation_window_start", sa.Date(), nullable=True),
        sa.Column("evaluation_window_end", sa.Date(), nullable=True),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ml_model_metrics_tenant_id", "ml_model_metrics", ["tenant_id"])
    op.create_index(
        "ix_ml_metrics_tenant_time", "ml_model_metrics", ["tenant_id", "evaluated_at"]
    )
    op.create_index(
        "ix_ml_metrics_version_seg",
        "ml_model_metrics",
        ["tenant_id", "model_version", "segment_type"],
    )

    op.create_table(
        "ml_drift_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("baseline_version", sa.String(64), nullable=True),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_psi", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("score_psi", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("max_sentinel_delta", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="healthy"),
        sa.Column("drifted_features", sa.JSON(), nullable=True),
        sa.Column("feature_metrics", sa.JSON(), nullable=True),
        sa.Column("retrain_recommended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("retrain_triggered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("trigger_reason", sa.Text(), nullable=True),
        sa.Column("training_job_uri", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_ml_drift_reports_tenant_id", "ml_drift_reports", ["tenant_id"])
    op.create_index("ix_ml_drift_tenant_time", "ml_drift_reports", ["tenant_id", "created_at"])
    op.create_index("ix_ml_drift_tenant_sev", "ml_drift_reports", ["tenant_id", "severity"])


def downgrade() -> None:
    """Drop MLOps tables and revert seat_forecasts horizon changes."""
    op.drop_index("ix_ml_drift_tenant_sev", table_name="ml_drift_reports")
    op.drop_index("ix_ml_drift_tenant_time", table_name="ml_drift_reports")
    op.drop_index("ix_ml_drift_reports_tenant_id", table_name="ml_drift_reports")
    op.drop_table("ml_drift_reports")

    op.drop_index("ix_ml_metrics_version_seg", table_name="ml_model_metrics")
    op.drop_index("ix_ml_metrics_tenant_time", table_name="ml_model_metrics")
    op.drop_index("ix_ml_model_metrics_tenant_id", table_name="ml_model_metrics")
    op.drop_table("ml_model_metrics")

    op.drop_constraint(
        "uq_forecast_tenant_vendor_dept_date_horizon", "seat_forecasts", type_="unique"
    )
    op.create_unique_constraint(
        "uq_forecast_tenant_vendor_dept_date",
        "seat_forecasts",
        ["tenant_id", "vendor_id", "department", "forecast_date"],
    )
    op.drop_column("seat_forecasts", "headcount_growth_seats")
    op.drop_column("seat_forecasts", "renewal_date")
    op.drop_column("seat_forecasts", "horizon_days")
