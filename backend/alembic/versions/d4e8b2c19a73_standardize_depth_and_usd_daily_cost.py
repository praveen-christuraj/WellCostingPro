"""Standardize daily cost actual depth in metres and USD conversion tracking.

Revision ID: d4e8b2c19a73
Revises: f3c1a8d72b60
Create Date: 2026-10-20 12:00:00.000000

Adds column-wise actual depth fields (``actual_depth`` standardized in ``m``,
``actual_depth_input``, ``actual_depth_unit``, and ``depth_entry_seq``) plus
column-wise USD conversion tracking (``usd_exchange_rate`` and ``usd_amount``)
to all four ``DailyCostLine`` concrete tables, adds USD summary totals to
``daily_cost_entries``, converts historical ``ft`` baseline section depths to
``m`` using ``3.281`` (``feet / 3.281``), and ensures ``USD`` is present as the
workspace default currency where missing.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision: str = "d4e8b2c19a73"
down_revision: Union[str, None] = "f3c1a8d72b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LINE_TABLES = (
    "daily_cost_service_lines",
    "daily_cost_consumable_lines",
    "daily_cost_tangible_lines",
    "daily_cost_other_expense_lines",
)

ENTRY_USD_COLUMNS = (
    "services_total_usd",
    "consumables_total_usd",
    "tangibles_total_usd",
    "other_expenses_total_usd",
    "total_cost_usd",
    "upa_total_usd",
    "npt_total_usd",
)

FEET_PER_METER = Decimal("3.281")


def upgrade() -> None:
    with op.batch_alter_table("daily_cost_entries") as batch:
        batch.add_column(sa.Column("usd_exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"))
        for col in ENTRY_USD_COLUMNS:
            batch.add_column(sa.Column(col, sa.Numeric(18, 2), nullable=False, server_default="0"))

    for table in LINE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("usd_exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"))
            batch.add_column(sa.Column("usd_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
            batch.add_column(sa.Column("actual_depth", sa.Numeric(18, 2), nullable=True))
            batch.add_column(sa.Column("actual_depth_input", sa.Numeric(18, 2), nullable=True))
            batch.add_column(sa.Column("actual_depth_unit", sa.String(5), nullable=False, server_default="m"))
            batch.add_column(sa.Column("depth_entry_seq", sa.Integer(), nullable=False, server_default="0"))

    op.execute(
        "UPDATE daily_cost_entries "
        "SET services_total_usd = services_total, "
        "    consumables_total_usd = consumables_total, "
        "    tangibles_total_usd = tangibles_total, "
        "    other_expenses_total_usd = other_expenses_total, "
        "    total_cost_usd = total_cost, "
        "    upa_total_usd = upa_total, "
        "    npt_total_usd = npt_total "
        "WHERE UPPER(standard_currency) = 'USD'"
    )

    for table in LINE_TABLES:
        op.execute(f"UPDATE {table} SET depth_entry_seq = sort_order + 1")
        op.execute(
            f"UPDATE {table} SET usd_amount = amount, usd_exchange_rate = 1 "
            "WHERE UPPER(currency) = 'USD'"
        )
        op.execute(
            f"UPDATE {table} "
            "SET usd_amount = standard_amount, usd_exchange_rate = exchange_rate "
            "WHERE UPPER(currency) != 'USD' AND entry_id IN ("
            "  SELECT id FROM daily_cost_entries WHERE UPPER(standard_currency) = 'USD'"
            ")"
        )

    connection = op.get_bind()

    # Standardize historical baseline section snapshots from ft to m (feet / 3.281).
    ft_sections = connection.execute(
        sa.text(
            "SELECT s.id, s.from_depth, s.to_depth "
            "FROM daily_cost_baseline_sections s "
            "JOIN daily_cost_baselines b ON b.id = s.baseline_id "
            "JOIN afes a ON a.id = b.afe_id "
            "JOIN wells w ON w.id = b.well_id "
            "WHERE (a.configuration_scope = 'completion' AND LOWER(w.completion_depth_unit) = 'ft') "
            "   OR (a.configuration_scope != 'completion' AND LOWER(w.depth_unit) = 'ft')"
        )
    ).fetchall()
    for section_id, from_depth, to_depth in ft_sections:
        from_m = (Decimal(str(from_depth)) / FEET_PER_METER).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        to_m = (Decimal(str(to_depth)) / FEET_PER_METER).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        connection.execute(
            sa.text(
                "UPDATE daily_cost_baseline_sections "
                "SET from_depth = :from_m, to_depth = :to_m WHERE id = :id"
            ),
            {"from_m": from_m, "to_m": to_m, "id": section_id},
        )

    # Ensure every existing workspace has USD seeded as default currency when missing.
    org_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM organizations")).fetchall()]
    for org_id in org_ids:
        has_default = connection.execute(
            sa.text(
                "SELECT id FROM currencies "
                "WHERE organization_id = :org_id AND is_deleted = 0 AND is_default = 1 LIMIT 1"
                if connection.dialect.name == "sqlite"
                else "SELECT id FROM currencies "
                "WHERE organization_id = :org_id AND is_deleted IS FALSE AND is_default IS TRUE LIMIT 1"
            ),
            {"org_id": org_id},
        ).fetchone()
        usd_row = connection.execute(
            sa.text(
                "SELECT id, is_deleted FROM currencies "
                "WHERE organization_id = :org_id AND UPPER(currency_code) = 'USD' LIMIT 1"
            ),
            {"org_id": org_id},
        ).fetchone()
        if usd_row is None:
            connection.execute(
                sa.text(
                    "INSERT INTO currencies "
                    "(id, organization_id, currency_code, currency_name, currency_symbol, description, "
                    " is_default, is_deleted, created_at, updated_at) "
                    "VALUES (:id, :org_id, 'USD', 'US Dollar', '$', 'Standard US Dollar currency', "
                    " :is_default, :is_deleted, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": str(uuid4()),
                    "org_id": org_id,
                    "is_default": has_default is None,
                    "is_deleted": False,
                },
            )
        elif has_default is None and not bool(usd_row[1]):
            connection.execute(
                sa.text("UPDATE currencies SET is_default = :flag WHERE id = :id"),
                {"flag": True, "id": usd_row[0]},
            )


def downgrade() -> None:
    for table in LINE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("depth_entry_seq")
            batch.drop_column("actual_depth_unit")
            batch.drop_column("actual_depth_input")
            batch.drop_column("actual_depth")
            batch.drop_column("usd_amount")
            batch.drop_column("usd_exchange_rate")

    with op.batch_alter_table("daily_cost_entries") as batch:
        for col in reversed(ENTRY_USD_COLUMNS):
            batch.drop_column(col)
        batch.drop_column("usd_exchange_rate")
