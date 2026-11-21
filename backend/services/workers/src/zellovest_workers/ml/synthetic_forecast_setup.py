"""Prepare isolated synthetic data and enqueue one development forecast."""

from __future__ import annotations

import argparse
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from zellovest_shared.db.core import Employee, Vendor
from zellovest_shared.db.intelligence import LicenseAssignment
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.logging_conf import get_logger

from zellovest_workers.ml.feature_pipeline import FeaturePipelineConfig, run_feature_pipeline
from zellovest_workers.ml.synthetic_ingest import prepare_feeds, upload_feeds
from zellovest_workers.tasks.seat_forecasting import run_seat_forecast

logger = get_logger(__name__)


def seed_database(directory: Path, tenant_id: str, horizon: int) -> None:
    """Insert stable synthetic records into an explicitly selected development database."""
    feeds = prepare_feeds(directory, tenant_id, inference_horizon=horizon)
    session = get_session_factory()()
    try:
        users = feeds["hris_employees"].set_index("user_id")
        assignments = feeds["license_assignments"]
        for app, vendor_id in assignments[["app_name", "vendor_id"]].drop_duplicates().itertuples(
            index=False, name=None
        ):
            existing = session.get(Vendor, uuid.UUID(vendor_id))
            if existing is None:
                session.add(Vendor(id=uuid.UUID(vendor_id), tenant_id=tenant_id, name=app))
            elif existing.tenant_id != tenant_id or existing.name != app:
                raise ValueError("Synthetic vendor ID conflicts with an existing record")
        for user_id in assignments["user_id"].unique():
            user = users.loc[user_id]
            existing = session.get(Employee, uuid.UUID(user_id))
            if existing is None:
                session.add(Employee(
                    id=uuid.UUID(user_id), tenant_id=tenant_id, email=user["email"],
                    department_raw=user["department"],
                ))
            elif existing.tenant_id != tenant_id or existing.email != user["email"]:
                raise ValueError("Synthetic employee ID conflicts with an existing record")
        session.flush()
        for row in assignments.itertuples(index=False):
            existing_assignment = session.get(LicenseAssignment, uuid.UUID(row.assignment_id))
            if existing_assignment is not None:
                if (existing_assignment.tenant_id != tenant_id
                    or existing_assignment.employee_id != uuid.UUID(row.user_id)
                    or existing_assignment.vendor_id != uuid.UUID(row.vendor_id)):
                    raise ValueError("Synthetic assignment ID conflicts with an existing record")
                continue
            session.add(LicenseAssignment(
                id=uuid.UUID(row.assignment_id), tenant_id=tenant_id,
                employee_id=uuid.UUID(row.user_id), vendor_id=uuid.UUID(row.vendor_id),
                app_id_text=row.app_id, seats=1, status="active",
                assigned_at=datetime.fromisoformat(row.assigned_at).replace(tzinfo=UTC),
            ))
        session.commit()
        logger.info("synthetic_database_seeded", tenant_id=tenant_id, assignments=len(assignments))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    """Seed a disposable database, refresh synthetic features, and enqueue inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--horizon", type=int, choices=(30, 60, 90, 120), default=120)
    parser.add_argument("--development-database", action="store_true", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"tenant_\d{3}", args.tenant_id):
        parser.error("tenant ID must identify a synthetic tenant, e.g. tenant_002")
    config = FeaturePipelineConfig.from_environment(tenant_id=args.tenant_id)
    if (config.bronze_dataset, config.silver_dataset, config.gold_dataset) != (
        "zellovest_synthetic_bronze", "zellovest_synthetic_silver", "zellovest_synthetic_gold"
    ):
        raise ValueError("Configure the three isolated zellovest_synthetic BigQuery datasets")
    if not os.getenv("SEAT_RAW_PREFIX", "").startswith("synthetic/"):
        raise ValueError("SEAT_RAW_PREFIX must begin with synthetic/")
    seed_database(args.directory, args.tenant_id, args.horizon)
    upload_feeds(
        args.directory, args.tenant_id, config.gcs_raw_bucket, config.raw_prefix,
        inference_horizon=args.horizon,
    )
    run_feature_pipeline(config)
    task = run_seat_forecast.delay(args.tenant_id, args.horizon)
    logger.info("synthetic_forecast_enqueued", task_id=task.id, tenant_id=args.tenant_id)


if __name__ == "__main__":
    main()
