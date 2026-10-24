"""Strict API contracts for the NDT Inspection register."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.precision import Decimal10

Scope = Literal["drilling", "completion"]
MAX_LINES = 500
MAX_IMPORT_ROWS = 2000
MAX_QUANTITY = Decimal("1000000000000")


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NdtLineIn(_Strict):
    description: str = Field(min_length=1, max_length=300)
    quantity_received: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_QUANTITY)
    quantity_consumed: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_QUANTITY)
    quantity_backloaded_good: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_QUANTITY)
    quantity_backloaded_bad: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_QUANTITY)
    remarks: str = Field(default="", max_length=500)

    @field_validator("description", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class NdtBulkCreate(_Strict):
    rig_id: str = Field(min_length=1, max_length=36)
    well_id: str = Field(min_length=1, max_length=36)
    scope: Scope
    lines: list[NdtLineIn] = Field(min_length=1, max_length=MAX_LINES)

    @field_validator("rig_id", "well_id", mode="before")
    @classmethod
    def trim_ids(cls, value: Any) -> Any:
        return _trim(value)


class NdtUpdate(NdtLineIn):
    rig_id: str = Field(min_length=1, max_length=36)
    well_id: str = Field(min_length=1, max_length=36)
    scope: Scope


class NdtIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=MAX_LINES)


class NdtBulkActionOut(_Strict):
    affected_count: int


class NdtEntryOut(_Strict):
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    well_id: str
    well_code: str
    well_name: str
    scope: Scope
    description: str
    quantity_received: Decimal
    quantity_consumed: Decimal
    quantity_backloaded_good: Decimal
    quantity_backloaded_bad: Decimal
    remarks: str
    is_deleted: bool
    deleted_at: datetime | None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class NdtRigOption(_Strict):
    id: str
    rig_code: str
    rig_name: str
    display_name: str


class NdtWellOption(_Strict):
    id: str
    rig_id: str
    well_code: str
    well_name: str
    drilling_available: bool
    completion_available: bool
    display_name: str


class NdtReference(_Strict):
    rigs: list[NdtRigOption]
    wells: list[NdtWellOption]


class NdtImportRow(_Strict):
    rig_code: str = Field(min_length=1, max_length=50)
    well_code: str = Field(min_length=1, max_length=50)
    scope: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=300)
    quantity_received: Any = 0
    quantity_consumed: Any = 0
    quantity_backloaded_good: Any = 0
    quantity_backloaded_bad: Any = 0
    remarks: str = Field(default="", max_length=500)

    @field_validator("rig_code", "well_code", "scope", "description", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class NdtImportRequest(_Strict):
    rows: list[NdtImportRow] = Field(min_length=1, max_length=MAX_IMPORT_ROWS)


class NdtImportOut(_Strict):
    created_count: int
    errors: list[str]


class NdtExportAudit(_Strict):
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0)
    include_deleted: bool = False
