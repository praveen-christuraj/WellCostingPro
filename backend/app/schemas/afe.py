"""Typed API contracts for the AFE register and AFE cost estimation."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.afe_costing import CHARGE_CATEGORIES, CHARGING_BASES, CONSUMABLE_CATEGORIES

AfeType = Literal["Drilling", "Completion"]
AfeStatusAction = Literal["submit", "review", "approve", "reopen"]
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
ChargingBasis = Literal["Day Rate", "Per Service Rate", "Per Section Rate"]
ConsumableCategory = Literal["Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits"]
QuantityUnit = Literal["days", "hours"]

assert set(CHARGE_CATEGORIES) == set(ChargeCategory.__args__)  # keep Literal in step with the engine
assert set(CHARGING_BASES) == set(ChargingBasis.__args__)
assert set(CONSUMABLE_CATEGORIES) == set(ConsumableCategory.__args__)

MAX_LINES = 500


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# AFE header
# ---------------------------------------------------------------------------


class AfeCreate(BaseModel):
    configuration_scope: Literal["drilling", "completion"] = "drilling"
    rig_id: str = Field(min_length=1, max_length=36)
    well_id: str = Field(min_length=1, max_length=36)
    afe_code: str = Field(min_length=1, max_length=50)
    afe_name: str = Field(min_length=1, max_length=200)
    afe_type: AfeType
    remarks: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("afe_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("afe_name", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class AfeUpdate(BaseModel):
    """Header edits are allowed only while the AFE is a draft."""

    configuration_scope: Literal["drilling", "completion"] | None = None

    rig_id: str | None = Field(default=None, min_length=1, max_length=36)
    well_id: str | None = Field(default=None, min_length=1, max_length=36)
    afe_code: str | None = Field(default=None, min_length=1, max_length=50)
    afe_name: str | None = Field(default=None, min_length=1, max_length=200)
    afe_type: AfeType | None = None
    remarks: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("afe_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("afe_name", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class AfeStatusIn(BaseModel):
    action: AfeStatusAction
    remarks: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim(value)


class AfeOut(BaseModel):
    configuration_scope: Literal["drilling", "completion"] = "drilling"
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    well_id: str
    well_code: str
    well_name: str
    well_status: str
    afe_code: str
    afe_name: str
    afe_type: str
    remarks: str
    status: str
    status_remarks: str
    status_changed_at: datetime | None
    status_changed_by: str
    estimate_saved_at: datetime | None
    estimate_saved_by: str
    service_count: int
    consumable_count: int
    tangible_count: int
    services_total: Decimal | None  # standard currency; null while a conversion rate is missing
    consumables_total: Decimal | None
    tangibles_total: Decimal | None
    total_cost: Decimal | None
    standard_currency: str
    conversion_pending: bool
    totals_by_currency: list["CurrencyTotalOut"]
    warning_count: int
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AfeIDs(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class AfeBulkActionResponse(BaseModel):
    affected_count: int


class AfeImportRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class AfeImportResponse(BaseModel):
    imported_count: int
    error_count: int
    errors: list[str]
    success: bool


class AfeExportAudit(BaseModel):
    module: Literal["afes", "estimates", "deleted", "afe-print", "estimate-print"]
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=1_000_000)
    include_deleted: bool = False

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Estimate input (request side)
# ---------------------------------------------------------------------------


class RateIn(BaseModel):
    category: ChargeCategory
    unit_rate: Decimal = Field(ge=0, le=Decimal("100000000"))

    model_config = ConfigDict(extra="forbid")


class ChargeIn(BaseModel):
    category: ChargeCategory
    quantity: Decimal = Field(ge=0, le=Decimal("100000"))
    quantity_unit: QuantityUnit = "days"

    model_config = ConfigDict(extra="forbid")


class SectionRateIn(BaseModel):
    hole_section_id: str = Field(min_length=1, max_length=36)
    phase_id: str | None = Field(default=None, max_length=36)
    amount: Decimal = Field(ge=0, le=Decimal("100000000000"))

    model_config = ConfigDict(extra="forbid")


class ServiceLineIn(BaseModel):
    client_key: str | None = Field(default=None, max_length=64)
    service_id: str = Field(min_length=1, max_length=36)
    charging_basis: ChargingBasis
    hole_section_id: str | None = Field(default=None, max_length=36)
    phase_id: str | None = Field(default=None, max_length=36)
    currency: str = Field(default="", max_length=10)
    service_amount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000000"))
    remarks: str = Field(default="", max_length=500)
    rates: list[RateIn] = Field(default_factory=list, max_length=8)
    charges: list[ChargeIn] = Field(default_factory=list, max_length=50)
    section_rates: list[SectionRateIn] = Field(default_factory=list, max_length=200)

    model_config = ConfigDict(extra="forbid")

    @field_validator("currency", mode="before")
    @classmethod
    def upper_currency(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("hole_section_id", "phase_id", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        value = _trim(value)
        return value or None


class ConsumableLineIn(BaseModel):
    client_key: str | None = Field(default=None, max_length=64)
    category: ConsumableCategory
    hole_section_id: str = Field(min_length=1, max_length=36)
    phase_id: str | None = Field(default=None, max_length=36)
    drill_bit_id: str | None = Field(default=None, max_length=36)
    quantity: Decimal = Field(default=Decimal("1"), ge=0, le=Decimal("1000000"))
    override_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    estimated_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000000"))
    currency: str = Field(default="", max_length=10)
    remarks: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("currency", mode="before")
    @classmethod
    def upper_currency(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("phase_id", "drill_bit_id", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        value = _trim(value)
        return value or None


class TangibleLineIn(BaseModel):
    client_key: str | None = Field(default=None, max_length=64)
    tangible_id: str = Field(min_length=1, max_length=36)
    quantity: Decimal = Field(default=Decimal("1"), ge=0, le=Decimal("1000000"))
    override_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("100000000"))
    remarks: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class ExchangeRateIn(BaseModel):
    """Units of the standard currency per one unit of ``currency_code``."""

    currency_code: str = Field(max_length=10)
    rate: Decimal = Field(gt=0, max_digits=18, decimal_places=6)

    model_config = ConfigDict(extra="forbid")

    @field_validator("currency_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _upper(value)


class EstimateIn(BaseModel):
    services: list[ServiceLineIn] = Field(default_factory=list, max_length=MAX_LINES)
    consumables: list[ConsumableLineIn] = Field(default_factory=list, max_length=MAX_LINES)
    tangibles: list[TangibleLineIn] = Field(default_factory=list, max_length=MAX_LINES)
    # Only used when the estimate mixes currencies. Ignored for a single currency.
    standard_currency: str = Field(default="", max_length=10)
    exchange_rates: list[ExchangeRateIn] = Field(default_factory=list, max_length=50)

    model_config = ConfigDict(extra="forbid")

    @field_validator("standard_currency", mode="before")
    @classmethod
    def upper_standard(cls, value: Any) -> Any:
        return _upper(value)

    @model_validator(mode="after")
    def unique_rate_currencies(self) -> "EstimateIn":
        codes = [rate.currency_code for rate in self.exchange_rates]
        if len(codes) != len(set(codes)):
            raise ValueError("Each currency can have only one conversion rate.")
        return self


# ---------------------------------------------------------------------------
# Estimate output (response side)
# ---------------------------------------------------------------------------


class CurrencyTotalOut(BaseModel):
    currency: str
    amount: Decimal


class ExchangeRateOut(BaseModel):
    currency_code: str
    rate: Decimal


class CurrencySetupOut(BaseModel):
    standard_currency: str
    currencies: list[str]
    multi_currency: bool
    converted: bool
    standard_missing: bool
    missing_rates: list[str]
    exchange_rates: list[ExchangeRateOut]


class ComponentOut(BaseModel):
    group: str
    category: str
    description: str
    amount: Decimal
    section_id: str | None
    section_label: str
    phase_id: str | None
    phase_label: str
    quantity: Decimal | None
    rate: Decimal | None
    unit: str


class RateOut(BaseModel):
    category: str
    unit_rate: Decimal


class ChargeOut(BaseModel):
    category: str
    quantity: Decimal
    quantity_unit: str


class SectionRateOut(BaseModel):
    hole_section_id: str
    section_label: str
    phase_id: str | None
    phase_label: str
    amount: Decimal


class ServiceLineOut(BaseModel):
    id: str | None
    client_key: str | None
    service_id: str
    service_code: str
    service_name: str
    service_category: str
    provider_type: str
    vendor_name: str
    charging_basis: str
    hole_section_id: str | None
    section_label: str
    phase_id: str | None
    phase_label: str
    currency: str
    service_amount: Decimal
    remarks: str
    rates: list[RateOut]
    charges: list[ChargeOut]
    section_rates: list[SectionRateOut]
    amount: Decimal
    warnings: list[str]
    components: list[ComponentOut]


class ConsumableLineOut(BaseModel):
    id: str | None
    client_key: str | None
    category: str
    hole_section_id: str
    section_label: str
    phase_id: str | None
    phase_label: str
    drill_bit_id: str | None
    bit_code: str
    bit_name: str
    bit_type: str
    manufacturer: str
    model_no: str
    size: str
    iadc_code: str
    serial_number: str
    bit_description: str
    quantity: Decimal
    captured_rate: Decimal
    override_rate: Decimal | None
    effective_rate: Decimal | None
    estimated_amount: Decimal | None
    currency: str
    remarks: str
    amount: Decimal
    warnings: list[str]
    components: list[ComponentOut]


class TangibleLineOut(BaseModel):
    id: str | None
    client_key: str | None
    tangible_id: str
    tangible_code: str
    tangible_name: str
    tangible_scope: str
    category_name: str
    subcategory_name: str
    manufacturer_name: str
    tangible_description: str
    uom: str
    quantity: Decimal
    captured_rate: Decimal
    override_rate: Decimal | None
    effective_rate: Decimal
    currency: str
    remarks: str
    amount: Decimal
    warnings: list[str]
    components: list[ComponentOut]


class SectionSummaryOut(BaseModel):
    hole_section_id: str | None
    label: str
    planned_days: Decimal
    services: Decimal | None
    consumables: Decimal | None
    tangibles: Decimal | None
    total: Decimal | None


class EstimateSummaryOut(BaseModel):
    # Converted figures are in the standard currency. They are null while a rate is missing.
    services_total: Decimal | None
    consumables_total: Decimal | None
    tangibles_total: Decimal | None
    total: Decimal | None
    totals_by_currency: list[CurrencyTotalOut]  # as entered, one per currency
    currency: CurrencySetupOut
    by_section: list[SectionSummaryOut]
    warnings: list[str]


class ScopePhaseOut(BaseModel):
    phase_id: str
    phase_code: str
    phase_name: str
    days: Decimal


class ScopeSectionOut(BaseModel):
    hole_section_id: str
    section_code: str
    section_name: str
    from_depth: Decimal
    to_depth: Decimal
    total_days: Decimal
    phases: list[ScopePhaseOut]


class WellScopeOut(BaseModel):
    scope: Literal["drilling", "completion"] = "drilling"
    well_id: str
    well_code: str
    well_name: str
    well_location: str
    block: str
    objective: str
    rig_code: str
    rig_name: str
    depth_unit: str
    status: str
    config_status: str
    total_depth: Decimal | None
    total_days: Decimal
    sections: list[ScopeSectionOut]


class AfeEstimateOut(BaseModel):
    afe: AfeOut
    well: WellScopeOut
    services: list[ServiceLineOut]
    consumables: list[ConsumableLineOut]
    tangibles: list[TangibleLineOut]
    summary: EstimateSummaryOut
    persisted: bool
    saved_at: datetime | None
    saved_by: str


class AfeOverviewStatus(BaseModel):
    status: str
    label: str
    count: int


class AfeOverviewWell(BaseModel):
    well_id: str
    label: str
    total: Decimal
    currency: str


class AfeOverview(BaseModel):
    active_afes: int
    deleted_afes: int
    drilling_afes: int
    completion_afes: int
    approved_afes: int
    wells_with_afes: int
    totals_by_currency: list["CurrencyTotalOut"]
    approved_by_currency: list["CurrencyTotalOut"]
    conversion_pending_afes: int
    statuses: list[AfeOverviewStatus]
    top_wells: list[AfeOverviewWell]
    warning_afes: int
    recent_activity: list["AfeRecentActivity"]


class AfeRecentActivity(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_label: str
    summary: str
    created_at: datetime


class AfeImportHeadersOut(BaseModel):
    required: list[str]
    optional: list[str]


class AfeReferenceRig(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    display_name: str


class AfeReferenceWell(BaseModel):
    completion_config_status: str = "draft"
    completion_status: str = "active"
    completion_section_count: int = 0
    id: str
    rig_id: str
    well_code: str
    well_name: str
    display_name: str
    status: str
    config_status: str
    total_days: Decimal
    total_depth: Decimal | None
    depth_unit: str
    section_count: int


class AfeReferenceService(BaseModel):
    id: str
    service_code: str
    service_name: str
    service_category: str
    provider_type: str
    vendor_name: str
    display_name: str
    description: str


class AfeReferenceTangible(BaseModel):
    id: str
    tangible_code: str
    tangible_name: str
    scope: str
    category_name: str
    subcategory_name: str
    manufacturer_name: str
    description: str
    uom: str
    unit_rate: Decimal
    final_cost: Decimal | None
    captured_rate: Decimal
    currency: str
    display_name: str


class AfeReferenceDrillBit(BaseModel):
    id: str
    bit_code: str
    bit_name: str
    bit_type: str
    manufacturer_name: str
    model_no: str
    size: str
    iadc_code: str
    serial_number: str
    description: str
    captured_rate: Decimal
    currency: str
    display_name: str


class AfeReference(BaseModel):
    rigs: list[AfeReferenceRig]
    wells: list[AfeReferenceWell]
    services: list[AfeReferenceService]
    tangibles: list[AfeReferenceTangible]
    drill_bits: list[AfeReferenceDrillBit]
    currencies: list[dict[str, str]]
    afe_types: list[str]
    charging_bases: list[str]
    charge_categories: list[str]
    one_time_categories: list[str]
    consumable_categories: list[str]
    statuses: list[str]


AfeOut.model_rebuild()
AfeOverview.model_rebuild()
AfeEstimateOut.model_rebuild()
