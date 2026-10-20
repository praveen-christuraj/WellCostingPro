"""Add section-scoped mud type and Cost/BBL configuration.

Revision ID: c4a7e1b93d52
Revises: e9a4c7b15d38
Create Date: 2026-10-20

Every well section can be configured once with a mud system (WBM / OBM / SOBM /
OTHERS), an optional remark, and a Cost/BBL base rate. The row is keyed by the
stable hole-section identity plus configuration scope so a later well-plan edit
(which replaces ``well_sections`` rows) does not orphan the configuration.
Only OTHERS requires a remark. No JSON payload is persisted.
"""
from alembic import op
import sqlalchemy as sa


revision = "c4a7e1b93d52"
down_revision = "e9a4c7b15d38"
branch_labels = None
depends_on = None

MUD_TYPES = ("WBM", "OBM", "SOBM", "OTHERS")


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "mud_cost_section_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=False),
        sa.Column("section_scope", sa.String(length=20), nullable=False),
        sa.Column("section_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("section_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("mud_type", sa.String(length=10), nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("base_rate", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=10), server_default="", nullable=False),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_check("mud_type", MUD_TYPES), name="ck_mud_cost_section_settings_mud_type"),
        sa.CheckConstraint("base_rate >= 0", name="ck_mud_cost_section_settings_base_rate"),
        sa.CheckConstraint(
            "mud_type <> 'OTHERS' OR LENGTH(TRIM(remarks)) > 0",
            name="ck_mud_cost_section_settings_remarks",
        ),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "well_id", "section_scope", "hole_section_id",
            name="uq_mud_cost_section_settings_scope",
        ),
    )
    for column in ("organization_id", "rig_id", "well_id", "section_id", "hole_section_id"):
        op.create_index(
            f"ix_mud_cost_section_settings_{column}",
            "mud_cost_section_settings",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_mud_cost_section_settings_org_well",
        "mud_cost_section_settings",
        ["organization_id", "well_id"],
        unique=False,
    )
    op.create_index(
        "ix_mud_cost_section_settings_org_rig",
        "mud_cost_section_settings",
        ["organization_id", "rig_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_mud_cost_section_settings_org_rig", table_name="mud_cost_section_settings")
    op.drop_index("ix_mud_cost_section_settings_org_well", table_name="mud_cost_section_settings")
    for column in ("hole_section_id", "section_id", "well_id", "rig_id", "organization_id"):
        op.drop_index(f"ix_mud_cost_section_settings_{column}", table_name="mud_cost_section_settings")
    op.drop_table("mud_cost_section_settings")
