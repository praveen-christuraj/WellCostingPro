"""Typed API contracts for the Reports module usage/cost matrix reports.

These reports are read-only projections of the Daily Cost ledger. Every value
is derived from stored, column-wise daily cost lines; nothing is persisted by
this module except export audit rows.
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UsageReportKey = Literal["mud-chemicals", "drill-bits", "tangibles", "services", "vendors"]
UsageReportMode = Literal["usage", "cost"]
UsageScope = Literal["drilling", "completion"]
WellLifecycle = Literal["active", "final_review", "completed"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Reference / filter options
# ---------------------------------------------------------------------------


class UsageBlockOption(_Strict):
    id: str
    block_code: str
    block_name: str


class UsageRigOption(_Strict):
    id: str
    rig_code: str
    rig_name: str


class UsageWellOption(_Strict):
    id: str
    rig_id: str
    block_id: str
    well_code: str
    well_name: str
    display_name: str
    status: str
    config_status: str
    completion_status: str
    completion_config_status: str
    # Configuration scopes the well actually carries costs/plans for.
    scopes: list[str] = Field(default_factory=list)
    has_costs: bool = False


class UsageCurrencyOption(_Strict):
    code: str
    name: str = ""
    symbol: str = ""
    is_default: bool = False


class UsageReference(_Strict):
    blocks: list[UsageBlockOption]
    rigs: list[UsageRigOption]
    wells: list[UsageWellOption]
    currencies: list[UsageCurrencyOption]
    default_currency: str


# ---------------------------------------------------------------------------
# Matrix reports (mud chemicals, drill bits, tangibles, services, vendors)
# ---------------------------------------------------------------------------


class UsageSectionOut(_Strict):
    section_key: str
    hole_section_id: str
    section_code: str
    section_name: str
    scope: str


class UsageWellColumnOut(_Strict):
    well_id: str
    well_code: str
    well_name: str
    rig_id: str
    rig_code: str
    rig_name: str
    block_id: str
    block_code: str
    block_name: str
    scopes: list[str] = Field(default_factory=list)
    sections: list[UsageSectionOut] = Field(default_factory=list)


class UsageCellOut(_Strict):
    section_key: str
    quantity: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")


class UsageWellCellOut(_Strict):
    well_id: str
    sections: list[UsageCellOut] = Field(default_factory=list)
    quantity: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")


class UsageItemRowOut(_Strict):
    item_id: str
    item_code: str
    item_name: str
    uom: str = ""
    category: str = ""
    subcategory: str = ""
    manufacturer: str = ""
    detail: str = ""
    cells: list[UsageWellCellOut] = Field(default_factory=list)
    quantity_total: Decimal = Decimal("0")
    amount_total: Decimal = Decimal("0")


class UsageDetailRowOut(_Strict):
    """Flat item × well × section row for the filterable detail grid."""

    row_id: str
    report: str
    cost_group: str = ""
    item_id: str
    item_code: str
    item_name: str
    uom: str = ""
    category: str = ""
    subcategory: str = ""
    manufacturer: str = ""
    detail: str = ""
    well_id: str
    well_code: str
    well_name: str
    rig_code: str = ""
    block_code: str = ""
    scope: str = ""
    section_key: str
    section_code: str = ""
    section_name: str = ""
    quantity: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    currency: str


class UsageMatrixOut(_Strict):
    report: UsageReportKey
    mode: UsageReportMode
    currency: str
    date_from: date | None = None
    date_to: date | None = None
    include_draft: bool = True
    wells: list[UsageWellColumnOut] = Field(default_factory=list)
    rows: list[UsageItemRowOut] = Field(default_factory=list)
    detail: list[UsageDetailRowOut] = Field(default_factory=list)
    well_totals: list[UsageWellCellOut] = Field(default_factory=list)
    grand_quantity: Decimal = Decimal("0")
    grand_amount: Decimal = Decimal("0")
    entry_count: int = 0
    excluded_entry_count: int = 0


# ---------------------------------------------------------------------------
# NPT / UPA report
# ---------------------------------------------------------------------------


class NptUpaWellRow(_Strict):
    well_id: str
    well_code: str
    well_name: str
    rig_code: str = ""
    block_code: str = ""
    planned_affected_dates: int = 0
    upa_affected_dates: int = 0
    npt_affected_dates: int = 0
    planned_hours: Decimal = Decimal("0")
    upa_hours: Decimal = Decimal("0")
    npt_hours: Decimal = Decimal("0")
    planned_days: Decimal = Decimal("0")
    upa_days: Decimal = Decimal("0")
    npt_days: Decimal = Decimal("0")
    planned_amount: Decimal = Decimal("0")
    upa_amount: Decimal = Decimal("0")
    npt_amount: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    overallocated_dates: int = 0


class NptUpaDetailRow(_Strict):
    row_id: str
    well_id: str
    well_code: str
    well_name: str
    rig_code: str = ""
    block_code: str = ""
    scope: str = ""
    classification: str
    affected_dates: int = 0
    hours: Decimal = Decimal("0")
    days: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    currency: str


class NptUpaReportOut(_Strict):
    currency: str
    date_from: date | None = None
    date_to: date | None = None
    include_draft: bool = True
    wells: list[NptUpaWellRow] = Field(default_factory=list)
    detail: list[NptUpaDetailRow] = Field(default_factory=list)
    totals: NptUpaWellRow
    entry_count: int = 0
    excluded_entry_count: int = 0
    overallocated_date_count: int = 0


# ---------------------------------------------------------------------------
# Export audit
# ---------------------------------------------------------------------------


class UsageReportExportAudit(_Strict):
    report: Literal[
        "mud-chemicals", "drill-bits", "tangibles", "services", "vendors", "npt-upa"
    ]
    format: Literal["csv", "xlsx", "pdf", "print"]
    record_count: int = Field(ge=0, le=1_000_000)
    block_id: str = Field(default="", max_length=36)
    rig_id: str = Field(default="", max_length=36)
    well_ids: list[str] = Field(default_factory=list, max_length=500)
    scope: Literal["", "drilling", "completion"] = ""
    lifecycle: Literal["", "active", "final_review", "completed"] = ""
    currency: str = Field(default="", max_length=10)
    date_from: date | None = None
    date_to: date | None = None
    include_draft: bool = True
