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
# A worksheet save and an import are bounded so one request cannot exhaust the API.
MAX_LINES_PER_DAY = 500
MAX_IMPORT_ROWS = 2000


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
    """One LIH item on a day's worksheet.

    ``item_description``, ``no_of_units`` and ``unit_cost`` are mandatory. The
    server always recomputes ``total_cost`` as units × unit cost; a client
    supplied total is not accepted. The equipment dimensions and identity
    fields are optional, typed measurements and text.

    ``id`` is set when the row already exists on the day (editing an item in
    the worksheet); a row without ``id`` is a new item. ``source`` records how
    the row was captured so duplicates and imports stay distinguishable.
    """

    id: str | None = Field(default=None, max_length=36)
    source: Literal["manual", "duplicate", "import"] = "manual"
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

    @field_validator("id", "item_description", "serial_number", "connection", "unit", "remarks", mode="before")
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


class LihCostDaySave(_Strict):
    """One worksheet save: the day header plus every item on it.

    The payload is authoritative — items missing from ``lines`` are removed
    from the day, the array order is the saved item order, rows that carry an
    ``id`` are updated and rows without one are created. Everything is written
    in one transaction, so a user can capture many items with a single save.
    """

    well_id: str = Field(min_length=1, max_length=36)
    rig_id: str = Field(default="", max_length=36)
    afe_id: str = Field(default="", max_length=36)
    cost_date: date
    remarks: str = Field(default="", max_length=1000)
    lines: list[LihCostLineIn] = Field(default_factory=list, max_length=MAX_LINES_PER_DAY)
    # Revision the worksheet was opened at. Omitted by clients that do not
    # track it; when supplied, a stale value is rejected instead of overwriting.
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("well_id", "rig_id", "afe_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class LihCostLineIDs(_Strict):
    """Remove selected items from one day's worksheet in a single call."""

    line_ids: list[str] = Field(min_length=1, max_length=MAX_LINES_PER_DAY)


class LihCostImportRow(_Strict):
    """One loose spreadsheet row; the service validates it into a LIH item.

    Fields stay lenient so the import can report a precise, per-row error
    (for example "Row 7: No of units must be greater than zero") instead of
    rejecting the whole file with one generic message.
    """

    cost_date: date | None = None
    item_description: Any = ""
    od_size: Any = None
    id_size: Any = None
    fish_neck_od: Any = None
    fish_neck_length: Any = None
    serial_number: Any = ""
    connection: Any = ""
    length: Any = None
    no_of_units: Any = ""
    unit: Any = ""
    unit_cost: Any = ""
    remarks: Any = ""


class LihCostImportRequest(_Strict):
    """Import LIH items into one well, optionally splitting them by date."""

    well_id: str = Field(min_length=1, max_length=36)
    afe_id: str = Field(default="", max_length=36)
    cost_date: date | None = None
    rows: list[LihCostImportRow] = Field(min_length=1, max_length=MAX_IMPORT_ROWS)

    @field_validator("well_id", "afe_id", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class LihCostImportResponse(BaseModel):
    imported_count: int
    error_count: int
    success: bool
    day_count: int = 0
    errors: list[str] = Field(default_factory=list)


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


class LihCostItemSuggestion(BaseModel):
    """A previously entered item, offered while typing so a repeat is one pick.

    The serial number is deliberately omitted: it identifies a specific tool and
    must not be copied from an earlier item by accident.
    """

    item_description: str
    od_size: Decimal | None = None
    id_size: Decimal | None = None
    fish_neck_od: Decimal | None = None
    fish_neck_length: Decimal | None = None
    connection: str = ""
    length: Decimal | None = None
    unit: str = ""
    unit_cost: Decimal = Decimal("0")


class LihCostReference(BaseModel):
    rigs: list[LihCostRigOption]
    wells: list[LihCostWellOption]
    afes: list[LihCostAfeOption]
    uoms: list[LihCostUomOption]
    default_currency: str = ""
    # Most recently used items in this workspace, newest first, for quick reuse.
    previous_items: list[LihCostItemSuggestion] = Field(default_factory=list)


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
    source: str = "manual"
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
    revision: int = 0
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
