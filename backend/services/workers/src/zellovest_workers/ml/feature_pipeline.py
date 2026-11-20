"""BigQuery Bronze-to-Gold feature refresh for seat forecasting."""

from __future__ import annotations

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
class FeaturePipelineConfig:
    """Configuration for an ELT feature refresh."""

    project_id: str
    tenant_id: str
    gcs_raw_bucket: str
    bronze_dataset: str
    silver_dataset: str
    gold_dataset: str
    bq_location: str
    default_trueup_penalty_rate: float

    @classmethod
    def from_environment(cls, *, tenant_id: str | None = None) -> FeaturePipelineConfig:
        """Load feature pipeline settings from application environment."""
        settings = MLRuntimeSettings()
        resolved_tenant = str(tenant_id or os.getenv("TENANT_ID") or "").strip()
        required = {
            "GOOGLE_CLOUD_PROJECT": settings.google_cloud_project,
            "GCS_RAW_BUCKET": settings.gcs_raw_bucket,
            "TENANT_ID": resolved_tenant,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"missing required pipeline settings: {', '.join(missing)}")
        return cls(
            project_id=settings.google_cloud_project,
            tenant_id=resolved_tenant,
            gcs_raw_bucket=settings.gcs_raw_bucket.removeprefix("gs://").rstrip("/"),
            bronze_dataset=settings.bigquery_bronze_dataset,
            silver_dataset=settings.bigquery_silver_dataset,
            gold_dataset=settings.bigquery_gold_dataset,
            bq_location=os.getenv("BIGQUERY_LOCATION", "US"),
            default_trueup_penalty_rate=settings.seat_default_trueup_penalty_rate,
        )

    def template_values(self) -> dict[str, str]:
        """Return SQL template values for this tenant deployment."""
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
    """Render a checked SQL template and reject unresolved placeholders."""
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    if "{{" in rendered or "}}" in rendered:
        unresolved = sorted(
            part.split("}}", 1)[0] for part in rendered.split("{{")[1:] if "}}" in part
        )
        raise ValueError(f"unresolved SQL template placeholders: {unresolved}")
    return rendered


def run_feature_pipeline(config: FeaturePipelineConfig) -> list[str]:
    """Execute ordered BigQuery Bronze-to-Gold transformations."""
    from google.cloud import bigquery

    client = bigquery.Client(project=config.project_id, location=config.bq_location)
    completed: list[str] = []
    for filename in SQL_FILES:
        statement = render_sql(
            (SQL_DIRECTORY / filename).read_text(encoding="utf-8"),
            config.template_values(),
        )
        logger.info("seat_feature_sql_started", script=filename, tenant_id=config.tenant_id)
        client.query(statement).result()
        completed.append(filename)
        logger.info("seat_feature_sql_completed", script=filename, tenant_id=config.tenant_id)
    return completed


def scheduled_feature_refresh(request: Any) -> tuple[str, int, dict[str, str]]:
    """HTTP entry point for an authenticated Scheduler-triggered ELT refresh."""
    payload = request.get_json(silent=True) or {}
    tenant_id = str(payload.get("tenant_id") or os.getenv("TENANT_ID", ""))
    completed = run_feature_pipeline(
        FeaturePipelineConfig.from_environment(tenant_id=tenant_id)
    )
    result = {"status": "completed", "tenant_id": tenant_id, "completed_sql_scripts": completed}
    return json.dumps(result), 200, {"Content-Type": "application/json"}
