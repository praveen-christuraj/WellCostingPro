from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PermissionCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*$", max_length=100)
    description: str = Field(default="", max_length=500)


class PermissionUpdate(BaseModel):
    description: str = Field(max_length=500)


class PermissionOut(ORMModel):
    id: str
    key: str
    description: str
    created_at: datetime


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class RoleOut(ORMModel):
    id: str
    name: str
    description: str
    is_owner: bool
    created_at: datetime
    permissions: list[PermissionOut]


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    role_ids: list[str] = Field(default_factory=list)
    # When true the new account must choose its own password before the workspace
    # opens, so the administrator who typed the initial value never keeps a
    # working credential for somebody else's account.
    require_password_change: bool = False


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    is_active: bool | None = None


class UserOut(ORMModel):
    id: str
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime
    roles: list[RoleOut]
    # Whether the account still has to choose its own password. Surfaced so the
    # register can show it instead of an administrator guessing from the audit trail.
    must_change_password: bool = False


class IDList(BaseModel):
    ids: list[str]


class LoginInput(BaseModel):
    """Sign-in input, bounded so an oversized body cannot reach the hash function."""

    organization: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MeOut(UserOut):
    organization_name: str
    organization_slug: str
    permission_keys: list[str]
    is_owner: bool
    # A security-centre action (or password age) can demand a new password before
    # anything else is reachable. The UI gates the workspace on both flags.
    must_change_password: bool = False
    password_expired: bool = False
    password_changed_at: datetime | None = None
    password_expires_at: datetime | None = None
    password_days_remaining: int | None = None


class Overview(BaseModel):
    users: int
    active_users: int
    roles: int
    permissions: int
    recent_users: list[UserOut]
    role_distribution: list[dict]


class AuditOut(ORMModel):
    id: str
    actor_user_id: str | None
    actor_email: str
    actor_name: str
    action: str
    entity_type: str
    entity_id: str | None
    entity_label: str
    summary: str
    ip_address: str
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    page_size: int
