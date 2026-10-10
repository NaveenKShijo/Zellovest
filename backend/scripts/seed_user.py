"""Seed a local user account (first member and/or public demo account).

Why a script and not a web endpoint? The web app has no public signup
(single-tenant, invite-only), and invites need an existing logged-in
member — a chicken-and-egg problem. The deployer breaks it from the
server shell, where no attacker can reach:

    FIRST_USER_EMAIL="you@company.com" FIRST_USER_PASSWORD="..." \\
        uv run python scripts/seed_user.py --name "Your Name"

    DEMO_EMAIL="demo@zellovest.ai" DEMO_PASSWORD="..." \\
        uv run python scripts/seed_user.py --demo --name "Demo Explorer"

Credential precedence per field: CLI flag > *_EMAIL/*_PASSWORD env >
interactive prompt (password via getpass, hidden from shell history).
The script is idempotent: an existing email is reported, never duplicated.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

# Make the shared package importable when run from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR / "shared" / "src"))

# Load backend/.env so DATABASE_URL and credential env vars resolve the
# same way they do for Alembic and the services (shell env still wins).
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    load_dotenv(_BACKEND_DIR / ".env", override=False)
except ImportError:
    pass

from zellovest_shared.db.models import User  # noqa: E402
from zellovest_shared.db.session import sync_session_scope  # noqa: E402
from zellovest_shared.security.auth import normalize_email, validate_email, validate_password  # noqa: E402
from zellovest_shared.security.passwords import hash_password  # noqa: E402


def _resolve(prompt_label: str, flag_value: str | None, env_var: str, secret: bool) -> str:
    """Resolve a credential: CLI flag > env var > interactive prompt."""
    if flag_value:
        return flag_value
    value = os.environ.get(env_var, "").strip()
    if value:
        return value
    prompt = f"{prompt_label} (env {env_var}): "
    answer = getpass.getpass(prompt) if secret else input(prompt).strip()
    return answer.strip()


def main() -> int:
    """Create the user row and report the outcome."""
    parser = argparse.ArgumentParser(description="Seed a Zellovest local user.")
    parser.add_argument("--email", default=None, help="User email (or *_EMAIL env)")
    parser.add_argument("--password", default=None, help="Password (or *_PASSWORD env)")
    parser.add_argument("--name", default="", help="Display name")
    parser.add_argument("--demo", action="store_true", help="Use DEMO_* vars, not FIRST_USER_*")
    args = parser.parse_args()

    prefix = "DEMO" if args.demo else "FIRST_USER"
    email = normalize_email(_resolve("Email", args.email, f"{prefix}_EMAIL", secret=False))
    password = _resolve("Password", args.password, f"{prefix}_PASSWORD", secret=True)
    if not email or not password:
        print("Email and password are both required.", file=sys.stderr)
        return 2
    if not validate_email(email):
        print("Invalid email address.", file=sys.stderr)
        return 2
    if (pw_error := validate_password(password)) is not None:
        print(pw_error, file=sys.stderr)
        return 2

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL is not set (see backend/.env.example).", file=sys.stderr)
        return 2

    with sync_session_scope(database_url) as session:
        existing = session.execute(select(User).where(User.email == email)).scalars().first()
        if existing is not None:
            print(f"User {email} already exists — nothing to do.")
            return 0
        user = User(
            email=email,
            name=(args.name or "").strip(),
            password_hash=hash_password(password),
            role="procurement_member",
            tenant_id="default",
            is_active=True,
        )
        session.add(user)
        session.commit()
        print(f"Created user {user.email} (id={user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
