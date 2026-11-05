"""Helpers for determining whether a provider connection can refresh."""

from zellovest_shared.db.models import TenantIntegration
from zellovest_shared.security.crypto import decrypt_token


def has_refresh_token(integration: TenantIntegration, encryption_key: str) -> bool:
    """Return whether an integration has a decryptable, non-empty refresh token.

    Older rows may have no refresh nonce, and OAuth providers can omit a
    refresh token when offline access was not granted. Neither case can
    silently renew an expired access token.

    Args:
        integration: Persisted provider integration row.
        encryption_key: Base64-encoded credential encryption key.

    Returns:
        True only when the stored refresh token decrypts to a non-empty value.
    """
    if not integration.encrypted_refresh_token or not integration.refresh_nonce:
        return False
    try:
        token = decrypt_token(
            integration.encrypted_refresh_token,
            integration.refresh_nonce,
            encryption_key,
        )
    except Exception:
        return False
    return bool(token.strip())
