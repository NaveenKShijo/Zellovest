"""Production data-drift, score-drift, and continuous-training policy logic."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from zellovest_shared.config import Settings, get_settings
from zellovest_shared.db.intelligence import MLDriftReport
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_writer import make_storage_client

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DriftAnalysisResult:
    """Computed feature and prediction-score drift summary."""

    tenant_id: str
    model_version: str
    baseline_version: str
    reference_date: date
    sample_size: int
    max_psi: float
    score_psi: float
    max_sentinel_delta: float
    severity: str
    drifted_features: tuple[str, ...]
    feature_metrics: dict[str, dict[str, float]]
    retrain_recommended: bool

    def to_orm(
        self,
        *,
        retrain_triggered: bool = False,
        trigger_reason: str | None = None,
        training_job_uri: str | None = None,
    ) -> MLDriftReport:
        """Convert this analysis into an immutable PostgreSQL ``MLDriftReport`` row."""
        return MLDriftReport(
            tenant_id=self.tenant_id,
            model_version=self.model_version,
            baseline_version=self.baseline_version,
            reference_date=self.reference_date,
            sample_size=self.sample_size,
            max_psi=self.max_psi,
            score_psi=self.score_psi,
            max_sentinel_delta=self.max_sentinel_delta,
            severity=self.severity,
            drifted_features=list(self.drifted_features),
            feature_metrics=self.feature_metrics,
            retrain_recommended=self.retrain_recommended,
            retrain_triggered=retrain_triggered,
            trigger_reason=trigger_reason,
            training_job_uri=training_job_uri,
        )


@dataclass(frozen=True, slots=True)
class RetrainingDecision:
    """Policy decision determining whether automated Vertex retraining should run."""

    should_retrain: bool
    reasons: tuple[str, ...]


def compute_psi(
    expected_proportions: Sequence[float],
    bin_edges: Sequence[float],
    actual_values: np.ndarray,
    *,
    epsilon: float = 1e-4,
) -> float:
    """Compute Population Stability Index between a training histogram and live values."""
    if len(actual_values) == 0 or len(bin_edges) < 2:
        return 0.0
    edges = np.asarray(bin_edges, dtype=np.float64)
    # Widen outer edges to +/- inf so out-of-range live values fall into boundary bins.
    bounded_edges = edges.copy()
    bounded_edges[0] = -np.inf
    bounded_edges[-1] = np.inf
    counts, _ = np.histogram(actual_values, bins=bounded_edges)
    actual_props = counts / max(int(counts.sum()), 1)
    expected = np.asarray(expected_proportions, dtype=np.float64)
    if len(expected) != len(actual_props):
        return 0.0

    expected_safe = np.clip(expected, epsilon, None)
    actual_safe = np.clip(actual_props, epsilon, None)
    expected_safe = expected_safe / expected_safe.sum()
    actual_safe = actual_safe / actual_safe.sum()
    psi = float(np.sum((actual_safe - expected_safe) * np.log(actual_safe / expected_safe)))
    return max(0.0, round(psi, 6))


def analyze_feature_drift(
    *,
    baseline_stats: Mapping[str, Any],
    live_frame: pd.DataFrame,
    tenant_id: str,
    model_version: str,
    reference_date: date | None = None,
    psi_warning: float = 0.10,
    psi_critical: float = 0.25,
    sentinel_delta_critical: float = 0.15,
) -> DriftAnalysisResult:
    """Compare live inference features and scores against training baselines."""
    ref_date = reference_date or datetime.now(UTC).date()
    baseline_version = str(baseline_stats.get("model_version") or model_version)
    features_baseline: Mapping[str, Any] = baseline_stats.get("features") or {}
    if live_frame.empty:
        return DriftAnalysisResult(
            tenant_id=tenant_id,
            model_version=model_version,
            baseline_version=baseline_version,
            reference_date=ref_date,
            sample_size=0,
            max_psi=0.0,
            score_psi=0.0,
            max_sentinel_delta=0.0,
            severity="healthy",
            drifted_features=(),
            feature_metrics={},
            retrain_recommended=False,
        )

    feature_metrics: dict[str, dict[str, float]] = {}
    drifted: list[str] = []
    max_psi = 0.0
    max_sentinel_delta = 0.0

    for feature_name, stats in features_baseline.items():
        if feature_name not in live_frame.columns:
            continue
        values = pd.to_numeric(live_frame[feature_name], errors="coerce").fillna(0.0).to_numpy(
            dtype=np.float64
        )
        psi = compute_psi(
            stats.get("proportions", []),
            stats.get("bin_edges", []),
            values,
        )
        live_mean = float(np.mean(values))
        baseline_mean = float(stats.get("mean", 0.0))
        sentinel_delta = 0.0
        if feature_name == "days_since_last_login":
            live_sentinel = float(np.mean(values >= 9999.0))
            base_sentinel = float(stats.get("sentinel_rate", 0.0))
            sentinel_delta = max(0.0, round(live_sentinel - base_sentinel, 6))
            max_sentinel_delta = max(max_sentinel_delta, sentinel_delta)

        max_psi = max(max_psi, psi)
        if psi >= psi_warning or sentinel_delta >= sentinel_delta_critical:
            drifted.append(feature_name)

        feature_metrics[feature_name] = {
            "psi": psi,
            "live_mean": round(live_mean, 6),
            "baseline_mean": round(baseline_mean, 6),
            "sentinel_delta": sentinel_delta,
        }

    score_psi = 0.0
    score_baseline = baseline_stats.get("score_distribution") or {}
    if "calibrated_probability" in live_frame.columns and score_baseline:
        probs = (
            pd.to_numeric(live_frame["calibrated_probability"], errors="coerce")
            .dropna()
            .to_numpy(dtype=np.float64)
        )
        score_psi = compute_psi(
            score_baseline.get("proportions", []),
            score_baseline.get("bin_edges", []),
            probs,
        )

    if (
        max_psi >= psi_critical
        or score_psi >= psi_critical
        or max_sentinel_delta >= sentinel_delta_critical
    ):
        severity = "critical"
    elif max_psi >= psi_warning or score_psi >= psi_warning:
        severity = "warning"
    else:
        severity = "healthy"

    retrain_recommended = severity == "critical"
    return DriftAnalysisResult(
        tenant_id=tenant_id,
        model_version=model_version,
        baseline_version=baseline_version,
        reference_date=ref_date,
        sample_size=len(live_frame),
        max_psi=round(max_psi, 6),
        score_psi=round(score_psi, 6),
        max_sentinel_delta=round(max_sentinel_delta, 6),
        severity=severity,
        drifted_features=tuple(sorted(drifted)),
        feature_metrics=feature_metrics,
        retrain_recommended=retrain_recommended,
    )


def evaluate_retraining_triggers(
    *,
    drift: DriftAnalysisResult | None = None,
    online_brier_score: float | None = None,
    online_ece: float | None = None,
    new_labeled_rows: int = 0,
    days_since_last_train: int = 0,
    online_brier_threshold: float = 0.08,
    online_ece_threshold: float = 0.06,
    min_new_labels: int = 500,
    cadence_days: int = 30,
) -> RetrainingDecision:
    """Determine whether performance decay, drift, or data volume justifies retraining."""
    reasons: list[str] = []
    if drift is not None and drift.severity == "critical":
        if drift.max_sentinel_delta >= 0.15:
            reasons.append(
                f"upstream_sentinel_spike(delta={drift.max_sentinel_delta:.3f})"
            )
        else:
            reasons.append(
                f"critical_drift(max_psi={drift.max_psi:.3f},score_psi={drift.score_psi:.3f})"
            )

    if online_brier_score is not None and online_brier_score > online_brier_threshold:
        reasons.append(
            f"online_brier_degraded({online_brier_score:.4f}>{online_brier_threshold:.4f})"
        )
    if online_ece is not None and online_ece > online_ece_threshold:
        reasons.append(
            f"online_ece_degraded({online_ece:.4f}>{online_ece_threshold:.4f})"
        )
    if new_labeled_rows >= min_new_labels and days_since_last_train >= cadence_days:
        reasons.append(
            f"scheduled_volume_refresh(new_labels={new_labeled_rows},age_days={days_since_last_train})"
        )

    return RetrainingDecision(
        should_retrain=bool(reasons),
        reasons=tuple(reasons),
    )


def load_baseline_stats(settings: Settings | None = None) -> dict[str, Any] | None:
    """Download ``models/latest/baseline_stats.json`` from the configured ML bucket."""
    resolved = settings or get_settings()
    configured_bucket = (
        resolved.gcs_ml_synth if resolved.seat_synthetic_mode else resolved.gcs_ml_bucket
    )
    bucket_name = configured_bucket.removeprefix("gs://").rstrip("/")
    if not bucket_name:
        return None
    client = make_storage_client(resolved.google_cloud_project or None)
    blob = client.bucket(bucket_name).blob("models/latest/baseline_stats.json")
    try:
        parsed = json.loads(blob.download_as_bytes().decode("utf-8"))
        return dict(parsed) if isinstance(parsed, dict) else None
    except Exception as exc:
        from google.api_core.exceptions import NotFound

        if isinstance(exc, NotFound):
            return None
        raise


def persist_drift_report(
    session: Session,
    analysis: DriftAnalysisResult,
    *,
    retrain_triggered: bool = False,
    trigger_reason: str | None = None,
    training_job_uri: str | None = None,
) -> uuid.UUID:
    """Persist one ``MLDriftReport`` row to PostgreSQL."""
    row = analysis.to_orm(
        retrain_triggered=retrain_triggered,
        trigger_reason=trigger_reason,
        training_job_uri=training_job_uri,
    )
    session.add(row)
    session.commit()
    return row.id
