"""Typed API contracts for Backup & Recovery.

Archives are opaque files; every fact the UI shows about one is a stored column,
so nothing here parses a payload.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BackupScope = Literal["workspace", "full"]
ScheduleMode = Literal["minutes", "hours", "daily", "weekly"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackupSettingsIn(_Strict):
    enabled: bool = False
    schedule_mode: ScheduleMode = "daily"
    interval_value: int = Field(default=1, ge=1, le=10080)
    run_time: str = Field(default="02:00", pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$")
    retention_days: int = Field(default=30, ge=1, le=3650)
    keep_minimum: int = Field(default=5, ge=1, le=100)
    backup_directory: str = Field(default="", max_length=120)
    scope: BackupScope = "workspace"
    compression_enabled: bool = True

    @field_validator("backup_directory")
    @classmethod
    def safe_folder(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            return ""
        # A folder name, never a path: the service also re-checks containment.
        if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."} or ".." in cleaned:
            raise ValueError("Use a folder name, not a path (the backup root is set by the server).")
        return cleaned


class BackupSettingsOut(BaseModel):
    id: str
    enabled: bool
    schedule_mode: str
    interval_value: int
    run_time: str
    retention_days: int
    keep_minimum: int
    backup_directory: str
    scope: str
    compression_enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    folder: str
    multi_tenant: bool
    allowed_scope: str
    server_time: datetime


class BackupJobOut(BaseModel):
    id: str
    backup_number: str
    scope: str
    trigger_source: str
    status: str
    description: str
    file_name: str
    file_size_bytes: int
    checksum_sha256: str
    format_version: int
    compression: str
    schema_revision: str
    table_count: int
    row_count: int
    audit_row_count: int
    requested_by_display: str
    started_at: datetime | None
    completed_at: datetime | None
    checksum_verified_at: datetime | None
    error_message: str
    retention_hold: bool
    created_at: datetime
    can_download: bool
    can_restore: bool
    open_request: str


class BackupJobTableOut(BaseModel):
    table_name: str
    module_group: str
    row_count: int
    column_count: int


class BackupJobList(BaseModel):
    items: list[BackupJobOut]
    total: int
    page: int
    page_size: int
    pages: int


class BackupCreateIn(_Strict):
    description: str = Field(default="", max_length=500)
    scope: BackupScope | None = None


class BackupCleanupOut(BaseModel):
    deleted_jobs: list[str]
    deleted_count: int
    freed_bytes: int
    kept_count: int
    retention_days: int
    keep_minimum: int
    dry_run: bool


class BackupChecksumOut(BaseModel):
    matched: bool
    expected_checksum: str
    actual_checksum: str
    verified_at: datetime | None
    status: str


class BackupReadiness(BaseModel):
    directory: str
    directory_writable: bool
    scheduled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    retention_days: int
    keep_minimum: int
    scope: str
    backup_count: int
    completed_count: int
    open_restore_requests: int
    failed_recently: int
    total_size_bytes: int
    latest_backup: BackupJobOut | None
    warnings: list[str]


class BackupOverview(BaseModel):
    total_backups: int
    completed: int
    failed: int
    checksum_mismatch: int
    running: int
    total_size_bytes: int
    latest_completed_at: datetime | None
    verified_count: int
    scheduled: bool
    next_run_at: datetime | None
    open_requests: int
    restored_count: int
    readiness: BackupReadiness


class BackupRestoreRequestIn(_Strict):
    backup_job_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=10, max_length=1000)
    business_impact: str = Field(default="", max_length=1000)


class RestoreDecisionIn(_Strict):
    remarks: str = Field(default="", max_length=1000)


class RestoreExecuteIn(_Strict):
    confirmation_text: str = Field(min_length=1, max_length=120)
    remarks: str = Field(default="", max_length=1000)


class BackupRestoreRequestOut(BaseModel):
    id: str
    request_number: str
    backup_job_id: str
    backup_number: str
    backup_file_name: str
    backup_scope: str
    backup_status: str
    status: str
    reason: str
    business_impact: str
    requested_by_display: str
    requested_at: datetime
    reviewed_by_display: str
    reviewed_at: datetime | None
    review_remarks: str
    validated_at: datetime | None
    executed_by_display: str
    executed_at: datetime | None
    execution_remarks: str
    pre_restore_backup_number: str
    tables_restored: int
    rows_restored: int
    error_message: str
    confirmation_phrase: str
    can_approve: bool
    can_validate: bool
    can_execute: bool
    can_cancel: bool
    latest_validation_status: str


class BackupRestoreRequestList(BaseModel):
    items: list[BackupRestoreRequestOut]
    total: int
    page: int
    page_size: int
    pages: int


class BackupValidationTableOut(BaseModel):
    table_name: str
    archive_rows: int
    database_rows: int
    status: str


class BackupValidationOut(BaseModel):
    id: str
    validation_number: str
    restore_request_id: str
    backup_number: str
    status: str
    checksum_matched: bool
    dry_run_performed: bool
    table_count: int
    row_count: int
    missing_tables: str
    changed_tables: str
    started_by_display: str
    started_at: datetime
    completed_at: datetime | None
    error_message: str


class BackupValidationDetail(BaseModel):
    validation: BackupValidationOut
    tables: list[BackupValidationTableOut]
