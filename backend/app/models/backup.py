"""Backup & Recovery records.

Everything here is stored column-wise. An archive is a portable, compressed
JSON-lines file on disk; the database keeps only its manifest facts (name,
size, checksum, counts), so no report or grid ever parses a payload column.

Restores are deliberately a two-person workflow: a request is raised, a second
capability approves it, a validation proves the archive against the live schema
without touching data, and only then may an execution capability apply it.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import now, uid

BACKUP_SCOPES = ("workspace", "full")
BACKUP_SCHEDULE_MODES = ("minutes", "hours", "daily", "weekly")
BACKUP_JOB_STATUSES = ("pending", "running", "completed", "failed", "checksum_mismatch")
BACKUP_TRIGGER_SOURCES = ("manual", "scheduled", "pre-restore", "import")
RESTORE_REQUEST_STATUSES = (
    "pending_approval",
    "approved",
    "rejected",
    "cancelled",
    "validation_running",
    "validated",
    "validation_failed",
    "restore_running",
    "restored",
    "restore_failed",
)
VALIDATION_STATUSES = ("running", "passed", "passed_with_warnings", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class BackupSettings(Base):
    """One backup policy per workspace. Owned by the workspace, not a user."""

    __tablename__ = "backup_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_backup_settings_organization"),
        CheckConstraint(_in("schedule_mode", BACKUP_SCHEDULE_MODES), name="ck_backup_settings_mode"),
        CheckConstraint(_in("scope", BACKUP_SCOPES), name="ck_backup_settings_scope"),
        CheckConstraint("interval_value >= 1", name="ck_backup_settings_interval"),
        CheckConstraint("retention_days >= 1 AND retention_days <= 3650", name="ck_backup_settings_retention"),
        CheckConstraint("keep_minimum >= 1 AND keep_minimum <= 100", name="ck_backup_settings_keep"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    schedule_mode: Mapped[str] = mapped_column(String(20), default="daily", server_default="daily", nullable=False)
    interval_value: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    run_time: Mapped[str] = mapped_column(String(5), default="02:00", server_default="02:00", nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)
    keep_minimum: Mapped[int] = mapped_column(Integer, default=5, server_default="5", nullable=False)
    # Relative folder name under the configured backup root (never an arbitrary absolute path).
    backup_directory: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="workspace", server_default="workspace", nullable=False)
    compression_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class BackupJob(Base):
    """One archive produced by a manual, scheduled or pre-restore run."""

    __tablename__ = "backup_jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "backup_number", name="uq_backup_jobs_org_number"),
        CheckConstraint(_in("scope", BACKUP_SCOPES), name="ck_backup_jobs_scope"),
        CheckConstraint(_in("status", BACKUP_JOB_STATUSES), name="ck_backup_jobs_status"),
        CheckConstraint(_in("trigger_source", BACKUP_TRIGGER_SOURCES), name="ck_backup_jobs_trigger"),
        Index("ix_backup_jobs_org_status", "organization_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    backup_number: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="workspace", nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    # Absolute path is kept server-side only; the API never returns it.
    file_path: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", server_default="", nullable=False)
    format_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    compression: Mapped[str] = mapped_column(String(20), default="gzip", server_default="gzip", nullable=False)
    app_version: Mapped[str] = mapped_column(String(40), default="", server_default="", nullable=False)
    schema_revision: Mapped[str] = mapped_column(String(40), default="", server_default="", nullable=False)
    organization_slug: Mapped[str] = mapped_column(String(80), default="", server_default="", nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    audit_row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum_verified_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    retention_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class BackupJobTable(Base):
    """Per-table facts of an archive, so the UI can show what a file contains."""

    __tablename__ = "backup_job_tables"
    __table_args__ = (UniqueConstraint("job_id", "table_name", name="uq_backup_job_tables_job_table"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("backup_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    table_name: Mapped[str] = mapped_column(String(120), nullable=False)
    module_group: Mapped[str] = mapped_column(String(80), default="", server_default="", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class BackupRestoreRequest(Base):
    """A request to restore one archive, with approval, validation and execution."""

    __tablename__ = "backup_restore_requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "request_number", name="uq_backup_restore_requests_org_number"),
        CheckConstraint(_in("status", RESTORE_REQUEST_STATUSES), name="ck_backup_restore_requests_status"),
        Index("ix_backup_restore_requests_org_status", "organization_id", "status", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_number: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # The archive may be removed by retention after the request is settled; the
    # request keeps its own snapshot of the backup number and file name.
    backup_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("backup_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    backup_number: Mapped[str] = mapped_column(String(40), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="workspace", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    business_impact: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    executed_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    pre_restore_backup_number: Mapped[str] = mapped_column(String(40), default="", server_default="", nullable=False)
    tables_restored: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rows_restored: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    error_message: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class BackupValidation(Base):
    """A proof that an archive can be read, matches its checksum and fits the schema."""

    __tablename__ = "backup_validations"
    __table_args__ = (
        UniqueConstraint("organization_id", "validation_number", name="uq_backup_validations_org_number"),
        CheckConstraint(_in("status", VALIDATION_STATUSES), name="ck_backup_validations_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    validation_number: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    restore_request_id: Mapped[str] = mapped_column(
        ForeignKey("backup_restore_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The archive may be removed by retention after the request is settled; the
    # request keeps its own snapshot of the backup number and file name.
    backup_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("backup_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    backup_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="running", nullable=False)
    checksum_matched: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    dry_run_performed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    missing_tables: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    changed_tables: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    started_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_by_display: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class BackupValidationTable(Base):
    """Per-table result of one validation (archive rows against live rows)."""

    __tablename__ = "backup_validation_tables"
    __table_args__ = (UniqueConstraint("validation_id", "table_name", name="uq_backup_validation_tables_validation_table"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    validation_id: Mapped[str] = mapped_column(
        ForeignKey("backup_validations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(120), nullable=False)
    archive_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    database_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="match", nullable=False)
