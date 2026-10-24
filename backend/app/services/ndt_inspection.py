"""Tenant-scoped manual NDT Inspection register operations."""

from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.models import NdtInspection, Rig, Well
from app.models.entities import User
from app.schemas.ndt_inspection import (
    NdtBulkActionOut, NdtBulkCreate, NdtEntryOut, NdtExportAudit,
    NdtImportRequest, NdtImportOut, NdtLineIn, NdtReference,
    NdtRigOption, NdtUpdate, NdtWellOption,
)
from app.services import audit


def _actor(user: User) -> str:
    return user.full_name or user.email


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "The NDT inspection record conflicts with existing data") from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(503, "The NDT inspection register could not be saved") from error


def _context(db: Session, organization_id: str, rig_id: str, well_id: str, scope: str) -> tuple[Rig, Well]:
    rig = db.scalar(select(Rig).where(Rig.id == rig_id, Rig.organization_id == organization_id, Rig.is_deleted.is_(False)))
    well = db.scalar(select(Well).where(Well.id == well_id, Well.organization_id == organization_id, Well.rig_id == rig_id, Well.is_deleted.is_(False)))
    if rig is None:
        raise HTTPException(422, "The selected rig is not available in this workspace")
    if well is None:
        raise HTTPException(422, "The selected well does not belong to the selected rig")
    if well.scope_is_deleted(scope) or well.scope_is_purged(scope):
        raise HTTPException(422, f"The selected well's {scope} scope is not available")
    return rig, well


def _out(row: NdtInspection) -> NdtEntryOut:
    return NdtEntryOut(
        id=row.id, rig_id=row.rig_id, rig_code=row.rig_code_snapshot, rig_name=row.rig_name_snapshot,
        well_id=row.well_id, well_code=row.well_code_snapshot, well_name=row.well_name_snapshot,
        scope=row.scope, description=row.description, quantity_received=row.quantity_received,
        quantity_consumed=row.quantity_consumed, quantity_backloaded_good=row.quantity_backloaded_good,
        quantity_backloaded_bad=row.quantity_backloaded_bad, remarks=row.remarks, is_deleted=row.is_deleted,
        deleted_at=row.deleted_at, created_by=row.created_by, updated_by=row.updated_by,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def reference_data(db: Session, organization_id: str) -> NdtReference:
    rigs = db.scalars(select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)).all()
    wells = db.scalars(select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False)).order_by(Well.well_code)).all()
    return NdtReference(
        rigs=[NdtRigOption(id=r.id, rig_code=r.rig_code, rig_name=r.rig_name, display_name=f"{r.rig_code} · {r.rig_name}") for r in rigs],
        wells=[NdtWellOption(id=w.id, rig_id=w.rig_id, well_code=w.well_code, well_name=w.well_name,
            drilling_available=not w.scope_is_deleted("drilling") and not w.scope_is_purged("drilling"),
            completion_available=not w.scope_is_deleted("completion") and not w.scope_is_purged("completion"),
            display_name=f"{w.well_code} · {w.well_name}") for w in wells],
    )


def list_entries(db: Session, organization_id: str, *, rig_id: str = "", well_id: str = "", scope: str = "", date_from: date | None = None, date_to: date | None = None, deleted: bool = False) -> list[NdtEntryOut]:
    query = select(NdtInspection).where(NdtInspection.organization_id == organization_id, NdtInspection.is_deleted.is_(deleted))
    if rig_id: query = query.where(NdtInspection.rig_id == rig_id)
    if well_id: query = query.where(NdtInspection.well_id == well_id)
    if scope: query = query.where(NdtInspection.scope == scope)
    if date_from: query = query.where(NdtInspection.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to: query = query.where(NdtInspection.created_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc))
    rows = db.scalars(query.order_by(NdtInspection.created_at.desc(), NdtInspection.id.desc())).all()
    return [_out(row) for row in rows]


def _new(organization_id: str, rig: Rig, well: Well, scope: str, line: NdtLineIn, actor: str) -> NdtInspection:
    return NdtInspection(
        organization_id=organization_id, rig_id=rig.id, rig_code_snapshot=rig.rig_code, rig_name_snapshot=rig.rig_name,
        well_id=well.id, well_code_snapshot=well.well_code, well_name_snapshot=well.well_name, scope=scope,
        description=line.description, quantity_received=line.quantity_received, quantity_consumed=line.quantity_consumed,
        quantity_backloaded_good=line.quantity_backloaded_good, quantity_backloaded_bad=line.quantity_backloaded_bad,
        remarks=line.remarks, created_by=actor, updated_by=actor,
    )


def create_bulk(db: Session, organization_id: str, data: NdtBulkCreate, user: User, request: Request | None) -> list[NdtEntryOut]:
    rig, well = _context(db, organization_id, data.rig_id, data.well_id, data.scope)
    rows = [_new(organization_id, rig, well, data.scope, line, _actor(user)) for line in data.lines]
    db.add_all(rows)
    db.flush()
    audit.record(db, organization_id=organization_id, actor=user, action="create", entity_type="ndt_inspection", entity_id=None,
        entity_label=f"{well.well_code} · {data.scope}", summary=f"Added {len(rows)} NDT inspection line(s)", request=request)
    _commit(db)
    return [_out(row) for row in rows]


def update_entry(db: Session, organization_id: str, entry_id: str, data: NdtUpdate, user: User, request: Request | None) -> NdtEntryOut:
    row = db.scalar(select(NdtInspection).where(NdtInspection.id == entry_id, NdtInspection.organization_id == organization_id, NdtInspection.is_deleted.is_(False)))
    if row is None: raise HTTPException(404, "NDT inspection entry not found")
    rig, well = _context(db, organization_id, data.rig_id, data.well_id, data.scope)
    for key, value in data.model_dump().items(): setattr(row, key, value)
    row.rig_code_snapshot, row.rig_name_snapshot = rig.rig_code, rig.rig_name
    row.well_code_snapshot, row.well_name_snapshot = well.well_code, well.well_name
    row.updated_by = _actor(user)
    audit.record(db, organization_id=organization_id, actor=user, action="update", entity_type="ndt_inspection", entity_id=row.id,
        entity_label=row.description, summary="Updated an NDT inspection line", request=request)
    _commit(db); db.refresh(row)
    return _out(row)


def _bulk(db: Session, organization_id: str, ids: list[str], user: User, request: Request | None, action: str) -> NdtBulkActionOut:
    rows = db.scalars(select(NdtInspection).where(NdtInspection.organization_id == organization_id, NdtInspection.id.in_(ids))).all()
    wanted = set(ids)
    if len(rows) != len(wanted): raise HTTPException(404, "One or more NDT inspection entries were not found")
    now = datetime.now(timezone.utc)
    affected = 0
    for row in rows:
        if action == "delete" and not row.is_deleted:
            row.is_deleted, row.deleted_at, affected = True, now, affected + 1
        elif action == "restore" and row.is_deleted:
            row.is_deleted, row.deleted_at, affected = False, None, affected + 1
        elif action == "permanent-delete":
            if not row.is_deleted: raise HTTPException(409, "Only deleted NDT inspection entries can be permanently removed")
            db.delete(row); affected += 1
    audit.record(db, organization_id=organization_id, actor=user, action=action, entity_type="ndt_inspection", entity_id=None,
        entity_label=f"{affected} NDT inspection line(s)", summary=f"{action.title()}d {affected} NDT inspection line(s)", request=request)
    _commit(db)
    return NdtBulkActionOut(affected_count=affected)


def soft_delete_entries(db, organization_id, ids, user, request): return _bulk(db, organization_id, ids, user, request, "delete")
def restore_entries(db, organization_id, ids, user, request): return _bulk(db, organization_id, ids, user, request, "restore")
def permanently_delete_entries(db, organization_id, ids, user, request): return _bulk(db, organization_id, ids, user, request, "permanent-delete")


def import_entries(db: Session, organization_id: str, data: NdtImportRequest, user: User, request: Request | None) -> NdtImportOut:
    rigs = {r.rig_code.lower(): r for r in db.scalars(select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False))).all()}
    wells = {w.well_code.lower(): w for w in db.scalars(select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False))).all()}
    prepared: list[tuple[Rig, Well, str, NdtLineIn]] = []; errors: list[str] = []
    for number, item in enumerate(data.rows, 2):
        try:
            rig, well, scope = rigs.get(item.rig_code.lower()), wells.get(item.well_code.lower()), item.scope.lower()
            if rig is None: raise ValueError("Rig code was not found")
            if well is None or well.rig_id != rig.id: raise ValueError("Well code was not found under that rig")
            if scope not in {"drilling", "completion"}: raise ValueError("Scope must be Drilling or Completion")
            _context(db, organization_id, rig.id, well.id, scope)
            line = NdtLineIn.model_validate(item.model_dump(exclude={"rig_code", "well_code", "scope"}))
            prepared.append((rig, well, scope, line))
        except (ValueError, ValidationError, HTTPException) as error:
            detail = error.detail if isinstance(error, HTTPException) else str(error)
            errors.append(f"Row {number}: {detail}")
    if errors: return NdtImportOut(created_count=0, errors=errors)
    rows = [_new(organization_id, rig, well, scope, line, _actor(user)) for rig, well, scope, line in prepared]
    db.add_all(rows)
    audit.record(db, organization_id=organization_id, actor=user, action="import", entity_type="ndt_inspection", entity_id=None,
        entity_label="NDT Inspection Register", summary=f"Imported {len(rows)} NDT inspection line(s)", request=request)
    _commit(db)
    return NdtImportOut(created_count=len(rows), errors=[])


def audit_export(db: Session, organization_id: str, data: NdtExportAudit, user: User, request: Request | None) -> None:
    audit.record(db, organization_id=organization_id, actor=user, action="export", entity_type="ndt_inspection", entity_id=None,
        entity_label="NDT Inspection Register", summary=f"Exported {data.record_count} line(s) as {data.format.upper()}", request=request)
    _commit(db)
