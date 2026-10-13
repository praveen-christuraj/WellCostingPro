"""Shared dependency checks for destructive actions.

Soft deletion intentionally keeps referenced master data available to historical
records. Permanent deletion is stricter: scan RESTRICT/NO ACTION foreign keys
before touching the database, so users get an actionable 409 instead of a generic
integrity error. Costing sets deliberately keep display snapshots for purged
items, so their polymorphic references do not block permanent deletion.
"""

from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import Base


REFERENCE_LABELS: dict[str, str] = {
    "afe_service_lines": "AFE service line(s)",
    "afe_service_rates": "AFE day-rate row(s)",
    "afe_service_charges": "AFE service charge row(s)",
    "afe_service_section_rates": "AFE per-section rate row(s)",
    "afe_consumable_lines": "AFE consumable line(s)",
    "afe_tangible_lines": "AFE tangible line(s)",
    "well_sections": "well configuration section(s)",
    "well_phases": "well configuration phase(s)",
    "well_sub_activities": "well sub activity record(s)",
    "daily_cost_service_lines": "daily-cost service line(s)",
    "daily_cost_consumable_lines": "daily-cost consumable line(s)",
    "daily_cost_tangible_lines": "daily-cost tangible line(s)",
    "daily_cost_other_expense_lines": "daily-cost expense line(s)",
    "daily_cost_baseline_service_rates": "locked daily-cost service-rate snapshot(s)",
    "daily_cost_baseline_sections": "locked daily-cost section snapshot(s)",
    "daily_cost_baseline_phases": "locked daily-cost phase snapshot(s)",
    "daily_cost_baseline_budget_lines": "locked AFE budget snapshot(s)",
    "daily_cost_catalogue_rate_snapshots": "locked catalogue-rate snapshot(s)",
    "daily_cost_baselines": "daily-cost baseline(s)",
    "daily_cost_well_rate_baselines": "daily-cost rate baseline(s)",
    "po_so_orders": "PO/SO order(s)",
    "services": "service record(s)",
    "vendors": "vendor record(s)",
    "tangibles": "tangible record(s)",
    "drill_bits": "drill-bit record(s)",
    "mud_chemicals": "mud-chemical record(s)",
    "cement_additives": "cement-additive record(s)",
    "fuel_types": "fuel-type record(s)",
    "catalogue_options": "catalogue dropdown record(s)",
    "currencies": "currency record(s)",
    "phases": "phase record(s)",
    "hole_sections": "hole-section record(s)",
    "activities": "activity record(s)",
}

def _label(table_name: str) -> str:
    return REFERENCE_LABELS.get(table_name, f"{table_name.replace('_', ' ')} row(s)")


def dependency_counts(db: Session, record: Any, organization_id: str) -> dict[str, int]:
    """Return counts of retained rows that would prevent deleting ``record``.

    Database CASCADE and SET NULL relations are excluded because those lifecycle
    effects are explicit in the schema. A table with multiple FKs to the same
    target is counted once per row, not once per column.
    """
    target_table = record.__table__
    references: dict[Any, list[tuple[Any, Any]]] = defaultdict(list)
    for table in Base.metadata.tables.values():
        if table is target_table:
            continue
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                try:
                    target_column = foreign_key.column
                except Exception:  # An unrelated unresolved optional FK should not block this check.
                    continue
                if target_column.table is not target_table:
                    continue
                on_delete = (foreign_key.ondelete or "").upper()
                if on_delete in {"CASCADE", "SET NULL"}:
                    continue
                references[table].append((column, getattr(record, target_column.name)))

    result: dict[str, int] = {}
    for table, columns in references.items():
        predicates = [column == value for column, value in columns]
        conditions = [or_(*predicates)]
        organization_column = table.c.get("organization_id")
        if organization_column is not None:
            conditions.append(organization_column == organization_id)
        count = int(db.scalar(select(func.count()).select_from(table).where(*conditions)) or 0)
        if count:
            result[_label(table.name)] = result.get(_label(table.name), 0) + count

    return result


def assert_no_dependencies(db: Session, record: Any, organization_id: str, *, entity_label: str) -> None:
    """Raise an actionable conflict when hard deletion would break references."""
    dependencies = dependency_counts(db, record, organization_id)
    if not dependencies:
        return
    summary = ", ".join(f"{count} {label}" for label, count in dependencies.items())
    next_step = (
        "Permanently delete the linked records first where allowed. Immutable AFE or daily-cost baselines "
        "require the referenced master data to remain in Deleted Entries."
    )
    raise HTTPException(
        status_code=409,
        detail=f"Cannot permanently delete {entity_label}: it is still referenced by {summary}. {next_step}",
    )
