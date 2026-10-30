"""security workflows, notifications and tasks

Revision ID: c3d7e9f1a204
Revises: a8d4f2c9e731
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d7e9f1a204"
down_revision = "a8d4f2c9e731"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_attempts_ip_hash", "password_reset_attempts", ["ip_hash"])
    op.create_index("ix_password_reset_attempts_attempted_at", "password_reset_attempts", ["attempted_at"])

    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_number", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_by_ip", sa.String(45), nullable=False, server_default=""),
        sa.Column("reviewed_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.String(1000), nullable=False, server_default=""),
        sa.Column("reset_token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("reset_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'completed', 'expired')", name="ck_password_reset_status"),
        sa.UniqueConstraint("organization_id", "request_number", name="uq_password_reset_org_number"),
    )
    op.create_index("ix_password_reset_requests_organization_id", "password_reset_requests", ["organization_id"])
    op.create_index("ix_password_reset_requests_user_id", "password_reset_requests", ["user_id"])
    op.create_index("ix_password_reset_org_status", "password_reset_requests", ["organization_id", "status", "requested_at"])

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notification_type", sa.String(40), nullable=False, server_default="system"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("action_path", sa.String(300), nullable=False, server_default=""),
        sa.Column("related_entity_type", sa.String(50), nullable=False, server_default=""),
        sa.Column("related_entity_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("severity IN ('info', 'success', 'warning', 'error')", name="ck_user_notification_severity"),
    )
    op.create_index("ix_user_notifications_organization_id", "user_notifications", ["organization_id"])
    op.create_index("ix_user_notifications_recipient_user_id", "user_notifications", ["recipient_user_id"])
    op.create_index("ix_user_notifications_recipient_read", "user_notifications", ["recipient_user_id", "read_at", "created_at"])

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_number", sa.String(40), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("required_permission", sa.String(100), nullable=False, server_default=""),
        sa.Column("assignee_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("related_entity_type", sa.String(50), nullable=False, server_default=""),
        sa.Column("related_entity_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("related_entity_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("action_path", sa.String(300), nullable=False, server_default=""),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'completed', 'cancelled')", name="ck_workflow_task_status"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'critical')", name="ck_workflow_task_priority"),
        sa.UniqueConstraint("organization_id", "task_number", name="uq_workflow_tasks_org_number"),
    )
    op.create_index("ix_workflow_tasks_organization_id", "workflow_tasks", ["organization_id"])
    op.create_index("ix_workflow_tasks_task_type", "workflow_tasks", ["task_type"])
    op.create_index("ix_workflow_tasks_status", "workflow_tasks", ["status"])
    op.create_index("ix_workflow_tasks_assignee_user_id", "workflow_tasks", ["assignee_user_id"])
    op.create_index("ix_workflow_tasks_org_status", "workflow_tasks", ["organization_id", "status", "created_at"])

    op.create_table(
        "workflow_task_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("workflow_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("old_status", sa.String(20), nullable=False, server_default=""),
        sa.Column("new_status", sa.String(20), nullable=False, server_default=""),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("notes", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_task_events_organization_id", "workflow_task_events", ["organization_id"])
    op.create_index("ix_workflow_task_events_task_id", "workflow_task_events", ["task_id"])

    connection = op.get_bind()
    capabilities = {
        "security:read": "Read security centre",
        "security:password-reset": "Review password reset requests",
        "security:unlock": "Unlock user accounts",
        "notifications:manage": "Send workspace notifications",
        "tasks:read": "Read workflow tasks",
        "tasks:create": "Create workflow tasks",
        "tasks:manage": "Manage workflow tasks",
    }
    for key, description in capabilities.items():
        rows = connection.execute(sa.text("SELECT id FROM organizations")).fetchall()
        for (organization_id,) in rows:
            permission_id = connection.execute(sa.text("SELECT id FROM permissions WHERE organization_id=:org AND key=:key"), {"org": organization_id, "key": key}).scalar()
            if permission_id is None:
                import uuid
                permission_id = str(uuid.uuid4())
                connection.execute(sa.text("INSERT INTO permissions (id, organization_id, key, description, created_at) VALUES (:id,:org,:key,:description,CURRENT_TIMESTAMP)"), {"id": permission_id, "org": organization_id, "key": key, "description": description})
            connection.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) SELECT id, :permission FROM roles WHERE organization_id=:org AND is_owner=true AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id=roles.id AND rp.permission_id=:permission)"), {"permission": permission_id, "org": organization_id})


def downgrade():
    connection = op.get_bind()
    keys = (
        "security:read", "security:password-reset", "security:unlock",
        "notifications:manage", "tasks:read", "tasks:create", "tasks:manage",
    )
    placeholders = ",".join(f":key_{index}" for index in range(len(keys)))
    parameters = {f"key_{index}": key for index, key in enumerate(keys)}
    connection.execute(sa.text(
        f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN ({placeholders}))"
    ), parameters)
    connection.execute(sa.text(f"DELETE FROM permissions WHERE key IN ({placeholders})"), parameters)
    op.drop_table("workflow_task_events")
    op.drop_table("workflow_tasks")
    op.drop_table("user_notifications")
    op.drop_table("password_reset_requests")
    op.drop_table("password_reset_attempts")
