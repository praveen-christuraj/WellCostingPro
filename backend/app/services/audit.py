"""Audit trail recording.

Every user-visible action is recorded in the same transaction as the change
itself, with typed columns only (see ``AuditLog``). Never build a JSON payload
for storage — extend the table with real columns instead.

The client address comes from :func:`app.core.request_security.client_ip`, so a
caller cannot forge an audit row by rotating ``X-Forwarded-For``. Free-text
fields are sanitised of control characters before storage because they are shown
verbatim in the audit register and in CSV exports.
"""
import re

from fastapi import Request
from sqlalchemy.orm import Session
from app.core.request_security import client_ip
from app.models import AuditLog, User

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value: str, limit: int) -> str:
    return _CONTROL.sub("", value or "").strip()[:limit]


def _request_meta(request: Request | None) -> tuple[str, str]:
    if request is None:
        return "", ""
    ip = client_ip(request)
    agent = _clean(request.headers.get("user-agent", ""), 255)
    return ip, agent


def record(
    db: Session,
    *,
    organization_id: str,
    action: str,
    entity_type: str,
    actor: User | None = None,
    actor_email: str = "",
    actor_name: str = "",
    entity_id: str | None = None,
    entity_label: str = "",
    summary: str = "",
    request: Request | None = None,
) -> AuditLog:
    """Append an audit entry. The caller commits; failures roll back with the change."""
    ip, agent = _request_meta(request)
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor.id if actor else None,
        actor_email=_clean(actor.email if actor else actor_email, 255),
        actor_name=_clean(actor.full_name if actor else actor_name, 160),
        action=_clean(action, 40),
        entity_type=_clean(entity_type, 40),
        entity_id=entity_id,
        entity_label=_clean(entity_label, 255),
        summary=_clean(summary, 500),
        ip_address=ip[:45],
        user_agent=agent,
    )
    db.add(entry)
    return entry
