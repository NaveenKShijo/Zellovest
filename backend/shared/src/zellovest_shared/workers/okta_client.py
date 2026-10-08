"""Okta API client with retry-aware error hierarchy.

Mirrors :mod:`zellovest_shared.workers.ramp_client` so Celery workers fetch
Okta data directly (control plane never passes raw payloads through Redis).

Two credential flavors, chosen by the caller:

- ``SSWS``: static per-tenant API token (``Authorization: SSWS <token>``)
  from the ``okta`` row in ``tenant_integrations`` or the ``OKTA_API_TOKEN``
  deployment secret. Never expires.
- ``Bearer``: short-lived OAuth access token from the per-tenant Connect
  flow (``Authorization: Bearer <token>``). The caller refreshes it with
  :func:`refresh_access_token` (needs ``offline_access`` grant) when the
  stored ``token_expires_at`` has passed.

Pagination follows Okta's ``Link`` response header (``rel="next"``
carries the ``after`` cursor).
"""

import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

_NEXT_AFTER_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


class OktaError(Exception):
    """Base exception for Okta API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TransientOktaError(OktaError):
    """Transient Okta error (5xx, network timeout) — safe to retry."""

    pass


class RateLimitError(OktaError):
    """Okta 429 Too Many Requests — retry after backoff."""

    def __init__(self, message: str, retry_after_seconds: int = 60):
        super().__init__(message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class PermanentOktaError(OktaError):
    """Permanent Okta error (4xx except 429, e.g. 401 bad token) — do not retry."""

    pass


def parse_next_after(link_header: str | None) -> str | None:
    """Extract the ``after`` cursor from an Okta ``Link`` header, if present.

    Args:
        link_header: Raw ``Link`` response header value.

    Returns:
        The ``after`` query param of the ``rel="next"`` URL, or None.
    """
    if not link_header:
        return None
    match = _NEXT_AFTER_RE.search(link_header)
    if not match:
        return None
    try:
        return parse_qs(urlparse(match.group(1)).query).get("after", [None])[0]
    except Exception:
        return None


class OktaClient:
    """Thin wrapper around the Okta API (``https://{domain}/api/v1``)."""

    def __init__(
        self,
        domain: str,
        api_token: str,
        timeout: float = 30.0,
        scheme: Literal["SSWS", "Bearer"] = "SSWS",
    ):
        """Initialize the client.

        Args:
            domain: Okta org domain (e.g. ``myorg.okta.com``).
            api_token: SSWS API token or OAuth access token with
                ``okta.users.read``, ``okta.apps.read`` and
                ``okta.logs.read`` scopes.
            timeout: Per-request timeout in seconds.
            scheme: ``"SSWS"`` for static API tokens, ``"Bearer"`` for
                OAuth access tokens from the Connect flow.
        """
        self._base_url = f"https://{domain.strip().rstrip('/').removeprefix('https://')}/api/v1"
        self._headers = {
            "Authorization": f"{scheme} {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=timeout)

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> tuple[Any, str | None]:
        """Send one request, returning ``(body, next_after_cursor)``.

        Raises:
            RateLimitError: On 429 (honours ``x-rate-limit-reset``/``Retry-After``).
            TransientOktaError: On 5xx / timeouts / connection errors.
            PermanentOktaError: On other 4xx (bad token, forbidden scope, bad params).
        """
        url = f"{self._base_url}{path}"
        try:
            resp = self._client.request(method, url, headers=self._headers, params=params)
        except httpx.TimeoutException as exc:
            logger.warning("okta_timeout", url=url)
            raise TransientOktaError(f"Okta timeout: {exc}") from exc
        except httpx.ConnectError as exc:
            logger.warning("okta_connect_error", url=url)
            raise TransientOktaError(f"Okta connection error: {exc}") from exc

        if resp.status_code == 429:
            retry_after = int(
                resp.headers.get("x-rate-limit-reset")
                or resp.headers.get("Retry-After", "60")
            )
            logger.warning("okta_rate_limited", url=url, retry_after=retry_after)
            raise RateLimitError("Okta rate limit", retry_after_seconds=retry_after)

        if 500 <= resp.status_code < 600:
            logger.warning("okta_server_error", url=url, status=resp.status_code)
            raise TransientOktaError(f"Okta server error: {resp.status_code}")

        if 400 <= resp.status_code < 500:
            logger.warning("okta_client_error", url=url, status=resp.status_code)
            raise PermanentOktaError(f"Okta client error: {resp.status_code} - {resp.text}")

        return resp.json(), parse_next_after(resp.headers.get("Link"))

    def fetch_page(
        self,
        entity: str,
        cursor: str | None = None,
        page_size: int = 200,
        since: str | None = None,
        until: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch a single page of an Okta collection.

        Args:
            entity: One of ``"users"``, ``"apps"``, ``"logs"``.
            cursor: ``after`` cursor from the previous page's ``Link`` header.
            page_size: ``limit`` per page (Okta caps at 200 for most endpoints).
            since: ISO-8601 lower bound (System Log ``/logs`` only).
            until: ISO-8601 upper bound (System Log ``/logs`` only).

        Returns:
            Tuple of (records_list, next_after_cursor_or_None).
        """
        paths = {"users": "/users", "apps": "/apps", "logs": "/logs"}
        if entity not in paths:
            raise PermanentOktaError(f"Unknown Okta entity: {entity}")
        params: dict[str, Any] = {"limit": min(max(page_size, 1), 200)}
        if cursor:
            params["after"] = cursor
        if entity == "logs":
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            params.setdefault("sortOrder", "ASCENDING")
        body, next_after = self._request("GET", paths[entity], params=params)
        records = body if isinstance(body, list) else body.get("data", [])
        return records, next_after

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "OktaClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def refresh_access_token(
    domain: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Refresh an expired Okta OAuth access token (sync, for Celery workers).

    Calls the org authorization server (``https://{domain}/oauth2/v1/token``)
    with ``grant_type=refresh_token`` and HTTP Basic client auth — the same
    exchange the Connect flow uses, minus the browser.

    Args:
        domain: Okta org domain.
        client_id: OIDC app client id (never logged).
        client_secret: OIDC app client secret (never logged).
        refresh_token: Previously issued refresh token (never logged).
        timeout: Per-request timeout in seconds.

    Returns:
        Token response mapping with ``access_token`` and usually a rotated
        ``refresh_token``, ``expires_in`` and ``scope``.

    Raises:
        TransientOktaError: Transport failure — safe to retry.
        PermanentOktaError: Rejected grant (revoked/rotated refresh token) —
            the tenant must Reconnect; do not retry.
    """
    url = f"https://{domain.strip().rstrip('/').removeprefix('https://')}/oauth2/v1/token"
    try:
        resp = httpx.post(
            url,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("okta_refresh_transport_error", error_class=type(exc).__name__)
        raise TransientOktaError(f"Okta refresh unreachable: {exc}") from exc
    if resp.status_code != 200:
        logger.warning("okta_refresh_rejected", status=resp.status_code, body=resp.text[:200])
        raise PermanentOktaError(
            f"Okta refresh rejected ({resp.status_code}): reconnect required",
            status_code=resp.status_code,
        )
    try:
        body = resp.json()
        access_token = body["access_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PermanentOktaError(f"Malformed refresh response: {exc}") from exc
    return {
        "access_token": access_token,
        "refresh_token": body.get("refresh_token") or "",
        "expires_in": int(body.get("expires_in", 3600)),
        "scope": body.get("scope") or "",
    }
