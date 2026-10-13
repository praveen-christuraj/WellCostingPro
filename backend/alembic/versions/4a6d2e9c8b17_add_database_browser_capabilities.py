"""Add Database Browser capabilities for Other Management.

Read-only module: no tables are created. Existing workspaces receive the two
``database-browser`` permission records, and their owner role is granted both.
Other roles stay unchanged until an administrator assigns the capabilities.

Revision ID: 4a6d2e9c8b17
Revises: 9c4f20b8a631
Create Date: 2026-10-13 09:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "4a6d2e9c8b17"
down_revision: Union[str, None] = "9c4f20b8a631"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DATABASE_BROWSER_CAPABILITIES = {
    "database-browser:read": "Browse tables, structure and rows of the workspace database",
    "database-browser:export": "Export Database Browser grids, structures and full table CSV downloads",
}


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
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(roles.c.organization_id == organization_id, roles.c.is_owner.is_(True))
        ).scalar_one_or_none()
        for key, description in DATABASE_BROWSER_CAPABILITIES.items():
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.organization_id == organization_id, permissions.c.key == key)
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = str(uuid4())
                bind.execute(
                    permissions.insert().values(
                        id=permission_id,
                        organization_id=organization_id,
                        key=key,
                        description=description,
                        created_at=datetime.now(timezone.utc),
                    )
                )
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
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key LIKE 'database-browser:%')"))
    op.execute(sa.text("DELETE FROM permissions WHERE key LIKE 'database-browser:%'"))
