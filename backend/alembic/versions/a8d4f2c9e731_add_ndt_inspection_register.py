"""Add the manual NDT Inspection register.

Revision ID: a8d4f2c9e731
Revises: c7a1d9e4b205
"""
from alembic import op
import sqlalchemy as sa

revision = "a8d4f2c9e731"
down_revision = "c7a1d9e4b205"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ndt_inspections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rig_id", sa.String(36), sa.ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rig_code_snapshot", sa.String(50), nullable=False),
        sa.Column("rig_name_snapshot", sa.String(200), nullable=False),
        sa.Column("well_id", sa.String(36), sa.ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("well_code_snapshot", sa.String(50), nullable=False),
        sa.Column("well_name_snapshot", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("quantity_received", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("quantity_consumed", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("quantity_backloaded_good", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("quantity_backloaded_bad", sa.Numeric(28, 10), nullable=False, server_default="0"),
        sa.Column("remarks", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('drilling', 'completion')", name="ck_ndt_inspections_scope"),
        sa.CheckConstraint("LENGTH(TRIM(description)) > 0", name="ck_ndt_inspections_description"),
        sa.CheckConstraint("quantity_received >= 0", name="ck_ndt_inspections_received"),
        sa.CheckConstraint("quantity_consumed >= 0", name="ck_ndt_inspections_consumed"),
        sa.CheckConstraint("quantity_backloaded_good >= 0", name="ck_ndt_inspections_backloaded_good"),
        sa.CheckConstraint("quantity_backloaded_bad >= 0", name="ck_ndt_inspections_backloaded_bad"),
    )
    op.create_index("ix_ndt_inspections_organization_id", "ndt_inspections", ["organization_id"])
    op.create_index("ix_ndt_inspections_rig_id", "ndt_inspections", ["rig_id"])
    op.create_index("ix_ndt_inspections_well_id", "ndt_inspections", ["well_id"])
    op.create_index("ix_ndt_inspections_org_scope", "ndt_inspections", ["organization_id", "rig_id", "well_id", "scope"])
    op.create_index("ix_ndt_inspections_org_deleted_created", "ndt_inspections", ["organization_id", "is_deleted", "created_at"])


def downgrade():
    op.drop_table("ndt_inspections")
