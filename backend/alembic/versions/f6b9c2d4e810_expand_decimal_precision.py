"""Expand decimal entry and calculation precision to ten places.

Revision ID: f6b9c2d4e810
Revises: d4e8b2c19a73
Create Date: 2026-10-20 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f6b9c2d4e810"
down_revision: str | None = "d4e8b2c19a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The previous type is retained per column so downgrade restores the exact
# pre-change schema. Upgrade uses Numeric(28, 10) everywhere to retain ten
# fractional places with ample headroom; API range checks remain authoritative.
DECIMAL_COLUMNS: dict[str, dict[str, tuple[int, int]]] = {
    "afe_consumable_lines": {"quantity": (18, 3), "captured_rate": (18, 4), "override_rate": (18, 4), "estimated_amount": (18, 2)},
    "afe_exchange_rates": {"rate": (18, 6)},
    "afe_service_charges": {"quantity": (12, 4)},
    "afe_service_lines": {"service_amount": (18, 4)},
    "afe_service_rates": {"unit_rate": (18, 4)},
    "afe_service_section_rates": {"amount": (18, 4)},
    "afe_sow_adjustments": {
        "original_services_total": (18, 2), "original_consumables_total": (18, 2),
        "original_tangibles_total": (18, 2), "original_total": (18, 2),
        "adjusted_services_total": (18, 2), "adjusted_consumables_total": (18, 2),
        "adjusted_tangibles_total": (18, 2), "adjusted_total": (18, 2),
    },
    "afe_tangible_lines": {"quantity": (18, 3), "captured_rate": (18, 4), "override_rate": (18, 4)},
    "cement_additive_rate_revisions": {
        "unit_rate": (18, 4), "previous_unit_rate": (18, 4), "cost_uplift": (9, 4),
        "final_cost": (18, 4), "previous_final_cost": (18, 4),
    },
    "cement_additives": {"unit_rate": (18, 4), "cost_uplift": (9, 4), "final_cost": (18, 4)},
    "daily_cost_baseline_budget_lines": {
        "quantity": (18, 4), "unit_rate": (18, 4), "native_amount": (18, 2),
        "exchange_rate": (18, 6), "planned_amount": (18, 2),
    },
    "daily_cost_baseline_exchange_rates": {"rate": (18, 6)},
    "daily_cost_baseline_phases": {"days": (12, 2)},
    "daily_cost_baseline_sections": {"from_depth": (18, 2), "to_depth": (18, 2), "total_days": (12, 2)},
    "daily_cost_baseline_service_rates": {"unit_rate": (18, 4)},
    "daily_cost_baselines": {
        "services_total": (18, 2), "consumables_total": (18, 2),
        "tangibles_total": (18, 2), "total_amount": (18, 2),
    },
    "daily_cost_catalogue_rate_snapshots": {"unit_rate": (18, 4)},
    "daily_cost_entries": {
        "services_total": (18, 2), "consumables_total": (18, 2), "tangibles_total": (18, 2),
        "other_expenses_total": (18, 2), "total_cost": (18, 2), "upa_total": (18, 2),
        "npt_total": (18, 2), "usd_exchange_rate": (18, 6), "services_total_usd": (18, 2),
        "consumables_total_usd": (18, 2), "tangibles_total_usd": (18, 2),
        "other_expenses_total_usd": (18, 2), "total_cost_usd": (18, 2),
        "upa_total_usd": (18, 2), "npt_total_usd": (18, 2),
    },
    "drill_bit_rate_revisions": {
        "unit_rate": (18, 4), "previous_unit_rate": (18, 4), "cost_uplift": (9, 4),
        "final_cost": (18, 4), "previous_final_cost": (18, 4),
    },
    "drill_bits": {"unit_rate": (18, 4), "cost_uplift": (9, 4), "final_cost": (18, 4)},
    "fuel_price_revisions": {
        "unit_rate": (18, 4), "previous_unit_rate": (18, 4), "cost_uplift": (9, 4),
        "final_cost": (18, 4), "previous_final_cost": (18, 4),
    },
    "fuel_types": {"unit_rate": (18, 4), "cost_uplift": (9, 4), "final_cost": (18, 4)},
    "mud_chemical_rate_revisions": {
        "unit_rate": (18, 4), "previous_unit_rate": (18, 4), "cost_uplift": (9, 4),
        "final_cost": (18, 4), "previous_final_cost": (18, 4),
    },
    "mud_chemicals": {"unit_rate": (18, 4), "cost_uplift": (9, 4), "final_cost": (18, 4)},
    "mud_cost_entries": {"section_from_depth": (18, 2), "section_to_depth": (18, 2)},
    "mud_cost_entry_lines": {"amount": (18, 3)},
    "tangible_rate_revisions": {
        "unit_rate": (18, 4), "previous_unit_rate": (18, 4), "cost_uplift": (9, 4),
        "final_cost": (18, 4), "previous_final_cost": (18, 4),
    },
    "tangibles": {"unit_rate": (18, 4), "cost_uplift": (9, 4), "final_cost": (18, 4)},
    "well_phases": {"days": (12, 2)},
    "well_plan_adjustments": {"planned_days_before": (12, 2), "planned_days_after": (12, 2)},
    "well_sections": {"from_depth": (18, 2), "to_depth": (18, 2)},
}

DAILY_LINE_TABLES = (
    "daily_cost_service_lines", "daily_cost_consumable_lines",
    "daily_cost_tangible_lines", "daily_cost_other_expense_lines",
)
DAILY_LINE_COLUMNS = {
    "quantity": (18, 4), "captured_rate": (18, 4), "override_rate": (18, 4),
    "exchange_rate": (18, 6), "amount": (18, 2), "standard_amount": (18, 2),
    "usd_exchange_rate": (18, 6), "usd_amount": (18, 2),
    "actual_depth": (18, 2), "actual_depth_input": (18, 2),
}
for _table in DAILY_LINE_TABLES:
    DECIMAL_COLUMNS[_table] = DAILY_LINE_COLUMNS


def _alter_columns(upgrade_precision: bool) -> None:
    for table_name, columns in DECIMAL_COLUMNS.items():
        with op.batch_alter_table(table_name) as batch:
            for column_name, (old_precision, old_scale) in columns.items():
                old_type = sa.Numeric(old_precision, old_scale)
                batch.alter_column(
                    column_name,
                    existing_type=old_type if upgrade_precision else sa.Numeric(28, 10),
                    type_=sa.Numeric(28, 10) if upgrade_precision else old_type,
                )


def upgrade() -> None:
    _alter_columns(True)


def downgrade() -> None:
    _alter_columns(False)

