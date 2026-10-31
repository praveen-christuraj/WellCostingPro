"""Timezone-safe time helpers.

SQLite returns naive ``DATETIME`` values and PostgreSQL returns aware ones. The
application stores UTC everywhere, so a naive value is *assumed* to be UTC and an
aware value is *converted* — never relabelled. Using ``.replace(tzinfo=...)`` on
an aware value silently changes the instant; that bug is why every comparison in
this codebase goes through :func:`as_utc`.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """The current instant, always timezone-aware UTC."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as an aware UTC datetime, or ``None``."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_expired(value: datetime | None, *, now: datetime | None = None) -> bool:
    """True when ``value`` is in the past; ``None`` never expires."""
    moment = as_utc(value)
    return bool(moment is not None and moment <= (as_utc(now) or utcnow()))
