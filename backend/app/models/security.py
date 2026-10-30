"""Security operations, notifications and workflow tasks.

All targeting and history is stored in ordinary typed columns. A notification
is materialised once per recipient; no JSON recipient lists or secret reset
codes are persisted.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.entities import now, uid


class PasswordResetAttempt(Base):
    __tablename__ = "password_reset_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)


class PasswordResetRequest(Base):
    __tablename__ = "password_reset_requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_number", name="uq_password_reset_org_number"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'completed', 'expired')", name="ck_password_reset_status"),
        Index("ix_password_reset_org_status", "organization_id", "status", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    request_number: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", nullable=False)
    # "user" when the account holder asked for help, "administrator" when the
    # security centre opened the request itself for a security reason.
    initiated_by: Mapped[str] = mapped_column(String(20), default="user", server_default="user", nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    requested_by_ip: Mapped[str] = mapped_column(String(45), default="", server_default="", nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordHistory(Base):
    """Recently used password hashes, so a password cannot simply be reused.

    Rows are typed columns only: the hash is a one-way verifier, never the
    password itself, and the newest N rows per user are kept.
    """

    __tablename__ = "password_history"
    __table_args__ = (
        Index("ix_password_history_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class Announcement(Base):
    """The administrative header for a workspace announcement.

    One row is created per broadcast; one `UserNotification` row per recipient
    points back to it, so the sender can see (and recall) what was delivered.
    """

    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'success', 'warning', 'error')", name="ck_announcement_severity"),
        CheckConstraint("audience IN ('all', 'roles', 'users')", name="ck_announcement_audience"),
        Index("ix_announcements_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="info", server_default="info", nullable=False)
    action_path: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    audience: Mapped[str] = mapped_column(String(20), default="all", server_default="all", nullable=False)
    audience_label: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    recalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recalled_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'success', 'warning', 'error')", name="ck_user_notification_severity"),
        Index("ix_user_notifications_recipient_read", "recipient_user_id", "read_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notification_type: Mapped[str] = mapped_column(String(40), default="system", server_default="system", nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="info", server_default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    action_path: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    related_entity_type: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    related_entity_id: Mapped[str] = mapped_column(String(36), default="", server_default="", nullable=False)
    announcement_id: Mapped[str | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class WorkflowTask(Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "task_number", name="uq_workflow_tasks_org_number"),
        CheckConstraint("status IN ('open', 'in_progress', 'completed', 'cancelled')", name="ck_workflow_task_status"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'critical')", name="ck_workflow_task_priority"),
        Index("ix_workflow_tasks_org_status", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    task_number: Mapped[str] = mapped_column(String(40), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), default="manual", server_default="manual", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", server_default="normal", nullable=False)
    required_permission: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    related_entity_type: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    related_entity_id: Mapped[str] = mapped_column(String(36), default="", server_default="", nullable=False)
    related_entity_label: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    action_path: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    events: Mapped[list["WorkflowTaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True, order_by="WorkflowTaskEvent.created_at"
    )


class WorkflowTaskEvent(Base):
    __tablename__ = "workflow_task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("workflow_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    old_status: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    new_status: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    notes: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    task: Mapped[WorkflowTask] = relationship(back_populates="events")
