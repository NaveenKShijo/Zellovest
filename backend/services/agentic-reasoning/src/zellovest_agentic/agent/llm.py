"""Structured JSON completion helper for the agent.

Planning and synthesis both need a JSON object back from the model. This
module centralizes that contract, bounded retries, and safe error handling so
callers never receive partially parsed output. Prompt and completion content
are never logged (they may contain procurement data).
"""

from __future__ import annotations

import json
from typing import Any

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


class AgentLLMError(RuntimeError):
    """Raised when the configured model cannot produce a valid JSON object."""


def complete_json(
    system: str,
    payload: dict[str, Any],
    *,
    temperature: float = 0.0,
    attempts: int = 2,
) -> dict[str, Any]:
    """Ask the configured LLM for one JSON object.

    Args:
        system: System prompt describing the output contract and safety rules.
        payload: Structured user payload (question, evidence, catalog).
        temperature: Sampling temperature; planning uses 0.
        attempts: Total attempts before raising.

    Returns:
        Parsed JSON object.

    Raises:
        AgentLLMError: When every attempt fails to produce a JSON object.
    """
    from zellovest_agentic.services.rag_llm import _completion, _json_object

    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            text, _usage = _completion(
                system,
                json.dumps(payload, ensure_ascii=False, default=str),
                temperature=temperature,
            )
            return _json_object(text)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "agent_llm_json_failed",
                attempt=attempt,
                error_class=type(exc).__name__,
            )
    raise AgentLLMError(
        "the reasoning model is unavailable or returned invalid JSON"
    ) from last_error


__all__ = ["AgentLLMError", "complete_json"]
