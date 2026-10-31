"""Sign-in, session rotation and password changes.

The session model is deliberately small: a short-lived signed access token held
in memory by the browser, and an opaque refresh token in an HttpOnly cookie that
is rotated on every use. Rotation leaves a tombstone, so replaying a consumed
token revokes every session for that account instead of silently succeeding.
"""
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Current, Db, granted, owner
from app.core.config import get_settings
from app.core.request_security import client_ip, throttle
from app.core.security import (
    access_token,
    hash_password,
    new_refresh_session,
    effective_expiry,
    password_days_remaining,
    password_is_expired,
    refresh_hash,
    verify_password,
)
from app.core.time import as_utc, utcnow
from app.models import Organization, RefreshSession, User
from app.schemas.rbac import LoginInput, MeOut, UserOut
from app.services import audit, password_policy, workflow

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Unknown accounts still perform a password verification, reducing account
# enumeration through response-time differences.
_DUMMY_PASSWORD_HASH = hash_password("Timing-only-password-42!")
COOKIE_NAME = "refresh_token"
COOKIE_PATH = "/api/v1/auth"


def set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path=COOKIE_PATH,
        max_age=settings.refresh_token_days * 86400,
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
    )


def _session_facts(user: User) -> dict[str, object]:
    return {
        "must_change_password": bool(user.must_change_password),
        "password_expired": password_is_expired(user),
        "password_expires_at": effective_expiry(user),
        "password_days_remaining": password_days_remaining(user),
    }


def _trim_sessions(db: Db, user: User, *, keep: int | None = None) -> None:
    """Keep at most MAX_ACTIVE_SESSIONS live refresh sessions per account.

    Expired and revoked tombstones are purged at the same time; keeping every
    rotated row forever would turn a security improvement into unbounded storage.
    """
    limit = get_settings().max_active_sessions
    now = utcnow()
    live: list[RefreshSession] = []
    for session in list(user.sessions):
        expires_at = as_utc(session.expires_at)
        if session.revoked_at is not None or (expires_at and expires_at <= now):
            db.delete(session)
        else:
            live.append(session)
    sessions = sorted(live, key=lambda session: session.created_at or now)
    allowance = limit if keep is None else max(0, limit - keep)
    while len(sessions) > allowance:
        db.delete(sessions.pop(0))


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Db):
    settings = get_settings()
    # Applies even when the workspace or account does not exist, which is exactly
    # the case account lockout alone cannot slow down.
    throttle(db, request, "login", settings.login_attempt_limit)

    org = db.scalar(select(Organization).where(Organization.slug == data.organization.strip().lower()))
    user = db.scalar(select(User).where(User.organization_id == org.id, User.email == data.email.lower())) if org else None
    # Use the same public error for unknown tenants, users, and passwords.
    if not user or not user.is_active:
        verify_password(data.password, _DUMMY_PASSWORD_HASH)
        if org:
            audit.record(db, organization_id=org.id, actor_email=data.email.lower(), actor_name="",
                         action="login_failed", entity_type="auth", entity_label=data.email.lower(),
                         summary="Sign-in failed: unknown user or inactive account", request=request)
            db.commit()
        raise HTTPException(401, "Invalid credentials")

    locked_until = as_utc(user.locked_until)
    if locked_until and locked_until > utcnow():
        audit.record(db, organization_id=org.id, actor=user, action="login_blocked", entity_type="auth",
                     entity_label=user.email, summary="Sign-in refused: account temporarily locked", request=request)
        db.commit()
        raise HTTPException(429, "Too many attempts. Try again later.")

    if not verify_password(data.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= settings.max_failed_logins:
            user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
            user.failed_logins = 0
        audit.record(db, organization_id=org.id, actor=user, action="login_failed", entity_type="auth",
                     entity_label=user.email, summary="Sign-in failed: incorrect password", request=request)
        db.commit()
        raise HTTPException(401, "Invalid credentials")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    expired = password_is_expired(user)
    if expired:
        # Containment: an expired password can only be replaced, never used to
        # browse the workspace. The gate in api.deps enforces the same rule.
        first_notice = not user.must_change_password
        user.must_change_password = True
        audit.record(db, organization_id=org.id, actor=user, action="password_expired", entity_type="auth",
                     entity_label=user.email,
                     summary="Password reached its maximum age; a new password is required", request=request)
        if first_notice:
            workflow.notify(
                db, organization_id=org.id, recipients=[user], title="Your password has expired",
                message="Your password reached its maximum age. Set a new one to reopen the workspace.",
                severity="warning", notification_type="security", actor=user,
            )
    _trim_sessions(db, user, keep=1)
    token, session = new_refresh_session(user.id)
    db.add(session)
    audit.record(db, organization_id=org.id, actor=user, action="login", entity_type="auth",
                 entity_label=user.email, summary="Signed in", request=request)
    db.commit()
    set_cookie(response, token)
    return {
        "access_token": access_token(user.id, user.organization_id, user.token_version),
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        **_session_facts(user),
    }


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Db):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Session expired")
    session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == refresh_hash(token)).with_for_update()
    )
    if not session:
        clear_cookie(response)
        raise HTTPException(401, "Session expired")

    if session.revoked_at is not None:
        # A token that was already rotated (or revoked) has been presented again.
        # Either it leaked or the legitimate holder is replaying an old copy; in
        # both cases the safe answer is to end every session for the account.
        user = db.get(User, session.user_id)
        if user:
            for other in list(user.sessions):
                db.delete(other)
            user.token_version += 1
            audit.record(db, organization_id=user.organization_id, actor=user, action="refresh_reuse",
                         entity_type="auth", entity_label=user.email,
                         summary="Replayed refresh token detected; all sessions revoked", request=request)
            db.commit()
        clear_cookie(response)
        raise HTTPException(401, "Session expired. Sign in again.")

    user = db.get(User, session.user_id)
    expires_at = as_utc(session.expires_at)
    if not user or not user.is_active or (expires_at and expires_at <= utcnow()):
        db.delete(session)
        db.commit()
        clear_cookie(response)
        raise HTTPException(401, "Session expired")

    new_token, new_session = new_refresh_session(user.id)
    _trim_sessions(db, user, keep=1)
    db.add(new_session)
    db.flush()
    session.revoked_at = utcnow()
    session.replaced_by_hash = new_session.token_hash
    db.commit()
    set_cookie(response, new_token)
    return {
        "access_token": access_token(user.id, user.organization_id, user.token_version),
        "token_type": "bearer",
        **_session_facts(user),
    }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db):
    token = request.cookies.get(COOKIE_NAME)
    session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == refresh_hash(token))) if token else None
    if session:
        actor = db.get(User, session.user_id)
        if actor:
            audit.record(db, organization_id=actor.organization_id, actor=actor, action="logout", entity_type="auth",
                         entity_label=actor.email, summary="Signed out", request=request)
        db.delete(session)
        db.commit()
    clear_cookie(response)


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, user: Current, db: Db, response: Response):
    """Sign the account out everywhere and invalidate outstanding access tokens."""
    for session in list(user.sessions):
        db.delete(session)
    user.token_version += 1
    audit.record(db, organization_id=user.organization_id, actor=user, action="logout_all", entity_type="auth",
                 entity_label=user.email, summary="Signed out of every device", request=request)
    db.commit()
    clear_cookie(response)


@router.get("/me", response_model=MeOut)
def me(user: Current, db: Db):
    org = db.get(Organization, user.organization_id)
    return {
        **UserOut.model_validate(user).model_dump(),
        "organization_name": org.name if org else "",
        "organization_slug": org.slug if org else "",
        "permission_keys": sorted(granted(user)),
        "is_owner": owner(user),
        **_session_facts(user),
    }


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/change-password", status_code=204)
def change_password(data: PasswordChange, request: Request, user: Current, db: Db, response: Response):
    throttle(db, request, "change-password", get_settings().change_password_attempt_limit)
    if not verify_password(data.current_password, user.password_hash):
        audit.record(db, organization_id=user.organization_id, actor=user, action="password_change_failed",
                     entity_type="auth", entity_label=user.email,
                     summary="Password change rejected: current password incorrect", request=request)
        db.commit()
        raise HTTPException(400, "Current password is incorrect")
    if data.current_password == data.new_password:
        raise HTTPException(400, "New password must be different")
    try:
        password_policy.set_password(db, user, data.new_password)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    user.token_version += 1
    # End all sessions, including the current one. Client signs in again.
    for session in list(user.sessions):
        db.delete(session)
    audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="auth",
                 entity_label=user.email, summary="Changed password; all sessions revoked", request=request)
    db.commit()
    clear_cookie(response)


# ``client_ip`` is re-exported for callers that only import the auth router.
__all__ = ["router", "set_cookie", "clear_cookie", "client_ip"]
