"""S3 writer for gzipped JSONL records (bronze lake)."""

import gzip
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

from zellovest_shared.config import get_settings
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

# S3 folder per entity type (bronze layer partitions)
ENTITY_FOLDERS = {
    "card_transactions": "cards",
    "bills": "bills",
    "events": "events",
    "invoices": "invoices",
    "contracts": "contracts",
    "documents": "documents",
}


def _get_s3_client():
    """Create S3 client with configurable endpoint (MinIO for local)."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
    )


def write_records_gz(
    records: list[dict[str, Any]],
    bucket: str,
    entity_folder: str,
    sync_id: str,
    suffix: str = "",
    endpoint_url: str | None = None,
    region: str | None = None,
) -> str:
    """Write records as gzipped JSONL to S3 bronze lake.

    Args:
        records: List of dict records to serialize.
        bucket: S3 bucket name.
        entity_folder: Partition folder (e.g., "cards", "bills").
        sync_id: Sync checkpoint ID for traceability.
        suffix: Optional suffix for object key uniqueness.
        endpoint_url: Optional S3 endpoint override (MinIO).
        region: Optional AWS region override.

    Returns:
        S3 object key written.
    """
    if not records:
        logger.debug("s3_write_skipped_empty", entity_folder=entity_folder)
        return ""

    # Build object key: entity/date/sync_id/uuid.gz
    date_prefix = datetime.now(UTC).strftime("%Y/%m/%d")
    unique_id = uuid.uuid4().hex[:8]
    suffix_part = f"-{suffix}" if suffix else ""
    key = f"{entity_folder}/{date_prefix}/{sync_id}/{unique_id}{suffix_part}.jsonl.gz"

    # Serialize to gzipped JSONL
    jsonl_lines = [json.dumps(record, separators=(",", ":")) for record in records]
    jsonl_bytes = "\n".join(jsonl_lines).encode("utf-8")
    gzipped = gzip.compress(jsonl_bytes)

    # Write to S3
    client = _get_s3_client()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=gzipped,
        ContentType="application/json",
        ContentEncoding="gzip",
        Metadata={
            "sync_id": sync_id,
            "record_count": str(len(records)),
            "entity_folder": entity_folder,
        },
    )

    logger.info(
        "s3_write_complete",
        bucket=bucket,
        key=key,
        records=len(records),
        bytes=len(gzipped),
    )
    return key