"""Password lifecycle helpers shared by sign-in, recovery and the security centre.

Three rules live here so every entry point behaves the same way:

* the single password policy in ``app.core.security.validate_password``;
* reuse prevention — a new password may not repeat the current one or any of
  the last ``password_history_limit`` accepted passwords, compared against
  one-way hashes stored in ``password_history`` (typed columns, never the password);
* lifetime — a password carries an expiry derived from ``PASSWORD_MAX_AGE_DAYS``
  and an expired password forces a change before the workspace reopens.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    effective_expiry,
    hash_password,
    password_expires_at,
    password_is_expired,
    validate_password,
    verify_password,
)
from app.core.time import utcnow
from app.models import PasswordHistory, User


def history_limit() -> int:
    return max(3, get_settings().password_history_limit)


def _history(db: Session, user: User, limit: int | None = None) -> list[PasswordHistory]:
    return list(db.scalars(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(limit or history_limit())
    ).all())


class PasswordReuseError(ValueError):
    """The requested password repeats one the account already used."""


def check_password(db: Session, user: User, value: str) -> None:
    """Raise ``ValueError`` when the password breaks policy or was used before."""
    validate_password(value, identity=user.email)
    candidates = [user.password_hash] + [row.password_hash for row in _history(db, user)]
    for hashed in candidates:
        if hashed and verify_password(value, hashed):
            raise PasswordReuseError(
                f"Choose a password you have not used before. The last {history_limit()} passwords cannot be reused."
            )


def remember_password(db: Session, user: User, hashed: str) -> None:
    """Apply the new hash, keep the replaced one in history and prune old rows.

    The *previous* hash is what is remembered, so "the last N passwords cannot be
    reused" includes the password the account was created with.
    """
    if user.password_hash:
        db.add(PasswordHistory(
            organization_id=user.organization_id, user_id=user.id, password_hash=user.password_hash,
            created_at=utcnow(),
        ))
    user.password_hash = hashed
    user.password_changed_at = utcnow()
    user.password_expires_at = password_expires_at(user.password_changed_at)
    user.must_change_password = False
    db.flush()
    stale = list(db.scalars(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .offset(history_limit())
    ).all())
    for row in stale:
        db.delete(row)


def set_password(db: Session, user: User, value: str) -> None:
    """Validate, hash, record history and apply the policy checks atomically."""
    check_password(db, user, value)
    remember_password(db, user, hash_password(value))


def require_change(user: User) -> None:
    """Flag the account so its next sign-in must set a new password.

    The reason is recorded on the audit entry, never on the row: the account
    register should not accumulate free text that might quote a ticket or a
    personal circumstance.
    """
    user.must_change_password = True


def expire_now(db: Session, user: User) -> None:
    """Invalidate the current password immediately (administrator containment)."""
    user.password_expires_at = utcnow() - timedelta(seconds=1)
    user.must_change_password = True
    db.flush()


def state(user: User) -> dict[str, object]:
    """Password-age facts the Security centre and the sign-in screen display."""
    return {
        "must_change_password": bool(user.must_change_password),
        "password_expired": password_is_expired(user),
        "password_expires_at": effective_expiry(user),
        "password_changed_at": user.password_changed_at,
    }
