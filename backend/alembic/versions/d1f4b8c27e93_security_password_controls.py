"""Administrator password controls, password history and announcements.

Adds the account-state columns the Security centre manages without waiting for a
user request (forced password change, password age, last sign-in), the typed
password-history table used for reuse prevention, and the announcement header
that lets a sender review or recall a broadcast.

Revision ID: d1f4b8c27e93
Revises: c3d7e9f1a204
Create Date: 2026-10-30 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f4b8c27e93"
down_revision: Union[str, None] = "c3d7e9f1a204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN works on every supported engine, so the users table (which
    # several tables reference) is never rebuilt by a batch copy.
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("password_reset_requests", sa.Column("initiated_by", sa.String(20), nullable=False, server_default="user"))

    op.create_table(
        "password_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_history_organization_id", "password_history", ["organization_id"])
    op.create_index("ix_password_history_user_id", "password_history", ["user_id"])
    op.create_index("ix_password_history_user_created", "password_history", ["user_id", "created_at"])

    op.create_table(
        "announcements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("action_path", sa.String(300), nullable=False, server_default=""),
        sa.Column("audience", sa.String(20), nullable=False, server_default="all"),
        sa.Column("audience_label", sa.String(300), nullable=False, server_default=""),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recalled_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("severity IN ('info', 'success', 'warning', 'error')", name="ck_announcement_severity"),
        sa.CheckConstraint("audience IN ('all', 'roles', 'users')", name="ck_announcement_audience"),
    )
    op.create_index("ix_announcements_organization_id", "announcements", ["organization_id"])
    op.create_index("ix_announcements_org_created", "announcements", ["organization_id", "created_at"])

    op.add_column("user_notifications", sa.Column("announcement_id", sa.String(36), nullable=True))
    op.create_index("ix_user_notifications_announcement_id", "user_notifications", ["announcement_id"])


def downgrade() -> None:
    op.drop_index("ix_user_notifications_announcement_id", table_name="user_notifications")
    op.drop_column("user_notifications", "announcement_id")
    op.drop_index("ix_announcements_org_created", table_name="announcements")
    op.drop_index("ix_announcements_organization_id", table_name="announcements")
    op.drop_table("announcements")
    op.drop_index("ix_password_history_user_created", table_name="password_history")
    op.drop_index("ix_password_history_user_id", table_name="password_history")
    op.drop_index("ix_password_history_organization_id", table_name="password_history")
    op.drop_table("password_history")
    op.drop_column("password_reset_requests", "initiated_by")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
