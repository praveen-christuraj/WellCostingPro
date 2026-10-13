"""Contracts for private, reusable service and catalogue-item sets."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CostingSetGroup = Literal["services", "tangibles", "consumables"]
CostingSetItemKind = Literal[
    "service", "tangible", "mud_chemical", "cement_additive", "fuel", "drill_bit",
]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CostingSetItemIn(_Strict):
    item_kind: CostingSetItemKind
    item_id: str = Field(min_length=1, max_length=36)

    @field_validator("item_id", mode="before")
    @classmethod
    def trim_item_id(cls, value: Any) -> Any:
        return _trim(value)


class CostingSetCreate(_Strict):
    name: str = Field(min_length=1, max_length=100)
    item_group: CostingSetGroup
    description: str = Field(default="", max_length=500)
    items: list[CostingSetItemIn] = Field(min_length=1, max_length=500)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("name")
    @classmethod
    def require_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Enter a name for this costing set.")
        return value


class CostingSetUpdate(CostingSetCreate):
    pass


class CostingSetItemOut(_Strict):
    id: str
    item_kind: CostingSetItemKind
    item_id: str
    item_code: str
    item_name: str
    display_name: str
    is_available: bool


class CostingSetOut(_Strict):
    id: str
    name: str
    item_group: CostingSetGroup
    description: str
    item_count: int
    items: list[CostingSetItemOut]
    created_at: datetime
    updated_at: datetime


class CostingSetOptionOut(_Strict):
    item_group: CostingSetGroup
    item_kind: CostingSetItemKind
    item_id: str
    item_code: str
    item_name: str
    display_name: str


class CostingSetImportRow(_Strict):
    """One import row: a set/item membership identified by a master-data code."""

    set_name: str = Field(min_length=1, max_length=100)
    item_group: CostingSetGroup
    item_kind: CostingSetItemKind
    item_code: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)

    @field_validator("set_name", "item_code", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class CostingSetImportRequest(_Strict):
    rows: list[CostingSetImportRow] = Field(min_length=1, max_length=10000)


class CostingSetImportError(_Strict):
    row: int
    set_name: str = ""
    item_code: str = ""
    message: str


class CostingSetImportResult(_Strict):
    created_sets: int
    updated_sets: int
    imported_items: int
    errors: list[CostingSetImportError]


class CostingSetExportAuditIn(_Strict):
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=100000)
