"""Refresh features and submit an explicitly requested Vertex AI training job."""

from __future__ import annotations

import argparse
import os
from typing import Any

from zellovest_shared.config import MLRuntimeSettings
from zellovest_shared.logging_conf import get_logger

from zellovest_workers.ml.feature_pipeline import FeaturePipelineConfig, run_feature_pipeline

logger = get_logger(__name__)


def submit_vertex_training(tenant_id: str, feature_table: str | None = None) -> str:
    """Submit one custom-container training job to Vertex AI."""
    settings = MLRuntimeSettings()
    project_id = settings.google_cloud_project.strip()
    synthetic = settings.seat_synthetic_mode
    configured_bucket = settings.gcs_ml_synth if synthetic else settings.gcs_ml_bucket
    bucket = configured_bucket.removeprefix("gs://").rstrip("/")
    image_uri = settings.vertex_training_image_uri.strip()
    if not project_id or not bucket or not image_uri:
        raise ValueError(
            "GOOGLE_CLOUD_PROJECT, the configured model bucket, and "
            "VERTEX_TRAINING_IMAGE_URI are required"
        )

    from google.cloud import aiplatform

    aiplatform.init(
        project=project_id,
        location=settings.vertex_ai_region,
        staging_bucket=f"gs://{bucket}",
    )
    training_job = aiplatform.CustomJob(
        display_name=f"seat-retention-{tenant_id}",
        worker_pool_specs=[{
            "machine_spec": {
                "machine_type": os.getenv("VERTEX_TRAINING_MACHINE_TYPE", "n1-standard-8"),
            },
            "replica_count": 1,
            "container_spec": {
                "image_uri": image_uri,
                "command": ["python", "-m", "zellovest_workers.ml.train_vertex"],
                "args": [
                    "--feature-table",
                    feature_table
                    or f"{project_id}.{settings.bigquery_gold_dataset}.gold_seat_features",
                    "--tenant-id",
                    tenant_id,
                ],
                "env": [
                    {"name": "GOOGLE_CLOUD_PROJECT", "value": project_id},
                    {"name": "GCS_ML_BUCKET", "value": bucket},
                    {"name": "GCS_ML_SYNTH", "value": bucket if synthetic else ""},
                    {"name": "SEAT_SYNTHETIC_MODE", "value": str(synthetic).lower()},
                    {"name": "VERTEX_AI_REGION", "value": settings.vertex_ai_region},
                ],
            },
        }],
        base_output_dir=f"gs://{bucket}/vertex-output/{tenant_id}",
    )
    training_job.submit(service_account=os.getenv("GCP_SERVICE_ACCOUNT") or None)
    resource_name = str(training_job.resource_name)
    logger.info(
        "seat_training_job_submitted",
        tenant_id=tenant_id,
        resource_name=resource_name,
        image_uri=image_uri,
    )
    return resource_name


def run_training(tenant_id: str) -> dict[str, Any]:
    """Refresh BigQuery features and start one Vertex training job."""
    feature_config = FeaturePipelineConfig.from_environment(tenant_id=tenant_id)
    completed = run_feature_pipeline(feature_config)
    feature_table = None
    snapshot_id = os.getenv("SEAT_FEATURE_SNAPSHOT_ID", "")
    if snapshot_id:
        if not snapshot_id.replace("_", "").isalnum():
            raise ValueError(
                "SEAT_FEATURE_SNAPSHOT_ID must contain only letters, digits and underscores"
            )
        from google.cloud import bigquery

        feature_table = (
            f"{feature_config.project_id}.{feature_config.gold_dataset}.snapshot_{snapshot_id}"
        )
        source = f"{feature_config.project_id}.{feature_config.gold_dataset}.gold_seat_features"
        client = bigquery.Client(
            project=feature_config.project_id, location=feature_config.bq_location
        )
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("tenant_id", "STRING", tenant_id)
        ])
        client.query(
            f"CREATE TABLE `{feature_table}` AS "
            f"SELECT * FROM `{source}` WHERE tenant_id = @tenant_id",
            job_config=job_config,
        ).result()
        logger.info("seat_feature_snapshot_created", table=feature_table, tenant_id=tenant_id)
    resource_name = submit_vertex_training(tenant_id, feature_table)
    return {"tenant_id": tenant_id, "features_refreshed": completed, "training_job": resource_name}


def main() -> None:
    """Run the manually requested Vertex training operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID"), required=False)
    args = parser.parse_args()
    tenant_id = str(args.tenant_id or "").strip()
    if not tenant_id:
        parser.error("--tenant-id or TENANT_ID is required")
    run_training(tenant_id)


if __name__ == "__main__":
    main()
