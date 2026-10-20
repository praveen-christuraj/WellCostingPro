"""Allow deleting non-owner workspace users.

Existing tenants receive users:delete for the owner role only. Other roles
must be granted it explicitly by an administrator.

Revision ID: 6b8e4f1a2c90
Revises: e7f2a1c9b305
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision: str = "6b8e4f1a2c90"
down_revision: Union[str, None] = "e7f2a1c9b305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    organizations = sa.table("organizations", sa.column("id", sa.String(36)))
    permissions = sa.table("permissions", sa.column("id", sa.String(36)),
                           sa.column("organization_id", sa.String(36)), sa.column("key", sa.String(100)),
                           sa.column("description", sa.String(500)), sa.column("created_at", sa.DateTime(timezone=True)))
    roles = sa.table("roles", sa.column("id", sa.String(36)),
                     sa.column("organization_id", sa.String(36)), sa.column("is_owner", sa.Boolean()))
    role_permissions = sa.table("role_permissions", sa.column("role_id", sa.String(36)),
                                sa.column("permission_id", sa.String(36)))
    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        permission_id = bind.execute(sa.select(permissions.c.id).where(
            permissions.c.organization_id == organization_id, permissions.c.key == "users:delete"
        )).scalar_one_or_none()
        if permission_id is None:
            permission_id = str(uuid4())
            bind.execute(permissions.insert().values(
                id=permission_id, organization_id=organization_id, key="users:delete",
                description="Delete workspace users", created_at=datetime.now(timezone.utc),
            ))
        for (role_id,) in bind.execute(sa.select(roles.c.id).where(
            roles.c.organization_id == organization_id, roles.c.is_owner.is_(True)
        )):
            if not bind.execute(sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id, role_permissions.c.permission_id == permission_id
            )).first():
                bind.execute(role_permissions.insert().values(role_id=role_id, permission_id=permission_id))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key = 'users:delete')"))
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'users:delete'"))
