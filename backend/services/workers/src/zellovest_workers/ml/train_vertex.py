"""Vertex AI training entry point for calibrated LightGBM seat retention.

The module reads the Gold feature table through BigQuery's Storage Read API,
performs leakage-free renewal-cohort splitting, tunes a LightGBM classifier with
early stopping, calibrates probabilities with Platt scaling, enforces
calibration/slice/financial champion-challenger gates, emits drift baseline
statistics, and promotes approved artifacts to versioned and ``latest`` GCS
prefixes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, f1_score, log_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit, ParameterGrid, train_test_split
from zellovest_shared.config import MLRuntimeSettings
from zellovest_shared.logging_conf import get_logger

from zellovest_workers.ml.optimizer import optimize_commitment

logger = get_logger(__name__)

FEATURE_COLUMNS: tuple[str, ...] = (
    "logins_30d",
    "logins_60d",
    "logins_90d",
    "days_since_last_login",
    "login_momentum",
    "tenure_days",
    "days_since_assigned",
    "department_churn_rate",
    "renewal_horizon_days",
    "app_median_logins_30d",
    "relative_login_ratio",
    "annual_seat_cost",
    "department_engineering",
    "department_sales",
    "department_marketing",
    "department_finance",
    "department_hr",
    "department_operations",
    "department_other",
    "app_cat_sales",
    "app_cat_collaboration",
    "app_cat_engineering",
    "app_cat_design",
    "app_cat_marketing",
    "app_cat_other",
)
TARGET_COLUMN = "retained_label"
METADATA_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "employee_id",
    "vendor_id",
    "department",
    "renewal_date",
    "feature_as_of_date",
    "trueup_penalty_rate",
)


class ModelRejectedError(RuntimeError):
    """Raised when a challenger fails a mandatory production quality gate."""


def _vertex_run_id(model_version: str) -> str:
    """Normalize a model version into a Vertex-compatible run resource ID."""
    run_id = re.sub(r"[^a-z0-9-]+", "-", model_version.lower()).strip("-")
    if not run_id or not run_id[0].isalnum():
        run_id = f"run-{run_id}"
    return run_id[:128].rstrip("-")


@dataclass(frozen=True, slots=True)
class CalibrationParameters:
    """Platt-scaling coefficients applied to model probability logits."""

    coefficient: float
    intercept: float
    epsilon: float = 1e-7


@dataclass(frozen=True, slots=True)
class TrainingMetrics:
    """Held-out probability, calibration, and financial quality metrics."""

    roc_auc: float
    log_loss: float
    brier_score: float
    f1: float
    decision_threshold: float
    train_rows: int
    validation_rows: int
    test_rows: int
    ece: float = 0.0
    financial_savings_rate: float | None = None
    backtest_cohorts: int = 0
    slice_metrics: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Cloud locations and quality limits for one training invocation."""

    project_id: str
    region: str
    ml_bucket: str
    feature_table: str
    tenant_id: str = ""
    brier_score_limit: float = 0.05
    ece_limit: float = 0.06
    min_roc_auc: float = 0.65
    experiment_name: str = "seat-retention-training"
    random_state: int = 47

    @classmethod
    def from_environment(cls) -> TrainingConfig:
        """Load GCP and model settings from ``backend/.env`` and the process env."""
        settings = MLRuntimeSettings()
        project_id = settings.google_cloud_project.strip()
        synthetic = settings.seat_synthetic_mode
        ml_bucket = (settings.gcs_ml_synth if synthetic else settings.gcs_ml_bucket).strip()
        if not project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for model training")
        if not ml_bucket:
            raise ValueError(
                "GCS_ML_SYNTH is required for synthetic training"
                if synthetic else "GCS_ML_BUCKET is required for model training"
            )
        feature_table = (
            f"{project_id}.{settings.bigquery_gold_dataset}.{settings.bigquery_seat_features_table}"
        )
        return cls(
            project_id=project_id,
            region=settings.vertex_ai_region,
            ml_bucket=ml_bucket.removeprefix("gs://").rstrip("/"),
            feature_table=feature_table,
            brier_score_limit=float(os.getenv("SEAT_MODEL_BRIER_LIMIT", "0.05")),
            ece_limit=float(os.getenv("SEAT_MODEL_ECE_LIMIT", "0.06")),
            min_roc_auc=float(os.getenv("SEAT_MODEL_MIN_AUC", "0.65")),
            experiment_name=os.getenv("VERTEX_SEAT_EXPERIMENT", "seat-retention-training"),
        )


def load_training_frame(config: TrainingConfig) -> pd.DataFrame:
    """Read labeled features and cohort metadata via the BigQuery Storage Read API."""
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    selected = list(dict.fromkeys([*FEATURE_COLUMNS, TARGET_COLUMN, *METADATA_COLUMNS]))
    columns = ", ".join(selected)
    query = f"""
        SELECT {columns}
        FROM `{config.feature_table}`
        WHERE {TARGET_COLUMN} IS NOT NULL
          AND (@tenant_id = '' OR tenant_id = @tenant_id)
    """
    logger.info("seat_training_bigquery_read_started", table=config.feature_table)
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("tenant_id", "STRING", config.tenant_id)
    ])
    frame = client.query(query, job_config=job_config).to_dataframe(
        create_bqstorage_client=True,
        progress_bar_type=None,
    )
    logger.info("seat_training_bigquery_read_completed", rows=len(frame))
    return frame


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate required fields and coerce model features to finite numerics."""
    missing = sorted({*FEATURE_COLUMNS, TARGET_COLUMN} - set(frame.columns))
    if missing:
        raise ValueError(f"training data is missing required columns: {missing}")
    if len(frame) < 40:
        raise ValueError("at least 40 labeled rows are required for training")

    cleaned = frame.copy()
    for column in FEATURE_COLUMNS:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    cleaned[list(FEATURE_COLUMNS)] = cleaned[list(FEATURE_COLUMNS)].replace(
        [np.inf, -np.inf], np.nan
    )
    cleaned[list(FEATURE_COLUMNS)] = cleaned[list(FEATURE_COLUMNS)].fillna(0.0)
    cleaned[TARGET_COLUMN] = pd.to_numeric(cleaned[TARGET_COLUMN], errors="raise").astype(int)
    if not set(cleaned[TARGET_COLUMN].unique()).issubset({0, 1}):
        raise ValueError("retained_label must contain only 0 and 1")
    if cleaned[TARGET_COLUMN].nunique() != 2:
        raise ValueError("training data must contain both retained and churned examples")
    return cleaned


def _valid_partitions(partitions: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]) -> bool:
    """Verify every partition has enough rows and both target classes."""
    return all(
        len(partition) >= 2 and partition[TARGET_COLUMN].nunique() == 2
        for partition in partitions
    )


def _split_frame(
    frame: pd.DataFrame,
    random_state: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create leakage-free train/calibration/test partitions.

    Preference order:
    1. Strict chronological cohort split on ``renewal_date`` so no renewal event
       or its four horizon snapshots span train, calibration, and test.
    2. Group-aware split on ``(tenant_id, employee_id, vendor_id)`` when fewer
       than 3 distinct renewal dates exist.
    3. Chronological split on ``feature_as_of_date`` / stratified split for
       synthetic unit-test frames without cohort identifiers.
    """
    if "renewal_date" in frame.columns and frame["renewal_date"].notna().all():
        renewal_dates = pd.to_datetime(frame["renewal_date"], utc=True)
        unique_dates = np.sort(renewal_dates.unique())
        if len(unique_dates) >= 3:
            ordered = frame.assign(_renewal_dt=renewal_dates).sort_values("_renewal_dt")
            total = len(ordered)
            cumulative = np.arange(1, total + 1) / float(total)
            date_last_fraction = (
                ordered.assign(_cum=cumulative)
                .groupby("_renewal_dt", sort=True)["_cum"]
                .max()
            )
            train_cutoff = date_last_fraction[date_last_fraction <= 0.72].index.max()
            if pd.isna(train_cutoff):
                train_cutoff = unique_dates[0]
            val_candidates = date_last_fraction[
                (date_last_fraction.index > train_cutoff) & (date_last_fraction <= 0.88)
            ].index
            val_cutoff = (
                val_candidates.max()
                if len(val_candidates) > 0
                else unique_dates[
                    min(len(unique_dates) - 2, max(1, int(len(unique_dates) * 0.8)))
                ]
            )
            train_part = ordered[ordered["_renewal_dt"] <= train_cutoff].drop(
                columns=["_renewal_dt"]
            )
            val_part = ordered[
                (ordered["_renewal_dt"] > train_cutoff) & (ordered["_renewal_dt"] <= val_cutoff)
            ].drop(columns=["_renewal_dt"])
            test_part = ordered[ordered["_renewal_dt"] > val_cutoff].drop(columns=["_renewal_dt"])
            if _valid_partitions((train_part, val_part, test_part)):
                logger.info(
                    "seat_training_split_selected",
                    strategy="renewal_cohort_temporal",
                    train_rows=len(train_part),
                    validation_rows=len(val_part),
                    test_rows=len(test_part),
                )
                return train_part, val_part, test_part

    group_cols = [col for col in ("tenant_id", "employee_id", "vendor_id") if col in frame.columns]
    if group_cols and frame[group_cols].notna().all().all():
        groups = frame[group_cols].astype(str).agg("|".join, axis=1)
        if groups.nunique() >= 6:
            splitter1 = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=random_state)
            train_idx, rem_idx = next(splitter1.split(frame, frame[TARGET_COLUMN], groups))
            train_part = frame.iloc[train_idx]
            rem_part = frame.iloc[rem_idx]
            rem_groups = groups.iloc[rem_idx]
            if rem_groups.nunique() >= 4:
                splitter2 = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=random_state)
                val_rel, test_rel = next(
                    splitter2.split(rem_part, rem_part[TARGET_COLUMN], rem_groups)
                )
                val_part = rem_part.iloc[val_rel]
                test_part = rem_part.iloc[test_rel]
                if _valid_partitions((train_part, val_part, test_part)):
                    logger.info(
                        "seat_training_split_selected",
                        strategy="seat_group_shuffle",
                        train_rows=len(train_part),
                        validation_rows=len(val_part),
                        test_rows=len(test_part),
                    )
                    return train_part, val_part, test_part

    if "feature_as_of_date" in frame.columns and frame["feature_as_of_date"].notna().all():
        ordered = frame.assign(
            feature_as_of_date=pd.to_datetime(frame["feature_as_of_date"], utc=True)
        ).sort_values("feature_as_of_date")
        train_end = max(1, int(len(ordered) * 0.70))
        validation_end = max(train_end + 1, int(len(ordered) * 0.85))
        partitions = (
            ordered.iloc[:train_end],
            ordered.iloc[train_end:validation_end],
            ordered.iloc[validation_end:],
        )
        if _valid_partitions(partitions):
            return partitions

    train, remainder = train_test_split(
        frame,
        test_size=0.30,
        random_state=random_state,
        stratify=frame[TARGET_COLUMN],
    )
    validation, test = train_test_split(
        remainder,
        test_size=0.50,
        random_state=random_state,
        stratify=remainder[TARGET_COLUMN],
    )
    return train, validation, test


def _fit_calibrator(raw_probabilities: np.ndarray, labels: np.ndarray) -> CalibrationParameters:
    """Fit a one-dimensional Platt calibrator on validation probabilities."""
    epsilon = 1e-7
    clipped = np.clip(raw_probabilities, epsilon, 1.0 - epsilon)
    logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
    calibrator = LogisticRegression(random_state=47, solver="lbfgs")
    calibrator.fit(logits, labels)
    return CalibrationParameters(
        coefficient=float(calibrator.coef_[0, 0]),
        intercept=float(calibrator.intercept_[0]),
        epsilon=epsilon,
    )


def apply_calibration(
    raw_probabilities: np.ndarray,
    calibration: CalibrationParameters,
) -> np.ndarray:
    """Apply stored Platt coefficients to raw LightGBM probabilities."""
    clipped = np.clip(
        np.asarray(raw_probabilities, dtype=np.float64),
        calibration.epsilon,
        1.0 - calibration.epsilon,
    )
    logits = np.log(clipped / (1.0 - clipped))
    calibrated_logits = calibration.coefficient * logits + calibration.intercept
    return cast(
        np.ndarray,
        np.asarray(
            1.0 / (1.0 + np.exp(-np.clip(calibrated_logits, -40.0, 40.0))),
            dtype=np.float64,
        ),
    )


def compute_ece(labels: np.ndarray, probabilities: np.ndarray, *, n_bins: int = 10) -> float:
    """Compute Expected Calibration Error across equal-width probability bins."""
    if len(labels) == 0:
        return 0.0
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    total = float(len(labels))
    for idx in range(n_bins):
        low, high = bin_edges[idx], bin_edges[idx + 1]
        mask = (
            (probabilities >= low) & (probabilities <= high)
            if idx == n_bins - 1
            else (probabilities >= low) & (probabilities < high)
        )
        count = int(mask.sum())
        if count == 0:
            continue
        avg_conf = float(probabilities[mask].mean())
        avg_acc = float(labels[mask].mean())
        ece += (count / total) * abs(avg_conf - avg_acc)
    return float(ece)


def _evaluate_slices(
    test_frame: pd.DataFrame,
    probabilities: np.ndarray,
) -> dict[str, dict[str, float]]:
    """Compute ROC-AUC and Brier score across horizon and department slices."""
    slices: dict[str, dict[str, float]] = {}
    if "renewal_horizon_days" in test_frame.columns:
        for horizon, group_idx in test_frame.groupby("renewal_horizon_days").groups.items():
            positions = test_frame.index.get_indexer(group_idx)
            y_slice = test_frame.iloc[positions][TARGET_COLUMN].to_numpy()
            p_slice = probabilities[positions]
            if len(y_slice) >= 20 and len(np.unique(y_slice)) == 2:
                slices[f"horizon_{int(horizon)}d"] = {
                    "rows": float(len(y_slice)),
                    "roc_auc": round(float(roc_auc_score(y_slice, p_slice)), 6),
                    "brier_score": round(float(brier_score_loss(y_slice, p_slice)), 6),
                }
    if "department" in test_frame.columns:
        for dept, group_idx in test_frame.groupby("department").groups.items():
            positions = test_frame.index.get_indexer(group_idx)
            y_slice = test_frame.iloc[positions][TARGET_COLUMN].to_numpy()
            p_slice = probabilities[positions]
            if len(y_slice) >= 20 and len(np.unique(y_slice)) == 2:
                slices[f"dept_{dept!s}"] = {
                    "rows": float(len(y_slice)),
                    "roc_auc": round(float(roc_auc_score(y_slice, p_slice)), 6),
                    "brier_score": round(float(brier_score_loss(y_slice, p_slice)), 6),
                }
    return slices


def evaluate_financial_backtest(
    test_frame: pd.DataFrame,
    probabilities: np.ndarray,
) -> tuple[float | None, int]:
    """Compute realized financial savings rate vs naive 100%-seat renewal."""
    required = {"tenant_id", "vendor_id", "department", "renewal_date", "annual_seat_cost"}
    if not required.issubset(test_frame.columns):
        return None, 0

    working = test_frame.copy()
    working["_prob"] = probabilities
    group_cols = ["tenant_id", "vendor_id", "department", "renewal_date"]
    if "renewal_horizon_days" in working.columns:
        group_cols.append("renewal_horizon_days")

    total_challenger_cost = 0.0
    total_naive_cost = 0.0
    cohort_count = 0
    for _, group in working.groupby(group_cols, dropna=False):
        if len(group) < 2:
            continue
        seat_cost = float(group["annual_seat_cost"].iloc[0] or 0.0)
        if seat_cost <= 0.0:
            continue
        penalty_rate = (
            float(group["trueup_penalty_rate"].iloc[0])
            if "trueup_penalty_rate" in group.columns
            and pd.notna(group["trueup_penalty_rate"].iloc[0])
            else 0.25
        )
        horizon = (
            int(group["renewal_horizon_days"].iloc[0])
            if "renewal_horizon_days" in group.columns
            else 90
        )
        optimization = optimize_commitment(
            group["_prob"].tolist(),
            seat_cost,
            penalty_rate,
            horizon_days=max(horizon, 1),
        )
        actual_retained = int(group[TARGET_COLUMN].sum())
        current_seats = len(group)
        recommended = optimization.recommended_seats
        challenger_trueup = max(actual_retained - recommended, 0) * seat_cost * (1.0 + penalty_rate)
        naive_trueup = max(actual_retained - current_seats, 0) * seat_cost * (1.0 + penalty_rate)
        total_challenger_cost += recommended * seat_cost + challenger_trueup
        total_naive_cost += current_seats * seat_cost + naive_trueup
        cohort_count += 1

    if cohort_count == 0 or total_naive_cost <= 0.0:
        return None, 0
    savings_rate = (total_naive_cost - total_challenger_cost) / total_naive_cost
    return round(float(savings_rate), 6), cohort_count


def _evaluate(
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    train_rows: int,
    validation_rows: int,
    test_rows: int,
    test_frame: pd.DataFrame | None = None,
) -> TrainingMetrics:
    """Calculate the production gate metrics on a held-out test partition."""
    threshold = 0.5
    ece = compute_ece(labels, probabilities)
    slice_metrics = _evaluate_slices(test_frame, probabilities) if test_frame is not None else {}
    savings_rate, backtest_cohorts = (
        evaluate_financial_backtest(test_frame, probabilities)
        if test_frame is not None
        else (None, 0)
    )
    return TrainingMetrics(
        roc_auc=float(roc_auc_score(labels, probabilities)),
        log_loss=float(log_loss(labels, probabilities, labels=[0, 1])),
        brier_score=float(brier_score_loss(labels, probabilities)),
        f1=float(f1_score(labels, probabilities >= threshold, zero_division=0)),
        decision_threshold=threshold,
        train_rows=train_rows,
        validation_rows=validation_rows,
        test_rows=test_rows,
        ece=ece,
        financial_savings_rate=savings_rate,
        backtest_cohorts=backtest_cohorts,
        slice_metrics=slice_metrics,
    )


def compute_baseline_stats(
    train_frame: pd.DataFrame,
    calibrated_test_probabilities: np.ndarray,
    *,
    model_version: str,
    bins: int = 10,
) -> dict[str, Any]:
    """Build numeric feature histograms and score baselines for drift monitoring."""
    feature_stats: dict[str, dict[str, Any]] = {}
    for column in FEATURE_COLUMNS:
        series = pd.to_numeric(train_frame[column], errors="coerce").fillna(0.0).to_numpy(
            dtype=np.float64
        )
        quantiles = np.quantile(series, np.linspace(0.0, 1.0, bins + 1))
        edges = np.unique(quantiles)
        if len(edges) < 2:
            edges = np.array([float(series.min()) - 0.5, float(series.max()) + 0.5])
        counts, bin_edges = np.histogram(series, bins=edges)
        proportions = (counts / max(int(counts.sum()), 1)).tolist()
        sentinel_rate = (
            float(np.mean(series >= 9999.0)) if column == "days_since_last_login" else 0.0
        )
        feature_stats[column] = {
            "mean": round(float(np.mean(series)), 6),
            "std": round(float(np.std(series)), 6),
            "min": round(float(np.min(series)), 6),
            "max": round(float(np.max(series)), 6),
            "sentinel_rate": round(sentinel_rate, 6),
            "bin_edges": [round(float(x), 6) for x in bin_edges],
            "proportions": [round(float(p), 6) for p in proportions],
        }

    score_edges = np.linspace(0.0, 1.0, bins + 1)
    score_counts, _ = np.histogram(
        np.clip(calibrated_test_probabilities, 0.0, 1.0), bins=score_edges
    )
    score_props = (score_counts / max(int(score_counts.sum()), 1)).tolist()

    return {
        "model_version": model_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "row_count": len(train_frame),
        "positive_rate": round(float(train_frame[TARGET_COLUMN].mean()), 6),
        "features": feature_stats,
        "score_distribution": {
            "bin_edges": [round(float(x), 4) for x in score_edges],
            "proportions": [round(float(p), 6) for p in score_props],
        },
    }


def train_challenger(
    frame: pd.DataFrame,
    *,
    random_state: int = 47,
    return_artifacts: bool = False,
) -> (
    tuple[Any, CalibrationParameters, TrainingMetrics, dict[str, Any]]
    | tuple[Any, CalibrationParameters, TrainingMetrics, dict[str, Any], dict[str, Any]]
):
    """Tune and fit a LightGBM challenger with early stopping and calibration."""
    import lightgbm as lgb

    cleaned = _validate_frame(frame)
    train, validation, test = _split_frame(cleaned, random_state)
    train_x, train_y = train[list(FEATURE_COLUMNS)], train[TARGET_COLUMN].to_numpy()
    validation_x = validation[list(FEATURE_COLUMNS)]
    validation_y = validation[TARGET_COLUMN].to_numpy()
    test_x, test_y = test[list(FEATURE_COLUMNS)], test[TARGET_COLUMN].to_numpy()

    search_space = ParameterGrid(
        {
            "learning_rate": [0.025, 0.05],
            "num_leaves": [15, 31],
            "min_child_samples": [20, 40],
            "feature_fraction": [0.8, 1.0],
            "bagging_fraction": [0.8],
        }
    )
    best_model: Any | None = None
    best_parameters: dict[str, Any] = {}
    best_loss = math.inf
    for parameters in search_space:
        model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=1500,
            random_state=random_state,
            n_jobs=-1,
            verbosity=-1,
            bagging_freq=1,
            **parameters,
        )
        model.fit(
            train_x,
            train_y,
            eval_X=validation_x,
            eval_y=validation_y,
            eval_metric="binary_logloss",
            callbacks=[lgb.early_stopping(75, verbose=False), lgb.log_evaluation(0)],
        )
        raw_validation = model.predict_proba(validation_x)[:, 1]
        candidate_loss = float(log_loss(validation_y, raw_validation, labels=[0, 1]))
        if candidate_loss < best_loss:
            best_loss = candidate_loss
            best_model = model
            best_parameters = dict(parameters)

    if best_model is None:
        raise RuntimeError("LightGBM hyperparameter search produced no candidate")
    raw_validation = best_model.predict_proba(validation_x)[:, 1]
    calibration = _fit_calibrator(raw_validation, validation_y)
    raw_test = best_model.predict_proba(test_x)[:, 1]
    calibrated_test = apply_calibration(raw_test, calibration)
    metrics = _evaluate(
        test_y,
        calibrated_test,
        train_rows=len(train),
        validation_rows=len(validation),
        test_rows=len(test),
        test_frame=test,
    )
    best_parameters.update(
        {
            "best_iteration": int(best_model.best_iteration_),
            "validation_log_loss_raw": best_loss,
            "feature_columns": list(FEATURE_COLUMNS),
        }
    )
    if return_artifacts:
        extras = {
            "train_frame": train,
            "calibrated_test_probabilities": calibrated_test,
        }
        return best_model.booster_, calibration, metrics, best_parameters, extras
    return best_model.booster_, calibration, metrics, best_parameters


def _storage_client(config: TrainingConfig) -> Any:
    """Create a GCS client with the same explicit credentials as BigQuery."""
    from google.cloud import storage

    return storage.Client(project=config.project_id)


def load_production_metrics(config: TrainingConfig) -> dict[str, Any] | None:
    """Load the currently promoted champion metrics, returning ``None`` initially."""
    blob = _storage_client(config).bucket(config.ml_bucket).blob("models/latest/metrics.json")
    try:
        parsed = json.loads(blob.download_as_bytes().decode("utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("latest metrics artifact must contain a JSON object")
        return {str(key): value for key, value in parsed.items()}
    except Exception as exc:
        from google.api_core.exceptions import NotFound

        if isinstance(exc, NotFound):
            return None
        raise


def validate_challenger(
    metrics: TrainingMetrics,
    baseline: Mapping[str, Any] | None,
    *,
    brier_score_limit: float = 0.05,
    ece_limit: float = 0.08,
    min_roc_auc: float = 0.65,
    require_positive_backtest: bool = False,
) -> None:
    """Reject a poorly calibrated, AUC-weak, slice-broken, or F1-regressing challenger."""
    failures: list[str] = []
    if metrics.brier_score > brier_score_limit:
        failures.append(f"Brier score {metrics.brier_score:.6f} exceeds {brier_score_limit:.6f}")
    if metrics.ece > ece_limit:
        failures.append(f"ECE {metrics.ece:.6f} exceeds {ece_limit:.6f}")
    if metrics.roc_auc < min_roc_auc:
        failures.append(f"ROC-AUC {metrics.roc_auc:.6f} is below {min_roc_auc:.6f}")

    for slice_name, slice_vals in metrics.slice_metrics.items():
        slice_auc = float(slice_vals.get("roc_auc", 1.0))
        if slice_auc < max(0.55, min_roc_auc - 0.08):
            failures.append(f"Slice {slice_name} ROC-AUC {slice_auc:.6f} is critically low")

    if (
        require_positive_backtest
        and metrics.backtest_cohorts > 0
        and metrics.financial_savings_rate is not None
        and metrics.financial_savings_rate < 0.0
    ):
        failures.append(
            f"Financial backtest savings rate {metrics.financial_savings_rate:.4f} is negative"
        )

    if baseline is not None:
        baseline_f1 = float(baseline.get("f1", 0.0))
        if metrics.f1 < baseline_f1:
            failures.append(f"F1 {metrics.f1:.6f} is lower than champion F1 {baseline_f1:.6f}")
        if "brier_score" in baseline:
            baseline_brier = float(baseline["brier_score"])
            if metrics.brier_score > baseline_brier * 1.10 + 1e-6:
                failures.append(
                    f"Brier score {metrics.brier_score:.6f} regressed "
                    f"vs champion {baseline_brier:.6f}"
                )

    if failures:
        raise ModelRejectedError("; ".join(failures))


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for an artifact file."""
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upload_file(
    config: TrainingConfig,
    source: Path,
    object_name: str,
    *,
    metadata: Mapping[str, str],
    content_type: str,
) -> None:
    """Upload one immutable or promoted artifact with integrity metadata."""
    blob = _storage_client(config).bucket(config.ml_bucket).blob(object_name)
    blob.metadata = dict(metadata)
    blob.upload_from_filename(str(source), content_type=content_type)


def _log_vertex_experiment(
    config: TrainingConfig,
    *,
    version: str,
    artifact_uri: str,
    metrics: TrainingMetrics,
    hyperparameters: Mapping[str, Any],
) -> None:
    """Log training parameters and evaluation metrics to Vertex Experiments."""
    from google.cloud import aiplatform

    aiplatform.init(
        project=config.project_id,
        location=config.region,
        staging_bucket=f"gs://{config.ml_bucket}",
        experiment=config.experiment_name,
    )
    with aiplatform.start_run(run=_vertex_run_id(version)) as run:
        run.log_params(
            {
                key: json.dumps(value) if isinstance(value, (list, dict)) else value
                for key, value in {
                    **hyperparameters,
                    "feature_table": config.feature_table,
                    "tenant_id": config.tenant_id,
                    "artifact_uri": artifact_uri,
                }.items()
            }
        )
        metric_payload: dict[str, float] = {
            "roc_auc": metrics.roc_auc,
            "log_loss": metrics.log_loss,
            "brier_score": metrics.brier_score,
            "f1": metrics.f1,
            "ece": metrics.ece,
        }
        if metrics.financial_savings_rate is not None:
            metric_payload["financial_savings_rate"] = metrics.financial_savings_rate
        run.log_metrics(metric_payload)


def promote_model_version(config: TrainingConfig, version: str) -> dict[str, str]:
    """Promote or roll back ``models/latest/`` to an immutable ``models/<version>/`` prefix."""
    client = _storage_client(config)
    bucket = client.bucket(config.ml_bucket)
    version_prefix = f"models/{version.strip('/')}"
    artifacts = (
        "model.booster",
        "calibration.json",
        "metrics.json",
        "baseline_stats.json",
        "feature_schema.json",
    )
    promoted: list[str] = []
    for name in artifacts:
        source_blob = bucket.blob(f"{version_prefix}/{name}")
        if not source_blob.exists():
            if name in ("baseline_stats.json", "feature_schema.json"):
                continue
            raise FileNotFoundError(f"Missing required artifact gs://{config.ml_bucket}/{version_prefix}/{name}")
        bucket.copy_blob(source_blob, bucket, f"models/latest/{name}")
        promoted.append(name)

    logger.info(
        "seat_model_version_promoted",
        model_version=version,
        ml_bucket=config.ml_bucket,
        artifacts=promoted,
    )
    return {"model_version": version, "artifact_uri": f"gs://{config.ml_bucket}/{version_prefix}/"}


def train_and_publish(
    config: TrainingConfig | None = None,
    *,
    shadow_only: bool = False,
) -> dict[str, Any]:
    """Train, gate, version, log lineage, and promote a model artifact to GCS."""
    resolved = config or TrainingConfig.from_environment()
    version = f"v_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    baseline = load_production_metrics(resolved)
    frame = load_training_frame(resolved)
    trained = train_challenger(
        frame,
        random_state=resolved.random_state,
        return_artifacts=True,
    )
    booster, calibration, metrics, hyperparameters, extras = cast(
        tuple[Any, CalibrationParameters, TrainingMetrics, dict[str, Any], dict[str, Any]],
        trained,
    )
    validate_challenger(
        metrics,
        baseline,
        brier_score_limit=resolved.brier_score_limit,
        ece_limit=resolved.ece_limit,
        min_roc_auc=resolved.min_roc_auc,
        require_positive_backtest=True,
    )
    baseline_stats = compute_baseline_stats(
        extras["train_frame"],
        extras["calibrated_test_probabilities"],
        model_version=version,
    )
    feature_schema = {
        "model_version": version,
        "feature_columns": list(FEATURE_COLUMNS),
        "target_column": TARGET_COLUMN,
    }

    with tempfile.TemporaryDirectory(prefix="zellovest-seat-model-") as directory:
        output_dir = Path(directory)
        model_path = output_dir / "model.booster"
        calibration_path = output_dir / "calibration.json"
        metrics_path = output_dir / "metrics.json"
        baseline_path = output_dir / "baseline_stats.json"
        schema_path = output_dir / "feature_schema.json"
        booster.save_model(str(model_path))
        calibration_path.write_text(
            json.dumps(asdict(calibration), indent=2, sort_keys=True), encoding="utf-8"
        )
        metrics_path.write_text(
            json.dumps(asdict(metrics), indent=2, sort_keys=True), encoding="utf-8"
        )
        baseline_path.write_text(
            json.dumps(baseline_stats, indent=2, sort_keys=True), encoding="utf-8"
        )
        schema_path.write_text(
            json.dumps(feature_schema, indent=2, sort_keys=True), encoding="utf-8"
        )
        model_sha = _sha256(model_path)
        metadata = {"sha256": model_sha, "model_version": version}
        version_prefix = f"models/{version}"
        artifact_specs: Sequence[tuple[Path, str, str]] = (
            (model_path, "model.booster", "application/octet-stream"),
            (calibration_path, "calibration.json", "application/json"),
            (metrics_path, "metrics.json", "application/json"),
            (baseline_path, "baseline_stats.json", "application/json"),
            (schema_path, "feature_schema.json", "application/json"),
        )
        for path, name, content_type in artifact_specs:
            _upload_file(
                resolved,
                path,
                f"{version_prefix}/{name}",
                metadata=metadata,
                content_type=content_type,
            )

        artifact_uri = f"gs://{resolved.ml_bucket}/{version_prefix}/"
        _log_vertex_experiment(
            resolved,
            version=version,
            artifact_uri=artifact_uri,
            metrics=metrics,
            hyperparameters=hyperparameters,
        )

        if not shadow_only:
            # Promote only after validation, artifact upload, and experiment logging succeed.
            for path, name, content_type in artifact_specs:
                _upload_file(
                    resolved,
                    path,
                    f"models/latest/{name}",
                    metadata=metadata,
                    content_type=content_type,
                )

    result = {
        "status": "shadow" if shadow_only else "approved",
        "model_version": version,
        "artifact_uri": artifact_uri,
        "metrics": asdict(metrics),
        "hyperparameters": hyperparameters,
    }
    event_name = "seat_model_promoted" if not shadow_only else "seat_model_shadow_published"
    logger.info(event_name, **result)
    return result


def _parse_args() -> argparse.Namespace:
    """Parse the custom-training container command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-table",
        help="Optional fully-qualified BigQuery Gold feature table override.",
    )
    parser.add_argument("--tenant-id", default="", help="Tenant whose labeled rows are used.")
    parser.add_argument(
        "--shadow-only",
        action="store_true",
        help="Upload versioned challenger artifacts without overwriting models/latest.",
    )
    return parser.parse_args()


def main() -> None:
    """Run one training and promotion job from a Vertex custom container."""
    args = _parse_args()
    config = TrainingConfig.from_environment()
    if args.feature_table:
        config = TrainingConfig(**{**asdict(config), "feature_table": args.feature_table})
    config = TrainingConfig(**{**asdict(config), "tenant_id": args.tenant_id})
    train_and_publish(config, shadow_only=args.shadow_only)


if __name__ == "__main__":
    main()
