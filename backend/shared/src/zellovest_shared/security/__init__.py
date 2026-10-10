"""Security package exports."""

from zellovest_shared.security.auth import (
    DEFAULT_INVITE_TTL_DAYS,
    create_user,
    generate_invite_token,
    get_invite_by_token,
    get_user_by_email,
    get_user_by_id,
    hash_invite_token,
    normalize_email,
    validate_email,
    validate_password,
)
from zellovest_shared.security.crypto import (
    DecryptionError,
    decrypt_token,
    encrypt_token,
    generate_key,
    generate_nonce,
)
from zellovest_shared.security.jwt import (
    create_access_token,
    create_user_access_token,
    decode_token,
    get_tenant_id_from_token,
)
from zellovest_shared.security.oauth_state import (
    OAuthState,
    OAuthStateStore,
    consume_state,
    create_state,
)
from zellovest_shared.security.passwords import hash_password, verify_password
from zellovest_shared.security.webhook import InvalidSignatureError, verify_signature

__all__ = [
    "DecryptionError",
    "InvalidSignatureError",
    "OAuthState",
    "OAuthStateStore",
    "DEFAULT_INVITE_TTL_DAYS",
    "consume_state",
    "create_access_token",
    "create_state",
    "create_user",
    "create_user_access_token",
    "decode_token",
    "decrypt_token",
    "encrypt_token",
    "generate_key",
    "generate_nonce",
    "generate_invite_token",
    "get_invite_by_token",
    "get_tenant_id_from_token",
    "get_user_by_email",
    "get_user_by_id",
    "hash_invite_token",
    "hash_password",
    "normalize_email",
    "validate_email",
    "validate_password",
    "verify_password",
    "verify_signature",
]
