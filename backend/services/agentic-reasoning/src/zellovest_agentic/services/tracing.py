"""Langfuse tracing helpers that intentionally omit prompt and document content."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from zellovest_agentic.config import get_agentic_reasoning_settings
from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_langfuse_client() -> Any | None:
    """Create one SDK client from service settings, including backend/.env values."""
    try:
        settings = get_agentic_reasoning_settings()
        if not settings.langfuse_public_key or not settings.langfuse_secret_key:
            return None
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            tracing_enabled=True,
        )
    except Exception as exc:
        logger.warning("langfuse_client_unavailable", error_class=type(exc).__name__)
        return None


@contextmanager
def trace_span(name: str, metadata: dict[str, Any]) -> Iterator[Any | None]:
    """Create a Langfuse span with metadata only; tracing failures never fail RAG."""
    client = _get_langfuse_client()
    if client is None:
        yield None
        return
    try:
        observation = client.start_as_current_observation(as_type="span", name=name)
    except Exception as exc:
        logger.warning("langfuse_span_unavailable", span=name, error_class=type(exc).__name__)
        yield None
        return
    with observation as span:
        try:
            span.update(metadata=metadata)
        except Exception as exc:
            logger.warning("langfuse_metadata_failed", span=name,
                           error_class=type(exc).__name__)
        yield span


@contextmanager
def trace_generation(model: str, provider: str) -> Iterator[Any | None]:
    """Create a generation observation without recording prompt or completion text."""
    client = _get_langfuse_client()
    if client is None:
        yield None
        return
    try:
        observation = client.start_as_current_observation(
            as_type="generation", name="rag.llm_call", model=model
        )
    except Exception as exc:
        logger.warning("langfuse_generation_unavailable", error_class=type(exc).__name__)
        yield None
        return
    with observation as generation:
        try:
            generation.update(metadata={"provider": provider})
        except Exception as exc:
            logger.warning("langfuse_generation_metadata_failed", error_class=type(exc).__name__)
        yield generation
