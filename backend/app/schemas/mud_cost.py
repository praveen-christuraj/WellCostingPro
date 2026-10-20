"""Typed API contracts for Mud Cost Analysis."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.precision import Decimal10
from app.domain.mud_cost import MUD_COST_LINE_BY_CODE, MUD_COST_LINE_CODES

MudCostCategory = Literal[
    "opening_stock", "receipt", "additions", "consumption_losses", "others", "closing_stock",
]
MudCostBalanceView = Literal["daily", "monthly", "section", "inception"]
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
    module: Literal["entries", "deleted", "material_balance"]
    format: Literal["csv", "xlsx", "pdf", "print"]
    record_count: int = Field(ge=0, le=1_000_000)
    rig_id: str = Field(default="", max_length=36)
    well_id: str = Field(default="", max_length=36)
    section_id: str = Field(default="", max_length=36)
    view: MudCostBalanceView | None = None
    date_from: date | None = None
    date_to: date | None = None


class MudCostBulkActionOut(BaseModel):
    affected_count: int
