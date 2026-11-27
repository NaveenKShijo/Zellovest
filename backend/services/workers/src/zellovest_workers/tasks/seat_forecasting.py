"""Celery batch inference and PostgreSQL sync for license seat forecasts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session
from zellovest_shared.config import Settings, get_settings
from zellovest_shared.db.core import Department, Employee
from zellovest_shared.db.intelligence import LicenseAssignment, SeatForecast
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_writer import make_storage_client

from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app
from zellovest_workers.ml.evaluation import build_prediction_log_rows, log_seat_predictions
from zellovest_workers.ml.optimizer import optimize_commitment
from zellovest_workers.ml.train_vertex import (
    FEATURE_COLUMNS,
    CalibrationParameters,
    apply_calibration,
)

logger = get_logger(__name__)
ALLOWED_HORIZONS = frozenset({120, 90, 60, 30})
_BQ_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")


class RetentionPredictor(Protocol):
    """Minimal batch predictor contract used by the forecast service."""

    model_version: str

    def predict(self, feature_rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
        """Return one calibrated retention probability per feature row."""


@dataclass(frozen=True, slots=True)
class ActiveSeat:
    """Canonical PostgreSQL seat assignment used to scope inference."""

    employee_id: str
    vendor_id: str
    department_id: uuid.UUID | None
    department: str
    seats: int


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    """Database-ready output for one vendor, department, and horizon cohort."""

    tenant_id: str
    vendor_id: uuid.UUID
    department_id: uuid.UUID | None
    department: str
    forecast_date: date
    current_seats: int
    recommended_seats: int
    retention_curve: dict[str, Any]
    confidence: float
    shelfware_amount: float
    trueup_risk_amount: float
    savings_estimate: float
    model_version: str
    horizon_days: int = 90
    renewal_date: date | None = None
    headcount_growth_seats: int = 0

    def to_orm(self) -> SeatForecast:
        """Create the canonical immutable ORM record."""
        return SeatForecast(
            tenant_id=self.tenant_id,
            vendor_id=self.vendor_id,
            department_id=self.department_id,
            department=self.department,
            forecast_date=self.forecast_date,
            horizon_days=self.horizon_days,
            renewal_date=self.renewal_date,
            current_seats=self.current_seats,
            recommended_seats=self.recommended_seats,
            headcount_growth_seats=self.headcount_growth_seats,
            retention_curve=self.retention_curve,
            confidence=self.confidence,
            shelfware_amount=self.shelfware_amount,
            trueup_risk_amount=self.trueup_risk_amount,
            savings_estimate=self.savings_estimate,
            model_version=self.model_version,
        )


class LightGBMPredictor:
    """Locally cached LightGBM booster with a Platt calibration sidecar."""

    def __init__(
        self,
        model_path: Path,
        calibration: CalibrationParameters,
        model_version: str,
        feature_columns: Sequence[str] | None = None,
    ) -> None:
        """Load a booster from disk and retain its calibration and schema metadata."""
        import lightgbm as lgb

        self._booster = lgb.Booster(model_file=str(model_path))
        self._calibration = calibration
        self.model_version = model_version
        expected_count = int(self._booster.num_feature())
        resolved_columns = list(feature_columns or FEATURE_COLUMNS)
        if len(resolved_columns) != expected_count:
            resolved_columns = list(FEATURE_COLUMNS[:expected_count])
        self.feature_columns = tuple(resolved_columns)

    def predict_with_raw(
        self, feature_rows: Sequence[Mapping[str, Any]]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(raw_probabilities, calibrated_probabilities)`` in stable order."""
        matrix: np.ndarray[Any, np.dtype[np.float64]] = np.asarray(
            [
                [float(row.get(column, 0.0) or 0.0) for column in self.feature_columns]
                for row in feature_rows
            ],
            dtype=np.float64,
        )
        raw = np.asarray(self._booster.predict(matrix), dtype=np.float64)
        return raw, apply_calibration(raw, self._calibration)

    def predict(self, feature_rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
        """Predict calibrated retention probabilities in stable feature order."""
        _, calibrated = self.predict_with_raw(feature_rows)
        return calibrated


def _sha256(path: Path) -> str:
    """Calculate a local model artifact's SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    """Write cache metadata atomically so concurrent workers never see partial data."""
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.part")
    temporary.write_bytes(content)
    temporary.replace(path)


def load_latest_model(settings: Settings | None = None) -> LightGBMPredictor:
    """Hot-reload ``model.booster`` from GCS with generation and SHA validation."""
    resolved = settings or get_settings()
    synthetic = resolved.seat_synthetic_mode
    configured_bucket = resolved.gcs_ml_synth if synthetic else resolved.gcs_ml_bucket
    bucket_name = configured_bucket.removeprefix("gs://").rstrip("/")
    if not bucket_name:
        raise ValueError("GCS_ML_BUCKET is required for batch inference")

    cache_directory = Path(resolved.seat_model_cache_dir)
    cache_directory.mkdir(parents=True, exist_ok=True)
    model_path = cache_directory / "model.booster"
    manifest_path = cache_directory / "model.manifest.json"
    client = make_storage_client(resolved.google_cloud_project or None)
    bucket = client.bucket(bucket_name)
    model_blob = bucket.blob("models/latest/model.booster")
    model_blob.reload()
    metadata = model_blob.metadata or {}
    expected_sha = metadata.get("sha256", "")
    model_version = metadata.get("model_version", "")
    generation = str(model_blob.generation or "")
    if not expected_sha:
        raise RuntimeError("latest model is missing required sha256 GCS metadata")
    if not model_version:
        raise RuntimeError("latest model is missing required model_version GCS metadata")

    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
    cache_valid = (
        model_path.exists()
        and manifest.get("generation") == generation
        and manifest.get("sha256") == expected_sha
        and _sha256(model_path) == expected_sha
    )
    if not cache_valid:
        temporary = model_path.with_name(f"model.{uuid.uuid4().hex}.part")
        try:
            model_blob.download_to_filename(str(temporary))
            actual_sha = _sha256(temporary)
            if actual_sha != expected_sha:
                raise RuntimeError(
                    f"model SHA mismatch: expected {expected_sha}, received {actual_sha}"
                )
            temporary.replace(model_path)
        finally:
            temporary.unlink(missing_ok=True)

    calibration_blob = bucket.blob("models/latest/calibration.json")
    calibration_data = json.loads(calibration_blob.download_as_bytes().decode("utf-8"))
    calibration = CalibrationParameters(**calibration_data)

    feature_columns: list[str] | None = None
    schema_blob = bucket.blob("models/latest/feature_schema.json")
    try:
        if schema_blob.exists():
            schema_data = json.loads(schema_blob.download_as_bytes().decode("utf-8"))
            cols = schema_data.get("feature_columns")
            if isinstance(cols, list) and cols:
                feature_columns = [str(col) for col in cols]
    except Exception:
        feature_columns = None

    _atomic_write(
        manifest_path,
        json.dumps(
            {
                "generation": generation,
                "sha256": expected_sha,
                "model_version": model_version,
            },
            sort_keys=True,
        ).encode("utf-8"),
    )
    logger.info(
        "seat_model_cache_ready",
        model_version=model_version,
        generation=generation,
        cache_hit=cache_valid,
    )
    return LightGBMPredictor(
        model_path,
        calibration,
        model_version,
        feature_columns=feature_columns,
    )


def _feature_table(settings: Settings) -> str:
    """Build and validate the configured fully-qualified Gold table identifier."""
    table = (
        f"{settings.google_cloud_project}.{settings.bigquery_gold_dataset}."
        f"{settings.bigquery_seat_features_table}"
    )
    if not _BQ_IDENTIFIER.fullmatch(table):
        raise ValueError(f"invalid BigQuery feature table identifier: {table!r}")
    return table


def fetch_bigquery_features(
    tenant_id: str,
    horizon_days: int,
    *,
    vendor_id: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Fetch the latest point-in-time feature row per active employee/vendor."""
    from google.cloud import bigquery

    resolved = settings or get_settings()
    credentials = None
    if resolved.google_application_credentials:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            resolved.google_application_credentials
        )
    client = bigquery.Client(
        project=resolved.google_cloud_project,
        credentials=credentials,
    )
    vendor_filter = "AND CAST(vendor_id AS STRING) = @vendor_id" if vendor_id else ""
    query = f"""
        SELECT *
        FROM `{_feature_table(resolved)}`
        WHERE tenant_id = @tenant_id
          AND renewal_horizon_days = @horizon_days
          AND renewal_date >= CURRENT_DATE()
          AND feature_as_of_date <= CURRENT_DATE()
          {vendor_filter}
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY employee_id, vendor_id
          ORDER BY renewal_date, feature_as_of_date DESC
        ) = 1
    """
    parameters: list[Any] = [
        bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id),
        bigquery.ScalarQueryParameter("horizon_days", "INT64", horizon_days),
    ]
    if vendor_id:
        parameters.append(bigquery.ScalarQueryParameter("vendor_id", "STRING", vendor_id))
    job_config = bigquery.QueryJobConfig(query_parameters=parameters)
    rows = [dict(row.items()) for row in client.query(query, job_config=job_config).result()]
    logger.info(
        "seat_features_loaded",
        tenant_id=tenant_id,
        horizon_days=horizon_days,
        rows=len(rows),
    )
    return rows


def load_active_seats(
    session: Session,
    tenant_id: str,
    *,
    vendor_id: str | None = None,
) -> list[ActiveSeat]:
    """Load tenant-scoped active assignments and canonical HR departments."""
    statement = (
        select(
            LicenseAssignment.employee_id,
            LicenseAssignment.vendor_id,
            LicenseAssignment.seats,
            Employee.department_id,
            Department.name.label("department_name"),
            Employee.department_raw,
        )
        .join(
            Employee,
            (Employee.id == LicenseAssignment.employee_id)
            & (Employee.tenant_id == LicenseAssignment.tenant_id),
        )
        .outerjoin(
            Department,
            (Department.id == Employee.department_id)
            & (Department.tenant_id == LicenseAssignment.tenant_id),
        )
        .where(
            LicenseAssignment.tenant_id == tenant_id,
            LicenseAssignment.status == "active",
            LicenseAssignment.unassigned_at.is_(None),
        )
    )
    if vendor_id:
        try:
            statement = statement.where(LicenseAssignment.vendor_id == uuid.UUID(vendor_id))
        except ValueError as exc:
            raise ValueError("vendor_id must be a UUID") from exc
    seats = [
        ActiveSeat(
            employee_id=str(row.employee_id),
            vendor_id=str(row.vendor_id),
            department_id=row.department_id,
            department=row.department_name or row.department_raw or "Unassigned",
            seats=max(int(row.seats), 1),
        )
        for row in session.execute(statement)
    ]
    logger.info("active_seats_loaded", tenant_id=tenant_id, rows=len(seats))
    return seats


def _parse_renewal_date(value: Any) -> date | None:
    """Coerce a date, datetime, or ISO date string into ``datetime.date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _score_and_build(
    *,
    tenant_id: str,
    horizon_days: int,
    active_seats: Sequence[ActiveSeat],
    feature_rows: Sequence[Mapping[str, Any]],
    predictor: RetentionPredictor,
    annual_seat_cost_override: float | None = None,
    penalty_rate_override: float | None = None,
    default_penalty_rate: float = 0.25,
    forecast_on: date | None = None,
    growth_attach_rate: float = 1.0,
) -> tuple[list[ForecastRecord], list[dict[str, Any]]]:
    """Score active seats, optimize cohorts, and construct prediction logs."""
    if horizon_days not in ALLOWED_HORIZONS:
        raise ValueError(f"horizon_days must be one of {sorted(ALLOWED_HORIZONS)}")
    if not active_seats:
        return [], []
    feature_index = {
        (str(row.get("employee_id")), str(row.get("vendor_id"))): row for row in feature_rows
    }
    renewal_vendor_ids = {str(row.get("vendor_id")) for row in feature_rows}
    selected_seats = [seat for seat in active_seats if seat.vendor_id in renewal_vendor_ids]
    if not selected_seats:
        raise ValueError("no active PostgreSQL seats match the BigQuery renewal features")
    missing = [
        (seat.employee_id, seat.vendor_id)
        for seat in selected_seats
        if (seat.employee_id, seat.vendor_id) not in feature_index
    ]
    if missing:
        raise ValueError(
            f"BigQuery feature coverage is incomplete for {len(missing)} active seat assignments"
        )

    scored_features = [feature_index[(seat.employee_id, seat.vendor_id)] for seat in selected_seats]
    if hasattr(predictor, "predict_with_raw"):
        raw_probabilities, probabilities = predictor.predict_with_raw(scored_features)
    else:
        probabilities = predictor.predict(scored_features)
        raw_probabilities = probabilities

    if len(probabilities) != len(selected_seats):
        raise RuntimeError("predictor returned a different number of probabilities than seats")
    if np.any(~np.isfinite(probabilities)) or np.any((probabilities < 0) | (probabilities > 1)):
        raise RuntimeError("predictor returned invalid retention probabilities")

    grouped: dict[tuple[str, uuid.UUID | None, str], list[tuple[float, Mapping[str, Any]]]] = {}
    for seat, probability, features in zip(
        selected_seats, probabilities, scored_features, strict=True
    ):
        key = (seat.vendor_id, seat.department_id, seat.department)
        expanded = grouped.setdefault(key, [])
        expanded.extend((float(probability), features) for _ in range(seat.seats))

    resolved_forecast_date = forecast_on or datetime.now(UTC).date()
    records: list[ForecastRecord] = []
    cohort_recommendations: dict[tuple[str, str], tuple[int, int]] = {}
    for (vendor_id, department_id, department), values in grouped.items():
        group_probabilities = [value[0] for value in values]
        sample_features = values[0][1]
        annual_cost_value = (
            annual_seat_cost_override
            if annual_seat_cost_override is not None
            else sample_features.get("annual_seat_cost")
        )
        feature_penalty = sample_features.get("trueup_penalty_rate")
        penalty_value = (
            penalty_rate_override
            if penalty_rate_override is not None
            else feature_penalty
            if feature_penalty is not None
            else default_penalty_rate
        )
        if annual_cost_value is None:
            raise ValueError(f"annual seat cost is missing for vendor {vendor_id}")
        if penalty_value is None:
            raise ValueError(f"true-up penalty rate is missing for vendor {vendor_id}")

        dept_growth_rate = float(sample_features.get("department_growth_rate") or 0.0)
        optimization = optimize_commitment(
            group_probabilities,
            float(annual_cost_value),
            float(penalty_value),
            departments=[department] * len(group_probabilities),
            horizon_days=horizon_days,
            expected_growth_rate=dept_growth_rate,
            growth_attach_rate=growth_attach_rate,
        )
        retention_curve = {
            "horizon_days": horizon_days,
            "expected_demand": optimization.expected_demand,
            "expected_retained_seats": optimization.expected_retained_seats,
            "expected_growth_seats": optimization.expected_growth_seats,
            "critical_fractile": optimization.critical_fractile,
            "expected_shelfware_seats": optimization.expected_shelfware_seats,
            "expected_trueup_seats": optimization.expected_trueup_seats,
            "departments": [curve.to_dict() for curve in optimization.departmental_curves],
        }
        try:
            vendor_uuid = uuid.UUID(vendor_id)
        except ValueError as exc:
            raise ValueError(f"Gold feature vendor_id is not a UUID: {vendor_id!r}") from exc

        cohort_recommendations[(vendor_id, department)] = (
            optimization.recommended_seats,
            optimization.current_seats,
        )
        records.append(
            ForecastRecord(
                tenant_id=tenant_id,
                vendor_id=vendor_uuid,
                department_id=department_id,
                department=department,
                forecast_date=resolved_forecast_date,
                horizon_days=horizon_days,
                renewal_date=_parse_renewal_date(sample_features.get("renewal_date")),
                current_seats=optimization.current_seats,
                recommended_seats=optimization.recommended_seats,
                headcount_growth_seats=round(optimization.expected_growth_seats),
                retention_curve=retention_curve,
                confidence=optimization.commitment_confidence,
                shelfware_amount=optimization.shelfware_amount,
                trueup_risk_amount=optimization.trueup_risk_amount,
                savings_estimate=optimization.savings_estimate,
                model_version=predictor.model_version,
            )
        )

    prediction_logs = build_prediction_log_rows(
        tenant_id=tenant_id,
        horizon_days=horizon_days,
        forecast_date=resolved_forecast_date,
        model_version=predictor.model_version,
        feature_rows=scored_features,
        raw_probabilities=[float(p) for p in raw_probabilities],
        calibrated_probabilities=[float(p) for p in probabilities],
        cohort_recommendations=cohort_recommendations,
    )
    return records, prediction_logs


def build_forecast_records(
    *,
    tenant_id: str,
    horizon_days: int,
    active_seats: Sequence[ActiveSeat],
    feature_rows: Sequence[Mapping[str, Any]],
    predictor: RetentionPredictor,
    annual_seat_cost_override: float | None = None,
    penalty_rate_override: float | None = None,
    default_penalty_rate: float = 0.25,
    forecast_on: date | None = None,
) -> list[ForecastRecord]:
    """Join features to seats, score individuals, and optimize each department."""
    records, _ = _score_and_build(
        tenant_id=tenant_id,
        horizon_days=horizon_days,
        active_seats=active_seats,
        feature_rows=feature_rows,
        predictor=predictor,
        annual_seat_cost_override=annual_seat_cost_override,
        penalty_rate_override=penalty_rate_override,
        default_penalty_rate=default_penalty_rate,
        forecast_on=forecast_on,
    )
    return records


def persist_forecasts(session: Session, records: Sequence[ForecastRecord]) -> list[uuid.UUID]:
    """Insert forecasts idempotently using tenant, vendor, department, date, and horizon."""
    inserted: list[uuid.UUID] = []
    for record in records:
        existing_id = session.scalar(
            select(SeatForecast.id).where(
                SeatForecast.tenant_id == record.tenant_id,
                SeatForecast.vendor_id == record.vendor_id,
                SeatForecast.department == record.department,
                SeatForecast.forecast_date == record.forecast_date,
                SeatForecast.horizon_days == record.horizon_days,
            )
        )
        if existing_id is not None:
            inserted.append(existing_id)
            continue
        row = record.to_orm()
        session.add(row)
        session.flush()
        inserted.append(row.id)
    session.commit()
    return inserted


@celery_app.task(
    name="zellovest.workers.tasks.forecasting.run_seat_forecast",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def run_seat_forecast(
    tenant_id: str,
    horizon_days: int,
    vendor_id: str | None = None,
    annual_seat_cost: float | None = None,
    trueup_penalty_rate: float | None = None,
) -> dict[str, Any]:
    """Score active seats for a tenant/horizon, sync forecasts, and log predictions."""
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if horizon_days not in ALLOWED_HORIZONS:
        raise ValueError(f"horizon_days must be one of {sorted(ALLOWED_HORIZONS)}")
    logger.info(
        "seat_forecast_started",
        tenant_id=tenant_id,
        horizon_days=horizon_days,
        vendor_id=vendor_id,
    )
    settings = get_settings()
    feature_rows = fetch_bigquery_features(
        tenant_id,
        horizon_days,
        vendor_id=vendor_id,
        settings=settings,
    )
    if not feature_rows:
        logger.info(
            "seat_forecast_no_renewals",
            tenant_id=tenant_id,
            horizon_days=horizon_days,
        )
        return {
            "tenant_id": tenant_id,
            "horizon_days": horizon_days,
            "status": "no_renewals",
            "forecasts_written": 0,
        }

    session = get_session_factory()()
    try:
        active_seats = load_active_seats(session, tenant_id, vendor_id=vendor_id)
        predictor = load_latest_model(settings)
        records, prediction_logs = _score_and_build(
            tenant_id=tenant_id,
            horizon_days=horizon_days,
            active_seats=active_seats,
            feature_rows=feature_rows,
            predictor=predictor,
            annual_seat_cost_override=annual_seat_cost,
            penalty_rate_override=(
                trueup_penalty_rate if trueup_penalty_rate is not None else None
            ),
            default_penalty_rate=settings.seat_default_trueup_penalty_rate,
        )
        forecast_ids = persist_forecasts(session, records)
    except Exception:
        session.rollback()
        logger.exception(
            "seat_forecast_failed",
            tenant_id=tenant_id,
            horizon_days=horizon_days,
            vendor_id=vendor_id,
        )
        raise
    finally:
        session.close()

    logged_predictions = 0
    try:
        logged_predictions = log_seat_predictions(prediction_logs, settings=settings)
    except Exception as exc:
        logger.warning(
            "seat_prediction_log_failed",
            tenant_id=tenant_id,
            horizon_days=horizon_days,
            error=str(exc),
        )

    result = {
        "tenant_id": tenant_id,
        "horizon_days": horizon_days,
        "status": "completed",
        "forecasts_written": len(forecast_ids),
        "predictions_logged": logged_predictions,
        "forecast_ids": [str(value) for value in forecast_ids],
        "model_version": predictor.model_version,
    }
    logger.info("seat_forecast_completed", **result)
    return result


@celery_app.task(
    name="zellovest.workers.tasks.forecasting.dispatch_seat_forecasts",
    queue=QUEUE_ANALYTICS,
    max_retries=3,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def dispatch_seat_forecasts() -> dict[str, Any]:
    """Enqueue a batch forecast for each supported renewal horizon every 15 days."""
    tenant_id = os.getenv("TENANT_ID", "").strip()
    if not tenant_id:
        raise ValueError("TENANT_ID is required for scheduled seat forecasting")

    task_ids = [
        run_seat_forecast.delay(tenant_id, horizon_days).id
        for horizon_days in sorted(ALLOWED_HORIZONS, reverse=True)
    ]
    logger.info(
        "seat_forecast_dispatch_completed",
        tenant_id=tenant_id,
        horizon_days=sorted(ALLOWED_HORIZONS, reverse=True),
        task_ids=task_ids,
    )
    return {"tenant_id": tenant_id, "task_ids": task_ids}
