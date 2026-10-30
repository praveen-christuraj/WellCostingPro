import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select

from app.api.deps import Current, Db, granted, owner, require
from app.core.config import get_settings
from app.core.security import hash_password, validate_password
from app.models import (
    Organization, PasswordResetAttempt, PasswordResetRequest, User, UserNotification,
    WorkflowTask, WorkflowTaskEvent,
)
from app.schemas.security import (
    ForgotPasswordIn, NotificationCreate, NotificationOut, NotificationPage,
    PasswordResetOut, ResetCodeOut, ResetPasswordIn, ReviewResetIn,
    SecurityUserOut, TaskCreate, TaskEventOut, TaskOut, TaskPage, TaskUpdate,
)
from app.services import audit, workflow

router = APIRouter(tags=["Security and workflow"])
PUBLIC_RESET_MESSAGE = "If the account exists, a password reset request has been sent to the workspace administrators."


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    # The schema holds IPv4/IPv6 text. Truncation also prevents an untrusted
    # forwarding header from turning a public recovery request into a DB error.
    return (forwarded or (request.client.host if request.client else "unknown"))[:45]


def ip_hash(value: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def reset_out(row: PasswordResetRequest, user: User) -> PasswordResetOut:
    return PasswordResetOut(
        id=row.id, request_number=row.request_number, user_id=user.id, user_name=user.full_name,
        user_email=user.email, status=row.status, reason=row.reason, requested_at=row.requested_at,
        requested_by_ip=row.requested_by_ip, reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=row.reviewed_at, review_notes=row.review_notes,
        reset_token_expires_at=row.reset_token_expires_at, completed_at=row.completed_at,
    )


def scoped_reset(db: Db, row_id: str, organization_id: str, lock: bool = False) -> tuple[PasswordResetRequest, User]:
    statement = select(PasswordResetRequest).where(
        PasswordResetRequest.id == row_id, PasswordResetRequest.organization_id == organization_id
    )
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if not row:
        raise HTTPException(404, "Password reset request not found")
    user = db.get(User, row.user_id)
    if not user or user.organization_id != organization_id:
        raise HTTPException(404, "User not found")
    return row, user


def issue_code(db: Db, row: PasswordResetRequest, reviewer: User, notes: str) -> tuple[str, datetime]:
    code = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(minutes=get_settings().password_reset_minutes)
    row.status = "approved"
    row.reviewed_by_user_id = reviewer.id
    row.reviewed_at = utcnow()
    row.review_notes = notes.strip()
    row.reset_token_hash = token_hash(code)
    row.reset_token_expires_at = expires
    workflow.complete_related_tasks(db, row.organization_id, "password_reset", row.id, reviewer, "Reset request approved")
    return code, expires


@router.post("/auth/forgot-password", status_code=202)
def forgot_password(data: ForgotPasswordIn, request: Request, db: Db):
    address = client_ip(request)
    hashed_ip = ip_hash(address)
    cutoff = utcnow() - timedelta(minutes=15)
    recent = db.scalar(select(func.count(PasswordResetAttempt.id)).where(
        PasswordResetAttempt.ip_hash == hashed_ip, PasswordResetAttempt.attempted_at >= cutoff
    )) or 0
    if recent >= 5:
        raise HTTPException(429, "Too many password reset attempts. Wait 15 minutes and try again.")
    db.add(PasswordResetAttempt(ip_hash=hashed_ip))
    db.execute(PasswordResetAttempt.__table__.delete().where(PasswordResetAttempt.attempted_at < utcnow() - timedelta(days=1)))

    org = db.scalar(select(Organization).where(Organization.slug == data.organization.strip().lower()))
    user = db.scalar(select(User).where(
        User.organization_id == org.id, User.email == str(data.email).lower(), User.is_active.is_(True)
    )) if org else None
    if user:
        pending = db.scalar(select(PasswordResetRequest).where(
            PasswordResetRequest.organization_id == org.id,
            PasswordResetRequest.user_id == user.id,
            PasswordResetRequest.status == "pending",
        ))
        if not pending:
            row = PasswordResetRequest(
                organization_id=org.id, request_number=workflow.number("PWR"), user_id=user.id,
                reason=data.reason.strip(), requested_by_ip=address,
            )
            db.add(row)
            db.flush()
            workflow.create_task(
                db, organization_id=org.id, title=f"Review password reset for {user.full_name}",
                description=data.reason.strip() or "The user cannot access their account and requested a password reset.",
                task_type="password_reset", required_permission="security:password-reset", priority="high",
                entity_type="password_reset", entity_id=row.id, entity_label=row.request_number,
                action_path="/security", actor=user,
            )
            audit.record(db, organization_id=org.id, actor=user, action="request", entity_type="password_reset",
                         entity_id=row.id, entity_label=row.request_number,
                         summary="Requested administrator-approved password reset", request=request)
    db.commit()
    return {"message": PUBLIC_RESET_MESSAGE}


@router.post("/auth/reset-password", status_code=204)
def reset_password(data: ResetPasswordIn, request: Request, response: Response, db: Db):
    org = db.scalar(select(Organization).where(Organization.slug == data.organization.strip().lower()))
    user = db.scalar(select(User).where(User.organization_id == org.id, User.email == str(data.email).lower())) if org else None
    row = db.scalar(select(PasswordResetRequest).where(
        PasswordResetRequest.organization_id == org.id,
        PasswordResetRequest.user_id == user.id,
        PasswordResetRequest.status == "approved",
        PasswordResetRequest.reset_token_hash == token_hash(data.reset_code),
    ).order_by(PasswordResetRequest.reviewed_at.desc()).with_for_update()) if user else None
    if not row or not row.reset_token_expires_at or aware(row.reset_token_expires_at) <= utcnow():
        if row:
            row.status = "expired"
            db.commit()
        raise HTTPException(400, "This reset code is invalid or expired. Ask an administrator to approve a new request.")
    try:
        validate_password(data.new_password, identity=user.email)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    user.failed_logins = 0
    user.locked_until = None
    for session in list(user.sessions):
        db.delete(session)
    row.status = "completed"
    row.completed_at = utcnow()
    row.reset_token_hash = None
    workflow.notify(
        db, organization_id=org.id, recipients=[user], title="Password reset completed",
        message="Your password was reset and all previous sessions were signed out.", severity="success",
        notification_type="security", actor=user, entity_type="password_reset", entity_id=row.id,
    )
    audit.record(db, organization_id=org.id, actor=user, action="complete", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number,
                 summary="Completed one-time password reset; all sessions revoked", request=request)
    db.commit()
    response.delete_cookie("refresh_token", path="/api/v1/auth")


@router.get("/security/password-reset-requests", response_model=list[PasswordResetOut], dependencies=[Depends(require("security:read"))])
def list_reset_requests(db: Db, user: Current, request_status: str = Query("", alias="status")):
    statement = select(PasswordResetRequest).where(PasswordResetRequest.organization_id == user.organization_id)
    if request_status:
        statement = statement.where(PasswordResetRequest.status == request_status)
    rows = db.scalars(statement.order_by(PasswordResetRequest.requested_at.desc())).all()
    users = {item.id: item for item in db.scalars(select(User).where(User.organization_id == user.organization_id)).all()}
    return [reset_out(row, users[row.user_id]) for row in rows if row.user_id in users]


@router.get("/security/users", response_model=list[SecurityUserOut], dependencies=[Depends(require("security:read"))])
def security_users(db: Db, user: Current):
    """Minimal account-state view; roles and credentials stay on their existing surfaces."""
    return db.scalars(select(User).where(
        User.organization_id == user.organization_id
    ).order_by(User.full_name, User.email)).all()


@router.post("/security/password-reset-requests/{row_id}/approve", response_model=ResetCodeOut, dependencies=[Depends(require("security:password-reset"))])
def approve_reset(row_id: str, data: ReviewResetIn, request: Request, db: Db, user: Current):
    row, target = scoped_reset(db, row_id, user.organization_id, lock=True)
    if row.status != "pending":
        raise HTTPException(409, f"This request is already {row.status}")
    code, expires = issue_code(db, row, user, data.notes)
    audit.record(db, organization_id=user.organization_id, actor=user, action="approve", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number,
                 summary=f"Approved password reset for {target.email}; code expires in {get_settings().password_reset_minutes} minutes", request=request)
    db.commit()
    return ResetCodeOut(request=reset_out(row, target), reset_code=code, expires_at=expires)


@router.post("/security/password-reset-requests/{row_id}/reject", response_model=PasswordResetOut, dependencies=[Depends(require("security:password-reset"))])
def reject_reset(row_id: str, data: ReviewResetIn, request: Request, db: Db, user: Current):
    row, target = scoped_reset(db, row_id, user.organization_id, lock=True)
    if row.status != "pending":
        raise HTTPException(409, f"This request is already {row.status}")
    row.status = "rejected"
    row.reviewed_by_user_id = user.id
    row.reviewed_at = utcnow()
    row.review_notes = data.notes.strip()
    workflow.complete_related_tasks(db, row.organization_id, "password_reset", row.id, user, "Reset request rejected")
    audit.record(db, organization_id=user.organization_id, actor=user, action="reject", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number, summary=f"Rejected password reset for {target.email}", request=request)
    db.commit()
    return reset_out(row, target)


@router.post("/security/users/{user_id}/reset-code", response_model=ResetCodeOut, dependencies=[Depends(require("security:password-reset"))])
def admin_reset_code(user_id: str, data: ReviewResetIn, request: Request, db: Db, user: Current):
    target = db.scalar(select(User).where(User.id == user_id, User.organization_id == user.organization_id))
    if not target:
        raise HTTPException(404, "User not found")
    row = PasswordResetRequest(
        organization_id=user.organization_id, request_number=workflow.number("PWR"), user_id=target.id,
        reason="Administrator initiated reset", requested_by_ip=client_ip(request),
    )
    db.add(row)
    db.flush()
    code, expires = issue_code(db, row, user, data.notes)
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number, summary=f"Issued one-time reset code for {target.email}", request=request)
    db.commit()
    return ResetCodeOut(request=reset_out(row, target), reset_code=code, expires_at=expires)


@router.post("/security/users/{user_id}/unlock", status_code=204, dependencies=[Depends(require("security:unlock"))])
def unlock_user(user_id: str, request: Request, db: Db, user: Current):
    target = db.scalar(select(User).where(User.id == user_id, User.organization_id == user.organization_id))
    if not target:
        raise HTTPException(404, "User not found")
    target.failed_logins = 0
    target.locked_until = None
    audit.record(db, organization_id=user.organization_id, actor=user, action="unlock", entity_type="user",
                 entity_id=target.id, entity_label=target.email, summary=f"Unlocked account {target.email}", request=request)
    db.commit()


@router.get("/notifications", response_model=NotificationPage)
def notifications(db: Db, user: Current, limit: int = Query(40, ge=1, le=100)):
    items = list(db.scalars(select(UserNotification).where(
        UserNotification.organization_id == user.organization_id, UserNotification.recipient_user_id == user.id
    ).order_by(UserNotification.created_at.desc()).limit(limit)).all())
    unread = db.scalar(select(func.count(UserNotification.id)).where(
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
        UserNotification.read_at.is_(None),
    )) or 0
    return NotificationPage(items=items, unread_count=unread)


@router.post("/notifications", response_model=list[NotificationOut], status_code=201, dependencies=[Depends(require("notifications:manage"))])
def send_notification(data: NotificationCreate, request: Request, db: Db, user: Current):
    statement = select(User).where(User.organization_id == user.organization_id, User.is_active.is_(True))
    if data.recipient_user_ids:
        if len(data.recipient_user_ids) != len(set(data.recipient_user_ids)):
            raise HTTPException(422, "Duplicate recipients are not allowed")
        statement = statement.where(User.id.in_(data.recipient_user_ids))
    recipients = list(db.scalars(statement).all())
    if data.recipient_user_ids and len(recipients) != len(data.recipient_user_ids):
        raise HTTPException(422, "One or more recipients do not belong to this workspace")
    rows = workflow.notify(db, organization_id=user.organization_id, recipients=recipients, actor=user,
                           title=data.title.strip(), message=data.message.strip(), severity=data.severity,
                           notification_type="announcement", action_path=data.action_path)
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="notification",
                 entity_label=data.title.strip(), summary=f"Sent notification to {len(rows)} user(s)", request=request)
    db.commit()
    return rows


@router.post("/notifications/read-all", status_code=204)
def read_all_notifications(db: Db, user: Current):
    rows = db.scalars(select(UserNotification).where(
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
        UserNotification.read_at.is_(None),
    )).all()
    stamp = utcnow()
    for row in rows:
        row.read_at = stamp
    db.commit()


@router.post("/notifications/{notification_id}/read", status_code=204)
def read_notification(notification_id: str, db: Db, user: Current):
    row = db.scalar(select(UserNotification).where(
        UserNotification.id == notification_id,
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    ))
    if not row:
        raise HTTPException(404, "Notification not found")
    row.read_at = row.read_at or utcnow()
    db.commit()


def task_out(db: Db, row: WorkflowTask) -> TaskOut:
    assignee = db.get(User, row.assignee_user_id) if row.assignee_user_id else None
    return TaskOut(
        id=row.id, task_number=row.task_number, task_type=row.task_type, title=row.title,
        description=row.description, status=row.status, priority=row.priority,
        required_permission=row.required_permission, assignee_user_id=row.assignee_user_id,
        assignee_name=assignee.full_name if assignee else "Unassigned", created_by_user_id=row.created_by_user_id,
        due_at=row.due_at, related_entity_type=row.related_entity_type, related_entity_id=row.related_entity_id,
        related_entity_label=row.related_entity_label, action_path=row.action_path, completed_at=row.completed_at,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def can_manage_task(user: User, row: WorkflowTask) -> bool:
    keys = granted(user)
    return owner(user) or "tasks:manage" in keys or row.assignee_user_id == user.id or row.created_by_user_id == user.id or (row.required_permission and row.required_permission in keys)


@router.get("/tasks", response_model=TaskPage, dependencies=[Depends(require("tasks:read"))])
def list_tasks(db: Db, user: Current, task_status: str = Query("", alias="status"), page: int = Query(1, ge=1), page_size: int = Query(20, ge=20, le=100)):
    statement = select(WorkflowTask).where(WorkflowTask.organization_id == user.organization_id)
    keys = granted(user)
    if not owner(user) and "tasks:manage" not in keys:
        allowed_permissions = list(keys)
        statement = statement.where(or_(
            WorkflowTask.assignee_user_id == user.id,
            WorkflowTask.created_by_user_id == user.id,
            WorkflowTask.required_permission.in_(allowed_permissions) if allowed_permissions else WorkflowTask.id == "",
        ))
    if task_status:
        statement = statement.where(WorkflowTask.status == task_status)
    count = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(WorkflowTask.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return TaskPage(items=[task_out(db, row) for row in rows], total=count, page=page, page_size=page_size)


@router.post("/tasks", response_model=TaskOut, status_code=201, dependencies=[Depends(require("tasks:create"))])
def create_manual_task(data: TaskCreate, request: Request, db: Db, user: Current):
    assignee = None
    if data.assignee_user_id:
        assignee = db.scalar(select(User).where(User.id == data.assignee_user_id, User.organization_id == user.organization_id, User.is_active.is_(True)))
        if not assignee:
            raise HTTPException(422, "Assignee does not belong to this workspace")
    row = workflow.create_task(db, organization_id=user.organization_id, title=data.title.strip(),
                               description=data.description.strip(), task_type="manual", priority=data.priority,
                               actor=user, assignee=assignee, action_path=data.action_path)
    row.due_at = data.due_at
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="workflow_task",
                 entity_id=row.id, entity_label=row.task_number, summary=f"Created task {row.title}", request=request)
    db.commit()
    return task_out(db, row)


@router.patch("/tasks/{task_id}", response_model=TaskOut, dependencies=[Depends(require("tasks:read"))])
def update_task(task_id: str, data: TaskUpdate, request: Request, db: Db, user: Current):
    row = db.scalar(select(WorkflowTask).where(
        WorkflowTask.id == task_id, WorkflowTask.organization_id == user.organization_id
    ).with_for_update())
    if not row:
        raise HTTPException(404, "Task not found")
    if not can_manage_task(user, row):
        raise HTTPException(403, "You are not assigned or authorized to act on this task")
    if data.assignee_user_id is not None:
        assignee = db.scalar(select(User).where(User.id == data.assignee_user_id, User.organization_id == user.organization_id, User.is_active.is_(True)))
        if not assignee:
            raise HTTPException(422, "Assignee does not belong to this workspace")
        row.assignee_user_id = assignee.id
    elif row.assignee_user_id is None and data.status == "in_progress":
        row.assignee_user_id = user.id
    if data.priority is not None:
        row.priority = data.priority
    if data.due_at is not None:
        row.due_at = data.due_at
    old = row.status
    if data.status is not None:
        row.status = data.status
        row.completed_at = utcnow() if data.status in ("completed", "cancelled") else None
    workflow.add_event(db, row, "updated", user, old=old, new=row.status, notes=data.notes.strip())
    audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="workflow_task",
                 entity_id=row.id, entity_label=row.task_number, summary=f"Updated task {row.task_number}: {old} → {row.status}", request=request)
    db.commit()
    return task_out(db, row)


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventOut], dependencies=[Depends(require("tasks:read"))])
def task_events(task_id: str, db: Db, user: Current):
    row = db.scalar(select(WorkflowTask).where(WorkflowTask.id == task_id, WorkflowTask.organization_id == user.organization_id))
    if not row or not can_manage_task(user, row):
        raise HTTPException(404, "Task not found")
    return db.scalars(select(WorkflowTaskEvent).where(
        WorkflowTaskEvent.task_id == row.id, WorkflowTaskEvent.organization_id == user.organization_id
    ).order_by(WorkflowTaskEvent.created_at)).all()
