"""Password lifecycle helpers shared by sign-in, recovery and the security centre.

Two rules live here so every entry point behaves the same way:

* the single password policy in ``app.core.security.validate_password``;
* reuse prevention — a new password may not repeat the current one or any of
  the last ``HISTORY_LIMIT`` accepted passwords, compared against one-way
  hashes stored in ``password_history`` (typed columns, never the password).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, validate_password, verify_password
from app.models import PasswordHistory, User

# How many previous passwords are remembered per account.
HISTORY_LIMIT = 5


class PasswordReuseError(ValueError):
    """The requested password repeats one the account already used."""


def _history(db: Session, user: User, limit: int = HISTORY_LIMIT) -> list[PasswordHistory]:
    return list(db.scalars(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(limit)
    ).all())


def check_password(db: Session, user: User, value: str) -> None:
    """Raise ``ValueError`` when the password breaks policy or was used before."""
    validate_password(value, identity=user.email)
    candidates = [user.password_hash] + [row.password_hash for row in _history(db, user)]
    for hashed in candidates:
        if hashed and verify_password(value, hashed):
            raise PasswordReuseError(
                f"Choose a password you have not used before. The last {HISTORY_LIMIT} passwords cannot be reused."
            )


def remember_password(db: Session, user: User, hashed: str) -> None:
    """Apply the new hash, keep the replaced one in history and prune old rows.

    The *previous* hash is what is remembered, so "the last N passwords cannot be
    reused" includes the password the account was created with.
    """
    if user.password_hash:
        db.add(PasswordHistory(
            organization_id=user.organization_id, user_id=user.id, password_hash=user.password_hash,
            created_at=datetime.now(timezone.utc),
        ))
    user.password_hash = hashed
    user.password_changed_at = datetime.now(timezone.utc)
    user.must_change_password = False
    db.flush()
    stale = list(db.scalars(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .offset(HISTORY_LIMIT)
    ).all())
    for row in stale:
        db.delete(row)


def set_password(db: Session, user: User, value: str) -> None:
    """Validate, hash, record history and apply the policy checks atomically."""
    check_password(db, user, value)
    remember_password(db, user, hash_password(value))


def require_change(user: User) -> None:
    """Flag the account so the next sign-in must set a new password."""
    user.must_change_password = True
