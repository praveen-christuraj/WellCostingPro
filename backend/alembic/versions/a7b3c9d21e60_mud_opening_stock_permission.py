"""Grant owners the separately assignable mud opening-stock correction capability."""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "a7b3c9d21e60"
down_revision: Union[str, None] = "c4a7e1b93d52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OPENING_STOCK_CAPABILITIES = {
    "mud-cost:opening-stock-update": "Correct initial section mud opening stock and recalculate balances and costs",
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
        for key, description in OPENING_STOCK_CAPABILITIES.items():
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
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key = 'mud-cost:opening-stock-update')"))
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'mud-cost:opening-stock-update'"))
