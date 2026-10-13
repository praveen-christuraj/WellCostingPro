"""Add private reusable costing sets.

Revision ID: a7e2c6b4d901
Revises: c9b7e4a2d518
Create Date: 2026-10-13 11:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "a7e2c6b4d901"
down_revision: Union[str, None] = "c9b7e4a2d518"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COSTING_SET_CAPABILITIES = {
    "costing-sets:read": "View private reusable service and catalogue-item sets",
    "costing-sets:create": "Create reusable costing sets",
    "costing-sets:update": "Update reusable costing sets",
    "costing-sets:delete": "Delete reusable costing sets",
    "costing-sets:import": "Import reusable costing sets",
    "costing-sets:export": "Export reusable costing sets",
}


def upgrade() -> None:
    op.create_table(
        "user_costing_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(100), nullable=False),
        sa.Column("item_group", sa.String(20), nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "organization_id", "user_id", "item_group", "name_key",
            name="uq_user_costing_sets_owner_name",
        ),
        sa.CheckConstraint(
            "item_group IN ('services', 'tangibles', 'consumables')",
            name="ck_user_costing_sets_group",
        ),
    )
    op.create_index("ix_user_costing_sets_organization_id", "user_costing_sets", ["organization_id"])
    op.create_index("ix_user_costing_sets_user_id", "user_costing_sets", ["user_id"])
    op.create_index("ix_user_costing_sets_org_user", "user_costing_sets", ["organization_id", "user_id"])

    op.create_table(
        "user_costing_set_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("set_id", sa.String(36), nullable=False),
        sa.Column("item_kind", sa.String(30), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("item_code_snapshot", sa.String(100), nullable=False),
        sa.Column("item_name_snapshot", sa.String(200), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["set_id"], ["user_costing_sets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("set_id", "item_kind", "item_id", name="uq_user_costing_set_items_item"),
        sa.CheckConstraint(
            "item_kind IN ('service', 'tangible', 'mud_chemical', 'cement_additive', 'fuel', 'drill_bit')",
            name="ck_user_costing_set_items_kind",
        ),
    )
    op.create_index("ix_user_costing_set_items_organization_id", "user_costing_set_items", ["organization_id"])
    op.create_index("ix_user_costing_set_items_set_id", "user_costing_set_items", ["set_id"])
    op.create_index(
        "ix_user_costing_set_items_org_set",
        "user_costing_set_items",
        ["organization_id", "set_id", "sort_order"],
    )

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
        for key, description in COSTING_SET_CAPABILITIES.items():
            permission_id = bind.execute(
                sa.select(permissions.c.id).where(
                    permissions.c.organization_id == organization_id,
                    permissions.c.key == key,
                )
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
    op.execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE key LIKE 'costing-sets:%')"
    ))
    op.execute(sa.text("DELETE FROM permissions WHERE key LIKE 'costing-sets:%'"))
    op.drop_table("user_costing_set_items")
    op.drop_table("user_costing_sets")
