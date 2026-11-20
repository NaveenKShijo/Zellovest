"""Integration coverage for seat feature mocks, optimization, and DB sync."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from zellovest_shared.config import MLRuntimeSettings, Settings
from zellovest_shared.db.intelligence import SeatForecast
from zellovest_workers.ml.feature_pipeline import (
    SQL_DIRECTORY,
    SQL_FILES,
    FeaturePipelineConfig,
    render_sql,
)
from zellovest_workers.ml.optimizer import optimize_commitment, poisson_binomial_pmf
from zellovest_workers.ml.train_vertex import (
    FEATURE_COLUMNS,
    ModelRejectedError,
    TrainingMetrics,
    train_challenger,
    validate_challenger,
)
from zellovest_workers.tasks import seat_forecasting
from zellovest_workers.tasks.seat_forecasting import ActiveSeat

TELEMETRY_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "telemetry"


def test_feature_sql_templates_render_without_unresolved_placeholders() -> None:
    """Ensure documented SQL comments do not look like unresolved variables."""
    config = FeaturePipelineConfig(
        project_id="test-project",
        tenant_id="tenant_test",
        gcs_raw_bucket="test-raw-bucket",
        bronze_dataset="bronze",
        silver_dataset="silver",
        gold_dataset="gold",
        bq_location="US",
        default_trueup_penalty_rate=0.25,
    )

    for filename in SQL_FILES:
        rendered = render_sql(
            (SQL_DIRECTORY / filename).read_text(encoding="utf-8"),
            config.template_values(),
        )
        assert "{{" not in rendered
        assert "}}" not in rendered
        if filename == "01_bronze_okta_logs.sql":
            assert "autodetect =" not in rendered.lower()
            for uri in re.findall(r"gs://[^']+", rendered):
                assert uri.count("*") <= 1


class _TelemetryPredictor:
    """Deterministic stand-in for a calibrated LightGBM booster."""

    model_version = "v_test_telemetry"

    def predict(self, feature_rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
        """Map synthetic 30-day activity into bounded retention probabilities."""
        return np.asarray(
            [min(0.98, 0.10 + (float(row["logins_30d"]) * 0.04)) for row in feature_rows]
        )


def _synthetic_feature_mock() -> tuple[list[ActiveSeat], list[dict[str, Any]]]:
    """Build a mocked BigQuery response from repository telemetry Parquet files."""
    assignments = pd.read_parquet(TELEMETRY_DIRECTORY / "fact_seat_assignments.parquet")
    events = pd.read_parquet(TELEMETRY_DIRECTORY / "fact_sso_events.parquet")
    users = pd.read_parquet(TELEMETRY_DIRECTORY / "dim_users.parquet")
    active = assignments[assignments["status"].str.upper() == "ACTIVE"].copy()
    candidates = active.merge(
        events[["tenant_id", "user_id", "app_id", "occurred_at"]],
        on=["tenant_id", "user_id", "app_id"],
        how="inner",
    )
    if candidates.empty:
        pytest.fail("synthetic assignment and SSO telemetry have no joinable rows")
    tenant_id, app_id = candidates[["tenant_id", "app_id"]].iloc[0]
    cohort = active[(active["tenant_id"] == tenant_id) & (active["app_id"] == app_id)].head(20)
    cohort = cohort.merge(
        users[["tenant_id", "user_id", "department"]],
        on=["tenant_id", "user_id"],
        how="left",
        suffixes=("", "_hris"),
    )
    cohort_events = events[(events["tenant_id"] == tenant_id) & (events["app_id"] == app_id)]
    as_of = pd.Timestamp(cohort_events["occurred_at"].max()).normalize()
    vendor_id = uuid.uuid4()
    department_ids: dict[str, uuid.UUID] = {}
    seats: list[ActiveSeat] = []
    features: list[dict[str, Any]] = []
    for assignment in cohort.to_dict("records"):
        department = str(
            assignment.get("department_hris") or assignment.get("department") or "Unassigned"
        )
        department_id = department_ids.setdefault(department, uuid.uuid4())
        user_events = cohort_events[cohort_events["user_id"] == assignment["user_id"]]
        ages = (as_of - pd.to_datetime(user_events["occurred_at"]).dt.normalize()).dt.days
        login_30 = int((ages <= 30).sum())
        login_60 = int((ages <= 60).sum())
        login_90 = int((ages <= 90).sum())
        days_since = int(ages.min()) if not ages.empty else 9999
        department_lower = department.casefold()
        features.append(
            {
                "tenant_id": tenant_id,
                "employee_id": assignment["user_id"],
                "vendor_id": str(vendor_id),
                "logins_30d": login_30,
                "logins_60d": login_60,
                "logins_90d": login_90,
                "days_since_last_login": days_since,
                "login_momentum": (login_30 / 30.0) / ((login_90 / 90.0) + 1e-4),
                "tenure_days": 365,
                "days_since_assigned": 180,
                "department_churn_rate": 0.08,
                "department_engineering": int("engineering" in department_lower),
                "department_sales": int("sales" in department_lower),
                "department_marketing": int("marketing" in department_lower),
                "department_finance": int("finance" in department_lower),
                "department_hr": int("hr" in department_lower),
                "department_operations": int("operations" in department_lower),
                "department_other": 0,
                "annual_seat_cost": 1200.0,
                "trueup_penalty_rate": 0.25,
            }
        )
        seats.append(
            ActiveSeat(
                employee_id=str(assignment["user_id"]),
                vendor_id=str(vendor_id),
                department_id=department_id,
                department=department,
                seats=1,
            )
        )
    return seats, features


def test_poisson_binomial_distribution_is_normalized() -> None:
    """Exact demand convolution returns all N+1 outcomes and unit mass."""
    pmf = poisson_binomial_pmf([0.2, 0.5, 0.9])
    assert len(pmf) == 4
    assert float(pmf.sum()) == pytest.approx(1.0)


def test_high_penalty_protects_with_at_least_as_many_committed_seats() -> None:
    """A larger true-up penalty raises the critical fractile and commitment."""
    probabilities = [0.22, 0.38, 0.51, 0.64, 0.73, 0.82, 0.91]
    low_penalty = optimize_commitment(probabilities, 1000.0, 0.0)
    high_penalty = optimize_commitment(probabilities, 1000.0, 2.0)
    assert high_penalty.critical_fractile > low_penalty.critical_fractile
    assert high_penalty.recommended_seats >= low_penalty.recommended_seats
    assert high_penalty.commitment_confidence >= low_penalty.commitment_confidence


def test_champion_gate_rejects_bad_calibration_and_f1_regression() -> None:
    """Both mandatory challenger gates produce an explicit rejection."""
    metrics = TrainingMetrics(
        roc_auc=0.70,
        log_loss=0.60,
        brier_score=0.08,
        f1=0.65,
        decision_threshold=0.5,
        train_rows=100,
        validation_rows=20,
        test_rows=20,
    )
    with pytest.raises(ModelRejectedError, match="Brier score.*lower than champion F1"):
        validate_challenger(metrics, {"f1": 0.75})


def test_lightgbm_training_and_calibration_smoke() -> None:
    """The Vertex training core fits an early-stopped, calibrated challenger."""
    random = np.random.default_rng(47)
    row_count = 120
    frame = pd.DataFrame(
        {column: random.normal(size=row_count) for column in FEATURE_COLUMNS}
    )
    frame["retained_label"] = np.arange(row_count) % 2
    frame["feature_as_of_date"] = pd.date_range("2025-01-01", periods=row_count)
    booster, calibration, metrics, parameters = train_challenger(frame)
    assert booster.current_iteration() > 0
    assert np.isfinite(calibration.coefficient)
    assert 0.0 <= metrics.brier_score <= 1.0
    assert parameters["feature_columns"] == list(FEATURE_COLUMNS)


def test_worker_uses_parquet_feature_mock_and_inserts_forecasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the Celery task body with mocked BigQuery and a real SQL seat table."""
    active_seats, feature_rows = _synthetic_feature_mock()
    tenant_id = str(feature_rows[0]["tenant_id"])
    engine = create_engine("sqlite+pysqlite:///:memory:")
    SeatForecast.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    monkeypatch.setattr(
        seat_forecasting,
        "get_settings",
        lambda: SimpleNamespace(seat_default_trueup_penalty_rate=0.25),
    )
    monkeypatch.setattr(seat_forecasting, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        seat_forecasting,
        "fetch_bigquery_features",
        lambda *_args, **_kwargs: feature_rows,
    )
    monkeypatch.setattr(
        seat_forecasting,
        "load_active_seats",
        lambda *_args, **_kwargs: active_seats,
    )
    monkeypatch.setattr(
        seat_forecasting,
        "load_latest_model",
        lambda *_args, **_kwargs: _TelemetryPredictor(),
    )

    result = seat_forecasting.run_seat_forecast.run(tenant_id, 90)
    assert result["status"] == "completed"
    assert result["forecasts_written"] > 0
    with factory() as session:
        count = session.scalar(select(func.count()).select_from(SeatForecast))
        stored = session.scalars(select(SeatForecast)).all()
    assert count == result["forecasts_written"]
    assert all(row.tenant_id == tenant_id for row in stored)
    assert all(row.model_version == "v_test_telemetry" for row in stored)
    assert all(row.retention_curve["horizon_days"] == 90 for row in stored)


def test_gcp_ml_credentials_load_from_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The three required GCP ML values load through pydantic ``.env`` support."""
    for variable in (
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GCS_ML_BUCKET",
    ):
        monkeypatch.delenv(variable, raising=False)
    env_file = Path(__file__).parent / "fixtures" / "seat_forecasting.env"
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.google_cloud_project == "project-test"
    assert settings.gcs_ml_bucket == "ml-test"
    assert settings.google_application_credentials == "/secrets/gcp.json"


def test_ml_runtime_settings_do_not_require_application_secrets() -> None:
    """Standalone training configuration loads with only ML runtime values."""
    settings = MLRuntimeSettings(
        _env_file=Path(__file__).parent / "fixtures" / "seat_ml_runtime.env"
    )  # type: ignore[call-arg]
    assert settings.google_cloud_project == "project-test"
    assert settings.gcs_raw_bucket == "raw-test"
    assert settings.gcs_ml_bucket == "ml-test"


def test_forecasting_task_is_registered_on_celery() -> None:
    """The externally documented Celery task name remains stable."""
    from zellovest_workers.celery_app import celery_app

    task_name = "zellovest.workers.tasks.forecasting.run_seat_forecast"
    assert task_name in celery_app.tasks
