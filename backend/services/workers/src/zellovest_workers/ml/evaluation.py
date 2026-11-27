"""Closed-loop prediction logging and delayed ground-truth evaluation.

Inference batches record seat-level predictions and feature vectors to BigQuery
(``gold_seat_prediction_logs``). Once a contract's ``renewal_date`` passes,
delayed ground truth is joined to measure online calibration (Brier, ECE),
discrimination (ROC-AUC, F1), and realized financial regret vs naive renewal.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, f1_score, log_loss, roc_auc_score
from sqlalchemy.orm import Session
from zellovest_shared.config import Settings, get_settings
from zellovest_shared.db.intelligence import MLModelMetric
from zellovest_shared.logging_conf import get_logger

from zellovest_workers.ml.feature_pipeline import render_sql
from zellovest_workers.ml.train_vertex import FEATURE_COLUMNS, compute_ece

logger = get_logger(__name__)
EVALUATION_SQL_PATH = Path(__file__).resolve().parent / "sql" / "04_gold_prediction_evaluation.sql"


@dataclass(frozen=True, slots=True)
class EvaluationSegment:
    """Computed ML + financial regret metrics for one evaluated segment."""

    tenant_id: str
    model_version: str
    horizon_days: int | None
    segment_type: str
    segment_value: str
    evaluated_seats: int
    cohort_count: int
    roc_auc: float | None
    log_loss: float | None
    brier_score: float | None
    ece: float | None
    f1: float | None
    realized_cost: float
    naive_baseline_cost: float
    oracle_cost: float
    realized_savings_vs_naive: float
    financial_regret: float
    trueup_incident_rate: float
    evaluation_window_start: date | None
    evaluation_window_end: date | None

    def to_orm(self) -> MLModelMetric:
        """Convert this segment into a PostgreSQL ``MLModelMetric`` row."""
        return MLModelMetric(
            tenant_id=self.tenant_id,
            model_version=self.model_version,
            horizon_days=self.horizon_days,
            segment_type=self.segment_type,
            segment_value=self.segment_value,
            evaluated_seats=self.evaluated_seats,
            cohort_count=self.cohort_count,
            roc_auc=self.roc_auc,
            log_loss=self.log_loss,
            brier_score=self.brier_score,
            ece=self.ece,
            f1=self.f1,
            realized_cost=self.realized_cost,
            naive_baseline_cost=self.naive_baseline_cost,
            oracle_cost=self.oracle_cost,
            realized_savings_vs_naive=self.realized_savings_vs_naive,
            financial_regret=self.financial_regret,
            trueup_incident_rate=self.trueup_incident_rate,
            evaluation_window_start=self.evaluation_window_start,
            evaluation_window_end=self.evaluation_window_end,
        )


def build_prediction_log_rows(
    *,
    tenant_id: str,
    horizon_days: int,
    forecast_date: date,
    model_version: str,
    feature_rows: Sequence[Mapping[str, Any]],
    raw_probabilities: Sequence[float],
    calibrated_probabilities: Sequence[float],
    cohort_recommendations: Mapping[tuple[str, str], tuple[int, int]],
) -> list[dict[str, Any]]:
    """Construct JSON-serializable BigQuery prediction log records."""
    now_iso = datetime.now(UTC).isoformat()
    logs: list[dict[str, Any]] = []
    for row, raw_p, cal_p in zip(
        feature_rows, raw_probabilities, calibrated_probabilities, strict=True
    ):
        vendor_id = str(row.get("vendor_id", ""))
        department = str(row.get("department") or "Unassigned")
        rec_seats, cur_seats = cohort_recommendations.get((vendor_id, department), (1, 1))
        renewal_raw = row.get("renewal_date")
        if isinstance(renewal_raw, datetime):
            renewal_iso = renewal_raw.date().isoformat()
        elif isinstance(renewal_raw, date):
            renewal_iso = renewal_raw.isoformat()
        elif renewal_raw:
            renewal_iso = str(renewal_raw)[:10]
        else:
            renewal_iso = None

        feature_payload = {
            column: float(row.get(column, 0.0) or 0.0) for column in FEATURE_COLUMNS
        }
        logs.append(
            {
                "prediction_id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "vendor_id": vendor_id,
                "employee_id": str(row.get("employee_id", "")),
                "department": department,
                "app_category": str(row.get("app_category") or "Other"),
                "renewal_date": renewal_iso,
                "horizon_days": int(horizon_days),
                "forecast_date": forecast_date.isoformat(),
                "model_version": model_version,
                "raw_probability": round(float(raw_p), 8),
                "calibrated_probability": round(float(cal_p), 8),
                "annual_seat_cost": float(row.get("annual_seat_cost") or 0.0),
                "trueup_penalty_rate": float(row.get("trueup_penalty_rate") or 0.25),
                "recommended_cohort_seats": int(rec_seats),
                "current_cohort_seats": int(cur_seats),
                "features_json": json.dumps(feature_payload, sort_keys=True),
                "logged_at": now_iso,
            }
        )
    return logs


def log_seat_predictions(
    rows: Sequence[Mapping[str, Any]],
    *,
    settings: Settings | None = None,
) -> int:
    """Persist seat-level prediction logs to BigQuery ``gold_seat_prediction_logs``."""
    if not rows:
        return 0
    resolved = settings or get_settings()
    project_id = getattr(resolved, "google_cloud_project", "") or ""
    if not project_id:
        logger.warning("seat_prediction_log_skipped", reason="missing GOOGLE_CLOUD_PROJECT")
        return 0

    from google.cloud import bigquery

    gold_dataset = getattr(resolved, "bigquery_gold_dataset", "zellovest_gold")
    table_name = getattr(
        resolved, "bigquery_seat_prediction_logs_table", "gold_seat_prediction_logs"
    )
    table_id = f"{project_id}.{gold_dataset}.{table_name}"
    client = bigquery.Client(project=project_id)

    schema = [
        bigquery.SchemaField("prediction_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tenant_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("vendor_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("employee_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("department", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("app_category", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("renewal_date", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("horizon_days", "INT64", mode="REQUIRED"),
        bigquery.SchemaField("forecast_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("model_version", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("raw_probability", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("calibrated_probability", "FLOAT64", mode="REQUIRED"),
        bigquery.SchemaField("annual_seat_cost", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("trueup_penalty_rate", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("recommended_cohort_seats", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("current_cohort_seats", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("features_json", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("logged_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="forecast_date",
    )
    table.clustering_fields = ["tenant_id", "model_version"]
    client.create_table(table, exists_ok=True)

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(list(rows), table_id, job_config=job_config)
    job.result()
    logger.info("seat_prediction_logs_written", table=table_id, rows=len(rows))
    return len(rows)


def _score_segment(
    frame: pd.DataFrame,
    *,
    tenant_id: str,
    model_version: str,
    horizon_days: int | None,
    segment_type: str,
    segment_value: str,
) -> EvaluationSegment:
    """Compute ML calibration/accuracy and cohort financial regret on one slice."""
    labels = frame["actual_retained"].astype(int).to_numpy()
    probs = np.clip(frame["calibrated_probability"].astype(float).to_numpy(), 1e-7, 1.0 - 1e-7)

    roc_auc: float | None = None
    ll_val: float | None = None
    if len(np.unique(labels)) == 2:
        roc_auc = round(float(roc_auc_score(labels, probs)), 6)
    ll_val = round(float(log_loss(labels, probs, labels=[0, 1])), 6)
    brier = round(float(brier_score_loss(labels, probs)), 6)
    ece = round(float(compute_ece(labels, probs)), 6)
    f1 = round(float(f1_score(labels, probs >= 0.5, zero_division=0)), 6)

    cohort_cols = ["vendor_id", "department", "renewal_date", "horizon_days"]
    realized_cost = 0.0
    naive_cost = 0.0
    oracle_cost = 0.0
    trueup_incidents = 0
    cohort_count = 0

    for _, cohort in frame.groupby(cohort_cols, dropna=False):
        seat_cost = float(cohort["annual_seat_cost"].iloc[0] or 0.0)
        penalty = float(cohort["trueup_penalty_rate"].iloc[0] or 0.25)
        actual_demand = int(cohort["actual_retained"].sum())
        current_seats = int(cohort["current_cohort_seats"].iloc[0] or len(cohort))
        rec_raw = cohort["recommended_cohort_seats"].iloc[0]
        recommended_seats = int(rec_raw) if pd.notna(rec_raw) else current_seats

        rec_trueup = max(actual_demand - recommended_seats, 0) * seat_cost * (1.0 + penalty)
        naive_trueup = max(actual_demand - current_seats, 0) * seat_cost * (1.0 + penalty)

        realized_cost += recommended_seats * seat_cost + rec_trueup
        naive_cost += current_seats * seat_cost + naive_trueup
        oracle_cost += actual_demand * seat_cost
        if actual_demand > recommended_seats:
            trueup_incidents += 1
        cohort_count += 1

    renewal_series = pd.to_datetime(frame["renewal_date"], errors="coerce").dropna()
    win_start = renewal_series.min().date() if not renewal_series.empty else None
    win_end = renewal_series.max().date() if not renewal_series.empty else None

    return EvaluationSegment(
        tenant_id=tenant_id,
        model_version=model_version,
        horizon_days=horizon_days,
        segment_type=segment_type,
        segment_value=segment_value,
        evaluated_seats=len(frame),
        cohort_count=cohort_count,
        roc_auc=roc_auc,
        log_loss=ll_val,
        brier_score=brier,
        ece=ece,
        f1=f1,
        realized_cost=round(realized_cost, 2),
        naive_baseline_cost=round(naive_cost, 2),
        oracle_cost=round(oracle_cost, 2),
        realized_savings_vs_naive=round(naive_cost - realized_cost, 2),
        financial_regret=round(realized_cost - oracle_cost, 2),
        trueup_incident_rate=round(trueup_incidents / max(cohort_count, 1), 6),
        evaluation_window_start=win_start,
        evaluation_window_end=win_end,
    )


def compute_online_evaluation(
    outcomes_frame: pd.DataFrame,
    *,
    tenant_id: str,
) -> list[EvaluationSegment]:
    """Compute overall, per-horizon, and per-department evaluation segments."""
    if outcomes_frame.empty:
        return []

    required = {
        "model_version",
        "vendor_id",
        "department",
        "renewal_date",
        "horizon_days",
        "calibrated_probability",
        "actual_retained",
    }
    missing = sorted(required - set(outcomes_frame.columns))
    if missing:
        raise ValueError(f"outcomes frame missing required columns: {missing}")

    frame = outcomes_frame.copy()
    if "annual_seat_cost" not in frame.columns:
        frame["annual_seat_cost"] = 0.0
    if "trueup_penalty_rate" not in frame.columns:
        frame["trueup_penalty_rate"] = 0.25
    if "current_cohort_seats" not in frame.columns:
        frame["current_cohort_seats"] = frame.groupby(
            ["vendor_id", "department", "renewal_date", "horizon_days"]
        )["calibrated_probability"].transform("count")
    if "recommended_cohort_seats" not in frame.columns:
        frame["recommended_cohort_seats"] = frame["current_cohort_seats"]

    segments: list[EvaluationSegment] = []
    for model_version, mv_frame in frame.groupby("model_version"):
        mv_str = str(model_version)
        segments.append(
            _score_segment(
                mv_frame,
                tenant_id=tenant_id,
                model_version=mv_str,
                horizon_days=None,
                segment_type="overall",
                segment_value="all",
            )
        )
        for horizon, h_frame in mv_frame.groupby("horizon_days"):
            segments.append(
                _score_segment(
                    h_frame,
                    tenant_id=tenant_id,
                    model_version=mv_str,
                    horizon_days=int(horizon),
                    segment_type="horizon",
                    segment_value=f"{int(horizon)}d",
                )
            )
        for department, d_frame in mv_frame.groupby("department"):
            segments.append(
                _score_segment(
                    d_frame,
                    tenant_id=tenant_id,
                    model_version=mv_str,
                    horizon_days=None,
                    segment_type="department",
                    segment_value=str(department or "Unassigned"),
                )
            )
    return segments


def persist_evaluation_segments(
    session: Session,
    segments: Sequence[EvaluationSegment],
) -> list[uuid.UUID]:
    """Persist evaluated online metric segments into PostgreSQL."""
    inserted: list[uuid.UUID] = []
    for segment in segments:
        row = segment.to_orm()
        session.add(row)
        session.flush()
        inserted.append(row.id)
    session.commit()
    return inserted


def evaluate_matured_forecasts(
    *,
    tenant_id: str,
    session: Session,
    settings: Settings | None = None,
) -> list[EvaluationSegment]:
    """Refresh BigQuery outcome joins and persist PostgreSQL evaluation metrics."""
    resolved = settings or get_settings()
    project_id = getattr(resolved, "google_cloud_project", "") or ""
    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT is required for BigQuery evaluation")

    from google.cloud import bigquery

    gold_dataset = getattr(resolved, "bigquery_gold_dataset", "zellovest_gold")
    logs_table = getattr(
        resolved, "bigquery_seat_prediction_logs_table", "gold_seat_prediction_logs"
    )
    features_table = getattr(resolved, "bigquery_seat_features_table", "gold_seat_features")
    location = (
        getattr(resolved, "bigquery_location", "US")
        if hasattr(resolved, "bigquery_location")
        else "US"
    )

    sql = render_sql(
        EVALUATION_SQL_PATH.read_text(encoding="utf-8"),
        {
            "PROJECT_ID": project_id,
            "GOLD_DATASET": gold_dataset,
            "BQ_LOCATION": location,
            "PREDICTION_LOGS_TABLE": logs_table,
            "SEAT_FEATURES_TABLE": features_table,
        },
    )
    client = bigquery.Client(project=project_id)
    client.query(sql).result()

    outcomes_table = f"{project_id}.{gold_dataset}.gold_seat_prediction_outcomes"
    query = f"""
        SELECT *
        FROM `{outcomes_table}`
        WHERE tenant_id = @tenant_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id)]
    )
    frame = client.query(query, job_config=job_config).to_dataframe(progress_bar_type=None)
    segments = compute_online_evaluation(frame, tenant_id=tenant_id)
    if segments:
        persist_evaluation_segments(session, segments)
    logger.info(
        "seat_online_evaluation_completed",
        tenant_id=tenant_id,
        outcomes=len(frame),
        segments=len(segments),
    )
    return segments
