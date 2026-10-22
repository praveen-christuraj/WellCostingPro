"""Add LIH worksheet save support (revision and line source).

Revision ID: f1a7c3d95b28
Revises: b8e3f1c72d90
Create Date: 2026-10-22

The LIH register is now edited as a worksheet and saved in one atomic request.
Two columns support that without touching existing data:

* ``lih_cost_entries.revision`` — bumped on every worksheet save so a stale
  browser cannot overwrite items another user saved in the meantime,
* ``lih_cost_lines.source`` — how the row entered the register (manual,
  duplicate, import), kept as a plain column with a check constraint.

Batch mode is used so the same revision runs on SQLite (which cannot add a
constraint in place) and PostgreSQL. No JSON is introduced; every business
attribute stays its own typed column.
"""
import sqlalchemy as sa
from alembic import op


revision = "f1a7c3d95b28"
down_revision = "b8e3f1c72d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("lih_cost_entries") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), server_default="0", nullable=False))
        batch.create_check_constraint("ck_lih_cost_entries_revision", "revision >= 0")
    with op.batch_alter_table("lih_cost_lines") as batch:
        batch.add_column(
            sa.Column("source", sa.String(length=20), server_default="manual", nullable=False)
        )
        batch.create_check_constraint(
            "ck_lih_cost_lines_source", "source IN ('manual', 'duplicate', 'import')"
        )
    # Existing items keep sort_order; the composite index supports the
    # "previously used item" suggestions the worksheet offers while typing.
    op.create_index(
        "ix_lih_cost_lines_org_description",
        "lih_cost_lines",
        ["organization_id", "item_description"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_lih_cost_lines_org_description", table_name="lih_cost_lines")
    with op.batch_alter_table("lih_cost_lines") as batch:
        batch.drop_constraint("ck_lih_cost_lines_source", type_="check")
        batch.drop_column("source")
    with op.batch_alter_table("lih_cost_entries") as batch:
        batch.drop_constraint("ck_lih_cost_entries_revision", type_="check")
        batch.drop_column("revision")
