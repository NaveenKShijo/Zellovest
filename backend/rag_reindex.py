"""Backfill and reconcile a tenant's document index into an inactive collection.

Run with PYTHONPATH containing shared/src and services/workers/src. See
docs/rag-operations.md before invoking against an existing deployment.
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

import httpx
from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from zellovest_shared.config import get_settings
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.models import ExtractionArtifact, Upload, UploadStatus
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.db.transact import Document
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.rag import delete_document_points
from zellovest_workers.tasks.document_index import document_source_version, index_document_task

logger = get_logger(__name__)


def expected_documents(tenant_id: str) -> dict[str, str]:
    """Return fingerprints for every eligible tenant document and artifact."""
    with Session(get_sync_engine()) as session:
        statement = (
            select(Document, ExtractionArtifact, Vendor)
            .join(Upload, and_(Upload.id == Document.upload_id, Upload.tenant_id == tenant_id))
            .join(ExtractionArtifact, and_(
                ExtractionArtifact.upload_id == Document.upload_id,
                ExtractionArtifact.tenant_id == tenant_id,
            ))
            .outerjoin(Vendor, and_(Vendor.id == Document.vendor_id, Vendor.tenant_id == tenant_id))
            .where(Document.tenant_id == tenant_id, Upload.status != UploadStatus.FAILED,
                   ExtractionArtifact.artifact_gcs_key.is_not(None),
                   ExtractionArtifact.artifact_gcs_key != "")
        )
        return {
            str(document.id): document_source_version(document, artifact, vendor.name if vendor else None)
            for document, artifact, vendor in session.execute(statement).all()
        }


def target_status(tenant_id: str, target: str) -> dict[str, dict[str, Any]]:
    """Read every active parent and child for integrity and source verification."""
    settings = get_settings()
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    result: dict[str, dict[str, Any]] = {}
    offset: Any = None
    seen_offsets: set[str] = set()
    with httpx.Client(timeout=60) as client:
        while True:
            request: dict[str, Any] = {
                "filter": {"must": [
                    {"key": "tenant_id", "match": {"value": tenant_id}},
                    {"key": "record_type", "match": {"any": ["parent", "child"]}},
                    {"key": "index_state", "match": {"value": "active"}},
                ]},
                "limit": 256, "with_payload": True, "with_vector": False,
            }
            if offset is not None:
                request["offset"] = offset
            response = client.post(
                f"{settings.qdrant_url.rstrip('/')}/collections/{target}/points/scroll",
                headers=headers, json=request,
            )
            response.raise_for_status()
            body = response.json().get("result") or {}
            for point in body.get("points", []):
                payload = point.get("payload") or {}
                doc_id = str(payload.get("document_id") or "")
                state = result.setdefault(doc_id, {
                    "versions": set(), "children": 0, "parents": set(), "references": set(),
                    "adjacent_references": set(),
                    "expected_children": set(), "expected_parents": set(),
                })
                state["versions"].add((str(payload.get("generation") or ""),
                                       str(payload.get("source_version") or "")))
                state["expected_children"].add(payload.get("expected_children"))
                state["expected_parents"].add(payload.get("expected_parents"))
                if payload.get("record_type") == "parent":
                    state["parents"].add(str(point.get("id") or ""))
                    state["adjacent_references"].update(
                        str(payload[key]) for key in ("previous_parent_id", "next_parent_id")
                        if payload.get(key)
                    )
                else:
                    state["children"] += 1
                    state["references"].add(str(payload.get("parent_id") or ""))
            offset = body.get("next_page_offset")
            if offset is None:
                break
            offset_key = json.dumps(offset, sort_keys=True)
            if offset_key in seen_offsets:
                raise RuntimeError("Qdrant scroll repeated an offset")
            seen_offsets.add(offset_key)
    return result


def compare_index(
    expected: dict[str, str], actual: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Find missing, stale, duplicate-generation, and orphan documents."""
    def stale(doc: str) -> bool:
        """Check source version, generation consistency, counts and parent links."""
        item = actual[doc]
        versions = item["versions"]
        return (len(versions) != 1 or next(iter(versions))[1] != expected[doc]
                or item["expected_children"] != {item["children"]}
                or item["expected_parents"] != {len(item["parents"])}
                or item["references"] != item["parents"]
                or not item["adjacent_references"].issubset(item["parents"]))

    return {
        "missing": sorted(expected.keys() - actual.keys()),
        "stale": sorted(doc for doc in expected.keys() & actual.keys() if stale(doc)),
        "orphan": sorted(actual.keys() - expected.keys()),
    }


def assert_inactive_target(target: str) -> None:
    """Refuse to backfill or prune the active collection or an alias to it."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise ValueError("target must be a Qdrant collection name")
    settings = get_settings()
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    response = httpx.get(f"{settings.qdrant_url.rstrip('/')}/aliases", headers=headers, timeout=20)
    response.raise_for_status()
    aliases = {entry["alias_name"]: entry["collection_name"]
               for entry in (response.json().get("result") or {}).get("aliases", [])}
    if target in aliases:
        raise ValueError("target must be a physical collection, not an alias")
    if target == aliases.get(settings.qdrant_collection, settings.qdrant_collection):
        raise ValueError("target resolves to the active collection")


def main() -> None:
    """Run the selected tenant-scoped backfill, verification, or orphan cleanup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backfill", "verify", "prune"))
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--writers-paused", action="store_true")
    args = parser.parse_args()
    assert_inactive_target(args.target)
    if args.action == "prune" and not args.writers_paused:
        parser.error("prune requires --writers-paused; see docs/rag-operations.md")
    expected = expected_documents(args.tenant)
    if args.action == "backfill":
        failures = []
        for document_id in expected:
            try:
                result = index_document_task(args.tenant, document_id, collection=args.target)
                if result.get("status") != "indexed":
                    failures.append(document_id)
            except Exception as exc:
                logger.error("rag_backfill_document_failed", tenant_id=args.tenant,
                             document_id=document_id, error_class=type(exc).__name__)
                failures.append(document_id)
        print(json.dumps({"eligible": len(expected), "failed_document_ids": failures}, indent=2))
        if failures:
            raise SystemExit(1)
        return
    comparison = compare_index(expected, target_status(args.tenant, args.target))
    if args.action == "prune":
        for document_id in comparison["orphan"]:
            delete_document_points(tenant_id=args.tenant, document_id=document_id,
                                   collection=args.target)
        comparison = compare_index(expected_documents(args.tenant),
                                   target_status(args.tenant, args.target))
    print(json.dumps({"eligible": len(expected), **comparison}, indent=2))
    if not expected or any(comparison.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
