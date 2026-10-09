"""Audit trail recording.

Every user-visible action is recorded in the same transaction as the change
itself, with typed columns only (see ``AuditLog``). Never build a JSON payload
for storage — extend the table with real columns instead.
"""
from fastapi import Request
from sqlalchemy.orm import Session
from app.models import AuditLog, User


def _request_meta(request: Request | None) -> tuple[str, str]:
    if request is None:
        return "", ""
    ip = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    agent = request.headers.get("user-agent", "")[:255]
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
        actor_email=actor.email if actor else actor_email,
        actor_name=actor.full_name if actor else actor_name,
        action=action[:40],
        entity_type=entity_type[:40],
        entity_id=entity_id,
        entity_label=entity_label[:255],
        summary=summary[:500],
        ip_address=ip[:45],
        user_agent=agent,
    )
    db.add(entry)
    return entry
