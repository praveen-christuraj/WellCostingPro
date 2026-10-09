"""tenant-scoped master data management

Revision ID: a4c86b91e712
Revises: 3d9e6b51c4a0
Create Date: 2026-10-09 13:30:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "a4c86b91e712"
down_revision: Union[str, None] = "3d9e6b51c4a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MASTER_DATA_CAPABILITIES = {
    "master-data:read": "Read master data",
    "master-data:create": "Create master data",
    "master-data:update": "Update master data",
    "master-data:delete": "Move master data to deleted entries",
    "master-data:restore": "Restore deleted master data",
    "master-data:permanent-delete": "Permanently delete master data",
    "master-data:import": "Import master data",
    "master-data:export": "Export master data",
}


def _backfill_capabilities() -> None:
    """Make the new capabilities assignable in existing workspaces as well."""
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
    roles = sa.table(
        "roles",
        sa.column("id", sa.String(36)),
        sa.column("organization_id", sa.String(36)),
        sa.column("is_owner", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String(36)),
        sa.column("permission_id", sa.String(36)),
    )

    for (organization_id,) in bind.execute(sa.select(organizations.c.id)):
        owner_role_id = bind.execute(
            sa.select(roles.c.id).where(
                roles.c.organization_id == organization_id,
                roles.c.is_owner.is_(True),
            )
        ).scalar_one_or_none()
        for key, description in MASTER_DATA_CAPABILITIES.items():
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
                assignment = bind.execute(
                    sa.select(role_permissions.c.role_id).where(
                        role_permissions.c.role_id == owner_role_id,
                        role_permissions.c.permission_id == permission_id,
                    )
                ).first()
                if assignment is None:
                    bind.execute(
                        role_permissions.insert().values(
                            role_id=owner_role_id,
                            permission_id=permission_id,
                        )
                    )


def upgrade() -> None:
    op.create_table(
        "uom",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit_code", sa.String(length=50), nullable=False),
        sa.Column("unit_name", sa.String(length=150), nullable=False),
        sa.Column("unit_symbol", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "unit_code", name="uq_uom_org_code"),
    )
    op.create_index(op.f("ix_uom_organization_id"), "uom", ["organization_id"], unique=False)

    op.create_table(
        "currencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency_code", sa.String(length=10), nullable=False),
        sa.Column("currency_name", sa.String(length=100), nullable=False),
        sa.Column("currency_symbol", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "currency_code", name="uq_currencies_org_code"),
    )
    op.create_index(op.f("ix_currencies_organization_id"), "currencies", ["organization_id"], unique=False)

    op.create_table(
        "phases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase_code", sa.String(length=50), nullable=False),
        sa.Column("phase_name", sa.String(length=150), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "phase_code", name="uq_phases_org_code"),
    )
    op.create_index(op.f("ix_phases_organization_id"), "phases", ["organization_id"], unique=False)

    op.create_table(
        "hole_sections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("section_code", sa.String(length=50), nullable=False),
        sa.Column("section_name", sa.String(length=150), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "section_code", name="uq_hole_sections_org_code"),
    )
    op.create_index(op.f("ix_hole_sections_organization_id"), "hole_sections", ["organization_id"], unique=False)

    op.create_table(
        "activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activity_code", sa.String(length=50), nullable=False),
        sa.Column("activity_name", sa.String(length=150), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "activity_code", name="uq_activities_org_code"),
    )
    op.create_index(op.f("ix_activities_organization_id"), "activities", ["organization_id"], unique=False)

    _backfill_capabilities()


def downgrade() -> None:
    bind = op.get_bind()
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String(36)),
        sa.column("key", sa.String(100)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String(36)),
        sa.column("permission_id", sa.String(36)),
    )
    permission_ids = list(
        bind.execute(
            sa.select(permissions.c.id).where(
                permissions.c.key.in_(tuple(MASTER_DATA_CAPABILITIES))
            )
        ).scalars()
    )
    if permission_ids:
        bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
        bind.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))

    op.drop_index(op.f("ix_activities_organization_id"), table_name="activities")
    op.drop_table("activities")
    op.drop_index(op.f("ix_hole_sections_organization_id"), table_name="hole_sections")
    op.drop_table("hole_sections")
    op.drop_index(op.f("ix_phases_organization_id"), table_name="phases")
    op.drop_table("phases")
    op.drop_index(op.f("ix_currencies_organization_id"), table_name="currencies")
    op.drop_table("currencies")
    op.drop_index(op.f("ix_uom_organization_id"), table_name="uom")
    op.drop_table("uom")
