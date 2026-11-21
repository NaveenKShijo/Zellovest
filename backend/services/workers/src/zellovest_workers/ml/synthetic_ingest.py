"""Convert repository telemetry into isolated Bronze inputs for development runs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
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
    directory: Path,
    source_tenant_id: str,
    *,
    target_tenant_id: str | None = None,
    inference_horizon: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Map synthetic records from a source tenant into a target tenant."""
    target_tenant_id = target_tenant_id or source_tenant_id
    frames = {}
    for name, filename in FILES.items():
        frame = pd.read_parquet(directory / filename)
        frames[name] = frame.loc[frame["tenant_id"] == source_tenant_id].copy()
        if frames[name].empty:
            raise ValueError(f"No {name} records found for tenant {source_tenant_id}")

    source_users = frames["users"].copy()
    # IDs are tenant-scoped in the app database. Re-key employees and assignments
    # so ingesting the same source tenant into another target cannot collide.
    user_id_map = {
        source_id: str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"zellovest-synthetic:{target_tenant_id}:user:{source_id}",
            )
        )
        for source_id in frames["users"]["user_id"].unique()
    }
    assignment_id_map = {
        source_id: str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"zellovest-synthetic:{target_tenant_id}:assignment:{source_id}",
            )
        )
        for source_id in frames["assignments"]["assignment_id"].unique()
    }
    for name in ("users", "assignments", "contracts"):
        frames[name]["tenant_id"] = target_tenant_id
    frames["users"]["user_id"] = frames["users"]["user_id"].map(user_id_map)
    frames["assignments"]["user_id"] = frames["assignments"]["user_id"].map(user_id_map)
    frames["assignments"]["assignment_id"] = frames["assignments"]["assignment_id"].map(
        assignment_id_map
    )
    frames["assignments"]["vendor_id"] = frames["assignments"]["app_name"].map(
        lambda app: synthetic_vendor_id(target_tenant_id, str(app))
    )
    frames["contracts"]["vendor_id"] = frames["contracts"]["app_name"].map(
        lambda app: synthetic_vendor_id(target_tenant_id, str(app))
    )

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
    for name, columns in {
        "users": ("hire_date", "termination_date"),
        "assignments": ("assigned_at", "unassigned_at"),
        "contracts": ("renewal_date",),
    }.items():
        for column in columns:
            frames[name][column] = pd.to_datetime(frames[name][column]).dt.strftime("%Y-%m-%d")
    events = frames["events"].merge(
        source_users[["user_id", "email"]],
        on="user_id",
        how="left",
        validate="many_to_one",
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
    directory: Path,
    source_tenant_id: str,
    bucket_name: str,
    prefix: str,
    *,
    target_tenant_id: str | None = None,
    inference_horizon: int | None = None,
) -> None:
    """Upload mapped feeds and source checksums to an isolated GCS prefix."""
    from google.cloud import storage

    target_tenant_id = target_tenant_id or source_tenant_id
    feeds = prepare_feeds(
        directory,
        source_tenant_id,
        target_tenant_id=target_tenant_id,
        inference_horizon=inference_horizon,
    )
    bucket = storage.Client().bucket(bucket_name.removeprefix("gs://").rstrip("/"))
    manifest = {
        "source_tenant_id": source_tenant_id,
        "tenant_id": target_tenant_id,
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
    parser.add_argument("--source-tenant-id", required=True)
    parser.add_argument("--tenant-id", required=True, help="Target application tenant ID")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", args.tenant_id):
        parser.error("target tenant ID must contain lowercase letters, digits, _ or -")
    if not args.prefix.startswith("synthetic/") or ".." in args.prefix.split("/"):
        raise ValueError("Synthetic prefix must start with synthetic/ and contain no .. segments")
    upload_feeds(
        args.directory,
        args.source_tenant_id,
        args.bucket,
        args.prefix.rstrip("/"),
        target_tenant_id=args.tenant_id,
    )


if __name__ == "__main__":
    main()
