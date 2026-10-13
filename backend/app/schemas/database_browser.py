from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TableSummary(BaseModel):
    name: str
    group: str
    column_count: int
    row_count: int
    scope: str
    primary_key: list[str]
    has_timestamps: bool


class TableCatalogue(BaseModel):
    items: list[TableSummary]
    total_tables: int
    total_rows: int
    excluded_tables: int
    hidden_columns: int


class ColumnInfo(BaseModel):
    position: int
    name: str
    data_type: str
    kind: Literal["text", "number", "date", "boolean"]
    nullable: bool
    primary_key: bool
    unique: bool
    indexed: bool
    foreign_key: str
    default: str
    max_length: int | None


class IndexInfo(BaseModel):
    name: str
    columns: str
    unique: bool


class TableStructure(BaseModel):
    name: str
    group: str
    scope: str
    row_count: int
    columns: list[ColumnInfo]
    indexes: list[IndexInfo]
    hidden_columns: int


class TableRows(BaseModel):
    name: str
    columns: list[str]
    primary_key: list[str]
    items: list[dict[str, Any]]
    shown: int
    total: int
    truncated: bool
    preview_limit: int


class DatabaseExportAudit(_Strict):
    scope: Literal["rows", "structure", "catalogue"]
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=10_000_000)
    table: str = Field(default="", max_length=120)
