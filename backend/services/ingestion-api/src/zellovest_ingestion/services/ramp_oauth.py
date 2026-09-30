"""Ramp OAuth helpers: authorize URL builder + code-for-token exchange."""

from urllib.parse import urlencode

import httpx

from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.integrations import TokenExchangeResult

logger = get_logger(__name__)

DEFAULT_RAMP_SCOPES = ["transactions:read", "bills:read", "offline_access"]


def build_authorize_url(
    auth_base_url: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: list[str] | None = None,
) -> str:
    """Build the Ramp OAuth 2.0 authorization URL with CSRF state.

    Args:
        auth_base_url: Ramp authorize endpoint.
        client_id: OAuth client id.
        redirect_uri: Registered callback URL.
        state: Cryptographically secure single-use CSRF token.
        scopes: Optional OAuth scopes (defaults to transactions:read, bills:read, offline_access).

    Returns:
        Full redirect URL for the caller.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    effective_scopes = scopes if scopes is not None else DEFAULT_RAMP_SCOPES
    if effective_scopes:
        params["scope"] = " ".join(effective_scopes)
    return f"{auth_base_url}?{urlencode(params)}"


class OAuthExchangeError(Exception):
    """Raised when Ramp's token endpoint rejects the exchange."""


async def exchange_code_for_tokens(
    token_url: str,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout_seconds: float = 15.0,
) -> TokenExchangeResult:
    """Exchange an authorization code for access/refresh tokens.

    Ramp requires HTTP Basic Authentication with client_id:client_secret and
    application/x-www-form-urlencoded payload.

    Args:
        token_url: Ramp token endpoint.
        client_id: OAuth client id.
        client_secret: OAuth client secret (never logged).
        code: Authorization code from the callback.
        redirect_uri: Must match the authorize request.
        timeout_seconds: HTTP timeout bound.

    Raises:
        OAuthExchangeError: On non-2xx or malformed provider responses.
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                auth=(client_id, client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("oauth_exchange_transport_error", error_class=type(exc).__name__)
            raise OAuthExchangeError("token endpoint unreachable") from exc

    if response.status_code != 200:
        logger.warning(
            "oauth_exchange_rejected",
            status_code=response.status_code,
            response_body=response.text[:500],
        )
        raise OAuthExchangeError(f"token endpoint returned {response.status_code}: {response.text[:200]}")

    try:
        body = response.json()
        raw_scopes = body.get("scopes") or body.get("scope") or []
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
        raise OAuthExchangeError(f"malformed token response: {exc}") from exc
