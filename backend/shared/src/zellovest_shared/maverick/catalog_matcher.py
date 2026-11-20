"""Approved software retrieval derived from active contract product terms."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from zellovest_shared.config import get_settings
from zellovest_shared.db.core import Vendor
from zellovest_shared.db.intelligence import ContractProductProfile
from zellovest_shared.db.transact import Contract, ContractStatus, ContractTermsVersion
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.maverick.groq_vendor import resolve_contract_product
from zellovest_shared.rag import _voyage_embeddings

logger = get_logger(__name__)
_DENSE_SIZE = 1024
_PROFILE_ENRICHMENT_VERSION = "contract-product-v3"
_MINIMUM_DISPLAY_SIMILARITY = 0.45


def _qdrant_url(settings: Any) -> str:
    """Return the configured Qdrant endpoint without a trailing slash."""
    return settings.qdrant_url.rstrip("/")


def _qdrant_headers(settings: Any) -> dict[str, str]:
    """Build optional API-key authentication headers for Qdrant."""
    return {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}


def _collection(settings: Any) -> str:
    """Return the dedicated collection for approved active contract products."""
    return settings.qdrant_contract_products_collection


def _ensure_contract_product_collection(
    client: httpx.Client, collection: str, settings: Any
) -> None:
    """Create the contract-product collection and tenant filter index when absent."""
    url = f"{_qdrant_url(settings)}/collections/{collection}"
    response = client.get(url, headers=_qdrant_headers(settings))
    if response.status_code == 404:
        response = client.put(
            url,
            headers=_qdrant_headers(settings),
            json={"vectors": {"size": _DENSE_SIZE, "distance": "Cosine"}},
        )
        response.raise_for_status()
    else:
        response.raise_for_status()
    response = client.put(
        f"{url}/index",
        headers=_qdrant_headers(settings),
        json={"field_name": "tenant_id", "field_schema": "keyword"},
    )
    if response.status_code not in {200, 201, 409}:
        response.raise_for_status()


def _active_contract_terms(session: Session, tenant_id: str) -> list[tuple[Any, Any, Any]]:
    """Return the tenant's contract terms effective today under active contracts."""
    today = date.today()
    stmt = (
        select(ContractTermsVersion, Contract, Vendor)
        .join(Contract, ContractTermsVersion.contract_id == Contract.id)
        .join(Vendor, Contract.vendor_id == Vendor.id)
        .where(
            ContractTermsVersion.tenant_id == tenant_id,
            Contract.status == ContractStatus.ACTIVE,
            Contract.start_date <= today,
            or_(Contract.end_date.is_(None), Contract.end_date >= today),
            ContractTermsVersion.effective_from <= today,
            or_(
                ContractTermsVersion.effective_to.is_(None),
                ContractTermsVersion.effective_to >= today,
            ),
        )
        .order_by(Contract.id, ContractTermsVersion.line_no)
    )
    return list(session.execute(stmt).all())


def _source_fingerprint(term: Any, contract: Any, vendor: Any) -> str:
    """Fingerprint fields whose change requires a new product profile."""
    raw = {
        "enrichment_version": _PROFILE_ENRICHMENT_VERSION,
        "vendor": vendor.name,
        "title": contract.title or "",
        "product_code": term.product_code or "",
        "description": term.description or "",
    }
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()


def _capability_text(
    *, profile: dict[str, Any], term: Any, contract: Any, vendor: Any
) -> str:
    """Build the canonical text embedded for one approved contracted product."""
    capabilities = ", ".join(profile.get("capabilities") or [])
    use_cases = ", ".join(profile.get("use_cases") or [])
    return "\n".join(
        part
        for part in (
            f"Product: {profile.get('product_name') or term.description or term.product_code or vendor.name}",
            f"Vendor: {vendor.name}",
            f"Category: {profile.get('category') or 'Software'}",
            f"Capabilities: {capabilities}" if capabilities else "",
            f"Use cases: {use_cases}" if use_cases else "",
            f"Contract title: {contract.title}" if contract.title else "",
            f"Contract SKU: {term.product_code}" if term.product_code else "",
            f"Contract line: {term.description}" if term.description else "",
        )
        if part
    )


def _resolve_profile(
    session: Session, *, term: Any, contract: Any, vendor: Any, settings: Any
) -> ContractProductProfile:
    """Load or refresh the cached LLM profile for one current contract line."""
    fingerprint = _source_fingerprint(term, contract, vendor)
    profile = session.execute(
        select(ContractProductProfile).where(
            ContractProductProfile.tenant_id == term.tenant_id,
            ContractProductProfile.contract_line_id == term.contract_line_id,
        )
    ).scalar_one_or_none()
    prior_response = profile.raw_response if profile is not None else None
    retry_failed_enrichment = bool(settings.groq_api_key) and (
        isinstance(prior_response, dict)
        and prior_response.get("enrichment_status") == "failed"
    )
    if (
        profile is None
        or profile.source_fingerprint != fingerprint
        or retry_failed_enrichment
    ):
        resolved = resolve_contract_product(
            vendor_name=vendor.name,
            contract_title=contract.title,
            product_code=term.product_code,
            description=term.description,
            settings=settings,
        )
        values = {
            "contract_id": contract.id,
            "contract_line_id": term.contract_line_id,
            "contract_term_id": term.id,
            "vendor_id": vendor.id,
            "source_fingerprint": fingerprint,
            "product_name": resolved.get("product_name") or term.description or term.product_code or vendor.name,
            "category": resolved.get("category"),
            "capabilities": resolved.get("capabilities") or [],
            "use_cases": resolved.get("use_cases") or [],
            "is_saas": bool(resolved.get("is_saas", False)),
            "raw_response": resolved,
        }
        values["capability_text"] = _capability_text(
            profile=resolved, term=term, contract=contract, vendor=vendor
        )
        if profile is None:
            profile = ContractProductProfile(tenant_id=term.tenant_id, **values)
            session.add(profile)
        else:
            for field, value in values.items():
                setattr(profile, field, value)
    else:
        profile.contract_id = contract.id
        profile.contract_term_id = term.id
        profile.vendor_id = vendor.id
    session.flush()
    return profile


def sync_active_contract_products(
    session: Session, tenant_id: str, settings: Any = None
) -> dict[str, int]:
    """Enrich and replace a tenant's active contracted-software vectors in Qdrant."""
    settings = settings or get_settings()
    points: list[dict[str, Any]] = []
    excluded_non_saas = 0
    enrichment_failures = 0
    terms = _active_contract_terms(session, tenant_id)
    for term, contract, vendor in terms:
        profile = _resolve_profile(
            session, term=term, contract=contract, vendor=vendor, settings=settings
        )
        if not profile.is_saas:
            excluded_non_saas += 1
            profile_response = profile.raw_response if isinstance(profile.raw_response, dict) else {}
            is_enrichment_failure = profile_response.get("enrichment_status") == "failed"
            if is_enrichment_failure:
                enrichment_failures += 1
            logger.info(
                (
                    "contract_product_enrichment_failed"
                    if is_enrichment_failure
                    else "contract_product_excluded_non_saas"
                ),
                tenant_id=tenant_id,
                contract_line_id=str(term.contract_line_id),
                vendor_name=vendor.name,
                error=profile_response.get("enrichment_error") if is_enrichment_failure else None,
            )
            continue
        vector = _voyage_embeddings([profile.capability_text], input_type="document")[0]
        points.append(
            {
                "id": str(profile.contract_line_id),
                "vector": vector,
                "payload": {
                    "tenant_id": tenant_id,
                    "contract_id": str(contract.id),
                    "contract_term_id": str(term.id),
                    "contract_line_id": str(term.contract_line_id),
                    "vendor_id": str(vendor.id),
                    "vendor_name": vendor.name,
                    "contract_title": contract.title or "",
                    "product_name": profile.product_name,
                    "category": profile.category or "Software",
                    "capabilities": profile.capabilities or [],
                    "use_cases": profile.use_cases or [],
                    "contract_product_code": term.product_code or "",
                    "contract_description": term.description or "",
                    "quantity_max": float(term.qty_max) if term.qty_max is not None else None,
                },
            }
        )

    collection = _collection(settings)
    with httpx.Client(timeout=60) as client:
        _ensure_contract_product_collection(client, collection, settings)
        headers = _qdrant_headers(settings)
        deleted = client.post(
            f"{_qdrant_url(settings)}/collections/{collection}/points/delete?wait=true",
            headers=headers,
            json={"filter": {"must": [{"key": "tenant_id", "match": {"value": tenant_id}}]}},
        )
        deleted.raise_for_status()
        for offset in range(0, len(points), 64):
            response = client.put(
                f"{_qdrant_url(settings)}/collections/{collection}/points?wait=true",
                headers=headers,
                json={"points": points[offset:offset + 64]},
            )
            response.raise_for_status()
    session.commit()
    logger.info(
        "active_contract_products_indexed",
        tenant_id=tenant_id,
        active_terms=len(terms),
        indexed_products=len(points),
        excluded_non_saas=excluded_non_saas,
        enrichment_failures=enrichment_failures,
        groq_model=settings.groq_model,
    )
    return {
        "active_terms": len(terms),
        "indexed_products": len(points),
        "excluded_non_saas": excluded_non_saas,
        "enrichment_failures": enrichment_failures,
    }


def _shared_capabilities(query: list[str], candidate: list[str]) -> list[str]:
    """Return candidate capabilities that share meaningful words with the query."""
    query_text = " ".join(query).casefold()
    return [item for item in candidate if any(word in query_text for word in item.casefold().split())][:3]


def find_approved_alternatives(
    session: Session,
    tenant_id: str,
    product_name: str,
    capabilities: list[str],
    category: str | None = None,
    settings: Any = None,
    limit: int = 3,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve semantically similar products from active procurement contracts.

    Args:
        diagnostics: Optional mutable mapping populated with retrieval facts
            suitable for persisting in the Maverick alert evidence.
    """
    del session
    settings = settings or get_settings()
    if diagnostics is None:
        diagnostics = {}
    diagnostics.update(
        {
            "collection": _collection(settings),
            "minimum_display_similarity": _MINIMUM_DISPLAY_SIMILARITY,
            "qdrant_hits": 0,
            "eligible_matches": 0,
        }
    )
    query_text = "\n".join(
        (
            f"Product: {product_name}",
            f"Category: {category or 'Software'}",
            f"Capabilities: {', '.join(capabilities)}",
        )
    )
    try:
        vector = _voyage_embeddings([query_text], input_type="query")[0]
        collection = _collection(settings)
        with httpx.Client(timeout=30) as client:
            filter_spec = {
                "must": [{"key": "tenant_id", "match": {"value": tenant_id}}]
            }
            response = client.post(
                f"{_qdrant_url(settings)}/collections/{collection}/points/query",
                headers=_qdrant_headers(settings),
                json={
                    "query": vector,
                    "filter": filter_spec,
                    "limit": limit,
                    "with_payload": True,
                },
            )
            if response.status_code == 404:
                # Qdrant before 1.10 exposes the equivalent search endpoint.
                response = client.post(
                    f"{_qdrant_url(settings)}/collections/{collection}/points/search",
                    headers=_qdrant_headers(settings),
                    json={
                        "vector": vector,
                        "filter": filter_spec,
                        "limit": limit,
                        "with_payload": True,
                    },
                )
            if response.status_code == 404:
                diagnostics["reason"] = "contract_product_collection_not_found"
                return []
            response.raise_for_status()
        result = response.json().get("result") or {}
        hits = result.get("points", []) if isinstance(result, dict) else result
        diagnostics["qdrant_hits"] = len(hits)
    except Exception as exc:
        diagnostics["reason"] = "vector_search_failed"
        diagnostics["error_class"] = type(exc).__name__
        logger.warning(
            "contract_product_vector_search_failed",
            tenant_id=tenant_id,
            error_class=type(exc).__name__,
            error=str(exc),
        )
        return []

    matches: list[dict[str, Any]] = []
    for hit in hits:
        payload = hit.get("payload") or {}
        similarity = float(hit.get("score") or 0.0)
        if similarity < _MINIMUM_DISPLAY_SIMILARITY:
            continue
        candidate_caps = payload.get("capabilities") or []
        matches.append(
            {
                "contract_id": payload.get("contract_id"),
                "contract_term_id": payload.get("contract_term_id"),
                "contract_line_id": payload.get("contract_line_id"),
                "name": payload.get("product_name"),
                "vendor_id": payload.get("vendor_id"),
                "vendor_name": payload.get("vendor_name"),
                "category": payload.get("category") or "Software",
                "similarity_score": round(similarity, 4),
                "contracted_quantity": payload.get("quantity_max"),
                "license_available": None,
                "unused_licenses": None,
                "shared_capabilities": _shared_capabilities(capabilities, candidate_caps),
            }
        )
    logger.info(
        "contract_product_vector_search_completed",
        tenant_id=tenant_id,
        qdrant_hits=len(hits),
        eligible_matches=len(matches),
    )
    diagnostics["eligible_matches"] = len(matches)
    diagnostics["reason"] = "match_found" if matches else "below_similarity_threshold"
    if hits:
        diagnostics["top_similarity"] = round(float(hits[0].get("score") or 0.0), 4)
    return matches
