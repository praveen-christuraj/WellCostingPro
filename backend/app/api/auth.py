from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from app.api.deps import Current, Db, granted, owner
from app.core.config import get_settings
from app.core.security import access_token, new_refresh_session, refresh_hash, verify_password
from app.models import Organization, User, RefreshSession
from app.schemas.rbac import LoginInput, MeOut, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])


def set_cookie(response: Response, token: str):
    settings = get_settings()
    response.set_cookie("refresh_token", token, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/api/v1/auth", max_age=settings.refresh_token_days * 86400)


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Db):
    org = db.scalar(select(Organization).where(Organization.slug == data.organization.strip().lower()))
    user = db.scalar(select(User).where(User.organization_id == org.id, User.email == data.email.lower())) if org else None
    # Use the same public error for unknown tenants, users, and passwords.
    if not user or not user.is_active:
        if org:
            audit.record(db, organization_id=org.id, actor_email=data.email.lower(), actor_name="",
                         action="login_failed", entity_type="auth", entity_label=data.email.lower(),
                         summary="Sign-in failed: unknown user or inactive account", request=request)
            db.commit()
        raise HTTPException(401, "Invalid credentials")
    locked = user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    if locked:
        raise HTTPException(429, "Too many attempts. Try again later.")
    if not verify_password(data.password, user.password_hash):
        from datetime import timedelta
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            user.failed_logins = 0
        audit.record(db, organization_id=org.id, actor=user, action="login_failed", entity_type="auth",
                     entity_label=user.email, summary="Sign-in failed: incorrect password", request=request)
        db.commit()
        raise HTTPException(401, "Invalid credentials")
    user.failed_logins = 0
    user.locked_until = None
    token, session = new_refresh_session(user.id)
    db.add(session)
    audit.record(db, organization_id=org.id, actor=user, action="login", entity_type="auth",
                 entity_label=user.email, summary="Signed in", request=request)
    db.commit()
    set_cookie(response, token)
    return {"access_token": access_token(user.id, user.organization_id, user.token_version), "token_type": "bearer"}


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Db):
    token = request.cookies.get("refresh_token")
    session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == refresh_hash(token))) if token else None
    if not session:
        raise HTTPException(401, "Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.is_active or session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise HTTPException(401, "Session expired")
    db.delete(session)
    new_token, new_session = new_refresh_session(user.id)
    db.add(new_session)
    db.commit()
    set_cookie(response, new_token)
    return {"access_token": access_token(user.id, user.organization_id, user.token_version), "token_type": "bearer"}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db):
    token = request.cookies.get("refresh_token")
    session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == refresh_hash(token))) if token else None
    if session:
        actor = db.get(User, session.user_id)
        if actor:
            audit.record(db, organization_id=actor.organization_id, actor=actor, action="logout", entity_type="auth",
                         entity_label=actor.email, summary="Signed out", request=request)
        db.delete(session)
        db.commit()
    response.delete_cookie("refresh_token", path="/api/v1/auth")


@router.get("/me", response_model=MeOut)
def me(user: Current, db: Db):
    org = db.get(Organization, user.organization_id)
    return {**UserOut.model_validate(user).model_dump(), "organization_name": org.name, "organization_slug": org.slug, "permission_keys": sorted(granted(user)), "is_owner": owner(user)}


from pydantic import BaseModel, Field
from app.core.security import hash_password


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/change-password", status_code=204)
def change_password(data: PasswordChange, request: Request, user: Current, db: Db, response: Response):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if data.current_password == data.new_password:
        raise HTTPException(400, "New password must be different")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    # End all sessions, including the current one. Client signs in again.
    for session in list(user.sessions):
        db.delete(session)
    audit.record(db, organization_id=user.organization_id, actor=user, action="update", entity_type="auth",
                 entity_label=user.email, summary="Changed password; all sessions revoked", request=request)
    db.commit()
    response.delete_cookie("refresh_token", path="/api/v1/auth")
