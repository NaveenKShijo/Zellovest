"""Scheduled BigQuery ELT and Vertex custom-training pipeline launcher.

Cloud Scheduler can invoke :func:`scheduled_training` through an authenticated
Cloud Function/Cloud Run service. The handler refreshes Bronze/Silver/Gold
tables and submits an ephemeral Vertex AI Custom Training job; it never creates
an always-on prediction endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zellovest_shared.config import MLRuntimeSettings
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
SQL_DIRECTORY = Path(__file__).resolve().parent / "sql"
SQL_FILES = (
    "01_bronze_okta_logs.sql",
    "02_silver_user_activity.sql",
    "03_gold_seat_features.sql",
)


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Configuration for ELT rendering and Vertex job submission."""

    project_id: str
    tenant_id: str
    gcs_raw_bucket: str
    gcs_ml_bucket: str
    bronze_dataset: str
    silver_dataset: str
    gold_dataset: str
    bq_location: str
    vertex_region: str
    training_image_uri: str
    default_trueup_penalty_rate: float
    machine_type: str = "n1-standard-8"

    @classmethod
    def from_environment(cls, *, tenant_id: str | None = None) -> PipelineConfig:
        """Load pipeline configuration from the shared ``.env`` settings."""
        settings = MLRuntimeSettings()
        resolved_tenant = str(tenant_id or os.getenv("TENANT_ID") or "").strip()
        required = {
            "GOOGLE_CLOUD_PROJECT": settings.google_cloud_project,
            "GCS_RAW_BUCKET": settings.gcs_raw_bucket,
            "GCS_ML_BUCKET": settings.gcs_ml_bucket,
            "VERTEX_TRAINING_IMAGE_URI": settings.vertex_training_image_uri,
            "TENANT_ID": resolved_tenant,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"missing required pipeline settings: {', '.join(missing)}")
        return cls(
            project_id=settings.google_cloud_project,
            tenant_id=resolved_tenant,
            gcs_raw_bucket=settings.gcs_raw_bucket.removeprefix("gs://").rstrip("/"),
            gcs_ml_bucket=settings.gcs_ml_bucket.removeprefix("gs://").rstrip("/"),
            bronze_dataset=settings.bigquery_bronze_dataset,
            silver_dataset=settings.bigquery_silver_dataset,
            gold_dataset=settings.bigquery_gold_dataset,
            bq_location=os.getenv("BIGQUERY_LOCATION", "US"),
            vertex_region=settings.vertex_ai_region,
            training_image_uri=settings.vertex_training_image_uri,
            default_trueup_penalty_rate=settings.seat_default_trueup_penalty_rate,
            machine_type=os.getenv("VERTEX_TRAINING_MACHINE_TYPE", "n1-standard-8"),
        )

    def template_values(self) -> dict[str, str]:
        """Return SQL placeholder values for this deployment."""
        return {
            "PROJECT_ID": self.project_id,
            "TENANT_ID": self.tenant_id,
            "GCS_RAW_BUCKET": self.gcs_raw_bucket,
            "BRONZE_DATASET": self.bronze_dataset,
            "SILVER_DATASET": self.silver_dataset,
            "GOLD_DATASET": self.gold_dataset,
            "BQ_LOCATION": self.bq_location,
            "DEFAULT_TRUEUP_PENALTY_RATE": str(self.default_trueup_penalty_rate),
        }


def render_sql(template: str, values: Mapping[str, str]) -> str:
    """Render a checked SQL template without allowing unresolved placeholders."""
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    if "{{" in rendered or "}}" in rendered:
        unresolved = sorted(
            part.split("}}", 1)[0] for part in rendered.split("{{")[1:] if "}}" in part
        )
        raise ValueError(f"unresolved SQL template placeholders: {unresolved}")
    return rendered


def run_feature_pipeline(config: PipelineConfig) -> list[str]:
    """Execute the ordered BigQuery Bronze-to-Gold transformation scripts."""
    from google.cloud import bigquery

    client = bigquery.Client(
        project=config.project_id,
        location=config.bq_location,
    )
    completed: list[str] = []
    for filename in SQL_FILES:
        path = SQL_DIRECTORY / filename
        statement = render_sql(
            path.read_text(encoding="utf-8"),
            config.template_values(),
        )
        logger.info("seat_feature_sql_started", script=filename, tenant_id=config.tenant_id)
        client.query(statement).result()
        completed.append(filename)
        logger.info("seat_feature_sql_completed", script=filename, tenant_id=config.tenant_id)
    return completed


def submit_training_job(config: PipelineConfig, *, sync: bool = False) -> str:
    """Submit an ephemeral Vertex custom-container training job."""
    from google.cloud import aiplatform

    aiplatform.init(
        project=config.project_id,
        location=config.vertex_region,
        staging_bucket=f"gs://{config.gcs_ml_bucket}",
    )
    training_job = aiplatform.CustomContainerTrainingJob(
        display_name=f"seat-retention-{config.tenant_id}",
        container_uri=config.training_image_uri,
        command=["python", "-m", "zellovest_workers.ml.train_vertex"],
    )
    feature_table = f"{config.project_id}.{config.gold_dataset}.gold_seat_features"
    training_job.run(
        args=["--feature-table", feature_table],
        environment_variables={
            "GOOGLE_CLOUD_PROJECT": config.project_id,
            "GCS_ML_BUCKET": config.gcs_ml_bucket,
            "VERTEX_AI_REGION": config.vertex_region,
            "VERTEX_MODEL_SERVING_IMAGE_URI": os.getenv(
                "VERTEX_MODEL_SERVING_IMAGE_URI", ""
            ),
        },
        replica_count=1,
        machine_type=config.machine_type,
        base_output_dir=f"gs://{config.gcs_ml_bucket}/vertex-output/{config.tenant_id}",
        sync=sync,
    )
    resource_name = str(training_job.resource_name)
    logger.info(
        "seat_training_job_submitted",
        tenant_id=config.tenant_id,
        resource_name=resource_name,
    )
    return resource_name


def run_pipeline(config: PipelineConfig, *, sync_training: bool = False) -> dict[str, Any]:
    """Refresh point-in-time features and submit the model training job."""
    scripts = run_feature_pipeline(config)
    resource_name = submit_training_job(config, sync=sync_training)
    return {
        "status": "submitted" if not sync_training else "completed",
        "tenant_id": config.tenant_id,
        "completed_sql_scripts": scripts,
        "training_job": resource_name,
    }


def scheduled_training(request: Any) -> tuple[str, int, dict[str, str]]:
    """HTTP Cloud Function entry point intended for an OIDC Cloud Scheduler call."""
    payload = request.get_json(silent=True) or {}
    tenant_id = str(payload.get("tenant_id") or os.getenv("TENANT_ID", ""))
    result = run_pipeline(PipelineConfig.from_environment(tenant_id=tenant_id))
    return json.dumps(result), 202, {"Content-Type": "application/json"}


def _parse_args() -> argparse.Namespace:
    """Parse local/CI pipeline launcher arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID"))
    parser.add_argument(
        "--sync-training",
        action="store_true",
        help="Wait for Vertex training; scheduler invocations should omit this.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the ELT and training launcher from a command line."""
    args = _parse_args()
    result = run_pipeline(
        PipelineConfig.from_environment(tenant_id=args.tenant_id),
        sync_training=args.sync_training,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
