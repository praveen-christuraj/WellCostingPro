"""Add tenant-scoped Rig & Well Management and well sub activities.

Revision ID: f3a7d0b9c214
Revises: e5b0c7a9f213
Create Date: 2026-10-10 17:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "f3a7d0b9c214"
down_revision: Union[str, None] = "e5b0c7a9f213"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RIG_WELL_CAPABILITIES = {
    "rig-well:read": "Read rigs, wells, configuration, and well sub activities",
    "rig-well:create": "Create rigs, wells, configuration, and well sub activities",
    "rig-well:update": "Update rigs, wells, configuration, and well sub activities",
    "rig-well:delete": "Move rig and well records to Deleted Entries",
    "rig-well:restore": "Restore deleted rig and well records",
    "rig-well:permanent-delete": "Permanently delete records from Deleted Entries",
    "rig-well:import": "Import rigs, wells, and well sub activities",
    "rig-well:export": "Export rigs, wells, and well sub activities",
}


def _backfill_capabilities() -> None:
    """Make module permissions available to existing workspaces and owners."""
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
        for key, description in RIG_WELL_CAPABILITIES.items():
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
                    bind.execute(
                        role_permissions.insert().values(
                            role_id=owner_role_id,
                            permission_id=permission_id,
                        )
                    )


def upgrade() -> None:
    op.create_table(
        "rigs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rig_code", sa.String(length=50), nullable=False),
        sa.Column("rig_name", sa.String(length=200), nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "rig_code", name="uq_rigs_org_code"),
    )
    op.create_index("ix_rigs_organization_id", "rigs", ["organization_id"])
    op.create_index("ix_rigs_org_deleted", "rigs", ["organization_id", "is_deleted"])

    op.create_table(
        "wells",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=False),
        sa.Column("well_code", sa.String(length=50), nullable=False),
        sa.Column("well_name", sa.String(length=200), nullable=False),
        sa.Column("well_location", sa.String(length=300), nullable=False),
        sa.Column("block", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.String(length=500), nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("config_status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("depth_unit", sa.String(length=10), server_default="m", nullable=False),
        sa.CheckConstraint("status IN ('active', 'completed')", name="ck_wells_status"),
        sa.CheckConstraint("config_status IN ('draft', 'configured')", name="ck_wells_config_status"),
        sa.CheckConstraint("depth_unit IN ('m', 'ft')", name="ck_wells_depth_unit"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "well_code", name="uq_wells_org_code"),
    )
    op.create_index("ix_wells_organization_id", "wells", ["organization_id"])
    op.create_index("ix_wells_rig_id", "wells", ["rig_id"])
    op.create_index("ix_wells_org_rig", "wells", ["organization_id", "rig_id"])
    op.create_index("ix_wells_org_deleted", "wells", ["organization_id", "is_deleted"])

    op.create_table(
        "well_sections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=False),
        sa.Column("from_depth", sa.Numeric(18, 2), nullable=False),
        sa.Column("to_depth", sa.Numeric(18, 2), nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("well_id", "sort_order", name="uq_well_sections_order"),
    )
    op.create_index("ix_well_sections_organization_id", "well_sections", ["organization_id"])
    op.create_index("ix_well_sections_well_id", "well_sections", ["well_id"])
    op.create_index("ix_well_sections_hole_section_id", "well_sections", ["hole_section_id"])
    op.create_index("ix_well_sections_org_well", "well_sections", ["organization_id", "well_id"])

    op.create_table(
        "well_phases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("phase_id", sa.String(length=36), nullable=False),
        sa.Column("days", sa.Numeric(12, 2), nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["well_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "sort_order", name="uq_well_phases_order"),
    )
    op.create_index("ix_well_phases_organization_id", "well_phases", ["organization_id"])
    op.create_index("ix_well_phases_section_id", "well_phases", ["section_id"])
    op.create_index("ix_well_phases_phase_id", "well_phases", ["phase_id"])
    op.create_index("ix_well_phases_org_section", "well_phases", ["organization_id", "section_id"])

    op.create_table(
        "well_sub_activities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("sub_activity_code", sa.String(length=50), nullable=False),
        sa.Column("sub_activity_name", sa.String(length=150), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("responsible_party", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "well_id", "sub_activity_code",
            name="uq_well_sub_activities_org_well_code",
        ),
    )
    op.create_index("ix_well_sub_activities_organization_id", "well_sub_activities", ["organization_id"])
    op.create_index("ix_well_sub_activities_well_id", "well_sub_activities", ["well_id"])
    op.create_index("ix_well_sub_activities_activity_id", "well_sub_activities", ["activity_id"])
    op.create_index("ix_well_sub_activities_org_deleted", "well_sub_activities", ["organization_id", "is_deleted"])
    op.create_index("ix_well_sub_activities_org_activity", "well_sub_activities", ["organization_id", "activity_id"])

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
                permissions.c.key.in_(tuple(RIG_WELL_CAPABILITIES))
            )
        ).scalars()
    )
    if permission_ids:
        bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
        bind.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))

    op.drop_index("ix_well_sub_activities_org_activity", table_name="well_sub_activities")
    op.drop_index("ix_well_sub_activities_org_deleted", table_name="well_sub_activities")
    op.drop_index("ix_well_sub_activities_activity_id", table_name="well_sub_activities")
    op.drop_index("ix_well_sub_activities_well_id", table_name="well_sub_activities")
    op.drop_index("ix_well_sub_activities_organization_id", table_name="well_sub_activities")
    op.drop_table("well_sub_activities")

    op.drop_index("ix_well_phases_org_section", table_name="well_phases")
    op.drop_index("ix_well_phases_phase_id", table_name="well_phases")
    op.drop_index("ix_well_phases_section_id", table_name="well_phases")
    op.drop_index("ix_well_phases_organization_id", table_name="well_phases")
    op.drop_table("well_phases")

    op.drop_index("ix_well_sections_org_well", table_name="well_sections")
    op.drop_index("ix_well_sections_hole_section_id", table_name="well_sections")
    op.drop_index("ix_well_sections_well_id", table_name="well_sections")
    op.drop_index("ix_well_sections_organization_id", table_name="well_sections")
    op.drop_table("well_sections")

    op.drop_index("ix_wells_org_deleted", table_name="wells")
    op.drop_index("ix_wells_org_rig", table_name="wells")
    op.drop_index("ix_wells_rig_id", table_name="wells")
    op.drop_index("ix_wells_organization_id", table_name="wells")
    op.drop_table("wells")

    op.drop_index("ix_rigs_org_deleted", table_name="rigs")
    op.drop_index("ix_rigs_organization_id", table_name="rigs")
    op.drop_table("rigs")
