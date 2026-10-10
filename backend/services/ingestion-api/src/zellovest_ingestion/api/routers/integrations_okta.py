"""Okta OAuth lifecycle router: connect (authorize URL) + callback (token exchange) + status.
Mirrors the Ramp OAuth router (``integrations.py``) for the Okta provider:

- ``POST /api/v1/integrations/okta/connect`` — Okta org-authorization-server
  authorize URL (``openid`` + ``okta.users.read`` / ``okta.apps.read`` /
  ``okta.logs.read`` + ``offline_access`` for refresh).
- ``GET /api/v1/integrations/okta/callback`` — code exchange, encrypted
  token persistence on the per-tenant ``okta`` integration row.
- ``GET /api/v1/integrations/okta/status`` — connection state for the UI.

Setup prerequisite (Okta Admin Console): Applications → Create App
Integration → OIDC → Web Application; grant types Authorization Code +
Refresh Token; sign-in redirect URI = ``OKTA_REDIRECT_URI``; assign the
app to the users/groups whose directories should sync.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.models import TenantIntegration
from zellovest_shared.db.repository import aupsert_integration
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.integrations import ConnectRequest, ConnectResponse
from zellovest_shared.security.crypto import encrypt_token, generate_nonce
from zellovest_shared.security.oauth_state import consume_state, create_state

from zellovest_ingestion.api.deps import get_app_settings, get_db_session, get_redis_client
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.services.okta_oauth import (
    DEFAULT_OKTA_SCOPES,
    OKTA_PROVIDER,
    OktaOAuthExchangeError,
    build_okta_authorize_url,
    exchange_okta_code_for_tokens,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/integrations/okta", tags=["integrations"])
# Unprefixed alias router: serves GET /okta/callback (see callback_alias).
alias_router = APIRouter(tags=["integrations"])

# The callback route path served by this router (under the /api/v1 prefix).
CALLBACK_PATH = "/api/v1/integrations/okta/callback"
# Legacy short callback path, served as an alias below. Some Okta tenants
# already whitelist this shorter URL, and Okta compares redirect URIs
# exactly — so both forms are accepted server-side.
CALLBACK_ALIAS_PATH = "/okta/callback"
ACCEPTED_CALLBACK_SUFFIXES = (CALLBACK_PATH, CALLBACK_ALIAS_PATH)


def _require_oauth_config(settings: IngestionAPISettings) -> None:
    """Fail fast when the deployment has no Okta OAuth app configured.

    Also rejects a redirect URI that does not point at this router's
    callback — the most common cause of "404 after Okta login". The
    process must be restarted after fixing ``backend/.env`` because
    uvicorn ``--reload`` does not re-read env files.

    Args:
        settings: Ingestion API settings.

    Raises:
        HTTPException: 400 describing the missing ``OKTA_DOMAIN`` /
            ``OKTA_CLIENT_ID`` / ``OKTA_CLIENT_SECRET`` env vars, or a
            redirect URI pointing at a non-existent callback path.
    """
    if not settings.okta_domain or not settings.okta_client_id or not settings.okta_client_secret:
        raise HTTPException(
            status_code=400,
            detail="Okta OAuth is not configured (need OKTA_DOMAIN, OKTA_CLIENT_ID, OKTA_CLIENT_SECRET)",
        )
    callback_path = urlparse(settings.okta_redirect_uri).path or ""
    if not callback_path.endswith(ACCEPTED_CALLBACK_SUFFIXES):
        raise HTTPException(
            status_code=400,
            detail=(
                f"OKTA_REDIRECT_URI path must end with one of {list(ACCEPTED_CALLBACK_SUFFIXES)} "
                f"(got {settings.okta_redirect_uri!r}); fix backend/.env, register the same "
                "URL on the Okta app, and restart uvicorn"
            ),
        )


@router.post("/connect", response_model=ConnectResponse, status_code=200)
def connect(
    body: ConnectRequest | None = None,
    settings: IngestionAPISettings = Depends(get_app_settings),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> ConnectResponse:
    """Generate the Okta OAuth authorization URL with CSRF state and requested scopes.

    Args:
        body: Optional tenant binding and scopes for this OAuth flow.

    Returns:
        Authorization URL + single-use state token.
    """
    _require_oauth_config(settings)
    tenant_id = body.tenant_id if (body and body.tenant_id) else "default-org"
    scopes = body.scopes if (body and body.scopes) else DEFAULT_OKTA_SCOPES
    state = create_state(
        redis_client, tenant_id, settings.oauth_state_ttl_seconds, provider=OKTA_PROVIDER
    )
    url = build_okta_authorize_url(
        settings.okta_domain,
        client_id=settings.okta_client_id,
        redirect_uri=settings.okta_redirect_uri,
        state=state,
        scopes=scopes,
    )
    logger.info(
        "okta_oauth_connect_issued",
        tenant_id=tenant_id,
        scopes=scopes,
        redirect_uri=settings.okta_redirect_uri,
    )
    return ConnectResponse(
        authorization_url=url, state=state, expires_in=settings.oauth_state_ttl_seconds
    )


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    settings: IngestionAPISettings = Depends(get_app_settings),
    redis_client: redis.Redis = Depends(get_redis_client),
    session: AsyncSession = Depends(get_db_session),
):
    """Handle the OAuth redirect at the canonical callback path."""
    return await _handle_okta_callback(request, code, state, settings, redis_client, session)


@alias_router.get("/okta/callback")
async def callback_alias(
    request: Request,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    settings: IngestionAPISettings = Depends(get_app_settings),
    redis_client: redis.Redis = Depends(get_redis_client),
    session: AsyncSession = Depends(get_db_session),
):
    """Handle the OAuth redirect at the legacy short callback path.

    Serves tenants whose Okta app whitelists the shorter URL — Okta
    compares redirect URIs exactly, so both forms are served rather
    than forcing a console change.
    """
    return await _handle_okta_callback(request, code, state, settings, redis_client, session)


async def _handle_okta_callback(
    request: Request,
    code: str,
    state: str,
    settings: IngestionAPISettings,
    redis_client: redis.Redis,
    session: AsyncSession,
):
    """Handle the OAuth redirect: verify state, exchange code, persist tokens.

    Tokens are AES-256-GCM encrypted before persistence; raw secrets are
    never logged or returned. The stored refresh token (``offline_access``)
    lets sync workers renew the hourly access token without reconnects.

    For browser visits (Accept: text/html), redirects back to the Next.js UI
    at /integrations with the connection status query param.
    For API consumers, returns a JSON response.

    Raises:
        HTTPException: 400 on invalid/expired state, 502 on provider failure.
    """
    accept_header = request.headers.get("accept", "")
    is_browser_request = "text/html" in accept_header

    tenant_id = consume_state(redis_client, state, expected_provider=OKTA_PROVIDER)
    if tenant_id is None:
        logger.warning("okta_oauth_callback_bad_state")
        if is_browser_request:
            return RedirectResponse(
                url=f"{settings.frontend_url}/integrations?status=error&message=invalid_or_expired_state",
                status_code=302,
            )
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        tokens = await exchange_okta_code_for_tokens(
            settings.okta_domain,
            client_id=settings.okta_client_id,
            client_secret=settings.okta_client_secret,
            code=code,
            redirect_uri=settings.okta_redirect_uri,
        )
    except OktaOAuthExchangeError as exc:
        logger.warning("okta_oauth_callback_exchange_failed", tenant_id=tenant_id, error=str(exc))
        if is_browser_request:
            return RedirectResponse(
                url=f"{settings.frontend_url}/integrations?status=error&message=token_exchange_failed",
                status_code=302,
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    # Each token gets its own fresh nonce; both are stored (migration 0009)
    # so access renewal via the refresh token keeps working.
    key = settings.credentials_encryption_key
    access_nonce = generate_nonce()
    access_ct, _ = encrypt_token(tokens.access_token, key, access_nonce)
    refresh_ct, refresh_nonce = encrypt_token(tokens.refresh_token or "", key)
    await aupsert_integration(
        session,
        tenant_id=tenant_id,
        provider=OKTA_PROVIDER,
        encrypted_access_token=access_ct,
        encrypted_refresh_token=refresh_ct,
        access_nonce=access_nonce,
        refresh_nonce=refresh_nonce,
        token_expires_at=expires_at,
        scopes=tokens.scopes,
    )
    await session.commit()
    logger.info("okta_oauth_callback_stored", tenant_id=tenant_id, scopes=tokens.scopes)

    if is_browser_request:
        return RedirectResponse(
            url=f"{settings.frontend_url}/integrations?status=connected&provider=okta&tenant_id={tenant_id}",
            status_code=302,
        )
    return {"connected": True, "tenant_id": tenant_id, "provider": OKTA_PROVIDER}


@router.get("/status", status_code=200)
async def status(
    tenant_id: str = Query(default="default-org"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Check whether the Okta integration is active for this tenant."""
    stmt = select(TenantIntegration).where(
        TenantIntegration.tenant_id == tenant_id,
        TenantIntegration.provider == OKTA_PROVIDER,
    )
    result = await session.execute(stmt)
    integration = result.scalar_one_or_none()

    if integration is None:
        return {
            "connected": False,
            "provider": OKTA_PROVIDER,
            "tenant_id": tenant_id,
            "status": "DISCONNECTED",
            "scopes": [],
            "updated_at": None,
        }

    status_str = (
        integration.connection_status.value
        if hasattr(integration.connection_status, "value")
        else str(integration.connection_status)
    )
    return {
        "connected": status_str.upper() == "ACTIVE",
        "provider": OKTA_PROVIDER,
        "tenant_id": tenant_id,
        "status": status_str,
        "scopes": integration.scopes or [],
        "token_expires_at": integration.token_expires_at.isoformat() if integration.token_expires_at else None,
        "updated_at": integration.updated_at.isoformat() if integration.updated_at else None,
    }
