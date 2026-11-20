"""Vertex AI training entry point for calibrated LightGBM seat retention.

The module reads the Gold feature table through BigQuery's Storage Read API,
tunes a LightGBM classifier with early stopping, calibrates probabilities with
Platt scaling, enforces the champion/challenger gate, and promotes approved
artifacts to versioned and ``latest`` GCS prefixes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, f1_score, log_loss, roc_auc_score
from sklearn.model_selection import ParameterGrid, train_test_split
from zellovest_shared.config import MLRuntimeSettings
from zellovest_shared.logging_conf import get_logger

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
    "department_engineering",
    "department_sales",
    "department_marketing",
    "department_finance",
    "department_hr",
    "department_operations",
    "department_other",
)
TARGET_COLUMN = "retained_label"


class ModelRejectedError(RuntimeError):
    """Raised when a challenger fails a mandatory production quality gate."""


@dataclass(frozen=True, slots=True)
class CalibrationParameters:
    """Platt-scaling coefficients applied to model probability logits."""

    coefficient: float
    intercept: float
    epsilon: float = 1e-7


@dataclass(frozen=True, slots=True)
class TrainingMetrics:
    """Held-out probability and classification quality metrics."""

    roc_auc: float
    log_loss: float
    brier_score: float
    f1: float
    decision_threshold: float
    train_rows: int
    validation_rows: int
    test_rows: int


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Cloud locations and quality limits for one training invocation."""

    project_id: str
    region: str
    ml_bucket: str
    feature_table: str
    brier_score_limit: float = 0.05
    experiment_name: str = "seat-retention-training"
    random_state: int = 47

    @classmethod
    def from_environment(cls) -> TrainingConfig:
        """Load GCP and model settings from ``backend/.env`` and the process env."""
        settings = MLRuntimeSettings()
        project_id = settings.google_cloud_project.strip()
        ml_bucket = settings.gcs_ml_bucket.strip()
        if not project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for model training")
        if not ml_bucket:
            raise ValueError("GCS_ML_BUCKET is required for model training")
        feature_table = (
            f"{project_id}.{settings.bigquery_gold_dataset}.{settings.bigquery_seat_features_table}"
        )
        return cls(
            project_id=project_id,
            region=settings.vertex_ai_region,
            ml_bucket=ml_bucket.removeprefix("gs://").rstrip("/"),
            feature_table=feature_table,
            brier_score_limit=float(os.getenv("SEAT_MODEL_BRIER_LIMIT", "0.05")),
            experiment_name=os.getenv("VERTEX_SEAT_EXPERIMENT", "seat-retention-training"),
        )


def load_training_frame(config: TrainingConfig) -> pd.DataFrame:
    """Read labeled features using the BigQuery Storage Read API."""
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id)
    columns = ", ".join([*FEATURE_COLUMNS, TARGET_COLUMN, "feature_as_of_date"])
    query = f"""
        SELECT {columns}
        FROM `{config.feature_table}`
        WHERE {TARGET_COLUMN} IS NOT NULL
    """
    logger.info("seat_training_bigquery_read_started", table=config.feature_table)
    frame = client.query(query).to_dataframe(
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


def _split_frame(
    frame: pd.DataFrame,
    random_state: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create train/calibration/test partitions, preferring temporal ordering."""
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
        if all(
            len(partition) >= 2 and partition[TARGET_COLUMN].nunique() == 2
            for partition in partitions
        ):
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


def _evaluate(
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    train_rows: int,
    validation_rows: int,
    test_rows: int,
) -> TrainingMetrics:
    """Calculate the production gate metrics on a held-out test partition."""
    threshold = 0.5
    return TrainingMetrics(
        roc_auc=float(roc_auc_score(labels, probabilities)),
        log_loss=float(log_loss(labels, probabilities, labels=[0, 1])),
        brier_score=float(brier_score_loss(labels, probabilities)),
        f1=float(f1_score(labels, probabilities >= threshold, zero_division=0)),
        decision_threshold=threshold,
        train_rows=train_rows,
        validation_rows=validation_rows,
        test_rows=test_rows,
    )


def train_challenger(
    frame: pd.DataFrame,
    *,
    random_state: int = 47,
) -> tuple[Any, CalibrationParameters, TrainingMetrics, dict[str, Any]]:
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
    )
    best_parameters.update(
        {
            "best_iteration": int(best_model.best_iteration_),
            "validation_log_loss_raw": best_loss,
            "feature_columns": list(FEATURE_COLUMNS),
        }
    )
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
) -> None:
    """Reject a poorly calibrated or F1-regressing challenger."""
    failures: list[str] = []
    if metrics.brier_score > brier_score_limit:
        failures.append(f"Brier score {metrics.brier_score:.6f} exceeds {brier_score_limit:.6f}")
    if baseline is not None:
        baseline_f1 = float(baseline.get("f1", 0.0))
        if metrics.f1 < baseline_f1:
            failures.append(f"F1 {metrics.f1:.6f} is lower than champion F1 {baseline_f1:.6f}")
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
    with aiplatform.start_run(run=version) as run:
        run.log_params(
            {
                key: json.dumps(value) if isinstance(value, (list, dict)) else value
                for key, value in hyperparameters.items()
            }
        )
        run.log_metrics(
            {
                "roc_auc": metrics.roc_auc,
                "log_loss": metrics.log_loss,
                "brier_score": metrics.brier_score,
                "f1": metrics.f1,
            }
        )


def train_and_publish(config: TrainingConfig | None = None) -> dict[str, Any]:
    """Train, gate, version, log lineage, and promote a model artifact to GCS."""
    resolved = config or TrainingConfig.from_environment()
    version = f"v_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    baseline = load_production_metrics(resolved)
    frame = load_training_frame(resolved)
    booster, calibration, metrics, hyperparameters = train_challenger(
        frame,
        random_state=resolved.random_state,
    )
    validate_challenger(
        metrics,
        baseline,
        brier_score_limit=resolved.brier_score_limit,
    )

    with tempfile.TemporaryDirectory(prefix="zellovest-seat-model-") as directory:
        output_dir = Path(directory)
        model_path = output_dir / "model.booster"
        calibration_path = output_dir / "calibration.json"
        metrics_path = output_dir / "metrics.json"
        booster.save_model(str(model_path))
        calibration_path.write_text(
            json.dumps(asdict(calibration), indent=2, sort_keys=True), encoding="utf-8"
        )
        metrics_path.write_text(
            json.dumps(asdict(metrics), indent=2, sort_keys=True), encoding="utf-8"
        )
        model_sha = _sha256(model_path)
        metadata = {"sha256": model_sha, "model_version": version}
        version_prefix = f"models/{version}"
        for path, name, content_type in (
            (model_path, "model.booster", "application/octet-stream"),
            (calibration_path, "calibration.json", "application/json"),
            (metrics_path, "metrics.json", "application/json"),
        ):
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

        # Promote only after validation, artifact upload, and experiment logging succeed.
        for path, name, content_type in (
            (model_path, "model.booster", "application/octet-stream"),
            (calibration_path, "calibration.json", "application/json"),
            (metrics_path, "metrics.json", "application/json"),
        ):
            _upload_file(
                resolved,
                path,
                f"models/latest/{name}",
                metadata=metadata,
                content_type=content_type,
            )

    result = {
        "status": "approved",
        "model_version": version,
        "artifact_uri": artifact_uri,
        "metrics": asdict(metrics),
        "hyperparameters": hyperparameters,
    }
    logger.info("seat_model_promoted", **result)
    return result


def _parse_args() -> argparse.Namespace:
    """Parse the custom-training container command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--feature-table",
        help="Optional fully-qualified BigQuery Gold feature table override.",
    )
    return parser.parse_args()


def main() -> None:
    """Run one training and promotion job from a Vertex custom container."""
    args = _parse_args()
    config = TrainingConfig.from_environment()
    if args.feature_table:
        config = TrainingConfig(**{**asdict(config), "feature_table": args.feature_table})
    train_and_publish(config)


if __name__ == "__main__":
    main()
