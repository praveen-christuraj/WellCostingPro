"""Shared notification and task primitives for security and approvals."""

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Permission, Role, User, UserNotification, WorkflowTask, WorkflowTaskEvent


def now() -> datetime:
    return datetime.now(timezone.utc)


def number(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


def permission_holders(db: Session, organization_id: str, permission_key: str) -> list[User]:
    return list(db.scalars(
        select(User).where(
            User.organization_id == organization_id,
            User.is_active.is_(True),
            User.roles.any((Role.is_owner.is_(True)) | Role.permissions.any(Permission.key == permission_key)),
        ).order_by(User.full_name)
    ).unique().all())


def notify(
    db: Session,
    *,
    organization_id: str,
    recipients: list[User],
    title: str,
    message: str,
    severity: str = "info",
    notification_type: str = "system",
    action_path: str = "",
    actor: User | None = None,
    entity_type: str = "",
    entity_id: str = "",
    announcement_id: str | None = None,
) -> list[UserNotification]:
    rows: list[UserNotification] = []
    seen: set[str] = set()
    for recipient in recipients:
        if recipient.organization_id != organization_id or recipient.id in seen:
            continue
        seen.add(recipient.id)
        row = UserNotification(
            organization_id=organization_id,
            recipient_user_id=recipient.id,
            created_by_user_id=actor.id if actor else None,
            notification_type=notification_type,
            severity=severity,
            title=title,
            message=message,
            action_path=action_path,
            related_entity_type=entity_type,
            related_entity_id=entity_id,
            announcement_id=announcement_id,
        )
        db.add(row)
        rows.append(row)
    return rows


def add_event(db: Session, task: WorkflowTask, event_type: str, actor: User | None, old: str = "", new: str = "", notes: str = "") -> WorkflowTaskEvent:
    event = WorkflowTaskEvent(
        organization_id=task.organization_id,
        task_id=task.id,
        event_type=event_type,
        old_status=old,
        new_status=new,
        actor_user_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else "System",
        notes=notes,
    )
    db.add(event)
    return event


def create_task(
    db: Session,
    *,
    organization_id: str,
    title: str,
    description: str,
    task_type: str,
    required_permission: str = "",
    priority: str = "normal",
    actor: User | None = None,
    assignee: User | None = None,
    entity_type: str = "",
    entity_id: str = "",
    entity_label: str = "",
    action_path: str = "",
) -> WorkflowTask:
    existing = db.scalar(select(WorkflowTask).where(
        WorkflowTask.organization_id == organization_id,
        WorkflowTask.task_type == task_type,
        WorkflowTask.related_entity_type == entity_type,
        WorkflowTask.related_entity_id == entity_id,
        WorkflowTask.status.in_(("open", "in_progress")),
    )) if entity_id else None
    if existing:
        return existing
    task = WorkflowTask(
        organization_id=organization_id,
        task_number=number("TSK"),
        task_type=task_type,
        title=title,
        description=description,
        priority=priority,
        required_permission=required_permission,
        assignee_user_id=assignee.id if assignee else None,
        created_by_user_id=actor.id if actor else None,
        related_entity_type=entity_type,
        related_entity_id=entity_id,
        related_entity_label=entity_label,
        action_path=action_path,
    )
    db.add(task)
    db.flush()
    add_event(db, task, "created", actor, new="open", notes=description[:1000])
    recipients = [assignee] if assignee else permission_holders(db, organization_id, required_permission) if required_permission else []
    notify(
        db, organization_id=organization_id, recipients=[row for row in recipients if row], actor=actor,
        title=f"New task: {title}", message=description or title, severity="warning" if priority in ("high", "critical") else "info",
        notification_type="task", action_path="/other-management/tasks", entity_type="workflow_task", entity_id=task.id,
    )
    return task


def complete_related_tasks(db: Session, organization_id: str, entity_type: str, entity_id: str, actor: User | None, notes: str) -> None:
    tasks = db.scalars(select(WorkflowTask).where(
        WorkflowTask.organization_id == organization_id,
        WorkflowTask.related_entity_type == entity_type,
        WorkflowTask.related_entity_id == entity_id,
        WorkflowTask.status.in_(("open", "in_progress")),
    )).all()
    for task in tasks:
        old = task.status
        task.status = "completed"
        task.completed_at = now()
        add_event(db, task, "completed", actor, old=old, new="completed", notes=notes)


def sync_afe_status(db: Session, afe, action: str, actor: User) -> None:
    """Materialise the existing AFE state machine as actionable work."""
    complete_related_tasks(db, afe.organization_id, "afe", afe.id, actor, f"AFE moved to {afe.status}")
    if action == "submit":
        create_task(
            db, organization_id=afe.organization_id, title=f"Review AFE {afe.afe_code}",
            description=f"{afe.afe_name} was submitted and is ready for technical/finance review.",
            task_type="afe_review", required_permission="afe:review", priority="high", actor=actor,
            entity_type="afe", entity_id=afe.id, entity_label=afe.afe_code, action_path=f"/afe/estimate/{afe.id}",
        )
    elif action == "review":
        create_task(
            db, organization_id=afe.organization_id, title=f"Approve AFE {afe.afe_code}",
            description=f"{afe.afe_name} completed review and is ready for approval.",
            task_type="afe_approval", required_permission="afe:approve", priority="high", actor=actor,
            entity_type="afe", entity_id=afe.id, entity_label=afe.afe_code, action_path=f"/afe/estimate/{afe.id}",
        )
