"""GCS bronze-lake writer for ingestion workers.

Streams source-API records as gzipped JSONL into the tenant's GCS raw
bucket. Replaces the legacy S3 bronze lake: all cloud storage is Google
Cloud Storage (GCS) per the GCP-only deployment policy.

Key layout embeds the sync ticket so re-runs never overwrite history::

    raw/{entity_folder}/sync={sync_id}/{suffix}.jsonl.gz
"""

from __future__ import annotations

import gzip
import json
from typing import Any

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

ENTITY_FOLDERS: dict[str, str] = {
    "card_transactions": "ramp_card_transactions",
    "bills": "ramp_bills",
    "events": "events",
    "invoices": "invoices",
    "contracts": "contracts",
    "documents": "documents",
    "ramp_users": "ramp_users",
    "ramp_departments": "ramp_departments",
    "ramp_merchants": "ramp_merchants",
    "ramp_vendors": "ramp_vendors",
    "okta_apps": "okta_apps",
    "okta_groups": "okta_groups",
}


def _to_jsonl_gz(records: list[dict[str, Any]]) -> bytes:
    """Serialize records to gzipped JSONL bytes.

    Args:
        records: List of JSON-serializable mappings.

    Returns:
        Gzipped JSONL payload (one object per line).
    """
    lines = [json.dumps(r, default=str) for r in records]
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"))

def _make_storage_client(project: str | None):
    """Create a GCS client, using the configured service-account key file.

    ``google.auth.default()`` only inspects the process environment and
    gcloud ADC. Pydantic Settings reads ``backend/.env`` without exporting
    it, so the key path is passed explicitly here.

    Args:
        project: GCP project id, or None to use the key's project.

    Returns:
        An authenticated ``google.cloud.storage.Client``.
    """
    from google.cloud import storage
    from google.oauth2 import service_account

    credentials_path = ""
    try:
        from zellovest_shared.config import get_settings

        credentials_path = get_settings().google_application_credentials or ""
    except Exception:
        credentials_path = ""

    if credentials_path:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path
        )
        return storage.Client(project=project, credentials=credentials)
    return storage.Client(project=project)


def write_records_gz(
    records: list[dict[str, Any]],
    *,
    bucket: str,
    entity_folder: str,
    sync_id: str,
    suffix: str,
    project: str | None = None,
    **_ignored: Any,
) -> str:
    """Write one gzipped JSONL batch to GCS.

    Args:
        records: Source-API records to persist.
        bucket: GCS bucket name (tenant-isolated per deployment).
        entity_folder: Partition prefix, e.g. ``ramp_card_transactions``.
        sync_id: Ingestion checkpoint ticket for traceability.
        suffix: Unique batch marker (cursor/event id) to avoid overwrites.
        project: GCP project id (uses default credentials when None).
        **_ignored: Legacy S3 kwargs (``endpoint_url``, ``region``) — accepted
            and ignored for backward compatibility.

    Returns:
        The GCS object key written.

    Raises:
        ValueError: When bucket, folder, or records are missing.
        RuntimeError: When the upload fails or dependency is missing.
    """
    if not bucket:
        raise ValueError("bucket is required")
    if not entity_folder:
        raise ValueError("entity_folder is required")
    if not records:
        raise ValueError("records must not be empty")

    key = f"raw/{entity_folder}/sync={sync_id}/{suffix}.jsonl.gz"
    payload = _to_jsonl_gz(records)

    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is not installed; add it to shared dependencies"
        ) from exc

    try:
        client = _make_storage_client(project)
        blob = client.bucket(bucket).blob(key)
        blob.upload_from_string(payload, content_type="application/gzip")

    except Exception as exc:
        logger.error(
            "gcs_write_failed",
            bucket=bucket,
            key=key,
            records=len(records),
            error_class=type(exc).__name__,
        )
        raise RuntimeError(f"failed to write GCS object {key!r}") from exc

    logger.info("gcs_write_ok", bucket=bucket, key=key, records=len(records))
    return key
