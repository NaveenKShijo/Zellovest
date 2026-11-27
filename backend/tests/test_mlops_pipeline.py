"""Comprehensive tests for Phases 1-5 of production seat forecasting & MLOps."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from zellovest_shared.db.intelligence import MLDriftReport, MLModelMetric, SeatForecast
from zellovest_workers.ml.benchmark_generator import (
    TRAINING_CATALOG,
    UNSEEN_INFERENCE_CATALOG,
    build_features_from_telemetry,
    generate_multi_cohort_benchmark,
)
from zellovest_workers.ml.evaluation import (
    EVALUATION_SQL_PATH,
    build_prediction_log_rows,
    compute_online_evaluation,
    persist_evaluation_segments,
)
from zellovest_workers.ml.feature_pipeline import render_sql
from zellovest_workers.ml.monitoring import (
    analyze_feature_drift,
    compute_psi,
    evaluate_retraining_triggers,
    persist_drift_report,
)
from zellovest_workers.ml.optimizer import optimize_commitment, poisson_growth_pmf
from zellovest_workers.ml.train_vertex import (
    FEATURE_COLUMNS,
    ModelRejectedError,
    TrainingMetrics,
    _split_frame,
    compute_baseline_stats,
    train_challenger,
    validate_challenger,
)
from zellovest_workers.tasks import ml_ops, seat_forecasting
from zellovest_workers.tasks.seat_forecasting import ActiveSeat


def test_feature_columns_are_vendor_agnostic_and_include_horizon_and_category() -> None:
    """Model inputs exclude identifiers and include horizon + normalized app context."""
    for forbidden in ("vendor_id", "employee_id", "tenant_id", "app_name"):
        assert forbidden not in FEATURE_COLUMNS
    for required in (
        "renewal_horizon_days",
        "app_median_logins_30d",
        "relative_login_ratio",
        "annual_seat_cost",
        "app_cat_sales",
        "app_cat_collaboration",
        "app_cat_engineering",
    ):
        assert required in FEATURE_COLUMNS


def test_evaluation_sql_renders_without_unresolved_placeholders() -> None:
    """The BigQuery outcome-join SQL template renders cleanly."""
    rendered = render_sql(
        EVALUATION_SQL_PATH.read_text(encoding="utf-8"),
        {
            "PROJECT_ID": "test-proj",
            "GOLD_DATASET": "zellovest_gold",
            "BQ_LOCATION": "US",
            "PREDICTION_LOGS_TABLE": "gold_seat_prediction_logs",
            "SEAT_FEATURES_TABLE": "gold_seat_features",
        },
    )
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_split_frame_enforces_leak_free_renewal_cohort_separation() -> None:
    """No renewal_date may appear in more than one split partition."""
    rng = np.random.default_rng(47)
    renewal_dates = [
        date(2025, 3, 1),
        date(2025, 6, 1),
        date(2025, 9, 1),
        date(2025, 12, 1),
        date(2026, 3, 1),
    ]
    rows = []
    for r_date in renewal_dates:
        for horizon in (120, 90, 60, 30):
            for idx in range(15):
                row = {col: float(rng.normal()) for col in FEATURE_COLUMNS}
                row["renewal_horizon_days"] = float(horizon)
                row["retained_label"] = int((idx + horizon) % 2)
                row["renewal_date"] = r_date.isoformat()
                row["feature_as_of_date"] = (r_date - timedelta(days=horizon)).isoformat()
                row["tenant_id"] = "t1"
                row["employee_id"] = f"e_{idx}"
                row["vendor_id"] = "v1"
                rows.append(row)

    frame = pd.DataFrame(rows)
    train, val, test = _split_frame(frame, random_state=47)
    train_dates = set(train["renewal_date"])
    val_dates = set(val["renewal_date"])
    test_dates = set(test["renewal_date"])
    assert train_dates.isdisjoint(val_dates)
    assert train_dates.isdisjoint(test_dates)
    assert val_dates.isdisjoint(test_dates)


def test_benchmark_training_generalizes_to_unseen_vendors_end_to_end() -> None:
    """Train on multi-cohort benchmark tenants and score unseen vendors in default_org."""
    train_bundle, infer_bundle = generate_multi_cohort_benchmark(
        num_training_tenants=3,
        seed=47,
        reference_today=date(2026, 11, 27),
    )
    assert set(train_bundle.keys()) == {
        "dim_users",
        "fact_seat_assignments",
        "fact_sso_events",
        "dim_contracts",
    }
    train_apps = {tool.app_name for tool in TRAINING_CATALOG}
    infer_apps = {tool.app_name for tool in UNSEEN_INFERENCE_CATALOG}
    assert train_apps.isdisjoint(infer_apps)

    train_features = build_features_from_telemetry(
        train_bundle,
        reference_today=date(2026, 11, 27),
    )
    labeled_train = train_features[train_features["retained_label"].notna()].copy()
    assert len(labeled_train) >= 400

    booster, calibration, metrics, params, extras = train_challenger(
        labeled_train,
        random_state=47,
        return_artifacts=True,
    )
    assert metrics.roc_auc >= 0.72
    assert metrics.brier_score <= 0.22
    assert metrics.ece <= 0.12
    assert params["feature_columns"] == list(FEATURE_COLUMNS)

    baseline_stats = compute_baseline_stats(
        extras["train_frame"],
        extras["calibrated_test_probabilities"],
        model_version="v_20261127T000000Z",
    )
    assert len(baseline_stats["features"]) == len(FEATURE_COLUMNS)

    # Score unseen vendors in default_org using the trained model + calibration.
    infer_features = build_features_from_telemetry(
        infer_bundle,
        horizons=(90,),
        reference_today=date(2026, 11, 27),
    )
    infer_90 = infer_features[infer_features["renewal_horizon_days"] == 90].copy()
    assert not infer_90.empty
    assert set(infer_90["app_name"]).issubset(infer_apps)

    from zellovest_workers.ml.train_vertex import apply_calibration

    raw_preds = booster.predict(infer_90[list(FEATURE_COLUMNS)].to_numpy(dtype=np.float64))
    cal_preds = apply_calibration(raw_preds, calibration)
    assert np.all(np.isfinite(cal_preds))
    assert np.all((cal_preds >= 0.0) & (cal_preds <= 1.0))
    assert float(np.std(cal_preds)) > 0.05


def test_growth_aware_optimizer_can_recommend_expansion_and_is_monotonic() -> None:
    """High department headcount growth shifts recommended seats above current seats."""
    probs = [0.92] * 20
    zero_growth = optimize_commitment(probs, 1000.0, 0.40, horizon_days=120, expected_growth_rate=0.0)
    high_growth = optimize_commitment(probs, 1000.0, 0.40, horizon_days=120, expected_growth_rate=0.45)
    assert zero_growth.expected_growth_seats == 0.0
    assert high_growth.expected_growth_seats > 0.0
    assert high_growth.recommended_seats >= zero_growth.recommended_seats
    assert high_growth.recommended_seats > high_growth.current_seats
    pmf = poisson_growth_pmf(2.5)
    assert float(pmf.sum()) == pytest.approx(1.0)


def test_multi_horizon_forecasts_persist_on_same_forecast_date() -> None:
    """Running 120d and 90d forecasts on the same day keeps both rows in SQL."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    SeatForecast.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    vendor_id = str(uuid.uuid4())
    active_seats = [
        ActiveSeat(
            employee_id=f"emp_{i}",
            vendor_id=vendor_id,
            department_id=None,
            department="Engineering",
            seats=1,
        )
        for i in range(6)
    ]
    feature_rows = [
        {
            "tenant_id": "default_org",
            "employee_id": f"emp_{i}",
            "vendor_id": vendor_id,
            "department": "Engineering",
            "app_category": "Engineering",
            "renewal_date": "2027-03-01",
            "logins_30d": 12 - i,
            "logins_60d": 24,
            "logins_90d": 36,
            "days_since_last_login": i,
            "login_momentum": 1.0,
            "tenure_days": 300,
            "days_since_assigned": 200,
            "department_churn_rate": 0.08,
            "department_growth_rate": 0.25,
            "annual_seat_cost": 500.0,
            "trueup_penalty_rate": 0.25,
        }
        for i in range(6)
    ]

    class _MockPredictor:
        model_version = "v_test_multi"

        def predict(self, rows):
            return np.asarray([0.85 for _ in rows], dtype=np.float64)

    fixed_date = date(2026, 11, 27)
    r_120 = seat_forecasting.build_forecast_records(
        tenant_id="default_org",
        horizon_days=120,
        active_seats=active_seats,
        feature_rows=feature_rows,
        predictor=_MockPredictor(),
        forecast_on=fixed_date,
    )
    r_90 = seat_forecasting.build_forecast_records(
        tenant_id="default_org",
        horizon_days=90,
        active_seats=active_seats,
        feature_rows=feature_rows,
        predictor=_MockPredictor(),
        forecast_on=fixed_date,
    )
    with factory() as session:
        seat_forecasting.persist_forecasts(session, r_120)
        seat_forecasting.persist_forecasts(session, r_90)
        count = session.scalar(select(func.count()).select_from(SeatForecast))
        horizons = session.scalars(select(SeatForecast.horizon_days)).all()
    assert count == 2
    assert set(horizons) == {90, 120}


def test_prediction_logging_and_delayed_online_evaluation() -> None:
    """Prediction logs convert cleanly and delayed outcomes compute financial regret."""
    vendor_id = str(uuid.uuid4())
    feature_rows = [
        {
            **{col: 1.0 for col in FEATURE_COLUMNS},
            "vendor_id": vendor_id,
            "employee_id": f"e{i}",
            "department": "Sales",
            "app_category": "Sales",
            "renewal_date": "2026-10-01",
            "annual_seat_cost": 1000.0,
            "trueup_penalty_rate": 0.50,
        }
        for i in range(10)
    ]
    logs = build_prediction_log_rows(
        tenant_id="default_org",
        horizon_days=90,
        forecast_date=date(2026, 7, 1),
        model_version="v_eval_1",
        feature_rows=feature_rows,
        raw_probabilities=[0.9 if i < 6 else 0.1 for i in range(10)],
        calibrated_probabilities=[0.9 if i < 6 else 0.1 for i in range(10)],
        cohort_recommendations={(vendor_id, "Sales"): (6, 10)},
    )
    assert len(logs) == 10
    assert json.loads(logs[0]["features_json"])["renewal_horizon_days"] == 1.0

    outcomes_df = pd.DataFrame(logs)
    outcomes_df["actual_retained"] = [1 if i < 6 else 0 for i in range(10)]
    segments = compute_online_evaluation(outcomes_df, tenant_id="default_org")
    overall = next(s for s in segments if s.segment_type == "overall")
    assert overall.evaluated_seats == 10
    assert overall.roc_auc == 1.0
    assert overall.realized_savings_vs_naive == 4000.0
    assert overall.financial_regret == 0.0

    engine = create_engine("sqlite+pysqlite:///:memory:")
    MLModelMetric.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        ids = persist_evaluation_segments(session, segments)
        assert len(ids) == len(segments)
        assert session.scalar(select(func.count()).select_from(MLModelMetric)) == len(segments)


def test_drift_detection_sentinel_alerts_and_ct_triggers() -> None:
    """PSI and sentinel spike detection catch upstream Okta outages and drift."""
    rng = np.random.default_rng(47)
    base_df = pd.DataFrame(
        {col: rng.normal(loc=5.0, scale=1.5, size=300) for col in FEATURE_COLUMNS}
    )
    base_df["days_since_last_login"] = rng.integers(0, 30, size=300).astype(float)
    base_df["retained_label"] = rng.integers(0, 2, size=300)
    baseline = compute_baseline_stats(
        base_df,
        rng.uniform(0.1, 0.9, size=300),
        model_version="v_base",
    )

    # Healthy live sample matches baseline distribution.
    healthy_live = base_df[list(FEATURE_COLUMNS)].copy()
    healthy_live["calibrated_probability"] = rng.uniform(0.1, 0.9, size=300)
    healthy_res = analyze_feature_drift(
        baseline_stats=baseline,
        live_frame=healthy_live,
        tenant_id="default_org",
        model_version="v_base",
    )
    assert healthy_res.severity == "healthy"
    assert not healthy_res.retrain_recommended

    # Broken Okta sync causes 9999 sentinel spike.
    broken_live = healthy_live.copy()
    broken_live["days_since_last_login"] = 9999.0
    broken_res = analyze_feature_drift(
        baseline_stats=baseline,
        live_frame=broken_live,
        tenant_id="default_org",
        model_version="v_base",
    )
    assert broken_res.severity == "critical"
    assert broken_res.max_sentinel_delta >= 0.95
    assert "days_since_last_login" in broken_res.drifted_features
    assert broken_res.retrain_recommended

    decision = evaluate_retraining_triggers(
        drift=broken_res,
        online_brier_score=0.11,
        online_ece=0.07,
        new_labeled_rows=600,
        days_since_last_train=35,
    )
    assert decision.should_retrain
    assert len(decision.reasons) == 4
    assert compute_psi([0.5, 0.5], [0.0, 0.5, 1.0], np.array([0.9, 0.95, 0.99])) > 0.25


def test_challenger_gate_enforces_ece_auc_and_negative_backtest() -> None:
    """Production gate rejects high ECE, weak AUC, and negative financial backtest."""
    bad = TrainingMetrics(
        roc_auc=0.58,
        log_loss=0.65,
        brier_score=0.09,
        f1=0.60,
        decision_threshold=0.5,
        train_rows=200,
        validation_rows=50,
        test_rows=50,
        ece=0.11,
        financial_savings_rate=-0.05,
        backtest_cohorts=4,
    )
    with pytest.raises(ModelRejectedError, match="ECE.*ROC-AUC.*Financial backtest"):
        validate_challenger(bad, None, brier_score_limit=0.08, require_positive_backtest=True)


def test_mlops_drift_task_registered_and_persists_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scheduled Celery MLOps task runs end-to-end and saves MLDriftReport."""
    from zellovest_workers.celery_app import celery_app

    assert "zellovest.workers.tasks.mlops.run_drift_monitoring" in celery_app.tasks

    engine = create_engine("sqlite+pysqlite:///:memory:")
    MLDriftReport.__table__.create(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    rng = np.random.default_rng(7)
    base_df = pd.DataFrame({col: rng.normal(size=100) for col in FEATURE_COLUMNS})
    base_df["days_since_last_login"] = 5.0
    base_df["retained_label"] = rng.integers(0, 2, size=100)
    baseline = compute_baseline_stats(base_df, rng.uniform(0.2, 0.8, size=100), model_version="v_1")
    live_df = base_df[list(FEATURE_COLUMNS)].copy()
    live_df["calibrated_probability"] = rng.uniform(0.2, 0.8, size=100)
    live_df["model_version"] = "v_1"

    monkeypatch.setattr(
        ml_ops,
        "get_settings",
        lambda: SimpleNamespace(
            ml_psi_warning_threshold=0.10,
            ml_psi_critical_threshold=0.25,
            ml_online_brier_threshold=0.08,
            ml_online_ece_threshold=0.06,
            ml_min_retrain_labels=500,
            ml_retrain_cadence_days=30,
            ml_auto_retrain_enabled=False,
        ),
    )
    monkeypatch.setattr(ml_ops, "load_baseline_stats", lambda _s: baseline)
    monkeypatch.setattr(ml_ops, "_fetch_live_inference_slice", lambda _t, _s: live_df)
    monkeypatch.setattr(ml_ops, "get_session_factory", lambda: factory)
    monkeypatch.setattr(ml_ops, "evaluate_matured_forecasts", lambda **_kw: [])

    result = ml_ops.run_drift_monitoring.run("default_org")
    assert result["status"] == "completed"
    assert result["severity"] == "healthy"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MLDriftReport)) == 1
        report = session.scalar(select(MLDriftReport))
        assert report is not None
        assert report.tenant_id == "default_org"
        # Exercise persist_drift_report explicitly as well.
        _ = persist_drift_report(
            session,
            analyze_feature_drift(
                baseline_stats=baseline,
                live_frame=live_df,
                tenant_id="default_org",
                model_version="v_1",
                reference_date=None,
            ),
        )
        assert session.scalar(select(func.count()).select_from(MLDriftReport)) == 2


def test_drift_report_uses_utc_date() -> None:
    """Drift analysis defaults reference_date to UTC today."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({col: rng.normal(size=50) for col in FEATURE_COLUMNS})
    df["retained_label"] = rng.integers(0, 2, size=50)
    baseline = compute_baseline_stats(df, rng.uniform(0.1, 0.9, size=50), model_version="v_utc")
    res = analyze_feature_drift(
        baseline_stats=baseline,
        live_frame=df[list(FEATURE_COLUMNS)],
        tenant_id="t_utc",
        model_version="v_utc",
    )
    assert res.reference_date == pd.Timestamp.now(tz=UTC).date()
