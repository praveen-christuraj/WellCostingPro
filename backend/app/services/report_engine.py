"""Report Builder validation and execution.

Pipeline for one run:

1. **Validate** the saved design against the live catalogue (tables, columns,
   related links, operators, formulae and access targets). A design that no
   longer fits the schema answers with readable problems instead of SQL errors.
2. **Load** the base rows through SQLAlchemy with bound parameters only, joined
   to at most one declared parent per foreign key and already limited to the
   caller's workspace.
3. **Compare** per-column rules: a measure can be blanked for rows that do not
   match, without dropping the row (this is how the same quantity appears twice
   with different conditions).
4. **Calculate** formula columns in dependency order with the Decimal engine;
   a failed cell is blank and counted, never fatal.
5. **Filter** (fixed, then run-time, then quick search), **group** or **pivot**,
   **total**, **sort**, page and format.

All caps produce explicit warnings — a report never silently drops data.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections import OrderedDict
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import Date as SADate, DateTime as SADateTime, and_, select
from sqlalchemy.orm import Session

from app.models import ReportDefinition
from app.core.spreadsheets import safe_csv_cell
from app.services import report_formula as formula
from app.services.report_catalog import (
    CatalogError,
    Relation,
    build_catalog,
    column_data_type,
    humanize,
    relation_scope_condition,
    resolve_column,
    table_label,
)

SCAN_CAP = 50_000
EXPORT_CAP = 50_000
MAX_COLUMNS = 60
MAX_MATRIX_COLUMNS = 60
MAX_CONDITIONS_PER_COLUMN = 20
MAX_CONDITIONS = 100
MAX_FILTERS = 30
MAX_RUNTIME_FILTERS = 12
MAX_SORTS = 5
MAX_GROUPINGS = 5
MAX_PAGE_SIZE = 500
TIME_BUDGET_SECONDS = 25
MAX_TEXT_CELL = 2000

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REPORT_TYPES = {"TABULAR", "MATRIX"}
COLUMN_KINDS = {"DATA", "RELATED", "CALCULATED"}
DATA_TYPES = {"text", "number", "date", "boolean"}
AGGREGATES = {"NONE", "SUM", "AVG", "COUNT", "COUNT_DISTINCT", "MIN", "MAX", "PRODUCT", "FIRST", "LAST"}
NUMERIC_AGGREGATES = {"SUM", "AVG", "MIN", "MAX", "PRODUCT"}
BUCKETS = {"VALUE", "DAY", "WEEK", "MONTH", "QUARTER", "YEAR"}
OPERATORS = {
    "eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_contains", "starts_with",
    "ends_with", "in", "not_in", "between", "is_blank", "is_not_blank",
}
RUNTIME_TYPES = {"text", "number", "date", "boolean", "select"}
DATE_BASES = {"COLUMN", "CREATED_AT", "UPDATED_AT", "NONE"}
GRANT_TYPES = {"user", "role"}
LEVELS = {"view", "edit"}
MONTH_LABELS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class ReportError(ValueError):
    """A rejected design or run, carrying the HTTP status for the router."""

    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Definition shape helpers
# ---------------------------------------------------------------------------


def empty_definition() -> dict:
    return {
        "name": "", "description": "", "report_type": "TABULAR",
        "source_table": "", "date_basis": "NONE", "date_column": "",
        "filter_logic": "AND", "show_totals": True, "page_size": 50, "empty_text": "",
        "matrix_value_key": "", "matrix_aggregate": "SUM", "matrix_show_totals": True,
        "visibility": "private",
        "columns": [], "filters": [], "runtime_filters": [], "groupings": [], "sorts": [], "grants": [],
    }


def definition_from_record(record: ReportDefinition) -> dict:
    return {
        "name": record.name,
        "description": record.description,
        "report_type": record.report_type,
        "source_table": record.source_table,
        "date_basis": record.date_basis,
        "date_column": record.date_column,
        "filter_logic": record.filter_logic,
        "show_totals": record.show_totals,
        "page_size": record.page_size,
        "empty_text": record.empty_text,
        "matrix_value_key": record.matrix_value_key,
        "matrix_aggregate": record.matrix_aggregate,
        "matrix_show_totals": record.matrix_show_totals,
        "visibility": record.visibility,
        "columns": [
            {
                "key": column.key, "label": column.label, "kind": column.kind,
                "column_name": column.column_name, "related_table": column.related_table,
                "related_key_column": column.related_key_column, "formula": column.formula,
                "data_type": column.data_type, "decimals": column.decimals,
                "prefix": column.prefix, "suffix": column.suffix, "aggregate": column.aggregate,
                "show_total": column.show_total, "hidden": column.hidden,
                "condition_logic": column.condition_logic, "width": column.width,
                "conditions": [
                    {
                        "source_kind": condition.source_kind, "column_name": condition.column_name,
                        "related_table": condition.related_table, "related_key_column": condition.related_key_column,
                        "operator": condition.operator, "value": condition.value, "value2": condition.value2,
                    }
                    for condition in column.conditions
                ],
            }
            for column in record.columns
        ],
        "filters": [
            {
                "label": item.label, "source_kind": item.source_kind, "column_name": item.column_name,
                "related_table": item.related_table, "related_key_column": item.related_key_column,
                "operator": item.operator, "value": item.value, "value2": item.value2,
            }
            for item in record.filters
        ],
        "runtime_filters": [
            {
                "key": item.key, "label": item.label, "filter_type": item.filter_type,
                "source_kind": item.source_kind, "column_name": item.column_name,
                "related_table": item.related_table, "related_key_column": item.related_key_column,
                "operator": item.operator, "required": item.required, "default_value": item.default_value,
                "options": [option for option in (item.options_text or "").split("\n") if option],
            }
            for item in record.runtime_filters
        ],
        "groupings": [
            {"kind": item.kind, "column_key": item.column_key, "bucket": item.bucket} for item in record.groupings
        ],
        "sorts": [{"column_key": item.column_key, "direction": item.direction} for item in record.sorts],
        "grants": [
            {
                "grant_type": item.grant_type,
                "user_id": item.user_id or "",
                "role_id": item.role_id or "",
                "level": item.level,
            }
            for item in record.grants
        ],
    }


def snapshot_definition(record: ReportDefinition) -> str:
    import json

    return json.dumps(definition_from_record(record), ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Validation / normalisation
# ---------------------------------------------------------------------------


def _as_text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _resolve(catalog, source_table: str, item: dict, owner: str):
    try:
        return resolve_column(
            catalog,
            source_table=source_table,
            source_kind=item.get("source_kind", "DATA"),
            column_name=item.get("column_name", ""),
            related_table=item.get("related_table", ""),
            related_key_column=item.get("related_key_column", ""),
        )
    except CatalogError as error:
        raise ReportError(f"{owner}: {error}") from error


def validate_definition(db: Session, payload: dict, organization_id: str) -> dict:
    """Return a normalised design, or raise :class:`ReportError` with the problems."""
    from app.models import Role, User

    if not isinstance(payload, dict):
        raise ReportError("The report design could not be read.")
    design = empty_definition()
    design.update({key: value for key, value in payload.items() if key in design or key in {"name", "description"}})
    design["name"] = _as_text(payload.get("name"), 160)
    design["description"] = _as_text(payload.get("description"), 1000)
    design["empty_text"] = _as_text(payload.get("empty_text"), 200)
    if not design["name"]:
        raise ReportError("Give the report a name.")
    if design["report_type"] not in REPORT_TYPES:
        raise ReportError("Choose either a tabular or a matrix report.")
    catalog = build_catalog(db.get_bind())
    table = catalog.get(design["source_table"])
    if table is None:
        raise ReportError("Choose the table this report reads from. It is not available in this workspace.")
    problems: list[str] = []

    # Date basis
    design["date_basis"] = str(design["date_basis"]).upper()
    if design["date_basis"] not in DATE_BASES:
        raise ReportError("Choose a valid date basis for the date range.")
    if design["date_basis"] == "COLUMN":
        if design["date_column"] not in table.columns:
            raise ReportError(f"{table.label} has no column named {design['date_column']!r} for the date range.")
    elif design["date_basis"] == "CREATED_AT" and "created_at" not in table.columns:
        raise ReportError(f"{table.label} has no creation date, so it cannot be filtered by date.")
    elif design["date_basis"] == "UPDATED_AT" and "updated_at" not in table.columns:
        raise ReportError(f"{table.label} has no update date, so it cannot be filtered by date.")
    else:
        design["date_column"] = ""

    columns_in = payload.get("columns") or []
    if not isinstance(columns_in, list) or not columns_in:
        raise ReportError("Add at least one column to the report.")
    if len(columns_in) > MAX_COLUMNS:
        raise ReportError(f"A report can hold at most {MAX_COLUMNS} columns.")
    seen_keys: set[str] = set()
    columns: list[dict] = []
    condition_total = 0
    for position, item in enumerate(columns_in, start=1):
        if not isinstance(item, dict):
            raise ReportError(f"Column {position} could not be read.")
        key = _as_text(item.get("key"), 80)
        if not KEY_RE.match(key):
            problems.append(f"Column {position}: the key must start with a letter and use lowercase letters, numbers and underscores.")
            continue
        if key in seen_keys:
            problems.append(f"Column {position}: the key {key!r} is used twice.")
            continue
        seen_keys.add(key)
        kind = str(item.get("kind") or "DATA").upper()
        if kind not in COLUMN_KINDS:
            problems.append(f"Column {key}: choose a data, related or calculated column.")
            continue
        label = _as_text(item.get("label"), 160) or humanize(item.get("column_name") or key)
        column: dict = {
            "key": key, "label": label, "kind": kind,
            "column_name": "", "related_table": "", "related_key_column": "", "formula": "",
            "data_type": "text", "decimals": 2, "prefix": _as_text(item.get("prefix"), 20),
            "suffix": _as_text(item.get("suffix"), 20), "show_total": bool(item.get("show_total")),
            "hidden": bool(item.get("hidden")), "width": int(item.get("width") or 0),
            "condition_logic": str(item.get("condition_logic") or "AND").upper(),
            "aggregate": str(item.get("aggregate") or "NONE").upper(),
            "conditions": [],
        }
        if column["condition_logic"] not in {"AND", "OR"}:
            problems.append(f"Column {key}: comparison rules must be combined with AND or OR.")
        if column["aggregate"] not in AGGREGATES:
            problems.append(f"Column {key}: {column['aggregate']!r} is not a supported summary.")
        try:
            column["decimals"] = max(0, min(8, int(item.get("decimals", 2))))
        except (TypeError, ValueError):
            column["decimals"] = 2
        if kind in {"DATA", "RELATED"}:
            column["column_name"] = _as_text(item.get("column_name"), 120)
            column["related_table"] = _as_text(item.get("related_table"), 120)
            column["related_key_column"] = _as_text(item.get("related_key_column"), 120)
            resolved, alias, relation = _resolve(catalog, design["source_table"], {
                "source_kind": kind, "column_name": column["column_name"],
                "related_table": column["related_table"], "related_key_column": column["related_key_column"],
            }, f"Column {key}")
            stored_type = column_data_type(resolved)
            column["related_table"] = relation.parent_name if relation else ""
            column["related_key_column"] = relation.key_column if relation else ""
            # A count is a number even when it counts text; a stored text column
            # cannot be summed. Everything else keeps the database's own type.
            if column["aggregate"] in {"COUNT", "COUNT_DISTINCT"}:
                column["data_type"] = "number"
            elif column["aggregate"] in {"SUM", "AVG", "PRODUCT"} and stored_type != "number":
                problems.append(f"Column {key}: {column['aggregate'].title()} needs a number column, but this one stores {stored_type}.")
                column["data_type"] = stored_type
            else:
                column["data_type"] = stored_type
            if not item.get("label") and not column["label"]:
                column["label"] = humanize(resolved.name)
        else:
            column["formula"] = _as_text(item.get("formula"), 2000)
            if not column["formula"]:
                problems.append(f"Column {key}: a calculated column needs a formula.")
            declared = str(item.get("data_type") or "number").lower()
            column["data_type"] = declared if declared in {"number", "text", "date"} else "number"
            # Comparison rules belong to a stored quantity, never to a formula.
            if item.get("conditions"):
                problems.append(f"Column {key}: comparison rules apply to a data column, not a calculated one.")
        raw_conditions = item.get("conditions") or []
        if len(raw_conditions) > MAX_CONDITIONS_PER_COLUMN:
            problems.append(f"Column {key}: at most {MAX_CONDITIONS_PER_COLUMN} comparison rules are allowed.")
        for condition in raw_conditions[:MAX_CONDITIONS_PER_COLUMN]:
            if not isinstance(condition, dict):
                continue
            operator = str(condition.get("operator") or "eq")
            if operator not in OPERATORS:
                problems.append(f"Column {key}: {operator!r} is not a supported comparison.")
                continue
            try:
                resolved, _, relation = _resolve(catalog, design["source_table"], condition, f"Column {key} comparison")
            except ReportError as error:
                problems.append(str(error))
                continue
            condition_total += 1
            column["conditions"].append({
                "source_kind": str(condition.get("source_kind") or "DATA").upper(),
                "column_name": resolved.name,
                "related_table": relation.parent_name if relation else "",
                "related_key_column": relation.key_column if relation else "",
                "operator": operator,
                "value": _as_text(condition.get("value"), 500),
                "value2": _as_text(condition.get("value2"), 500),
            })
        if not raw_conditions:
            column["condition_logic"] = "AND"
        columns.append(column)
    if condition_total > MAX_CONDITIONS:
        problems.append(f"A report can hold at most {MAX_CONDITIONS} comparison rules in total.")

    # Calculated formulas can only use columns this report defines.
    available = {column["key"] for column in columns}
    for column in columns:
        if column["kind"] != "CALCULATED":
            continue
        for problem in formula.validate_formula(column["formula"], available):
            problems.append(f"Column {column['key']}: {problem}")
    calculated = [column for column in columns if column["kind"] == "CALCULATED"]
    if calculated:
        dependencies = {
            column["key"]: [key for key in formula.referenced_columns(column["formula"]) if key in {c["key"] for c in calculated}]
            for column in calculated
        }
        if _has_cycle(dependencies):
            problems.append("The calculated columns refer to each other in a circle. Break the circle by splitting one formula.")
    design["columns"] = columns
    visible = [column for column in columns if not column["hidden"]]
    if not visible:
        raise ReportError("Every column is hidden, so the report would show nothing. Show at least one column.")

    # Fixed filters
    filters = []
    for index, item in enumerate(payload.get("filters") or []):
        if not isinstance(item, dict):
            continue
        operator = str(item.get("operator") or "eq")
        if operator not in OPERATORS:
            problems.append(f"Filter {index + 1}: {operator!r} is not a supported operator.")
            continue
        try:
            resolved, _, relation = _resolve(catalog, design["source_table"], item, f"Filter {index + 1}")
        except ReportError as error:
            problems.append(str(error))
            continue
        filters.append({
            "label": _as_text(item.get("label"), 160) or humanize(resolved.name),
            "source_kind": str(item.get("source_kind") or "DATA").upper(),
            "column_name": resolved.name,
            "related_table": relation.parent_name if relation else "",
            "related_key_column": relation.key_column if relation else "",
            "operator": operator,
            "value": _as_text(item.get("value"), 500),
            "value2": _as_text(item.get("value2"), 500),
        })
    if len(filters) > MAX_FILTERS:
        raise ReportError(f"A report can hold at most {MAX_FILTERS} fixed filters.")
    design["filters"] = filters
    design["filter_logic"] = "OR" if str(payload.get("filter_logic") or "AND").upper() == "OR" else "AND"

    # Run-time questions
    runtime = []
    runtime_keys: set[str] = set()
    for index, item in enumerate(payload.get("runtime_filters") or []):
        if not isinstance(item, dict):
            continue
        key = _as_text(item.get("key"), 80)
        if not KEY_RE.match(key):
            problems.append(f"Run-time filter {index + 1}: the key must be lowercase letters, numbers and underscores.")
            continue
        if key in runtime_keys:
            problems.append(f"Run-time filter {index + 1}: the key {key!r} is used twice.")
            continue
        runtime_keys.add(key)
        filter_type = str(item.get("filter_type") or "text").lower()
        if filter_type not in RUNTIME_TYPES:
            problems.append(f"Run-time filter {key}: {filter_type!r} is not a supported question type.")
            continue
        operator = str(item.get("operator") or ("between" if filter_type == "date" else "eq"))
        if operator not in OPERATORS:
            problems.append(f"Run-time filter {key}: {operator!r} is not a supported operator.")
            continue
        try:
            resolved, _, relation = _resolve(catalog, design["source_table"], item, f"Run-time filter {key}")
        except ReportError as error:
            problems.append(str(error))
            continue
        options = [str(option).strip() for option in (item.get("options") or []) if str(option).strip()]
        if filter_type == "select" and not options:
            problems.append(f"Run-time filter {key}: add the choices the user can pick from.")
        runtime.append({
            "key": key,
            "label": _as_text(item.get("label"), 160) or humanize(resolved.name),
            "filter_type": filter_type,
            "source_kind": str(item.get("source_kind") or "DATA").upper(),
            "column_name": resolved.name,
            "related_table": relation.parent_name if relation else "",
            "related_key_column": relation.key_column if relation else "",
            "operator": operator,
            "required": bool(item.get("required")),
            "default_value": _as_text(item.get("default_value"), 500),
            "options": options[:50],
        })
    if len(runtime) > MAX_RUNTIME_FILTERS:
        raise ReportError(f"A report can hold at most {MAX_RUNTIME_FILTERS} run-time questions.")
    design["runtime_filters"] = runtime

    # Grouping / layout
    columns_by_key = {column["key"]: column for column in columns}
    groupings = []
    for item in payload.get("groupings") or []:
        if not isinstance(item, dict):
            continue
        column_key = _as_text(item.get("column_key"), 80)
        kind = str(item.get("kind") or "group").lower()
        bucket = str(item.get("bucket") or "VALUE").upper()
        if column_key not in columns_by_key:
            problems.append(f"Grouping: {column_key!r} is not a column of this report.")
            continue
        if kind not in {"group", "matrix_row", "matrix_column"}:
            problems.append("Grouping: choose a grouping, matrix row or matrix column.")
            continue
        if bucket not in BUCKETS:
            problems.append(f"Grouping {column_key}: {bucket!r} is not a supported date period.")
            continue
        if bucket != "VALUE" and columns_by_key[column_key]["data_type"] != "date":
            problems.append(f"Grouping {column_key}: only a date column can be grouped by day, week, month, quarter or year.")
            bucket = "VALUE"
        groupings.append({"kind": kind, "column_key": column_key, "bucket": bucket})
    if len(groupings) > MAX_GROUPINGS:
        raise ReportError(f"At most {MAX_GROUPINGS} grouping choices are allowed.")
    tabular_groupings = [item for item in groupings if item["kind"] == "group"]
    matrix_rows = [item for item in groupings if item["kind"] == "matrix_row"]
    matrix_columns = [item for item in groupings if item["kind"] == "matrix_column"]
    if len({item["column_key"] for item in tabular_groupings}) != len(tabular_groupings):
        problems.append("Each column can be grouped once.")
    if design["report_type"] == "TABULAR":
        if matrix_rows or matrix_columns:
            problems.append("A tabular report cannot have matrix row or column groupings.")
    else:
        if tabular_groupings:
            problems.append("A matrix report uses matrix rows and one matrix column, not a grouped summary.")
        if not 1 <= len(matrix_rows) <= 3:
            problems.append("A matrix report needs one to three matrix rows.")
        if len(matrix_columns) != 1:
            problems.append("A matrix report needs exactly one matrix column.")
        design["matrix_value_key"] = _as_text(payload.get("matrix_value_key"), 80)
        design["matrix_aggregate"] = str(payload.get("matrix_aggregate") or "SUM").upper()
        value_column = columns_by_key.get(design["matrix_value_key"])
        counts_only = design["matrix_aggregate"] in {"COUNT", "COUNT_DISTINCT"}
        if value_column is None:
            problems.append("Choose the column whose values fill the matrix cells.")
        elif value_column["data_type"] != "number" and not counts_only:
            problems.append(
                f"Matrix cells need a number column; {value_column['label']} is {value_column['data_type']}. "
                "Use Count to count its values instead."
            )
        if design["matrix_aggregate"] not in AGGREGATES - {"NONE"}:
            problems.append("Choose a summary for the matrix cells.")
        design["matrix_show_totals"] = bool(payload.get("matrix_show_totals", True))
    if len({item["column_key"] for item in matrix_rows}) != len(matrix_rows):
        problems.append("Each matrix row dimension can be used once.")
    design["groupings"] = groupings

    # Summaries: a grouped report needs one summary per non-grouping column.
    if tabular_groupings:
        grouped_keys = {item["column_key"] for item in tabular_groupings}
        for column in columns:
            if column["key"] in grouped_keys:
                column["aggregate"] = "NONE"
                column["show_total"] = False
                continue
            if column["aggregate"] == "NONE":
                column["aggregate"] = "SUM" if column["data_type"] == "number" else "FIRST"
    if design["report_type"] == "MATRIX":
        for column in columns:
            if column["key"] != design["matrix_value_key"] and column["aggregate"] == "NONE" and column["data_type"] == "number":
                column["aggregate"] = "SUM"

    sorts = []
    for item in payload.get("sorts") or []:
        if not isinstance(item, dict):
            continue
        column_key = _as_text(item.get("column_key"), 80)
        if column_key not in columns_by_key:
            problems.append(f"Sorting: {column_key!r} is not a column of this report.")
            continue
        direction = "DESC" if str(item.get("direction") or "ASC").upper() == "DESC" else "ASC"
        sorts.append({"column_key": column_key, "direction": direction})
    if len(sorts) > MAX_SORTS:
        raise ReportError(f"At most {MAX_SORTS} sort columns are allowed.")
    design["sorts"] = sorts

    # Access grants
    grants = []
    for item in payload.get("grants") or []:
        if not isinstance(item, dict):
            continue
        grant_type = str(item.get("grant_type") or "").lower()
        level = str(item.get("level") or "view").lower()
        if grant_type not in GRANT_TYPES or level not in LEVELS:
            problems.append("Access: each grant must name a user or role and a view or edit level.")
            continue
        target_id = _as_text(item.get("user_id") if grant_type == "user" else item.get("role_id"), 36)
        if not target_id:
            problems.append("Access: choose the user or role to share the report with.")
            continue
        model = User if grant_type == "user" else Role
        if db.get(model, target_id) is None or db.get(model, target_id).organization_id != organization_id:
            problems.append("Access: that account or role is not in this workspace.")
            continue
        grants.append({
            "grant_type": grant_type, "user_id": target_id if grant_type == "user" else "",
            "role_id": target_id if grant_type == "role" else "", "level": level,
        })
    seen_grants = set()
    unique_grants = []
    for grant in grants:
        signature = (grant["grant_type"], grant["user_id"] or grant["role_id"])
        if signature in seen_grants:
            continue
        seen_grants.add(signature)
        unique_grants.append(grant)
    design["grants"] = unique_grants
    if len(unique_grants) > 100:
        raise ReportError("A report can be shared with at most 100 users and roles.")

    design["visibility"] = str(payload.get("visibility") or "private").lower()
    if design["visibility"] not in {"private", "internal", "shared"}:
        design["visibility"] = "private"
    if design["visibility"] == "shared" and not unique_grants:
        problems.append("Access: add at least one user or role, or choose another visibility.")
    if design["visibility"] == "private" and unique_grants:
        design["visibility"] = "shared"
    try:
        design["page_size"] = max(10, min(MAX_PAGE_SIZE, int(payload.get("page_size") or 50)))
    except (TypeError, ValueError):
        design["page_size"] = 50
    design["show_totals"] = bool(payload.get("show_totals", True))

    if problems:
        raise ReportError(" ".join(dict.fromkeys(problems))[:2000])
    return design


def _has_cycle(dependencies: dict[str, list[str]]) -> bool:
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        for child in dependencies.get(node, []):
            if visit(child):
                return True
        state[node] = 2
        return False

    return any(visit(node) for node in dependencies)


# ---------------------------------------------------------------------------
# Values, operators and formatting
# ---------------------------------------------------------------------------


def _coerce_comparable(value):
    if formula.is_blank(value):
        return None
    return value


def _matches(operator: str, value, expected: str, expected2: str = "") -> bool:
    blank = formula.is_blank(value)
    if operator == "is_blank":
        return blank
    if operator == "is_not_blank":
        return not blank
    if operator in {"in", "not_in"}:
        options = [item.strip() for item in str(expected).split(",") if item.strip()]
        hit = any(formula.compare_values(value, option) == 0 for option in options)
        return hit if operator == "in" else not hit
    if operator == "between":
        low = formula.compare_values(value, expected)
        high = formula.compare_values(value, expected2)
        return low is not None and high is not None and low >= 0 and high <= 0
    if operator in {"contains", "not_contains", "starts_with", "ends_with"}:
        if blank:
            return operator == "not_contains"
        haystack = formula.to_text(value).lower()
        needle = str(expected).lower()
        if operator == "contains":
            return needle in haystack
        if operator == "not_contains":
            return needle not in haystack
        if operator == "starts_with":
            return haystack.startswith(needle)
        return haystack.endswith(needle)
    outcome = formula.compare_values(value, expected)
    if outcome is None:
        # Blank only equals blank.
        return operator == "eq" and formula.is_blank(expected)
    return {
        "eq": outcome == 0, "ne": outcome != 0, "gt": outcome > 0,
        "gte": outcome >= 0, "lt": outcome < 0, "lte": outcome <= 0,
    }[operator]


def _bucket(value, bucket: str):
    """Grouping label and sort key for a value and a date period."""
    if bucket == "VALUE":
        return value
    moment = value if isinstance(value, (date, datetime)) else formula.to_date(value)
    if moment is None:
        return None
    if isinstance(moment, datetime):
        moment = moment.date()
    if bucket == "DAY":
        return moment
    if bucket == "WEEK":
        monday = moment - timedelta(days=moment.weekday())
        return monday
    if bucket == "MONTH":
        return date(moment.year, moment.month, 1)
    if bucket == "QUARTER":
        return date(moment.year, ((moment.month - 1) // 3) * 3 + 1, 1)
    return date(moment.year, 1, 1)


def bucket_label(value, bucket: str) -> str:
    if value is None or bucket == "VALUE":
        return format_value(value, {"data_type": "text", "decimals": 0, "prefix": "", "suffix": ""})
    if isinstance(value, datetime):
        value = value.date()
    if bucket == "DAY":
        return value.isoformat()
    if bucket == "WEEK":
        return f"Week of {value.isoformat()}"
    if bucket == "MONTH":
        return f"{value.year:04d}-{value.month:02d}"
    if bucket == "QUARTER":
        return f"{value.year:04d} Q{(value.month - 1) // 3 + 1}"
    return f"{value.year:04d}"


def _quantity(value):
    return formula.to_decimal(value)


def aggregate_values(values: list, aggregate: str, data_type: str = "number"):
    """Summarise raw values for one output cell. Blanks are ignored."""
    present = [value for value in values if not formula.is_blank(value)]
    if aggregate in {"COUNT", "COUNT_DISTINCT"}:
        if aggregate == "COUNT_DISTINCT":
            return Decimal(len({formula.to_text(value) for value in present}))
        return Decimal(len(present))
    if not present:
        return None
    if aggregate in {"FIRST", "LAST", "NONE"}:
        return present[0] if aggregate != "LAST" else present[-1]
    numbers = [number for number in (_quantity(value) for value in present) if number is not None]
    if not numbers:
        return present[0] if data_type != "number" else None
    if aggregate == "SUM":
        return sum(numbers, Decimal(0))
    if aggregate == "AVG":
        return sum(numbers, Decimal(0)) / Decimal(len(numbers))
    if aggregate == "MIN":
        return min(numbers)
    if aggregate == "MAX":
        return max(numbers)
    if aggregate == "PRODUCT":
        result = Decimal(1)
        for number in numbers:
            result *= number
        return result
    return present[0]


def format_value(value, column: dict) -> str:
    """Display text for one cell. Numbers never lose stored precision."""
    if formula.is_blank(value):
        return ""
    data_type = column.get("data_type", "text")
    prefix = column.get("prefix") or ""
    suffix = column.get("suffix") or ""
    if data_type == "number":
        number = formula.to_decimal(value)
        if number is None:
            return formula.to_text(value)
        places = max(0, min(8, int(column.get("decimals", 2))))
        try:
            scaled = number.quantize(Decimal(1).scaleb(-places))
        except InvalidOperation:
            scaled = number
        text = f"{scaled:,.{places}f}"
        return f"{prefix}{text}{suffix}"
    if data_type == "date":
        moment = value if isinstance(value, (date, datetime)) else formula.to_date(value)
        if moment is None:
            return formula.to_text(value)
        if isinstance(moment, datetime) and (moment.hour or moment.minute):
            return moment.strftime("%Y-%m-%d %H:%M")
        return moment.strftime("%Y-%m-%d")
    if data_type == "boolean":
        if isinstance(value, bool):
            return "Yes" if value else "No"
        text = formula.to_text(value).strip().lower()
        if text in {"1", "true", "yes", "y"}:
            return "Yes"
        if text in {"0", "false", "no", "n"}:
            return "No"
        return formula.to_text(value)
    text = formula.to_text(value)
    return text if len(text) <= MAX_TEXT_CELL else text[:MAX_TEXT_CELL] + "…"


def _sort_key(value):
    if formula.is_blank(value):
        return (2, Decimal(0), "")
    number = formula.to_decimal(value)
    if number is not None:
        return (0, number, "")
    moment = formula.to_date(value)
    if moment is not None:
        return (0, Decimal(moment.toordinal()), "")
    return (1, Decimal(0), formula.to_text(value).lower())


# ---------------------------------------------------------------------------
# Loading rows
# ---------------------------------------------------------------------------


class _FieldRef:
    __slots__ = ("source_kind", "column_name", "related_table", "related_key_column")

    def __init__(self, source_kind: str, column_name: str, related_table: str = "", related_key_column: str = ""):
        self.source_kind = source_kind
        self.column_name = column_name
        self.related_table = related_table
        self.related_key_column = related_key_column

    @property
    def signature(self) -> tuple:
        return (self.source_kind, self.column_name, self.related_table, self.related_key_column)

    @property
    def alias(self) -> str:
        if self.source_kind == "RELATED":
            return f"r__{self.related_key_column}__{self.column_name}"
        return f"b__{self.column_name}"


def _field_of(item: dict) -> _FieldRef:
    # Report columns carry `kind` (DATA/RELATED/CALCULATED); filters and
    # conditions carry `source_kind`. Both resolve to the same field reference.
    kind = str(item.get("source_kind") or item.get("kind") or "DATA").upper()
    return _FieldRef(
        kind,
        item.get("column_name", ""),
        item.get("related_table", ""),
        item.get("related_key_column", ""),
    )


def _collect_fields(catalog, design: dict) -> dict[tuple, _FieldRef]:
    fields: dict[tuple, _FieldRef] = {}

    def add(item: dict):
        ref = _field_of(item)
        fields.setdefault(ref.signature, ref)

    for column in design["columns"]:
        if column["kind"] in {"DATA", "RELATED"}:
            add(column)
        for condition in column["conditions"]:
            add(condition)
    for item in design["filters"]:
        add(item)
    for item in design["runtime_filters"]:
        add(item)
    if design["date_basis"] == "COLUMN" and design["date_column"]:
        add({"source_kind": "DATA", "column_name": design["date_column"]})
    return fields


def _build_statement(catalog, design: dict, organization_id: str, fields: dict, params: dict):
    base = catalog[design["source_table"]]
    # One alias instance per relation: a second alias with the same name would
    # become a second FROM entry and make every selected column ambiguous.
    aliases = {
        key: base.relations[key].parent_table.alias(f"rel_{key}")
        for ref in fields.values() if ref.source_kind == "RELATED"
        for key in [ref.related_key_column]
    }
    statement = select()
    selected = []
    for ref in fields.values():
        if ref.source_kind == "DATA":
            selected.append(base.table.c[ref.column_name].label(ref.alias))
        else:
            selected.append(aliases[ref.related_key_column].c[ref.column_name].label(ref.alias))
    statement = statement.add_columns(*selected)
    statement = statement.select_from(base.table)
    joined: set[str] = set()
    for ref in fields.values():
        if ref.source_kind != "RELATED" or ref.related_key_column in joined:
            continue
        relation = base.relations[ref.related_key_column]
        alias = aliases[ref.related_key_column]
        condition = base.table.c[relation.key_column] == alias.c[relation.parent_pk]
        scope_condition = relation_scope_condition(relation, alias, organization_id)
        if scope_condition is not None:
            # A parent row outside this workspace is treated as missing, never as another tenant's value.
            condition = and_(condition, scope_condition)
        statement = statement.outerjoin(alias, condition)
        joined.add(ref.related_key_column)
    statement = statement.where(base.scope(organization_id))

    # Push the date range down when the column really stores dates.
    date_field = None
    if design["date_basis"] == "COLUMN" and design["date_column"]:
        date_field = _FieldRef("DATA", design["date_column"])
    elif design["date_basis"] == "CREATED_AT":
        date_field = _FieldRef("DATA", "created_at")
    elif design["date_basis"] == "UPDATED_AT":
        date_field = _FieldRef("DATA", "updated_at")
    pushed = False
    if date_field is not None and date_field.signature in fields:
        column = base.columns.get(date_field.column_name)
        start, end = params.get("date_from"), params.get("date_to")
        column_type = column.type if column is not None else None
        # Only real date columns are filtered in SQL; a text date is filtered after
        # loading so the comparison uses the same parser as the rest of the engine.
        if column is not None and isinstance(column_type, (SADateTime, SADate)):
            if start:
                if isinstance(column_type, SADateTime):
                    statement = statement.where(base.table.c[column.name] >= datetime.combine(start, datetime_time.min))
                else:
                    statement = statement.where(base.table.c[column.name] >= start)
                pushed = True
            if end:
                if isinstance(column_type, SADateTime):
                    statement = statement.where(base.table.c[column.name] < datetime.combine(end + timedelta(days=1), datetime_time.min))
                else:
                    statement = statement.where(base.table.c[column.name] <= end)
                pushed = True
    if base.primary_key:
        statement = statement.order_by(*(base.table.c[name] for name in base.primary_key))
    return statement, date_field, pushed


def _load_rows(db: Session, statement, fields: dict, limit: int) -> tuple[list[dict], bool]:
    rows: list[dict] = []
    aliases = {ref.alias: ref.signature for ref in fields.values()}
    result = db.execute(statement, execution_options={"yield_per": 1000})
    truncated = False
    for record in result:
        if len(rows) >= limit:
            truncated = True
            break
        mapping = record._mapping
        rows.append({aliases[key]: mapping[key] for key in aliases})
    return rows, truncated


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _parse_params(design: dict, raw: dict) -> dict:
    params = {
        "date_from": None,
        "date_to": None,
        "values": {},
        "search": str((raw or {}).get("search") or "").strip()[:120],
        "page": 1,
        "page_size": design["page_size"],
    }
    date_from = (raw or {}).get("date_from")
    date_to = (raw or {}).get("date_to")
    if date_from:
        parsed = formula.to_date(date_from)
        if parsed is None:
            raise ReportError("The start of the date range is not a valid date.")
        params["date_from"] = parsed
    if date_to:
        parsed = formula.to_date(date_to)
        if parsed is None:
            raise ReportError("The end of the date range is not a valid date.")
        params["date_to"] = parsed
    if params["date_from"] and params["date_to"] and params["date_from"] > params["date_to"]:
        raise ReportError("The date range starts after it ends.")
    values = (raw or {}).get("filters") or {}
    if not isinstance(values, dict):
        raise ReportError("The filter answers could not be read.")
    for item in design["runtime_filters"]:
        value = values.get(item["key"], item["default_value"])
        text = "" if value is None else str(value).strip()
        if item["required"] and not text:
            raise ReportError(f"Answer “{item['label']}” before running this report.")
        params["values"][item["key"]] = text[:500]
    try:
        params["page"] = max(1, int(((raw or {}).get("page") or 1)))
        requested = int(((raw or {}).get("page_size") or design["page_size"]))
        params["page_size"] = max(10, min(MAX_PAGE_SIZE, requested))
    except (TypeError, ValueError):
        params["page"], params["page_size"] = 1, design["page_size"]
    params["all_rows"] = bool((raw or {}).get("all_rows"))
    return params


def _calculation_order(columns: list[dict]) -> list[str]:
    calculated = {column["key"]: column for column in columns if column["kind"] == "CALCULATED"}
    order: list[str] = []
    visited: dict[str, int] = {}

    def visit(key: str):
        if visited.get(key) == 2:
            return
        if visited.get(key) == 1:
            return  # cycle already reported by validation
        visited[key] = 1
        for dependency in formula.referenced_columns(calculated[key]["formula"]):
            if dependency in calculated:
                visit(dependency)
        visited[key] = 2
        order.append(key)

    for key in calculated:
        visit(key)
    return order


def run_report(db: Session, design: dict, raw_params: dict, organization_id: str) -> dict:
    started = time.monotonic()
    deadline = started + TIME_BUDGET_SECONDS
    catalog = build_catalog(db.get_bind())
    if design["source_table"] not in catalog:
        raise ReportError("The table this report reads from is no longer available in this workspace.", 409)
    params = _parse_params(design, raw_params or {})
    fields = _collect_fields(catalog, design)
    statement, date_field, pushed = _build_statement(catalog, design, organization_id, fields, params)
    rows, truncated = _load_rows(db, statement, fields, SCAN_CAP + 1)
    warnings: list[str] = []
    if len(rows) > SCAN_CAP:
        rows = rows[:SCAN_CAP]
        truncated = True
    if truncated:
        warnings.append(
            f"Only the first {SCAN_CAP:,} matching rows were read. Narrow the date range or filters to see the rest."
        )
    stats = {
        "scanned": len(rows),
        "excluded_by_date": 0,
        "calculation_errors": 0,
        "matched": 0,
        "truncated": truncated,
        "elapsed_ms": 0,
    }

    # Date filter (post-filter handles text dates and is a no-op when pushed down)
    if date_field is not None and date_field.signature in fields:
        kept = []
        for row in rows:
            value = row.get(date_field.signature)
            moment = value if isinstance(value, (date, datetime)) else formula.to_date(value)
            if isinstance(moment, datetime):
                moment = moment.date()
            if params["date_from"] and (moment is None or moment < params["date_from"]):
                stats["excluded_by_date"] += 1
                continue
            if params["date_to"] and (moment is None or moment > params["date_to"]):
                stats["excluded_by_date"] += 1
                continue
            kept.append(row)
        rows = kept
    if stats["excluded_by_date"]:
        warnings.append(
            f"{stats['excluded_by_date']:,} row(s) were outside the selected date range and were left out."
        )

    # Comparison rules blank a measure for non-matching rows (the row stays).
    # Blanking is tracked per column key, never per stored field: two columns may
    # read the same field, one with a comparison rule and one without.
    for column in design["columns"]:
        conditions = column["conditions"]
        if not conditions:
            continue
        for row in rows:
            results = [
                _matches(condition["operator"], row.get(_field_of(condition).signature), condition["value"], condition["value2"])
                for condition in conditions
            ]
            passed = all(results) if column["condition_logic"] == "AND" else any(results)
            if not passed:
                row.setdefault("__blank__", set()).add(column["key"])

    # Assemble values per report column, then run calculated columns in order.
    order = _calculation_order(design["columns"])
    calculated_by_key = {column["key"]: column for column in design["columns"] if column["kind"] == "CALCULATED"}
    for row in rows:
        values: dict = {}
        for column in design["columns"]:
            if column["kind"] == "CALCULATED":
                continue
            values[column["key"]] = None if column["key"] in row.get("__blank__", ()) else row.get(
                _FieldRef(column["kind"], column["column_name"], column["related_table"], column["related_key_column"]).signature
            )
        for key in order:
            column = calculated_by_key[key]
            try:
                values[key] = formula.evaluate(formula.parse_formula(column["formula"]), values)
            except (formula.EvaluationError, formula.FormulaError):
                values[key] = None
                stats["calculation_errors"] += 1
        row["__values"] = values
        if time.monotonic() > deadline:
            raise ReportError(
                "This report took longer than 25 seconds to calculate. Narrow the date range or add filters."
            )

    # Fixed + run-time filters, then quick search.
    def keep(row) -> bool:
        outcomes = []
        for item in design["filters"]:
            outcomes.append(_matches(item["operator"], row.get(_field_of(item).signature), item["value"], item["value2"]))
        if outcomes:
            passed = all(outcomes) if design["filter_logic"] == "AND" else any(outcomes)
            if not passed:
                return False
        for item in design["runtime_filters"]:
            answer = params["values"].get(item["key"], "")
            if not answer:
                continue
            if not _matches(item["operator"], row.get(_field_of(item).signature), answer, answer):
                return False
        if params["search"]:
            needle = params["search"].lower()
            haystacks = [
                formula.to_text(row["__values"].get(column["key"])).lower()
                for column in design["columns"] if not column["hidden"]
            ]
            if not any(needle in haystack for haystack in haystacks):
                return False
        return True

    rows = [row for row in rows if keep(row)]
    stats["matched"] = len(rows)

    visible = [column for column in design["columns"] if not column["hidden"]]
    total_row = _totals(design, visible, rows) if design["show_totals"] else None
    matrix_columns: list[str] = []
    if design["report_type"] == "MATRIX":
        output_rows, matrix_columns, matrix_totals, warnings_extra = _matrix_rows(design, rows)
        warnings.extend(warnings_extra)
        total_row = matrix_totals if design["matrix_show_totals"] else None
    elif any(item["kind"] == "group" for item in design["groupings"]):
        output_rows = _grouped_rows(design, rows)
    else:
        output_rows = _detail_rows(design, rows)

    _sort_output(design, output_rows)
    total_count = len(output_rows)
    page_size = total_count if params["all_rows"] else params["page_size"]
    page = 1 if params["all_rows"] else params["page"]
    pages = max(1, -(-total_count // page_size)) if page_size else 1
    window = output_rows if params["all_rows"] else output_rows[(page - 1) * page_size: (page - 1) * page_size + page_size]
    if page > pages and total_count:
        page = pages
        window = output_rows[(page - 1) * page_size: (page - 1) * page_size + page_size]

    output_columns = [
        {
            "key": column["key"], "label": column["label"], "data_type": column["data_type"],
            "align": "right" if column["data_type"] == "number" else "left",
            "decimals": column["decimals"], "width": column["width"],
        }
        for column in visible
    ]
    if design["report_type"] == "MATRIX":
        value_column = next(
            (column for column in design["columns"] if column["key"] == design["matrix_value_key"]), None
        )
        cell_decimals = 0 if design["matrix_aggregate"] in {"COUNT", "COUNT_DISTINCT"} else int(
            (value_column or {}).get("decimals", 2)
        )
        output_columns = [
            {
                "key": item["key"], "label": item["label"], "data_type": item["data_type"],
                "align": "right" if item["data_type"] == "number" else "left", "decimals": 0, "width": 0,
            }
            for item in design["matrix_row_columns"]
        ] + [
            {"key": f"m__{index}", "label": label, "data_type": "number", "align": "right", "decimals": cell_decimals, "width": 0}
            for index, label in enumerate(matrix_columns)
        ] + (
            [{"key": "m__total", "label": "Total", "data_type": "number", "align": "right", "decimals": cell_decimals, "width": 0}]
            if design["matrix_show_totals"] else []
        )
    formatted_rows = [
        {item["key"]: _cell_value(row, item) for item in output_columns} for row in window
    ]
    stats["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return {
        "report_type": design["report_type"],
        "columns": output_columns,
        "rows": formatted_rows,
        "totals": _format_total(total_row, output_columns),
        "grouped": any(item["kind"] == "group" for item in design["groupings"]),
        "matrix": design["report_type"] == "MATRIX",
        "total_rows": total_count,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "warnings": warnings,
        "stats": stats,
        "date_basis": _date_basis_label(design),
        "date_from": params["date_from"].isoformat() if params["date_from"] else "",
        "date_to": params["date_to"].isoformat() if params["date_to"] else "",
        "notes": describe_definition(design),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _cell_value(row: dict, column: dict) -> str:
    return format_value(row.get(column["key"]), column)


def _format_total(total: dict | None, columns: list[dict]) -> dict | None:
    if total is None:
        return None
    return {
        column["key"]: format_value(total.get(column["key"]), column)
        for column in columns
        if column["key"] in total
    }


def _totals(design: dict, visible: list[dict], rows: list[dict]) -> dict:
    totals: dict = {}
    for column in visible:
        if column["data_type"] != "number" or not column["show_total"]:
            continue
        aggregate = column["aggregate"] if column["aggregate"] not in {"NONE", "FIRST", "LAST", "COUNT_DISTINCT"} else "SUM"
        values = [row["__values"].get(column["key"]) for row in rows]
        totals[column["key"]] = aggregate_values(values, aggregate, "number")
    return totals


def _detail_rows(design: dict, rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        output.append({column["key"]: row["__values"].get(column["key"]) for column in design["columns"]})
    return output


def _grouped_rows(design: dict, rows: list[dict]) -> list[dict]:
    grouping = [item for item in design["groupings"] if item["kind"] == "group"]
    columns = design["columns"]
    buckets: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for row in rows:
        key = tuple(
            _bucket(row["__values"].get(item["column_key"]), item["bucket"]) for item in grouping
        )
        buckets.setdefault(key, []).append(row)
    output = []
    for key, members in buckets.items():
        record: dict = {}
        for index, item in enumerate(grouping):
            column = next(column for column in columns if column["key"] == item["column_key"])
            value = key[index]
            record[item["column_key"]] = bucket_label(value, item["bucket"]) if item["bucket"] != "VALUE" else value
            if item["bucket"] != "VALUE":
                record[f"__sort__{column['key']}"] = value
        for column in columns:
            if column["key"] in {item["column_key"] for item in grouping}:
                continue
            aggregate = column["aggregate"] if column["aggregate"] != "NONE" else ("SUM" if column["data_type"] == "number" else "FIRST")
            record[column["key"]] = aggregate_values(
                [row["__values"].get(column["key"]) for row in members], aggregate, column["data_type"]
            )
        output.append(record)
    return output


def _matrix_rows(design: dict, rows: list[dict]) -> tuple[list[dict], list[str], dict | None, list[str]]:
    warnings: list[str] = []
    row_items = [item for item in design["groupings"] if item["kind"] == "matrix_row"]
    column_item = next(item for item in design["groupings"] if item["kind"] == "matrix_column")
    value_key = design["matrix_value_key"]
    labels: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw = _bucket(row["__values"].get(column_item["column_key"]), column_item["bucket"])
        label = bucket_label(raw, column_item["bucket"])
        if label not in seen:
            seen.add(label)
            labels.append(label)
    labels.sort()
    overflow = len(labels) > MAX_MATRIX_COLUMNS
    kept = labels[:MAX_MATRIX_COLUMNS]
    if overflow:
        kept = kept[: MAX_MATRIX_COLUMNS - 1]
        warnings.append(
            f"The matrix has {len(labels)} columns; the first {MAX_MATRIX_COLUMNS - 1} are shown individually and the rest are "
            "combined into “Other” so the totals still add up. Narrow the date range to see them separately."
        )

    def cell_label(row) -> str:
        label = bucket_label(_bucket(row["__values"].get(column_item["column_key"]), column_item["bucket"]), column_item["bucket"])
        return label if label in kept else "Other"

    row_columns = []
    for index, item in enumerate(row_items):
        column = next(column for column in design["columns"] if column["key"] == item["column_key"])
        row_columns.append({
            "key": f"r__{index}", "label": column["label"], "data_type": column["data_type"],
            "source_key": column["key"], "bucket": item["bucket"],
        })
    design["matrix_row_columns"] = row_columns

    buckets: "OrderedDict[tuple, dict]" = OrderedDict()
    column_totals: dict[str, list] = {label: [] for label in kept}
    grand_totals: list = []
    for row in rows:
        key = tuple(_bucket(row["__values"].get(item["column_key"]), item["bucket"]) for item in row_items)
        entry = buckets.setdefault(key, {"__cells__": {}, "__total__": [], "__labels__": []})
        if not entry["__labels__"]:
            entry["__labels__"] = [
                bucket_label(value, item["bucket"]) if item["bucket"] != "VALUE" else value
                for item, value in zip(row_items, key)
            ]
        label = cell_label(row)
        value = row["__values"].get(value_key)
        entry["__cells__"].setdefault(label, []).append(value)
        entry["__total__"].append(value)
        column_totals.setdefault(label, []).append(value)
        grand_totals.append(value)

    output = []
    for key, entry in buckets.items():
        record = {row_columns[index]["key"]: value for index, value in enumerate(entry["__labels__"])}
        grand: list = []
        for index, label in enumerate(kept):
            values = entry["__cells__"].get(label, [])
            record[f"m__{index}"] = _matrix_cell(values, design["matrix_aggregate"])
            grand.extend(values)
        if overflow:
            values = [value for label, collection in entry["__cells__"].items() if label == "Other" for value in collection]
            record[f"m__{MAX_MATRIX_COLUMNS - 1}"] = _matrix_cell(values, design["matrix_aggregate"])
            grand.extend(values)
        record["m__total"] = _matrix_cell(grand, design["matrix_aggregate"])
        output.append(record)

    totals: dict | None = None
    if design["matrix_show_totals"]:
        totals = {}
        for index, label in enumerate(kept):
            totals[f"m__{index}"] = _matrix_cell(column_totals.get(label, []), design["matrix_aggregate"])
        if overflow:
            totals[f"m__{MAX_MATRIX_COLUMNS - 1}"] = _matrix_cell(
                column_totals.get("Other", []), design["matrix_aggregate"]
            )
        totals["m__total"] = _matrix_cell(grand_totals, design["matrix_aggregate"])
    design["matrix_labels"] = kept
    return output, kept, totals, warnings


def _matrix_cell(values: list, aggregate: str):
    if not values:
        return None
    return aggregate_values(values, aggregate if aggregate != "NONE" else "SUM", "number")


def _sort_output(design: dict, rows: list[dict]) -> None:
    if not rows:
        return
    for sort in reversed(design["sorts"]):
        key = sort["column_key"]
        reverse = sort["direction"] == "DESC"
        rows.sort(key=lambda row, key=key: _sort_key(row.get(f"__sort__{key}", row.get(key))), reverse=reverse)
    if not design["sorts"]:
        # Deterministic order even without an explicit sort.
        visible_keys = [column["key"] for column in design["columns"] if not column["hidden"]]
        rows.sort(key=lambda row: tuple(_sort_key(row.get(key)) for key in visible_keys[:3]))


def _date_basis_label(design: dict) -> str:
    if design["date_basis"] == "COLUMN":
        return humanize(design["date_column"])
    if design["date_basis"] == "CREATED_AT":
        return "Created date"
    if design["date_basis"] == "UPDATED_AT":
        return "Last updated date"
    return "No date range"


def describe_definition(design: dict) -> list[str]:
    """Plain-English notes for the viewer's “About this report” panel."""
    notes: list[str] = [f"Data source: {table_label(design['source_table'])}."]
    if design["date_basis"] != "NONE":
        notes.append(f"The From–To range filters on {_date_basis_label(design).lower()}.")
    calculations = [column for column in design["columns"] if column["kind"] == "CALCULATED"]
    if calculations:
        notes.append("Calculated columns: " + "; ".join(f"{column['label']} = {column['formula']}" for column in calculations))
    comparisons = [column for column in design["columns"] if column["conditions"]]
    for column in comparisons:
        rules = ", ".join(
            f"{humanize(condition['column_name'])} {condition['operator'].replace('_', ' ')} "
            f"“{condition['value'] or '(blank)'}”"
            + (f" and “{condition['value2']}”" if condition["operator"] == "between" else "")
            for condition in column["conditions"]
        )
        notes.append(
            f"{column['label']} only counts rows where {rules} ({column['condition_logic']} of the rules). "
            "Other rows still appear in the report with this measure left blank."
        )
    grouping = [item for item in design["groupings"] if item["kind"] == "group"]
    if grouping:
        notes.append(
            "Grouped by "
            + ", ".join(
                f"{next(column['label'] for column in design['columns'] if column['key'] == item['column_key'])}"
                + (f" ({item['bucket'].lower()})" if item["bucket"] != "VALUE" else "")
                for item in grouping
            )
            + "."
        )
    if design["report_type"] == "MATRIX":
        notes.append("Matrix report: each cell summarises the chosen value for one matrix row and column.")
    if design["filters"]:
        notes.append(
            "Always applies "
            + " and ".join(
                f"{item['label']} {item['operator'].replace('_', ' ')} “{item['value']}”" for item in design["filters"]
            )
            + "."
        )
    return notes


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def export_csv(design: dict, result: dict, title: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    # Every cell — headers included, because a column label is user-defined text —
    # is passed through the shared neutraliser. A spreadsheet must treat a stored
    # value beginning with =, +, -, @ or a control/space prefix as data, not as a
    # formula it should execute on open.
    writer.writerow([safe_csv_cell(column["label"]) for column in result["columns"]])
    for row in result["rows"]:
        writer.writerow([safe_csv_cell(row.get(column["key"], "")) for column in result["columns"]])
    totals = result.get("totals")
    if totals:
        writer.writerow([safe_csv_cell(totals.get(column["key"], "")) for column in result["columns"]])
    text = buffer.getvalue()
    # Excel reads a UTF-8 BOM as UTF-8 and keeps non-ASCII labels intact.
    return ("\ufeff" + text).encode("utf-8")


# ---------------------------------------------------------------------------
# Starter designs
# ---------------------------------------------------------------------------


def _column(key, label, column_name, *, data_type="text", aggregate="NONE", show_total=False,
            decimals=2, prefix="", suffix="", related_key="", related_table="", hidden=False, kind="DATA",
            formula=""):
    return {
        "key": key, "label": label, "kind": kind, "column_name": column_name,
        "related_table": related_table, "related_key_column": related_key, "formula": formula,
        "data_type": data_type, "decimals": decimals, "prefix": prefix, "suffix": suffix,
        "aggregate": aggregate, "show_total": show_total, "hidden": hidden,
        "condition_logic": "AND", "width": 0, "conditions": [],
    }


def _blank_design(name, description, table, date_column, columns, **extra) -> dict:
    design = empty_definition()
    design.update({
        "name": name, "description": description, "source_table": table,
        "date_basis": "COLUMN" if date_column else "NONE", "date_column": date_column or "",
        "columns": columns,
    })
    design.update(extra)
    return design


def starter_designs() -> list[dict]:
    """Ready-made reports a workspace can copy in one click."""
    return [
        _blank_design(
            "Daily cost by well",
            "Total, USD, NPT and UPA cost per well for the selected dates, from the daily cost register.",
            "daily_cost_entries", "cost_date",
            [
                _column("well", "Well", "well_name_snapshot"),
                _column("cost_date", "Cost Date", "cost_date", data_type="date"),
                _column("total_cost", "Total Cost", "total_cost", data_type="number", aggregate="SUM", show_total=True),
                _column("total_cost_usd", "Total Cost (USD)", "total_cost_usd", data_type="number", aggregate="SUM", show_total=True),
                _column("npt_usd", "NPT (USD)", "npt_total_usd", data_type="number", aggregate="SUM", show_total=True),
                _column("upa_usd", "UPA (USD)", "upa_total_usd", data_type="number", aggregate="SUM", show_total=True),
            ],
            groupings=[{"kind": "group", "column_key": "well", "bucket": "VALUE"}],
            sorts=[{"column_key": "total_cost_usd", "direction": "DESC"}],
        ),
        _blank_design(
            "Monthly cost trend",
            "Monthly totals of the daily cost register, ready for trend analysis.",
            "daily_cost_entries", "cost_date",
            [
                _column("month", "Month", "cost_date", data_type="date"),
                _column("total_cost_usd", "Total Cost (USD)", "total_cost_usd", data_type="number", aggregate="SUM", show_total=True),
                _column("sheets", "Sheets", "id", data_type="text", aggregate="COUNT", show_total=True, decimals=0),
            ],
            groupings=[{"kind": "group", "column_key": "month", "bucket": "MONTH"}],
            sorts=[{"column_key": "month", "direction": "ASC"}],
        ),
        _blank_design(
            "Service-wise cost",
            "Every daily service line with its well, service, vendor and USD amount.",
            "daily_cost_service_lines", "",
            [
                _column("service", "Service", "service_name_snapshot"),
                _column("vendor", "Vendor", "vendor_name_snapshot"),
                _column("activity", "Activity", "activity_name_snapshot"),
                _column("quantity", "Quantity", "quantity", data_type="number", aggregate="SUM", show_total=True, decimals=2),
                _column("usd", "Amount (USD)", "usd_amount", data_type="number", aggregate="SUM", show_total=True, decimals=2),
            ],
            groupings=[{"kind": "group", "column_key": "service", "bucket": "VALUE"}],
            sorts=[{"column_key": "usd", "direction": "DESC"}],
        ),
        _blank_design(
            "AFE register",
            "AFE code, well, type, status and standard currency.",
            "afes", "created_at",
            [
                _column("afe_code", "AFE Code", "afe_code"),
                _column("afe_name", "AFE Name", "afe_name"),
                _column("afe_type", "Type", "afe_type"),
                _column("scope", "Scope", "configuration_scope"),
                _column("status", "Status", "status"),
                _column("currency", "Currency", "standard_currency"),
                _column("created", "Created", "created_at", data_type="date"),
            ],
            sorts=[{"column_key": "created", "direction": "DESC"}],
        ),
        _blank_design(
            "Fuel consumption by company",
            "Litres recorded against each fuel company, from the fuel cost register.",
            "fuel_cost_company_lines", "",
            [
                _column("company", "Fuel Company", "company_name_snapshot"),
                _column("category", "Category", "category_name_snapshot"),
                _column("litres", "Litres", "litres", data_type="number", aggregate="SUM", show_total=True, decimals=2),
                _column("lines", "Lines", "id", data_type="text", aggregate="COUNT", show_total=True, decimals=0),
            ],
            groupings=[{"kind": "group", "column_key": "company", "bucket": "VALUE"}],
            sorts=[{"column_key": "litres", "direction": "DESC"}],
        ),
        _blank_design(
            "Well register",
            "Every well with its rig, location, status and spud date.",
            "wells", "created_at",
            [
                _column("code", "Well Code", "well_code"),
                _column("name", "Well Name", "well_name"),
                _column("location", "Location", "well_location"),
                _column("status", "Status", "status"),
                _column("drilling_spud", "Drilling Spud", "drilling_spud_at", data_type="date"),
                _column("completion_spud", "Completion Spud", "completion_spud_at", data_type="date"),
            ],
            sorts=[{"column_key": "code", "direction": "ASC"}],
        ),
        _blank_design(
            "Well cost comparison (AFE vs actual)",
            "Planned AFE estimate against daily cost actuals per well, with a variance column.",
            "daily_cost_entries", "cost_date",
            [
                _column("well", "Well", "well_name_snapshot"),
                _column("afe", "AFE", "afe_code_snapshot"),
                _column("actual", "Actual (USD)", "total_cost_usd", data_type="number", aggregate="SUM", show_total=True),
                _column("npt", "NPT (USD)", "npt_total_usd", data_type="number", aggregate="SUM", show_total=True),
                _column("variance", "Share of cost", "", kind="CALCULATED", formula="PCT([actual], [actual] + [npt])",
                        data_type="number", aggregate="AVG", suffix=" %"),
            ],
            groupings=[{"kind": "group", "column_key": "well", "bucket": "VALUE"}],
            sorts=[{"column_key": "actual", "direction": "DESC"}],
        ),
    ]
