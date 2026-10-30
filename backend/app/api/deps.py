from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User

Db = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)

# While an administrator has demanded a new password, the account may only reach
# the endpoints needed to comply. Everything else answers 403 with a message the
# UI turns into the "set a new password" screen.
PASSWORD_CHANGE_ALLOWED = {
    "/api/v1/auth/me",
    "/api/v1/auth/change-password",
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
}


def current_user(db: Db, request: Request, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if not credential:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        payload = jwt.decode(credential.credentials, get_settings().secret_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError()
        user = db.get(User, payload["sub"])
        if not user or not user.is_active or user.organization_id != payload.get("org") or user.token_version != payload.get("ver"):
            raise ValueError()
        if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Your administrator requires a new password before you can continue. "
                "Open the password screen and set one.",
            )
        return user
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token")


Current = Annotated[User, Depends(current_user)]


def granted(user: User) -> set[str]:
    return {permission.key for role in user.roles for permission in role.permissions}


def owner(user: User) -> bool:
    return any(role.is_owner for role in user.roles)


def require(key: str):
    def check(user: Current):
        if not owner(user) and key not in granted(user):
            # Naming the capability turns a dead end into a request the user can
            # make of their administrator; it never reveals another record.
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Permission denied. This action needs {key}.",
            )
        return user
    return check


def require_any(*keys: str):
    """Allow a surface that is shared by closely related capabilities.

    The security centre is the example: a reviewer may read the queue with
    `security:password-reset` even when the wider registers stay behind
    `security:read`, so an approval task never opens onto a dead end.
    """
    def check(user: Current):
        if not owner(user) and not set(keys).intersection(granted(user)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Permission denied. This action needs one of: {', '.join(keys)}.",
            )
        return user
    return check
