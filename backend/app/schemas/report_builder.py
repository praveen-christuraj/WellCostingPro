"""Typed API contracts for Report Builder and Custom Reports.

A design is sent and returned as a structured payload; the stored shape is
column-wise (see ``app/models/report_builder.py``). Run results are already
display-formatted strings plus the raw totals the caller may export.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReportType = Literal["TABULAR", "MATRIX"]
ColumnKind = Literal["DATA", "RELATED", "CALCULATED"]
DataType = Literal["text", "number", "date", "boolean"]
Aggregate = Literal["NONE", "SUM", "AVG", "COUNT", "COUNT_DISTINCT", "MIN", "MAX", "PRODUCT", "FIRST", "LAST"]
Bucket = Literal["VALUE", "DAY", "WEEK", "MONTH", "QUARTER", "YEAR"]
Operator = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_contains", "starts_with",
    "ends_with", "in", "not_in", "between", "is_blank", "is_not_blank",
]
RuntimeType = Literal["text", "number", "date", "boolean", "select"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportConditionIn(_Strict):
    source_kind: Literal["DATA", "RELATED"] = "DATA"
    column_name: str = Field(default="", max_length=120)
    related_table: str = Field(default="", max_length=120)
    related_key_column: str = Field(default="", max_length=120)
    operator: Operator = "eq"
    value: str = Field(default="", max_length=500)
    value2: str = Field(default="", max_length=500)


class ReportColumnIn(_Strict):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=160)
    kind: ColumnKind = "DATA"
    column_name: str = Field(default="", max_length=120)
    related_table: str = Field(default="", max_length=120)
    related_key_column: str = Field(default="", max_length=120)
    formula: str = Field(default="", max_length=2000)
    data_type: DataType = "text"
    decimals: int = Field(default=2, ge=0, le=8)
    prefix: str = Field(default="", max_length=20)
    suffix: str = Field(default="", max_length=20)
    aggregate: Aggregate = "NONE"
    show_total: bool = False
    hidden: bool = False
    condition_logic: Literal["AND", "OR"] = "AND"
    width: int = Field(default=0, ge=0, le=2000)
    conditions: list[ReportConditionIn] = Field(default_factory=list)


class ReportFilterIn(_Strict):
    label: str = Field(default="", max_length=160)
    source_kind: Literal["DATA", "RELATED"] = "DATA"
    column_name: str = Field(default="", max_length=120)
    related_table: str = Field(default="", max_length=120)
    related_key_column: str = Field(default="", max_length=120)
    operator: Operator = "eq"
    value: str = Field(default="", max_length=500)
    value2: str = Field(default="", max_length=500)


class ReportRuntimeFilterIn(_Strict):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=160)
    filter_type: RuntimeType = "text"
    source_kind: Literal["DATA", "RELATED"] = "DATA"
    column_name: str = Field(default="", max_length=120)
    related_table: str = Field(default="", max_length=120)
    related_key_column: str = Field(default="", max_length=120)
    operator: Operator = "eq"
    required: bool = False
    default_value: str = Field(default="", max_length=500)
    options: list[str] = Field(default_factory=list)


class ReportGroupingIn(_Strict):
    kind: Literal["group", "matrix_row", "matrix_column"] = "group"
    column_key: str = Field(min_length=1, max_length=80)
    bucket: Bucket = "VALUE"


class ReportSortIn(_Strict):
    column_key: str = Field(min_length=1, max_length=80)
    direction: Literal["ASC", "DESC"] = "ASC"


class ReportGrantIn(_Strict):
    grant_type: Literal["user", "role"]
    user_id: str = Field(default="", max_length=36)
    role_id: str = Field(default="", max_length=36)
    level: Literal["view", "edit"] = "view"


class ReportDefinitionIn(_Strict):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    report_type: ReportType = "TABULAR"
    source_table: str = Field(min_length=1, max_length=120)
    date_basis: Literal["COLUMN", "CREATED_AT", "UPDATED_AT", "NONE"] = "NONE"
    date_column: str = Field(default="", max_length=120)
    filter_logic: Literal["AND", "OR"] = "AND"
    show_totals: bool = True
    page_size: int = Field(default=50, ge=10, le=500)
    empty_text: str = Field(default="", max_length=200)
    matrix_value_key: str = Field(default="", max_length=80)
    matrix_aggregate: Aggregate = "SUM"
    matrix_show_totals: bool = True
    visibility: Literal["private", "internal", "shared"] = "private"
    columns: list[ReportColumnIn] = Field(default_factory=list)
    filters: list[ReportFilterIn] = Field(default_factory=list)
    runtime_filters: list[ReportRuntimeFilterIn] = Field(default_factory=list)
    groupings: list[ReportGroupingIn] = Field(default_factory=list)
    sorts: list[ReportSortIn] = Field(default_factory=list)
    grants: list[ReportGrantIn] = Field(default_factory=list)


class ReportRunIn(_Strict):
    date_from: str = Field(default="", max_length=10)
    date_to: str = Field(default="", max_length=10)
    filters: dict[str, str] = Field(default_factory=dict)
    search: str = Field(default="", max_length=120)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=10, le=500)
    all_rows: bool = False


class ReportGrantOut(BaseModel):
    grant_type: str
    id: str
    level: str
    name: str
    detail: str


class ReportDefinitionOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    version: int
    visibility: str
    report_type: str
    source_table: str
    run_count: int
    last_run_at: datetime | None
    published_at: datetime | None
    created_by_display: str
    updated_by_display: str
    created_at: datetime
    updated_at: datetime
    can_edit: bool
    can_delete: bool
    can_publish: bool
    can_run: bool
    grants: list[ReportGrantOut]
    design: dict[str, Any]


class ReportDefinitionList(BaseModel):
    items: list[ReportDefinitionOut]
    counts: dict[str, int]


class ReportVersionOut(BaseModel):
    id: str
    version: int
    report_name: str
    report_type: str
    source_table: str
    column_count: int
    filter_count: int
    grouping_count: int
    grant_count: int
    status: str
    change_note: str
    changed_by_display: str
    created_at: datetime


class ReportRunColumn(BaseModel):
    key: str
    label: str
    data_type: str
    align: str
    decimals: int
    width: int = 0


class ReportRunOut(BaseModel):
    report_type: str
    columns: list[ReportRunColumn]
    rows: list[dict[str, Any]]
    totals: dict[str, str] | None
    grouped: bool
    matrix: bool
    total_rows: int
    page: int
    page_size: int
    pages: int
    warnings: list[str]
    stats: dict[str, Any]
    date_basis: str
    date_from: str
    date_to: str
    notes: list[str]
    generated_at: str


class ReportPublishIn(_Strict):
    published: bool


class ReportFromStarterIn(_Strict):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=160)


class ReportExportAuditIn(_Strict):
    report_id: str = Field(default="", max_length=36)
    report_name: str = Field(max_length=160)
    format: Literal["csv", "xlsx", "pdf"]
    row_count: int = Field(ge=0, le=10_000_000)


class ReportVersionDetail(BaseModel):
    version: ReportVersionOut
    design: dict[str, Any] | None
