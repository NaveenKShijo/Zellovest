"""Voyage rate limits carry retry guidance into Celery tasks."""

from unittest.mock import MagicMock

import pytest
from zellovest_shared import rag


def test_voyage_429_raises_retryable_error_with_retry_after(monkeypatch) -> None:
    """Parse the provider retry delay instead of treating HTTP 429 as permanent."""
    settings = MagicMock(voyage_api_key="test-key", voyage_api_url="https://example.test")
    monkeypatch.setattr(rag, "_rag_settings", lambda: settings)
    response = MagicMock(status_code=429, headers={"Retry-After": "17"})
    monkeypatch.setattr(rag.httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(rag.VoyageRateLimitError) as error:
        rag._voyage_embeddings(["contract text"], input_type="document")

    assert error.value.retry_after_seconds == 17


def test_voyage_429_without_retry_after_uses_safe_default(monkeypatch) -> None:
    """Use a bounded default delay when Voyage omits Retry-After."""
    settings = MagicMock(voyage_api_key="test-key", voyage_api_url="https://example.test")
    monkeypatch.setattr(rag, "_rag_settings", lambda: settings)
    response = MagicMock(status_code=429, headers={})
    monkeypatch.setattr(rag.httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(rag.VoyageRateLimitError) as error:
        rag._voyage_embeddings(["contract text"], input_type="document")

    assert error.value.retry_after_seconds == 60
