"""Auditing module: paginated, filterable audit trail (read-only)."""
from datetime import date, datetime, time, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from app.api.deps import Current, Db, require
from app.models import AuditLog
from app.schemas.rbac import AuditPage

router = APIRouter(tags=["Auditing"])

PAGE_SIZES = (20, 50, 100)


@router.get("/audit", response_model=AuditPage, dependencies=[Depends(require("audit:read"))])
def list_audit(
    db: Db,
    user: Current,
    action: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
):
    """Audit entries for the caller's organization. Filterable and paginated (20/50/100)."""
    if page_size not in PAGE_SIZES:
        page_size = 20
    where = [AuditLog.organization_id == user.organization_id]
    if action:
        where.append(AuditLog.action == action)
    if entity_type:
        where.append(AuditLog.entity_type == entity_type)
    if actor:
        pattern = f"%{actor.strip().lower()}%"
        where.append(func.lower(AuditLog.actor_email).like(pattern) | func.lower(AuditLog.actor_name).like(pattern))
    if date_from:
        where.append(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        where.append(AuditLog.created_at < datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    total = db.scalar(select(func.count(AuditLog.id)).where(*where)) or 0
    items = db.scalars(select(AuditLog).where(*where).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}
