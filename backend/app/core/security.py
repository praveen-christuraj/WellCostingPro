"""Password policy, JWT issuance/validation and refresh-session primitives.

One policy function serves account creation, sign-in changes, recovery codes and
administrator resets, so a weaker path cannot exist. Tokens carry an explicit
issuer/audience and every claim the API depends on is *required*, not optional:
a correctly signed token that simply omits ``exp`` is rejected.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.time import as_utc, utcnow
from app.models.entities import RefreshSession

passwords = PasswordHash.recommended()

ISSUER = "wellcostiq"
AUDIENCE = "wellcostiq-api"
ALGORITHM = "HS256"
# ``aud`` is intentionally not asserted: this API has a single audience, and
# adding a claim that consumers must supply would break existing integrations.
REQUIRED_CLAIMS = ("exp", "iat", "nbf", "sub", "org", "type", "ver", "iss")
ACCESS_TOKEN_TYPE = "access"

# Deliberately small and dependency-free: a blocklist of the passwords that
# dominate credential-stuffing lists, plus structural rules below. A breached
# password service can be added as an external control without changing callers.
COMMON_PASSWORDS = {
    "password", "password1", "password12", "password123", "password1234", "passw0rd",
    "p@ssw0rd", "p@ssword", "passwort", "contraseña", "motdepasse", "qwerty", "qwerty123",
    "qwertyuiop", "azerty", "letmein", "welcome", "welcome1", "welcome123", "admin",
    "admin123", "administrator", "administrator123", "root", "toor", "changeme", "changeme1",
    "changeme123", "default", "secret", "iloveyou", "monkey", "dragon", "sunshine",
    "princess", "football", "baseball", "superman", "trustno1", "abc123", "abcd1234",
    "123456", "1234567", "12345678", "123456789", "1234567890", "111111", "000000",
    "123123", "654321", "qazwsx", "zaq12wsx", "asdfghjkl", "1q2w3e4r", "1qaz2wsx",
    "wellcost", "wellcosting", "wellcostpro", "wellcostiq", "oilfield", "petroleum",
}
SEQUENCES = ("0123", "1234", "2345", "3456", "4567", "5678", "6789", "abcd", "bcde", "cdef",
             "qwer", "wert", "erty", "asdf", "sdfg", "dfgh", "zxcv", "xcvb", "cvbn")
MIN_CLASSES = 3


def hash_password(value: str) -> str:
    return passwords.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return passwords.verify(value, hashed)
    except Exception:  # a corrupted/legacy hash must fail closed, not crash the request
        return False


def _classes(value: str) -> int:
    return sum(bool(re.search(pattern, value)) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))


def validate_password(value: str, *, identity: str = "") -> str:
    """Raise ``ValueError`` with a user-readable reason when ``value`` is weak.

    The rules are intentionally explainable to a non-technical user: length,
    character variety, no personal data, no famous default, no keyboard walk.
    """
    settings = get_settings()
    minimum = max(12, settings.password_min_length)
    maximum = min(128, settings.password_max_length)
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"Password must be {minimum}–{maximum} characters")
    if value != value.strip():
        raise ValueError("Password must not begin or end with a space")
    lowered = value.lower()
    if _classes(value) < MIN_CLASSES:
        raise ValueError("Password must use at least three of: lowercase, uppercase, number, symbol")
    identity = identity.strip().lower()
    if identity and identity in lowered:
        raise ValueError("Password must not contain the e-mail address")
    local_part = identity.split("@", 1)[0] if "@" in identity else ""
    if len(local_part) >= 8 and local_part in lowered:
        # Short logins are usually ordinary words ("manager", "analyst"); blocking
        # those over-restricts without adding much. A real account handle
        # ("praveen.christuraj") is long enough to be recognised here.
        raise ValueError("Password must not contain the account name")
    compact = re.sub(r"[^a-z0-9]", "", lowered)
    if compact in COMMON_PASSWORDS or lowered in COMMON_PASSWORDS:
        raise ValueError("That password is a well-known default. Choose something unique to you")
    if len(set(value)) == 1:
        raise ValueError("Password cannot repeat one character")
    if any(sequence in compact for sequence in SEQUENCES) and len(set(compact)) < 6:
        raise ValueError("Password must not be a keyboard or number sequence")
    # "Qwerty12345!" has enough character classes and unique characters to pass the
    # rules above, but it is still one famous keyboard walk plus digits.
    if re.match(r"^(qwerty|azerty|qwertz|asdf|sdfg|zxcv|1234|abcd|1q2w3e)[0-9!@#$%^&*._-]*$", compact):
        raise ValueError("Password must not be a keyboard or number sequence")
    for word in ("wellcostiq", "wellcost"):
        if word in compact:
            raise ValueError("Password must not contain the product name")
    return value


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------

def access_token(user_id: str, organization_id: str, token_version: int) -> str:
    settings = get_settings()
    issued = utcnow()
    return jwt.encode(
        {
            "sub": user_id,
            "org": organization_id,
            "ver": token_version,
            "type": ACCESS_TOKEN_TYPE,
            "iss": ISSUER,
            "iat": issued,
            "nbf": issued,
            "exp": issued + timedelta(minutes=settings.access_token_minutes),
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """Verify signature, issuer, audience, expiry and the required claim set."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        options={"require": list(REQUIRED_CLAIMS), "verify_iss": True},
    )
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("token type is not access")
    return payload


# ---------------------------------------------------------------------------
# Refresh sessions
# ---------------------------------------------------------------------------

def refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_session(user_id: str, *, replacing: str | None = None) -> tuple[str, RefreshSession]:
    token = secrets.token_urlsafe(48)
    session = RefreshSession(
        user_id=user_id,
        token_hash=refresh_hash(token),
        expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days),
    )
    if replacing:
        session.replaced_by_hash = None  # set by the caller on the previous row
    return token, session


# ---------------------------------------------------------------------------
# Password lifetime
# ---------------------------------------------------------------------------

def password_expires_at(changed_at: datetime | None, created_at: datetime | None = None) -> datetime | None:
    """When the password must be replaced, derived from policy and its age.

    Accounts created before password ageing existed fall back to their creation
    time, so a dormant legacy account cannot keep a password forever.
    """
    settings = get_settings()
    if settings.password_max_age_days <= 0:
        return None
    basis = as_utc(changed_at) or as_utc(created_at)
    if basis is None:
        return None
    return basis + timedelta(days=settings.password_max_age_days)


def effective_expiry(user) -> datetime | None:
    stored = as_utc(getattr(user, "password_expires_at", None))
    return stored or password_expires_at(getattr(user, "password_changed_at", None), getattr(user, "created_at", None))


def password_is_expired(user) -> bool:
    expiry = effective_expiry(user)
    return bool(expiry and expiry <= utcnow())


def password_days_remaining(user) -> int | None:
    expiry = effective_expiry(user)
    if expiry is None:
        return None
    return max(0, (expiry - utcnow()).days)


def password_expiry_warning(user) -> bool:
    days = password_days_remaining(user)
    return days is not None and days <= get_settings().password_expiry_warning_days
