"""Backup & Recovery API.

Capabilities are split so the person who takes backups is not automatically the
person who may approve and run a restore:

``backup:read``               see the register, readiness and restore queue
``backup:create``             take a backup, verify a checksum, import an archive
``backup:download``           download an archive file
``backup:delete``             delete an archive or apply retention
``backup:settings``           change the schedule and retention policy
``backup:restore-request``    raise or cancel a restore request
``backup:restore-approve``    approve/reject a request and validate its archive
``backup:restore-execute``    apply a validated restore
"""

import tempfile
from datetime import datetime, timezone
from math import ceil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import Current, Db, granted, owner, require
from app.core.config import get_settings
from app.models import BackupJob, BackupRestoreRequest, BackupValidation, User
from app.schemas.backup import (
    BackupChecksumOut,
    BackupCleanupOut,
    BackupCreateIn,
    BackupJobList,
    BackupJobOut,
    BackupJobTableOut,
    BackupOverview,
    BackupReadiness,
    BackupRestoreRequestIn,
    BackupRestoreRequestList,
    BackupRestoreRequestOut,
    BackupSettingsIn,
    BackupSettingsOut,
    BackupValidationDetail,
    BackupValidationOut,
    BackupValidationTableOut,
    RestoreDecisionIn,
    RestoreExecuteIn,
)
from app.services import audit
from app.services import backup as service

router = APIRouter(prefix="/backup", tags=["Backup & Recovery"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fail(error: service.BackupError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def _allowed(user: User, *keys: str) -> bool:
    return owner(user) or bool(set(keys).intersection(granted(user)))


def _job_out(db: Db, user: User, job: BackupJob, open_request: str = "") -> BackupJobOut:
    return BackupJobOut(
        id=job.id,
        backup_number=job.backup_number,
        scope=job.scope,
        trigger_source=job.trigger_source,
        status=job.status,
        description=job.description,
        file_name=job.file_name,
        file_size_bytes=job.file_size_bytes,
        checksum_sha256=job.checksum_sha256,
        format_version=job.format_version,
        compression=job.compression,
        schema_revision=job.schema_revision,
        table_count=job.table_count,
        row_count=job.row_count,
        audit_row_count=job.audit_row_count,
        requested_by_display=job.requested_by_display,
        started_at=service.as_utc(job.started_at),
        completed_at=service.as_utc(job.completed_at),
        checksum_verified_at=service.as_utc(job.checksum_verified_at),
        error_message=job.error_message,
        retention_hold=job.retention_hold,
        created_at=service.as_utc(job.created_at) or datetime.now(timezone.utc),
        can_download=job.status in {"completed", "checksum_mismatch"} and bool(job.file_name),
        can_restore=job.status == "completed" and not open_request,
        open_request=open_request or "",
    )


def _open_request_map(db: Db, organization_id: str) -> dict[str, str]:
    rows = db.query(BackupRestoreRequest).filter(
        BackupRestoreRequest.organization_id == organization_id,
        BackupRestoreRequest.status.in_(service.PENDING_REQUEST_STATUSES),
    ).all()
    return {row.backup_job_id: row.request_number for row in rows}


def _latest_validation_status(db: Db, request_id: str) -> str:
    row = (
        db.query(BackupValidation)
        .filter(BackupValidation.restore_request_id == request_id)
        .order_by(BackupValidation.started_at.desc())
        .first()
    )
    return row.status if row else ""


def _request_out(db: Db, user: User, request: BackupRestoreRequest) -> BackupRestoreRequestOut:
    job = db.get(BackupJob, request.backup_job_id)
    validation_status = _latest_validation_status(db, request.id)
    can_approve = (
        request.status == "pending_approval"
        and request.requested_by_user_id != user.id
        and _allowed(user, "backup:restore-approve")
    )
    can_validate = request.status in {"approved", "validation_failed"} and _allowed(user, "backup:restore-approve")
    can_execute = (
        request.status in {"validated", "restore_failed"}
        and validation_status in {"passed", "passed_with_warnings"}
        and _allowed(user, "backup:restore-execute")
    )
    can_cancel = request.status in {"pending_approval", "approved", "validated", "validation_failed", "restore_failed"} and _allowed(
        user, "backup:restore-request", "backup:restore-approve"
    )
    return BackupRestoreRequestOut(
        id=request.id,
        request_number=request.request_number,
        backup_job_id=request.backup_job_id or "",
        backup_number=request.backup_number,
        backup_file_name=job.file_name if job else "",
        backup_scope=request.scope,
        backup_status=job.status if job else "",
        status=request.status,
        reason=request.reason,
        business_impact=request.business_impact,
        requested_by_display=request.requested_by_display,
        requested_at=service.as_utc(request.requested_at) or datetime.now(timezone.utc),
        reviewed_by_display=request.reviewed_by_display,
        reviewed_at=service.as_utc(request.reviewed_at),
        review_remarks=request.review_remarks,
        validated_at=service.as_utc(request.validated_at),
        executed_by_display=request.executed_by_display,
        executed_at=service.as_utc(request.executed_at),
        execution_remarks=request.execution_remarks,
        pre_restore_backup_number=request.pre_restore_backup_number,
        tables_restored=request.tables_restored,
        rows_restored=request.rows_restored,
        error_message=request.error_message,
        confirmation_phrase=f"{service.RESTORE_CONFIRM_PREFIX} {request.backup_number}",
        can_approve=can_approve,
        can_validate=can_validate,
        can_execute=can_execute,
        can_cancel=can_cancel,
        latest_validation_status=validation_status,
    )


def _validation_out(validation: BackupValidation) -> BackupValidationOut:
    return BackupValidationOut(
        id=validation.id,
        validation_number=validation.validation_number,
        restore_request_id=validation.restore_request_id,
        backup_number=validation.backup_number,
        status=validation.status,
        checksum_matched=validation.checksum_matched,
        dry_run_performed=validation.dry_run_performed,
        table_count=validation.table_count,
        row_count=validation.row_count,
        missing_tables=validation.missing_tables,
        changed_tables=validation.changed_tables,
        started_by_display=validation.started_by_display,
        started_at=service.as_utc(validation.started_at) or datetime.now(timezone.utc),
        completed_at=service.as_utc(validation.completed_at),
        error_message=validation.error_message,
    )


def _settings_out(db: Db, user: User, settings) -> BackupSettingsOut:
    multi_tenant = service.organization_count(db) > 1
    return BackupSettingsOut(
        id=settings.id,
        enabled=settings.enabled,
        schedule_mode=settings.schedule_mode,
        interval_value=settings.interval_value,
        run_time=settings.run_time,
        retention_days=settings.retention_days,
        keep_minimum=settings.keep_minimum,
        backup_directory=settings.backup_directory,
        scope=settings.scope,
        compression_enabled=settings.compression_enabled,
        last_run_at=service.as_utc(settings.last_run_at),
        next_run_at=service.as_utc(settings.next_run_at),
        folder=service.folder_name(settings, service.workspace_slug(db, user.organization_id)),
        multi_tenant=multi_tenant,
        allowed_scope="workspace" if multi_tenant else "workspace|full",
        server_time=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Overview, readiness, settings
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=BackupOverview, dependencies=[Depends(require("backup:read"))])
def overview(db: Db, user: Current) -> BackupOverview:
    jobs = db.query(BackupJob).filter(BackupJob.organization_id == user.organization_id).all()
    requests = db.query(BackupRestoreRequest).filter(BackupRestoreRequest.organization_id == user.organization_id).all()
    completed = [job for job in jobs if job.status == "completed"]
    latest = max(completed, key=lambda job: service.as_utc(job.created_at) or datetime.min.replace(tzinfo=timezone.utc), default=None)
    ready = service.readiness(db, user.organization_id)
    return BackupOverview(
        total_backups=len(jobs),
        completed=len(completed),
        failed=sum(1 for job in jobs if job.status == "failed"),
        checksum_mismatch=sum(1 for job in jobs if job.status == "checksum_mismatch"),
        running=sum(1 for job in jobs if job.status in service.RUNNING_JOB_STATUSES),
        total_size_bytes=sum(job.file_size_bytes for job in completed),
        latest_completed_at=service.as_utc(latest.completed_at) if latest else None,
        verified_count=sum(1 for job in jobs if job.checksum_verified_at is not None),
        scheduled=ready["scheduled"],
        next_run_at=ready["next_run_at"],
        open_requests=sum(1 for request in requests if request.status in service.PENDING_REQUEST_STATUSES),
        restored_count=sum(1 for request in requests if request.status == "restored"),
        readiness=BackupReadiness(**{**ready, "latest_backup": _job_out(db, user, ready["latest_backup"]) if ready["latest_backup"] else None}),
    )


@router.get("/readiness", response_model=BackupReadiness, dependencies=[Depends(require("backup:read"))])
def readiness(db: Db, user: Current) -> BackupReadiness:
    ready = service.readiness(db, user.organization_id)
    latest = ready["latest_backup"]
    return BackupReadiness(**{**ready, "latest_backup": _job_out(db, user, latest) if latest else None})


@router.get("/settings", response_model=BackupSettingsOut, dependencies=[Depends(require("backup:read"))])
def get_settings_row(db: Db, user: Current) -> BackupSettingsOut:
    settings = service.get_or_create_settings(db, user.organization_id)
    db.commit()
    return _settings_out(db, user, settings)


@router.put("/settings", response_model=BackupSettingsOut, dependencies=[Depends(require("backup:settings"))])
def update_settings(payload: BackupSettingsIn, request: Request, db: Db, user: Current) -> BackupSettingsOut:
    if payload.scope == "full" and service.organization_count(db) > 1:
        raise HTTPException(
            409,
            "This deployment holds more than one workspace, so full-database backups are not offered here. "
            "A full archive would contain other tenants' rows.",
        )
    settings = service.get_or_create_settings(db, user.organization_id)
    # Prove the destination is writable now, not when the first scheduled run fails.
    try:
        settings.backup_directory = payload.backup_directory
        directory = service.archive_directory(settings, service.workspace_slug(db, user.organization_id))
        probe = Path(directory) / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except service.BackupError as error:
        db.rollback()
        raise _fail(error) from error
    except OSError as error:
        db.rollback()
        raise HTTPException(422, f"That backup folder cannot be written to: {error}") from error

    settings.enabled = payload.enabled
    settings.schedule_mode = payload.schedule_mode
    settings.interval_value = payload.interval_value
    settings.run_time = payload.run_time
    settings.retention_days = payload.retention_days
    settings.keep_minimum = payload.keep_minimum
    settings.scope = payload.scope
    settings.compression_enabled = payload.compression_enabled
    settings.updated_by_user_id = user.id
    settings.next_run_at = service.calculate_next_run(settings)
    settings.updated_at = datetime.now(timezone.utc)
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="backup_settings",
        entity_type="backup", entity_id=settings.id, entity_label="Backup policy",
        summary=(
            f"Backup policy updated: {'on' if settings.enabled else 'off'}, {settings.schedule_mode} every "
            f"{settings.interval_value} at {settings.run_time}, keep {settings.retention_days} days "
            f"(minimum {settings.keep_minimum}), {settings.scope} scope, folder {service.folder_name(settings, service.workspace_slug(db, user.organization_id))}"
        ),
        request=request,
    )
    db.commit()
    return _settings_out(db, user, settings)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.get("/jobs", response_model=BackupJobList, dependencies=[Depends(require("backup:read"))])
def list_jobs(
    db: Db,
    user: Current,
    status: str = Query(default="", max_length=30),
    scope: str = Query(default="", max_length=20),
    q: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BackupJobList:
    from sqlalchemy import or_

    query = db.query(BackupJob).filter(BackupJob.organization_id == user.organization_id)
    if status:
        query = query.filter(BackupJob.status == status)
    if scope:
        query = query.filter(BackupJob.scope == scope)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(BackupJob.backup_number.ilike(like), BackupJob.description.ilike(like), BackupJob.requested_by_display.ilike(like)))
    total = query.count()
    rows = query.order_by(BackupJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    open_requests = _open_request_map(db, user.organization_id)
    return BackupJobList(
        items=[_job_out(db, user, job, open_requests.get(job.id, "")) for job in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, ceil(total / page_size)),
    )


@router.post("/jobs", response_model=BackupJobOut, dependencies=[Depends(require("backup:create"))])
def create_backup(payload: BackupCreateIn, request: Request, db: Db, user: Current) -> BackupJobOut:
    settings = service.get_or_create_settings(db, user.organization_id)
    scope = payload.scope or settings.scope or "workspace"
    try:
        job = service.create_job(
            db, organization_id=user.organization_id, scope=scope,
            trigger_source="manual", description=payload.description or "Manual backup", user=user,
        )
        db.commit()
        job = service.execute_job(db, job, user=user, settings=settings)
    except service.BackupError as error:
        db.rollback()
        raise _fail(error) from error
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="backup_request",
        entity_type="backup", entity_id=job.id, entity_label=job.backup_number,
        summary=f"Requested manual {scope} backup {job.backup_number}", request=request,
    )
    db.commit()
    if job.status == "failed":
        raise HTTPException(500, f"Backup {job.backup_number} failed: {job.error_message}")
    return _job_out(db, user, job)


@router.get("/jobs/{job_id}/tables", response_model=list[BackupJobTableOut], dependencies=[Depends(require("backup:read"))])
def job_tables(job_id: str, db: Db, user: Current) -> list[BackupJobTableOut]:
    job = db.get(BackupJob, job_id)
    if job is None or job.organization_id != user.organization_id:
        raise HTTPException(404, "That backup is not in this workspace.")
    return [
        BackupJobTableOut(table_name=row.table_name, module_group=row.module_group, row_count=row.row_count, column_count=row.column_count)
        for row in service.archive_tables(db, job)
    ]


@router.post("/jobs/{job_id}/verify", response_model=BackupChecksumOut, dependencies=[Depends(require("backup:create"))])
def verify(job_id: str, request: Request, db: Db, user: Current) -> BackupChecksumOut:
    job = db.get(BackupJob, job_id)
    if job is None or job.organization_id != user.organization_id:
        raise HTTPException(404, "That backup is not in this workspace.")
    try:
        result = service.verify_job(db, job, user)
    except service.BackupError as error:
        raise _fail(error) from error
    return BackupChecksumOut(**result)


@router.get("/jobs/{job_id}/download", dependencies=[Depends(require("backup:download"))])
def download(job_id: str, db: Db, user: Current) -> FileResponse:
    job = db.get(BackupJob, job_id)
    if job is None or job.organization_id != user.organization_id:
        raise HTTPException(404, "That backup is not in this workspace.")
    if job.status not in {"completed", "checksum_mismatch"}:
        raise HTTPException(409, "Only a completed backup can be downloaded.")
    try:
        path = service.ensure_within_root(Path(job.file_path))
    except service.BackupError as error:
        raise _fail(error) from error
    if not path.exists():
        raise HTTPException(404, "The archive file is missing from the server. Take a fresh backup.")
    service.audit_export(db, job, user)
    return FileResponse(path, media_type="application/gzip", filename=job.file_name or path.name)


@router.post("/jobs/import", response_model=BackupJobOut, dependencies=[Depends(require("backup:create"))])
def import_archive(
    request: Request,
    db: Db,
    user: Current,
    file: UploadFile = File(...),
    description: str = Form(default="", max_length=500),
) -> BackupJobOut:
    limits = get_settings().backup_max_upload_mb * 1024 * 1024
    root = service.backup_root()
    uploads = root / ".uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(delete=False, dir=uploads, suffix=".upload")
    size = 0
    try:
        while True:
            block = file.file.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > limits:
                raise HTTPException(413, f"That archive is larger than the {get_settings().backup_max_upload_mb} MB upload limit.")
            handle.write(block)
        handle.close()
        job = service.import_archive(
            db, organization_id=user.organization_id, source=Path(handle.name),
            file_name=file.filename or "imported-archive", user=user, description=description,
        )
    except service.BackupError as error:
        db.rollback()
        Path(handle.name).unlink(missing_ok=True)
        raise _fail(error) from error
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return _job_out(db, user, job)


@router.delete("/jobs/{job_id}", status_code=204, dependencies=[Depends(require("backup:delete"))])
def delete_job(job_id: str, request: Request, db: Db, user: Current) -> None:
    job = db.get(BackupJob, job_id)
    if job is None or job.organization_id != user.organization_id:
        raise HTTPException(404, "That backup is not in this workspace.")
    try:
        service.delete_job(db, job, user)
    except service.BackupError as error:
        raise _fail(error) from error


@router.post("/cleanup", response_model=BackupCleanupOut, dependencies=[Depends(require("backup:delete"))])
def cleanup(db: Db, user: Current, dry_run: bool = Query(default=False)) -> BackupCleanupOut:
    result = service.cleanup(db, user.organization_id, user, dry_run=dry_run)
    return BackupCleanupOut(**result)


# ---------------------------------------------------------------------------
# Restore workflow
# ---------------------------------------------------------------------------


@router.get("/restore-requests", response_model=BackupRestoreRequestList, dependencies=[Depends(require("backup:read"))])
def list_restore_requests(
    db: Db,
    user: Current,
    status: str = Query(default="", max_length=30),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> BackupRestoreRequestList:
    query = db.query(BackupRestoreRequest).filter(BackupRestoreRequest.organization_id == user.organization_id)
    if status:
        query = query.filter(BackupRestoreRequest.status == status)
    total = query.count()
    rows = query.order_by(BackupRestoreRequest.requested_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return BackupRestoreRequestList(
        items=[_request_out(db, user, row) for row in rows],
        total=total, page=page, page_size=page_size, pages=max(1, ceil(total / page_size)),
    )


@router.post("/restore-requests", response_model=BackupRestoreRequestOut, status_code=201, dependencies=[Depends(require("backup:restore-request"))])
def create_restore_request(payload: BackupRestoreRequestIn, db: Db, user: Current) -> BackupRestoreRequestOut:
    job = db.get(BackupJob, payload.backup_job_id)
    if job is None or job.organization_id != user.organization_id:
        raise HTTPException(404, "That backup is not in this workspace.")
    try:
        row = service.create_restore_request(
            db, organization_id=user.organization_id, job=job,
            reason=payload.reason, business_impact=payload.business_impact, user=user,
        )
    except service.BackupError as error:
        raise _fail(error) from error
    return _request_out(db, user, row)


def _request_or_404(db: Db, user: Current, request_id: str) -> BackupRestoreRequest:
    row = db.get(BackupRestoreRequest, request_id)
    if row is None or row.organization_id != user.organization_id:
        raise HTTPException(404, "That restore request is not in this workspace.")
    return row


@router.post("/restore-requests/{request_id}/approve", response_model=BackupRestoreRequestOut, dependencies=[Depends(require("backup:restore-approve"))])
def approve(request_id: str, payload: RestoreDecisionIn, db: Db, user: Current) -> BackupRestoreRequestOut:
    row = _request_or_404(db, user, request_id)
    try:
        row = service.review_restore_request(db, row, user, approve=True, remarks=payload.remarks)
    except service.BackupError as error:
        raise _fail(error) from error
    return _request_out(db, user, row)


@router.post("/restore-requests/{request_id}/reject", response_model=BackupRestoreRequestOut, dependencies=[Depends(require("backup:restore-approve"))])
def reject(request_id: str, payload: RestoreDecisionIn, db: Db, user: Current) -> BackupRestoreRequestOut:
    row = _request_or_404(db, user, request_id)
    try:
        row = service.review_restore_request(db, row, user, approve=False, remarks=payload.remarks)
    except service.BackupError as error:
        raise _fail(error) from error
    return _request_out(db, user, row)


@router.post("/restore-requests/{request_id}/cancel", response_model=BackupRestoreRequestOut, dependencies=[Depends(require("backup:restore-request"))])
def cancel(request_id: str, payload: RestoreDecisionIn, db: Db, user: Current) -> BackupRestoreRequestOut:
    row = _request_or_404(db, user, request_id)
    try:
        row = service.cancel_restore_request(db, row, user, payload.remarks)
    except service.BackupError as error:
        raise _fail(error) from error
    return _request_out(db, user, row)


@router.post("/restore-requests/{request_id}/validate", response_model=BackupValidationDetail, dependencies=[Depends(require("backup:restore-approve"))])
def validate(request_id: str, db: Db, user: Current) -> BackupValidationDetail:
    row = _request_or_404(db, user, request_id)
    try:
        validation = service.validate_restore_request(db, row, user)
    except service.BackupError as error:
        raise _fail(error) from error
    tables = [
        BackupValidationTableOut(table_name=item.table_name, archive_rows=item.archive_rows, database_rows=item.database_rows, status=item.status)
        for item in service.validation_tables(db, validation.id)
    ]
    return BackupValidationDetail(validation=_validation_out(validation), tables=tables)


@router.get("/restore-requests/{request_id}/validations", response_model=list[BackupValidationOut], dependencies=[Depends(require("backup:read"))])
def validations(request_id: str, db: Db, user: Current) -> list[BackupValidationOut]:
    row = _request_or_404(db, user, request_id)
    return [_validation_out(item) for item in service.request_validations(db, row.id)]


@router.post("/restore-requests/{request_id}/execute", response_model=BackupRestoreRequestOut, dependencies=[Depends(require("backup:restore-execute"))])
def execute(request_id: str, payload: RestoreExecuteIn, db: Db, user: Current) -> BackupRestoreRequestOut:
    row = _request_or_404(db, user, request_id)
    try:
        row = service.execute_restore_request(
            db, row, user,
            confirmation_text=payload.confirmation_text, remarks=payload.remarks,
        )
    except service.BackupError as error:
        raise _fail(error) from error
    if row.status == "restore_failed":
        raise HTTPException(500, f"Restore failed: {row.error_message}. The workspace data was not changed.")
    return _request_out(db, user, row)
