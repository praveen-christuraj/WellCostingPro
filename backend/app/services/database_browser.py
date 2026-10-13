"""Database Browser: a read-only, tenant-scoped view of every table in the database.

Design rules (enforced here, not in the UI):

* Tables are **reflected from the live database**, so the browser always matches the
  real structure, including tables that migrations added later.
* Every table must be **scoped to the caller's workspace**. A table with an
  ``organization_id`` column is filtered on it; a child table is filtered through its
  foreign-key chain (for example ``user_roles`` → ``users.organization_id``). A table
  that cannot be tied to a workspace is not shown at all, so another tenant's rows can
  never leak through this module.
* Credential, session and lockout columns are **never** returned, sorted, filtered or
  exported (see ``HIDDEN_COLUMN_PATTERN``); the session table is hidden entirely.
* Identifiers come only from the reflected schema. Request input is matched against
  those names; it is never interpolated into SQL. Nothing here writes to the database.
"""
import csv
import io
import math
import re
import tempfile
import warnings
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Callable
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, MetaData, Numeric, Table, Time, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import Session

# Tables that are internal plumbing or hold session secrets: never listed.
HIDDEN_TABLES = frozenset({"alembic_version", "refresh_sessions"})
# Columns that hold credentials, token material or lockout state: never shown.
HIDDEN_COLUMN_PATTERN = re.compile(r"password|secret|token|hash", re.IGNORECASE)
HIDDEN_COLUMNS = frozenset({"failed_logins", "locked_until", "token_version"})
# The grid preview is capped so a very large table cannot exhaust memory in the browser.
PREVIEW_ROW_LIMIT = 5000
# Full CSV downloads are streamed to a temporary file; this cap protects the API host.
EXPORT_ROW_LIMIT = 250_000
EXPORT_FORMATS = ("csv", "xlsx", "pdf")
MAX_SCOPE_DEPTH = 4

# Module grouping used by the catalogue. Matched by table-name prefix, first match wins.
MODULE_GROUPS: tuple[tuple[str, str], ...] = (
    ("daily_cost", "Daily Cost Management"),
    ("afe", "AFE Management"),
    ("rigs", "Rig & Well Management"),
    ("rig", "Rig & Well Management"),
    ("wells", "Rig & Well Management"),
    ("well", "Rig & Well Management"),
    ("audit", "Other Managements"),
    ("users", "User Management"),
    ("user_", "User Management"),
    ("roles", "User Management"),
    ("role_", "User Management"),
    ("permissions", "User Management"),
    ("organizations", "User Management"),
    ("vendors", "Master Data Management"),
    ("purchase_orders", "Master Data Management"),
    ("po_so_", "Master Data Management"),
    ("order_documents", "Master Data Management"),
    ("services", "Master Data Management"),
    ("uom", "Master Data Management"),
    ("currencies", "Master Data Management"),
    ("phases", "Master Data Management"),
    ("hole_sections", "Master Data Management"),
    ("activities", "Master Data Management"),
    ("tangible", "Master Data Management"),
    ("consumable", "Master Data Management"),
    ("catalogue", "Master Data Management"),
    ("cement_", "Master Data Management"),
    ("drill_", "Master Data Management"),
    ("fuel_", "Master Data Management"),
    ("mud_", "Master Data Management"),
)


class DatabaseBrowserError(Exception):
    """Carries an HTTP-style status so the router can answer with a readable message."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class BrowsableTable:
    table: Table
    scope: Callable[[str], ColumnElement]
    scope_label: str
    group: str

    @property
    def name(self) -> str:
        return self.table.name

    @property
    def visible_columns(self) -> list:
        return [column for column in self.table.columns if not is_hidden_column(column.name)]

    @property
    def primary_key(self) -> list[str]:
        return [column.name for column in self.table.primary_key.columns if not is_hidden_column(column.name)]


def is_hidden_column(name: str) -> bool:
    return name in HIDDEN_COLUMNS or bool(HIDDEN_COLUMN_PATTERN.search(name))


def module_group(table_name: str) -> str:
    for prefix, group in MODULE_GROUPS:
        if table_name == prefix or table_name.startswith(prefix):
            return group
    return "Other"


def column_kind(column) -> str:
    """Coarse type family the UI uses for alignment, sorting and filter operators."""
    kind = column.type
    if isinstance(kind, Boolean):
        return "boolean"
    if isinstance(kind, (Integer, Numeric, Float)):
        return "number"
    if isinstance(kind, (DateTime, Date, Time)):
        return "date"
    return "text"


def _scope_for(table: Table, seen: frozenset[str] = frozenset()) -> tuple[Callable[[str], ColumnElement], str] | None:
    """Find how to restrict ``table`` to one workspace, or None when it cannot be tied to one."""
    if table.name == "organizations":
        return (lambda org: table.c.id == org), "organizations.id"
    if "organization_id" in table.c:
        return (lambda org: table.c.organization_id == org), "organization_id"
    if table.name in seen or len(seen) >= MAX_SCOPE_DEPTH:
        return None
    column_order = {column.name: index for index, column in enumerate(table.columns)}
    single_column_constraints = [constraint for constraint in table.foreign_key_constraints if len(constraint.columns) == 1]
    for constraint in sorted(
        single_column_constraints,
        key=lambda item: (
            column_order.get(next(iter(item.columns)).name, len(column_order)),
            next(iter(item.columns)).name,
            item.name or "",
        ),
    ):
        parent = list(constraint.columns)[0]
        reference = list(constraint.elements)[0].column
        resolved = _scope_for(reference.table, seen | {table.name})
        if resolved is None:
            continue
        inner, _ = resolved
        return (
            lambda org, p=parent, r=reference, build=inner: p.in_(select(r).where(build(org)))
        ), f"{parent.name} → {reference.table.name}"
    return None


def reflect(engine: Engine) -> MetaData:
    """Reflect the whole database. Not cached, so a migration is visible immediately."""
    metadata = MetaData()
    with warnings.catch_warnings():
        # Expression indexes (for example lower(name)) cannot be reflected; they are not browsable anyway.
        warnings.filterwarnings("ignore", message="Skipped unsupported reflection of expression-based index")
        metadata.reflect(bind=engine)
    return metadata


def browsable_tables(engine: Engine) -> dict[str, BrowsableTable]:
    """Every table this workspace may browse, keyed by table name."""
    metadata = reflect(engine)
    result: dict[str, BrowsableTable] = {}
    for name, table in metadata.tables.items():
        if name in HIDDEN_TABLES:
            continue
        resolved = _scope_for(table)
        if resolved is None:
            continue
        scope, label = resolved
        result[name] = BrowsableTable(table=table, scope=scope, scope_label=label, group=module_group(name))
    return result


def get_browsable(engine: Engine, table_name: str) -> BrowsableTable:
    tables = browsable_tables(engine)
    if table_name not in tables:
        raise DatabaseBrowserError(404, "Table not found or not available in this workspace")
    return tables[table_name]


def jsonable(value):
    """Convert a database value into a plain JSON value without losing precision."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary {len(bytes(value))} bytes>"
    return str(value)


def _order_by(bt: BrowsableTable):
    """Newest first when the table has a timestamp, then primary key for a stable order."""
    columns = []
    if "created_at" in bt.table.c and not is_hidden_column("created_at"):
        columns.append(bt.table.c.created_at.desc())
    columns.extend(bt.table.c[name].asc() for name in bt.primary_key)
    return columns


def count_rows(db: Session, bt: BrowsableTable, organization_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(bt.table).where(bt.scope(organization_id))) or 0)


def preview_rows(db: Session, bt: BrowsableTable, organization_id: str, limit: int) -> tuple[list[dict], int]:
    """Visible columns of the newest rows in this workspace, capped at ``limit``."""
    limit = max(1, min(limit, PREVIEW_ROW_LIMIT))
    columns = bt.visible_columns
    total = count_rows(db, bt, organization_id)
    statement = (
        select(*columns)
        .where(bt.scope(organization_id))
        .order_by(*_order_by(bt))
        .limit(limit)
    )
    names = [column.name for column in columns]
    rows = [{name: jsonable(value) for name, value in zip(names, record)} for record in db.execute(statement).all()]
    return rows, total


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (datetime, date, time)):
        text = value.isoformat()
    elif isinstance(value, (bytes, bytearray, memoryview)):
        text = jsonable(value)
    else:
        text = str(value)
    # Keep spreadsheet applications from evaluating database text as a formula.
    if text[:1] in ("=", "+", "@", "\t", "\r"):
        text = "'" + text
    return text


def export_csv(db: Session, bt: BrowsableTable, organization_id: str) -> tuple[tempfile.SpooledTemporaryFile, int]:
    """Stream every workspace row of one table into a UTF-8 CSV (with BOM for Excel and Power BI)."""
    total = count_rows(db, bt, organization_id)
    if total > EXPORT_ROW_LIMIT:
        raise DatabaseBrowserError(422, f"{bt.name} has {total:,} rows, above the {EXPORT_ROW_LIMIT:,}-row download limit. Narrow the table with a database query.")
    columns = bt.visible_columns
    statement = select(*columns).where(bt.scope(organization_id)).order_by(*_order_by(bt))
    buffer = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    text = io.TextIOWrapper(buffer, encoding="utf-8-sig", newline="")
    writer = csv.writer(text)
    writer.writerow([column.name for column in columns])
    result = db.execute(statement, execution_options={"yield_per": 1000})
    for record in result:
        writer.writerow([_csv_cell(value) for value in record])
    text.flush()
    text.detach()
    buffer.seek(0)
    return buffer, total
