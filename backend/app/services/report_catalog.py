"""The live, tenant-safe catalogue the Report Builder designs against.

The catalogue is discovered from the real database (never a hand-written list),
reuses the Database Browser's tenancy resolution and secret-column filter, and
adds what a report designer needs: readable names, coarse value types, and one
declared foreign-key hop so a line table can show its parent's facts (for
example ``daily_cost_service_lines`` → ``daily_cost_entries.cost_date``).

Only catalogue-approved columns can ever appear in a report; validation re-runs
against the live catalogue on every save and every run, so a hand-crafted
definition cannot reach a password column or invent SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, Numeric, Table, Time, false, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.services.database_browser import browsable_tables, column_kind, module_group

# More than this many joins in one report is a design smell, not a requirement.
MAX_RELATIONS = 8
# Keeps the per-table catalogue payload readable in the builder.
MAX_RELATED_COLUMNS = 60
MAX_TABLES = 200

SPECIAL_WORDS = {
    "id": "ID", "usd": "USD", "afe": "AFE", "npt": "NPT", "upa": "UPA", "uom": "UOM",
    "lih": "LIH", "ndt": "NDT", "po": "PO", "so": "SO", "rig": "Rig", "well": "Well",
    "api": "API", "fx": "FX", "gsv": "GSV", "nsv": "NSV",
}


def humanize(name: str) -> str:
    """`daily_cost_total_usd` → `Daily Cost Total USD`."""
    if not name:
        return ""
    words = [word for word in re.split(r"[_\s]+", name) if word]
    return " ".join(SPECIAL_WORDS.get(word.lower(), word.capitalize()) for word in words)


def table_label(name: str) -> str:
    """`daily_cost_service_lines` → `Daily Cost Service Lines`."""
    return humanize(name)


def column_label(name: str, *, prefix: str = "") -> str:
    label = humanize(name)
    return f"{prefix} {label}".strip() if prefix else label


def value_type(column: Column) -> str:
    return column_kind(column)


@dataclass
class Relation:
    """One declared foreign key from the base table to a parent table."""

    key_column: str
    parent_name: str
    parent_label: str
    parent_table: Table
    parent_columns: dict[str, Column]
    parent_pk: str
    parent_scope: object

    def as_dict(self) -> dict:
        return {
            "key_column": self.key_column,
            "table": self.parent_name,
            "label": self.parent_label,
            "columns": [
                {
                    "column": name,
                    "label": column_label(name, prefix=self.parent_label + " ·"),
                    "data_type": value_type(column),
                }
                for name, column in self.parent_columns.items()
            ],
        }


@dataclass
class TableInfo:
    name: str
    label: str
    group: str
    table: Table
    scope: object
    scope_label: str
    columns: dict[str, Column]
    primary_key: list[str]
    relations: dict[str, Relation] = field(default_factory=dict)

    @property
    def date_columns(self) -> list[str]:
        return [name for name, column in self.columns.items() if value_type(column) == "date"]

    def summary(self) -> dict:
        return {
            "table": self.name,
            "label": self.label,
            "group": self.group,
            "scope": self.scope_label,
            "primary_key": self.primary_key,
            "column_count": len(self.columns),
            "date_columns": self.date_columns,
            "relation_count": len(self.relations),
            "has_created_at": "created_at" in self.columns,
            "has_updated_at": "updated_at" in self.columns,
        }

    def detail(self) -> dict:
        return {
            **self.summary(),
            "columns": [
                {"column": name, "label": column_label(name), "data_type": value_type(column)}
                for name, column in self.columns.items()
            ],
            "relations": [relation.as_dict() for relation in sorted(self.relations.values(), key=lambda item: item.key_column)],
        }


def _parent_key(table: Table) -> str | None:
    keys = [column.name for column in table.primary_key.columns]
    if len(keys) != 1:
        return None
    return keys[0]


def _relations_for(info: TableInfo, browsable: dict) -> dict[str, Relation]:
    """One hop out of the base table, using only declared single-column foreign keys."""
    relations: dict[str, Relation] = {}
    for constraint in info.table.foreign_key_constraints:
        if len(constraint.columns) != 1 or len(relations) >= MAX_RELATIONS:
            continue
        parent_column = list(constraint.columns)[0]
        reference = list(constraint.elements)[0].column
        parent_name = reference.table.name
        if parent_name == info.name or parent_name not in browsable:
            continue
        parent = browsable[parent_name]
        parent_pk = _parent_key(parent.table)
        if parent_pk is None or parent_column.name in relations:
            continue
        columns = {column.name: column for column in parent.visible_columns[:MAX_RELATED_COLUMNS]}
        relations[parent_column.name] = Relation(
            key_column=parent_column.name,
            parent_name=parent_name,
            parent_label=table_label(parent_name),
            parent_table=parent.table,
            parent_columns=columns,
            parent_pk=parent_pk,
            parent_scope=parent.scope,
        )
    return relations


def build_catalog(engine: Engine) -> dict[str, TableInfo]:
    """Every reportable table in this workspace, keyed by table name."""
    browsable = browsable_tables(engine)
    catalog: dict[str, TableInfo] = {}
    for name, browsable_table in browsable.items():
        if len(catalog) >= MAX_TABLES:
            break
        info = TableInfo(
            name=name,
            label=table_label(name),
            group=module_group(name),
            table=browsable_table.table,
            scope=browsable_table.scope,
            scope_label=browsable_table.scope_label,
            columns={column.name: column for column in browsable_table.visible_columns},
            primary_key=browsable_table.primary_key,
        )
        info.relations = _relations_for(info, browsable)
        catalog[name] = info
    return catalog


def catalog_payload(engine: Engine) -> dict:
    catalog = build_catalog(engine)
    groups: dict[str, list[str]] = {}
    for info in catalog.values():
        groups.setdefault(info.group, []).append(info.name)
    return {
        "tables": [info.summary() for info in sorted(catalog.values(), key=lambda item: (item.group, item.label))],
        "groups": [
            {"group": group, "tables": sorted(tables)} for group, tables in sorted(groups.items())
        ],
        "table_count": len(catalog),
        "relation_help": "A related column follows one declared foreign key from the report's table to its parent "
                         "(for example entry_id → Daily Cost Entries). No arbitrary joins are possible.",
    }


class CatalogError(ValueError):
    pass


def resolve_column(
    catalog: dict[str, TableInfo],
    *,
    source_table: str,
    source_kind: str,
    column_name: str,
    related_table: str = "",
    related_key_column: str = "",
) -> tuple[Column, str | None, Relation | None]:
    """Find a catalogued column, returning (column, alias suffix, relation)."""
    base = catalog.get(source_table)
    if base is None:
        raise CatalogError(f"The data source {source_table!r} is not available in this workspace.")
    kind = (source_kind or "DATA").upper()
    if kind == "DATA":
        column = base.columns.get(column_name or "")
        if column is None:
            raise CatalogError(f"{base.label} has no column named {column_name!r}.")
        return column, None, None
    if kind != "RELATED":
        raise CatalogError(f"{source_kind!r} is not a supported column source.")
    relation = base.relations.get(related_key_column or "")
    if relation is None:
        raise CatalogError(
            f"{base.label} has no declared link through {related_key_column!r}. Choose one of its foreign keys."
        )
    if related_table and relation.parent_name != related_table:
        raise CatalogError(
            f"{base.label}.{relation.key_column} points at {relation.parent_label}, not {related_table!r}."
        )
    column = relation.parent_columns.get(column_name or "")
    if column is None:
        raise CatalogError(f"{relation.parent_label} has no column named {column_name!r}.")
    return column, relation.key_column, relation


def column_data_type(column: Column) -> str:
    return value_type(column)


def relation_join_condition(relation: Relation, alias):
    """The SQL join predicate for one relation alias (base column handled by the caller)."""
    return alias.c[relation.parent_pk]


def parent_alias_key(relation: Relation) -> str:
    return f"{relation.parent_name}::{relation.key_column}"


def relation_scope_condition(relation: Relation, alias, organization_id: str):
    """Related rows of a tenant-bearing parent stay inside the caller's workspace.

    The predicate uses the join *alias*, never the reflected parent table, so the
    generated statement cannot grow a second, unaliased FROM entry.
    """
    if "organization_id" in alias.c:
        return alias.c.organization_id == organization_id
    return None


def count_table_rows(db: Session, info: TableInfo, organization_id: str) -> int:
    from sqlalchemy import func

    statement = select(func.count()).select_from(info.table).where(info.scope(organization_id))
    return int(db.scalar(statement) or 0)


def no_rows_condition():
    """A deliberately impossible predicate, used when a caller has no scope at all."""
    return false()
