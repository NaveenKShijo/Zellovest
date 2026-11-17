"""TypeSafe Jev AI client for Maverick Spend decision evaluation via OpenRouter Decisions API."""

from __future__ import annotations

import json
from typing import Any

import httpx

from zellovest_shared.config import get_settings
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

# Non-software merchant categories (clear non-software expenses)
_CLEAR_NON_SOFTWARE_MCCS = frozenset(
    {
        "5812",  # Eating places and restaurants
        "5814",  # Fast food restaurants
        "4121",  # Taxicabs and limousines
        "3000",  # Airlines
        "4722",  # Travel agencies
        "5411",  # Grocery stores
        "5541",  # Service stations / gas
        "7011",  # Hotels and motels
    }
)


class JevDecisionError(Exception):
    """Raised when Jev decision API fails and no fallback is desired."""

    pass


def _flatten_state(raw_state: dict[str, Any]) -> dict[str, str]:
    """Ensure every state field passed to Jev is a top-level string."""
    flat: dict[str, str] = {}
    for k, v in raw_state.items():
        if v is None:
            flat[k] = ""
        elif isinstance(v, bool):
            flat[k] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            flat[k] = str(v)
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, default=str)
        else:
            flat[k] = str(v)
    return flat


def evaluate_stage1_screening(
    features: dict[str, Any],
    settings: Any = None,
) -> dict[str, Any]:
    """Stage 1: Preliminary Jev AI screening of card transaction.

    Questions:
        - is_software_related (noul)
        - is_likely_subscription (noul)
        - warrants_procurement_investigation (noul)

    Returns:
        dict with probabilities and routing decision:
        {
            "is_software_score": float,
            "is_subscription_score": float,
            "warrants_investigation_score": float,
            "proceed_to_stage2": bool,
            "method": "jev_api" | "rule_fallback",
        }
    """
    settings = settings or get_settings()
    mcc = str(features.get("mcc") or "")
    is_strong = bool(features.get("is_recurrence_evidence_strong", False))
    is_non_software_category = bool(features.get("is_non_software_category", False))

    # Early deterministic exit for obvious non-software expenses if no subscription pattern
    if (mcc in _CLEAR_NON_SOFTWARE_MCCS or is_non_software_category) and not is_strong:
        logger.info(
            "stage1_early_exit_non_software",
            mcc=mcc,
            merchant=features.get("merchant_name"),
            sk_category=features.get("sk_category_name"),
        )
        return {
            "is_software_score": 0.05,
            "is_subscription_score": 0.10,
            "warrants_investigation_score": 0.05,
            "proceed_to_stage2": False,
            "method": "rule_early_exit",
        }

    raw_state = {
        "merchant_name": features.get("merchant_name", ""),
        "amount": features.get("amount", 0.0),
        "currency": features.get("currency", "USD"),
        "mcc": mcc,
        "spend_category": features.get("sk_category_name") or "",
        "memo": features.get("memo") or "",
        "previous_transaction_count": features.get("previous_transaction_count", 0),
        "cadence_days": features.get("cadence_days", 30),
        "amount_variance": features.get("amount_variance", 0.0),
        "is_recurrence_evidence_strong": is_strong,
        "employee_department": features.get("department", "Unknown"),
    }
    state = _flatten_state(raw_state)

    questions = {
        "is_software_related": {
            "type": "noul",
            "instructions": (
                "Does the available transaction evidence indicate this purchase is for "
                "software, SaaS, or a digital software service?"
            ),
        },
        "is_likely_subscription": {
            "type": "noul",
            "instructions": (
                "Does the recurrence history, cadence, amount consistency, and merchant profile "
                "support that this is a recurring software subscription?"
            ),
        },
        "warrants_procurement_investigation": {
            "type": "noul",
            "instructions": (
                "Does this software purchase warrant procurement investigation for potential "
                "maverick or unmanaged software spend?"
            ),
        },
    }

    api_key = settings.jev_api_key
    if not api_key:
        logger.info("jev_api_key_unset_using_fallback")
        return _stage1_deterministic_fallback(features)

    payload = {
        "model": settings.jev_model,
        "state": state,
        "questions": questions,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Zellovest",
    }

    try:
        resp = httpx.post(
            settings.jev_api_url,
            json=payload,
            headers=headers,
            timeout=settings.jev_timeout_seconds,
        )
        if resp.status_code == 200:
            data = resp.json().get("answers", {})
            is_soft = float(data.get("is_software_related", {}).get("noul", 0.5))
            is_sub = float(data.get("is_likely_subscription", {}).get("noul", 0.5))
            warrants = float(data.get("warrants_procurement_investigation", {}).get("noul", 0.5))

            # Proceed if software/subscription score is high or recurrence is strong
            proceed = (is_soft >= 0.60 or warrants >= 0.60) or features.get(
                "is_recurrence_evidence_strong", False
            )
            return {
                "is_software_score": round(is_soft, 4),
                "is_subscription_score": round(is_sub, 4),
                "warrants_investigation_score": round(warrants, 4),
                "proceed_to_stage2": proceed,
                "method": "jev_api",
            }
        else:
            logger.warning("jev_stage1_http_error", status=resp.status_code, body=resp.text[:200])
            return _stage1_deterministic_fallback(features)
    except Exception as exc:
        logger.warning("jev_stage1_call_failed", error=str(exc))
        return _stage1_deterministic_fallback(features)


def _stage1_deterministic_fallback(features: dict[str, Any]) -> dict[str, Any]:
    """Deterministic rule-based fallback when Jev API is unavailable."""
    mcc = str(features.get("mcc") or "")
    merchant = str(features.get("merchant_name") or "").lower()
    is_strong = features.get("is_recurrence_evidence_strong", False)
    prior_count = features.get("previous_transaction_count", 0)
    is_software_category = features.get("is_software_category", False)
    is_non_software_category = features.get("is_non_software_category", False)

    # Common SaaS keywords
    saas_keywords = (
        "software",
        "cloud",
        "ai",
        "github",
        "cursor",
        "openai",
        "figma",
        "notion",
        "slack",
        "zoom",
        "aws",
        "docker",
    )
    is_known_name = any(kw in merchant for kw in saas_keywords)

    if mcc == "5734" or is_known_name or is_software_category:
        is_soft = 0.95
    elif is_non_software_category:
        is_soft = 0.05
    else:
        is_soft = 0.40

    if is_strong:
        is_sub = 0.92
    elif prior_count >= 1:
        is_sub = 0.70
    else:
        is_sub = 0.45

    warrants = max(is_soft, is_sub)
    proceed = warrants >= 0.60 or is_strong

    return {
        "is_software_score": is_soft,
        "is_subscription_score": is_sub,
        "warrants_investigation_score": warrants,
        "proceed_to_stage2": proceed,
        "method": "rule_fallback",
    }


def evaluate_stage4_assessment(
    decision_state: dict[str, Any],
    settings: Any = None,
) -> dict[str, Any]:
    """Stage 4: Final potential maverick spend assessment.

    Evaluates full context: transaction, product profile, capability overlap,
    available licenses, and procurement policy compliance.

    Questions:
        - potential_maverick_spend (noul)
        - assessment_outcome (choice)
        - procurement_review_priority (choice)
    """
    settings = settings or get_settings()

    # Deterministic policy override: if approved by formal PO, not maverick
    if decision_state.get("has_been_approved"):
        return {
            "potential_maverick_probability": 0.05,
            "assessment_outcome": "not_maverick",
            "review_priority": "low",
            "method": "deterministic_policy_approved",
        }

    raw_state = {
        "merchant_name": decision_state.get("merchant_name", ""),
        "product_name": decision_state.get("product_name")
        or decision_state.get("merchant_name", ""),
        "amount": decision_state.get("amount", 0.0),
        "currency": decision_state.get("currency", "USD"),
        "cadence_days": decision_state.get("cadence_days", 30),
        "is_subscription": decision_state.get("is_subscription", True),
        "requires_procurement_approval": decision_state.get("requires_procurement_approval", True),
        "has_procurement_approval": decision_state.get("has_been_approved", False),
        "approved_alternative_found": decision_state.get("has_approved_alternative", False),
        "approved_alternative_name": decision_state.get("approved_alternative_name") or "None",
        "overlap_similarity": f"{float(decision_state.get('overlap_score') or 0.0):.2f}",
        "available_unused_licenses": decision_state.get("unused_licenses", 0),
        "employee_department": decision_state.get("department", "Unknown"),
    }
    state = _flatten_state(raw_state)

    questions = {
        "potential_maverick_spend": {
            "type": "noul",
            "instructions": (
                "Based on the complete transaction evidence, procurement policy, approval records, "
                "existing approved software, capability overlap, and available licenses, does this "
                "purchase represent potential maverick spend?"
            ),
        },
        "assessment_outcome": {
            "type": "choice",
            "instructions": "Classify this purchase according to the available evidence.",
            "criteria": {
                "potential_maverick": (
                    "Evidence suggests the purchase bypassed procurement requirements or "
                    "represents an unmanaged duplicate purchase."
                ),
                "not_maverick": (
                    "Evidence indicates that the purchase is compliant "
                    "or no procurement concern exists."
                ),
                "legitimate_distinct_requirement": (
                    "The new product provides legitimate capabilities "
                    "not covered by approved alternatives."
                ),
                "insufficient_evidence": (
                    "The available evidence is inadequate to make a reliable determination."
                ),
            },
        },
        "procurement_review_priority": {
            "type": "choice",
            "instructions": (
                "Evaluate the priority level for procurement to investigate this transaction."
            ),
            "criteria": {
                "critical": "High dollar amount or immediate duplicate license waste.",
                "high": "Duplicate SaaS with active alternative licenses in the same department.",
                "medium": "Unapproved SaaS subscription with moderate overlap or missing approval.",
                "low": "Minor expenditure or low overlap likelihood.",
            },
        },
    }

    api_key = settings.jev_api_key
    if not api_key:
        return _stage4_deterministic_fallback(decision_state)

    payload = {
        "model": settings.jev_model,
        "state": state,
        "questions": questions,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Zellovest",
    }

    try:
        resp = httpx.post(
            settings.jev_api_url,
            json=payload,
            headers=headers,
            timeout=settings.jev_timeout_seconds,
        )
        if resp.status_code == 200:
            data = resp.json().get("answers", {})
            p_mav = float(data.get("potential_maverick_spend", {}).get("noul", 0.5))
            outcome = data.get("assessment_outcome", {}).get("choice", "potential_maverick")
            priority = data.get("procurement_review_priority", {}).get("choice", "medium")
            return {
                "potential_maverick_probability": round(p_mav, 4),
                "assessment_outcome": outcome,
                "review_priority": priority,
                "method": "jev_api",
            }
        else:
            logger.warning("jev_stage4_http_error", status=resp.status_code, body=resp.text[:200])
            return _stage4_deterministic_fallback(decision_state)
    except Exception as exc:
        logger.warning("jev_stage4_call_failed", error=str(exc))
        return _stage4_deterministic_fallback(decision_state)


def _stage4_deterministic_fallback(decision_state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic policy assessment fallback."""
    has_alt = decision_state.get("has_approved_alternative", False)
    overlap = float(decision_state.get("overlap_score") or 0.0)
    unused_licenses = int(decision_state.get("unused_licenses") or 0)
    has_approval = decision_state.get("has_been_approved", False)

    if has_approval:
        return {
            "potential_maverick_probability": 0.05,
            "assessment_outcome": "not_maverick",
            "review_priority": "low",
            "method": "rule_fallback",
        }

    if has_alt and overlap >= 0.75 and unused_licenses > 0:
        return {
            "potential_maverick_probability": 0.94,
            "assessment_outcome": "potential_maverick",
            "review_priority": "high",
            "method": "rule_fallback",
        }

    if has_alt and overlap >= 0.70:
        return {
            "potential_maverick_probability": 0.85,
            "assessment_outcome": "potential_maverick",
            "review_priority": "medium",
            "method": "rule_fallback",
        }

    # Software subscription with no prior approval
    return {
        "potential_maverick_probability": 0.78,
        "assessment_outcome": "potential_maverick",
        "review_priority": "medium",
        "method": "rule_fallback",
    }
