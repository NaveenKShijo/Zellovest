"""Ramp API client with retry-aware error hierarchy.

Used by Celery workers to fetch data directly from Ramp (control plane
never passes raw payloads through Redis).
"""

import httpx
from typing import Any

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)


class RampError(Exception):
    """Base exception for Ramp API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TransientRampError(RampError):
    """Transient Ramp error (5xx, network timeout) — safe to retry."""

    pass


class RateLimitError(RampError):
    """Ramp 429 Too Many Requests — retry after backoff."""

    def __init__(self, message: str, retry_after_seconds: int = 60):
        super().__init__(message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class PermanentRampError(RampError):
    """Permanent Ramp error (4xx except 429) — do not retry."""

    pass


class RampClient:
    """Thin wrapper around Ramp REST API with structured errors."""

    def __init__(self, base_url: str, access_token: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=timeout)

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = self._client.request(
                method, url, headers=self._headers, params=params, json=json_body
            )
        except httpx.TimeoutException as exc:
            logger.warning("ramp_timeout", url=url)
            raise TransientRampError(f"Ramp timeout: {exc}") from exc
        except httpx.ConnectError as exc:
            logger.warning("ramp_connect_error", url=url)
            raise TransientRampError(f"Ramp connection error: {exc}") from exc

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("ramp_rate_limited", url=url, retry_after=retry_after)
            raise RateLimitError("Ramp rate limit", retry_after_seconds=retry_after)

        if 500 <= resp.status_code < 600:
            logger.warning("ramp_server_error", url=url, status=resp.status_code)
            raise TransientRampError(f"Ramp server error: {resp.status_code}")

        if 400 <= resp.status_code < 500:
            logger.warning("ramp_client_error", url=url, status=resp.status_code)
            raise PermanentRampError(f"Ramp client error: {resp.status_code} - {resp.text}")

        return resp.json()

    def fetch_page(
        self,
        entity: str,
        cursor: str | None = None,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch a single page of records from Ramp.

        Args:
            entity: Ramp entity name (e.g., "card_transactions", "bills").
            cursor: Opaque pagination cursor from previous page.
            page_size: Number of records per page.

        Returns:
            Tuple of (records_list, next_cursor_or_None).
        """
        params = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor

        data = self._request("GET", f"/developer/v1/{entity}", params=params)
        records = data.get("data", [])
        next_cursor = data.get("pagination", {}).get("next_cursor")
        return records, next_cursor

    def fetch_object(self, entity: str, object_id: str) -> dict[str, Any]:
        """Fetch a single object by ID."""
        return self._request("GET", f"/developer/v1/{entity}/{object_id}")

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "RampClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()