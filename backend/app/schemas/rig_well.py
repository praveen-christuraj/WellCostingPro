"""Typed API contracts for Rig & Well Management."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _trim_required(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _trim_optional(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _normalise_code(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


class RigCreate(BaseModel):
    rig_code: str = Field(min_length=1, max_length=50)
    rig_name: str = Field(min_length=1, max_length=200)
    remarks: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("rig_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("rig_name", mode="before")
    @classmethod
    def trim_name(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class RigUpdate(BaseModel):
    rig_code: str | None = Field(default=None, min_length=1, max_length=50)
    rig_name: str | None = Field(default=None, min_length=1, max_length=200)
    remarks: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("rig_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("rig_name", mode="before")
    @classmethod
    def trim_name(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class RigOut(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    remarks: str
    well_count: int = 0
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RigDropdownOut(BaseModel):
    id: str
    rig_code: str
    rig_name: str
    display_name: str
    well_count: int = 0


class WellCreate(BaseModel):
    rig_id: str = Field(min_length=1, max_length=36)
    well_code: str = Field(min_length=1, max_length=50)
    well_name: str = Field(min_length=1, max_length=200)
    well_location: str = Field(min_length=1, max_length=300)
    block: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=500)
    remarks: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("well_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("rig_id", "well_name", "well_location", "block", "objective", mode="before")
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class WellUpdate(BaseModel):
    rig_id: str | None = Field(default=None, min_length=1, max_length=36)
    well_code: str | None = Field(default=None, min_length=1, max_length=50)
    well_name: str | None = Field(default=None, min_length=1, max_length=200)
    well_location: str | None = Field(default=None, min_length=1, max_length=300)
    block: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, min_length=1, max_length=500)
    remarks: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("well_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("rig_id", "well_name", "well_location", "block", "objective", mode="before")
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class WellOut(BaseModel):
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    rig_display: str
    well_code: str
    well_name: str
    well_location: str
    block: str
    objective: str
    remarks: str
    status: Literal["active", "completed"]
    config_status: Literal["draft", "configured"]
    depth_unit: Literal["m", "ft"]
    total_depth: Decimal | None = None
    total_days: Decimal = Decimal("0")
    section_count: int = 0
    sub_activity_count: int = 0
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConfigurationPhaseIn(BaseModel):
    phase_id: str = Field(min_length=1, max_length=36)
    days: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=2)
    remarks: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class ConfigurationSectionIn(BaseModel):
    hole_section_id: str = Field(min_length=1, max_length=36)
    from_depth: Decimal = Field(ge=Decimal("0"), max_digits=18, decimal_places=2)
    to_depth: Decimal = Field(ge=Decimal("0"), max_digits=18, decimal_places=2)
    remarks: str = Field(default="", max_length=1000)
    phases: list[ConfigurationPhaseIn] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class WellConfigurationIn(BaseModel):
    depth_unit: Literal["m", "ft"] = "m"
    sections: list[ConfigurationSectionIn] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(extra="forbid")


class ConfigurationPhaseOut(BaseModel):
    id: str
    phase_id: str
    phase_code: str
    phase_name: str
    days: Decimal
    remarks: str


class ConfigurationSectionOut(BaseModel):
    id: str
    hole_section_id: str
    section_code: str
    section_name: str
    from_depth: Decimal
    to_depth: Decimal
    remarks: str
    total_days: Decimal
    phases: list[ConfigurationPhaseOut]


class WellConfigurationOut(BaseModel):
    well_id: str
    well_code: str
    well_name: str
    rig_code: str
    rig_name: str
    status: Literal["active", "completed"]
    config_status: Literal["draft", "configured"]
    depth_unit: Literal["m", "ft"]
    total_depth: Decimal | None = None
    total_days: Decimal
    sections: list[ConfigurationSectionOut]


class WellTransitionIn(BaseModel):
    action: Literal["configure", "draft", "complete", "activate"]
    remarks: str = Field(min_length=3, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_required(value)


class WellSubActivityCreate(BaseModel):
    well_id: str = Field(min_length=1, max_length=36)
    sub_activity_code: str = Field(min_length=1, max_length=50)
    sub_activity_name: str = Field(min_length=1, max_length=150)
    activity_id: str = Field(min_length=1, max_length=36)
    responsible_party: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("sub_activity_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator(
        "well_id", "sub_activity_name", "activity_id", "responsible_party", "description", mode="before"
    )
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)


class WellSubActivityUpdate(BaseModel):
    sub_activity_code: str | None = Field(default=None, min_length=1, max_length=50)
    sub_activity_name: str | None = Field(default=None, min_length=1, max_length=150)
    activity_id: str | None = Field(default=None, min_length=1, max_length=36)
    responsible_party: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=4000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("sub_activity_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator(
        "sub_activity_name", "activity_id", "responsible_party", "description", mode="before"
    )
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)


class WellSubActivityOut(BaseModel):
    id: str
    well_id: str
    sub_activity_code: str
    sub_activity_name: str
    activity_id: str
    responsible_party: str
    description: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    well_code: str
    well_name: str
    rig_id: str
    rig_code: str
    rig_name: str
    activity_code: str
    activity_name: str
    activity_display: str

    model_config = ConfigDict(from_attributes=True)


class RigWellImportRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class RigWellImportResponse(BaseModel):
    imported_count: int
    error_count: int
    errors: list[str]
    success: bool


class RigWellIDs(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class DeletedSelectionItem(BaseModel):
    entity_type: Literal["rig", "well", "well_sub_activity"]
    id: str = Field(min_length=1, max_length=36)


class DeletedSelection(BaseModel):
    records: list[DeletedSelectionItem] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class RigWellBulkActionResponse(BaseModel):
    affected_count: int


class RigWellExportAudit(BaseModel):
    module: Literal["rigs", "wells", "well-sub-activities", "deleted"]
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=1_000_000)
    include_deleted: bool = False

    model_config = ConfigDict(extra="forbid")


class RigWellMasterDataOption(BaseModel):
    id: str
    code: str
    name: str


class RigWellConfigurationOptions(BaseModel):
    hole_sections: list[RigWellMasterDataOption]
    phases: list[RigWellMasterDataOption]


class RigWellActivityCount(BaseModel):
    key: str
    label: str
    count: int


class RigWellRecentActivity(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_label: str
    summary: str
    created_at: datetime


class RigWellOverview(BaseModel):
    active_rigs: int
    deleted_rigs: int
    active_wells: int
    deleted_wells: int
    active_sub_activities: int
    deleted_sub_activities: int
    configured_wells: int
    draft_wells: int
    completed_wells: int
    activity_counts: list[RigWellActivityCount]
    recent_activity: list[RigWellRecentActivity]


class DeletedRigWellRecord(BaseModel):
    id: str
    entity_type: Literal["rig", "well", "well_sub_activity"]
    code: str
    name: str
    parent_label: str = ""
    deleted_at: datetime
    created_at: datetime
