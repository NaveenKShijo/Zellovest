"""Password hashing for custom local authentication.

Replaces the outsourced WSO2/Asgardeo password store with a local,
auditable scheme so the team owns the full credential lifecycle.

Scheme (stdlib-only, no extra dependency):
- ``PBKDF2-HMAC-SHA256`` with a per-password 16-byte random salt and
  210,000 iterations. One-way: the plaintext is never stored; verification
  re-derives the key with the stored salt/params and compares in constant
  time (``hmac.compare_digest``).
- Stored format: ``$pbkdf2-sha256$<iterations>$<salt_b64>$<hash_b64>`` —
  salt, cost and hash travel together, so no separate salt column.
- Rate limiting / lockout and peppering are deployment concerns layered
  on top (see auth router: 401 parity, structured logging, no user
  enumeration via distinct messages).
"""

import base64
import hashlib
import hmac
import os

ALGORITHM = "pbkdf2-sha256"
ITERATIONS = 210_000
SALT_BYTES = 16


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with PBKDF2 + random salt.

    Args:
        plaintext: Raw password from signup / password change (never logged).

    Returns:
        Encoded ``$pbkdf2-sha256$...`` string safe for DB storage.
    """
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt, ITERATIONS)
    return (
        f"${ALGORITHM}${ITERATIONS}"
        f"${base64.b64encode(salt).decode()}"
        f"${base64.b64encode(dk).decode()}"
    )


def verify_password(plaintext: str, password_hash: str) -> bool:
    """Verify a candidate password against a stored hash.

    Args:
        plaintext: Candidate password from the login form.
        password_hash: Stored hash from the users table.

    Returns:
        True when the candidate matches; False otherwise (including
        malformed hashes — never raises on attacker input).
    """
    try:
        parts = password_hash.split("$")
        # ['', 'pbkdf2-sha256', '<iter>', '<salt>', '<hash>']
        if len(parts) != 5 or parts[1] != ALGORITHM:
            return False
        iterations = int(parts[2])
        salt = base64.b64decode(parts[3])
        expected = base64.b64decode(parts[4])
        candidate = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False
