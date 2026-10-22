"""Add the LIH Cost Register.

Revision ID: b8e3f1c72d90
Revises: b4d8e2c91a70
Create Date: 2026-10-22

Lost In Hole cost is entered manually, item by item, under a rig / well / date
(and the AFE it is deducted from). Every item is a column-wise row: equipment
dimensions, serial number, connection, units, UOM, unit cost, the server
computed total and remarks. A day keeps the summed total and line count so the
cost analysis and printed reports can deduct LIH from the AFE total explicitly.
No JSON payload is stored.
"""
import sqlalchemy as sa
from alembic import op


revision = "b8e3f1c72d90"
down_revision = "b4d8e2c91a70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lih_cost_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=False),
        sa.Column("rig_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("rig_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("well_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("well_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("afe_id", sa.String(length=36), nullable=True),
        sa.Column("afe_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("afe_name_snapshot", sa.String(length=200), server_default="", nullable=False),
        sa.Column("cost_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=10), server_default="", nullable=False),
        sa.Column("remarks", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("line_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_cost >= 0", name="ck_lih_cost_entries_total"),
        sa.CheckConstraint("line_count >= 0", name="ck_lih_cost_entries_line_count"),
        sa.ForeignKeyConstraint(["afe_id"], ["afes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "well_id", "cost_date", name="uq_lih_cost_entries_org_well_date"),
    )
    for column in ("organization_id", "rig_id", "well_id", "afe_id", "cost_date"):
        op.create_index(f"ix_lih_cost_entries_{column}", "lih_cost_entries", [column], unique=False)
    op.create_index(
        "ix_lih_cost_entries_org_rig", "lih_cost_entries", ["organization_id", "rig_id"], unique=False
    )
    op.create_index(
        "ix_lih_cost_entries_org_afe_date", "lih_cost_entries", ["organization_id", "afe_id", "cost_date"],
        unique=False,
    )
    op.create_index(
        "ix_lih_cost_entries_org_deleted_date",
        "lih_cost_entries", ["organization_id", "is_deleted", "cost_date"], unique=False,
    )

    op.create_table(
        "lih_cost_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("item_description", sa.String(length=300), nullable=False),
        sa.Column("od_size", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("id_size", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("fish_neck_od", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("fish_neck_length", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("serial_number", sa.String(length=100), server_default="", nullable=False),
        sa.Column("connection", sa.String(length=100), server_default="", nullable=False),
        sa.Column("length", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("no_of_units", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False),
        sa.Column("unit", sa.String(length=50), server_default="", nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=28, scale=10), server_default="0", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("LENGTH(TRIM(item_description)) > 0", name="ck_lih_cost_lines_description"),
        sa.CheckConstraint("no_of_units >= 0", name="ck_lih_cost_lines_units"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_lih_cost_lines_unit_cost"),
        sa.CheckConstraint("total_cost >= 0", name="ck_lih_cost_lines_total"),
        sa.CheckConstraint("od_size IS NULL OR od_size >= 0", name="ck_lih_cost_lines_od"),
        sa.CheckConstraint("id_size IS NULL OR id_size >= 0", name="ck_lih_cost_lines_id"),
        sa.CheckConstraint("fish_neck_od IS NULL OR fish_neck_od >= 0", name="ck_lih_cost_lines_fish_neck_od"),
        sa.CheckConstraint(
            "fish_neck_length IS NULL OR fish_neck_length >= 0", name="ck_lih_cost_lines_fish_neck_length"
        ),
        sa.CheckConstraint("length IS NULL OR length >= 0", name="ck_lih_cost_lines_length"),
        sa.ForeignKeyConstraint(["entry_id"], ["lih_cost_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lih_cost_lines_organization_id", "lih_cost_lines", ["organization_id"], unique=False)
    op.create_index("ix_lih_cost_lines_entry_id", "lih_cost_lines", ["entry_id"], unique=False)
    op.create_index("ix_lih_cost_lines_entry_order", "lih_cost_lines", ["entry_id", "sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_lih_cost_lines_entry_order", table_name="lih_cost_lines")
    op.drop_index("ix_lih_cost_lines_entry_id", table_name="lih_cost_lines")
    op.drop_index("ix_lih_cost_lines_organization_id", table_name="lih_cost_lines")
    op.drop_table("lih_cost_lines")
    for index in (
        "ix_lih_cost_entries_org_deleted_date",
        "ix_lih_cost_entries_org_afe_date",
        "ix_lih_cost_entries_org_rig",
        "ix_lih_cost_entries_cost_date",
        "ix_lih_cost_entries_afe_id",
        "ix_lih_cost_entries_well_id",
        "ix_lih_cost_entries_rig_id",
        "ix_lih_cost_entries_organization_id",
    ):
        op.drop_index(index, table_name="lih_cost_entries")
    op.drop_table("lih_cost_entries")
