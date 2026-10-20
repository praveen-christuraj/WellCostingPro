"""Add the users:delete capability.

Administrators could create and edit workspace members but not remove them:
there was no delete endpoint and no capability to gate one. This revision adds
the ``users:delete`` permission record to every workspace and grants it to the
immutable owner role, so existing administrators can delete ordinary accounts
immediately after deploying. Other roles stay unchanged until an administrator
assigns the capability. Owner accounts themselves remain protected.

Revision ID: f1c4a8e27d05
Revises: e7f2a1c9b305
Create Date: 2026-10-20 09:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "f1c4a8e27d05"
down_revision: Union[str, None] = "e7f2a1c9b305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


USER_DELETE_CAPABILITY = "users:delete"
USER_DELETE_DESCRIPTION = "Delete workspace users"


def upgrade() -> None:
    bind = op.get_bind()
    organizations = sa.table("organizations", sa.column("id", sa.String(36)))
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("key", sa.String(100)),
        sa.column("description", sa.String(500)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table("roles", sa.column("id", sa.String(36)), sa.column("organization_id", sa.String(36)), sa.column("is_owner", sa.Boolean()))
    role_permissions = sa.table("role_permissions", sa.column("role_id", sa.String(36)), sa.column("permission_id", sa.String(36)))

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        permission_id = bind.execute(
            sa.select(permissions.c.id).where(
                permissions.c.organization_id == organization_id,
                permissions.c.key == USER_DELETE_CAPABILITY,
            )
        ).scalar_one_or_none()
        if permission_id is None:
            permission_id = str(uuid4())
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    organization_id=organization_id,
                    key=USER_DELETE_CAPABILITY,
                    description=USER_DELETE_DESCRIPTION,
                    created_at=datetime.now(timezone.utc),
                )
            )
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(roles.c.organization_id == organization_id, roles.c.is_owner.is_(True))
        ).scalar_one_or_none()
        if owner_role_id:
            assigned = bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == owner_role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if assigned is None:
                bind.execute(role_permissions.insert().values(role_id=owner_role_id, permission_id=permission_id))


def downgrade() -> None:
    # Remove assignments before the permission rows they reference.
    op.execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE key = 'users:delete')"
    ))
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'users:delete'"))
