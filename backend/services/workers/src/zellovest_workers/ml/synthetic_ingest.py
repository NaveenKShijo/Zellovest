"""Convert repository telemetry into isolated Bronze inputs for development runs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
FILES = {
    "users": "dim_users.parquet",
    "assignments": "fact_seat_assignments.parquet",
    "events": "fact_sso_events.parquet",
    "contracts": "dim_contracts.parquet",
}


def synthetic_vendor_id(tenant_id: str, app_name: str) -> str:
    """Create a stable synthetic vendor UUID for one tenant and product."""
    name = f"zellovest-synthetic:{tenant_id}:{app_name.lower()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def prepare_feeds(
    directory: Path, tenant_id: str, *, inference_horizon: int | None = None
) -> dict[str, pd.DataFrame]:
    """Map one tenant's synthetic records to the external table schemas."""
    frames = {}
    for name, filename in FILES.items():
        frame = pd.read_parquet(directory / filename)
        frames[name] = frame.loc[frame["tenant_id"] == tenant_id].copy()
        if frames[name].empty:
            raise ValueError(f"No {name} records found for tenant {tenant_id}")

    users = frames["users"]
    if inference_horizon is not None:
        if inference_horizon not in {30, 60, 90, 120}:
            raise ValueError("inference horizon must be 30, 60, 90 or 120 days")
        today = datetime.now(UTC).date()
        assignments = frames["assignments"]
        frames["assignments"] = assignments.loc[
            (assignments["status"].str.upper() == "ACTIVE")
            & (pd.to_datetime(assignments["assigned_at"]).dt.date <= today)
            & assignments["unassigned_at"].isna()
        ].copy()
        if frames["assignments"].empty:
            raise ValueError("No active synthetic assignments available for inference")
        frames["contracts"]["renewal_date"] = today + timedelta(days=inference_horizon)
        for name in ("assignments", "contracts"):
            frames[name]["vendor_id"] = frames[name]["app_name"].map(
                lambda app: synthetic_vendor_id(tenant_id, str(app))
            )
    for name, columns in {
        "users": ("hire_date", "termination_date"),
        "assignments": ("assigned_at", "unassigned_at"),
        "contracts": ("renewal_date",),
    }.items():
        for column in columns:
            frames[name][column] = pd.to_datetime(frames[name][column]).dt.strftime("%Y-%m-%d")
    events = frames["events"].merge(
        users[["user_id", "email"]], on="user_id", how="left", validate="many_to_one"
    )
    if events["email"].isna().any():
        raise ValueError("Synthetic events contain users missing from the employee feed")
    logs = pd.DataFrame({
        "id": events["event_id"],
        "published": pd.to_datetime(events["occurred_at"], utc=True).dt.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "eventType": events["event_type"],
        "outcome": [{"result": value} for value in events["outcome"]],
        "actor": [{"alternateId": value} for value in events["email"]],
        "target": [
            [{"type": "AppInstance", "id": app_id, "displayName": app_name}]
            for app_id, app_name in zip(events["app_id"], events["app_name"], strict=True)
        ],
    })
    return {
        "okta_logs": logs,
        "license_assignments": frames["assignments"],
        "hris_employees": users,
        "license_contracts": frames["contracts"],
    }


def upload_feeds(
    directory: Path, tenant_id: str, bucket_name: str, prefix: str,
    *, inference_horizon: int | None = None,
) -> None:
    """Upload a run's feeds and source checksums to an isolated GCS prefix."""
    from google.cloud import storage

    feeds = prepare_feeds(directory, tenant_id, inference_horizon=inference_horizon)
    bucket = storage.Client().bucket(bucket_name.removeprefix("gs://").rstrip("/"))
    manifest = {
        "tenant_id": tenant_id,
        "inference_horizon": inference_horizon,
        "source_commit": os.getenv("GITHUB_SHA", "unknown"),
        "files": {
            filename: hashlib.sha256((directory / filename).read_bytes()).hexdigest()
            for filename in FILES.values()
        },
        "rows": {name: len(frame) for name, frame in feeds.items()},
    }
    for name, frame in feeds.items():
        payload = frame.to_json(orient="records", lines=True, date_format="iso").encode()
        path = f"{prefix}/{name}/sync=initial/part.jsonl.gz"
        bucket.blob(path).upload_from_string(
            gzip.compress(payload), content_type="application/gzip"
        )
        logger.info("synthetic_feed_uploaded", path=path, rows=len(frame))
    bucket.blob(f"{prefix}/manifest.json").upload_from_string(
        json.dumps(manifest, indent=2), content_type="application/json"
    )


def main() -> None:
    """Run synthetic ingestion with explicitly supplied isolation settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    if not args.prefix.startswith("synthetic/") or ".." in args.prefix.split("/"):
        raise ValueError("Synthetic prefix must start with synthetic/ and contain no .. segments")
    upload_feeds(args.directory, args.tenant_id, args.bucket, args.prefix.rstrip("/"))


if __name__ == "__main__":
    main()
