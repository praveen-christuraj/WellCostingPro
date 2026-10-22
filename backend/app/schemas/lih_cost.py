"""Typed API contracts for the LIH Cost Register (Daily Cost Management)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.precision import Decimal10

MAX_UNITS = Decimal("1000000")
MAX_UNIT_COST = Decimal("100000000")
MAX_DIMENSION = Decimal("1000000")
MAX_LINE_COST = Decimal("100000000000")


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LihCostLineIn(_Strict):
    """One manually entered LIH item.

    ``item_description``, ``no_of_units`` and ``unit_cost`` are mandatory. The
    server always recomputes ``total_cost`` as units × unit cost; a client
    supplied total is not accepted. The equipment dimensions and identity
    fields are optional, typed measurements and text.
    """

    item_description: str = Field(min_length=1, max_length=300)
    od_size: Decimal10 | None = Field(default=None, ge=0, le=MAX_DIMENSION)
    id_size: Decimal10 | None = Field(default=None, ge=0, le=MAX_DIMENSION)
    fish_neck_od: Decimal10 | None = Field(default=None, ge=0, le=MAX_DIMENSION)
    fish_neck_length: Decimal10 | None = Field(default=None, ge=0, le=MAX_DIMENSION)
    serial_number: str = Field(default="", max_length=100)
    connection: str = Field(default="", max_length=100)
    length: Decimal10 | None = Field(default=None, ge=0, le=MAX_DIMENSION)
    no_of_units: Decimal10 = Field(gt=0, le=MAX_UNITS)
    unit: str = Field(default="", max_length=50)
    unit_cost: Decimal10 = Field(ge=0, le=MAX_UNIT_COST)
    remarks: str = Field(default="", max_length=500)

    @field_validator(
        "od_size", "id_size", "fish_neck_od", "fish_neck_length", "length", mode="before"
    )
    @classmethod
    def blank_dimensions(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("item_description", "serial_number", "connection", "unit", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class LihCostEntryCreate(_Strict):
    well_id: str = Field(min_length=1, max_length=36)
    rig_id: str = Field(default="", max_length=36)
    afe_id: str = Field(default="", max_length=36)
    cost_date: date
    remarks: str = Field(default="", max_length=1000)

    @field_validator("well_id", "rig_id", "afe_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class LihCostEntryUpdate(_Strict):
    """Edit a LIH day header. Omitted fields keep their stored values."""

    afe_id: str | None = Field(default=None, max_length=36)
    cost_date: date | None = None
    remarks: str | None = Field(default=None, max_length=1000)

    @field_validator("afe_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class LihCostIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=5000)


class LihCostBulkActionOut(BaseModel):
    affected_count: int


class LihCostExportAudit(_Strict):
    module: Literal["register", "deleted", "day", "well-report"]
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=1_000_000)
    well_id: str = Field(default="", max_length=36)
    entry_id: str = Field(default="", max_length=36)
    date_from: date | None = None
    date_to: date | None = None
    include_deleted: bool = False


class LihCostRigOption(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    display_name: str


class LihCostWellOption(BaseModel):
    id: str
    rig_id: str
    well_code: str
    well_name: str
    status: str
    config_status: str
    display_name: str


class LihCostAfeOption(BaseModel):
    id: str
    well_id: str
    afe_code: str
    afe_name: str
    status: str
    configuration_scope: str = ""
    standard_currency: str
    total_cost: Decimal = Decimal("0")
    display_name: str


class LihCostUomOption(BaseModel):
    code: str
    name: str
    symbol: str
    display_name: str


class LihCostReference(BaseModel):
    rigs: list[LihCostRigOption]
    wells: list[LihCostWellOption]
    afes: list[LihCostAfeOption]
    uoms: list[LihCostUomOption]
    default_currency: str = ""


class LihCostLineOut(BaseModel):
    id: str
    item_description: str
    od_size: Decimal | None = None
    id_size: Decimal | None = None
    fish_neck_od: Decimal | None = None
    fish_neck_length: Decimal | None = None
    serial_number: str = ""
    connection: str = ""
    length: Decimal | None = None
    no_of_units: Decimal
    unit: str = ""
    unit_cost: Decimal
    total_cost: Decimal
    remarks: str = ""
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime


class LihCostEntryOut(BaseModel):
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    well_id: str
    well_code: str
    well_name: str
    afe_id: str | None = None
    afe_code: str = ""
    afe_name: str = ""
    cost_date: date
    currency: str
    remarks: str
    line_count: int
    total_cost: Decimal
    display_name: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime
    updated_at: datetime


class LihCostDayOut(BaseModel):
    entry: LihCostEntryOut
    lines: list[LihCostLineOut]


class LihCostCurrencyTotal(BaseModel):
    currency: str
    total: Decimal
    line_count: int
    entry_count: int


class LihCostReportOut(BaseModel):
    """Cumulative LIH register for one well, as printed in the cost reports.

    ``totals`` keeps each currency apart (a well can carry AFEs in different
    standard currencies); ``currency`` holds the single currency when there is
    only one so a report can print one figure.
    """

    well_id: str
    well_code: str
    well_name: str
    from_date: date | None = None
    to_date: date | None = None
    currency: str = ""
    total: Decimal = Decimal("0")
    line_count: int = 0
    entry_count: int = 0
    totals: list[LihCostCurrencyTotal] = Field(default_factory=list)
    days: list[LihCostDayOut] = Field(default_factory=list)
