"""Typed API contracts for Tangibles, Consumables and the Catalogue Lists.

Rate fields (rate, uplift, currency, PO number, effective date) never change
through the plain update endpoints: they change only through a rate revision
that carries a reason, so the price history stays complete.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TangibleScope = Literal["Drilling", "Completion", "Others"]
MAX_RATE = Decimal("999999999999")
MAX_UPLIFT = Decimal("100000")


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _blank_to_none(value: Any) -> Any:
    value = _trim(value)
    return None if value == "" else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Catalogue Lists (user-managed dropdown values)
# ---------------------------------------------------------------------------


class CatalogueOptionCreate(_Strict):
    list_key: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=120)
    parent_id: str | None = Field(default=None, max_length=36)

    @field_validator("list_key", "value", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("parent_id", mode="before")
    @classmethod
    def blank_parent(cls, value: Any) -> Any:
        return _blank_to_none(value)


class CatalogueOptionBulkCreate(_Strict):
    list_key: str = Field(min_length=1, max_length=40)
    values: list[str] = Field(min_length=1, max_length=300)
    parent_id: str | None = Field(default=None, max_length=36)

    @field_validator("list_key", mode="before")
    @classmethod
    def trim_key(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("parent_id", mode="before")
    @classmethod
    def blank_parent(cls, value: Any) -> Any:
        return _blank_to_none(value)


class CatalogueOptionUpdate(_Strict):
    value: str = Field(min_length=1, max_length=120)

    @field_validator("value", mode="before")
    @classmethod
    def trim_value(cls, value: Any) -> Any:
        return _trim(value)


class CatalogueOptionOut(BaseModel):
    id: str
    list_key: str
    list_label: str
    value: str
    parent_id: str | None = None
    parent_value: str | None = None
    usage_count: int
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CatalogueListSummary(BaseModel):
    key: str
    label: str
    parent_key: str | None = None
    parent_label: str | None = None
    active_count: int
    removed_count: int
    usage_count: int


class CatalogueBulkCreateResult(BaseModel):
    created_count: int
    skipped: list[str]


# ---------------------------------------------------------------------------
# Shared rate revision output
# ---------------------------------------------------------------------------


class RateRevisionOut(BaseModel):
    id: str
    item_type: str
    item_id: str
    item_code: str
    item_name: str
    revision_number: int
    effective_date: date
    unit_rate: Decimal
    previous_unit_rate: Decimal
    cost_uplift: Decimal | None = None
    final_cost: Decimal | None = None
    previous_final_cost: Decimal | None = None
    currency: str
    uom: str
    po_number: str
    reason: str
    recorded_by: str
    created_at: datetime


class BreakdownItem(BaseModel):
    key: str
    label: str
    count: int


class PricedItemOverview(BaseModel):
    active_count: int
    deleted_count: int
    revisions_last_30_days: int
    breakdown_label: str | None = None
    breakdown: list[BreakdownItem]
    recent_revisions: list[RateRevisionOut]


# ---------------------------------------------------------------------------
# Tangibles
# ---------------------------------------------------------------------------


class TangibleCreate(_Strict):
    tangible_code: str = Field(min_length=1, max_length=50)
    tangible_name: str = Field(min_length=1, max_length=200)
    scope: TangibleScope
    category_id: str = Field(min_length=1, max_length=36)
    subcategory_id: str = Field(min_length=1, max_length=36)
    manufacturer_id: str = Field(min_length=1, max_length=36)
    uom: str = Field(default="", max_length=50)
    po_number: str = Field(default="", max_length=100)
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    cost_uplift: Decimal = Field(default=Decimal("100"), ge=0, le=MAX_UPLIFT)
    currency: str = Field(min_length=1, max_length=10)
    effective_date: date | None = None
    description: str = Field(default="", max_length=500)
    remarks: str = Field(default="", max_length=500)

    @field_validator("tangible_code", "tangible_name", "uom", "po_number", "currency", "description", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def blank_date(cls, value: Any) -> Any:
        return _blank_to_none(value)


class TangibleUpdate(_Strict):
    tangible_code: str | None = Field(default=None, min_length=1, max_length=50)
    tangible_name: str | None = Field(default=None, min_length=1, max_length=200)
    scope: TangibleScope | None = None
    category_id: str | None = Field(default=None, min_length=1, max_length=36)
    subcategory_id: str | None = Field(default=None, min_length=1, max_length=36)
    manufacturer_id: str | None = Field(default=None, min_length=1, max_length=36)
    uom: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    remarks: str | None = Field(default=None, max_length=500)

    @field_validator("tangible_code", "tangible_name", "uom", "description", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class TangibleOut(BaseModel):
    id: str
    tangible_code: str
    tangible_name: str
    scope: str
    category_id: str
    category_name: str | None = None
    subcategory_id: str
    subcategory_name: str | None = None
    manufacturer_id: str
    manufacturer_name: str | None = None
    uom: str
    unit_rate: Decimal
    cost_uplift: Decimal | None = None
    final_cost: Decimal | None = None
    currency: str
    po_number: str
    effective_date: date | None = None
    current_revision_number: int
    description: str
    remarks: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Drill bits (tangible-style pricing, consumable classification)
# ---------------------------------------------------------------------------


class DrillBitCreate(_Strict):
    bit_code: str = Field(min_length=1, max_length=50)
    bit_name: str = Field(min_length=1, max_length=200)
    bit_type_id: str = Field(min_length=1, max_length=36)
    manufacturer_id: str = Field(min_length=1, max_length=36)
    model_no: str = Field(min_length=1, max_length=100)
    size: str = Field(min_length=1, max_length=60)
    iadc_code: str = Field(default="", max_length=20)
    serial_number: str = Field(default="", max_length=100)
    po_number: str = Field(default="", max_length=100)
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    cost_uplift: Decimal = Field(default=Decimal("100"), ge=0, le=MAX_UPLIFT)
    currency: str = Field(min_length=1, max_length=10)
    effective_date: date | None = None
    description: str = Field(default="", max_length=500)
    remarks: str = Field(default="", max_length=500)

    @field_validator(
        "bit_code", "bit_name", "model_no", "size", "iadc_code", "serial_number",
        "po_number", "currency", "description", "remarks", mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def blank_date(cls, value: Any) -> Any:
        return _blank_to_none(value)


class DrillBitUpdate(_Strict):
    bit_code: str | None = Field(default=None, min_length=1, max_length=50)
    bit_name: str | None = Field(default=None, min_length=1, max_length=200)
    bit_type_id: str | None = Field(default=None, min_length=1, max_length=36)
    manufacturer_id: str | None = Field(default=None, min_length=1, max_length=36)
    model_no: str | None = Field(default=None, min_length=1, max_length=100)
    size: str | None = Field(default=None, min_length=1, max_length=60)
    iadc_code: str | None = Field(default=None, max_length=20)
    serial_number: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    remarks: str | None = Field(default=None, max_length=500)

    @field_validator(
        "bit_code", "bit_name", "model_no", "size", "iadc_code", "serial_number", "description", "remarks", mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class DrillBitOut(BaseModel):
    id: str
    bit_code: str
    bit_name: str
    bit_type_id: str
    bit_type_name: str | None = None
    manufacturer_id: str
    manufacturer_name: str | None = None
    model_no: str
    size: str
    iadc_code: str
    serial_number: str
    unit_rate: Decimal
    cost_uplift: Decimal | None = None
    final_cost: Decimal | None = None
    currency: str
    po_number: str
    effective_date: date | None = None
    current_revision_number: int
    description: str
    remarks: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Mud chemicals and cement additives (unit-rate pricing)
# ---------------------------------------------------------------------------


class MudChemicalCreate(_Strict):
    chemical_code: str = Field(min_length=1, max_length=50)
    chemical_name: str = Field(min_length=1, max_length=200)
    group_id: str = Field(min_length=1, max_length=36)
    manufacturer_id: str | None = Field(default=None, max_length=36)
    part_number: str = Field(default="", max_length=100)
    uom: str = Field(default="", max_length=50)
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    currency: str = Field(min_length=1, max_length=10)
    po_number: str = Field(default="", max_length=100)
    effective_date: date | None = None
    description: str = Field(default="", max_length=500)
    remarks: str = Field(default="", max_length=500)

    @field_validator(
        "chemical_code", "chemical_name", "part_number", "uom", "currency", "po_number",
        "description", "remarks", mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("manufacturer_id", "effective_date", mode="before")
    @classmethod
    def blank_optional(cls, value: Any) -> Any:
        return _blank_to_none(value)


class MudChemicalUpdate(_Strict):
    chemical_code: str | None = Field(default=None, min_length=1, max_length=50)
    chemical_name: str | None = Field(default=None, min_length=1, max_length=200)
    group_id: str | None = Field(default=None, min_length=1, max_length=36)
    manufacturer_id: str | None = Field(default=None, max_length=36)
    part_number: str | None = Field(default=None, max_length=100)
    uom: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    remarks: str | None = Field(default=None, max_length=500)

    @field_validator("chemical_code", "chemical_name", "part_number", "uom", "description", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("manufacturer_id", mode="before")
    @classmethod
    def blank_manufacturer(cls, value: Any) -> Any:
        return _blank_to_none(value)


class MudChemicalOut(BaseModel):
    id: str
    chemical_code: str
    chemical_name: str
    group_id: str
    group_name: str | None = None
    manufacturer_id: str | None = None
    manufacturer_name: str | None = None
    part_number: str
    uom: str
    unit_rate: Decimal
    currency: str
    po_number: str
    effective_date: date | None = None
    current_revision_number: int
    description: str
    remarks: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CementAdditiveCreate(_Strict):
    additive_code: str = Field(min_length=1, max_length=50)
    additive_name: str = Field(min_length=1, max_length=200)
    additive_type_id: str = Field(min_length=1, max_length=36)
    manufacturer_id: str | None = Field(default=None, max_length=36)
    part_number: str = Field(default="", max_length=100)
    uom: str = Field(default="", max_length=50)
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    currency: str = Field(min_length=1, max_length=10)
    po_number: str = Field(default="", max_length=100)
    effective_date: date | None = None
    description: str = Field(default="", max_length=500)
    remarks: str = Field(default="", max_length=500)

    @field_validator(
        "additive_code", "additive_name", "part_number", "uom", "currency", "po_number",
        "description", "remarks", mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("manufacturer_id", "effective_date", mode="before")
    @classmethod
    def blank_optional(cls, value: Any) -> Any:
        return _blank_to_none(value)


class CementAdditiveUpdate(_Strict):
    additive_code: str | None = Field(default=None, min_length=1, max_length=50)
    additive_name: str | None = Field(default=None, min_length=1, max_length=200)
    additive_type_id: str | None = Field(default=None, min_length=1, max_length=36)
    manufacturer_id: str | None = Field(default=None, max_length=36)
    part_number: str | None = Field(default=None, max_length=100)
    uom: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    remarks: str | None = Field(default=None, max_length=500)

    @field_validator(
        "additive_code", "additive_name", "additive_type_id", "manufacturer_id", "part_number", "uom", "description", "remarks",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class CementAdditiveOut(BaseModel):
    id: str
    additive_code: str
    additive_name: str
    additive_type_id: str
    additive_type_name: str | None = None
    manufacturer_id: str | None = None
    manufacturer_name: str | None = None
    part_number: str
    uom: str
    unit_rate: Decimal
    currency: str
    po_number: str
    effective_date: date | None = None
    current_revision_number: int
    description: str
    remarks: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Fuel
# ---------------------------------------------------------------------------


class FuelOut(BaseModel):
    id: str
    fuel_code: str
    fuel_name: str
    uom: str
    unit_rate: Decimal
    currency: str
    effective_date: date | None = None
    current_revision_number: int
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Rate revisions (price changes)
# ---------------------------------------------------------------------------


class UpliftRevise(_Strict):
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    cost_uplift: Decimal = Field(ge=0, le=MAX_UPLIFT)
    currency: str = Field(min_length=1, max_length=10)
    po_number: str = Field(default="", max_length=100)
    effective_date: date | None = None
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("currency", "po_number", "reason", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def blank_date(cls, value: Any) -> Any:
        return _blank_to_none(value)


class UnitRevise(_Strict):
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    currency: str = Field(min_length=1, max_length=10)
    po_number: str = Field(default="", max_length=100)
    effective_date: date | None = None
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("currency", "po_number", "reason", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def blank_date(cls, value: Any) -> Any:
        return _blank_to_none(value)


class FuelRevise(_Strict):
    unit_rate: Decimal = Field(ge=0, le=MAX_RATE)
    currency: str = Field(min_length=1, max_length=10)
    effective_date: date | None = None
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("currency", "reason", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def blank_date(cls, value: Any) -> Any:
        return _blank_to_none(value)


__all__ = [
    "TangibleScope",
    "CatalogueOptionCreate",
    "CatalogueOptionBulkCreate",
    "CatalogueOptionUpdate",
    "CatalogueOptionOut",
    "CatalogueListSummary",
    "CatalogueBulkCreateResult",
    "RateRevisionOut",
    "BreakdownItem",
    "PricedItemOverview",
    "TangibleCreate",
    "TangibleUpdate",
    "TangibleOut",
    "DrillBitCreate",
    "DrillBitUpdate",
    "DrillBitOut",
    "MudChemicalCreate",
    "MudChemicalUpdate",
    "MudChemicalOut",
    "CementAdditiveCreate",
    "CementAdditiveUpdate",
    "CementAdditiveOut",
    "FuelOut",
    "UpliftRevise",
    "UnitRevise",
    "FuelRevise",
]
