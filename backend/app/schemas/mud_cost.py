"""Typed API contracts for Mud Cost Analysis."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.precision import Decimal10
from app.domain.mud_cost import (
    MUD_COST_LINE_BY_CODE,
    MUD_COST_LINE_CODES,
    MUD_COST_REMARK_REQUIRED_TYPE,
)

MudCostCategory = Literal[
    "opening_stock", "receipt", "additions", "consumption_losses", "others", "closing_stock",
]
MudCostBalanceView = Literal["daily", "monthly", "section", "inception"]
MudCostLossView = Literal["daily", "monthly", "section", "inception"]
MudCostMudType = Literal["WBM", "OBM", "SOBM", "OTHERS"]
MAX_QUANTITY = Decimal("999999999999999.9999999999")


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MudCostLineIn(_Strict):
    line_code: str = Field(min_length=1, max_length=50)
    amount: Decimal10 | None = Field(default=None, ge=0, le=MAX_QUANTITY)
    remarks: str = Field(default="", max_length=500)

    @field_validator("line_code", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("amount", mode="before")
    @classmethod
    def blank_amount_is_zero(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @model_validator(mode="after")
    def known_code(self):
        spec = MUD_COST_LINE_BY_CODE.get(self.line_code)
        if spec is None:
            raise ValueError(f"Unknown Mud Cost Analysis row '{self.line_code}'.")
        return self


class MudCostOpeningStockIn(_Strict):
    amount: Decimal10 = Field(ge=0, le=MAX_QUANTITY)
    remarks: str = Field(default="", max_length=500)


class MudCostEntryCreate(_Strict):
    rig_id: str = Field(min_length=1, max_length=36)
    well_id: str = Field(min_length=1, max_length=36)
    section_id: str = Field(min_length=1, max_length=36)
    entry_date: date
    lines: list[MudCostLineIn] = Field(default_factory=list, max_length=len(MUD_COST_LINE_CODES))

    @field_validator("rig_id", "well_id", "section_id", mode="before")
    @classmethod
    def trim_ids(cls, value: Any) -> Any:
        return _trim(value)

    @model_validator(mode="after")
    def line_codes_are_unique(self):
        codes = [line.line_code for line in self.lines]
        if len(codes) != len(set(codes)):
            raise ValueError("Each Mud Cost Analysis row can appear only once per daily entry.")
        return self


class MudCostEntryUpdate(_Strict):
    entry_date: date
    lines: list[MudCostLineIn] = Field(max_length=len(MUD_COST_LINE_CODES))

    @model_validator(mode="after")
    def line_codes_are_unique(self):
        codes = [line.line_code for line in self.lines]
        if len(codes) != len(set(codes)):
            raise ValueError("Each Mud Cost Analysis row can appear only once per daily entry.")
        return self


class MudCostLineOut(BaseModel):
    line_code: str
    category: MudCostCategory
    label: str
    amount: Decimal
    remarks: str
    sort_order: int


class MudCostEntryOut(BaseModel):
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    well_id: str
    well_code: str
    well_name: str
    section_id: str
    hole_section_id: str
    section_scope: Literal["drilling", "completion"]
    section_code: str
    section_name: str
    section_label: str
    section_from_depth: Decimal
    section_to_depth: Decimal
    entry_date: date
    opening_stock: Decimal
    opening_stock_remarks: str
    receipt: Decimal
    additions: Decimal
    consumption_losses: Decimal
    others: Decimal
    closing_stock: Decimal
    lines: list[MudCostLineOut]
    is_deleted: bool
    deleted_at: datetime | None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class MudCostBalanceRowOut(BaseModel):
    id: str
    rig_id: str
    rig_code: str
    well_id: str
    well_code: str
    section_id: str
    section_scope: Literal["drilling", "completion"]
    section_code: str
    section_name: str
    section_label: str
    period_label: str
    cost_date: date
    first_entry_date: date
    last_entry_date: date
    entry_count: int
    opening_stock: Decimal
    receipt: Decimal
    additions: Decimal
    consumption_losses: Decimal
    others: Decimal
    closing_stock: Decimal


class MudCostMaterialBalanceOut(BaseModel):
    view: MudCostBalanceView
    from_date: date | None
    to_date: date | None
    selected_section_count: int
    entry_count: int
    rows: list[MudCostBalanceRowOut]


class MudCostSectionOption(BaseModel):
    id: str
    hole_section_id: str
    section_code: str
    section_name: str
    scope: Literal["drilling", "completion"]
    from_depth: Decimal
    to_depth: Decimal
    is_current: bool
    display_name: str


class MudCostRigOption(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    display_name: str
    is_deleted: bool


class MudCostWellOption(BaseModel):
    id: str
    rig_id: str
    well_code: str
    well_name: str
    display_name: str
    status: Literal["active", "completed"]
    config_status: Literal["draft", "configured"]
    is_deleted: bool
    sections: list[MudCostSectionOption]


class MudCostReference(BaseModel):
    rigs: list[MudCostRigOption]
    wells: list[MudCostWellOption]


class MudCostIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=5000)


class MudCostImportRequest(_Strict):
    rig_id: str = Field(min_length=1, max_length=36)
    well_id: str = Field(min_length=1, max_length=36)
    section_id: str = Field(min_length=1, max_length=36)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class MudCostImportResponse(BaseModel):
    imported_count: int
    error_count: int
    errors: list[str]
    success: bool


class MudCostExportAudit(_Strict):
    module: Literal["entries", "deleted", "material_balance", "reconciliation", "consumption_losses"]
    format: Literal["csv", "xlsx", "pdf", "print"]
    record_count: int = Field(ge=0, le=1_000_000)
    rig_id: str = Field(default="", max_length=36)
    well_id: str = Field(default="", max_length=36)
    section_id: str = Field(default="", max_length=36)
    view: MudCostBalanceView | None = None
    date_from: date | None = None
    date_to: date | None = None


class MudCostLossRowOut(BaseModel):
    id: str
    period_label: str
    cost_date: date
    first_entry_date: date
    last_entry_date: date
    entry_count: int
    rig_id: str
    rig_code: str
    rig_name: str
    well_id: str
    well_code: str
    well_name: str
    section_id: str
    hole_section_id: str
    section_scope: Literal["drilling", "completion"]
    section_code: str
    section_name: str
    section_label: str
    mud_type: MudCostMudType | None
    mud_type_label: str
    verti_g_mud_on_cuttings: Decimal
    centrifuge: Decimal
    by_pass: Decimal
    evaporation: Decimal
    trips: Decimal
    surface_loss_total: Decimal
    mud_cleaner: Decimal
    formation_seepage: Decimal
    pit_cleaning_dump: Decimal
    left_in_hole: Decimal
    other_losses: Decimal
    other_loss_total: Decimal
    total_losses: Decimal


class MudCostLossReportOut(BaseModel):
    view: MudCostLossView
    from_date: date | None
    to_date: date | None
    selected_section_count: int
    entry_count: int
    surface_loss_total: Decimal
    other_loss_total: Decimal
    total_losses: Decimal
    rows: list[MudCostLossRowOut]


class MudCostBulkActionOut(BaseModel):
    affected_count: int



class MudCostSectionSettingIn(_Strict):
    """One section's mud system, remark and Cost/BBL base rate.

    The server resolves the section snapshots and the currency; the browser only
    sends the scope, the selected mud type, the remark and the rate. OTHERS is
    the only type whose remark is mandatory, and every non-WBM type must carry a
    positive base rate because it drives the reconciliation arithmetic.
    """

    rig_id: str = Field(min_length=1, max_length=36)
    well_id: str = Field(min_length=1, max_length=36)
    section_id: str = Field(min_length=1, max_length=36)
    mud_type: MudCostMudType
    remarks: str = Field(default="", max_length=500)
    base_rate: Decimal10 | None = Field(default=None, ge=0, le=MAX_QUANTITY)

    @field_validator("rig_id", "well_id", "section_id", "remarks", mode="before")
    @classmethod
    def trim_setting_text(cls, value: Any) -> Any:
        return _trim(value)

    @model_validator(mode="after")
    def required_fields_for_type(self):
        if self.mud_type == MUD_COST_REMARK_REQUIRED_TYPE and not self.remarks.strip():
            raise ValueError("Remarks are mandatory when the mud type is OTHERS.")
        if self.mud_type != "WBM" and (self.base_rate is None or self.base_rate <= 0):
            raise ValueError("Enter a positive Cost/BBL base rate for this mud type.")
        return self


class MudCostSectionSettingOut(BaseModel):
    id: str | None = None
    rig_id: str
    rig_code: str
    well_id: str
    well_code: str
    section_id: str
    hole_section_id: str
    section_scope: Literal["drilling", "completion"]
    section_code: str
    section_name: str
    section_label: str
    display_name: str
    mud_type: MudCostMudType | None = None
    mud_type_label: str
    remarks: str
    base_rate: Decimal
    currency: str
    is_configured: bool
    is_current: bool
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MudCostReconciliationRowOut(BaseModel):
    id: str
    rig_id: str
    rig_code: str
    well_id: str
    well_code: str
    section_id: str
    section_scope: Literal["drilling", "completion"]
    section_code: str
    section_name: str
    section_label: str
    mud_type: MudCostMudType | None
    mud_type_label: str
    is_configured: bool
    is_wbm: bool
    cost_date: date
    currency: str
    base_rate: Decimal
    opening_stock: Decimal
    additions: Decimal
    extra_obm_received: Decimal
    actual_cost: Decimal
    total_mud: Decimal
    alpha: Decimal | None
    beta: Decimal | None
    cost_per_bbl: Decimal | None
    consumption_losses: Decimal
    reconciled_cost: Decimal | None
    cumulative_additions: Decimal
    cumulative_extra_obm_received: Decimal
    cumulative_actual_cost: Decimal
    cumulative_total_mud: Decimal
    cumulative_alpha: Decimal | None
    cumulative_beta: Decimal | None
    cumulative_consumption_losses: Decimal
    cumulative_reconciled_cost: Decimal | None


class MudCostReconciliationSectionOut(BaseModel):
    section_id: str
    hole_section_id: str
    rig_id: str
    rig_code: str
    well_id: str
    well_code: str
    section_scope: Literal["drilling", "completion"]
    section_code: str
    section_name: str
    section_label: str
    mud_type: MudCostMudType | None
    mud_type_label: str
    remarks: str
    is_configured: bool
    is_current: bool
    is_wbm: bool
    currency: str
    base_rate: Decimal
    opening_stock: Decimal
    first_date: date | None
    last_date: date | None
    entry_count: int
    additions: Decimal
    extra_obm_received: Decimal
    actual_cost: Decimal
    total_mud: Decimal
    alpha: Decimal | None
    beta: Decimal | None
    consumption_losses: Decimal
    cost_per_bbl: Decimal | None
    reconciled_cost: Decimal | None
    adjustment: Decimal | None
    verti_g_mud_on_cuttings: Decimal = Decimal("0")
    centrifuge: Decimal = Decimal("0")
    by_pass: Decimal = Decimal("0")
    evaporation: Decimal = Decimal("0")
    trips: Decimal = Decimal("0")
    surface_loss_total: Decimal = Decimal("0")
    mud_cleaner: Decimal = Decimal("0")
    formation_seepage: Decimal = Decimal("0")
    pit_cleaning_dump: Decimal = Decimal("0")
    left_in_hole: Decimal = Decimal("0")
    other_losses: Decimal = Decimal("0")
    other_loss_total: Decimal = Decimal("0")
    total_losses: Decimal = Decimal("0")


class MudCostReconciliationOut(BaseModel):
    from_date: date | None
    to_date: date | None
    currency: str
    selected_section_count: int
    configured_section_count: int
    unconfigured_section_count: int
    entry_count: int
    latest_cost_per_bbl: Decimal | None = None
    latest_cost_per_bbl_section: str = ""
    latest_cost_per_bbl_date: date | None = None
    total_actual_cost: Decimal
    total_reconciled_cost: Decimal
    total_adjustment: Decimal
    total_consumption_losses: Decimal
    sections: list[MudCostReconciliationSectionOut]
    rows: list[MudCostReconciliationRowOut]
