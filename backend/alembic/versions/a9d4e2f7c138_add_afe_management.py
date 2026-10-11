"""Add tenant-scoped AFE register and AFE cost estimation.

Revision ID: a9d4e2f7c138
Revises: f3a7d0b9c214
Create Date: 2026-10-11 09:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "a9d4e2f7c138"
down_revision: Union[str, None] = "f3a7d0b9c214"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AFE_CAPABILITIES = {
    "afe:read": "Read AFEs, well scope and AFE cost estimates",
    "afe:create": "Create AFEs for wells",
    "afe:update": "Edit AFE header details",
    "afe:delete": "Move AFEs to Deleted Entries",
    "afe:restore": "Restore deleted AFEs",
    "afe:permanent-delete": "Permanently delete AFEs from Deleted Entries",
    "afe:import": "Import AFEs",
    "afe:export": "Export and print AFEs and cost estimates",
    "afe:estimate": "Edit AFE cost estimate lines while the AFE is a draft",
    "afe:submit": "Submit a draft AFE for review",
    "afe:review": "Move a submitted AFE into review",
    "afe:approve": "Approve an AFE that is under review",
    "afe:reopen": "Reopen a submitted, reviewed or approved AFE as a draft",
}


def _backfill_capabilities() -> None:
    """Make AFE permissions available to existing workspaces and owners."""
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
        for key, description in AFE_CAPABILITIES.items():
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


def _org_column() -> sa.Column:
    return sa.Column("organization_id", sa.String(length=36), nullable=False)


def _child_timestamps() -> list[sa.Column]:
    return [
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "afes",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("rig_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("afe_code", sa.String(length=50), nullable=False),
        sa.Column("afe_name", sa.String(length=200), nullable=False),
        sa.Column("afe_type", sa.String(length=20), nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("status_remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("estimate_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimate_saved_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("afe_type IN ('Drilling', 'Completion')", name="ck_afes_type"),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'review', 'approval')", name="ck_afes_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "afe_code", name="uq_afes_org_code"),
    )
    op.create_index("ix_afes_organization_id", "afes", ["organization_id"])
    op.create_index("ix_afes_rig_id", "afes", ["rig_id"])
    op.create_index("ix_afes_well_id", "afes", ["well_id"])
    op.create_index("ix_afes_org_deleted", "afes", ["organization_id", "is_deleted"])
    op.create_index("ix_afes_org_well", "afes", ["organization_id", "well_id"])

    op.create_table(
        "afe_service_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("afe_id", sa.String(length=36), nullable=False),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column("charging_basis", sa.String(length=30), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=True),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default="", nullable=False),
        sa.Column("service_amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        *_child_timestamps(),
        sa.CheckConstraint(
            "charging_basis IN ('Day Rate', 'Per Service Rate', 'Per Section Rate')",
            name="ck_afe_service_lines_basis",
        ),
        sa.CheckConstraint("service_amount >= 0", name="ck_afe_service_lines_amount"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["afe_id"], ["afes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_afe_service_lines_organization_id", "afe_service_lines", ["organization_id"])
    op.create_index("ix_afe_service_lines_afe", "afe_service_lines", ["afe_id"])
    op.create_index("ix_afe_service_lines_service_id", "afe_service_lines", ["service_id"])
    op.create_index("ix_afe_service_lines_hole_section_id", "afe_service_lines", ["hole_section_id"])
    op.create_index("ix_afe_service_lines_phase_id", "afe_service_lines", ["phase_id"])

    op.create_table(
        "afe_service_rates",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("line_id", sa.String(length=36), nullable=False),
        sa.Column("charge_category", sa.String(length=40), nullable=False),
        sa.Column("unit_rate", sa.Numeric(18, 4), server_default="0", nullable=False),
        *_child_timestamps(),
        sa.CheckConstraint(
            "charge_category IN ('Mobilization', 'Demobilization', 'Operation', 'Standby', "
            "'Personnel-Operation', 'Personnel-Standby', 'Fixed Charge', 'Others')",
            name="ck_afe_service_rates_category",
        ),
        sa.CheckConstraint("unit_rate >= 0", name="ck_afe_service_rates_rate"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["line_id"], ["afe_service_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("line_id", "charge_category", name="uq_afe_service_rates_category"),
    )
    op.create_index("ix_afe_service_rates_organization_id", "afe_service_rates", ["organization_id"])
    op.create_index("ix_afe_service_rates_line_id", "afe_service_rates", ["line_id"])

    op.create_table(
        "afe_service_charges",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("line_id", sa.String(length=36), nullable=False),
        sa.Column("charge_category", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 4), server_default="0", nullable=False),
        sa.Column("quantity_unit", sa.String(length=10), server_default="days", nullable=False),
        *_child_timestamps(),
        sa.CheckConstraint(
            "charge_category IN ('Mobilization', 'Demobilization', 'Operation', 'Standby', "
            "'Personnel-Operation', 'Personnel-Standby', 'Fixed Charge', 'Others')",
            name="ck_afe_service_charges_category",
        ),
        sa.CheckConstraint("quantity_unit IN ('days', 'hours')", name="ck_afe_service_charges_unit"),
        sa.CheckConstraint("quantity >= 0", name="ck_afe_service_charges_qty"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["line_id"], ["afe_service_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_afe_service_charges_organization_id", "afe_service_charges", ["organization_id"])
    op.create_index("ix_afe_service_charges_line_id", "afe_service_charges", ["line_id"])

    op.create_table(
        "afe_service_section_rates",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("line_id", sa.String(length=36), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=False),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        *_child_timestamps(),
        sa.CheckConstraint("amount >= 0", name="ck_afe_service_section_rates_amount"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["line_id"], ["afe_service_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_afe_service_section_rates_organization_id", "afe_service_section_rates", ["organization_id"])
    op.create_index("ix_afe_service_section_rates_line_id", "afe_service_section_rates", ["line_id"])
    op.create_index("ix_afe_service_section_rates_hole_section_id", "afe_service_section_rates", ["hole_section_id"])
    op.create_index("ix_afe_service_section_rates_phase_id", "afe_service_section_rates", ["phase_id"])

    op.create_table(
        "afe_consumable_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("afe_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=False),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("drill_bit_id", sa.String(length=36), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 3), server_default="1", nullable=False),
        sa.Column("captured_rate", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("override_rate", sa.Numeric(18, 4), nullable=True),
        sa.Column("estimated_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default="", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        *_child_timestamps(),
        sa.CheckConstraint(
            "category IN ('Mud Chemicals', 'Cement Additives', 'Fuel', 'Drill Bits')",
            name="ck_afe_consumable_lines_category",
        ),
        sa.CheckConstraint(
            "(category = 'Drill Bits' AND drill_bit_id IS NOT NULL AND estimated_amount IS NULL) OR "
            "(category <> 'Drill Bits' AND drill_bit_id IS NULL AND estimated_amount IS NOT NULL)",
            name="ck_afe_consumable_lines_kind",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_afe_consumable_lines_qty"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["afe_id"], ["afes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["drill_bit_id"], ["drill_bits.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_afe_consumable_lines_organization_id", "afe_consumable_lines", ["organization_id"])
    op.create_index("ix_afe_consumable_lines_afe", "afe_consumable_lines", ["afe_id"])
    op.create_index("ix_afe_consumable_lines_hole_section_id", "afe_consumable_lines", ["hole_section_id"])
    op.create_index("ix_afe_consumable_lines_phase_id", "afe_consumable_lines", ["phase_id"])
    op.create_index("ix_afe_consumable_lines_drill_bit_id", "afe_consumable_lines", ["drill_bit_id"])

    op.create_table(
        "afe_tangible_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        _org_column(),
        sa.Column("afe_id", sa.String(length=36), nullable=False),
        sa.Column("tangible_id", sa.String(length=36), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), server_default="1", nullable=False),
        sa.Column("captured_rate", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("override_rate", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default="", nullable=False),
        sa.Column("uom", sa.String(length=50), server_default="", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        *_child_timestamps(),
        sa.CheckConstraint("quantity >= 0", name="ck_afe_tangible_lines_qty"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["afe_id"], ["afes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tangible_id"], ["tangibles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_afe_tangible_lines_organization_id", "afe_tangible_lines", ["organization_id"])
    op.create_index("ix_afe_tangible_lines_afe", "afe_tangible_lines", ["afe_id"])
    op.create_index("ix_afe_tangible_lines_tangible_id", "afe_tangible_lines", ["tangible_id"])

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
        bind.execute(sa.select(permissions.c.id).where(permissions.c.key.in_(tuple(AFE_CAPABILITIES)))).scalars()
    )
    if permission_ids:
        bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
        bind.execute(permissions.delete().where(permissions.c.id.in_(permission_ids)))

    op.drop_table("afe_tangible_lines")
    op.drop_table("afe_consumable_lines")
    op.drop_table("afe_service_section_rates")
    op.drop_table("afe_service_charges")
    op.drop_table("afe_service_rates")
    op.drop_table("afe_service_lines")
    op.drop_table("afes")
