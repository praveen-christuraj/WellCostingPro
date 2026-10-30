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


class NotificationCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=3, max_length=1000)
    severity: str = Field(default="info", pattern="^(info|success|warning|error)$")
    recipient_user_ids: list[str] = Field(default_factory=list, max_length=500)
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
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread_count: int


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
    notes: str = Field(default="", max_length=1000)


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
    due_at: datetime | None
    related_entity_type: str
    related_entity_id: str
    related_entity_label: str
    action_path: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int
