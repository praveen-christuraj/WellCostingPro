"""Typed API contracts for Rig & Well Management."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.precision import Decimal10, Decimal10Days


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


class BlockCreate(BaseModel):
    block_code: str = Field(min_length=1, max_length=50)
    block_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("block_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("block_name", mode="before")
    @classmethod
    def trim_name(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value: Any) -> Any:
        return _trim_optional(value)


class BlockUpdate(BaseModel):
    block_code: str | None = Field(default=None, min_length=1, max_length=50)
    block_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("block_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("block_name", mode="before")
    @classmethod
    def trim_name(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value: Any) -> Any:
        return _trim_optional(value)


class BlockOut(BaseModel):
    id: str
    block_code: str
    block_name: str
    description: str
    well_count: int = 0
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BlockDropdownOut(BaseModel):
    id: str
    block_code: str
    block_name: str
    description: str = ""
    display_name: str
    well_count: int = 0


class WellCreate(BaseModel):
    rig_id: str = Field(min_length=1, max_length=36)
    block_id: str = Field(min_length=1, max_length=36)
    well_code: str = Field(min_length=1, max_length=50)
    well_name: str = Field(min_length=1, max_length=200)
    well_location: str = Field(min_length=1, max_length=300)
    objective: str = Field(min_length=1, max_length=500)
    remarks: str = Field(default="", max_length=1000)
    scopes: list[Literal["drilling", "completion"]] = Field(
        default_factory=lambda: ["drilling", "completion"], min_length=1, max_length=2
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("well_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("rig_id", "block_id", "well_name", "well_location", "objective", mode="before")
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)

    @field_validator("scopes", mode="after")
    @classmethod
    def unique_scopes(cls, value: list[Literal["drilling", "completion"]]) -> list[Literal["drilling", "completion"]]:
        ordered: list[Literal["drilling", "completion"]] = []
        for item in value:
            if item not in ordered:
                ordered.append(item)
        return ordered


class WellUpdate(BaseModel):
    rig_id: str | None = Field(default=None, min_length=1, max_length=36)
    block_id: str | None = Field(default=None, min_length=1, max_length=36)
    well_code: str | None = Field(default=None, min_length=1, max_length=50)
    well_name: str | None = Field(default=None, min_length=1, max_length=200)
    well_location: str | None = Field(default=None, min_length=1, max_length=300)
    objective: str | None = Field(default=None, min_length=1, max_length=500)
    remarks: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("well_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("rig_id", "block_id", "well_name", "well_location", "objective", mode="before")
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class WellOut(BaseModel):
    completion_status: Literal["active", "completed"] = "active"
    completion_config_status: Literal["draft", "configured", "final_review"] = "draft"
    completion_section_count: int = 0
    id: str
    rig_id: str
    rig_code: str
    rig_name: str
    rig_display: str
    well_code: str
    well_name: str
    well_location: str
    block_id: str
    block_code: str
    block_name: str
    block: str
    objective: str
    remarks: str
    status: Literal["active", "completed"]
    config_status: Literal["draft", "configured", "final_review"]
    depth_unit: Literal["m", "ft"]
    completion_depth_unit: Literal["m", "ft"]
    standard_depth_unit: Literal["m"] = "m"
    total_depth: Decimal | None = None
    total_depth_m: Decimal | None = None
    total_days: Decimal = Decimal("0")
    completion_total_depth: Decimal | None = None
    completion_total_depth_m: Decimal | None = None
    completion_total_days: Decimal = Decimal("0")
    section_count: int = 0
    sub_activity_count: int = 0
    drilling_sub_activity_count: int = 0
    completion_sub_activity_count: int = 0
    drilling_is_deleted: bool = False
    drilling_deleted_at: datetime | None = None
    drilling_purged: bool = False
    completion_is_deleted: bool = False
    completion_deleted_at: datetime | None = None
    completion_purged: bool = False
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Latest approved drilling-scope plan adjustment, when one exists. Null
    # means no approved adjustment, so callers use total_days above.
    adjusted_total_days: Decimal | None = None
    has_plan_adjustment: bool = False
    plan_revision: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ConfigurationPhaseIn(BaseModel):
    phase_id: str = Field(min_length=1, max_length=36)
    days: Decimal10Days = Field(ge=Decimal("0"))
    remarks: str = Field(default="", max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class ConfigurationSectionIn(BaseModel):
    hole_section_id: str = Field(min_length=1, max_length=36)
    from_depth: Decimal10 = Field(ge=Decimal("0"))
    to_depth: Decimal10 = Field(ge=Decimal("0"))
    remarks: str = Field(default="", max_length=1000)
    phases: list[ConfigurationPhaseIn] = Field(min_length=1, max_length=50)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_optional(value)


class WellConfigurationIn(BaseModel):
    scope: Literal["drilling", "completion"] = "drilling"
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
    from_depth_m: Decimal | None = None
    to_depth_m: Decimal | None = None
    remarks: str
    total_days: Decimal
    phases: list[ConfigurationPhaseOut]


class WellConfigurationOut(BaseModel):
    scope: Literal["drilling", "completion"] = "drilling"
    well_id: str
    well_code: str
    well_name: str
    rig_code: str
    rig_name: str
    status: Literal["active", "completed"]
    config_status: Literal["draft", "configured", "final_review"]
    depth_unit: Literal["m", "ft"]
    standard_depth_unit: Literal["m"] = "m"
    total_depth: Decimal | None = None
    total_depth_m: Decimal | None = None
    total_days: Decimal
    sections: list[ConfigurationSectionOut]


class WellTransitionIn(BaseModel):
    scope: Literal["drilling", "completion"] = "drilling"
    action: Literal["configure", "draft", "final_review", "complete", "activate"]
    remarks: str = Field(min_length=3, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("remarks", mode="before")
    @classmethod
    def trim_remarks(cls, value: Any) -> Any:
        return _trim_required(value)


class WellSubActivityCreate(BaseModel):
    well_id: str = Field(min_length=1, max_length=36)
    scope: Literal["drilling", "completion"] = "drilling"
    sub_activity_code: str = Field(min_length=1, max_length=50)
    sub_activity_name: str = Field(min_length=1, max_length=150)
    activity_id: str = Field(min_length=1, max_length=36)
    responsible_party: str = Field(default="Not Applicable", max_length=200)
    description: str = Field(min_length=1, max_length=4000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("sub_activity_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("responsible_party", mode="before")
    @classmethod
    def trim_responsible_party(cls, value: Any) -> Any:
        if value is None:
            return "Not Applicable"
        val = str(value).strip()
        return val if val else "Not Applicable"

    @field_validator(
        "well_id", "sub_activity_name", "activity_id", "description", mode="before"
    )
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)


class WellSubActivityUpdate(BaseModel):
    sub_activity_code: str | None = Field(default=None, min_length=1, max_length=50)
    sub_activity_name: str | None = Field(default=None, min_length=1, max_length=150)
    activity_id: str | None = Field(default=None, min_length=1, max_length=36)
    responsible_party: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=4000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("sub_activity_code", mode="before")
    @classmethod
    def normalise_code(cls, value: Any) -> Any:
        return _normalise_code(value)

    @field_validator("responsible_party", mode="before")
    @classmethod
    def trim_responsible_party(cls, value: Any) -> Any:
        if value is None:
            return None
        val = str(value).strip()
        return val if val else "Not Applicable"

    @field_validator(
        "sub_activity_name", "activity_id", "description", mode="before"
    )
    @classmethod
    def trim_required(cls, value: Any) -> Any:
        return _trim_required(value)


class WellSubActivityOut(BaseModel):
    id: str
    well_id: str
    scope: Literal["drilling", "completion"] = "drilling"
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


class WellScopeSelectionItem(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    scope: Literal["drilling", "completion"]

    model_config = ConfigDict(extra="forbid")


class WellBulkDeleteRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=5000)
    items: list[WellScopeSelectionItem] = Field(default_factory=list, max_length=5000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def require_selection(self) -> "WellBulkDeleteRequest":
        if not self.ids and not self.items:
            raise ValueError("Select at least one well or well scope to move to Deleted Entries")
        if self.ids and self.items:
            raise ValueError("Specify either ids or scoped items, not both")
        return self


class DeletedSelectionItem(BaseModel):
    entity_type: Literal["block", "rig", "well", "well_sub_activity"]
    id: str = Field(min_length=1, max_length=36)
    scope: Literal["drilling", "completion"] | None = None


class DeletedSelection(BaseModel):
    records: list[DeletedSelectionItem] = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(extra="forbid")


class RigWellBulkActionResponse(BaseModel):
    affected_count: int


class RigWellExportAudit(BaseModel):
    module: Literal["blocks", "rigs", "wells", "well-sub-activities", "deleted"]
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


class RigWellBlockCount(BaseModel):
    block_id: str
    block_code: str
    block_name: str
    well_count: int = 0


class RigWellRecentActivity(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_label: str
    summary: str
    created_at: datetime


class RigWellOverview(BaseModel):
    active_blocks: int = 0
    deleted_blocks: int = 0
    block_counts: list[RigWellBlockCount] = Field(default_factory=list)
    active_rigs: int
    deleted_rigs: int
    active_wells: int
    deleted_wells: int
    active_sub_activities: int
    deleted_sub_activities: int
    configured_wells: int
    draft_wells: int
    final_review_wells: int = 0
    completed_wells: int
    activity_counts: list[RigWellActivityCount]
    recent_activity: list[RigWellRecentActivity]


class DeletedRigWellRecord(BaseModel):
    id: str
    entity_type: Literal["block", "rig", "well", "well_sub_activity"]
    scope: Literal["drilling", "completion"] | None = None
    code: str
    name: str
    parent_label: str = ""
    deleted_at: datetime
    created_at: datetime
