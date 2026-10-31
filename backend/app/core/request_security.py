"""Client identity and per-client request budgets.

``request.client.host`` is the only address the transport actually knows. A
``X-Forwarded-For`` header is attacker-controlled text unless the immediate peer
is a proxy we configured, so it is honoured **only** when the connecting address
is in ``TRUSTED_PROXY_IPS`` — and then the rightmost address that is not itself a
trusted proxy is used. This closes the ``X-Forwarded-For`` rotation bypass that
let an unauthenticated caller reset a recovery budget, and it stops forged
addresses from entering the audit trail.
"""
import hashlib
import hmac
import ipaddress
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import PasswordResetAttempt


def _network(value: str):
    try:
        return ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return None


def _trusted(value: str, networks) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in networks if network is not None)


def _valid(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def proxy_networks():
    return [network for network in (_network(item) for item in get_settings().trusted_proxies) if network is not None]


def client_ip(request: Request) -> str:
    """The best address available without trusting an unverified header."""
    peer = request.client.host if request.client else "unknown"
    networks = proxy_networks()
    if networks and _trusted(peer, networks):
        forwarded = request.headers.get("x-forwarded-for", "")
        candidates = [item.strip() for item in forwarded.split(",") if item.strip()]
        for candidate in reversed(candidates):
            if _valid(candidate) and not _trusted(candidate, networks):
                return candidate[:45]
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if _valid(real_ip) and not _trusted(real_ip, networks):
            return real_ip[:45]
    return peer[:45]


def client_key(request: Request, action: str) -> str:
    """Keyed digest of one client's budget for one action; never the raw address."""
    return hmac.new(
        get_settings().secret_key.encode(),
        f"{action}:{client_ip(request)}".encode(),
        hashlib.sha256,
    ).hexdigest()


def throttle(db: Session, request: Request, action: str, limit: int, *, window_minutes: int | None = None) -> None:
    """Spend one unit from a database-backed budget shared by every API worker.

    ``limit`` attempts are allowed per window; the next raises HTTP 429. The
    ledger also stores the keyed digest only. This is not a substitute for an
    atomic edge limiter under heavy concurrency, but it closes the practical
    bypass where each request claimed a different address.
    """
    settings = get_settings()
    window = window_minutes or settings.throttle_window_minutes
    now = utcnow()
    key = client_key(request, action)
    count = db.scalar(
        select(func.count(PasswordResetAttempt.id)).where(
            PasswordResetAttempt.ip_hash == key,
            PasswordResetAttempt.attempted_at >= now - timedelta(minutes=window),
        )
    ) or 0
    if count >= limit:
        raise HTTPException(
            429,
            f"Too many attempts. Wait {window} minutes and try again.",
            headers={"Retry-After": str(window * 60)},
        )
    db.add(PasswordResetAttempt(ip_hash=key, attempted_at=now))
    db.execute(delete(PasswordResetAttempt).where(PasswordResetAttempt.attempted_at < now - timedelta(days=1)))
    db.commit()
