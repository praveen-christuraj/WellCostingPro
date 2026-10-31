"""Client identity is supplied by ASGI, never by arbitrary HTTP headers.

Configure Uvicorn's forwarded-allow-ips with only the trusted reverse proxy IPs.
"""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PasswordResetAttempt


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")[:45]


def throttle(db: Session, request: Request, action: str, limit: int) -> None:
    """Database-backed per-client budget, shared by API workers.

    An edge limiter remains required for strict atomic limits under concurrency.
    Store only a keyed digest; reuse the expiring recovery-attempt ledger.
    """
    now = datetime.now(timezone.utc)
    key = hmac.new(get_settings().secret_key.encode(),
                   f"{action}:{client_ip(request)}".encode(), hashlib.sha256).hexdigest()
    count = db.scalar(select(func.count(PasswordResetAttempt.id)).where(
        PasswordResetAttempt.ip_hash == key,
        PasswordResetAttempt.attempted_at >= now - timedelta(minutes=15),
    )) or 0
    if count >= limit:
        raise HTTPException(429, "Too many attempts. Wait 15 minutes and try again.", headers={"Retry-After": "900"})
    db.add(PasswordResetAttempt(ip_hash=key))
    db.execute(PasswordResetAttempt.__table__.delete().where(
        PasswordResetAttempt.attempted_at < now - timedelta(days=1)))
    db.commit()
