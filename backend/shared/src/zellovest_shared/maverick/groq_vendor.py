"""Stage 2: Merchant & Product context resolution using Groq and persistent caching."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.config import get_settings
from zellovest_shared.db.core import MerchantProfile
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)
_MERCHANT_PROFILE_ENRICHMENT_VERSION = "merchant-product-v2"


class GroqProductResolution(BaseModel):
    """Pydantic schema for Groq structured JSON output."""

    canonical_name: str = Field(description="Canonical vendor/company name")
    domain: str | None = Field(default=None, description="Primary domain e.g. cursor.com")
    product_name: str = Field(description="Specific software or SaaS product name")
    category: str = Field(
        description="Software category e.g. AI coding assistant, Project management"
    )
    capabilities: list[str] = Field(
        default_factory=list, description="List of 3-6 core software capabilities"
    )
    use_cases: list[str] = Field(default_factory=list, description="Primary business use cases")
    is_saas: bool = Field(default=True, description="Whether this is a software or SaaS product")


# Seeded dictionary for immediate zero-latency heuristic resolution & offline testing
_KNOWN_SAAS_DIRECTORY: dict[str, dict[str, Any]] = {
    "cursor": {
        "canonical_name": "Cursor",
        "domain": "cursor.com",
        "product_name": "Cursor AI Code Editor",
        "category": "AI coding assistant",
        "capabilities": ["Code completion", "Code generation", "Codebase indexing", "Refactoring"],
        "use_cases": ["Software engineering", "Developer productivity"],
        "is_saas": True,
    },
    "github": {
        "canonical_name": "GitHub",
        "domain": "github.com",
        "product_name": "GitHub Copilot",
        "category": "AI coding assistant",
        "capabilities": [
            "Code completion",
            "Code explanation",
            "Code generation",
            "Test generation",
        ],
        "use_cases": ["Software engineering", "Code review"],
        "is_saas": True,
    },
    "openai": {
        "canonical_name": "OpenAI",
        "domain": "openai.com",
        "product_name": "ChatGPT Plus / Enterprise",
        "category": "Generative AI assistant",
        "capabilities": ["Text generation", "Data analysis", "Reasoning", "Workflow automation"],
        "use_cases": ["Knowledge work", "Content generation", "Research"],
        "is_saas": True,
    },
    "figma": {
        "canonical_name": "Figma",
        "domain": "figma.com",
        "product_name": "Figma Design & FigJam",
        "category": "Collaborative design software",
        "capabilities": [
            "UI/UX prototyping",
            "Vector graphics",
            "Design system management",
            "Whiteboarding",
        ],
        "use_cases": ["Product design", "Collaboration"],
        "is_saas": True,
    },
    "slack": {
        "canonical_name": "Slack Technologies",
        "domain": "slack.com",
        "product_name": "Slack Pro / Business+",
        "category": "Team collaboration & messaging",
        "capabilities": [
            "Channel messaging",
            "Direct messaging",
            "Voice/video huddles",
            "Bot integrations",
        ],
        "use_cases": ["Team communications", "Incident management"],
        "is_saas": True,
    },
    "notion": {
        "canonical_name": "Notion Labs",
        "domain": "notion.so",
        "product_name": "Notion Workspace",
        "category": "Knowledge base & notes",
        "capabilities": ["Wikis", "Documentation", "Project tracking", "AI writing"],
        "use_cases": ["Knowledge management", "Team documentation"],
        "is_saas": True,
    },
}


def resolve_merchant_product(
    session: Session,
    tenant_id: str,
    merchant_name: str,
    memo: str | None = None,
    mcc: str | None = None,
    settings: Any = None,
) -> dict[str, Any]:
    """Resolve merchant and product capabilities with caching and Groq extraction.

    1. Checks the persistent `merchant_profiles` database table.
    2. If missing, attempts Groq structured JSON extraction.
    3. If Groq is unavailable, falls back to the known vendor dictionary / heuristics.
    4. Persists the result into `merchant_profiles` for subsequent reuse.
    """
    settings = settings or get_settings()
    norm_name = merchant_name.strip()

    # 1. Check persistent database cache
    stmt = select(MerchantProfile).where(
        MerchantProfile.tenant_id == tenant_id,
        MerchantProfile.merchant_name == norm_name,
    )
    existing = session.execute(stmt).scalars().first()
    existing_response = existing.raw_response if existing else None
    if (
        existing
        and isinstance(existing_response, dict)
        and existing_response.get("enrichment_version")
        == _MERCHANT_PROFILE_ENRICHMENT_VERSION
        and existing_response.get("enrichment_status") == "succeeded"
    ):
        logger.info("merchant_profile_cache_hit", merchant=norm_name, tenant_id=tenant_id)
        return {
            "canonical_name": existing.canonical_name or existing.merchant_name,
            "domain": existing.domain,
            "product_name": existing.product_name or existing.merchant_name,
            "category": existing.category or "Software",
            "capabilities": existing.capabilities or [],
            "use_cases": existing.use_cases or [],
            "is_saas": existing.is_saas,
            "cached": True,
        }

    # 2. Try Groq extraction if configured
    resolved_data: dict[str, Any] | None = None
    enrichment_error: str | None = None
    if settings.groq_api_key:
        try:
            resolved_data = _call_groq_extraction(
                merchant_name=norm_name,
                memo=memo,
                mcc=mcc,
                settings=settings,
            )
            resolved_data["enrichment_status"] = "succeeded"
        except Exception as exc:
            enrichment_error = str(exc)
            logger.warning("groq_vendor_resolution_failed", merchant=norm_name, error=str(exc))
    else:
        enrichment_error = "GROQ_API_KEY is not configured"

    # 3. Fallback to dictionary / heuristic
    if not resolved_data:
        resolved_data = _heuristic_resolution(norm_name, memo)
        resolved_data["enrichment_status"] = "failed"
        resolved_data["enrichment_error"] = enrichment_error
    resolved_data["enrichment_version"] = _MERCHANT_PROFILE_ENRICHMENT_VERSION

    # 4. Save to database cache
    try:
        profile_values = {
            "canonical_name": resolved_data.get("canonical_name"),
            "domain": resolved_data.get("domain"),
            "product_name": resolved_data.get("product_name"),
            "category": resolved_data.get("category"),
            "capabilities": resolved_data.get("capabilities", []),
            "use_cases": resolved_data.get("use_cases", []),
            "is_saas": resolved_data.get("is_saas", True),
            "raw_response": resolved_data,
        }
        if existing is None:
            profile = MerchantProfile(
                tenant_id=tenant_id,
                merchant_name=norm_name,
                **profile_values,
            )
            session.add(profile)
        else:
            profile = existing
            for field, value in profile_values.items():
                setattr(profile, field, value)
        session.commit()
        logger.info(
            "merchant_profile_enriched",
            merchant=norm_name,
            product=profile.product_name,
            model=settings.groq_model,
        )
    except Exception as exc:
        session.rollback()
        logger.warning("merchant_profile_cache_save_failed", error=str(exc))

    return resolved_data


def resolve_contract_product(
    *,
    vendor_name: str,
    contract_title: str | None,
    product_code: str | None,
    description: str | None,
    settings: Any = None,
) -> dict[str, Any]:
    """Classify one contracted product line for capability matching.

    Contract terms are the only source of approved products. GPT-OSS-120B
    enriches the actual vendor and line description before it is embedded. A
    failed enrichment is stored as a retryable failure rather than replaced by
    a provider-specific fallback profile.
    """
    settings = settings or get_settings()
    if settings.groq_api_key:
        try:
            resolved = _call_groq_contract_extraction(
                vendor_name=vendor_name,
                contract_title=contract_title,
                product_code=product_code,
                description=description,
                settings=settings,
            )
            resolved["enrichment_status"] = "succeeded"
            resolved["enrichment_model"] = settings.groq_model
            return resolved
        except Exception as exc:
            logger.warning(
                "groq_contract_product_resolution_failed",
                vendor=vendor_name,
                product_code=product_code,
                error_class=type(exc).__name__,
            )
            error_message = str(exc)
    else:
        error_message = "GROQ_API_KEY is not configured"

    return {
        "canonical_name": vendor_name,
        "domain": None,
        "product_name": description or product_code or vendor_name,
        "category": "Unknown",
        "capabilities": [],
        "use_cases": [],
        "is_saas": False,
        "enrichment_status": "failed",
        "enrichment_model": settings.groq_model,
        "enrichment_error": error_message,
    }


def _call_groq_extraction(
    merchant_name: str,
    memo: str | None,
    mcc: str | None,
    settings: Any,
) -> dict[str, Any]:
    """Call Groq API with JSON mode for structured product understanding."""
    system_prompt = (
        "You are an enterprise software procurement analyst. Your task is to analyze "
        "corporate card transaction merchant names, memos, and MCC codes to extract the "
        "software product identity, category, core capabilities, and use cases in JSON."
    )

    user_prompt = (
        f"Merchant Name: {merchant_name}\n"
        f"Transaction Memo: {memo or 'N/A'}\n"
        f"Merchant Category Code (MCC): {mcc or 'N/A'}\n\n"
        "Return a JSON object conforming to this schema:\n"
        "{\n"
        '  "canonical_name": string,\n'
        '  "domain": string or null,\n'
        '  "product_name": string,\n'
        '  "category": string,\n'
        '  "capabilities": list of 3-5 capabilities (e.g. ["Code completion"]),\n'
        '  "use_cases": list of 2-3 business use cases (e.g. ["Software engineering"]),\n'
        '  "is_saas": boolean\n'
        "}"
    )

    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    resp = httpx.post(
        settings.groq_api_url,
        json=payload,
        headers=headers,
        timeout=settings.groq_timeout_seconds,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Groq HTTP {resp.status_code}: {resp.text[:200]}")

    result_json = resp.json()
    content = result_json["choices"][0]["message"]["content"]
    data = json.loads(content)
    validated = GroqProductResolution.model_validate(data)
    return validated.model_dump()


def _call_groq_contract_extraction(
    *,
    vendor_name: str,
    contract_title: str | None,
    product_code: str | None,
    description: str | None,
    settings: Any,
) -> dict[str, Any]:
    """Resolve an active contract line into a conservative SaaS product profile."""
    payload = {
        "model": settings.groq_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an enterprise procurement analyst. Classify one active "
                    "contract line. Mark is_saas true only when the line clearly refers "
                    "to software or a cloud subscription. Do not infer software from "
                    "generic consulting, hardware, support, training, or legal services."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Vendor: {vendor_name}\n"
                    f"Contract title: {contract_title or 'N/A'}\n"
                    f"Product code: {product_code or 'N/A'}\n"
                    f"Contract line description: {description or 'N/A'}\n\n"
                    "Return JSON with canonical_name, domain, product_name, category, "
                    "capabilities (3-6), use_cases (2-3), and is_saas."
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    response = httpx.post(
        settings.groq_api_url,
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        },
        timeout=settings.groq_timeout_seconds,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Groq HTTP {response.status_code}: {response.text[:200]}")
    parsed = json.loads(response.json()["choices"][0]["message"]["content"])
    return GroqProductResolution.model_validate(parsed).model_dump()


def _heuristic_resolution(merchant_name: str, memo: str | None) -> dict[str, Any]:
    """Heuristic fallback when Groq is not configured or fails."""
    m_lower = merchant_name.lower().strip()
    for key, info in _KNOWN_SAAS_DIRECTORY.items():
        if key in m_lower or (memo and key in memo.lower()):
            return dict(info)

    # Generic software profile
    return {
        "canonical_name": merchant_name,
        "domain": None,
        "product_name": merchant_name,
        "category": "Enterprise Software / SaaS",
        "capabilities": ["Software service", "Cloud subscription"],
        "use_cases": ["Business operations"],
        "is_saas": True,
    }
