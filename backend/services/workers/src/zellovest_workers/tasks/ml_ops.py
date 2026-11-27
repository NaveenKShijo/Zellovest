"""Celery MLOps tasks: drift monitoring, online evaluation, and auto-retraining."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from zellovest_shared.config import get_settings
from zellovest_shared.db.session import get_session_factory
from zellovest_shared.logging_conf import get_logger

from zellovest_workers.celery_app import QUEUE_ANALYTICS, celery_app
from zellovest_workers.ml.evaluation import evaluate_matured_forecasts
from zellovest_workers.ml.monitoring import (
    analyze_feature_drift,
    evaluate_retraining_triggers,
    load_baseline_stats,
    persist_drift_report,
)
from zellovest_workers.ml.vertex_training import run_training

logger = get_logger(__name__)


def _parse_model_age_days(model_version: str) -> int:
    """Extract age in days from ``v_YYYYMMDDTHHMMSSZ`` model version strings."""
    if model_version.startswith("v_") and len(model_version) >= 10:
        try:
            trained_dt = datetime.strptime(model_version[2:10], "%Y%m%d").replace(tzinfo=UTC)
            return max((datetime.now(UTC) - trained_dt).days, 0)
        except ValueError:
            pass
    return 0


def _fetch_live_inference_slice(tenant_id: str, settings: Any) -> pd.DataFrame:
    """Load recent logged prediction features and scores from BigQuery."""
    project_id = getattr(settings, "google_cloud_project", "") or ""
    if not project_id:
        return pd.DataFrame()
    from google.cloud import bigquery

    gold_dataset = getattr(settings, "bigquery_gold_dataset", "zellovest_gold")
    logs_table = getattr(
        settings, "bigquery_seat_prediction_logs_table", "gold_seat_prediction_logs"
    )
    client = bigquery.Client(project=project_id)
    query = f"""
        SELECT calibrated_probability, features_json, model_version
        FROM `{project_id}.{gold_dataset}.{logs_table}`
        WHERE tenant_id = @tenant_id
          AND forecast_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        LIMIT 10000
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id)]
    )
    rows = [dict(row.items()) for row in client.query(query, job_config=job_config).result()]
    if not rows:
        return pd.DataFrame()

    import json

    expanded: list[dict[str, Any]] = []
    for row in rows:
        features = json.loads(row.get("features_json") or "{}")
        features["calibrated_probability"] = row.get("calibrated_probability")
        features["model_version"] = row.get("model_version")
        expanded.append(features)
    return pd.DataFrame(expanded)


@celery_app.task(
    name="zellovest.workers.tasks.mlops.run_drift_monitoring",
    queue=QUEUE_ANALYTICS,
    max_retries=2,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
)
def run_drift_monitoring(tenant_id: str | None = None) -> dict[str, Any]:
    """Check feature/score drift against the champion baseline and evaluate CT triggers."""
    configured_tenant = os.getenv("TENANT_ID")
    resolved_tenant = (tenant_id or configured_tenant or "").strip()
    if not resolved_tenant:
        raise ValueError("tenant_id or TENANT_ID is required for drift monitoring")

    settings = get_settings()
    baseline = load_baseline_stats(settings)
    if baseline is None:
        logger.info("ml_drift_monitoring_skipped", tenant_id=resolved_tenant, reason="no_baseline")
        return {"tenant_id": resolved_tenant, "status": "no_baseline"}

    live_frame = _fetch_live_inference_slice(resolved_tenant, settings)
    model_version = (
        str(live_frame["model_version"].iloc[0])
        if not live_frame.empty and "model_version" in live_frame.columns
        else str(baseline.get("model_version") or "unknown")
    )
    analysis = analyze_feature_drift(
        baseline_stats=baseline,
        live_frame=live_frame,
        tenant_id=resolved_tenant,
        model_version=model_version,
        psi_warning=settings.ml_psi_warning_threshold,
        psi_critical=settings.ml_psi_critical_threshold,
    )

    session = get_session_factory()()
    try:
        segments = []
        try:
            segments = evaluate_matured_forecasts(
                tenant_id=resolved_tenant,
                session=session,
                settings=settings,
            )
        except Exception as exc:
            logger.warning(
                "ml_online_evaluation_skipped",
                tenant_id=resolved_tenant,
                error=str(exc),
            )

        overall = next((seg for seg in segments if seg.segment_type == "overall"), None)
        decision = evaluate_retraining_triggers(
            drift=analysis,
            online_brier_score=overall.brier_score if overall else None,
            online_ece=overall.ece if overall else None,
            new_labeled_rows=overall.evaluated_seats if overall else 0,
            days_since_last_train=_parse_model_age_days(model_version),
            online_brier_threshold=settings.ml_online_brier_threshold,
            online_ece_threshold=settings.ml_online_ece_threshold,
            min_new_labels=settings.ml_min_retrain_labels,
            cadence_days=settings.ml_retrain_cadence_days,
        )

        triggered = False
        job_uri: str | None = None
        if decision.should_retrain and settings.ml_auto_retrain_enabled:
            try:
                training_result = run_training(resolved_tenant)
                triggered = True
                job_uri = str(training_result.get("training_job") or "")
            except Exception:
                logger.exception("ml_auto_retrain_failed", tenant_id=resolved_tenant)

        report_id = persist_drift_report(
            session,
            analysis,
            retrain_triggered=triggered,
            trigger_reason="; ".join(decision.reasons) if decision.reasons else None,
            training_job_uri=job_uri,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    result = {
        "tenant_id": resolved_tenant,
        "status": "completed",
        "report_id": str(report_id),
        "severity": analysis.severity,
        "max_psi": analysis.max_psi,
        "score_psi": analysis.score_psi,
        "retrain_recommended": decision.should_retrain,
        "retrain_triggered": triggered,
        "reasons": list(decision.reasons),
        "training_job_uri": job_uri,
    }
    logger.info("ml_drift_monitoring_completed", **result)
    return result
