"""Typed API contracts for the Master Data Management module."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MasterDataCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    symbol: str | None = Field(default=None, max_length=50)
    description: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("code", "name", mode="before")
    @classmethod
    def trim_required_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("symbol", "description", mode="before")
    @classmethod
    def trim_optional_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class MasterDataUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    symbol: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("code", "name", mode="before")
    @classmethod
    def trim_required_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("symbol", "description", mode="before")
    @classmethod
    def trim_optional_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class MasterDataRecordOut(BaseModel):
    id: str
    code: str
    name: str
    symbol: str | None = None
    description: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MasterDataIDs(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)


class MasterDataSelection(BaseModel):
    module: str = Field(min_length=1, max_length=30)
    id: str = Field(min_length=1, max_length=36)


class MasterDataBulkSelection(BaseModel):
    records: list[MasterDataSelection] = Field(min_length=1, max_length=5000)


class MasterDataImportRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class MasterDataImportResponse(BaseModel):
    imported_count: int
    error_count: int
    errors: list[str]
    success: bool


class MasterDataBulkActionResponse(BaseModel):
    affected_count: int


class MasterDataExportAudit(BaseModel):
    module: str = Field(min_length=1, max_length=30)
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = Field(ge=0, le=1_000_000)
    include_deleted: bool = False


class MasterDataModuleStats(BaseModel):
    key: str
    label: str
    active_count: int
    deleted_count: int


class MasterDataActivity(BaseModel):
    id: str
    action: str
    entity_label: str
    summary: str
    created_at: datetime


class MasterDataOverview(BaseModel):
    active_records: int
    deleted_records: int
    module_count: int
    modules: list[MasterDataModuleStats]
    recent_activity: list[MasterDataActivity]
