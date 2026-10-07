from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User

Db = Annotated[Session, Depends(get_db)]
bearer = HTTPBearer(auto_error=False)


def current_user(db: Db, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if not credential:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        payload = jwt.decode(credential.credentials, get_settings().secret_key, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError()
        user = db.get(User, payload["sub"])
        if not user or not user.is_active or user.organization_id != payload.get("org") or user.token_version != payload.get("ver"):
            raise ValueError()
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
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
        return user
    return check
