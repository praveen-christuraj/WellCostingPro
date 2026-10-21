"""Typed API contracts for the Services register."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.service_groups import DEFAULT_SERVICE_GROUP, normalize_service_group

ServiceCategory = Literal["Drilling Services", "Completion Services"]
ServiceProviderType = Literal["In House Services", "Third Party Services"]
ServiceGroup = Literal[
    "Rig Operations",
    "Formation Evaluation",
    "Well Services",
    "Land Facilities and Preparation",
    "Miscellaneous Services",
    "Supervisions",
]


_CATEGORY_ALIASES = {
    "drilling": "Drilling Services",
    "drilling service": "Drilling Services",
    "drilling services": "Drilling Services",
    "completion": "Completion Services",
    "completions": "Completion Services",
    "completion service": "Completion Services",
    "completion services": "Completion Services",
}
_PROVIDER_ALIASES = {
    "in house": "In House Services",
    "inhouse": "In House Services",
    "in house service": "In House Services",
    "in house services": "In House Services",
    "internal": "In House Services",
    "internal service": "In House Services",
    "internal services": "In House Services",
    "third party": "Third Party Services",
    "3rd party": "Third Party Services",
    "third party service": "Third Party Services",
    "third party services": "Third Party Services",
    "3rd party service": "Third Party Services",
    "3rd party services": "Third Party Services",
    "external": "Third Party Services",
    "external services": "Third Party Services",
    "outsource": "Third Party Services",
    "outsourced": "Third Party Services",
    "3p": "Third Party Services",
}


def _normalized_key(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())


def normalize_service_category(value: Any) -> Any:
    key = _normalized_key(value)
    return _CATEGORY_ALIASES.get(key, value.strip() if isinstance(value, str) else value)


def normalize_provider_type(value: Any) -> Any:
    key = _normalized_key(value)
    return _PROVIDER_ALIASES.get(key, value.strip() if isinstance(value, str) else value)


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class ServiceCreate(BaseModel):
    service_code: str = Field(min_length=1, max_length=50)
    service_name: str = Field(min_length=1, max_length=200)
    service_category: ServiceCategory
    # The group is required for reporting order. It defaults for legacy API
    # clients and spreadsheets that predate the taxonomy; the UI always asks.
    service_group: ServiceGroup = DEFAULT_SERVICE_GROUP
    provider_type: ServiceProviderType
    vendor_id: str | None = Field(default=None, max_length=36)
    description: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("service_code", "service_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("service_category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        return normalize_service_category(value)

    @field_validator("service_group", mode="before")
    @classmethod
    def normalize_group(cls, value: Any) -> Any:
        return normalize_service_group(value)

    @field_validator("provider_type", mode="before")
    @classmethod
    def normalize_provider(cls, value: Any) -> Any:
        return normalize_provider_type(value)

    @field_validator("vendor_id", mode="before")
    @classmethod
    def normalize_vendor_id(cls, value: Any) -> Any:
        return None if value == "" else _trim(value)


class ServiceUpdate(BaseModel):
    service_code: str | None = Field(default=None, min_length=1, max_length=50)
    service_name: str | None = Field(default=None, min_length=1, max_length=200)
    service_category: ServiceCategory | None = None
    service_group: ServiceGroup | None = None
    provider_type: ServiceProviderType | None = None
    vendor_id: str | None = Field(default=None, max_length=36)
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("service_code", "service_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("service_category", mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        return None if value is None else normalize_service_category(value)

    @field_validator("service_group", mode="before")
    @classmethod
    def normalize_group(cls, value: Any) -> Any:
        return None if value is None else normalize_service_group(value)

    @field_validator("provider_type", mode="before")
    @classmethod
    def normalize_provider(cls, value: Any) -> Any:
        return None if value is None else normalize_provider_type(value)

    @field_validator("vendor_id", mode="before")
    @classmethod
    def normalize_vendor_id(cls, value: Any) -> Any:
        return None if value == "" else _trim(value)


class ServiceOut(BaseModel):
    id: str
    service_code: str
    service_name: str
    service_category: ServiceCategory
    service_group: ServiceGroup
    provider_type: ServiceProviderType
    vendor_id: str | None = None
    vendor_code: str | None = None
    vendor_name: str | None = None
    description: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ServiceBreakdown(BaseModel):
    key: str
    label: str
    count: int


class ServiceOverview(BaseModel):
    active_count: int
    deleted_count: int
    category_counts: list[ServiceBreakdown]
    group_counts: list[ServiceBreakdown] = []
    provider_type_counts: list[ServiceBreakdown]


class ServiceGroupAssignment(BaseModel):
    """Bulk classification of existing services, so no legacy row stays ungrouped."""

    ids: list[str]
    service_group: ServiceGroup

    model_config = ConfigDict(extra="forbid")

    @field_validator("service_group", mode="before")
    @classmethod
    def normalize_group(cls, value: Any) -> Any:
        return normalize_service_group(value)
