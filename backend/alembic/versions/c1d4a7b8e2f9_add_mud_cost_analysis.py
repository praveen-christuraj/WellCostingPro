"""Add tenant-scoped Mud Cost Analysis material-balance entries.

Revision ID: c1d4a7b8e2f9
Revises: a7e2c6b4d901
Create Date: 2026-10-18

The main entry and each named quantity/remark are stored in conventional typed
columns. There is no JSON payload. The section identifier is a historical
snapshot key because Rig & Well Management replaces configured section rows
when a draft is saved; Hole Section, Rig and Well identities remain protected
by restrictive foreign keys.
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d4a7b8e2f9"
down_revision = "a7e2c6b4d901"
branch_labels = None
depends_on = None

LINE_CODES = (
    "opening_stock", "extra_obm_received", "other_receipts", "drill_water", "base_oil",
    "crude_tdu_oil", "chemicals", "barite", "other_additions", "verti_g_mud_on_cuttings",
    "mud_cleaner", "centrifuge", "by_pass", "formation_seepage", "shakers", "evaporation",
    "pit_cleaning_dump", "trips", "left_in_hole", "consumption_losses_others",
    "offline_centrifuge_loss", "backloads", "obm_left_in_hole", "other_losses_others",
    "actual_closing_stock",
)
CATEGORIES = ("opening_stock", "receipt", "additions", "consumption_losses", "others", "closing_stock")


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "mud_cost_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rig_id", sa.String(length=36), nullable=False),
        sa.Column("rig_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("rig_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("well_id", sa.String(length=36), nullable=False),
        sa.Column("well_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("well_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=False),
        sa.Column("section_scope", sa.String(length=20), nullable=False),
        sa.Column("section_code_snapshot", sa.String(length=50), nullable=False),
        sa.Column("section_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("section_from_depth", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("section_to_depth", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("section_scope IN ('drilling', 'completion')", name="ck_mud_cost_entries_section_scope"),
        sa.CheckConstraint(
            "section_from_depth >= 0 AND section_to_depth >= section_from_depth",
            name="ck_mud_cost_entries_section_depth",
        ),
        sa.ForeignKeyConstraint(["hole_section_id"], ["hole_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rig_id"], ["rigs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["well_id"], ["wells.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "well_id", "entry_date", name="uq_mud_cost_entries_org_well_date"),
    )
    for column in ("organization_id", "rig_id", "well_id", "section_id", "hole_section_id", "entry_date"):
        op.create_index(f"ix_mud_cost_entries_{column}", "mud_cost_entries", [column], unique=False)
    op.create_index(
        "ix_mud_cost_entries_org_rig_date", "mud_cost_entries",
        ["organization_id", "rig_id", "entry_date"], unique=False,
    )
    op.create_index(
        "ix_mud_cost_entries_org_section_date", "mud_cost_entries",
        ["organization_id", "section_id", "entry_date"], unique=False,
    )
    op.create_index(
        "ix_mud_cost_entries_org_deleted_date", "mud_cost_entries",
        ["organization_id", "is_deleted", "entry_date"], unique=False,
    )

    op.create_table(
        "mud_cost_entry_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("line_code", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("line_label", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=3), server_default="0", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_check("line_code", LINE_CODES), name="ck_mud_cost_entry_lines_code"),
        sa.CheckConstraint(_check("category", CATEGORIES), name="ck_mud_cost_entry_lines_category"),
        sa.CheckConstraint("amount >= 0", name="ck_mud_cost_entry_lines_amount"),
        sa.CheckConstraint(
            "amount = 0 OR LENGTH(TRIM(remarks)) >= 3",
            name="ck_mud_cost_entry_lines_remarks",
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["mud_cost_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "line_code", name="uq_mud_cost_entry_lines_entry_code"),
    )
    for column in ("organization_id", "entry_id"):
        op.create_index(f"ix_mud_cost_entry_lines_{column}", "mud_cost_entry_lines", [column], unique=False)
    op.create_index(
        "ix_mud_cost_entry_line_entry_order", "mud_cost_entry_lines", ["entry_id", "sort_order"], unique=False,
    )
    op.create_index(
        "ix_mud_cost_entry_line_org_category", "mud_cost_entry_lines", ["organization_id", "category"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_mud_cost_entry_line_org_category", table_name="mud_cost_entry_lines")
    op.drop_index("ix_mud_cost_entry_line_entry_order", table_name="mud_cost_entry_lines")
    op.drop_index("ix_mud_cost_entry_lines_entry_id", table_name="mud_cost_entry_lines")
    op.drop_index("ix_mud_cost_entry_lines_organization_id", table_name="mud_cost_entry_lines")
    op.drop_table("mud_cost_entry_lines")
    op.drop_index("ix_mud_cost_entries_org_deleted_date", table_name="mud_cost_entries")
    op.drop_index("ix_mud_cost_entries_org_section_date", table_name="mud_cost_entries")
    op.drop_index("ix_mud_cost_entries_org_rig_date", table_name="mud_cost_entries")
    for column in ("entry_date", "hole_section_id", "section_id", "well_id", "rig_id", "organization_id"):
        op.drop_index(f"ix_mud_cost_entries_{column}", table_name="mud_cost_entries")
    op.drop_table("mud_cost_entries")
