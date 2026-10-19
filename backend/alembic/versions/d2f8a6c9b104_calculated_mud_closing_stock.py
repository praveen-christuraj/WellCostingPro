"""Calculate mud closing stock and make all line remarks optional.

Revision ID: d2f8a6c9b104
Revises: c1d4a7b8e2f9
Create Date: 2026-10-19

Historical actual-closing measurements are retained, but are not used in the
balance. Rebuild active opening stocks from the initial opening and movements,
scoped by workspace, rig, well and section. Missing days need no stored rows:
without movements their closing and opening stocks are identical.
"""
from decimal import Decimal

from alembic import op
import sqlalchemy as sa

revision = "d2f8a6c9b104"
down_revision = "c1d4a7b8e2f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mud_cost_entry_lines") as batch:
        batch.drop_constraint("ck_mud_cost_entry_lines_remarks", type_="check")
        batch.drop_constraint("ck_mud_cost_entry_lines_amount", type_="check")
        # Movements remain non-negative; an automatically derived deficit must
        # carry forward unchanged rather than being clamped to zero.
        batch.create_check_constraint(
            "ck_mud_cost_entry_lines_amount", "amount >= 0 OR line_code = 'opening_stock'"
        )

    connection = op.get_bind()
    metadata = sa.MetaData()
    entries = sa.Table("mud_cost_entries", metadata, autoload_with=connection)
    lines = sa.Table("mud_cost_entry_lines", metadata, autoload_with=connection)
    rows = connection.execute(
        sa.select(
            entries.c.organization_id, entries.c.rig_id, entries.c.well_id,
            entries.c.section_id, entries.c.id.label("entry_id"),
            lines.c.id.label("line_id"), lines.c.line_code, lines.c.category, lines.c.amount,
        ).join(lines, lines.c.entry_id == entries.c.id)
        .where(entries.c.is_deleted.is_(False))
        .order_by(entries.c.organization_id, entries.c.rig_id, entries.c.well_id,
                  entries.c.section_id, entries.c.entry_date, entries.c.id, lines.c.sort_order)
    ).mappings().all()
    grouped = {}
    for row in rows:
        key = (row["organization_id"], row["rig_id"], row["well_id"], row["section_id"])
        grouped.setdefault(key, {}).setdefault(row["entry_id"], []).append(row)
    for section in grouped.values():
        closing = None
        for entry_lines in section.values():
            opening = next((row for row in entry_lines if row["line_code"] == "opening_stock"), None)
            if opening is None:
                continue
            if closing is None:
                closing = Decimal(opening["amount"])
            else:
                connection.execute(lines.update().where(lines.c.id == opening["line_id"]).values(
                    amount=closing, remarks="",
                ))
            for row in entry_lines:
                if row["category"] in ("receipt", "additions"):
                    closing += Decimal(row["amount"])
                elif row["category"] in ("consumption_losses", "others"):
                    closing -= Decimal(row["amount"])


def downgrade() -> None:
    # Do not fabricate mandatory remarks or discard negative balances to make
    # old constraints fit. Operators must resolve such rows before downgrading.
    connection = op.get_bind()
    incompatible = connection.scalar(sa.text(
        "SELECT COUNT(*) FROM mud_cost_entry_lines "
        "WHERE amount < 0 OR (amount <> 0 AND LENGTH(TRIM(remarks)) < 3)"
    ))
    if incompatible:
        raise RuntimeError("Resolve negative stocks and missing remarks before downgrading Mud Cost Analysis.")
    with op.batch_alter_table("mud_cost_entry_lines") as batch:
        batch.drop_constraint("ck_mud_cost_entry_lines_amount", type_="check")
        batch.create_check_constraint("ck_mud_cost_entry_lines_amount", "amount >= 0")
        batch.create_check_constraint(
            "ck_mud_cost_entry_lines_remarks", "amount = 0 OR LENGTH(TRIM(remarks)) >= 3"
        )
