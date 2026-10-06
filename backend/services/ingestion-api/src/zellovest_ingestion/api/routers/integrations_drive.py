"""Google Drive OAuth lifecycle router: connect + callback + status.

Mirrors the Ramp OAuth router (``integrations.py``) for the Drive provider —
the "polling" leg of Drive ingestion (OAuth connection that polling, webhook
watch setup, and pull sync all build on):

- ``POST /api/v1/integrations/google-drive/connect`` — Google authorize URL.
- ``GET /api/v1/integrations/google-drive/callback`` — code exchange, token
  persistence, best-effort ``changes.watch`` setup.
- ``GET /api/v1/integrations/google-drive/status`` — connection + watch health.
"""

from datetime import UTC, datetime, timedelta

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zellovest_ingestion.api.deps import get_app_settings, get_db_session, get_redis_client
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.services.drive_oauth import (
    DEFAULT_DRIVE_SCOPES,
    DriveOAuthExchangeError,
    build_drive_authorize_url,
    exchange_drive_code_for_tokens,
)
from zellovest_ingestion.services.drive_watch import DRIVE_PROVIDER, ensure_drive_watch, get_drive_watch
from zellovest_shared.db.models import TenantIntegration
from zellovest_shared.db.repository import aupsert_integration
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.integrations import ConnectRequest, ConnectResponse
from zellovest_shared.security.crypto import encrypt_token
from zellovest_shared.security.oauth_state import consume_state, create_state

logger = get_logger(__name__)
router = APIRouter(prefix="/integrations/google-drive", tags=["integrations"])


@router.post("/connect", response_model=ConnectResponse, status_code=200)
def connect(
    body: ConnectRequest | None = None,
    settings: IngestionAPISettings = Depends(get_app_settings),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> ConnectResponse:
    """Generate the Google OAuth authorization URL with provider-bound CSRF state.

    Args:
        body: Optional tenant binding and scopes for this OAuth flow.

    Returns:
        Authorization URL + single-use state token.
    """
    tenant_id = body.tenant_id if (body and body.tenant_id) else "default-org"
    scopes = body.scopes if (body and body.scopes) else DEFAULT_DRIVE_SCOPES
    state = create_state(
        redis_client, tenant_id, settings.oauth_state_ttl_seconds, provider=DRIVE_PROVIDER
    )
    url = build_drive_authorize_url(
        settings.google_drive_auth_url,
        client_id=settings.google_drive_client_id,
        redirect_uri=settings.google_drive_redirect_uri,
        state=state,
        scopes=scopes,
    )
    logger.info("drive_oauth_connect_issued", tenant_id=tenant_id, scopes=scopes)
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
    """Handle the OAuth redirect: verify state, exchange code, persist tokens.

    Tokens are AES-256-GCM encrypted before persistence; raw secrets are
    never logged or returned. A ``changes.watch`` push channel is then created
    best-effort (failures only warn — pull sync keeps working).

    For browser visits (Accept: text/html), redirects back to the Next.js UI
    at /integrations with the connection status query param.
    For API consumers, returns a JSON response.

    Raises:
        HTTPException: 400 on invalid/expired state, 502 on provider failure.
    """
    accept_header = request.headers.get("accept", "")
    is_browser_request = "text/html" in accept_header

    tenant_id = consume_state(redis_client, state, expected_provider=DRIVE_PROVIDER)
    if tenant_id is None:
        logger.warning("drive_oauth_callback_bad_state")
        if is_browser_request:
            return RedirectResponse(
                url=f"{settings.frontend_url}/integrations?status=error&message=invalid_or_expired_state",
                status_code=302,
            )
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        tokens = await exchange_drive_code_for_tokens(
            settings.google_drive_token_url,
            client_id=settings.google_drive_client_id,
            client_secret=settings.google_drive_client_secret,
            code=code,
            redirect_uri=settings.google_drive_redirect_uri,
        )
    except DriveOAuthExchangeError as exc:
        logger.warning("drive_oauth_callback_exchange_failed", tenant_id=tenant_id, error=str(exc))
        if is_browser_request:
            return RedirectResponse(
                url=f"{settings.frontend_url}/integrations?status=error&message=token_exchange_failed",
                status_code=302,
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    # Encrypt both tokens under one fresh nonce (stored once per row).
    access_ct, nonce = encrypt_token(tokens.access_token, settings.credentials_encryption_key)
    refresh_ct, _ = encrypt_token(tokens.refresh_token or "", settings.credentials_encryption_key)
    await aupsert_integration(
        session,
        tenant_id=tenant_id,
        provider=DRIVE_PROVIDER,
        encrypted_access_token=access_ct,
        encrypted_refresh_token=refresh_ct,
        encryption_nonce=nonce,
        token_expires_at=expires_at,
        scopes=tokens.scopes,
    )
    await session.commit()
    logger.info("drive_oauth_callback_stored", tenant_id=tenant_id, scopes=tokens.scopes)

    # Best-effort push-channel setup so Drive change events arrive at
    # POST /api/v1/webhooks/google-drive. Never fails the OAuth flow.
    ensure_drive_watch(
        redis_client,
        tenant_id=tenant_id,
        access_token=tokens.access_token,
        webhook_callback_url=settings.google_drive_webhook_callback_url,
        webhook_token=settings.google_drive_webhook_token or None,
    )

    if is_browser_request:
        return RedirectResponse(
            url=f"{settings.frontend_url}/integrations?status=connected&provider=google-drive&tenant_id={tenant_id}",
            status_code=302,
        )
    return {"connected": True, "tenant_id": tenant_id, "provider": "google-drive"}


@router.get("/status", status_code=200)
async def status(
    tenant_id: str = Query(default="default-org"),
    session: AsyncSession = Depends(get_db_session),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> dict:
    """Check whether the Google Drive integration is active for this tenant."""
    stmt = select(TenantIntegration).where(
        TenantIntegration.tenant_id == tenant_id,
        TenantIntegration.provider == DRIVE_PROVIDER,
    )
    result = await session.execute(stmt)
    integration = result.scalar_one_or_none()

    watch = get_drive_watch(redis_client, tenant_id)

    if integration is None:
        return {
            "connected": False,
            "provider": "google-drive",
            "tenant_id": tenant_id,
            "status": "DISCONNECTED",
            "scopes": [],
            "updated_at": None,
            "watch": None,
        }

    status_str = (
        integration.connection_status.value
        if hasattr(integration.connection_status, "value")
        else str(integration.connection_status)
    )
    return {
        "connected": status_str.upper() == "ACTIVE",
        "provider": "google-drive",
        "tenant_id": tenant_id,
        "status": status_str,
        "scopes": integration.scopes or [],
        "token_expires_at": integration.token_expires_at.isoformat() if integration.token_expires_at else None,
        "updated_at": integration.updated_at.isoformat() if integration.updated_at else None,
        "watch": watch,
    }
