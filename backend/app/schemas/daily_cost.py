"""Column-wise request/response contracts for Daily Cost Management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.precision import Decimal10

# Classification (Planned / UPA / NPT) is no longer entered on daily cost
# lines: the Master Data Activity already carries that meaning, so every line's
# classification is derived from its selected Activity. The type is kept only
# for read/analysis outputs.
CostClassification = Literal["Planned", "UPA", "NPT"]
ChargingBasis = Literal["Day Rate", "Per Service Rate", "Per Section Rate"]
ChargeCategory = Literal[
    "Mobilization",
    "Demobilization",
    "Operation",
    "Standby",
    "Personnel-Operation",
    "Personnel-Standby",
    "Fixed Charge",
    "Others",
]
ConsumableCategory = Literal["Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits"]
ConsumableKind = Literal["mud_chemical", "cement_additive", "fuel", "drill_bit"]
# Unexpected charges that have no AFE allowance. The code is what is persisted;
# the label lives in OTHER_EXPENSE_TYPE_LABELS and is snapshotted per line.
OtherExpenseType = Literal[
    "LIH", "HOLE_PROBLEM", "FISHING", "SIDE_TRACK", "EQUIPMENT_DAMAGE",
    "THIRD_PARTY_CLAIM", "PENALTY", "MISC",
]
OtherExpenseUnit = Literal["unit", "days", "hours"]
# The four cost groups of a daily sheet. Other Expenses has no AFE allowance and
# is deducted from the locked AFE total instead of reconciled against a budget line.
CostGroup = Literal["Services", "Consumables", "Tangibles", "Other Expenses"]
TRACKED_COST_GROUPS: tuple[str, ...] = ("Services", "Consumables", "Tangibles")
ALL_COST_GROUPS: tuple[str, ...] = (*TRACKED_COST_GROUPS, "Other Expenses")
QuantityUnit = Literal["days", "hours", "service", "section", "unit"]
DAILY_COST_MAX_LINES = 1000
MAX_RATE = Decimal("100000000")
MAX_AMOUNT = Decimal("100000000000")
# An other-expense line is only as useful as the explanation attached to it, so a
# remark is mandatory on every one of these lines.
OTHER_EXPENSE_MIN_REMARKS = 3


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def _blank_to_none(value: Any) -> Any:
    value = _trim(value)
    return value or None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DailyCostEntryCreate(_Strict):
    well_id: str = Field(min_length=1, max_length=36)
    afe_id: str = Field(min_length=1, max_length=36)
    cost_date: date
    remarks: str = Field(default="", max_length=1000)
    usd_exchange_rate: Decimal10 | None = Field(default=None, gt=0, le=Decimal("999999"))

    @field_validator("well_id", "afe_id", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("usd_exchange_rate", mode="before")
    @classmethod
    def blank_usd_rate(cls, value: Any) -> Any:
        return _blank_to_none(value)


class DailyCostLineInput(_Strict):
    """Common typed fields for each actual cost line.

    ``sub_activity_id`` is mandatory on every saved line (the well's sub
    activities must be configured in Rig & Well Management first); the service
    layer enforces it together with the well/activity match. Classification is
    intentionally absent: it is derived from the selected Master Data Activity.
    """

    id: str | None = Field(default=None, max_length=36)
    client_key: str | None = Field(default=None, max_length=64)
    activity_id: str = Field(min_length=1, max_length=36)
    hole_section_id: str | None = Field(default=None, max_length=36)
    phase_id: str | None = Field(default=None, max_length=36)
    sub_activity_id: str | None = Field(default=None, max_length=36)
    vendor_id: str | None = Field(default=None, max_length=36)
    party_name: str = Field(default="", max_length=200)
    quantity: Decimal10 = Field(gt=0, le=Decimal("1000000"))
    currency: str = Field(default="", max_length=10)
    exchange_rate: Decimal10 | None = Field(default=None, gt=0, le=Decimal("999999"))
    actual_depth: Decimal10 | None = Field(default=None, ge=0, le=Decimal("999999999"))
    actual_depth_unit: Literal["m", "ft"] = "m"
    depth_seq: int | None = None
    override_rate: Decimal10 | None = Field(default=None, ge=0, le=MAX_RATE)
    override_reason: str = Field(default="", max_length=500)
    remarks: str = Field(default="", max_length=500)

    @field_validator("hole_section_id", "phase_id", "sub_activity_id", "vendor_id", "exchange_rate", "actual_depth", mode="before")
    @classmethod
    def blank_ids_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("actual_depth_unit", mode="before")
    @classmethod
    def normalize_depth_unit_field(cls, value: Any) -> Any:
        text = _trim(value).lower() if isinstance(value, str) else value
        if text in ("", None, "m", "meter", "meters", "metre", "metres"):
            return "m"
        if text in ("ft", "feet", "foot"):
            return "ft"
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("party_name", "override_reason", "remarks", mode="before")
    @classmethod
    def trim_fields(cls, value: Any) -> Any:
        return _trim(value)

    @model_validator(mode="after")
    def require_override_reason(self):
        if self.override_rate is not None and len(self.override_reason.strip()) < 3:
            raise ValueError("Give a reason of at least 3 characters for a daily rate override.")
        if self.override_rate is None and self.override_reason:
            raise ValueError("An override reason is only valid when an override rate is entered.")
        if self.phase_id and not self.hole_section_id:
            raise ValueError("Choose a hole section before selecting a phase.")
        return self


class ServiceCostItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    amount: Decimal = Field(ge=0, max_digits=24, decimal_places=6)

    @field_validator("description")
    @classmethod
    def nonblank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a cost item description.")
        return value.strip()


class DailyCostServiceLineIn(DailyCostLineInput):
    cost_items: list[ServiceCostItemIn] = Field(default_factory=list, max_length=100)
    service_id: str = Field(min_length=1, max_length=36)
    baseline_service_rate_id: str | None = Field(default=None, max_length=36)
    charging_basis: ChargingBasis | None = None
    charge_category: ChargeCategory = "Operation"
    quantity_unit: QuantityUnit = "days"

    @field_validator("baseline_service_rate_id", mode="before")
    @classmethod
    def blank_rate_to_none(cls, value: Any) -> Any:
        return _blank_to_none(value)


class DailyCostConsumableLineIn(DailyCostLineInput):
    category: ConsumableCategory
    item_kind: ConsumableKind
    item_id: str = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def category_matches_item(self):
        expected = {
            "Mud Chemicals": "mud_chemical",
            "Cement Additives": "cement_additive",
            "Fuel": "fuel",
            "Drill Bits": "drill_bit",
        }[self.category]
        if self.item_kind != expected:
            raise ValueError(f"{self.category} items must use the {expected} catalogue.")
        return self


class DailyCostTangibleLineIn(DailyCostLineInput):
    tangible_id: str = Field(min_length=1, max_length=36)


class DailyCostOtherExpenseLineIn(DailyCostLineInput):
    """An unexpected charge (Lost In Hole, hole problem, claim …) on the day sheet.

    There is no AFE or catalogue allowance to price from, so the unit rate is
    entered on the line. A daily override is meaningless here and is rejected, and
    the remarks are mandatory because they are what explains the charge.
    """

    expense_type: OtherExpenseType
    expense_description: str = Field(default="", max_length=300)
    quantity_unit: OtherExpenseUnit = "unit"
    unit_rate: Decimal10 = Field(gt=0, le=MAX_RATE)

    @field_validator("expense_description", mode="before")
    @classmethod
    def trim_description(cls, value: Any) -> Any:
        return _trim(value)

    @model_validator(mode="after")
    def require_remark_and_plain_rate(self):
        if len(self.remarks.strip()) < OTHER_EXPENSE_MIN_REMARKS:
            raise ValueError(
                "Other expenses need remarks of at least "
                f"{OTHER_EXPENSE_MIN_REMARKS} characters explaining the charge "
                "(what was lost in hole, the incident or the claim reference)."
            )
        if self.override_rate is not None or self.override_reason:
            raise ValueError(
                "An other expense is priced from its own unit rate; a daily rate override does not apply."
            )
        return self


class DailyCostSaveIn(_Strict):
    remarks: str = Field(default="", max_length=1000)
    usd_exchange_rate: Decimal10 | None = Field(default=None, gt=0, le=Decimal("999999"))
    services: list[DailyCostServiceLineIn] = Field(default_factory=list, max_length=DAILY_COST_MAX_LINES)
    consumables: list[DailyCostConsumableLineIn] = Field(default_factory=list, max_length=DAILY_COST_MAX_LINES)
    tangibles: list[DailyCostTangibleLineIn] = Field(default_factory=list, max_length=DAILY_COST_MAX_LINES)
    other_expenses: list[DailyCostOtherExpenseLineIn] = Field(default_factory=list, max_length=DAILY_COST_MAX_LINES)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("usd_exchange_rate", mode="before")
    @classmethod
    def blank_usd_rate(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def unique_line_ids(self):
        ids = [
            line.id
            for group in (self.services, self.consumables, self.tangibles, self.other_expenses)
            for line in group if line.id
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("A saved line can appear only once in a daily sheet.")
        return self


class DailyCostStatusIn(_Strict):
    remarks: str = Field(default="", max_length=500)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim(value)


class DailyCostReopenIn(_Strict):
    remarks: str = Field(min_length=3, max_length=500)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim(value)


class DailyCostIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=5000)


class DailyCostImportRequest(_Strict):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class DailyCostImportResponse(BaseModel):
    imported_count: int
    error_count: int
    errors: list[str]
    success: bool


class DailyCostExportAudit(_Strict):
    module: Literal["entries", "deleted", "day-sheet", "budget-comparison", "well-cost-sheet"]
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=1_000_000)
    include_deleted: bool = False
    well_id: str = Field(default="", max_length=36)
    entry_id: str = Field(default="", max_length=36)
    date_from: date | None = None
    date_to: date | None = None
    include_draft: bool = True


# ---------------------------------------------------------------------------
# Reference data and immutable rate/plan context
# ---------------------------------------------------------------------------


class DailyCostRigOption(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    display_name: str


class DailyCostPhaseOption(BaseModel):
    phase_id: str
    phase_code: str
    phase_name: str
    days: Decimal


class DailyCostSectionOption(BaseModel):
    hole_section_id: str
    section_code: str
    section_name: str
    from_depth: Decimal
    to_depth: Decimal
    total_days: Decimal
    phases: list[DailyCostPhaseOption]


class DailyCostWellOption(BaseModel):
    id: str
    rig_id: str
    well_code: str
    well_name: str
    display_name: str
    status: str
    config_status: str
    completion_status: str = "active"
    completion_config_status: str = "draft"
    drilling_is_deleted: bool = False
    completion_is_deleted: bool = False
    sections: list[DailyCostSectionOption]


class DailyCostAfeOption(BaseModel):
    id: str
    well_id: str
    afe_code: str
    afe_name: str
    afe_type: str
    status: str
    # The well scope this AFE was estimated against (drilling or completion).
    # Reports use it to title themselves, e.g. "Well Cost Report - Drilling".
    configuration_scope: Literal["drilling", "completion"] = "drilling"
    standard_currency: str
    total_cost: Decimal
    estimate_saved_at: datetime
    display_name: str


class DailyCostActivityOption(BaseModel):
    id: str
    activity_code: str
    activity_name: str
    display_name: str


class DailyCostSubActivityOption(BaseModel):
    id: str
    well_id: str
    scope: Literal["drilling", "completion"] = "drilling"
    activity_id: str
    sub_activity_code: str
    sub_activity_name: str
    responsible_party: str
    display_name: str


class DailyCostServiceOption(BaseModel):
    id: str
    service_code: str
    service_name: str
    service_category: str
    service_group: str = ""
    provider_type: str
    vendor_id: str | None
    vendor_code: str
    vendor_name: str
    display_name: str


class DailyCostCatalogueOption(BaseModel):
    id: str
    item_kind: ConsumableKind | Literal["tangible"]
    category: ConsumableCategory | Literal["Tangibles"]
    item_code: str
    item_name: str
    description: str
    uom: str
    captured_rate: Decimal
    currency: str
    revision_number: int
    effective_date: date | None
    display_name: str


class DailyCostVendorOption(BaseModel):
    id: str
    vendor_code: str
    vendor_name: str
    vendor_type: str
    status: str
    display_name: str


class DailyCostOtherExpenseTypeOption(BaseModel):
    """One selectable type of unexpected cost, e.g. LIH or a hole problem."""

    code: str
    label: str


class DailyCostReference(BaseModel):
    rigs: list[DailyCostRigOption]
    wells: list[DailyCostWellOption]
    afes: list[DailyCostAfeOption]
    activities: list[DailyCostActivityOption]
    sub_activities: list[DailyCostSubActivityOption]
    services: list[DailyCostServiceOption]
    catalogue_items: list[DailyCostCatalogueOption]
    vendors: list[DailyCostVendorOption]
    currencies: list[str]
    charge_categories: list[str]
    charge_bases: list[str]
    quantity_units: list[str]
    classifications: list[str]
    consumable_categories: list[str]
    other_expense_types: list[DailyCostOtherExpenseTypeOption]


class DailyCostRateOut(BaseModel):
    id: str
    service_id: str
    source_afe_line_id: str
    service_code: str
    service_name: str
    charging_basis: ChargingBasis
    rate_kind: Literal["day_rate", "per_service", "per_section"]
    charge_category: str
    hole_section_id: str | None
    section_label: str
    phase_id: str | None
    phase_label: str
    unit_rate: Decimal
    currency: str
    display_name: str


class DailyCostBaselineBudgetOut(BaseModel):
    id: str
    cost_group: Literal["Services", "Consumables", "Tangibles"]
    budget_kind: str
    item_key: str
    item_code: str
    item_name: str
    service_group: str = ""
    source_afe_line_id: str
    section_id: str | None
    phase_id: str | None
    quantity: Decimal
    unit_rate: Decimal
    native_amount: Decimal
    currency: str
    exchange_rate: Decimal
    planned_amount: Decimal
    uom: str


class DailyCostBaselineOut(BaseModel):
    id: str
    rate_baseline_id: str
    afe_id: str
    afe_code: str
    afe_name: str
    standard_currency: str
    total_amount: Decimal
    locked_at: datetime
    locked_by: str
    afe_estimate_saved_at: datetime | None
    catalogue_rates: list[DailyCostCatalogueOption]
    service_rates: list[DailyCostRateOut]
    budget_lines: list[DailyCostBaselineBudgetOut]
    sections: list[DailyCostSectionOption]
    exchange_rates: dict[str, Decimal]


# ---------------------------------------------------------------------------
# Daily line outputs
# ---------------------------------------------------------------------------


class DailyCostLineOut(BaseModel):
    id: str
    activity_id: str
    activity_code: str
    activity_name: str
    hole_section_id: str | None
    section_code: str
    section_name: str
    phase_id: str | None
    phase_code: str
    phase_name: str
    sub_activity_id: str | None
    sub_activity_code: str
    sub_activity_name: str
    sub_activity_party: str
    classification: CostClassification
    vendor_id: str | None
    vendor_code: str
    vendor_name: str
    party_name: str
    quantity: Decimal
    quantity_unit: QuantityUnit
    captured_rate: Decimal
    override_rate: Decimal | None
    effective_rate: Decimal
    currency: str
    exchange_rate: Decimal
    amount: Decimal
    standard_amount: Decimal
    usd_exchange_rate: Decimal = Decimal("1")
    usd_amount: Decimal = Decimal("0")
    actual_depth: Decimal | None = None
    actual_depth_entered: Decimal | None = None
    actual_depth_unit: Literal["m", "ft"] = "m"
    depth_seq: int = 0
    rate_source: str
    rate_revision_number: int | None
    rate_effective_date: date | None
    baseline_budget_line_id: str | None
    budget_key: str
    budget_name: str
    override_reason: str
    remarks: str


class DailyCostServiceLineOut(DailyCostLineOut):
    cost_items: list[ServiceCostItemIn] = Field(default_factory=list)
    service_id: str
    service_code: str
    service_name: str
    service_group: str = ""
    charging_basis: ChargingBasis
    charge_category: ChargeCategory
    baseline_service_rate_id: str | None


class DailyCostConsumableLineOut(DailyCostLineOut):
    category: ConsumableCategory
    item_kind: ConsumableKind
    item_id: str
    item_code: str
    item_name: str
    uom: str
    catalogue_rate_snapshot_id: str | None


class DailyCostTangibleLineOut(DailyCostLineOut):
    tangible_id: str
    tangible_code: str
    tangible_name: str
    uom: str
    catalogue_rate_snapshot_id: str | None


class DailyCostOtherExpenseLineOut(DailyCostLineOut):
    """An unexpected charge. It has no AFE allowance and reduces the AFE amount."""

    expense_type: OtherExpenseType
    expense_type_label: str
    expense_description: str


class DailyCostComparisonGroup(BaseModel):
    cost_group: CostGroup
    planned: Decimal
    actual_to_date: Decimal
    balance: Decimal
    # The same actuals split by the activity classification each daily line was
    # recorded under, so a report can show planned, UPA and NPT side by side.
    # The three add up to ``actual_to_date``.
    actual_planned: Decimal = Decimal("0")
    actual_upa: Decimal = Decimal("0")
    actual_npt: Decimal = Decimal("0")


class DailyCostBudgetComparison(BaseModel):
    budget_key: str
    cost_group: CostGroup
    budget_kind: str
    item_code: str
    item_name: str
    # Reporting group snapshotted with the AFE allowance; empty for consumables,
    # tangibles and unbudgeted actuals.
    service_group: str = ""
    planned: Decimal
    actual_to_date: Decimal
    balance: Decimal
    is_planned: bool
    # ``actual_to_date`` split by the activity classification of the lines, so a
    # service-wise report can print actual under Planned / UPA / NPT. The three
    # always add up to ``actual_to_date``.
    actual_planned: Decimal = Decimal("0")
    actual_upa: Decimal = Decimal("0")
    actual_npt: Decimal = Decimal("0")


class DailyCostComparison(BaseModel):
    """The locked AFE plan against every actual recorded through the sheet date.

    ``actual_to_date`` covers all four cost groups, so ``balance`` is the AFE total
    less the tracked actuals **and** less the other expenses: unexpected charges
    such as Lost In Hole are deducted from the AFE amount rather than reconciled
    against a budget line. ``tracked_actual_to_date`` and ``other_expenses_to_date``
    keep the two halves visible.

    The manual LIH Cost Register adds a second explicit deduction. ``lih_cost_to_date``
    is the LIH cost filed against this AFE (cumulative through the sheet date), so
    ``actual_including_lih`` is the actual cost including LIH, ``afe_available`` is
    the AFE amount left after deducting LIH, and ``balance`` is that available
    amount less the daily actuals.

    When an approved SOW adjustment exists, ``adjusted_planned_total`` carries
    the revised AFE amount and ``adjusted_balance`` is that amount less actuals.
    ``planned_total`` always stays the locked (original) AFE total.
    """

    effective_on: date
    currency: str
    planned_total: Decimal
    actual_to_date: Decimal
    tracked_actual_to_date: Decimal
    other_expenses_to_date: Decimal
    # LIH register cost deducted from this AFE, kept separate from the daily groups.
    lih_cost_to_date: Decimal = Decimal("0")
    actual_including_lih: Decimal = Decimal("0")
    afe_available: Decimal = Decimal("0")
    balance: Decimal
    over_budget: bool
    includes_draft_entries: bool
    upa_to_date: Decimal
    npt_to_date: Decimal
    groups: list[DailyCostComparisonGroup]
    budget_lines: list[DailyCostBudgetComparison]
    adjusted_planned_total: Decimal | None = None
    adjusted_balance: Decimal | None = None
    has_adjustment: bool = False


class DailyCostSectionDepthOut(BaseModel):
    """Last depth value entered for a (date, well, section) in standardized metres."""

    hole_section_id: str | None = None
    section_code: str = ""
    section_name: str = ""
    actual_depth: Decimal
    depth_unit: Literal["m"] = "m"
    entered_depth: Decimal | None = None
    entered_unit: Literal["m", "ft"] = "m"
    daily_cost_code: str = ""


class DailyCostEntryOut(BaseModel):
    id: str
    daily_cost_code: str
    rig_id: str
    rig_code: str
    rig_name: str
    well_id: str
    well_code: str
    well_name: str
    afe_id: str
    afe_code: str
    afe_name: str
    afe_status: str
    cost_date: date
    standard_currency: str
    remarks: str
    status: Literal["draft", "submitted"]
    submitted_at: datetime | None
    submitted_by: str
    status_remarks: str
    services_count: int
    consumables_count: int
    tangibles_count: int
    other_expenses_count: int
    services_total: Decimal
    consumables_total: Decimal
    tangibles_total: Decimal
    other_expenses_total: Decimal
    total_cost: Decimal
    upa_total: Decimal
    npt_total: Decimal
    usd_exchange_rate: Decimal = Decimal("1")
    services_total_usd: Decimal = Decimal("0")
    consumables_total_usd: Decimal = Decimal("0")
    tangibles_total_usd: Decimal = Decimal("0")
    other_expenses_total_usd: Decimal = Decimal("0")
    total_cost_usd: Decimal = Decimal("0")
    upa_total_usd: Decimal = Decimal("0")
    npt_total_usd: Decimal = Decimal("0")
    actual_depth: Decimal | None = None
    depth_unit: Literal["m"] = "m"
    section_depths: list[DailyCostSectionDepthOut] = Field(default_factory=list)
    rate_baseline_locked_at: datetime
    budget_baseline_locked_at: datetime
    warning_count: int
    is_deleted: bool
    deleted_at: datetime | None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class DailyCostWarnings(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class DailyCostWellProgress(BaseModel):
    """Spud and progress milestones for one configuration scope of a well.

    Actual days count from the Well Spud Date & Time — not from the first
    daily cost sheet — up to the Progress Completed Date & Time once it is
    entered (the count then stops for that progress), otherwise up to the end
    of the last cost sheet date for that scope, in fractional days rounded to
    three decimals (a well spudded 10:00 counts 0.583 days on that date).
    ``days_variance`` is actual days less planned days for the scope.
    """

    scope: Literal["drilling", "completion"]
    scope_label: str
    progress_label: str
    spud_at: datetime | None
    progress_completed_at: datetime | None
    is_completed: bool
    planned_days: Decimal
    actual_days: Decimal | None
    days_variance: Decimal | None
    as_of_date: date | None


class DailyCostWellProgressReport(BaseModel):
    """Per-scope progress milestones for one well."""

    well_id: str
    well_code: str
    well_name: str
    scopes: list[DailyCostWellProgress]


class DailyCostWellProgressUpdate(BaseModel):
    """Enter or edit the register's spud / progress completion milestones.

    ``spud_at`` can be entered once and then only edited — it can never be
    cleared, so the actual day count always keeps a start point. Omitted
    fields keep their stored values.
    """

    scope: Literal["drilling", "completion"]
    spud_at: datetime | None = None
    progress_completed_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class DailyCostDayOut(BaseModel):
    entry: DailyCostEntryOut
    services: list[DailyCostServiceLineOut]
    consumables: list[DailyCostConsumableLineOut]
    tangibles: list[DailyCostTangibleLineOut]
    other_expenses: list[DailyCostOtherExpenseLineOut]
    comparison: DailyCostComparison
    warnings: list[DailyCostWarnings]
    # Milestones of the sheet's AFE scope, counted to the sheet's cost date.
    progress: DailyCostWellProgress | None = None


class DailyCostPreviewOut(BaseModel):
    services: list[DailyCostServiceLineOut]
    consumables: list[DailyCostConsumableLineOut]
    tangibles: list[DailyCostTangibleLineOut]
    other_expenses: list[DailyCostOtherExpenseLineOut]
    services_total: Decimal
    consumables_total: Decimal
    tangibles_total: Decimal
    other_expenses_total: Decimal
    total_cost: Decimal
    upa_total: Decimal
    npt_total: Decimal
    total_cost_usd: Decimal = Decimal("0")
    actual_depth: Decimal | None = None
    depth_unit: Literal["m"] = "m"
    section_depths: list[DailyCostSectionDepthOut] = Field(default_factory=list)
    warnings: list[DailyCostWarnings]


class DailyCostGroupSummary(BaseModel):
    currency: str
    cost_group: CostGroup
    planned: Decimal
    actual: Decimal
    balance: Decimal


class DailyCostTrendPoint(BaseModel):
    cost_date: date
    currency: str
    actual: Decimal
    upa: Decimal
    npt: Decimal


class DailyCostRecentActivity(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_label: str
    summary: str
    created_at: datetime


class DailyCostOverview(BaseModel):
    active_entries: int
    deleted_entries: int
    submitted_entries: int
    draft_entries: int
    wells_tracked: int
    active_baselines: int
    over_budget_afes: int
    total_planned_by_currency: dict[str, Decimal]
    actual_to_date_by_currency: dict[str, Decimal]
    remaining_by_currency: dict[str, Decimal]
    # LIH Cost Register totals stay separate from the AFE/daily figures above.
    lih_cost_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    lih_entries: int = 0
    lih_lines: int = 0
    groups: list[DailyCostGroupSummary]
    trend: list[DailyCostTrendPoint]
    recent_activity: list[DailyCostRecentActivity]


class DailyCostBulkActionResponse(BaseModel):
    affected_count: int


# ---------------------------------------------------------------------------
# Whole-well cost analysis (the daily ledger every reporting module builds on)
# ---------------------------------------------------------------------------


class DailyCostWellHeader(BaseModel):
    """Identity of the well, rig and tracked AFEs a summary belongs to."""

    id: str
    well_code: str
    well_name: str
    rig_code: str
    rig_name: str
    status: str
    config_status: str
    afes: list[DailyCostAfeOption]


class DailyCostAfePosition(BaseModel):
    """One AFE's locked budget against the actuals recorded under it.

    ``planned_total`` is the locked (original) AFE amount. When an approved
    SOW adjustment exists, ``adjusted_planned_total`` is the revised amount
    and ``adjusted_balance`` is that amount less actuals.
    """

    afe_id: str
    afe_code: str
    afe_name: str
    afe_status: str
    currency: str
    planned_total: Decimal
    actual: Decimal
    other_expenses: Decimal
    # LIH register cost filed against this AFE, deducted explicitly from its total.
    lih_cost: Decimal = Decimal("0")
    actual_including_lih: Decimal = Decimal("0")
    afe_available: Decimal = Decimal("0")
    balance: Decimal
    balance_including_lih: Decimal = Decimal("0")
    over_budget: bool
    sheets: int
    days_recorded: int
    first_day: date | None
    last_day: date | None
    adjusted_planned_total: Decimal | None = None
    adjusted_balance: Decimal | None = None
    has_adjustment: bool = False


class DailyCostDailyRow(BaseModel):
    """One well-day: the daily actuals and the running total against the AFE."""

    cost_date: date
    services: Decimal
    consumables: Decimal
    tangibles: Decimal
    other_expenses: Decimal
    total: Decimal
    upa: Decimal
    npt: Decimal
    cumulative: Decimal
    budget_balance: Decimal
    # LIH register cost for the day, its running total and the AFE balance after it.
    lih: Decimal = Decimal("0")
    cumulative_including_lih: Decimal = Decimal("0")
    budget_balance_including_lih: Decimal = Decimal("0")
    sheets: int
    status: Literal["draft", "submitted", "mixed"]
    adjusted_budget_balance: Decimal | None = None
    actual_depth: Decimal | None = None
    total_usd: Decimal = Decimal("0")
    cumulative_usd: Decimal = Decimal("0")


class DailyCostFactorRow(BaseModel):
    """One factor (activity, section, vendor, …) with its share of well spend."""

    key: str
    code: str
    name: str
    detail: str
    amount: Decimal
    planned: Decimal | None
    balance: Decimal | None
    share: Decimal
    quantity: Decimal


class DailyCostFactorGroup(BaseModel):
    """A named cut of the same ledger, e.g. by activity or by responsible party.

    Other-expense lines appear in ``item`` as their expense type (LIH, hole
    problem, …), because that is the only grouping that describes them.
    """

    dimension: Literal[
        "cost_group", "classification", "section", "phase", "activity", "sub_activity",
        "party", "rate_source", "currency", "item",
    ]
    label: str
    currency: str
    total: Decimal
    rows: list[DailyCostFactorRow]


class DailyCostMudSectionReconciliation(BaseModel):
    """One section's mud chemicals actual versus its reconciled mud cost."""

    section_id: str
    section_label: str
    mud_type: str | None = None
    mud_type_label: str = "Not configured"
    is_configured: bool = False
    is_wbm: bool = False
    currency: str = ""
    base_rate: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    reconciled_cost: Decimal | None = None
    cost_per_bbl: Decimal | None = None
    consumption_losses: Decimal = Decimal("0")
    adjustment: Decimal | None = None
    remarks: str = ""


class DailyCostMudReconciliation(BaseModel):
    """Section-scoped mud reconciliation projected into the well cost analysis.

    ``actual_cost`` is the mud chemicals spend recorded in the daily register.
    ``reconciled_cost`` values the mud system at its latest Cost/BBL. The final
    comparison uses ``comparison_cost``: reconciled where a section can be
    reconciled, actual where it cannot (unconfigured, no mud entries, or mud
    chemicals with no attributable section), so no recorded cost ever vanishes.
    """

    available: bool
    currency: str
    actual_cost: Decimal
    reconciled_cost: Decimal
    unreconciled_actual_cost: Decimal
    comparison_cost: Decimal
    adjustment: Decimal
    latest_cost_per_bbl: Decimal | None = None
    latest_cost_per_bbl_section: str = ""
    latest_cost_per_bbl_date: date | None = None
    configured_section_count: int = 0
    unconfigured_section_count: int = 0
    sections: list[DailyCostMudSectionReconciliation] = Field(default_factory=list)
    note: str = ""


class DailyCostWellTotals(BaseModel):
    currency: str
    planned: Decimal
    actual: Decimal
    balance: Decimal
    used_percent: Decimal
    services: Decimal
    consumables: Decimal
    tangibles: Decimal
    other_expenses: Decimal
    # Services actual split by the activity classification of the daily lines.
    services_actual_planned: Decimal = Decimal("0")
    services_actual_upa: Decimal = Decimal("0")
    services_actual_npt: Decimal = Decimal("0")
    upa: Decimal
    npt: Decimal
    planned_days: Decimal
    recorded_days: int
    elapsed_days: int
    average_per_day: Decimal
    days_to_budget: Decimal | None
    first_day: date | None
    last_day: date | None
    sheets: int
    draft_sheets: int
    submitted_sheets: int
    lines: int
    # Revised plan when approved SOW adjustments exist. Nulls mean no approved
    # adjustment, so callers use planned / planned_days above.
    adjusted_planned: Decimal | None = None
    adjusted_balance: Decimal | None = None
    adjusted_used_percent: Decimal | None = None
    adjusted_planned_days: Decimal | None = None
    has_adjustment: bool = False
    # Progress-day figures counted from the Well Spud Date & Time (summed over
    # the scopes that have a spud instant). Null means no scope is spudded yet.
    spud_actual_days: Decimal | None = None
    spud_days_variance: Decimal | None = None
    # Mud chemicals comparison. ``actual_mud_chemicals`` is the recorded Daily
    # Cost figure; ``comparison_mud_cost`` replaces it with the reconciled amount
    # where a section supports reconciliation. The comparison_* figures are what
    # the final AFE comparison uses, while ``actual`` above remains as recorded.
    actual_mud_chemicals: Decimal = Decimal("0")
    reconciled_mud_cost: Decimal = Decimal("0")
    comparison_mud_cost: Decimal = Decimal("0")
    mud_cost_adjustment: Decimal = Decimal("0")
    # LIH Cost Register: recorded separately, added to the actual cost and
    # deducted explicitly from the AFE amount in every comparison.
    lih_cost: Decimal = Decimal("0")
    lih_line_count: int = 0
    lih_entries: int = 0
    afe_available: Decimal = Decimal("0")
    actual_including_lih: Decimal = Decimal("0")
    comparison_actual_including_lih: Decimal = Decimal("0")
    comparison_balance_including_lih: Decimal = Decimal("0")
    comparison_used_percent_including_lih: Decimal = Decimal("0")
    comparison_adjusted_balance_including_lih: Decimal | None = None
    comparison_actual: Decimal | None = None
    comparison_consumables: Decimal | None = None
    comparison_balance: Decimal | None = None
    comparison_used_percent: Decimal | None = None
    comparison_adjusted_balance: Decimal | None = None
    has_mud_reconciliation: bool = False


class DailyCostLihDeduction(BaseModel):
    """LIH cost filed against one AFE, deducted from that AFE's total."""

    afe_id: str
    afe_code: str
    afe_name: str
    currency: str
    lih_cost: Decimal
    afes_total: Decimal = Decimal("0")


class DailyCostLihDay(BaseModel):
    """One LIH register day inside the well cost analysis."""

    entry_id: str
    cost_date: date
    afe_id: str | None = None
    afe_code: str = ""
    currency: str
    line_count: int
    total_cost: Decimal


class DailyCostLihSummary(BaseModel):
    """The well's LIH Cost Register, accounted apart from the daily cost groups.

    ``total`` is added to the actual cost and deducted from the AFE amount. The
    register is never folded into a service, consumable or tangible budget line.
    """

    available: bool
    currency: str
    total: Decimal = Decimal("0")
    line_count: int = 0
    entry_count: int = 0
    deductions_by_afe: list[DailyCostLihDeduction] = Field(default_factory=list)
    days: list[DailyCostLihDay] = Field(default_factory=list)


class DailyCostWellSummary(BaseModel):
    """Everything captured from the AFE and the daily sheets, costed for the whole well.

    Every figure is a plain column-wise aggregation of the daily line tables, in the
    AFE standard currency (with native-currency amounts under `currency`), so cost
    analysis and reporting modules can read one stable shape.
    """

    well: DailyCostWellHeader
    from_date: date | None
    to_date: date | None
    as_of: date | None
    include_draft: bool
    totals: DailyCostWellTotals
    afes: list[DailyCostAfePosition]
    daily: list[DailyCostDailyRow]
    factors: list[DailyCostFactorGroup]
    budget_lines: list[DailyCostBudgetComparison]
    warnings: list[DailyCostWarnings]
    # One milestone block per configuration scope, counted to today.
    progress: list[DailyCostWellProgress] = Field(default_factory=list)
    # Present when the well has daily cost sheets: the section-by-section
    # actual vs reconciled mud cost used by the final comparison.
    mud_cost: DailyCostMudReconciliation | None = None
    # Present whenever the well has LIH register entries in the reported window.
    lih_cost: DailyCostLihSummary | None = None


DailyCostDayOut.model_rebuild()
DailyCostPreviewOut.model_rebuild()
