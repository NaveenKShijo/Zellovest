"""Okta OAuth helpers: authorize URL builder + code/refresh token exchange.

Mirrors :mod:`zellovest_ingestion.services.ramp_oauth` for the Okta
provider. Okta specifics that differ from Ramp:

- Endpoints live on the **org authorization server**,
  ``https://{domain}/oauth2/v1/authorize`` and ``.../oauth2/v1/token``.
  Okta API scopes (``okta.users.read`` & co.) only mint there — never on
  a custom (``/oauth2/default/...``) authorization server.
- Token exchange authenticates with HTTP Basic
  (``client_id:client_secret``) and a form-encoded body of
  ``grant_type`` / ``code`` / ``redirect_uri``.
- Offline access (refresh tokens) requires the ``offline_access`` scope;
  refresh uses ``grant_type=refresh_token`` with the same Basic auth.
"""

from urllib.parse import urlencode

import httpx

from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.integrations import TokenExchangeResult

logger = get_logger(__name__)

OKTA_PROVIDER = "okta"

DEFAULT_OKTA_SCOPES = [
    "openid",
    "okta.users.read",
    "okta.apps.read",
    "okta.logs.read",
    "offline_access",
]


def okta_domain_base(domain: str) -> str:
    """Normalize an Okta org domain to ``https://{domain}`` (no path, no trailing slash).

    Args:
        domain: Bare domain (``myorg.okta.com``) or full URL; leading
            ``https://`` and trailing slashes are tolerated.

    Returns:
        Canonical ``https://{domain}`` base URL.
    """
    cleaned = domain.strip().rstrip("/")
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    return f"https://{cleaned}"


def okta_authorize_url(domain: str) -> str:
    """Org authorization server authorize endpoint for an Okta domain."""
    return f"{okta_domain_base(domain)}/oauth2/v1/authorize"


def okta_token_url(domain: str) -> str:
    """Org authorization server token endpoint for an Okta domain."""
    return f"{okta_domain_base(domain)}/oauth2/v1/token"


def build_okta_authorize_url(
    domain: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: list[str] | None = None,
) -> str:
    """Build the Okta OAuth 2.0 authorization URL with CSRF state.

    Args:
        domain: Okta org domain (``myorg.okta.com``).
        client_id: OIDC app client id registered in that Okta org.
        redirect_uri: Registered callback URL (must match the Okta app).
        state: Cryptographically secure single-use CSRF token.
        scopes: Optional OAuth scopes (defaults to openid + users/apps/logs
            read plus ``offline_access`` for refresh tokens).

    Returns:
        Full redirect URL for the caller.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    effective_scopes = scopes if scopes is not None else DEFAULT_OKTA_SCOPES
    if effective_scopes:
        params["scope"] = " ".join(effective_scopes)
    return f"{okta_authorize_url(domain)}?{urlencode(params)}"


class OktaOAuthExchangeError(Exception):
    """Raised when Okta's token endpoint rejects the exchange or refresh."""


def _parse_token_body(body: dict) -> TokenExchangeResult:
    """Normalize an Okta token response (shared by code exchange + refresh).

    Args:
        body: Decoded JSON from the token endpoint.

    Raises:
        OktaOAuthExchangeError: On missing access token or bad types.
    """
    try:
        raw_scopes = body.get("scope") or body.get("scopes") or []
        if isinstance(raw_scopes, str):
            scopes_list = raw_scopes.split()
        elif isinstance(raw_scopes, list):
            scopes_list = [str(s) for s in raw_scopes]
        else:
            scopes_list = []
        return TokenExchangeResult(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token") or "",
            expires_in=int(body.get("expires_in", 3600)),
            scopes=scopes_list,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise OktaOAuthExchangeError(f"malformed token response: {exc}") from exc


async def exchange_okta_code_for_tokens(
    domain: str,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout_seconds: float = 15.0,
) -> TokenExchangeResult:
    """Exchange an authorization code for access/refresh tokens.

    Authenticates with HTTP Basic (``client_id:client_secret``) per the
    Okta docs; the form body carries only grant/code/redirect.

    Args:
        domain: Okta org domain.
        client_id: OIDC app client id (never logged; secret likewise).
        client_secret: OIDC app client secret.
        code: Authorization code from the callback.
        redirect_uri: Must match the authorize request exactly.
        timeout_seconds: HTTP timeout bound.

    Raises:
        OktaOAuthExchangeError: On transport failure, non-2xx, or
            malformed provider responses.
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            response = await client.post(
                okta_token_url(domain),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                auth=(client_id, client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("okta_oauth_exchange_transport_error", error_class=type(exc).__name__)
            raise OktaOAuthExchangeError("token endpoint unreachable") from exc

    if response.status_code != 200:
        logger.warning(
            "okta_oauth_exchange_rejected",
            status_code=response.status_code,
            response_body=response.text[:500],
        )
        raise OktaOAuthExchangeError(
            f"token endpoint returned {response.status_code}: {response.text[:200]}"
        )

    try:
        return _parse_token_body(response.json())
    except ValueError as exc:
        raise OktaOAuthExchangeError(f"malformed token response: {exc}") from exc


async def refresh_okta_access_token(
    domain: str,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout_seconds: float = 15.0,
) -> TokenExchangeResult:
    """Refresh an expired Okta access token (requires ``offline_access`` grant).

    Args:
        domain: Okta org domain.
        client_id: OIDC app client id.
        client_secret: OIDC app client secret.
        refresh_token: Previously issued refresh token (never logged).
        timeout_seconds: HTTP timeout bound.

    Raises:
        OktaOAuthExchangeError: On transport failure, non-2xx (e.g. revoked
            grant — caller should prompt reconnect), or malformed responses.
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            response = await client.post(
                okta_token_url(domain),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(client_id, client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("okta_oauth_refresh_transport_error", error_class=type(exc).__name__)
            raise OktaOAuthExchangeError("token endpoint unreachable") from exc

    if response.status_code != 200:
        logger.warning(
            "okta_oauth_refresh_rejected",
            status_code=response.status_code,
            response_body=response.text[:500],
        )
        raise OktaOAuthExchangeError(
            f"token endpoint returned {response.status_code}: {response.text[:200]}"
        )

    try:
        return _parse_token_body(response.json())
    except ValueError as exc:
        raise OktaOAuthExchangeError(f"malformed token response: {exc}") from exc
