"""Typed API contracts for the Fuel Cost Register (Daily Cost Management).

The register is rig-scoped and quantity-based: every value is litres. No prices
or currencies are stored, so a fuel day joins no AFE estimate and needs no
exchange rate.

``gas_consumption`` / ``rig_saving_litres`` represents **Rig Saving (litres)** —
the AGO saved through gas usage on the rig. Both field names are accepted on
write/import and returned on read for seamless compatibility, and the value is
always kept outside AGO consumption and the physical stock balance.

Material balance fields are returned, never accepted: opening stock is derived
from the preceding actual closing (or captured once on the first day), the book
closing is opening + receipts − AGO consumption, and the adjustments reconcile
the entered opening and actual closing with the book. A client-supplied balance
is rejected by ``extra="forbid"``.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.precision import Decimal10

# One rig's day is generous at a billion litres; the ceiling only stops absurd input.
MAX_LITRES = Decimal("1000000000")
MAX_COMPANY_NAME = 200
MAX_CATEGORY_NAME = 120
MAX_REMARKS = 500
MAX_DAY_REMARKS = 1000
MAX_LINES_PER_DAY = 1000
MAX_IMPORT_ROWS = 25000


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


# ---------------------------------------------------------------------------
# Companies and categories (the daily entry set)
# ---------------------------------------------------------------------------


class FuelCompanyCategoryIn(_Strict):
    category_name: str = Field(min_length=1, max_length=MAX_CATEGORY_NAME)
    remarks: str = Field(default="", max_length=MAX_REMARKS)

    @field_validator("category_name", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class FuelCompanyCategoryUpdate(_Strict):
    category_name: str | None = Field(default=None, min_length=1, max_length=MAX_CATEGORY_NAME)
    remarks: str | None = Field(default=None, max_length=MAX_REMARKS)

    @field_validator("category_name", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class FuelCompanyIn(_Strict):
    """Register a company for fuel consumption.

    ``vendor_id`` links the company to a Master Data vendor (the usual source of
    company names), while ``company_name`` stays a first-class column so a
    company that is not a vendor can still be registered. ``is_default`` adds it
    to the daily entry set the consumption dialog pre-lists.
    """

    company_name: str = Field(min_length=1, max_length=MAX_COMPANY_NAME)
    vendor_id: str = Field(default="", max_length=36)
    is_default: bool = False
    remarks: str = Field(default="", max_length=MAX_REMARKS)

    @field_validator("company_name", "vendor_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class FuelCompanyUpdate(_Strict):
    """Edit a company. Omitted fields keep their stored values."""

    company_name: str | None = Field(default=None, min_length=1, max_length=MAX_COMPANY_NAME)
    vendor_id: str | None = Field(default=None, max_length=36)
    is_default: bool | None = None
    remarks: str | None = Field(default=None, max_length=MAX_REMARKS)

    @field_validator("company_name", "vendor_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class FuelCompanyCategoryOut(BaseModel):
    id: str
    company_id: str
    category_name: str
    remarks: str = ""
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FuelCompanyOut(BaseModel):
    id: str
    company_name: str
    vendor_id: str | None = None
    vendor_code: str = ""
    is_default: bool
    source: str = "manual"
    remarks: str = ""
    is_deleted: bool = False
    deleted_at: datetime | None = None
    categories: list[FuelCompanyCategoryOut] = Field(default_factory=list)
    display_name: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class FuelCostRigOption(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    display_name: str


class FuelCostVendorOption(BaseModel):
    """A vendor offered as a source of company names."""

    id: str
    vendor_code: str
    vendor_name: str
    vendor_type: str
    status: str
    registered: bool = False
    display_name: str


class FuelCostReference(BaseModel):
    rigs: list[FuelCostRigOption]
    companies: list[FuelCompanyOut]
    vendors: list[FuelCostVendorOption]


# ---------------------------------------------------------------------------
# Write payloads
# ---------------------------------------------------------------------------


class FuelCostCompanyLineIn(_Strict):
    """One company's AGO consumption on the day.

    ``id`` is set when the line already exists (editing); a row without an id is
    new. ``category_id`` is optional — a company can be tracked as a whole.
    """

    id: str | None = Field(default=None, max_length=36)
    company_id: str = Field(min_length=1, max_length=36)
    category_id: str = Field(default="", max_length=36)
    litres: Decimal10 = Field(ge=0, le=MAX_LITRES)
    remarks: str = Field(default="", max_length=MAX_REMARKS)
    source: Literal["manual", "import"] = "manual"

    @field_validator("id", "company_id", "category_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class FuelCostEntrySave(_Strict):
    """Create or replace one rig day.

    The payload governs the whole day: company lines missing from ``lines`` are
    removed, rows with an ``id`` are updated, rows without one are created and the
    array order becomes the saved order. Day totals and every balance field are
    computed by the server.

    ``opening_stock`` is only valid on the rig's first day (the anchor) or when
    ``opening_overridden`` is true, which needs the separate opening-stock
    capability. Omitted means "derive from the previous actual closing".
    """

    rig_id: str = Field(min_length=1, max_length=36)
    cost_date: date
    rig_engine_consumption: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_LITRES)
    rig_engine_remarks: str = Field(default="", max_length=MAX_REMARKS)
    # Rig Saving (litres): AGO saved through gas usage. Accepted via either
    # ``rig_saving_litres`` or the legacy ``gas_consumption`` key.
    gas_consumption: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_LITRES)
    gas_remarks: str = Field(default="", max_length=MAX_REMARKS)
    rig_saving_litres: Decimal10 | None = Field(default=None, ge=0, le=MAX_LITRES)
    rig_saving_remarks: str | None = Field(default=None, max_length=MAX_REMARKS)
    opening_stock: Decimal10 | None = Field(default=None, ge=0, le=MAX_LITRES)
    opening_overridden: bool = False
    # Returns an ordinary day to the carried-forward opening. Ignored on the
    # rig's first day (its opening is the anchor the chain starts from).
    clear_opening_override: bool = False
    opening_remarks: str = Field(default="", max_length=MAX_REMARKS)
    receipt_quantity: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_LITRES)
    receipt_remarks: str = Field(default="", max_length=MAX_REMARKS)
    closing_stock: Decimal10 | None = Field(default=None, ge=0, le=MAX_LITRES)
    closing_remarks: str = Field(default="", max_length=MAX_REMARKS)
    remarks: str = Field(default="", max_length=MAX_DAY_REMARKS)
    lines: list[FuelCostCompanyLineIn] = Field(default_factory=list, max_length=MAX_LINES_PER_DAY)
    # Omitted by clients that do not track it; a stale value is rejected (409).
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator(
        "rig_id",
        "rig_engine_remarks",
        "gas_remarks",
        "rig_saving_remarks",
        "opening_remarks",
        "receipt_remarks",
        "closing_remarks",
        "remarks",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("opening_stock", "closing_stock", "rig_saving_litres", mode="before")
    @classmethod
    def blank_quantities(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def sync_rig_saving_aliases(self) -> "FuelCostEntrySave":
        if self.rig_saving_litres is not None:
            self.gas_consumption = self.rig_saving_litres
        if self.rig_saving_remarks is not None:
            self.gas_remarks = self.rig_saving_remarks
        return self


class FuelCostOpeningStockUpdate(_Strict):
    """Override (or correct) a day's opening stock.

    ``clear_override`` returns an ordinary day to the carried-forward opening.
    The first day keeps an opening — it is the anchor the whole rig chain starts
    from — so it cannot be cleared.
    """

    opening_stock: Decimal10 | None = Field(default=None, ge=0, le=MAX_LITRES)
    remarks: str = Field(default="", max_length=MAX_REMARKS)
    clear_override: bool = False

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("opening_stock", mode="before")
    @classmethod
    def blank_quantity(cls, value: Any) -> Any:
        return _blank_to_none(value)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


class FuelCostCompanyLineOut(BaseModel):
    id: str
    company_id: str
    company_name: str
    category_id: str | None = None
    category_name: str = ""
    litres: Decimal
    remarks: str = ""
    source: str = "manual"
    sort_order: int = 0
    display_name: str
    created_at: datetime
    updated_at: datetime


class FuelCostPreviousLineOut(BaseModel):
    """One company/category allocation from the preceding fuel day of the rig."""

    company_id: str
    company_name: str
    category_id: str | None = None
    category_name: str = ""
    litres: Decimal = Decimal("0")


class FuelCostBalance(BaseModel):
    """The day's material balance, computed from the rig's active chain."""

    is_first_entry: bool
    opening_overridden: bool = False
    carried_opening: Decimal = Decimal("0")
    previous_date: date | None = None
    opening_stock: Decimal = Decimal("0")
    opening_adjustment: Decimal = Decimal("0")
    receipt: Decimal = Decimal("0")
    rig_engine_consumption: Decimal = Decimal("0")
    company_consumption: Decimal = Decimal("0")
    total_consumption: Decimal = Decimal("0")
    book_closing_stock: Decimal = Decimal("0")
    actual_closing_stock: Decimal = Decimal("0")
    closing_adjustment: Decimal = Decimal("0")
    adjustments: Decimal = Decimal("0")
    # Rig Saving (litres): AGO saved via gas usage, reported beside the balance.
    gas_consumption: Decimal = Decimal("0")
    rig_saving_litres: Decimal = Decimal("0")


class FuelCostEntryOut(BaseModel):
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    cost_date: date
    rig_engine_consumption: Decimal
    rig_engine_remarks: str = ""
    gas_consumption: Decimal
    gas_remarks: str = ""
    rig_saving_litres: Decimal = Decimal("0")
    rig_saving_remarks: str = ""
    opening_stock: Decimal | None = None
    opening_overridden: bool = False
    opening_remarks: str = ""
    receipt_quantity: Decimal
    receipt_remarks: str = ""
    closing_stock: Decimal | None = None
    closing_remarks: str = ""
    remarks: str = ""
    revision: int = 0
    line_count: int = 0
    company_consumption: Decimal = Decimal("0")
    total_consumption: Decimal = Decimal("0")
    balance: FuelCostBalance
    display_name: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime
    updated_at: datetime


class FuelCostDayOut(BaseModel):
    """One rig day as the entry pop-up needs it, existing or still to be created.

    ``entry`` is null before the first save; ``balance`` then previews the day
    (the carried opening, whether this would be the rig's first day, and the
    previous date) so the dialog can lock the opening stock correctly.
    ``previous_lines`` provides the preceding active day's company/category set
    for instant one-click pre-filling.
    """

    rig_id: str
    rig_code: str
    rig_name: str
    cost_date: date
    entry: FuelCostEntryOut | None = None
    lines: list[FuelCostCompanyLineOut] = Field(default_factory=list)
    previous_lines: list[FuelCostPreviousLineOut] = Field(default_factory=list)
    balance: FuelCostBalance


class FuelCostRigSummaryOut(BaseModel):
    """Fast period and inception summary for one rig without transferring all rows."""

    rig_id: str
    rig_code: str
    rig_name: str
    from_date: date | None = None
    to_date: date | None = None
    total_active_days: int = 0
    period_days: int = 0
    earliest_date: date | None = None
    latest_date: date | None = None
    opening_stock: Decimal = Decimal("0")
    opening_adjustment: Decimal = Decimal("0")
    receipt: Decimal = Decimal("0")
    rig_engine_consumption: Decimal = Decimal("0")
    company_consumption: Decimal = Decimal("0")
    total_consumption: Decimal = Decimal("0")
    expected_closing_stock: Decimal = Decimal("0")
    book_closing_stock: Decimal = Decimal("0")
    actual_closing_stock: Decimal = Decimal("0")
    closing_adjustment: Decimal = Decimal("0")
    adjustments: Decimal = Decimal("0")
    gas_consumption: Decimal = Decimal("0")
    rig_saving_litres: Decimal = Decimal("0")


class FuelCostCompanyConsumptionRow(BaseModel):
    """Company / category consumption across a date range for one rig."""

    company_id: str
    company_name: str
    category_id: str | None = None
    category_name: str = ""
    litres: Decimal
    day_count: int
    line_count: int


class FuelCostCompanySummaryRow(BaseModel):
    """Company-level AGO consumption summary across all categories."""

    company_id: str
    company_name: str
    vendor_code: str = ""
    is_default: bool = False
    category_count: int = 0
    litres: Decimal
    day_count: int
    line_count: int


class FuelCostCategorySummaryRow(BaseModel):
    """Category-level AGO consumption summary across companies."""

    category_key: str
    category_name: str
    company_count: int
    litres: Decimal
    day_count: int
    line_count: int


class FuelCostCompanyConsumptionOut(BaseModel):
    rig_id: str
    rig_code: str
    rig_name: str
    from_date: date | None = None
    to_date: date | None = None
    total_litres: Decimal = Decimal("0")
    rig_engine_litres: Decimal = Decimal("0")
    total_ago_litres: Decimal = Decimal("0")
    rig_saving_litres: Decimal = Decimal("0")
    active_day_count: int = 0
    rows: list[FuelCostCompanyConsumptionRow] = Field(default_factory=list)
    company_rows: list[FuelCostCompanySummaryRow] = Field(default_factory=list)
    category_rows: list[FuelCostCategorySummaryRow] = Field(default_factory=list)


class FuelCostLedgerLineOut(BaseModel):
    """One company/category consumption row in the paginated ledger."""

    id: str
    entry_id: str
    cost_date: date
    rig_code: str
    company_id: str
    company_name: str
    vendor_code: str = ""
    category_id: str | None = None
    category_name: str = ""
    litres: Decimal
    remarks: str = ""
    source: str = "manual"


class FuelCostPaginatedLinesOut(BaseModel):
    rig_id: str
    total_count: int
    total_litres: Decimal = Decimal("0")
    page: int
    page_size: int
    rows: list[FuelCostLedgerLineOut] = Field(default_factory=list)


class FuelCostImportRow(_Strict):
    """One loose spreadsheet row; the service validates it into a fuel day line.

    Fields stay lenient so the import can report a precise per-row error instead
    of rejecting the whole file. A row may carry only day-level values (engine,
    rig saving litres, stock, receipt) or one company consumption line as well.
    """

    rig_code: Any = ""
    cost_date: Any = ""
    rig_engine_consumption: Any = ""
    rig_engine_remarks: Any = ""
    gas_consumption: Any = ""
    gas_remarks: Any = ""
    rig_saving_litres: Any = ""
    rig_saving_remarks: Any = ""
    opening_stock: Any = ""
    opening_remarks: Any = ""
    receipt_quantity: Any = ""
    receipt_remarks: Any = ""
    closing_stock: Any = ""
    closing_remarks: Any = ""
    remarks: Any = ""
    company_name: Any = ""
    category_name: Any = ""
    litres: Any = ""
    line_remarks: Any = ""


class FuelCostImportRequest(_Strict):
    """Import fuel days from a spreadsheet, optionally across several rigs."""

    rig_id: str = Field(default="", max_length=36)
    rows: list[FuelCostImportRow] = Field(min_length=1, max_length=MAX_IMPORT_ROWS)


class FuelCostImportResponse(BaseModel):
    imported_count: int
    line_count: int
    error_count: int
    success: bool
    day_count: int = 0
    errors: list[str] = Field(default_factory=list)


class FuelCostIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=5000)


class FuelCostBulkActionOut(BaseModel):
    affected_count: int


class FuelCostExportAudit(_Strict):
    module: Literal[
        "register",
        "recent-register",
        "deleted",
        "material-balance",
        "company-consumption",
        "category-consumption",
        "company-lines",
        "day",
    ]
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=1_000_000)
    rig_id: str = Field(default="", max_length=36)
    entry_id: str = Field(default="", max_length=36)
    date_from: date | None = None
    date_to: date | None = None
    include_deleted: bool = False
