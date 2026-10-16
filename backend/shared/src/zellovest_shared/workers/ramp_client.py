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


def is_auth_failure(exc: BaseException) -> bool:
    """Return True when a Ramp error looks like an expired/revoked token.

    Args:
        exc: Exception raised by :class:`RampClient`.

    Returns:
        True for 401/403 permanent failures — the tenant must reconnect
        (or the worker must refresh first) instead of retrying the call.
    """
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    message = str(exc).lower()
    return "client error: 401" in message or "client error: 403" in message


def refresh_ramp_access_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: float = 15.0,
) -> dict[str, object]:
    """Refresh an expired Ramp OAuth access token (sync, for Celery workers).

    Calls the Ramp token endpoint with ``grant_type=refresh_token`` and
    HTTP Basic client auth — the same exchange the Connect flow uses.

    Args:
        token_url: Ramp token endpoint URL.
        client_id: OAuth client id (never logged).
        client_secret: OAuth client secret (never logged).
        refresh_token: Previously issued refresh token (never logged).
        timeout: Per-request timeout in seconds.

    Returns:
        Token response mapping with ``access_token`` and usually a rotated
        ``refresh_token``, plus ``expires_in`` and ``scope``.

    Raises:
        TransientRampError: Transport failure — safe to retry.
        PermanentRampError: Rejected grant (revoked/rotated refresh token) —
            the tenant must reconnect; do not retry.
    """
    try:
        resp = httpx.post(
            token_url,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("ramp_refresh_transport_error", error_class=type(exc).__name__)
        raise TransientRampError(f"Ramp refresh unreachable: {exc}") from exc
    if resp.status_code != 200:
        logger.warning(
            "ramp_refresh_rejected", status=resp.status_code, body=resp.text[:200]
        )
        raise PermanentRampError(
            f"Ramp refresh rejected ({resp.status_code}): reconnect required",
            status_code=resp.status_code,
        )
    try:
        body = resp.json()
        access_token = body["access_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PermanentRampError(f"Malformed refresh response: {exc}") from exc
    return {
        "access_token": access_token,
        "refresh_token": body.get("refresh_token") or "",
        "expires_in": int(body.get("expires_in", 3600)),
        "scope": body.get("scope") or body.get("scopes") or "",
    }


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
        """
            It is the only place where the application code touches
            the internet to talk to RAMP
        """
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
        start_date: str | None = None,  # YYYY-MM-DD
        end_date: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch a single page of records from Ramp.

        Args:
            entity: Ramp entity name (e.g., "card_transactions", "bills").
            cursor: Opaque pagination cursor from previous page.
            page_size: Number of records per page.

        Returns:
            Tuple of (records_list, next_cursor_or_None).
        """
        params: dict[str, Any] = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor

        def _as_datetime(v: str, end: bool = False) -> str:
            v = v.strip()
            if "T" in v:
                return v if v.endswith("Z") else v + "Z"
            return f"{v}T{'23:59:59' if end else '00:00:00'}Z"

        is_txn = (entity == "card_transactions")  # mapped to /transactions at :196
        if start_date:
            params["from_date"] = _as_datetime(start_date, end=False) if is_txn else start_date
        if end_date:
            params["to_date"] = _as_datetime(end_date, end=True) if is_txn else end_date

        api_path = {"card_transactions":"transactions","bills":"bills"}.get(entity, entity)
        data = self._request("GET", f"/developer/v1/{api_path}", params=params)
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
