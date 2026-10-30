"""Backup & Recovery service.

Design decisions, and why they differ from a plain ``pg_dump``:

* **Portable archives.** A backup is a gzip-compressed JSON-lines file written
  through SQLAlchemy from the workspace's own scoped tables. It restores on
  SQLite and on PostgreSQL alike, needs no PostgreSQL client tools on the API
  host, and — because every tenant's rows are selected through the same
  tenancy rules as the Database Browser — a **workspace** backup can never
  contain another workspace's data.
* **Column-wise manifest.** Per-table row counts live in
  ``backup_job_tables`` / ``backup_validation_tables``; the file itself is the
  only place a per-row payload exists.
* **Two-person restore.** Request → approval (second capability) → validation
  (checksum + schema fit + a savepoint dry run that is always rolled back) →
  execution (typed confirmation, automatic pre-restore safety backup, one
  transaction).
* **The audit trail is never replaced.** ``audit_logs`` and the backup module's
  own tables are excluded from the replace phase, so the record of who did
  what survives a restore. Sessions are never archived, so every user signs in
  again after a restore.
* **Full-database scope is single-tenant only.** Returning another tenant's
  rows through a workspace-scoped download permission would cross a tenant
  boundary, so a deployment with more than one workspace is refused.

Timestamps are UTC (the whole application stores UTC).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import threading
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Time, delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, engine as default_engine
from app.core.migrations import current_revision
from app.models import (
    BackupJob,
    BackupJobTable,
    BackupRestoreRequest,
    BackupSettings,
    BackupValidation,
    BackupValidationTable,
    Organization,
    User,
)
from app.services import audit
from app.services.database_browser import browsable_tables, module_group, reflect

log = logging.getLogger("app.backup")

ARCHIVE_KIND = "wellcostiq-backup"
ARCHIVE_FORMAT_VERSION = 1
ARCHIVE_SUFFIX = ".jsonl.gz"
CHUNK_ROWS = 500
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024  # refuse to read a file bigger than 4 GiB
RESTORE_CONFIRM_PREFIX = "RESTORE"
# Never archived: migration bookkeeping, sessions (users must sign in again) and
# this module's own history (so a restore never rewrites the backup register).
EXCLUDED_TABLES = frozenset({"alembic_version", "refresh_sessions"})
EXCLUDED_PREFIXES = ("backup_",)
# Replaced by neither the delete nor the insert phase of a restore:
# * audit_logs — the trail of who did what must survive (and record) a restore;
# * organizations — the tenant anchor itself. Restoring it would cascade-delete
#   this module's own history through the workspace foreign key, and an archive
#   is never allowed to rewrite which workspace it belongs to.
PRESERVED_TABLES = frozenset({"audit_logs", "organizations"})
PENDING_REQUEST_STATUSES = ("pending_approval", "approved", "validation_running", "validated", "restore_running")
RUNNING_JOB_STATUSES = ("pending", "running")
SCHEDULE_MODES = ("minutes", "hours", "daily", "weekly")


class BackupError(Exception):
    """A rejected operation, carrying the HTTP status the router should answer."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Paths and small helpers
# ---------------------------------------------------------------------------


def backup_root() -> Path:
    """The configured archive root. Only folders beneath it are ever writable."""
    configured = (get_settings().backup_directory or os.getenv("BACKUP_DIRECTORY", "")).strip()
    root = Path(configured).expanduser() if configured else Path.cwd() / "backups"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def folder_name(settings: BackupSettings | None, slug: str) -> str:
    """Safe, per-workspace folder; a caller-supplied name can never escape the root."""
    candidate = (settings.backup_directory if settings else "") or slug or "workspace"
    candidate = "".join(character for character in candidate if character.isalnum() or character in "-_ ").strip()
    return candidate.replace(" ", "-")[:80] or "workspace"


def archive_directory(settings: BackupSettings | None, slug: str) -> Path:
    root = backup_root()
    directory = (root / folder_name(settings, slug)).resolve()
    if root != directory and root not in directory.parents:
        raise BackupError(422, "The backup folder must stay inside the configured backup root.")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_within_root(path: Path) -> Path:
    root = backup_root()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise BackupError(422, "The backup file is outside the configured backup root.")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything in this app is stored as UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def display_name(user: User | None) -> str:
    if user is None:
        return "System scheduler"
    return user.full_name or user.email


def workspace_slug(db: Session, organization_id: str) -> str:
    organization = db.get(Organization, organization_id)
    return organization.slug if organization else organization_id


def organization_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(Organization)) or 0)


def next_number(db: Session, model, column, organization_id: str, prefix: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    stem = f"{prefix}-{today}-"
    used = db.scalars(select(column).where(model.organization_id == organization_id, column.like(f"{stem}%"))).all()
    highest = 0
    for value in used:
        tail = str(value).rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{stem}{highest + 1:04d}"


def calculate_next_run(settings: BackupSettings, from_time: datetime | None = None) -> datetime | None:
    """The next scheduled run in UTC, or None when the schedule is off."""
    if not settings.enabled:
        return None
    moment = as_utc(from_time) or datetime.now(timezone.utc)
    mode = (settings.schedule_mode or "daily").lower()
    interval = max(1, int(settings.interval_value or 1))
    if mode == "minutes":
        return moment + timedelta(minutes=interval)
    if mode == "hours":
        return moment + timedelta(hours=interval)
    run_time = (settings.run_time or "02:00")[:5]
    try:
        hour, minute = (int(part) for part in run_time.split(":"))
    except ValueError:
        hour, minute = 2, 0
    candidate = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if mode == "weekly":
        # Same weekday next week; if today's slot is still ahead, use it.
        if candidate <= moment:
            candidate += timedelta(days=7)
        return candidate
    if candidate <= moment:
        candidate += timedelta(days=1)
    return candidate


def get_or_create_settings(db: Session, organization_id: str) -> BackupSettings:
    settings = db.scalar(select(BackupSettings).where(BackupSettings.organization_id == organization_id))
    if settings:
        return settings
    settings = BackupSettings(organization_id=organization_id)
    settings.next_run_at = calculate_next_run(settings)
    db.add(settings)
    db.flush()
    return settings


def ensure_no_job_running(db: Session, organization_id: str) -> None:
    running = db.scalar(
        select(BackupJob)
        .where(BackupJob.organization_id == organization_id, BackupJob.status.in_(RUNNING_JOB_STATUSES))
        .order_by(BackupJob.created_at.desc())
    )
    if running:
        raise BackupError(409, f"Backup {running.backup_number} is still {running.status}. Wait for it to finish before starting another.")


# ---------------------------------------------------------------------------
# Backup plan (which tables, which rows)
# ---------------------------------------------------------------------------


class PlanTable:
    __slots__ = ("name", "table", "scope", "group", "scope_label")

    def __init__(self, name: str, table, scope, group: str, scope_label: str):
        self.name = name
        self.table = table
        self.scope = scope
        self.group = group
        self.scope_label = scope_label

    @property
    def columns(self) -> list:
        return [column for column in self.table.columns]

    @property
    def primary_key(self) -> list[str]:
        return [column.name for column in self.table.primary_key.columns]


def backup_plan(db: Session, scope: str, organization_id: str) -> dict[str, PlanTable]:
    """The tables and row filters one archive covers."""
    bind = db.get_bind()
    if scope == "workspace":
        plan: dict[str, PlanTable] = {}
        for name, browsable in browsable_tables(bind).items():
            if name in EXCLUDED_TABLES or name in PRESERVED_TABLES or name.startswith(EXCLUDED_PREFIXES):
                continue
            plan[name] = PlanTable(name, browsable.table, browsable.scope, browsable.group, browsable.scope_label)
        return plan
    if scope != "full":
        raise BackupError(422, "Backup scope must be workspace or full")
    metadata = reflect(bind)
    plan = {}
    for name, table in metadata.tables.items():
        if name in EXCLUDED_TABLES or name in PRESERVED_TABLES or name.startswith(EXCLUDED_PREFIXES):
            continue
        plan[name] = PlanTable(name, table, None, module_group(name), "all rows")
    return plan


def table_order(tables: dict[str, PlanTable]) -> list[str]:
    """Parents before children, so inserts satisfy declared foreign keys."""
    parents: dict[str, set[str]] = {name: set() for name in tables}
    children: dict[str, set[str]] = {name: set() for name in tables}
    for name, plan in tables.items():
        for constraint in plan.table.foreign_key_constraints:
            target = next(iter(constraint.elements), None)
            if target is None:
                continue
            parent = target.column.table.name
            if parent in tables and parent != name:
                parents[name].add(parent)
                children[parent].add(name)
    ready = sorted(name for name, values in parents.items() if not values)
    ordered: list[str] = []
    while ready:
        name = ready.pop(0)
        ordered.append(name)
        for child in sorted(children[name]):
            parents[child].discard(name)
            if not parents[child] and child not in ordered and child not in ready:
                ready.append(child)
        ready.sort()
    # A reference cycle is rare; keeping the remaining tables (with deferred
    # constraints where the dialect supports it) beats silently dropping them.
    ordered.extend(sorted(name for name in tables if name not in ordered))
    return ordered


def self_reference_columns(table) -> list:
    """Single-column foreign keys a table holds to itself (inserted null, updated after)."""
    found = []
    for constraint in table.foreign_key_constraints:
        if len(constraint.columns) != 1:
            continue
        target = next(iter(constraint.elements)).column
        if target.table is table:
            found.append(next(iter(constraint.columns)))
    return found


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def to_json_value(value):
    """Plain JSON, keeping decimals exact and binary payloads intact."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, datetime_time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    return str(value)


def to_column_value(value, column):
    """Coerce an archived JSON value back to the column's own Python type."""
    if value is None:
        return None
    type_ = column.type
    if isinstance(value, dict) and "__bytes__" in value:
        return base64.b64decode(value["__bytes__"])
    if isinstance(value, str) and value == "" and not isinstance(type_, String):
        return None
    try:
        if isinstance(type_, Boolean):
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            return text in {"1", "true", "yes", "y"}
        if isinstance(type_, DateTime):
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if isinstance(type_, Date):
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return date.fromisoformat(str(value)[:10])
        if isinstance(type_, Time):
            return value if isinstance(value, datetime_time) else datetime_time.fromisoformat(str(value))
        if isinstance(type_, Numeric):
            return Decimal(str(value))
        if isinstance(type_, Integer):
            return int(value)
        if isinstance(type_, Float):
            return float(value)
        if isinstance(type_, String):
            return value if isinstance(value, str) else str(value)
    except (ValueError, TypeError, InvalidOperation) as error:
        raise BackupError(
            422,
            f"A stored value in {column.table.name}.{column.name} could not be restored ({error}). "
            "The archive was probably edited outside WellCostIQ.",
        ) from error
    return value


# ---------------------------------------------------------------------------
# Writing an archive
# ---------------------------------------------------------------------------


def _archive_metadata(db: Session, scope: str, organization_id: str) -> dict:
    organization = db.get(Organization, organization_id)
    return {
        "kind": ARCHIVE_KIND,
        "format_version": ARCHIVE_FORMAT_VERSION,
        "scope": scope,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "application": get_settings().app_name,
        "schema_revision": current_revision(db.get_bind()) or "",
        "organization": {
            "id": organization_id,
            "slug": organization.slug if organization else "",
            "name": organization.name if organization else "",
        },
    }


def write_archive(
    db: Session,
    job: BackupJob,
    plan: dict[str, PlanTable],
    organization_id: str,
    *,
    compress: bool = True,
) -> dict:
    """Stream the archive to disk; return the counted manifest facts."""
    directory = Path(job.file_path).parent if job.file_path else None
    if directory is None:
        raise BackupError(500, "The backup destination has not been prepared")
    directory.mkdir(parents=True, exist_ok=True)
    final_path = Path(job.file_path)
    partial_path = final_path.with_name(final_path.name + ".partial")
    order = table_order(plan)
    metadata = _archive_metadata(db, job.scope, organization_id)
    metadata["tables"] = [
        {
            "name": name,
            "group": plan[name].group,
            "scope": plan[name].scope_label,
            "columns": [column.name for column in plan[name].columns],
            "primary_key": plan[name].primary_key,
        }
        for name in order
    ]
    counts: dict[str, int] = {}
    total = 0
    audit_rows = 0
    try:
        with partial_path.open("wb") as raw:
            stream = gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6) if compress else raw
            text = io.TextIOWrapper(stream, encoding="utf-8", newline="\n")
            try:
                text.write(json.dumps({"type": "manifest", **metadata}, ensure_ascii=False, default=to_json_value) + "\n")
                for name in order:
                    plan_table = plan[name]
                    statement = select(*plan_table.columns)
                    if plan_table.scope is not None:
                        statement = statement.where(plan_table.scope(organization_id))
                    if plan_table.primary_key:
                        statement = statement.order_by(*(plan_table.table.c[column] for column in plan_table.primary_key))
                    result = db.execute(statement, execution_options={"yield_per": 1000})
                    names = [column.name for column in plan_table.columns]
                    row_count = 0
                    chunk: list[dict] = []
                    for record in result:
                        chunk.append({key: to_json_value(value) for key, value in zip(names, record)})
                        row_count += 1
                        if len(chunk) >= CHUNK_ROWS:
                            text.write(json.dumps({"type": "table", "table": name, "rows": chunk}, ensure_ascii=False) + "\n")
                            chunk = []
                    if chunk:
                        text.write(json.dumps({"type": "table", "table": name, "rows": chunk}, ensure_ascii=False) + "\n")
                    counts[name] = row_count
                    total += row_count
                    if name == "audit_logs":
                        audit_rows = row_count
                text.write(json.dumps({"type": "trailer", "tables": counts, "rows": total}, ensure_ascii=False) + "\n")
            finally:
                text.flush()
                text.detach()
                stream.close()
        partial_path.replace(final_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return {
        "counts": counts,
        "total_rows": total,
        "audit_rows": audit_rows,
        "tables": len(counts),
        "file_size": final_path.stat().st_size,
        "checksum": sha256_file(final_path),
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Reading / inspecting an archive
# ---------------------------------------------------------------------------


def read_manifest(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        raise BackupError(404, "The backup file is not on the server any more.")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise BackupError(422, "The backup file is larger than this server can validate (4 GiB).")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            first = stream.readline()
    except (OSError, EOFError, UnicodeDecodeError) as error:
        raise BackupError(422, "This file is not a readable WellCostIQ archive (it may be corrupt or truncated).") from error
    try:
        manifest = json.loads(first)
    except json.JSONDecodeError as error:
        raise BackupError(422, "This file is not a WellCostIQ archive: its header could not be read.") from error
    if not isinstance(manifest, dict) or manifest.get("type") != "manifest" or manifest.get("kind") != ARCHIVE_KIND:
        raise BackupError(422, "This file is not a WellCostIQ archive.")
    if int(manifest.get("format_version") or 0) != ARCHIVE_FORMAT_VERSION:
        raise BackupError(422, "This archive was written by a different WellCostIQ version and cannot be read here.")
    return manifest


def scan_archive(path: Path, expected_counts: dict[str, int] | None = None) -> dict:
    """Walk the whole archive once, verifying structure and counting rows."""
    manifest = read_manifest(path)
    counts: dict[str, int] = {}
    trailer: dict[str, int] | None = None
    tables_with_columns: dict[str, list[str]] = {
        entry.get("name"): list(entry.get("columns") or []) for entry in manifest.get("tables") or [] if entry.get("name")
    }
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            stream.readline()  # manifest
            for line in stream:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise BackupError(422, "The archive is damaged: one of its records could not be read.") from error
                kind = record.get("type")
                if kind == "table":
                    name = record.get("table")
                    rows = record.get("rows") or []
                    if name not in tables_with_columns:
                        raise BackupError(422, f"The archive contains a table ({name}) that its own header does not describe.")
                    if not isinstance(rows, list):
                        raise BackupError(422, f"The archive stores {name} in an unreadable shape.")
                    counts[name] = counts.get(name, 0) + len(rows)
                elif kind == "trailer":
                    trailer = {str(key): int(value) for key, value in (record.get("tables") or {}).items()}
    except (OSError, EOFError, UnicodeDecodeError) as error:
        raise BackupError(422, "The archive is truncated or compressed incorrectly; it cannot be used.") from error
    if trailer is None:
        raise BackupError(422, "The archive has no end marker, so it is incomplete. Take a fresh backup and use that file.")
    mismatched = [name for name, value in trailer.items() if counts.get(name, 0) != value]
    if mismatched:
        raise BackupError(
            422,
            "The archive's own row counts do not match its contents ("
            + ", ".join(sorted(mismatched)[:5])
            + "). Treat this file as damaged.",
        )
    if expected_counts is not None:
        for name, value in expected_counts.items():
            if counts.get(name, 0) != value:
                raise BackupError(422, f"The archive holds {counts.get(name, 0):,} rows for {name} but the backup register expects {value:,}.")
    total = sum(counts.values())
    return {
        "manifest": manifest,
        "counts": counts,
        "total_rows": total,
        "tables": tables_with_columns,
    }


# ---------------------------------------------------------------------------
# Applying an archive (shared by validation dry runs and real restores)
# ---------------------------------------------------------------------------


def _defer_foreign_keys(db: Session) -> None:
    """Best effort: let SQLite check foreign keys at commit rather than per statement."""
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("PRAGMA defer_foreign_keys = ON"))


def _row_counts(db: Session, plan: dict[str, PlanTable], organization_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, plan_table in plan.items():
        statement = select(func.count()).select_from(plan_table.table)
        if plan_table.scope is not None:
            statement = statement.where(plan_table.scope(organization_id))
        counts[name] = int(db.scalar(statement) or 0)
    return counts


def _replace_workspace_rows(
    db: Session,
    path: Path,
    plan: dict[str, PlanTable],
    organization_id: str,
    scope: str,
) -> dict:
    """Delete the covered rows and re-insert them from the archive, in one transaction."""
    order = table_order(plan)
    replaceable = {name: plan[name] for name in order if name not in PRESERVED_TABLES}
    _defer_foreign_keys(db)
    # Children first on the way out.
    for name in reversed(order):
        if name in PRESERVED_TABLES or name not in replaceable:
            continue
        plan_table = replaceable[name]
        statement = delete(plan_table.table)
        if plan_table.scope is not None:
            statement = statement.where(plan_table.scope(organization_id))
        db.execute(statement)

    # Parents first on the way in; the archive was written in the same order.
    scanned = scan_archive(path)
    manifest_names = [entry.get("name") for entry in scanned["manifest"].get("tables") or []]
    insertion_order = [name for name in order if name in manifest_names and name in replaceable]
    insertion_order += [name for name in manifest_names if name in replaceable and name not in insertion_order]

    inserted_rows = 0
    inserted_tables = 0
    pending_self_references: list[tuple] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            stream.readline()
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("type") != "table":
                    continue
                name = record.get("table")
                if name not in replaceable:
                    continue
                plan_table = replaceable[name]
                columns = {column.name: column for column in plan_table.columns}
                self_columns = {column.name for column in self_reference_columns(plan_table.table)}
                rows = []
                for raw in record.get("rows") or []:
                    row = {}
                    for key, value in raw.items():
                        column = columns.get(key)
                        # Unknown columns are a shape change, not a crash: skip them.
                        if column is None:
                            continue
                        row[key] = None if key in self_columns else to_column_value(value, column)
                    rows.append(row)
                    if self_columns:
                        deferred = {key: to_column_value(value, columns[key]) for key, value in raw.items() if key in self_columns and value is not None}
                        if deferred:
                            pending_self_references.append((plan_table, {key: row.get(key) for key in plan_table.primary_key}, deferred))
                if rows:
                    db.execute(plan_table.table.insert(), rows)
                    inserted_rows += len(rows)
                    inserted_tables += 1
        # Apply the self-referencing values now that every row of the table exists.
        for plan_table, key_values, deferred in pending_self_references:
            condition = [plan_table.table.c[key] == value for key, value in key_values.items()]
            if condition:
                db.execute(plan_table.table.update().where(*condition).values(**deferred))
    except BackupError:
        raise
    except SQLAlchemyError as error:
        log.exception("Archive apply failed")
        raise BackupError(
            422,
            "The archive could not be applied to this database. It may come from an incompatible "
            f"version of WellCostIQ (database detail: {type(error).__name__}).",
        ) from error
    db.flush()
    return {"tables": len(insertion_order), "rows": inserted_rows}


def restore_archive(
    db: Session,
    job: BackupJob,
    organization_id: str,
    *,
    dry_run: bool,
) -> dict:
    """Apply ``job``'s archive, or prove it applies and roll the attempt back."""
    path = ensure_within_root(Path(job.file_path))
    if not path.exists():
        raise BackupError(404, "The backup file is missing from the server, so it cannot be restored.")
    scope = job.scope
    if scope == "full" and organization_count(db) > 1:
        raise BackupError(409, "This deployment holds more than one workspace, so a full-database restore is refused here.")
    plan = backup_plan(db, scope, organization_id)
    manifest = read_manifest(path)
    archive_scope = manifest.get("scope")
    if archive_scope != scope:
        raise BackupError(422, f"This archive was taken with {archive_scope} scope, but the backup record says {scope}.")
    archive_org = (manifest.get("organization") or {}).get("id")
    if scope == "workspace" and archive_org and archive_org != organization_id:
        raise BackupError(403, "This archive belongs to another workspace and cannot be restored here.")
    before = _row_counts(db, plan, organization_id)
    if dry_run:
        savepoint = db.begin_nested()
        try:
            applied = _replace_workspace_rows(db, path, plan, organization_id, scope)
            db.flush()
        finally:
            savepoint.rollback()
            db.expire_all()
        return {"dry_run": True, "before": before, "applied": applied}

    applied = _replace_workspace_rows(db, path, plan, organization_id, scope)
    db.commit()
    db.expire_all()
    return {"dry_run": False, "before": before, "applied": applied}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def create_job(
    db: Session,
    *,
    organization_id: str,
    scope: str,
    trigger_source: str,
    description: str,
    user: User | None,
) -> BackupJob:
    if scope not in {"workspace", "full"}:
        raise BackupError(422, "Backup scope must be workspace or full")
    if scope == "full" and organization_count(db) > 1:
        raise BackupError(
            409,
            "This deployment holds more than one workspace. A full-database archive would contain other "
            "tenants' data, so only workspace backups can be taken here.",
        )
    ensure_no_job_running(db, organization_id)
    job = BackupJob(
        organization_id=organization_id,
        backup_number=next_number(db, BackupJob, BackupJob.backup_number, organization_id, "BKP"),
        scope=scope,
        trigger_source=trigger_source,
        status="pending",
        description=description.strip()[:500],
        requested_by_user_id=user.id if user else None,
        requested_by_display=display_name(user),
        organization_slug=workspace_slug(db, organization_id),
        app_version="0.2.0",
        schema_revision=current_revision(db.get_bind()) or "",
    )
    db.add(job)
    db.flush()
    return job


def execute_job(db: Session, job: BackupJob, *, user: User | None = None, settings: BackupSettings | None = None) -> BackupJob:
    """Produce the archive for ``job``. A failure is recorded, never raised at the caller."""
    organization_id = job.organization_id
    settings = settings or db.scalar(select(BackupSettings).where(BackupSettings.organization_id == organization_id))
    slug = workspace_slug(db, organization_id)
    try:
        directory = archive_directory(settings, slug)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_name = f"{job.backup_number}_{timestamp}{ARCHIVE_SUFFIX}"
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.file_name = file_name
        job.file_path = str(directory / file_name)
        job.file_size_bytes = 0
        job.error_message = ""
        db.commit()
        audit.record(
            db, organization_id=organization_id, actor=user, action="backup_start",
            entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
            summary=f"Started {job.scope} backup {job.backup_number} ({job.trigger_source})",
        )
        db.commit()

        plan = backup_plan(db, job.scope, organization_id)
        result = write_archive(db, job, plan, organization_id, compress=bool(settings.compression_enabled if settings else True))
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.file_size_bytes = result["file_size"]
        job.checksum_sha256 = result["checksum"]
        job.table_count = result["tables"]
        job.row_count = result["total_rows"]
        job.audit_row_count = result["audit_rows"]
        job.schema_revision = result["metadata"].get("schema_revision", job.schema_revision)
        for name, count in result["counts"].items():
            db.add(BackupJobTable(
                organization_id=organization_id,
                job_id=job.id,
                table_name=name,
                module_group=plan[name].group if name in plan else module_group(name),
                row_count=count,
                column_count=len(plan[name].columns) if name in plan else 0,
            ))
        if settings:
            settings.last_run_at = job.completed_at
            settings.next_run_at = calculate_next_run(settings, job.completed_at)
            settings.updated_at = datetime.now(timezone.utc)
        audit.record(
            db, organization_id=organization_id, actor=user, action="backup_complete",
            entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
            summary=(
                f"Completed backup {job.backup_number}: {result['tables']} tables, "
                f"{result['total_rows']:,} rows, {result['file_size']:,} bytes, SHA-256 {result['checksum'][:12]}…"
            ),
        )
        db.commit()
        return job
    except Exception as error:  # a failed archive must leave an inspectable record
        log.exception("Backup %s failed", job.backup_number)
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
            Path(job.file_path + ".partial").unlink(missing_ok=True)
        db.rollback()
        job = db.get(BackupJob, job.id)
        if job is None:
            raise
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = str(getattr(error, "detail", error))[:2000]
        if settings:
            settings.next_run_at = calculate_next_run(settings, datetime.now(timezone.utc))
        audit.record(
            db, organization_id=organization_id, actor=user, action="backup_failed",
            entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
            summary=f"Backup {job.backup_number} failed: {job.error_message[:300]}",
        )
        db.commit()
        return job


def verify_job(db: Session, job: BackupJob, user: User) -> dict:
    if job.status not in {"completed", "checksum_mismatch"}:
        raise BackupError(409, "Only a completed backup can be verified.")
    path = ensure_within_root(Path(job.file_path))
    if not path.exists():
        raise BackupError(404, "The backup file is missing from the server.")
    actual = sha256_file(path)
    matched = actual == job.checksum_sha256
    if not matched:
        job.status = "checksum_mismatch"
        job.error_message = "The file no longer matches the checksum recorded when it was produced."
    else:
        job.error_message = ""
        if job.status == "checksum_mismatch":
            job.status = "completed"
    job.checksum_verified_at = datetime.now(timezone.utc)
    job.checksum_verified_by_user_id = user.id
    job.updated_at = datetime.now(timezone.utc)
    audit.record(
        db, organization_id=job.organization_id, actor=user, action="backup_verify",
        entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
        summary=("Verified backup " if matched else "Checksum mismatch on backup ") + job.backup_number,
    )
    db.commit()
    return {
        "matched": matched,
        "expected_checksum": job.checksum_sha256,
        "actual_checksum": actual,
        "verified_at": job.checksum_verified_at,
        "status": job.status,
    }


def archive_tables(db: Session, job: BackupJob) -> list[BackupJobTable]:
    return list(db.scalars(
        select(BackupJobTable).where(BackupJobTable.job_id == job.id).order_by(BackupJobTable.table_name)
    ).all())


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _protected_job_ids(db: Session, organization_id: str) -> set[str]:
    rows = db.scalars(
        select(BackupRestoreRequest.backup_job_id).where(
            BackupRestoreRequest.organization_id == organization_id,
            BackupRestoreRequest.status.in_(PENDING_REQUEST_STATUSES),
        )
    ).all()
    return {row for row in rows if row}


def cleanup(db: Session, organization_id: str, user: User | None, *, dry_run: bool = False) -> dict:
    """Apply the workspace retention policy: age window, minimum keep, holds, live requests."""
    settings = get_or_create_settings(db, organization_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(settings.retention_days)))
    completed = list(db.scalars(
        select(BackupJob)
        .where(BackupJob.organization_id == organization_id, BackupJob.status.in_(["completed", "failed", "checksum_mismatch"]))
        .order_by(BackupJob.created_at.desc())
    ).all())
    protected = _protected_job_ids(db, organization_id)
    keep_always = set(job.id for job in completed[: max(1, int(settings.keep_minimum))])
    deleted: list[str] = []
    freed = 0
    for job in completed:
        if job.id in protected or job.id in keep_always or job.retention_hold:
            continue
        created = as_utc(job.created_at) or datetime.now(timezone.utc)
        if created >= cutoff:
            continue
        path = Path(job.file_path) if job.file_path else None
        if path is not None:
            try:
                safe = ensure_within_root(path)
                if safe.exists():
                    freed += safe.stat().st_size
                    if not dry_run:
                        safe.unlink()
            except (BackupError, OSError):
                log.warning("Could not remove archive %s", job.file_path)
        deleted.append(job.backup_number)
        if not dry_run:
            db.delete(job)
    if not dry_run:
        audit.record(
            db, organization_id=organization_id, actor=user, action="backup_cleanup",
            entity_type="backup", entity_label="Retention",
            summary=(
                f"Retention removed {len(deleted)} archive(s), freeing {freed:,} bytes "
                f"(retention {settings.retention_days} days, keep at least {settings.keep_minimum})"
            ),
        )
        db.commit()
    return {
        "deleted_jobs": deleted,
        "deleted_count": len(deleted),
        "freed_bytes": freed,
        "kept_count": len(completed) - len(deleted),
        "retention_days": settings.retention_days,
        "keep_minimum": settings.keep_minimum,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Restore requests and validation
# ---------------------------------------------------------------------------


def create_restore_request(
    db: Session, *, organization_id: str, job: BackupJob, reason: str, business_impact: str, user: User
) -> BackupRestoreRequest:
    if job.organization_id != organization_id:
        raise BackupError(404, "That backup does not belong to this workspace.")
    if job.status != "completed":
        raise BackupError(409, "Only a completed, verified backup can be restored.")
    existing = db.scalar(
        select(BackupRestoreRequest).where(
            BackupRestoreRequest.organization_id == organization_id,
            BackupRestoreRequest.backup_job_id == job.id,
            BackupRestoreRequest.status.in_(PENDING_REQUEST_STATUSES),
        )
    )
    if existing:
        raise BackupError(409, f"Restore request {existing.request_number} is already open for this backup.")
    request = BackupRestoreRequest(
        organization_id=organization_id,
        request_number=next_number(db, BackupRestoreRequest, BackupRestoreRequest.request_number, organization_id, "BRR"),
        backup_job_id=job.id,
        backup_number=job.backup_number,
        scope=job.scope,
        status="pending_approval",
        reason=reason.strip()[:1000],
        business_impact=business_impact.strip()[:1000],
        requested_by_user_id=user.id,
        requested_by_display=display_name(user),
        requested_at=datetime.now(timezone.utc),
    )
    db.add(request)
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="restore_request",
        entity_type="backup", entity_id=request.id, entity_label=request.request_number,
        summary=f"Requested restore of {job.backup_number}: {request.reason[:200]}",
    )
    db.commit()
    return request


def review_restore_request(
    db: Session, request: BackupRestoreRequest, user: User, *, approve: bool, remarks: str
) -> BackupRestoreRequest:
    if request.status != "pending_approval":
        raise BackupError(409, f"Request {request.request_number} is {request.status.replace('_', ' ')} and cannot be reviewed again.")
    if request.requested_by_user_id == user.id:
        raise BackupError(403, "A restore request must be approved by someone other than the person who raised it.")
    request.status = "approved" if approve else "rejected"
    request.reviewed_by_user_id = user.id
    request.reviewed_by_display = display_name(user)
    request.reviewed_at = datetime.now(timezone.utc)
    request.review_remarks = remarks.strip()[:1000]
    request.updated_at = datetime.now(timezone.utc)
    audit.record(
        db, organization_id=request.organization_id, actor=user,
        action="restore_approve" if approve else "restore_reject",
        entity_type="backup", entity_id=request.id, entity_label=request.request_number,
        summary=f"{'Approved' if approve else 'Rejected'} restore {request.request_number} of {request.backup_number}"
                + (f": {request.review_remarks[:200]}" if request.review_remarks else ""),
    )
    db.commit()
    return request


def cancel_restore_request(db: Session, request: BackupRestoreRequest, user: User, remarks: str) -> BackupRestoreRequest:
    if request.status in {"restored", "restore_running", "cancelled", "rejected"}:
        raise BackupError(409, f"Request {request.request_number} is {request.status.replace('_', ' ')} and cannot be cancelled.")
    request.status = "cancelled"
    request.execution_remarks = remarks.strip()[:1000]
    request.updated_at = datetime.now(timezone.utc)
    audit.record(
        db, organization_id=request.organization_id, actor=user, action="restore_cancel",
        entity_type="backup", entity_id=request.id, entity_label=request.request_number,
        summary=f"Cancelled restore {request.request_number}" + (f": {remarks[:200]}" if remarks else ""),
    )
    db.commit()
    return request


def validate_restore_request(db: Session, request: BackupRestoreRequest, user: User) -> BackupValidation:
    if request.status not in {"approved", "validated", "validation_failed"}:
        raise BackupError(409, "Approve the request before validating it.")
    job = db.get(BackupJob, request.backup_job_id)
    if job is None or job.organization_id != request.organization_id:
        raise BackupError(404, "The backup for this request no longer exists.")
    validation = BackupValidation(
        organization_id=request.organization_id,
        validation_number=next_number(db, BackupValidation, BackupValidation.validation_number, request.organization_id, "BRV"),
        restore_request_id=request.id,
        backup_job_id=job.id,
        backup_number=job.backup_number,
        status="running",
        started_by_user_id=user.id,
        started_by_display=display_name(user),
        started_at=datetime.now(timezone.utc),
    )
    request.status = "validation_running"
    request.updated_at = datetime.now(timezone.utc)
    db.add(validation)
    db.commit()

    try:
        path = ensure_within_root(Path(job.file_path))
        checksum = sha256_file(path)
        validation.checksum_matched = checksum == job.checksum_sha256
        if not validation.checksum_matched:
            raise BackupError(422, "The archive no longer matches the checksum recorded when it was produced.")
        scanned = scan_archive(path, expected_counts=None)
        manifest = scanned["manifest"]
        if manifest.get("scope") != job.scope:
            raise BackupError(422, "The archive's scope does not match the backup register.")
        if job.scope == "workspace" and (manifest.get("organization") or {}).get("id") != request.organization_id:
            raise BackupError(403, "The archive belongs to a different workspace.")
        plan = backup_plan(db, job.scope, request.organization_id)
        missing_tables = [name for name in scanned["counts"] if name not in plan]
        live_counts = _row_counts(db, plan, request.organization_id)
        changed: list[str] = []
        for name, archive_rows in sorted(scanned["counts"].items()):
            if name in missing_tables:
                continue
            database_rows = live_counts.get(name, 0)
            status = "match" if archive_rows == database_rows else "differs"
            if status == "differs":
                changed.append(name)
            db.add(BackupValidationTable(
                organization_id=request.organization_id,
                validation_id=validation.id,
                table_name=name,
                archive_rows=archive_rows,
                database_rows=database_rows,
                status=status,
            ))
        # A dry run deletes and re-inserts inside a savepoint, then rolls it back:
        # the strongest proof we can give without touching a single stored row.
        result = restore_archive(db, job, request.organization_id, dry_run=True)
        validation.dry_run_performed = True
        validation.table_count = len(scanned["counts"])
        validation.row_count = scanned["total_rows"]
        validation.missing_tables = ", ".join(missing_tables)[:2000]
        validation.changed_tables = ", ".join(changed)[:2000]
        validation.status = "passed_with_warnings" if (missing_tables or changed) else "passed"
        validation.completed_at = datetime.now(timezone.utc)
        request.status = "validated"
        request.validated_at = validation.completed_at
        request.updated_at = datetime.now(timezone.utc)
        audit.record(
            db, organization_id=request.organization_id, actor=user, action="restore_validate",
            entity_type="backup", entity_id=validation.id, entity_label=validation.validation_number,
            summary=(
                f"Validated {job.backup_number} for {request.request_number}: {scanned['total_rows']:,} rows, "
                f"dry run {'passed' if result.get('dry_run') else 'not run'}"
                + (f", {len(changed)} table(s) differ from live data" if changed else "")
            ),
        )
        db.commit()
        return validation
    except Exception as error:
        db.rollback()
        validation = db.get(BackupValidation, validation.id) or validation
        validation.status = "failed"
        validation.completed_at = datetime.now(timezone.utc)
        validation.error_message = str(getattr(error, "detail", error))[:2000]
        request = db.get(BackupRestoreRequest, request.id) or request
        request.status = "validation_failed"
        request.updated_at = datetime.now(timezone.utc)
        audit.record(
            db, organization_id=request.organization_id, actor=user, action="restore_validate_failed",
            entity_type="backup", entity_id=validation.id, entity_label=validation.validation_number,
            summary=f"Validation of {request.backup_number} failed: {validation.error_message[:300]}",
        )
        db.commit()
        return validation


def execute_restore_request(
    db: Session, request: BackupRestoreRequest, user: User, *, confirmation_text: str, remarks: str
) -> BackupRestoreRequest:
    job = db.get(BackupJob, request.backup_job_id)
    if job is None:
        raise BackupError(404, "The backup for this request no longer exists.")
    if request.status not in {"validated", "restore_failed"}:
        raise BackupError(409, "The request must be approved and validated before a restore can run.")
    latest = db.scalar(
        select(BackupValidation)
        .where(BackupValidation.restore_request_id == request.id)
        .order_by(BackupValidation.started_at.desc())
    )
    if latest is None or latest.status not in {"passed", "passed_with_warnings"}:
        raise BackupError(409, "There is no passing validation for this request. Validate it again first.")
    expected = f"{RESTORE_CONFIRM_PREFIX} {job.backup_number}"
    if (confirmation_text or "").strip() != expected:
        raise BackupError(422, f"Type exactly “{expected}” to confirm this restore.")

    # A safety archive of the current state is produced (and committed) before
    # anything is replaced, so the restore itself can be undone.
    settings = db.scalar(select(BackupSettings).where(BackupSettings.organization_id == request.organization_id))
    safety = create_job(
        db,
        organization_id=request.organization_id,
        scope=job.scope,
        trigger_source="pre-restore",
        description=f"Automatic safety backup before restoring {job.backup_number}",
        user=user,
    )
    db.commit()
    safety = execute_job(db, safety, user=user, settings=settings)
    request.pre_restore_backup_number = safety.backup_number if safety.status == "completed" else ""
    request.status = "restore_running"
    request.execution_remarks = remarks.strip()[:1000]
    request.updated_at = datetime.now(timezone.utc)
    db.commit()
    if safety.status != "completed":
        request.status = "restore_failed"
        request.error_message = "The automatic pre-restore safety backup failed, so the restore was not started."
        db.commit()
        raise BackupError(409, request.error_message)

    # The restore may replace (or remove) the acting account itself, so the audit
    # facts are captured now rather than read from an ORM object that may vanish.
    actor_id, actor_email, actor_name = user.id, user.email, user.full_name
    try:
        result = restore_archive(db, job, request.organization_id, dry_run=False)
        request.status = "restored"
        # The archive may predate the acting account, so the FK is only kept when
        # that account still exists; the readable name is always preserved.
        request.executed_by_user_id = actor_id if db.get(User, actor_id) else None
        request.executed_by_display = actor_name or actor_email
        request.executed_at = datetime.now(timezone.utc)
        request.tables_restored = int(result["applied"]["tables"])
        request.rows_restored = int(result["applied"]["rows"])
        request.error_message = ""
        request.updated_at = datetime.now(timezone.utc)
        audit.record(
            db, organization_id=request.organization_id, actor_email=actor_email, actor_name=actor_name,
            action="restore_complete",
            entity_type="backup", entity_id=request.id, entity_label=request.request_number,
            summary=(
                f"Restored {job.backup_number} into the workspace ({request.rows_restored:,} rows across "
                f"{request.tables_restored} tables). Safety backup: {request.pre_restore_backup_number}."
            ),
        )
        db.commit()
        return request
    except Exception as error:
        db.rollback()
        request = db.get(BackupRestoreRequest, request.id) or request
        request.status = "restore_failed"
        request.error_message = str(getattr(error, "detail", error))[:2000]
        request.executed_by_user_id = actor_id if db.get(User, actor_id) else None
        request.executed_by_display = actor_name or actor_email
        request.executed_at = datetime.now(timezone.utc)
        request.updated_at = datetime.now(timezone.utc)
        audit.record(
            db, organization_id=request.organization_id, actor_email=actor_email, actor_name=actor_name,
            action="restore_failed",
            entity_type="backup", entity_id=request.id, entity_label=request.request_number,
            summary=f"Restore of {job.backup_number} failed: {request.error_message[:300]}",
        )
        db.commit()
        return request


def request_validations(db: Session, request_id: str) -> list[BackupValidation]:
    return list(db.scalars(
        select(BackupValidation)
        .where(BackupValidation.restore_request_id == request_id)
        .order_by(BackupValidation.started_at.desc())
    ).all())


def validation_tables(db: Session, validation_id: str) -> list[BackupValidationTable]:
    return list(db.scalars(
        select(BackupValidationTable)
        .where(BackupValidationTable.validation_id == validation_id)
        .order_by(BackupValidationTable.table_name)
    ).all())


# ---------------------------------------------------------------------------
# Workspace readiness
# ---------------------------------------------------------------------------


def readiness(db: Session, organization_id: str) -> dict:
    settings = get_or_create_settings(db, organization_id)
    jobs = list(db.scalars(
        select(BackupJob).where(BackupJob.organization_id == organization_id).order_by(BackupJob.created_at.desc()).limit(200)
    ).all())
    completed = [job for job in jobs if job.status == "completed"]
    latest = completed[0] if completed else None
    now = datetime.now(timezone.utc)
    warnings: list[str] = []
    directory_ok = True
    directory = ""
    try:
        directory = str(archive_directory(settings, workspace_slug(db, organization_id)))
        probe = Path(directory) / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as error:
        directory_ok = False
        warnings.append(f"The backup folder is not writable ({error}).")
    if not settings.enabled:
        warnings.append("Scheduled backups are off. Turn them on so a recent archive always exists.")
    if latest is None:
        warnings.append("This workspace has no completed backup yet.")
    else:
        created = as_utc(latest.created_at) or now
        age_days = (now - created).total_seconds() / 86400
        if age_days > max(1, settings.retention_days):
            warnings.append(f"The newest backup is {age_days:.1f} days old, older than the {settings.retention_days}-day retention window.")
        if latest.status == "completed" and latest.checksum_verified_at is None:
            warnings.append("The newest backup has never been checksum-verified. Verify it to prove the file is intact.")
    open_requests = int(db.scalar(
        select(func.count()).select_from(BackupRestoreRequest).where(
            BackupRestoreRequest.organization_id == organization_id,
            BackupRestoreRequest.status.in_(PENDING_REQUEST_STATUSES),
        )
    ) or 0)
    failed_recently = [job for job in jobs[:10] if job.status == "failed"]
    return {
        "directory": directory,
        "directory_writable": directory_ok,
        "scheduled": settings.enabled,
        "next_run_at": as_utc(settings.next_run_at),
        "last_run_at": as_utc(settings.last_run_at),
        "retention_days": settings.retention_days,
        "keep_minimum": settings.keep_minimum,
        "scope": settings.scope,
        "backup_count": len(jobs),
        "completed_count": len(completed),
        "open_restore_requests": open_requests,
        "failed_recently": len(failed_recently),
        "total_size_bytes": sum(job.file_size_bytes for job in completed),
        "latest_backup": latest,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

_scheduler_started = False
_scheduler_lock = threading.Lock()


def run_due_backups(now: datetime | None = None) -> int:
    """Start every due scheduled backup once. Returns how many were started."""
    moment = as_utc(now) or datetime.now(timezone.utc)
    started = 0
    with SessionLocal() as db:
        due = list(db.scalars(
            select(BackupSettings).where(
                BackupSettings.enabled.is_(True),
                BackupSettings.next_run_at.is_not(None),
            )
        ).all())
        for settings in due:
            next_run = as_utc(settings.next_run_at)
            if next_run is None or next_run > moment:
                continue
            organization_id = settings.organization_id
            try:
                ensure_no_job_running(db, organization_id)
            except BackupError:
                settings.next_run_at = calculate_next_run(settings, moment + timedelta(minutes=5))
                db.commit()
                continue
            job = create_job(
                db, organization_id=organization_id, scope=settings.scope, trigger_source="scheduled",
                description="Scheduled backup", user=None,
            )
            db.commit()
            execute_job(db, job, settings=settings)
            started += 1
    return started


def _scheduler_loop() -> None:
    while True:
        try:
            run_due_backups()
        except Exception:  # the scheduler must never kill the API process
            log.exception("Scheduled backup check failed")
        time.sleep(30)


def start_scheduler() -> bool:
    global _scheduler_started
    if not get_settings().backup_scheduler_enabled:
        return False
    with _scheduler_lock:
        if _scheduler_started:
            return False
        _scheduler_started = True
        threading.Thread(target=_scheduler_loop, name="backup-scheduler", daemon=True).start()
        return True


# ---------------------------------------------------------------------------
# Uploading an existing archive (disaster recovery from another server)
# ---------------------------------------------------------------------------


def import_archive(db: Session, *, organization_id: str, source: Path, file_name: str, user: User, description: str) -> BackupJob:
    """Register a previously downloaded archive so it can be validated and restored."""
    manifest = read_manifest(source)
    if manifest.get("scope") == "workspace" and (manifest.get("organization") or {}).get("id") != organization_id:
        source.unlink(missing_ok=True)
        raise BackupError(403, "This archive belongs to a different workspace.")
    if manifest.get("scope") == "full" and organization_count(db) > 1:
        source.unlink(missing_ok=True)
        raise BackupError(409, "Full-database archives can only be imported into a single-workspace deployment.")
    scanned = scan_archive(source)
    settings = db.scalar(select(BackupSettings).where(BackupSettings.organization_id == organization_id))
    directory = archive_directory(settings, workspace_slug(db, organization_id))
    # The header describes every table in the archive, including the empty ones,
    # so the imported job reports the same shape as the backup it came from.
    described: list[tuple[str, int]] = [
        (str(entry.get("name")), len(entry.get("columns") or []))
        for entry in (manifest.get("tables") or [])
        if isinstance(entry, dict) and entry.get("name")
    ]
    if not described:
        described = [(name, len(scanned["tables"].get(name) or [])) for name in scanned["counts"]]
    job = create_job(
        db, organization_id=organization_id, scope=str(manifest.get("scope") or "workspace"),
        trigger_source="import", description=description or f"Imported archive {file_name}", user=user,
    )
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.file_name = f"{job.backup_number}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.jsonl.gz"[:255]
    job.file_path = str(directory / job.file_name)
    db.commit()
    try:
        shutil.copyfile(source, job.file_path)
        source.unlink(missing_ok=True)
        size = Path(job.file_path).stat().st_size
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.file_size_bytes = size
        job.checksum_sha256 = sha256_file(Path(job.file_path))
        job.table_count = len(described)
        job.row_count = scanned["total_rows"]
        job.audit_row_count = scanned["counts"].get("audit_logs", 0)
        job.schema_revision = str(manifest.get("schema_revision") or "")[:40]
        for name, column_count in described:
            db.add(BackupJobTable(
                organization_id=organization_id, job_id=job.id, table_name=name,
                module_group=module_group(name), row_count=scanned["counts"].get(name, 0),
                column_count=column_count,
            ))
        audit.record(
            db, organization_id=organization_id, actor=user, action="backup_import",
            entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
            summary=f"Imported archive {file_name} ({scanned['total_rows']:,} rows) as {job.backup_number}",
        )
        db.commit()
        return job
    except Exception:
        db.rollback()
        Path(job.file_path).unlink(missing_ok=True)
        job = db.get(BackupJob, job.id)
        if job is not None:
            job.status = "failed"
            job.error_message = "The uploaded archive could not be stored."
            db.commit()
        raise


def audit_export(db: Session, job: BackupJob, user: User) -> None:
    audit.record(
        db, organization_id=job.organization_id, actor=user, action="backup_download",
        entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
        summary=f"Downloaded archive {job.backup_number} ({job.file_size_bytes:,} bytes)",
    )
    db.commit()


def delete_job(db: Session, job: BackupJob, user: User) -> BackupJob:
    if job.id in _protected_job_ids(db, job.organization_id):
        raise BackupError(409, "This archive is referenced by an open restore request. Cancel the request first.")
    path = Path(job.file_path) if job.file_path else None
    if path is not None:
        try:
            safe = ensure_within_root(path)
            safe.unlink(missing_ok=True)
        except (BackupError, OSError):
            log.warning("Archive file %s could not be removed", job.file_path)
    audit.record(
        db, organization_id=job.organization_id, actor=user, action="backup_delete",
        entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
        summary=f"Deleted archive {job.backup_number}",
    )
    db.delete(job)
    db.commit()
    return job


