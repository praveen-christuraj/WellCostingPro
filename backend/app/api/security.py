"""Security centre, notification centre and task manager.

Three cooperating surfaces with one rule: every administrative action writes a
typed row (request, notification, task, event) and an audit entry in the same
transaction, so the workspace can always answer who did what and when.
"""
import hashlib
import hmac
import secrets
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select

from app.api.deps import Current, Db, granted, owner, require, require_any
from app.core.config import get_settings
from app.models import (
    Announcement, Organization, PasswordResetAttempt, PasswordResetRequest, RefreshSession, Role, User,
    UserNotification, WorkflowTask, WorkflowTaskEvent,
)
from app.schemas.security import (
    AnnouncementOut, AnnouncementPage, ForgotPasswordIn, NotificationCreate, NotificationIdsIn,
    NotificationOut, NotificationOverview, NotificationPage, PasswordResetOut, ResetCodeOut,
    ResetPasswordIn, ReviewResetIn, SecurityActionIn, SecurityBulkIn, SecurityBulkOut,
    SecurityOverview, SecurityUserOut, TaskBulkIn, TaskBulkOut, TaskCommentIn, TaskCreate,
    TaskEventOut, TaskOut, TaskOverview, TaskPage, TaskUpdate,
)
from app.services import audit, password_policy, workflow

router = APIRouter(tags=["Security and workflow"])
PUBLIC_RESET_MESSAGE = "If the account exists, a password reset request has been sent to the workspace administrators."
PAGE_SIZES = (20, 50, 100)
# An administrator lock is "until further notice"; the account cannot sign in
# until somebody with security:unlock clears it.
LOCK_YEARS = 100


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
        initiated_by=row.initiated_by,
    )


def scoped_reset(db: Db, row_id: str, organization_id: str, lock: bool = False) -> tuple[PasswordResetRequest, User]:
    statement = select(PasswordResetRequest).where(
        PasswordResetRequest.id == row_id, PasswordResetRequest.organization_id == organization_id
    )
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if not row:
        raise HTTPException(
            404,
            "That password reset request is no longer in this workspace. It may have been withdrawn — refresh the list.",
        )
    user = db.get(User, row.user_id)
    if not user or user.organization_id != organization_id:
        raise HTTPException(404, "The account behind this request no longer exists in this workspace.")
    return row, user


def scoped_user(db: Db, user_id: str, organization_id: str, lock: bool = False) -> User:
    statement = select(User).where(User.id == user_id, User.organization_id == organization_id)
    if lock:
        statement = statement.with_for_update()
    target = db.scalar(statement)
    if not target:
        raise HTTPException(
            404,
            "That account is not part of this workspace. It may have been removed — refresh the list and try again.",
        )
    return target


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


def revoke_sessions(db: Db, target: User) -> int:
    """Sign the account out everywhere by removing refresh sessions and bumping the token version."""
    count = len(list(target.sessions))
    for session in list(target.sessions):
        db.delete(session)
    target.token_version += 1
    return count


def active_session_count(db: Db, user_ids: list[str]) -> dict[str, int]:
    """Live refresh sessions per account, counted in one grouped query."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(RefreshSession.user_id, func.count(RefreshSession.id))
        .where(RefreshSession.user_id.in_(user_ids))
        .group_by(RefreshSession.user_id)
    ).all()
    return {row[0]: row[1] for row in rows}


def security_user_out(db: Db, target: User, sessions: dict[str, int] | None = None) -> SecurityUserOut:
    counts = sessions if sessions is not None else active_session_count(db, [target.id])
    return SecurityUserOut(
        id=target.id, full_name=target.full_name, email=target.email, is_active=target.is_active,
        failed_logins=target.failed_logins, locked_until=target.locked_until,
        must_change_password=target.must_change_password, password_changed_at=target.password_changed_at,
        last_login_at=target.last_login_at, active_sessions=counts.get(target.id, 0),
        role_names=sorted(role.name for role in target.roles),
        is_owner=any(role.is_owner for role in target.roles),
    )


def is_locked(user: User) -> bool:
    until = aware(user.locked_until)
    return bool(until and until > utcnow())


# ---------------------------------------------------------------------------
# Public recovery: an administrator approves every reset.
# ---------------------------------------------------------------------------

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
                reason=data.reason.strip(), requested_by_ip=address, initiated_by="user",
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
        password_policy.set_password(db, user, data.new_password)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
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


# ---------------------------------------------------------------------------
# Security centre
# ---------------------------------------------------------------------------

@router.get("/security/overview", response_model=SecurityOverview, dependencies=[Depends(require_any("security:read", "security:password-reset", "security:unlock"))])
def security_overview(db: Db, user: Current):
    org = user.organization_id
    cutoff = utcnow() - timedelta(days=30)
    users = list(db.scalars(select(User).where(User.organization_id == org)).all())
    pending = db.scalar(select(func.count(PasswordResetRequest.id)).where(
        PasswordResetRequest.organization_id == org, PasswordResetRequest.status == "pending")) or 0
    awaiting = db.scalar(select(func.count(PasswordResetRequest.id)).where(
        PasswordResetRequest.organization_id == org, PasswordResetRequest.status == "approved")) or 0
    completed = db.scalar(select(func.count(PasswordResetRequest.id)).where(
        PasswordResetRequest.organization_id == org, PasswordResetRequest.status == "completed",
        PasswordResetRequest.completed_at >= cutoff)) or 0
    announcements = db.scalar(select(func.count(Announcement.id)).where(
        Announcement.organization_id == org, Announcement.created_at >= cutoff)) or 0
    recent_rows = db.scalars(select(PasswordResetRequest).where(
        PasswordResetRequest.organization_id == org
    ).order_by(PasswordResetRequest.requested_at.desc()).limit(5)).all()
    by_id = {item.id: item for item in users}
    return SecurityOverview(
        users=len(users), active_users=sum(1 for item in users if item.is_active),
        locked_users=sum(1 for item in users if is_locked(item)),
        pending_requests=pending, awaiting_use=awaiting,
        must_change_password=sum(1 for item in users if item.must_change_password),
        completed_30d=completed, announcements_30d=announcements,
        reset_minutes=get_settings().password_reset_minutes,
        recent_requests=[reset_out(row, by_id[row.user_id]) for row in recent_rows if row.user_id in by_id],
    )


@router.get("/security/password-reset-requests", response_model=list[PasswordResetOut], dependencies=[Depends(require_any("security:read", "security:password-reset"))])
def list_reset_requests(
    db: Db,
    user: Current,
    request_status: str = Query("", alias="status"),
    search: str = Query("", max_length=120),
    user_id: str = Query("", max_length=36),
    date_from: date | None = None,
    date_to: date | None = None,
):
    statement = select(PasswordResetRequest).where(PasswordResetRequest.organization_id == user.organization_id)
    if request_status:
        statement = statement.where(PasswordResetRequest.status == request_status)
    if user_id:
        statement = statement.where(PasswordResetRequest.user_id == user_id)
    if date_from:
        statement = statement.where(PasswordResetRequest.requested_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        statement = statement.where(PasswordResetRequest.requested_at < datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    rows = db.scalars(statement.order_by(PasswordResetRequest.requested_at.desc())).all()
    users = {item.id: item for item in db.scalars(select(User).where(User.organization_id == user.organization_id)).all()}
    results = [reset_out(row, users[row.user_id]) for row in rows if row.user_id in users]
    if search.strip():
        needle = search.strip().lower()
        results = [
            item for item in results
            if needle in (item.user_name or "").lower() or needle in item.user_email.lower()
            or needle in item.request_number.lower() or needle in (item.reason or "").lower()
        ]
    return results


@router.get("/security/users", response_model=list[SecurityUserOut], dependencies=[Depends(require("security:read"))])
def security_users(db: Db, user: Current):
    """Account state the security centre acts on: lockout, password age and sessions."""
    people = list(db.scalars(select(User).where(
        User.organization_id == user.organization_id
    ).order_by(User.full_name, User.email)).all())
    sessions = active_session_count(db, [item.id for item in people])
    return [security_user_out(db, item, sessions) for item in people]


@router.post("/security/password-reset-requests/{row_id}/approve", response_model=ResetCodeOut, dependencies=[Depends(require("security:password-reset"))])
def approve_reset(row_id: str, data: ReviewResetIn, request: Request, db: Db, user: Current):
    row, target = scoped_reset(db, row_id, user.organization_id, lock=True)
    if row.status != "pending":
        raise HTTPException(409, f"This request is already {row.status}. Refresh the list to see the latest state.")
    code, expires = issue_code(db, row, user, data.notes)
    workflow.notify(
        db, organization_id=user.organization_id, recipients=[target], title="A reset code was issued for your account",
        message="An administrator approved a password reset. Use the one-time code you were given to set a new password.",
        severity="warning", notification_type="security", actor=user, entity_type="password_reset", entity_id=row.id,
        action_path="/login",
    )
    audit.record(db, organization_id=user.organization_id, actor=user, action="approve", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number,
                 summary=f"Approved password reset for {target.email}; code expires in {get_settings().password_reset_minutes} minutes", request=request)
    db.commit()
    return ResetCodeOut(request=reset_out(row, target), reset_code=code, expires_at=expires)


@router.post("/security/password-reset-requests/{row_id}/reject", response_model=PasswordResetOut, dependencies=[Depends(require("security:password-reset"))])
def reject_reset(row_id: str, data: ReviewResetIn, request: Request, db: Db, user: Current):
    row, target = scoped_reset(db, row_id, user.organization_id, lock=True)
    if row.status != "pending":
        raise HTTPException(409, f"This request is already {row.status}. Refresh the list to see the latest state.")
    row.status = "rejected"
    row.reviewed_by_user_id = user.id
    row.reviewed_at = utcnow()
    row.review_notes = data.notes.strip()
    workflow.complete_related_tasks(db, row.organization_id, "password_reset", row.id, user, "Reset request rejected")
    audit.record(db, organization_id=user.organization_id, actor=user, action="reject", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number,
                 summary=f"Rejected password reset for {target.email}" + (f": {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return reset_out(row, target)


@router.post("/security/users/{user_id}/reset-code", response_model=ResetCodeOut, dependencies=[Depends(require("security:password-reset"))])
def admin_reset_code(user_id: str, data: ReviewResetIn, request: Request, db: Db, user: Current):
    """Issue a one-time code without waiting for the account holder to ask.

    The security centre opens the request itself, records who decided and why,
    and notifies the account holder so the action is never silent.
    """
    target = scoped_user(db, user_id, user.organization_id)
    if not target.is_active:
        raise HTTPException(409, "This account is deactivated. Reactivate it in User Management before issuing a reset code.")
    row = PasswordResetRequest(
        organization_id=user.organization_id, request_number=workflow.number("PWR"), user_id=target.id,
        reason=data.notes.strip() or "Administrator initiated reset", requested_by_ip=client_ip(request),
        initiated_by="administrator",
    )
    db.add(row)
    db.flush()
    code, expires = issue_code(db, row, user, data.notes)
    workflow.notify(
        db, organization_id=user.organization_id, recipients=[target], title="A reset code was issued for your account",
        message="An administrator issued a one-time password reset code for security reasons. Use it to set a new password.",
        severity="warning", notification_type="security", actor=user, entity_type="password_reset", entity_id=row.id,
        action_path="/login",
    )
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="password_reset",
                 entity_id=row.id, entity_label=row.request_number,
                 summary=f"Issued one-time reset code for {target.email} without a user request"
                         + (f": {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return ResetCodeOut(request=reset_out(row, target), reset_code=code, expires_at=expires)


@router.post("/security/users/{user_id}/force-password-change", response_model=SecurityUserOut, dependencies=[Depends(require("security:password-reset"))])
def force_password_change(user_id: str, data: SecurityActionIn, request: Request, db: Db, user: Current):
    """Demand a new password at the next request and sign the account out everywhere."""
    target = scoped_user(db, user_id, user.organization_id, lock=True)
    if target.id == user.id:
        raise HTTPException(409, "Use the account menu to change your own password.")
    password_policy.require_change(target)
    revoked = revoke_sessions(db, target)
    workflow.notify(
        db, organization_id=user.organization_id, recipients=[target], title="Your password must be changed",
        message="For security reasons an administrator requires a new password. Sign in again and set one before continuing."
                + (f" Note: {data.notes.strip()}" if data.notes.strip() else ""),
        severity="warning", notification_type="security", actor=user,
    )
    audit.record(db, organization_id=user.organization_id, actor=user, action="force_password_change", entity_type="user",
                 entity_id=target.id, entity_label=target.email,
                 summary=f"Required a new password for {target.email}; {revoked} session(s) revoked"
                         + (f": {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return security_user_out(db, target)


@router.post("/security/users/{user_id}/revoke-sessions", response_model=SecurityUserOut, dependencies=[Depends(require("security:password-reset"))])
def revoke_user_sessions(user_id: str, data: SecurityActionIn, request: Request, db: Db, user: Current):
    target = scoped_user(db, user_id, user.organization_id, lock=True)
    if target.id == user.id:
        raise HTTPException(409, "Signing yourself out everywhere is done from the account menu.")
    revoked = revoke_sessions(db, target)
    if revoked:
        workflow.notify(
            db, organization_id=user.organization_id, recipients=[target], title="You were signed out of all devices",
            message="An administrator ended your sessions for security reasons. Sign in again to continue.",
            severity="warning", notification_type="security", actor=user,
        )
    audit.record(db, organization_id=user.organization_id, actor=user, action="revoke_sessions", entity_type="user",
                 entity_id=target.id, entity_label=target.email,
                 summary=f"Revoked {revoked} session(s) for {target.email}"
                         + (f": {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return security_user_out(db, target)


@router.post("/security/users/{user_id}/lock", response_model=SecurityUserOut, dependencies=[Depends(require("security:unlock"))])
def lock_user(user_id: str, data: SecurityActionIn, request: Request, db: Db, user: Current):
    target = scoped_user(db, user_id, user.organization_id, lock=True)
    if target.id == user.id:
        raise HTTPException(409, "You cannot lock your own account.")
    if any(role.is_owner for role in target.roles) and not owner(user):
        raise HTTPException(403, "Only an owner can lock an owner account.")
    target.locked_until = utcnow() + timedelta(days=365 * LOCK_YEARS)
    target.failed_logins = 0
    revoked = revoke_sessions(db, target)
    audit.record(db, organization_id=user.organization_id, actor=user, action="lock", entity_type="user",
                 entity_id=target.id, entity_label=target.email,
                 summary=f"Locked account {target.email}; {revoked} session(s) revoked"
                         + (f": {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return security_user_out(db, target)


@router.post("/security/users/{user_id}/unlock", status_code=204, dependencies=[Depends(require("security:unlock"))])
def unlock_user(user_id: str, request: Request, db: Db, user: Current):
    target = scoped_user(db, user_id, user.organization_id)
    target.failed_logins = 0
    target.locked_until = None
    audit.record(db, organization_id=user.organization_id, actor=user, action="unlock", entity_type="user",
                 entity_id=target.id, entity_label=target.email, summary=f"Unlocked account {target.email}", request=request)
    db.commit()


@router.post("/security/users/bulk", response_model=SecurityBulkOut, dependencies=[Depends(require("security:read"))])
def bulk_account_action(data: SecurityBulkIn, request: Request, db: Db, user: Current):
    """Apply one security action to several accounts in a single audited action."""
    required = {
        "force-password-change": "security:password-reset",
        "revoke-sessions": "security:password-reset",
        "lock": "security:unlock",
        "unlock": "security:unlock",
    }[data.action]
    if not owner(user) and required not in granted(user):
        raise HTTPException(
            403,
            f"Permission denied. Applying {data.action.replace('-', ' ')} to several accounts needs {required}.",
        )
    unique_ids = list(dict.fromkeys(data.user_ids))
    if len(unique_ids) != len(data.user_ids):
        raise HTTPException(422, "Duplicate accounts are not allowed")
    targets = list(db.scalars(select(User).where(
        User.id.in_(unique_ids), User.organization_id == user.organization_id
    ).with_for_update()).all())
    labels = {
        "force-password-change": "Required a new password",
        "revoke-sessions": "Revoked all sessions",
        "lock": "Locked the account",
        "unlock": "Unlocked the account",
    }
    affected, skipped, names = 0, 0, []
    for target in targets:
        if target.id == user.id or (data.action == "lock" and any(role.is_owner for role in target.roles) and not owner(user)):
            skipped += 1
            continue
        if data.action == "force-password-change":
            password_policy.require_change(target)
            revoke_sessions(db, target)
            workflow.notify(
                db, organization_id=user.organization_id, recipients=[target], title="Your password must be changed",
                message="For security reasons an administrator requires a new password. Sign in again and set one before continuing.",
                severity="warning", notification_type="security", actor=user,
            )
        elif data.action == "revoke-sessions":
            revoke_sessions(db, target)
            workflow.notify(
                db, organization_id=user.organization_id, recipients=[target], title="You were signed out of all devices",
                message="An administrator ended your sessions for security reasons. Sign in again to continue.",
                severity="warning", notification_type="security", actor=user,
            )
        elif data.action == "lock":
            target.locked_until = utcnow() + timedelta(days=365 * LOCK_YEARS)
            target.failed_logins = 0
            revoke_sessions(db, target)
        else:
            target.locked_until = None
            target.failed_logins = 0
        affected += 1
        names.append(target.email)
    skipped += len(unique_ids) - len(targets)
    audit.record(db, organization_id=user.organization_id, actor=user, action="bulk", entity_type="user",
                 entity_label=f"{affected} account(s)",
                 summary=f"{labels[data.action]} for {affected} account(s): {', '.join(names[:10])}"
                         + (" …" if len(names) > 10 else "")
                         + (f". Reason: {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return SecurityBulkOut(action=data.action, affected=affected, skipped=skipped)


# ---------------------------------------------------------------------------
# Notification centre
# ---------------------------------------------------------------------------

def notification_filters(user: User, *, status_filter: str, severity: str, notification_type: str,
                         search: str, date_from: date | None, date_to: date | None):
    where = [
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    ]
    if status_filter == "unread":
        where.append(UserNotification.read_at.is_(None))
    elif status_filter == "read":
        where.append(UserNotification.read_at.is_not(None))
    if severity:
        where.append(UserNotification.severity == severity)
    if notification_type:
        where.append(UserNotification.notification_type == notification_type)
    if search.strip():
        needle = f"%{search.strip().lower()}%"
        where.append(or_(func.lower(UserNotification.title).like(needle), func.lower(UserNotification.message).like(needle)))
    if date_from:
        where.append(UserNotification.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        where.append(UserNotification.created_at < datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    return where


@router.get("/notifications", response_model=NotificationPage)
def notifications(
    db: Db,
    user: Current,
    limit: int = Query(0, ge=0, le=100),
    notification_status: str = Query("", alias="status", pattern="^(|unread|read)$"),
    severity: str = Query("", pattern="^(|info|success|warning|error)$"),
    notification_type: str = Query("", alias="type", max_length=40),
    search: str = Query("", max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
):
    if page_size not in PAGE_SIZES:
        page_size = 20
    # The header bell asks for "the latest N" without filters, so `limit` wins there.
    if limit:
        page, page_size = 1, limit
    where = notification_filters(user, status_filter=notification_status, severity=severity, notification_type=notification_type,
                                 search=search, date_from=date_from, date_to=date_to)
    total = db.scalar(select(func.count(UserNotification.id)).where(*where)) or 0
    items = list(db.scalars(select(UserNotification).where(*where)
                            .order_by(UserNotification.created_at.desc(), UserNotification.id.desc())
                            .offset((page - 1) * page_size).limit(page_size)).all())
    unread = db.scalar(select(func.count(UserNotification.id)).where(
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
        UserNotification.read_at.is_(None),
    )) or 0
    counts = {
        key: db.scalar(select(func.count(UserNotification.id)).where(
            UserNotification.organization_id == user.organization_id,
            UserNotification.recipient_user_id == user.id,
            UserNotification.severity == key,
            UserNotification.read_at.is_(None),
        )) or 0
        for key in ("info", "success", "warning", "error")
    }
    return NotificationPage(items=items, total=total, unread_count=unread, page=page, page_size=page_size, counts=counts)


@router.get("/notifications/overview", response_model=NotificationOverview)
def notification_overview(db: Db, user: Current):
    scope = (UserNotification.organization_id == user.organization_id, UserNotification.recipient_user_id == user.id)
    total = db.scalar(select(func.count(UserNotification.id)).where(*scope)) or 0
    unread = db.scalar(select(func.count(UserNotification.id)).where(*scope, UserNotification.read_at.is_(None))) or 0
    by_severity = {key: db.scalar(select(func.count(UserNotification.id)).where(*scope, UserNotification.severity == key)) or 0
                   for key in ("info", "success", "warning", "error")}
    by_type = {key: count for key, count in db.execute(
        select(UserNotification.notification_type, func.count(UserNotification.id)).where(*scope)
        .group_by(UserNotification.notification_type).order_by(func.count(UserNotification.id).desc()).limit(8)
    ).all()}
    oldest = db.scalar(select(func.min(UserNotification.created_at)).where(*scope, UserNotification.read_at.is_(None)))
    sent = db.scalar(select(func.count(Announcement.id)).where(Announcement.organization_id == user.organization_id)) or 0
    oldest_days = 0
    if oldest:
        oldest_days = max(0, (utcnow().date() - aware(oldest).date()).days)
    return NotificationOverview(total=total, unread=unread, by_severity=by_severity, by_type=by_type,
                                announcements_sent=sent, oldest_unread_days=oldest_days)


@router.post("/notifications", response_model=list[NotificationOut], status_code=201, dependencies=[Depends(require("notifications:manage"))])
def send_notification(data: NotificationCreate, request: Request, db: Db, user: Current):
    statement = select(User).where(User.organization_id == user.organization_id, User.is_active.is_(True))
    audience, audience_label = "all", "All active users"
    if data.recipient_user_ids and data.recipient_role_ids:
        raise HTTPException(422, "Choose either specific people or roles, not both")
    if data.recipient_user_ids:
        if len(data.recipient_user_ids) != len(set(data.recipient_user_ids)):
            raise HTTPException(422, "Duplicate recipients are not allowed")
        statement = statement.where(User.id.in_(data.recipient_user_ids))
        audience = "users"
    elif data.recipient_role_ids:
        if len(data.recipient_role_ids) != len(set(data.recipient_role_ids)):
            raise HTTPException(422, "Duplicate roles are not allowed")
        statement = statement.where(User.roles.any(Role.id.in_(data.recipient_role_ids)))
        audience = "roles"
    recipients = list(db.scalars(statement).unique().all())
    if not recipients:
        raise HTTPException(422, "No active user matches the chosen audience")
    if data.recipient_user_ids and len(recipients) != len(data.recipient_user_ids):
        raise HTTPException(422, "One or more recipients are not active accounts in this workspace")
    if audience == "roles":
        names = [role.name for role in db.scalars(select(Role).where(
            Role.id.in_(data.recipient_role_ids), Role.organization_id == user.organization_id)).all()]
        if len(names) != len(set(data.recipient_role_ids)):
            raise HTTPException(422, "One or more roles do not belong to this workspace")
        audience_label = "Roles: " + ", ".join(sorted(names))
    elif audience == "users":
        audience_label = f"{len(recipients)} selected user(s)"
    announcement = Announcement(
        organization_id=user.organization_id, title=data.title.strip(), message=data.message.strip(),
        severity=data.severity, action_path=data.action_path.strip(), audience=audience,
        audience_label=audience_label, recipient_count=len(recipients), created_by_user_id=user.id,
    )
    db.add(announcement)
    db.flush()
    rows = workflow.notify(db, organization_id=user.organization_id, recipients=recipients, actor=user,
                           title=announcement.title, message=announcement.message, severity=announcement.severity,
                           notification_type="announcement", action_path=announcement.action_path,
                           entity_type="announcement", entity_id=announcement.id,
                           announcement_id=announcement.id)
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="notification",
                 entity_id=announcement.id, entity_label=announcement.title,
                 summary=f"Sent announcement '{announcement.title}' to {len(rows)} user(s) ({audience_label})", request=request)
    db.commit()
    return rows


@router.get("/notifications/announcements", response_model=AnnouncementPage, dependencies=[Depends(require("notifications:manage"))])
def list_announcements(db: Db, user: Current, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1), search: str = Query("", max_length=120)):
    if page_size not in PAGE_SIZES:
        page_size = 20
    where = [Announcement.organization_id == user.organization_id]
    if search.strip():
        needle = f"%{search.strip().lower()}%"
        where.append(or_(func.lower(Announcement.title).like(needle), func.lower(Announcement.message).like(needle)))
    total = db.scalar(select(func.count(Announcement.id)).where(*where)) or 0
    rows = list(db.scalars(select(Announcement).where(*where)
                           .order_by(Announcement.created_at.desc())
                           .offset((page - 1) * page_size).limit(page_size)).all())
    senders = {item.id: item.full_name for item in db.scalars(select(User).where(User.organization_id == user.organization_id)).all()}
    read_counts = {
        row[0]: row[1] for row in db.execute(
            select(UserNotification.announcement_id, func.count(UserNotification.id))
            .where(UserNotification.organization_id == user.organization_id,
                   UserNotification.announcement_id.in_([item.id for item in rows] or [""]),
                   UserNotification.read_at.is_not(None))
            .group_by(UserNotification.announcement_id)
        ).all()
    }
    items = [
        AnnouncementOut(
            id=item.id, title=item.title, message=item.message, severity=item.severity, action_path=item.action_path,
            audience=item.audience, audience_label=item.audience_label, recipient_count=item.recipient_count,
            created_by_name=senders.get(item.created_by_user_id or "", "System"), created_at=item.created_at,
            recalled_at=item.recalled_at, read_count=read_counts.get(item.id, 0),
        )
        for item in rows
    ]
    return AnnouncementPage(items=items, total=total, page=page, page_size=page_size)


@router.post("/notifications/announcements/{announcement_id}/recall", response_model=AnnouncementOut, dependencies=[Depends(require("notifications:manage"))])
def recall_announcement(announcement_id: str, request: Request, db: Db, user: Current):
    """Withdraw an announcement: undelivered copies disappear, read copies stay for the record."""
    item = db.scalar(select(Announcement).where(
        Announcement.id == announcement_id, Announcement.organization_id == user.organization_id).with_for_update())
    if not item:
        raise HTTPException(404, "That announcement is not in this workspace. Refresh the sent list and try again.")
    if item.recalled_at:
        raise HTTPException(409, "This announcement was already recalled.")
    removed = 0
    for row in db.scalars(select(UserNotification).where(
        UserNotification.organization_id == user.organization_id,
        UserNotification.announcement_id == item.id,
        UserNotification.read_at.is_(None),
    )).all():
        db.delete(row)
        removed += 1
    item.recalled_at = utcnow()
    item.recalled_by_user_id = user.id
    audit.record(db, organization_id=user.organization_id, actor=user, action="recall", entity_type="notification",
                 entity_id=item.id, entity_label=item.title,
                 summary=f"Recalled announcement '{item.title}'; {removed} unread copy(ies) withdrawn", request=request)
    db.commit()
    return AnnouncementOut(
        id=item.id, title=item.title, message=item.message, severity=item.severity, action_path=item.action_path,
        audience=item.audience, audience_label=item.audience_label, recipient_count=item.recipient_count,
        created_by_name=user.full_name, created_at=item.created_at, recalled_at=item.recalled_at, read_count=0,
    )


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


@router.post("/notifications/read", status_code=204)
def read_notifications(data: NotificationIdsIn, db: Db, user: Current):
    rows = db.scalars(select(UserNotification).where(
        UserNotification.id.in_(data.ids),
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    )).all()
    stamp = utcnow()
    for row in rows:
        row.read_at = row.read_at or stamp
    db.commit()


@router.get("/notifications/{notification_id}", response_model=NotificationOut)
def notification_detail(notification_id: str, db: Db, user: Current):
    row = db.scalar(select(UserNotification).where(
        UserNotification.id == notification_id,
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    ))
    if not row:
        raise HTTPException(404, "That notification is not in your inbox. It may have been recalled — refresh the list.")
    return row


@router.post("/notifications/{notification_id}/read", status_code=204)
def read_notification(notification_id: str, db: Db, user: Current):
    row = db.scalar(select(UserNotification).where(
        UserNotification.id == notification_id,
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    ))
    if not row:
        raise HTTPException(404, "That notification is not in your inbox. It may have been recalled — refresh the list.")
    row.read_at = row.read_at or utcnow()
    db.commit()


@router.post("/notifications/{notification_id}/unread", status_code=204)
def unread_notification(notification_id: str, db: Db, user: Current):
    row = db.scalar(select(UserNotification).where(
        UserNotification.id == notification_id,
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    ))
    if not row:
        raise HTTPException(404, "That notification is not in your inbox. It may have been recalled — refresh the list.")
    row.read_at = None
    db.commit()


@router.delete("/notifications/{notification_id}", status_code=204)
def dismiss_notification(notification_id: str, db: Db, user: Current):
    row = db.scalar(select(UserNotification).where(
        UserNotification.id == notification_id,
        UserNotification.organization_id == user.organization_id,
        UserNotification.recipient_user_id == user.id,
    ))
    if not row:
        raise HTTPException(404, "That notification is not in your inbox. It may already have been dismissed.")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Task manager
# ---------------------------------------------------------------------------

def task_out(db: Db, row: WorkflowTask, viewer: User) -> TaskOut:
    assignee = db.get(User, row.assignee_user_id) if row.assignee_user_id else None
    creator = db.get(User, row.created_by_user_id) if row.created_by_user_id else None
    due = aware(row.due_at)
    return TaskOut(
        id=row.id, task_number=row.task_number, task_type=row.task_type, title=row.title,
        description=row.description, status=row.status, priority=row.priority,
        required_permission=row.required_permission, assignee_user_id=row.assignee_user_id,
        assignee_name=assignee.full_name if assignee else "Unassigned", created_by_user_id=row.created_by_user_id,
        created_by_name=creator.full_name if creator else "System",
        due_at=row.due_at, related_entity_type=row.related_entity_type, related_entity_id=row.related_entity_id,
        related_entity_label=row.related_entity_label, action_path=row.action_path, completed_at=row.completed_at,
        created_at=row.created_at, updated_at=row.updated_at,
        overdue=bool(due and due < utcnow() and row.status in ("open", "in_progress")),
        is_mine=row.assignee_user_id == viewer.id,
        can_manage=can_manage_task(viewer, row),
    )


def can_manage_task(user: User, row: WorkflowTask) -> bool:
    keys = granted(user)
    return owner(user) or "tasks:manage" in keys or row.assignee_user_id == user.id or row.created_by_user_id == user.id or (row.required_permission and row.required_permission in keys)


def task_visibility(user: User):
    """Rows a viewer may see: own work, work they may manage, or work gated by a capability they hold."""
    if owner(user) or "tasks:manage" in granted(user):
        return []
    keys = list(granted(user))
    conditions = [WorkflowTask.assignee_user_id == user.id, WorkflowTask.created_by_user_id == user.id]
    if keys:
        conditions.append(WorkflowTask.required_permission.in_(keys))
    return [or_(*conditions)]


@router.get("/tasks", response_model=TaskPage, dependencies=[Depends(require("tasks:read"))])
def list_tasks(
    db: Db,
    user: Current,
    task_status: str = Query("", alias="status", pattern="^(|open|in_progress|completed|cancelled|active)$"),
    priority: str = Query("", pattern="^(|low|normal|high|critical)$"),
    task_type: str = Query("", alias="type", max_length=50),
    assignee: str = Query("", max_length=36),
    due: str = Query("", pattern="^(|overdue|today|week|none)$"),
    search: str = Query("", max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
):
    if page_size not in PAGE_SIZES:
        page_size = 20
    where = [WorkflowTask.organization_id == user.organization_id, *task_visibility(user)]
    if task_status == "active":
        where.append(WorkflowTask.status.in_(("open", "in_progress")))
    elif task_status:
        where.append(WorkflowTask.status == task_status)
    if priority:
        where.append(WorkflowTask.priority == priority)
    if task_type:
        where.append(WorkflowTask.task_type == task_type)
    if assignee == "me":
        where.append(WorkflowTask.assignee_user_id == user.id)
    elif assignee == "unassigned":
        where.append(WorkflowTask.assignee_user_id.is_(None))
    elif assignee:
        where.append(WorkflowTask.assignee_user_id == assignee)
    today = utcnow().date()
    if due == "overdue":
        where.append(WorkflowTask.due_at.is_not(None))
        where.append(WorkflowTask.due_at < datetime.combine(today, time.min, tzinfo=timezone.utc))
        where.append(WorkflowTask.status.in_(("open", "in_progress")))
    elif due == "today":
        where.append(WorkflowTask.due_at >= datetime.combine(today, time.min, tzinfo=timezone.utc))
        where.append(WorkflowTask.due_at < datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc))
    elif due == "week":
        where.append(WorkflowTask.due_at >= datetime.combine(today, time.min, tzinfo=timezone.utc))
        where.append(WorkflowTask.due_at < datetime.combine(today + timedelta(days=7), time.min, tzinfo=timezone.utc))
    elif due == "none":
        where.append(WorkflowTask.due_at.is_(None))
    if search.strip():
        needle = f"%{search.strip().lower()}%"
        where.append(or_(
            func.lower(WorkflowTask.title).like(needle),
            func.lower(WorkflowTask.description).like(needle),
            func.lower(WorkflowTask.task_number).like(needle),
            func.lower(WorkflowTask.related_entity_label).like(needle),
        ))
    if date_from:
        where.append(WorkflowTask.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        where.append(WorkflowTask.created_at < datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    count = db.scalar(select(func.count()).select_from(select(WorkflowTask).where(*where).subquery())) or 0
    rows = db.scalars(select(WorkflowTask).where(*where).order_by(
        WorkflowTask.status.in_(("open", "in_progress")).desc(),
        WorkflowTask.created_at.desc(),
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return TaskPage(items=[task_out(db, row, user) for row in rows], total=count, page=page, page_size=page_size)


@router.get("/tasks/overview", response_model=TaskOverview, dependencies=[Depends(require("tasks:read"))])
def task_overview(db: Db, user: Current):
    where = [WorkflowTask.organization_id == user.organization_id, *task_visibility(user)]
    base = select(WorkflowTask).where(*where).subquery()
    counts = {status: db.scalar(select(func.count()).select_from(base).where(base.c.status == status)) or 0
              for status in ("open", "in_progress", "completed", "cancelled")}
    today = utcnow().date()
    due_today = db.scalar(select(func.count()).select_from(base).where(
        base.c.due_at >= datetime.combine(today, time.min, tzinfo=timezone.utc),
        base.c.due_at < datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc),
        base.c.status.in_(("open", "in_progress")),
    )) or 0
    overdue = db.scalar(select(func.count()).select_from(base).where(
        base.c.due_at.is_not(None),
        base.c.due_at < datetime.combine(today, time.min, tzinfo=timezone.utc),
        base.c.status.in_(("open", "in_progress")),
    )) or 0
    completed_7d = db.scalar(select(func.count()).select_from(base).where(
        base.c.status == "completed",
        base.c.completed_at >= utcnow() - timedelta(days=7),
    )) or 0
    mine = db.scalar(select(func.count()).select_from(base).where(
        base.c.assignee_user_id == user.id, base.c.status.in_(("open", "in_progress")))) or 0
    unassigned = db.scalar(select(func.count()).select_from(base).where(
        base.c.assignee_user_id.is_(None), base.c.status.in_(("open", "in_progress")))) or 0
    by_priority = {key: db.scalar(select(func.count()).select_from(base).where(
        base.c.priority == key, base.c.status.in_(("open", "in_progress")))) or 0
        for key in ("low", "normal", "high", "critical")}
    by_type = {row[0]: row[1] for row in db.execute(
        select(base.c.task_type, func.count()).where(base.c.status.in_(("open", "in_progress"))).group_by(base.c.task_type)
    ).all()}
    return TaskOverview(open=counts["open"], in_progress=counts["in_progress"], overdue=overdue, due_today=due_today,
                        completed_7d=completed_7d, mine=mine, unassigned=unassigned, by_priority=by_priority, by_type=by_type)


@router.post("/tasks", response_model=TaskOut, status_code=201, dependencies=[Depends(require("tasks:create"))])
def create_manual_task(data: TaskCreate, request: Request, db: Db, user: Current):
    assignee = None
    if data.assignee_user_id:
        assignee = db.scalar(select(User).where(User.id == data.assignee_user_id, User.organization_id == user.organization_id, User.is_active.is_(True)))
        if not assignee:
            raise HTTPException(422, "That assignee is not an active account in this workspace. Choose another owner.")
    row = workflow.create_task(db, organization_id=user.organization_id, title=data.title.strip(),
                               description=data.description.strip(), task_type="manual", priority=data.priority,
                               actor=user, assignee=assignee, action_path=data.action_path.strip())
    row.due_at = data.due_at
    audit.record(db, organization_id=user.organization_id, actor=user, action="create", entity_type="workflow_task",
                 entity_id=row.id, entity_label=row.task_number,
                 summary=f"Created task {row.title}" + (f" for {assignee.email}" if assignee else ""), request=request)
    db.commit()
    return task_out(db, row, user)


@router.post("/tasks/bulk", response_model=TaskBulkOut, dependencies=[Depends(require("tasks:read"))])
def bulk_tasks(data: TaskBulkIn, request: Request, db: Db, user: Current):
    unique_ids = list(dict.fromkeys(data.task_ids))
    if len(unique_ids) != len(data.task_ids):
        raise HTTPException(422, "Duplicate tasks are not allowed")
    rows = list(db.scalars(select(WorkflowTask).where(
        WorkflowTask.id.in_(unique_ids), WorkflowTask.organization_id == user.organization_id
    ).with_for_update()).all())
    assignee = None
    if data.action == "assign":
        if not data.assignee_user_id:
            raise HTTPException(422, "Choose the person this task moves to")
        assignee = db.scalar(select(User).where(User.id == data.assignee_user_id, User.organization_id == user.organization_id, User.is_active.is_(True)))
        if not assignee:
            raise HTTPException(422, "That assignee is not an active account in this workspace")
        if not (owner(user) or "tasks:manage" in granted(user)):
            raise HTTPException(403, "Only a task manager can reassign other people's work")
    target_status = {"claim": "in_progress", "complete": "completed", "reopen": "open", "cancel": "cancelled", "assign": None}[data.action]
    affected, skipped = 0, len(unique_ids) - len(rows)
    for row in rows:
        if data.action != "assign" and not can_manage_task(user, row):
            skipped += 1
            continue
        old = row.status
        if data.action == "claim" and row.assignee_user_id is None:
            row.assignee_user_id = user.id
        if data.action == "assign":
            row.assignee_user_id = assignee.id if assignee else None
        if target_status:
            row.status = target_status
            row.completed_at = utcnow() if target_status in ("completed", "cancelled") else None
        workflow.add_event(db, row, data.action, user, old=old, new=row.status, notes=data.notes.strip() or f"Bulk {data.action}")
        affected += 1
    audit.record(db, organization_id=user.organization_id, actor=user, action="bulk", entity_type="workflow_task",
                 entity_label=f"{affected} task(s)",
                 summary=f"Bulk {data.action} on {affected} task(s)" + (f" for {assignee.email}" if assignee else "")
                         + (f". Notes: {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return TaskBulkOut(action=data.action, affected=affected, skipped=skipped)


@router.patch("/tasks/{task_id}", response_model=TaskOut, dependencies=[Depends(require("tasks:read"))])
def update_task(task_id: str, data: TaskUpdate, request: Request, db: Db, user: Current):
    row = db.scalar(select(WorkflowTask).where(
        WorkflowTask.id == task_id, WorkflowTask.organization_id == user.organization_id
    ).with_for_update())
    if not row or not can_manage_task(user, row):
        # Same answer as the events endpoint: a task you cannot act on is not
        # disclosed, so the queue never leaks work to an unrelated account.
        raise HTTPException(404, "That task is not available to you. Refresh the list to see the work you can act on.")
    fields = data.model_fields_set
    if "assignee_user_id" in fields:
        if data.assignee_user_id:
            assignee = db.scalar(select(User).where(User.id == data.assignee_user_id, User.organization_id == user.organization_id, User.is_active.is_(True)))
            if not assignee:
                raise HTTPException(422, "That assignee is not an active account in this workspace. Choose another owner.")
            if not (owner(user) or "tasks:manage" in granted(user) or data.assignee_user_id == user.id):
                raise HTTPException(403, "Only a task manager can assign this work to somebody else")
            row.assignee_user_id = assignee.id
        else:
            row.assignee_user_id = None
    elif row.assignee_user_id is None and data.status == "in_progress":
        row.assignee_user_id = user.id
    if data.priority is not None:
        row.priority = data.priority
    if "due_at" in fields:
        row.due_at = data.due_at
    if data.title is not None:
        if row.task_type != "manual" and not (owner(user) or "tasks:manage" in granted(user)):
            raise HTTPException(403, "Only a task manager can rename a workflow task")
        row.title = data.title.strip()
    if data.description is not None:
        if row.task_type != "manual" and not (owner(user) or "tasks:manage" in granted(user)):
            raise HTTPException(403, "Only a task manager can rewrite a workflow task")
        row.description = data.description.strip()
    old = row.status
    if data.status is not None:
        row.status = data.status
        row.completed_at = utcnow() if data.status in ("completed", "cancelled") else None
    workflow.add_event(db, row, "updated", user, old=old, new=row.status, notes=data.notes.strip())
    audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="workflow_task",
                 entity_id=row.id, entity_label=row.task_number,
                 summary=f"Updated task {row.task_number}: {old} → {row.status}"
                         + (f". Notes: {data.notes.strip()}" if data.notes.strip() else ""), request=request)
    db.commit()
    return task_out(db, row, user)


@router.get("/tasks/{task_id}", response_model=TaskOut, dependencies=[Depends(require("tasks:read"))])
def task_detail(task_id: str, db: Db, user: Current):
    row = db.scalar(select(WorkflowTask).where(
        WorkflowTask.id == task_id, WorkflowTask.organization_id == user.organization_id))
    if not row or not can_manage_task(user, row):
        raise HTTPException(404, "That task is not available to you. Refresh the list to see the work you can act on.")
    return task_out(db, row, user)


@router.post("/tasks/{task_id}/comments", response_model=TaskEventOut, status_code=201, dependencies=[Depends(require("tasks:read"))])
def add_task_comment(task_id: str, data: TaskCommentIn, db: Db, user: Current):
    row = db.scalar(select(WorkflowTask).where(
        WorkflowTask.id == task_id, WorkflowTask.organization_id == user.organization_id))
    if not row or not can_manage_task(user, row):
        raise HTTPException(404, "That task is not available to you. Refresh the list to see the work you can act on.")
    event = workflow.add_event(db, row, "comment", user, notes=data.notes.strip())
    row.updated_at = utcnow()
    db.commit()
    db.refresh(event)
    return event


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventOut], dependencies=[Depends(require("tasks:read"))])
def task_events(task_id: str, db: Db, user: Current):
    row = db.scalar(select(WorkflowTask).where(WorkflowTask.id == task_id, WorkflowTask.organization_id == user.organization_id))
    if not row or not can_manage_task(user, row):
        raise HTTPException(404, "That task is not available to you. Refresh the list to see the work you can act on.")
    return db.scalars(select(WorkflowTaskEvent).where(
        WorkflowTaskEvent.task_id == row.id, WorkflowTaskEvent.organization_id == user.organization_id
    ).order_by(WorkflowTaskEvent.created_at)).all()
