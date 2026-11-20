"""Checks for converting the checked-in synthetic telemetry into Bronze feeds."""

from pathlib import Path

import pytest
from zellovest_workers.ml.synthetic_ingest import prepare_feeds

TELEMETRY = Path(__file__).resolve().parents[2] / "data" / "telemetry"


def test_telemetry_converts_to_joinable_bronze_records() -> None:
    """The selected tenant produces four consistent feeds and usable Okta events."""
    feeds = prepare_feeds(TELEMETRY, "tenant_001")
    assert all(not frame.empty for frame in feeds.values())
    users = feeds["hris_employees"]
    assert set(feeds["license_assignments"]["user_id"]).issubset(set(users["user_id"]))
    event = feeds["okta_logs"].iloc[0]
    assert event["actor"]["alternateId"] in set(users["email"])
    assert event["target"][0]["type"] == "AppInstance"
    assert event["outcome"]["result"] == "SUCCESS"
    assert len(feeds["license_contracts"].iloc[0]["renewal_date"]) == 10


def test_unknown_tenant_fails_before_upload() -> None:
    """A typo in the tenant ID cannot create empty external tables."""
    with pytest.raises(ValueError, match="No users records"):
        prepare_feeds(TELEMETRY, "unknown-tenant")
