"""Typed API contracts for AFE SOW adjustments and well plan adjustments."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SowStatus = Literal["draft", "approved", "void"]
SowScope = Literal["drilling", "completion"]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class AfeSowAdjustmentCreate(BaseModel):
    """Revised group totals in the AFE standard currency.

    The adjusted total is the sum of the three groups and is computed
    server-side. ``sow_summary`` should name the services, consumables or
    tangibles that were added or removed.
    """

    adjusted_services_total: Decimal = Field(ge=Decimal("0"), le=Decimal("9999999999999999.99"))
    adjusted_consumables_total: Decimal = Field(ge=Decimal("0"), le=Decimal("9999999999999999.99"))
    adjusted_tangibles_total: Decimal = Field(ge=Decimal("0"), le=Decimal("9999999999999999.99"))
    reason: str = Field(min_length=3, max_length=500)
    sow_summary: str = Field(default="", max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class AfeSowAdjustmentUpdate(BaseModel):
    """Draft-only edits to a recorded adjustment."""

    adjusted_services_total: Decimal | None = Field(default=None, ge=Decimal("0"))
    adjusted_consumables_total: Decimal | None = Field(default=None, ge=Decimal("0"))
    adjusted_tangibles_total: Decimal | None = Field(default=None, ge=Decimal("0"))
    reason: str | None = Field(default=None, min_length=3, max_length=500)
    sow_summary: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


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


class WellPlanAdjustmentCreate(BaseModel):
    """Revised planned days for one well scope.

    ``planned_days_after`` is the new plan total in days. ``sow_summary``
    should describe added/removed sections or phases and day changes.
    ``section_count_after`` records how many sections the revised plan holds.
    """

    configuration_scope: SowScope = "drilling"
    planned_days_after: Decimal = Field(ge=Decimal("0"), le=Decimal("1000000"))
    section_count_after: int = Field(default=0, ge=0, le=500)
    reason: str = Field(min_length=3, max_length=500)
    sow_summary: str = Field(default="", max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class WellPlanAdjustmentUpdate(BaseModel):
    planned_days_after: Decimal | None = Field(default=None, ge=Decimal("0"))
    section_count_after: int | None = Field(default=None, ge=0, le=500)
    reason: str | None = Field(default=None, min_length=3, max_length=500)
    sow_summary: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", "sow_summary", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


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
    well_code: str = ""
    well_name: str = ""
    created_by: str
    approved_by: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
