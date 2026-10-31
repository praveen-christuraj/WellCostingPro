from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class ForgotPasswordIn(BaseModel):
    organization: str = Field(min_length=1, max_length=80)
    email: EmailStr
    reason: str = Field(default="", max_length=1000)


class ResetPasswordIn(BaseModel):
    organization: str = Field(min_length=1, max_length=80)
    email: EmailStr
    reset_code: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirmation do not match")
        return self


class ReviewResetIn(BaseModel):
    notes: str = Field(default="", max_length=1000)


class PasswordResetOut(BaseModel):
    id: str
    request_number: str
    user_id: str
    user_name: str
    user_email: EmailStr
    status: str
    reason: str
    requested_at: datetime
    requested_by_ip: str
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    review_notes: str
    reset_token_expires_at: datetime | None
    completed_at: datetime | None
    # "user" when the account holder asked for help, "administrator" when the
    # security centre opened the request itself for a security reason.
    initiated_by: str = "user"


class ResetCodeOut(BaseModel):
    request: PasswordResetOut
    reset_code: str
    expires_at: datetime


class SecurityUserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    is_active: bool
    failed_logins: int
    locked_until: datetime | None
    must_change_password: bool
    password_changed_at: datetime | None
    password_expires_at: datetime | None = None
    password_expired: bool = False
    password_days_remaining: int | None = None
    last_login_at: datetime | None
    active_sessions: int
    role_names: list[str]
    is_owner: bool


class SecurityOverview(BaseModel):
    users: int
    active_users: int
    locked_users: int
    pending_requests: int
    awaiting_use: int
    must_change_password: int
    completed_30d: int
    announcements_30d: int
    reset_minutes: int
    recent_requests: list[PasswordResetOut]


class SecurityActionIn(BaseModel):
    """Reason recorded with an administrator-initiated account action."""

    notes: str = Field(default="", max_length=1000)


class SecurityBulkIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=200)
    action: str = Field(pattern="^(force-password-change|revoke-sessions|lock|unlock)$")
    notes: str = Field(default="", max_length=1000)


class SecurityBulkOut(BaseModel):
    action: str
    affected: int
    skipped: int


class NotificationCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=3, max_length=1000)
    severity: str = Field(default="info", pattern="^(info|success|warning|error)$")
    recipient_user_ids: list[str] = Field(default_factory=list, max_length=500)
    recipient_role_ids: list[str] = Field(default_factory=list, max_length=200)
    action_path: str = Field(default="", max_length=300)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    notification_type: str
    severity: str
    title: str
    message: str
    action_path: str
    related_entity_type: str
    related_entity_id: str
    announcement_id: str | None = None
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int
    page: int = 1
    page_size: int = 20
    counts: dict[str, int] = Field(default_factory=dict)


class NotificationIdsIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class NotificationOverview(BaseModel):
    total: int
    unread: int
    by_severity: dict[str, int]
    by_type: dict[str, int]
    announcements_sent: int
    oldest_unread_days: int


class AnnouncementOut(BaseModel):
    id: str
    title: str
    message: str
    severity: str
    action_path: str
    audience: str
    audience_label: str
    recipient_count: int
    created_by_name: str
    created_at: datetime
    recalled_at: datetime | None
    read_count: int


class AnnouncementPage(BaseModel):
    items: list[AnnouncementOut]
    total: int
    page: int
    page_size: int


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    assignee_user_id: str | None = None
    due_at: datetime | None = None
    action_path: str = Field(default="", max_length=300)


class TaskUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|in_progress|completed|cancelled)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high|critical)$")
    assignee_user_id: str | None = None
    due_at: datetime | None = None
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    notes: str = Field(default="", max_length=1000)


class TaskCommentIn(BaseModel):
    notes: str = Field(min_length=1, max_length=1000)


class TaskBulkIn(BaseModel):
    task_ids: list[str] = Field(min_length=1, max_length=200)
    action: str = Field(pattern="^(claim|complete|reopen|cancel|assign)$")
    assignee_user_id: str | None = None
    notes: str = Field(default="", max_length=1000)


class TaskBulkOut(BaseModel):
    action: str
    affected: int
    skipped: int


class TaskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    old_status: str
    new_status: str
    actor_name: str
    notes: str
    created_at: datetime


class TaskOut(BaseModel):
    id: str
    task_number: str
    task_type: str
    title: str
    description: str
    status: str
    priority: str
    required_permission: str
    assignee_user_id: str | None
    assignee_name: str
    created_by_user_id: str | None
    created_by_name: str
    due_at: datetime | None
    related_entity_type: str
    related_entity_id: str
    related_entity_label: str
    action_path: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    overdue: bool = False
    is_mine: bool = False
    can_manage: bool = False


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int


class TaskOverview(BaseModel):
    open: int
    in_progress: int
    overdue: int
    due_today: int
    completed_7d: int
    mine: int
    unassigned: int
    by_priority: dict[str, int]
    by_type: dict[str, int]
