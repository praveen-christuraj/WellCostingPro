"""Typed API contracts for AFE SOW adjustments and well plan adjustments.

Both adjustments are entered through the same modules as the records they
revise. A well plan adjustment carries the well-configuration grid (sections
with hole section, depths and phases with planned days); an AFE SOW adjustment
carries the AFE estimate lines (services with rate cards, consumables and
tangibles) plus the currency setup they are priced with. Every line has a
``pair_key`` linking the revised (``after``) entry to the entered (``before``)
value it replaces; lines added by the revision have no before counterpart.

Planned days, section counts and cost-group totals are never typed in: they
are derived server-side from the revision lines.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.precision import Decimal10, Decimal10Days
from app.schemas.afe import (
    ConsumableLineIn,
    ConsumableLineOut,
    EstimateSummaryOut,
    ExchangeRateIn,
    ServiceLineIn,
    ServiceLineOut,
    TangibleLineIn,
    TangibleLineOut,
)

SowStatus = Literal["draft", "approved", "void"]
SowScope = Literal["drilling", "completion"]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _trim_optional(value: Any) -> Any:
    value = _trim(value)
    return value or None if isinstance(value, str) else value


# ---------------------------------------------------------------------------
# Well plan adjustment — the well-configuration grid, entered as a revision
# ---------------------------------------------------------------------------


class PlanPhaseIn(BaseModel):
    """One revised (or added) phase row of the plan grid."""

    pair_key: str | None = Field(default=None, max_length=64)
    phase_id: str = Field(min_length=1, max_length=36)
    days: Decimal10Days = Field(ge=Decimal("0"))
    remarks: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value) or ""


class PlanSectionIn(BaseModel):
    """One revised (or added) section row of the plan grid."""

    pair_key: str | None = Field(default=None, max_length=64)
    hole_section_id: str = Field(min_length=1, max_length=36)
    from_depth: Decimal10 = Field(ge=Decimal("0"))
    to_depth: Decimal10 = Field(ge=Decimal("0"))
    remarks: str = Field(default="", max_length=1000)
    phases: list[PlanPhaseIn] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value) or ""


class WellPlanAdjustmentCreate(BaseModel):
    """A revised plan grid for one well scope.

    ``sections`` holds the revised entries exactly as the well configuration
    would be entered: hole sections with depths and at least one phase each.
    Planned days and the section count are derived from this grid. ``pair_key``
    links each revised row to the configured row it replaces; rows without one
    are additions.
    """

    configuration_scope: SowScope = "drilling"
    sections: list[PlanSectionIn] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=3, max_length=500)
    sow_summary: str = Field(default="", max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class WellPlanAdjustmentUpdate(BaseModel):
    """Draft-only edits: replace the revised grid and/or the narrative."""

    sections: list[PlanSectionIn] | None = Field(default=None, min_length=1, max_length=50)
    reason: str | None = Field(default=None, min_length=3, max_length=500)
    sow_summary: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class PlanPhaseOut(BaseModel):
    pair_key: str
    plan_side: str
    phase_id: str
    phase_code: str = ""
    phase_name: str = ""
    days: Decimal
    remarks: str = ""
    # Set on after rows that pair with a before row: 'kept', 'modified',
    # 'added'. Before rows carry 'kept'/'modified'/'removed'.
    change: str = "kept"

    model_config = ConfigDict(from_attributes=True)


class PlanSectionOut(BaseModel):
    pair_key: str
    plan_side: str
    hole_section_id: str
    section_code: str = ""
    section_name: str = ""
    from_depth: Decimal
    to_depth: Decimal
    remarks: str = ""
    total_days: Decimal
    change: str = "kept"
    phases: list[PlanPhaseOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WellPlanAdjustmentOut(BaseModel):
    id: str
    well_id: str
    configuration_scope: str
    revision_number: int
    status: str
    reason: str
    sow_summary: str
    planned_days_before: Decimal
    planned_days_after: Decimal
    delta_days: Decimal
    section_count_before: int
    section_count_after: int
    # The two-sided revision grid: before rows snapshot the entered values,
    # after rows hold the revised entries (removed rows appear on the before
    # side only, added rows on the after side only).
    sections_before: list[PlanSectionOut] = Field(default_factory=list)
    sections_after: list[PlanSectionOut] = Field(default_factory=list)
    depth_unit: str = "m"
    well_code: str = ""
    well_name: str = ""
    created_by: str
    approved_by: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# AFE SOW adjustment — the AFE estimate modules, entered as a revision
# ---------------------------------------------------------------------------


class AfeSowServiceLineIn(ServiceLineIn):
    """One revised (or added) service line; ``pair_key`` links to the entered line."""

    pair_key: str | None = Field(default=None, max_length=64)


class AfeSowConsumableLineIn(ConsumableLineIn):
    pair_key: str | None = Field(default=None, max_length=64)


class AfeSowTangibleLineIn(TangibleLineIn):
    pair_key: str | None = Field(default=None, max_length=64)


class AfeSowLinesIn(BaseModel):
    """The revised estimate entry: the same modules as the AFE estimate."""

    standard_currency: str = Field(default="", max_length=10)
    exchange_rates: list[ExchangeRateIn] = Field(default_factory=list, max_length=50)
    services: list[AfeSowServiceLineIn] = Field(default_factory=list, max_length=500)
    consumables: list[AfeSowConsumableLineIn] = Field(default_factory=list, max_length=500)
    tangibles: list[AfeSowTangibleLineIn] = Field(default_factory=list, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("standard_currency", mode="before")
    @classmethod
    def upper_currency(cls, value: Any) -> Any:
        value = _trim(value)
        return value.upper() if isinstance(value, str) else value


class AfeSowAdjustmentCreate(AfeSowLinesIn):
    """A revised estimate for one AFE.

    The three line modules mirror the AFE estimate entry exactly (service
    lines with rates/charges/section rates, consumables, tangibles) plus the
    conversion setup used to price them. Adjusted group totals are derived
    server-side from these lines in the standard currency. ``pair_key`` links
    each revised line to the entered line it replaces; lines without one are
    additions.
    """

    reason: str = Field(min_length=3, max_length=500)
    sow_summary: str = Field(default="", max_length=2000)

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class AfeSowAdjustmentUpdate(AfeSowLinesIn):
    """Draft-only edits: replace the revised lines and/or the narrative."""

    reason: str | None = Field(default=None, min_length=3, max_length=500)
    sow_summary: str | None = Field(default=None, max_length=2000)

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class AfeSowBundleOut(BaseModel):
    """One priced side of the revision, in the shapes of the estimate modules."""

    services: list[ServiceLineOut] = Field(default_factory=list)
    consumables: list[ConsumableLineOut] = Field(default_factory=list)
    tangibles: list[TangibleLineOut] = Field(default_factory=list)
    summary: EstimateSummaryOut


class AfeSowAdjustmentOut(BaseModel):
    id: str
    afe_id: str
    well_id: str
    rig_id: str
    configuration_scope: str
    revision_number: int
    status: str
    reason: str
    sow_summary: str
    standard_currency: str
    original_services_total: Decimal | None
    original_consumables_total: Decimal | None
    original_tangibles_total: Decimal | None
    original_total: Decimal | None
    adjusted_services_total: Decimal
    adjusted_consumables_total: Decimal
    adjusted_tangibles_total: Decimal
    adjusted_total: Decimal
    delta_total: Decimal
    # The two-sided revision lines, priced exactly as each side was entered.
    before: AfeSowBundleOut | None = None
    after: AfeSowBundleOut | None = None
    # Identification snapshots so history lists read without extra lookups.
    afe_code: str = ""
    afe_name: str = ""
    well_code: str = ""
    well_name: str = ""
    created_by: str
    approved_by: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AfeSowAdjustmentPreviewOut(BaseModel):
    """A priced, not-yet-saved revision: the after side plus derived totals."""

    standard_currency: str
    services: list[ServiceLineOut] = Field(default_factory=list)
    consumables: list[ConsumableLineOut] = Field(default_factory=list)
    tangibles: list[TangibleLineOut] = Field(default_factory=list)
    summary: EstimateSummaryOut
    adjusted_services_total: Decimal
    adjusted_consumables_total: Decimal
    adjusted_tangibles_total: Decimal
    adjusted_total: Decimal


class SowApprovalIn(BaseModel):
    """Approval remarks are optional; the reason for the adjustment itself is mandatory at creation."""

    remarks: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class DailyCostAmendmentOut(BaseModel):
    id: str
    entry_id: str
    well_id: str
    afe_id: str
    amendment_number: int
    cost_date: date
    days_after_cost_date: int
    reason: str
    reopened_by: str
    reopened_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WellAdjustedSummary(BaseModel):
    """Effective (latest approved) adjustments for one well, for reporting.

    Absent adjustments are null so callers fall back to the original AFE
    total and the configured planned days.
    """

    well_id: str
    configuration_scope: str = "drilling"
    planned_days_before: Decimal | None = None
    planned_days_after: Decimal | None = None
    has_plan_adjustment: bool = False
    plan_revision: int | None = None
    # Per-AFE effective cost adjustments keyed by AFE id.
    afe_adjustments: dict[str, AfeSowAdjustmentOut] = Field(default_factory=dict)
