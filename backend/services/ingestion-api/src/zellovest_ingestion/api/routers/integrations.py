"""OAuth lifecycle router: connect (authorize URL) + callback (token exchange) + status."""

from datetime import UTC, datetime, timedelta
import json

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zellovest_shared.db.models import TenantIntegration, effective_connection_status
from zellovest_shared.db.repository import adelete_integration, aupsert_integration
from zellovest_shared.logging_conf import get_logger
from zellovest_shared.schemas.integrations import (
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    DisconnectResponse,
)
from zellovest_shared.security.crypto import encrypt_token, generate_nonce
from zellovest_shared.security.oauth_state import consume_state, create_state

from zellovest_ingestion.api.deps import get_app_settings, get_db_session, get_redis_client
from zellovest_ingestion.config import IngestionAPISettings
from zellovest_ingestion.services.ramp_oauth import (
    DEFAULT_RAMP_SCOPES,
    OAuthExchangeError,
    build_authorize_url,
    exchange_code_for_tokens,
)
from zellovest_ingestion.services.integration_tokens import has_refresh_token

logger = get_logger(__name__)
router = APIRouter(prefix="/integrations/ramp", tags=["integrations"])

STATUS_CACHE_TTL_SECONDS = 60


def _status_cache_key(tenant_id: str, provider: str = "ramp") -> str:
    """Redis key for caching integration connection status."""
    return f"integration:status:{tenant_id}:{provider}"


@router.post("/connect", response_model=ConnectResponse, status_code=200)
def connect(
    body: ConnectRequest | None = None,
    settings: IngestionAPISettings = Depends(get_app_settings),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> ConnectResponse:
    """Generate the Ramp OAuth authorization URL with CSRF state and requested scopes.

    Args:
        body: Optional tenant binding and scopes for this OAuth flow.

    Returns:
        Authorization URL + single-use state token.
    """
    tenant_id = body.tenant_id if (body and body.tenant_id) else "default-org"
    scopes = body.scopes if (body and body.scopes) else DEFAULT_RAMP_SCOPES
    state = create_state(redis_client, tenant_id, settings.oauth_state_ttl_seconds, provider="ramp")
    url = build_authorize_url(
        settings.ramp_auth_url,
        client_id=settings.ramp_client_id,
        redirect_uri=settings.ramp_redirect_uri,
        state=state,
        scopes=scopes,
    )
    logger.info("oauth_connect_issued", tenant_id=tenant_id, scopes=scopes)
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
    never logged or returned.

    For browser visits (Accept: text/html), redirects back to the Next.js UI
    at /integrations with the connection status query param.
    For API consumers, returns a JSON response.

    Raises:
        HTTPException: 400 on invalid/expired state, 502 on provider failure.
    """
    accept_header = request.headers.get("accept", "")
    is_browser_request = "text/html" in accept_header

    tenant_id = consume_state(redis_client, state, expected_provider="ramp")
    if tenant_id is None:
        logger.warning("oauth_callback_bad_state")
        if is_browser_request:
            return RedirectResponse(
                url=f"{settings.frontend_url}/integrations?status=error&message=invalid_or_expired_state",
                status_code=302,
            )
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        tokens = await exchange_code_for_tokens(
            settings.ramp_token_url,
            client_id=settings.ramp_client_id,
            client_secret=settings.ramp_client_secret,
            code=code,
            redirect_uri=settings.ramp_redirect_uri,
        )
    except OAuthExchangeError as exc:
        logger.warning("oauth_callback_exchange_failed", tenant_id=tenant_id, error=str(exc))
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
    access_ct, access_nonce = encrypt_token(tokens.access_token, key)
    refresh_ct, refresh_nonce = encrypt_token(tokens.refresh_token or "", key)
    await aupsert_integration(
        session,
        tenant_id=tenant_id,
        provider="ramp",
        encrypted_access_token=access_ct,
        encrypted_refresh_token=refresh_ct,
        access_nonce=access_nonce,
        refresh_nonce=refresh_nonce,
        token_expires_at=expires_at,
        scopes=tokens.scopes,
    )

    await session.commit()

    if redis_client is not None:
        try:
            redis_client.delete(_status_cache_key(tenant_id, "ramp"))
        except Exception:
            pass

    logger.info(
        "oauth_callback_stored",
        tenant_id=tenant_id,
        scopes=tokens.scopes,
        refresh_token_received=bool(tokens.refresh_token),
    )

    try:
        from zellovest_ingestion.services.sync_dispatcher import dispatch_sync_task

        for entity in ("card_transactions", "bills"):
            await dispatch_sync_task(session, tenant_id=tenant_id, source="ramp", entity=entity)
        await session.commit()
    except Exception as sync_exc:
        logger.warning(
            "ramp_initial_sync_skipped",
            tenant_id=tenant_id,
            error_class=type(sync_exc).__name__,
        )

    if is_browser_request:
        return RedirectResponse(
            url=f"{settings.frontend_url}/integrations?status=connected&provider=ramp&tenant_id={tenant_id}",
            status_code=302,
        )
    return {"connected": True, "tenant_id": tenant_id, "provider": "ramp"}


@router.get("/status", status_code=200)
async def status(
    tenant_id: str = Query(default="default-org"),
    fresh: bool = Query(default=False),
    settings: IngestionAPISettings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> dict:
    """Check whether Ramp integration is active for this tenant.

    An expired access token remains connected when a decryptable refresh
    token is stored. The ingestion worker renews it on the next sync; only
    a missing/rejected refresh grant needs a user reconnect.
    """
    cache_key = _status_cache_key(tenant_id, "ramp")
    if not fresh and redis_client is not None:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                raw_str = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
                return json.loads(raw_str)
        except Exception:
            pass

    stmt = select(TenantIntegration).where(
        TenantIntegration.tenant_id == tenant_id,
        TenantIntegration.provider == "ramp",
    )
    result = await session.execute(stmt)
    integration = result.scalar_one_or_none()

    if integration is None:
        resp_data = {
            "connected": False,
            "provider": "ramp",
            "tenant_id": tenant_id,
            "status": "DISCONNECTED",
            "scopes": [],
            "needs_reconnect": False,
            "refresh_available": False,
            "last_error": None,
            "token_expires_at": None,
            "updated_at": None,
        }
        if redis_client is not None:
            try:
                redis_client.set(cache_key, json.dumps(resp_data), ex=STATUS_CACHE_TTL_SECONDS)
            except Exception:
                pass
        return resp_data

    refresh_available = has_refresh_token(
        integration, settings.credentials_encryption_key
    )
    effective = effective_connection_status(
        integration.connection_status,
        integration.token_expires_at,
        refresh_token_available=refresh_available,
    )
    status_str = effective.value
    needs_reconnect = effective.value in ("EXPIRED", "REVOKED")
    resp_data = {
        "connected": effective.value == "ACTIVE",
        "provider": "ramp",
        "tenant_id": tenant_id,
        "status": status_str,
        "scopes": integration.scopes or [],
        "needs_reconnect": needs_reconnect,
        "refresh_available": refresh_available,
        "last_error": integration.last_error,
        "token_expires_at": (
            integration.token_expires_at.isoformat() if integration.token_expires_at else None
        ),
        "updated_at": integration.updated_at.isoformat() if integration.updated_at else None,
    }
    if redis_client is not None:
        try:
            redis_client.set(cache_key, json.dumps(resp_data), ex=STATUS_CACHE_TTL_SECONDS)
        except Exception:
            pass
    return resp_data


@router.post("/disconnect", response_model=DisconnectResponse, status_code=200)
@router.delete("/disconnect", response_model=DisconnectResponse, status_code=200)
@router.delete("", response_model=DisconnectResponse, status_code=200)
async def disconnect(
    body: DisconnectRequest | None = None,
    tenant_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> DisconnectResponse:
    """Disconnect Ramp integration by deleting credentials for this tenant.

    Purges the stored encrypted OAuth tokens so background syncs halt and
    the integration status transitions to DISCONNECTED.

    Args:
        body: Optional request body specifying tenant_id.
        tenant_id: Optional query parameter for tenant_id.
        session: Database session.
        redis_client: Redis client for cache invalidation.

    Returns:
        Disconnect confirmation response.
    """
    resolved_tenant = (
        (body.tenant_id if body and body.tenant_id else None) or tenant_id or "default-org"
    )
    await adelete_integration(session, tenant_id=resolved_tenant, provider="ramp")
    await session.commit()

    if redis_client is not None:
        try:
            redis_client.delete(_status_cache_key(resolved_tenant, "ramp"))
        except Exception:
            pass

    logger.info("ramp_integration_disconnected", tenant_id=resolved_tenant)
    return DisconnectResponse(
        tenant_id=resolved_tenant,
        provider="ramp",
        disconnected=True,
        status="DISCONNECTED",
    )

