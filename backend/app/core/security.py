import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import jwt
import re
from pwdlib import PasswordHash
from app.core.config import get_settings
from app.models.entities import RefreshSession

passwords = PasswordHash.recommended()


def hash_password(value: str) -> str:
    return passwords.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    return passwords.verify(value, hashed)


def validate_password(value: str, *, identity: str = "") -> str:
    """One policy for account creation, password changes and recovery."""
    if not 12 <= len(value) <= 128:
        raise ValueError("Password must be 12–128 characters")
    classes = sum(bool(re.search(pattern, value)) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes < 3:
        raise ValueError("Password must use at least three of: lowercase, uppercase, number, symbol")
    normalized_identity = identity.strip().lower()
    if normalized_identity and normalized_identity in value.lower():
        raise ValueError("Password must not contain the email address")
    if value.lower() in {"password123!", "changeme123!", "administrator123!"}:
        raise ValueError("Choose a less predictable password")
    return value


def access_token(user_id: str, organization_id: str, token_version: int) -> str:
    settings = get_settings()
    return jwt.encode({"sub": user_id, "org": organization_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes), "type": "access", "ver": token_version}, settings.secret_key, algorithm="HS256")


def new_refresh_session(user_id: str) -> tuple[str, RefreshSession]:
    token = secrets.token_urlsafe(48)
    session = RefreshSession(user_id=user_id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().refresh_token_days))
    return token, session


def refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
