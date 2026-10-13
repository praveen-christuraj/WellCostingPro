"""Add other expenses (LIH / hole problems) to the daily cost sheet.

Revision ID: 7c1f4a8d92b6
Revises: 4a6d2e9c8b17
Create Date: 2026-10-13

Unexpected charges have no AFE allowance, so they live in their own column-wise
table instead of the Services, Consumables or Tangibles line tables. Each line
keeps the full operational scope of a daily cost line (rig-scoped well, activity,
sub activity, hole section, phase, responsible party, native and standard amounts)
and is deducted from the locked AFE total rather than reconciled to a budget line.
Remarks are mandatory, which is why the check constraint on the column is here.

``daily_cost_entries.other_expenses_total`` is a denormalised day total for the
new group; it is included in ``total_cost`` and recomputed on every save.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c1f4a8d92b6"
down_revision: Union[str, None] = "4a6d2e9c8b17"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

EXPENSE_TYPES = (
    "LIH", "HOLE_PROBLEM", "FISHING", "SIDE_TRACK", "EQUIPMENT_DAMAGE",
    "THIRD_PARTY_CLAIM", "PENALTY", "MISC",
)
TABLE = "daily_cost_other_expense_lines"


def _expense_type_check() -> str:
    return f"expense_type IN ({', '.join(repr(value) for value in EXPENSE_TYPES)})"


def upgrade() -> None:
    op.add_column(
        "daily_cost_entries",
        sa.Column("other_expenses_total", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
    )
    op.create_table(
        TABLE,
        sa.Column("expense_type", sa.String(length=30), nullable=False),
        sa.Column("expense_type_label", sa.String(length=120), nullable=False),
        sa.Column("expense_description", sa.String(length=300), server_default="", nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("activity_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("activity_name_snapshot", sa.String(length=150), server_default="", nullable=False),
        sa.Column("section_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("section_name_snapshot", sa.String(length=150), server_default="", nullable=False),
        sa.Column("phase_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("phase_name_snapshot", sa.String(length=150), server_default="", nullable=False),
        sa.Column("sub_activity_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("sub_activity_name_snapshot", sa.String(length=150), server_default="", nullable=False),
        sa.Column("sub_activity_party_snapshot", sa.String(length=200), server_default="", nullable=False),
        sa.Column("hole_section_id", sa.String(length=36), nullable=True),
        sa.Column("phase_id", sa.String(length=36), nullable=True),
        sa.Column("sub_activity_id", sa.String(length=36), nullable=True),
        sa.Column("classification", sa.String(length=10), server_default="Planned", nullable=False),
        sa.Column("vendor_id", sa.String(length=36), nullable=True),
        sa.Column("vendor_code_snapshot", sa.String(length=50), server_default="", nullable=False),
        sa.Column("vendor_name_snapshot", sa.String(length=200), server_default="", nullable=False),
        sa.Column("party_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), server_default="0", nullable=False),
        sa.Column("quantity_unit", sa.String(length=20), server_default="unit", nullable=False),
        sa.Column("captured_rate", sa.Numeric(precision=18, scale=4), server_default="0", nullable=False),
        sa.Column("override_rate", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=10), server_default="", nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=18, scale=6), server_default="1", nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("standard_amount", sa.Numeric(precision=18, scale=2), server_default="0", nullable=False),
        sa.Column("rate_source", sa.String(length=30), server_default="", nullable=False),
        sa.Column("rate_revision_number", sa.Integer(), nullable=True),
        sa.Column("rate_effective_date", sa.Date(), nullable=True),
        sa.Column("baseline_budget_line_id", sa.String(length=36), nullable=True),
        sa.Column("budget_key", sa.String(length=100), server_default="", nullable=False),
        sa.Column("override_reason", sa.String(length=500), server_default="", nullable=False),
        sa.Column("remarks", sa.String(length=500), server_default="", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("classification IN ('Planned', 'UPA', 'NPT')", name="ck_daily_cost_other_classification"),
        sa.CheckConstraint(_expense_type_check(), name="ck_daily_cost_other_expense_type"),
        sa.CheckConstraint("quantity >= 0", name="ck_daily_cost_other_quantity"),
        sa.CheckConstraint("LENGTH(TRIM(remarks)) > 0", name="ck_daily_cost_other_remarks"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], name=f"fk_{TABLE}_activity_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["baseline_budget_line_id"], ["daily_cost_baseline_budget_lines.id"],
            name=f"fk_{TABLE}_baseline_budget_line_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["daily_cost_entries.id"], name=f"fk_{TABLE}_entry_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["hole_section_id"], ["hole_sections.id"], name=f"fk_{TABLE}_hole_section_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=f"fk_{TABLE}_organization_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["phase_id"], ["phases.id"], name=f"fk_{TABLE}_phase_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["sub_activity_id"], ["well_sub_activities.id"], name=f"fk_{TABLE}_sub_activity_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], name=f"fk_{TABLE}_vendor_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TABLE}"),
    )
    op.create_index("ix_daily_cost_other_line_entry_order", TABLE, ["entry_id", "sort_order"], unique=False)
    op.create_index("ix_daily_cost_other_line_org_type", TABLE, ["organization_id", "expense_type"], unique=False)
    for column in (
        "activity_id", "baseline_budget_line_id", "budget_key", "entry_id", "hole_section_id",
        "organization_id", "phase_id", "sub_activity_id", "vendor_id",
    ):
        op.create_index(op.f(f"ix_{TABLE}_{column}"), TABLE, [column], unique=False)


def downgrade() -> None:
    op.drop_index(op.f(f"ix_{TABLE}_vendor_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_sub_activity_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_organization_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_hole_section_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_entry_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_budget_key"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_baseline_budget_line_id"), table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_activity_id"), table_name=TABLE)
    op.drop_index("ix_daily_cost_other_line_org_type", table_name=TABLE)
    op.drop_index("ix_daily_cost_other_line_entry_order", table_name=TABLE)
    op.drop_table(TABLE)
    with op.batch_alter_table("daily_cost_entries") as batch:
        batch.drop_column("other_expenses_total")
