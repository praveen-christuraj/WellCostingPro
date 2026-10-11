"""Tenant-scoped Rig & Well Management APIs.

Rigs own wells. Well configuration uses the workspace's Hole Sections and
Phases master data, while well sub activities are tied to one well and one
workspace Activity. All business rows are soft-deleted first, exports/imports
and lifecycle changes are audited, and every lookup is organization-scoped.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import Current, Db, granted, owner, require
from app.models import (
    Activity,
    AuditLog,
    HoleSection,
    Phase,
    Rig,
    Well,
    WellPhase,
    WellSection,
    WellSubActivity,
)
from app.schemas.rig_well import (
    DeletedRigWellRecord,
    DeletedSelection,
    RigCreate,
    RigDropdownOut,
    RigUpdate,
    RigOut,
    RigWellActivityCount,
    RigWellBulkActionResponse,
    RigWellExportAudit,
    RigWellIDs,
    RigWellImportRequest,
    RigWellImportResponse,
    RigWellOverview,
    RigWellConfigurationOptions,
    RigWellMasterDataOption,
    RigWellRecentActivity,
    WellConfigurationIn,
    WellConfigurationOut,
    WellCreate,
    WellOut,
    WellSubActivityCreate,
    WellSubActivityOut,
    WellSubActivityUpdate,
    WellTransitionIn,
    WellUpdate,
)
from app.services import audit

router = APIRouter(prefix="/rig-well", tags=["Rig & Well Management"])

IMPORT_MAX_ROWS = 5000
RECENT_AUDIT_TYPES = ("rig", "well", "well_configuration", "well_sub_activity")
ENTITY_MODELS: dict[str, Any] = {
    "rig": Rig,
    "well": Well,
    "well_sub_activity": WellSubActivity,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This change conflicts with an existing record or a dependent workspace record",
        ) from error


def _record_audit(
    db: Session,
    *,
    user: Any,
    action: str,
    entity_type: str,
    record_id: str | None,
    entity_label: str,
    summary: str,
    request: Request,
) -> None:
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type=entity_type,
        entity_id=record_id,
        entity_label=entity_label,
        summary=summary,
        request=request,
    )


def _rig_or_404(
    db: Session,
    rig_id: str,
    organization_id: str,
    *,
    include_deleted: bool = True,
) -> Rig:
    statement = select(Rig).where(
        Rig.id == rig_id,
        Rig.organization_id == organization_id,
    )
    if not include_deleted:
        statement = statement.where(Rig.is_deleted.is_(False))
    rig = db.scalar(statement)
    if rig is None:
        raise HTTPException(status_code=404, detail="Rig not found in this workspace")
    return rig


def _well_or_404(
    db: Session,
    well_id: str,
    organization_id: str,
    *,
    include_deleted: bool = True,
) -> Well:
    statement = (
        select(Well)
        .options(
            joinedload(Well.rig),
            selectinload(Well.sections).selectinload(WellSection.phases),
        )
        .where(Well.id == well_id, Well.organization_id == organization_id)
    )
    if not include_deleted:
        statement = statement.where(Well.is_deleted.is_(False))
    well = db.scalar(statement)
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    return well


def _well_for_sub_activity(
    db: Session,
    well_id: str,
    organization_id: str,
    *,
    include_deleted: bool = False,
) -> Well:
    well = _well_or_404(db, well_id, organization_id, include_deleted=include_deleted)
    if well.rig is None or well.rig.organization_id != organization_id or well.rig.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the well's rig before using this well")
    return well


def _master_record_or_422(db: Session, model: Any, record_id: str, organization_id: str, label: str) -> Any:
    record = db.scalar(
        select(model).where(
            model.id == record_id,
            model.organization_id == organization_id,
            model.is_deleted.is_(False),
        )
    )
    if record is None:
        raise HTTPException(
            status_code=422,
            detail=f"Select an active {label} from this workspace's Master Data",
        )
    return record


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key).strip().lower().replace(" ", "_").replace("-", "_"): value
        for key, value in row.items()
    }


def _row_value(row: dict[str, Any], *aliases: str) -> Any:
    normalized = _normalise_row(row)
    for alias in aliases:
        key = alias.strip().lower().replace(" ", "_").replace("-", "_")
        if key in normalized and normalized[key] not in (None, ""):
            return normalized[key]
    return None


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
        for issue in error.errors()
    )


def _well_totals(well: Well) -> tuple[Decimal | None, Decimal]:
    total_depth: Decimal | None = None
    total_days = Decimal("0")
    for section in well.sections:
        total_depth = section.to_depth
        for phase in section.phases:
            total_days += phase.days
    return total_depth, total_days


def _rig_out(rig: Rig, well_count: int = 0) -> RigOut:
    return RigOut(
        id=rig.id,
        rig_code=rig.rig_code,
        rig_name=rig.rig_name,
        remarks=rig.remarks or "",
        well_count=well_count,
        is_deleted=rig.is_deleted,
        deleted_at=rig.deleted_at,
        created_at=rig.created_at,
        updated_at=rig.updated_at,
    )


def _well_out(well: Well, sub_activity_count: int = 0) -> WellOut:
    total_depth, total_days = _well_totals(well)
    rig = well.rig
    return WellOut(
        id=well.id,
        rig_id=well.rig_id,
        rig_code=rig.rig_code if rig else "",
        rig_name=rig.rig_name if rig else "",
        rig_display=(f"{rig.rig_code} — {rig.rig_name}" if rig else ""),
        well_code=well.well_code,
        well_name=well.well_name,
        well_location=well.well_location,
        block=well.block,
        objective=well.objective,
        remarks=well.remarks or "",
        status=well.status,
        config_status=well.config_status,
        depth_unit=well.depth_unit,
        total_depth=total_depth,
        total_days=total_days,
        section_count=len(well.sections),
        sub_activity_count=sub_activity_count,
        is_deleted=well.is_deleted,
        deleted_at=well.deleted_at,
        created_at=well.created_at,
        updated_at=well.updated_at,
    )


def _well_configuration_out(well: Well) -> WellConfigurationOut:
    total_depth, total_days = _well_totals(well)
    sections = []
    for section in well.sections:
        section_days = sum((phase.days for phase in section.phases), Decimal("0"))
        phases = [
            {
                "id": phase.id,
                "phase_id": phase.phase_id,
                "phase_code": phase.phase.phase_code if phase.phase else "",
                "phase_name": phase.phase.phase_name if phase.phase else "",
                "days": phase.days,
                "remarks": phase.remarks or "",
            }
            for phase in section.phases
        ]
        sections.append(
            {
                "id": section.id,
                "hole_section_id": section.hole_section_id,
                "section_code": section.hole_section.section_code if section.hole_section else "",
                "section_name": section.hole_section.section_name if section.hole_section else "",
                "from_depth": section.from_depth,
                "to_depth": section.to_depth,
                "remarks": section.remarks or "",
                "total_days": section_days,
                "phases": phases,
            }
        )
    return WellConfigurationOut(
        well_id=well.id,
        well_code=well.well_code,
        well_name=well.well_name,
        rig_code=well.rig.rig_code if well.rig else "",
        rig_name=well.rig.rig_name if well.rig else "",
        status=well.status,
        config_status=well.config_status,
        depth_unit=well.depth_unit,
        total_depth=total_depth,
        total_days=total_days,
        sections=sections,
    )


def _sub_activity_or_404(
    db: Session,
    record_id: str,
    organization_id: str,
    *,
    well_id: str | None = None,
    include_deleted: bool = True,
) -> WellSubActivity:
    statement = (
        select(WellSubActivity)
        .options(joinedload(WellSubActivity.well).joinedload(Well.rig), joinedload(WellSubActivity.activity))
        .where(WellSubActivity.id == record_id, WellSubActivity.organization_id == organization_id)
    )
    if well_id is not None:
        statement = statement.where(WellSubActivity.well_id == well_id)
    if not include_deleted:
        statement = statement.where(WellSubActivity.is_deleted.is_(False))
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(status_code=404, detail="Well sub activity not found in this workspace")
    return record


def _sub_activity_out(record: WellSubActivity) -> WellSubActivityOut:
    well = record.well
    rig = well.rig if well else None
    activity = record.activity
    return WellSubActivityOut(
        id=record.id,
        well_id=record.well_id,
        sub_activity_code=record.sub_activity_code,
        sub_activity_name=record.sub_activity_name,
        activity_id=record.activity_id,
        responsible_party=record.responsible_party,
        description=record.description,
        is_deleted=record.is_deleted,
        deleted_at=record.deleted_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        well_code=well.well_code if well else "",
        well_name=well.well_name if well else "",
        rig_id=well.rig_id if well else "",
        rig_code=rig.rig_code if rig else "",
        rig_name=rig.rig_name if rig else "",
        activity_code=activity.activity_code if activity else "",
        activity_name=activity.activity_name if activity else "",
        activity_display=(
            f"{activity.activity_code} — {activity.activity_name}" if activity else ""
        ),
    )


def _records_for_ids(
    db: Session,
    model: Any,
    ids: list[str],
    organization_id: str,
    *,
    deleted: bool,
) -> list[Any]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate record IDs are not allowed")
    records = list(
        db.scalars(
            select(model).where(
                model.organization_id == organization_id,
                model.id.in_(ids),
            )
        ).all()
    )
    if len(records) != len(ids):
        raise HTTPException(status_code=404, detail="One or more records do not belong to this workspace")
    if any(record.is_deleted is not deleted for record in records):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"This bulk action requires only {expected} records")
    return records


def _count_children(db: Session, model: Any, organization_id: str, **filters: Any) -> int:
    statement = select(func.count(model.id)).where(model.organization_id == organization_id)
    for field, value in filters.items():
        statement = statement.where(getattr(model, field) == value)
    return int(db.scalar(statement) or 0)


def _code_conflict_message(entity: str, code: str, *, deleted: bool = False) -> str:
    if deleted:
        return f"{entity} code '{code}' is retained in Deleted Entries; restore or permanently delete it first"
    return f"{entity} code '{code}' already exists in this workspace"


# ---------------------------------------------------------------------------
# Overview and dropdowns
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=RigWellOverview,
    dependencies=[Depends(require("rig-well:read"))],
)
def overview(db: Db, user: Current) -> RigWellOverview:
    org_id = user.organization_id

    def count(model: Any, *, deleted: bool | None = None, extra: tuple[Any, ...] = ()) -> int:
        conditions = [model.organization_id == org_id, *extra]
        if deleted is not None:
            conditions.append(model.is_deleted.is_(deleted))
        return int(db.scalar(select(func.count(model.id)).where(*conditions)) or 0)

    active_rigs = count(Rig, deleted=False)
    deleted_rigs = count(Rig, deleted=True)
    active_wells = count(Well, deleted=False, extra=(Well.status == "active",))
    deleted_wells = count(Well, deleted=True)
    active_sub_activities = count(WellSubActivity, deleted=False)
    deleted_sub_activities = count(WellSubActivity, deleted=True)
    configured_wells = count(
        Well, deleted=False, extra=(Well.config_status == "configured", Well.status == "active")
    )
    draft_wells = count(Well, deleted=False, extra=(Well.config_status == "draft", Well.status == "active"))
    completed_wells = count(Well, deleted=False, extra=(Well.status == "completed",))

    activity_rows = db.execute(
        select(
            Activity.id,
            Activity.activity_code,
            Activity.activity_name,
            func.count(WellSubActivity.id),
        )
        .join(WellSubActivity, WellSubActivity.activity_id == Activity.id)
        .join(Well, Well.id == WellSubActivity.well_id)
        .join(Rig, Rig.id == Well.rig_id)
        .where(
            Activity.organization_id == org_id,
            WellSubActivity.organization_id == org_id,
            WellSubActivity.is_deleted.is_(False),
            Well.organization_id == org_id,
            Well.is_deleted.is_(False),
            Rig.organization_id == org_id,
            Rig.is_deleted.is_(False),
        )
        .group_by(Activity.id, Activity.activity_code, Activity.activity_name)
        .order_by(func.count(WellSubActivity.id).desc(), Activity.activity_code)
        .limit(8)
    ).all()
    activity_counts = [
        RigWellActivityCount(key=row[0], label=f"{row[1]} — {row[2]}", count=int(row[3]))
        for row in activity_rows
    ]

    recent = []
    if owner(user) or "audit:read" in granted(user):
        recent = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.entity_type.in_(RECENT_AUDIT_TYPES),
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(8)
        ).all()
    return RigWellOverview(
        active_rigs=active_rigs,
        deleted_rigs=deleted_rigs,
        active_wells=active_wells,
        deleted_wells=deleted_wells,
        active_sub_activities=active_sub_activities,
        deleted_sub_activities=deleted_sub_activities,
        configured_wells=configured_wells,
        draft_wells=draft_wells,
        completed_wells=completed_wells,
        activity_counts=activity_counts,
        recent_activity=[
            RigWellRecentActivity(
                id=entry.id,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_label=entry.entity_label,
                summary=entry.summary,
                created_at=entry.created_at,
            )
            for entry in recent
        ],
    )


@router.get(
    "/rigs/dropdown",
    response_model=list[RigDropdownOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_rigs_dropdown(db: Db, user: Current) -> list[RigDropdownOut]:
    count_rows = db.execute(
        select(Well.rig_id, func.count(Well.id))
        .where(
            Well.organization_id == user.organization_id,
            Well.is_deleted.is_(False),
            Well.status == "active",
        )
        .group_by(Well.rig_id)
    ).all()
    counts = {rig_id: int(value) for rig_id, value in count_rows}
    rigs = db.scalars(
        select(Rig)
        .where(Rig.organization_id == user.organization_id, Rig.is_deleted.is_(False))
        .order_by(Rig.rig_code)
    ).all()
    return [
        RigDropdownOut(
            id=rig.id,
            rig_code=rig.rig_code,
            rig_name=rig.rig_name,
            display_name=f"{rig.rig_code} — {rig.rig_name}",
            well_count=counts.get(rig.id, 0),
        )
        for rig in rigs
    ]


@router.get(
    "/configuration-options",
    response_model=RigWellConfigurationOptions,
    dependencies=[Depends(require("rig-well:read"))],
)
def configuration_options(db: Db, user: Current) -> RigWellConfigurationOptions:
    sections = db.scalars(
        select(HoleSection)
        .where(HoleSection.organization_id == user.organization_id, HoleSection.is_deleted.is_(False))
        .order_by(HoleSection.section_code)
    ).all()
    phases = db.scalars(
        select(Phase)
        .where(Phase.organization_id == user.organization_id, Phase.is_deleted.is_(False))
        .order_by(Phase.phase_code)
    ).all()
    return RigWellConfigurationOptions(
        hole_sections=[RigWellMasterDataOption(id=item.id, code=item.section_code, name=item.section_name) for item in sections],
        phases=[RigWellMasterDataOption(id=item.id, code=item.phase_code, name=item.phase_name) for item in phases],
    )


# ---------------------------------------------------------------------------
# Rigs
# ---------------------------------------------------------------------------


@router.get("/rigs", response_model=list[RigOut], dependencies=[Depends(require("rig-well:read"))])
def list_rigs(db: Db, user: Current, search: str | None = Query(default=None, max_length=200)) -> list[RigOut]:
    statement = select(Rig).where(
        Rig.organization_id == user.organization_id,
        Rig.is_deleted.is_(False),
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        statement = statement.where(
            or_(Rig.rig_code.ilike(like), Rig.rig_name.ilike(like), Rig.remarks.ilike(like))
        )
    records = db.scalars(statement.order_by(Rig.rig_code)).all()
    count_rows = db.execute(
        select(Well.rig_id, func.count(Well.id))
        .where(Well.organization_id == user.organization_id, Well.is_deleted.is_(False), Well.status == "active")
        .group_by(Well.rig_id)
    ).all()
    counts = {rig_id: int(value) for rig_id, value in count_rows}
    return [_rig_out(record, counts.get(record.id, 0)) for record in records]


@router.post(
    "/rigs",
    response_model=RigOut,
    status_code=201,
    dependencies=[Depends(require("rig-well:create"))],
)
def create_rig(data: RigCreate, request: Request, db: Db, user: Current) -> RigOut:
    existing = db.scalar(
        select(Rig).where(
            Rig.organization_id == user.organization_id,
            Rig.rig_code == data.rig_code,
        )
    )
    if existing is not None:
        if not existing.is_deleted:
            raise HTTPException(status_code=409, detail=_code_conflict_message("Rig", data.rig_code))
        existing.rig_name = data.rig_name
        existing.remarks = data.remarks
        existing.is_deleted = False
        existing.deleted_at = None
        _record_audit(
            db, user=user, action="restore", entity_type="rig", record_id=existing.id,
            entity_label=existing.rig_code,
            summary=f"Restored and updated rig {existing.rig_code} from create",
            request=request,
        )
        _commit(db)
        db.refresh(existing)
        return _rig_out(existing)

    rig = Rig(
        organization_id=user.organization_id,
        rig_code=data.rig_code,
        rig_name=data.rig_name,
        remarks=data.remarks,
    )
    db.add(rig)
    db.flush()
    _record_audit(
        db, user=user, action="create", entity_type="rig", record_id=rig.id,
        entity_label=rig.rig_code,
        summary=f"Created rig {rig.rig_code} — {rig.rig_name}",
        request=request,
    )
    _commit(db)
    db.refresh(rig)
    return _rig_out(rig)


@router.patch(
    "/rigs/{rig_id}",
    response_model=RigOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def update_rig(rig_id: str, data: RigUpdate, request: Request, db: Db, user: Current) -> RigOut:
    rig = _rig_or_404(db, rig_id, user.organization_id, include_deleted=False)
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field, value in payload.items():
        if value is None:
            continue
        if field == "remarks":
            value = value or ""
        if getattr(rig, field) == value:
            continue
        if field == "rig_code":
            duplicate = db.scalar(
                select(Rig).where(
                    Rig.organization_id == user.organization_id,
                    Rig.rig_code == value,
                    Rig.id != rig.id,
                )
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409,
                    detail=_code_conflict_message("Rig", value, deleted=duplicate.is_deleted),
                )
        setattr(rig, field, value)
        changed.append(field)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="rig", record_id=rig.id,
            entity_label=rig.rig_code,
            summary=f"Updated rig {rig.rig_code}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
        db.refresh(rig)
    return _rig_out(rig, _count_children(db, Well, user.organization_id, rig_id=rig.id, is_deleted=False))


@router.delete(
    "/rigs/{rig_id}",
    response_model=RigOut,
    dependencies=[Depends(require("rig-well:delete"))],
)
def soft_delete_rig(rig_id: str, request: Request, db: Db, user: Current) -> RigOut:
    rig = _rig_or_404(db, rig_id, user.organization_id, include_deleted=False)
    active_wells = _count_children(db, Well, user.organization_id, rig_id=rig.id, is_deleted=False)
    if active_wells:
        raise HTTPException(
            status_code=409,
            detail=f"Rig {rig.rig_code} has {active_wells} active well(s). Move its wells to Deleted Entries first.",
        )
    rig.is_deleted = True
    rig.deleted_at = _now()
    _record_audit(
        db, user=user, action="soft_delete", entity_type="rig", record_id=rig.id,
        entity_label=rig.rig_code,
        summary=f"Moved rig {rig.rig_code} to Deleted Entries",
        request=request,
    )
    _commit(db)
    db.refresh(rig)
    return _rig_out(rig)


@router.post(
    "/rigs/{rig_id}/restore",
    response_model=RigOut,
    dependencies=[Depends(require("rig-well:restore"))],
)
def restore_rig(rig_id: str, request: Request, db: Db, user: Current) -> RigOut:
    rig = _rig_or_404(db, rig_id, user.organization_id)
    if not rig.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted rig can be restored")
    rig.is_deleted = False
    rig.deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="rig", record_id=rig.id,
        entity_label=rig.rig_code,
        summary=f"Restored rig {rig.rig_code}",
        request=request,
    )
    _commit(db)
    db.refresh(rig)
    return _rig_out(rig)


@router.delete(
    "/rigs/{rig_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("rig-well:permanent-delete"))],
)
def permanently_delete_rig(rig_id: str, request: Request, db: Db, user: Current) -> None:
    rig = _rig_or_404(db, rig_id, user.organization_id)
    if not rig.is_deleted:
        raise HTTPException(status_code=409, detail="Move the rig to Deleted Entries before permanent deletion")
    wells = _count_children(db, Well, user.organization_id, rig_id=rig.id)
    if wells:
        raise HTTPException(
            status_code=409,
            detail=f"Rig {rig.rig_code} still has {wells} well record(s). Permanently delete the wells first.",
        )
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="rig", record_id=rig.id,
        entity_label=rig.rig_code,
        summary=f"Permanently deleted rig {rig.rig_code}",
        request=request,
    )
    db.delete(rig)
    _commit(db)


@router.post(
    "/rigs/bulk-delete",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:delete"))],
)
def bulk_delete_rigs(data: RigWellIDs, request: Request, db: Db, user: Current) -> RigWellBulkActionResponse:
    rigs = _records_for_ids(db, Rig, data.ids, user.organization_id, deleted=False)
    counts = {
        rig_id: int(value)
        for rig_id, value in db.execute(
            select(Well.rig_id, func.count(Well.id))
            .where(
                Well.organization_id == user.organization_id,
                Well.rig_id.in_(data.ids),
                Well.is_deleted.is_(False),
            )
            .group_by(Well.rig_id)
        ).all()
    }
    blocked = [(rig, counts.get(rig.id, 0)) for rig in rigs if counts.get(rig.id, 0)]
    if blocked:
        rig, count = blocked[0]
        raise HTTPException(status_code=409, detail=f"Rig {rig.rig_code} has {count} active well(s); delete its wells first")
    deleted_at = _now()
    for rig in rigs:
        rig.is_deleted = True
        rig.deleted_at = deleted_at
        _record_audit(
            db, user=user, action="soft_delete", entity_type="rig", record_id=rig.id,
            entity_label=rig.rig_code,
            summary=f"Moved rig {rig.rig_code} to Deleted Entries (bulk action)",
            request=request,
        )
    _record_audit(
        db, user=user, action="delete", entity_type="rig", record_id=None,
        entity_label="Rig register",
        summary=f"Moved {len(rigs)} rigs to Deleted Entries",
        request=request,
    )
    _commit(db)
    return RigWellBulkActionResponse(affected_count=len(rigs))


@router.post(
    "/rigs/import",
    response_model=RigWellImportResponse,
    dependencies=[Depends(require("rig-well:import"))],
)
def import_rigs(data: RigWellImportRequest, request: Request, db: Db, user: Current) -> RigWellImportResponse:
    imported = 0
    errors: list[str] = []
    seen_codes: set[str] = set()
    for row_number, row in enumerate(data.rows, start=1):
        code = _string(_row_value(row, "rig_code", "code", "rigcode")).upper()
        name = _string(_row_value(row, "rig_name", "name", "rigname"))
        remarks = _string(_row_value(row, "remarks", "remark"))
        if not code:
            errors.append(f"Row {row_number}: rig_code is required")
            continue
        if not name:
            errors.append(f"Row {row_number} ({code}): rig_name is required")
            continue
        if code in seen_codes:
            errors.append(f"Row {row_number} ({code}): duplicate rig_code in this import")
            continue
        seen_codes.add(code)
        try:
            payload = RigCreate.model_validate({"rig_code": code, "rig_name": name, "remarks": remarks})
        except ValidationError as error:
            errors.append(f"Row {row_number} ({code}): {_validation_message(error)}")
            continue
        existing = db.scalar(
            select(Rig).where(
                Rig.organization_id == user.organization_id,
                Rig.rig_code == payload.rig_code,
            )
        )
        if existing is None:
            existing = Rig(
                organization_id=user.organization_id,
                rig_code=payload.rig_code,
                rig_name=payload.rig_name,
                remarks=payload.remarks,
            )
            db.add(existing)
            action = "create"
            summary = f"Created rig {payload.rig_code} from import"
        else:
            action = "restore" if existing.is_deleted else "update"
            existing.rig_name = payload.rig_name
            existing.remarks = payload.remarks
            existing.is_deleted = False
            existing.deleted_at = None
            summary = f"{'Restored and updated' if action == 'restore' else 'Updated'} rig {payload.rig_code} from import"
        db.flush()
        _record_audit(
            db, user=user, action=action, entity_type="rig", record_id=existing.id,
            entity_label=payload.rig_code, summary=summary, request=request,
        )
        imported += 1
    _record_audit(
        db, user=user, action="import", entity_type="rig", record_id=None,
        entity_label="Rig register",
        summary=f"Imported {imported} rigs with {len(errors)} row error(s)",
        request=request,
    )
    _commit(db)
    return RigWellImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


# ---------------------------------------------------------------------------
# Wells
# ---------------------------------------------------------------------------


@router.get(
    "/wells",
    response_model=list[WellOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_wells(
    db: Db,
    user: Current,
    rig_id: str | None = None,
    status: Literal["active", "completed"] | None = None,
    config_status: Literal["draft", "configured"] | None = None,
    block: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
) -> list[WellOut]:
    statement = (
        select(Well)
        .options(
            joinedload(Well.rig),
            selectinload(Well.sections).selectinload(WellSection.phases),
        )
        .where(Well.organization_id == user.organization_id, Well.is_deleted.is_(False))
    )
    if rig_id:
        _rig_or_404(db, rig_id, user.organization_id, include_deleted=False)
        statement = statement.where(Well.rig_id == rig_id)
    if status:
        statement = statement.where(Well.status == status)
    if config_status:
        statement = statement.where(Well.config_status == config_status)
    if block and block.strip():
        statement = statement.where(Well.block.ilike(block.strip()))
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Well.well_code.ilike(pattern),
                Well.well_name.ilike(pattern),
                Well.well_location.ilike(pattern),
                Well.block.ilike(pattern),
                Well.objective.ilike(pattern),
                Well.remarks.ilike(pattern),
            )
        )
    wells = db.scalars(statement.order_by(Well.well_code)).all()
    count_rows = db.execute(
        select(WellSubActivity.well_id, func.count(WellSubActivity.id))
        .where(
            WellSubActivity.organization_id == user.organization_id,
            WellSubActivity.is_deleted.is_(False),
            WellSubActivity.well_id.in_([well.id for well in wells] or [""]),
        )
        .group_by(WellSubActivity.well_id)
    ).all()
    activity_counts = {well_id: int(value) for well_id, value in count_rows}
    return [_well_out(well, activity_counts.get(well.id, 0)) for well in wells]


@router.post(
    "/wells",
    response_model=WellOut,
    status_code=201,
    dependencies=[Depends(require("rig-well:create"))],
)
def create_well(data: WellCreate, request: Request, db: Db, user: Current) -> WellOut:
    rig = _rig_or_404(db, data.rig_id, user.organization_id, include_deleted=False)
    existing = db.scalar(
        select(Well).where(
            Well.organization_id == user.organization_id,
            Well.well_code == data.well_code,
        )
    )
    if existing is not None:
        if not existing.is_deleted:
            raise HTTPException(status_code=409, detail=_code_conflict_message("Well", data.well_code))
        existing.rig = rig
        existing.well_name = data.well_name
        existing.well_location = data.well_location
        existing.block = data.block
        existing.objective = data.objective
        existing.remarks = data.remarks
        existing.is_deleted = False
        existing.deleted_at = None
        _record_audit(
            db, user=user, action="restore", entity_type="well", record_id=existing.id,
            entity_label=existing.well_code,
            summary=f"Restored and updated well {existing.well_code} on create",
            request=request,
        )
        _commit(db)
        db.refresh(existing)
        return _well_out(existing)
    well = Well(
        organization_id=user.organization_id,
        rig_id=rig.id,
        well_code=data.well_code,
        well_name=data.well_name,
        well_location=data.well_location,
        block=data.block,
        objective=data.objective,
        remarks=data.remarks,
    )
    db.add(well)
    db.flush()
    _record_audit(
        db, user=user, action="create", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Created well {well.well_code} — {well.well_name} under rig {rig.rig_code}",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out(well)


@router.patch(
    "/wells/{well_id}",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def update_well(well_id: str, data: WellUpdate, request: Request, db: Db, user: Current) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field, value in payload.items():
        if value is None:
            continue
        if field == "remarks":
            value = value or ""
        if getattr(well, field) == value:
            continue
        if field == "rig_id":
            well.rig = _rig_or_404(db, value, user.organization_id, include_deleted=False)
            changed.append(field)
            continue
        elif field == "well_code":
            duplicate = db.scalar(
                select(Well).where(
                    Well.organization_id == user.organization_id,
                    Well.well_code == value,
                    Well.id != well.id,
                )
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409,
                    detail=_code_conflict_message("Well", value, deleted=duplicate.is_deleted),
                )
        setattr(well, field, value)
        changed.append(field)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="well", record_id=well.id,
            entity_label=well.well_code,
            summary=f"Updated well {well.well_code}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
        db.refresh(well)
    return _well_out(well)


@router.delete(
    "/wells/{well_id}",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:delete"))],
)
def soft_delete_well(well_id: str, request: Request, db: Db, user: Current) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    active_children = _count_children(
        db, WellSubActivity, user.organization_id, well_id=well.id, is_deleted=False
    )
    if active_children:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Well {well.well_code} has {active_children} active sub activity record(s). "
                "Move those sub activities to Deleted Entries first."
            ),
        )
    well.is_deleted = True
    well.deleted_at = _now()
    _record_audit(
        db, user=user, action="soft_delete", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Moved well {well.well_code} to Deleted Entries",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out(well)


@router.post(
    "/wells/{well_id}/restore",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:restore"))],
)
def restore_well(well_id: str, request: Request, db: Db, user: Current) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id)
    if not well.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted well can be restored")
    _rig_or_404(db, well.rig_id, user.organization_id, include_deleted=False)
    well.is_deleted = False
    well.deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Restored well {well.well_code}",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out(well)


@router.delete(
    "/wells/{well_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("rig-well:permanent-delete"))],
)
def permanently_delete_well(well_id: str, request: Request, db: Db, user: Current) -> None:
    well = _well_or_404(db, well_id, user.organization_id)
    if not well.is_deleted:
        raise HTTPException(status_code=409, detail="Move the well to Deleted Entries before permanent deletion")
    sub_activities = _count_children(db, WellSubActivity, user.organization_id, well_id=well.id)
    if sub_activities:
        raise HTTPException(
            status_code=409,
            detail=f"Well {well.well_code} retains {sub_activities} sub activity record(s). Permanently delete them first.",
        )
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Permanently deleted well {well.well_code}",
        request=request,
    )
    db.delete(well)
    _commit(db)


@router.post(
    "/wells/bulk-delete",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:delete"))],
)
def bulk_delete_wells(data: RigWellIDs, request: Request, db: Db, user: Current) -> RigWellBulkActionResponse:
    wells = _records_for_ids(db, Well, data.ids, user.organization_id, deleted=False)
    counts = {
        well_id: int(value)
        for well_id, value in db.execute(
            select(WellSubActivity.well_id, func.count(WellSubActivity.id))
            .where(
                WellSubActivity.organization_id == user.organization_id,
                WellSubActivity.well_id.in_(data.ids),
                WellSubActivity.is_deleted.is_(False),
            )
            .group_by(WellSubActivity.well_id)
        ).all()
    }
    blocked = [(well, counts.get(well.id, 0)) for well in wells if counts.get(well.id, 0)]
    if blocked:
        well, count = blocked[0]
        raise HTTPException(status_code=409, detail=f"Well {well.well_code} has {count} active sub activity record(s); delete them first")
    deleted_at = _now()
    for well in wells:
        well.is_deleted = True
        well.deleted_at = deleted_at
        _record_audit(
            db, user=user, action="soft_delete", entity_type="well", record_id=well.id,
            entity_label=well.well_code,
            summary=f"Moved well {well.well_code} to Deleted Entries (bulk action)",
            request=request,
        )
    _record_audit(
        db, user=user, action="delete", entity_type="well", record_id=None,
        entity_label="Well register",
        summary=f"Moved {len(wells)} wells to Deleted Entries",
        request=request,
    )
    _commit(db)
    return RigWellBulkActionResponse(affected_count=len(wells))


@router.post(
    "/wells/import",
    response_model=RigWellImportResponse,
    dependencies=[Depends(require("rig-well:import"))],
)
def import_wells(data: RigWellImportRequest, request: Request, db: Db, user: Current) -> RigWellImportResponse:
    imported = 0
    errors: list[str] = []
    seen_codes: set[str] = set()
    for row_number, row in enumerate(data.rows, start=1):
        rig_ref = _string(_row_value(row, "rig_code", "rig", "rig_name"))
        rig = db.scalar(
            select(Rig).where(
                Rig.organization_id == user.organization_id,
                Rig.rig_code == rig_ref.upper(),
                Rig.is_deleted.is_(False),
            )
        ) if rig_ref else None
        if rig is None:
            errors.append(f"Row {row_number}: rig_code '{rig_ref or '—'}' is missing or is not an active rig in this workspace")
            continue
        raw = {
            "rig_id": rig.id,
            "well_code": _row_value(row, "well_code", "code", "wellcode"),
            "well_name": _row_value(row, "well_name", "name", "wellname"),
            "well_location": _row_value(row, "well_location", "location"),
            "block": _row_value(row, "block"),
            "objective": _row_value(row, "objective"),
            "remarks": _row_value(row, "remarks", "remark") or "",
        }
        try:
            payload = WellCreate.model_validate(raw)
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        if payload.well_code in seen_codes:
            errors.append(f"Row {row_number} ({payload.well_code}): duplicate well_code in this import")
            continue
        seen_codes.add(payload.well_code)
        existing = db.scalar(
            select(Well).where(
                Well.organization_id == user.organization_id,
                Well.well_code == payload.well_code,
            )
        )
        if existing is None:
            existing = Well(
                organization_id=user.organization_id,
                rig_id=rig.id,
                well_code=payload.well_code,
                well_name=payload.well_name,
                well_location=payload.well_location,
                block=payload.block,
                objective=payload.objective,
                remarks=payload.remarks,
            )
            db.add(existing)
            action = "create"
            summary = f"Created well {payload.well_code} under rig {rig.rig_code} from import"
        else:
            action = "restore" if existing.is_deleted else "update"
            existing.rig = rig
            existing.well_name = payload.well_name
            existing.well_location = payload.well_location
            existing.block = payload.block
            existing.objective = payload.objective
            existing.remarks = payload.remarks
            existing.is_deleted = False
            existing.deleted_at = None
            summary = f"{'Restored and updated' if action == 'restore' else 'Updated'} well {payload.well_code} from import"
        db.flush()
        _record_audit(
            db, user=user, action=action, entity_type="well", record_id=existing.id,
            entity_label=payload.well_code, summary=summary, request=request,
        )
        imported += 1
    _record_audit(
        db, user=user, action="import", entity_type="well", record_id=None,
        entity_label="Well register",
        summary=f"Imported {imported} wells with {len(errors)} row error(s)",
        request=request,
    )
    _commit(db)
    return RigWellImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


# ---------------------------------------------------------------------------
# Well configuration and lifecycle transitions
# ---------------------------------------------------------------------------


@router.get(
    "/wells/{well_id}/configuration",
    response_model=WellConfigurationOut,
    dependencies=[Depends(require("rig-well:read"))],
)
def get_well_configuration(well_id: str, db: Db, user: Current) -> WellConfigurationOut:
    return _well_configuration_out(_well_or_404(db, well_id, user.organization_id, include_deleted=False))


@router.put(
    "/wells/{well_id}/configuration",
    response_model=WellConfigurationOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def save_well_configuration(
    well_id: str,
    data: WellConfigurationIn,
    request: Request,
    db: Db,
    user: Current,
) -> WellConfigurationOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    if well.status == "completed":
        raise HTTPException(status_code=409, detail="Reactivate the completed well before editing its configuration")
    if well.config_status != "draft":
        raise HTTPException(status_code=409, detail="Reopen the configured well as Draft before editing its configuration")

    seen_sections: set[str] = set()
    previous_to_depth: Decimal | None = None
    resolved: list[tuple[Any, list[Any]]] = []
    for section_index, section_input in enumerate(data.sections, start=1):
        section = _master_record_or_422(
            db, HoleSection, section_input.hole_section_id, user.organization_id, "Hole Section"
        )
        if section.id in seen_sections:
            raise HTTPException(status_code=422, detail=f"Hole Section '{section.section_code}' is duplicated")
        seen_sections.add(section.id)
        if section_input.from_depth > section_input.to_depth:
            raise HTTPException(status_code=422, detail=f"Section {section_index}: from depth must not exceed to depth")
        if previous_to_depth is not None and section_input.from_depth < previous_to_depth:
            raise HTTPException(
                status_code=422,
                detail=f"Section {section_index}: from depth must be at least the previous section's to depth ({previous_to_depth})",
            )
        previous_to_depth = section_input.to_depth
        seen_phases: set[str] = set()
        resolved_phases = []
        for phase_index, phase_input in enumerate(section_input.phases, start=1):
            phase = _master_record_or_422(db, Phase, phase_input.phase_id, user.organization_id, "Phase")
            if phase.id in seen_phases:
                raise HTTPException(
                    status_code=422,
                    detail=f"Section '{section.section_code}': phase '{phase.phase_code}' is duplicated",
                )
            seen_phases.add(phase.id)
            resolved_phases.append((phase, phase_input))
        resolved.append((section, [(phase, payload) for phase, payload in resolved_phases]))

    # Delete old rows through the ORM so the phase cascade is handled in the
    # same transaction. The configuration itself has one explicit audit event.
    for old_section in list(well.sections):
        db.delete(old_section)
    db.flush()
    well.depth_unit = data.depth_unit
    for section_order, (master_section, phase_rows) in enumerate(resolved):
        section_row = WellSection(
            organization_id=user.organization_id,
            well_id=well.id,
            hole_section_id=master_section.id,
            from_depth=data.sections[section_order].from_depth,
            to_depth=data.sections[section_order].to_depth,
            remarks=data.sections[section_order].remarks,
            sort_order=section_order,
        )
        db.add(section_row)
        db.flush()
        for phase_order, (master_phase, phase_input) in enumerate(phase_rows):
            db.add(
                WellPhase(
                    organization_id=user.organization_id,
                    section_id=section_row.id,
                    phase_id=master_phase.id,
                    days=phase_input.days,
                    remarks=phase_input.remarks,
                    sort_order=phase_order,
                )
            )
    _record_audit(
        db, user=user, action="update", entity_type="well_configuration", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Saved draft configuration for well {well.well_code}: {len(data.sections)} section(s)",
        request=request,
    )
    _commit(db)
    db.expire(well, ["sections"])
    return _well_configuration_out(well)


@router.post(
    "/wells/{well_id}/transition",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def transition_well(
    well_id: str,
    data: WellTransitionIn,
    request: Request,
    db: Db,
    user: Current,
) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    action = data.action
    if action == "configure":
        if well.status != "active":
            raise HTTPException(status_code=409, detail="Reactivate the well before marking it configured")
        if well.config_status != "draft":
            raise HTTPException(status_code=409, detail="The well is already configured")
        if not well.sections:
            raise HTTPException(status_code=409, detail="Save at least one section and phase before marking the well configured")
        well.config_status = "configured"
        label = "configured"
    elif action == "draft":
        if well.status != "active":
            raise HTTPException(status_code=409, detail="Reactivate the well before reopening its configuration")
        if well.config_status != "configured":
            raise HTTPException(status_code=409, detail="The well is already in Draft")
        well.config_status = "draft"
        label = "Draft"
    elif action == "complete":
        if well.status != "active":
            raise HTTPException(status_code=409, detail="The well is already completed")
        if well.config_status != "configured" or not well.sections:
            raise HTTPException(status_code=409, detail="Configure the well before marking it completed")
        well.status = "completed"
        label = "completed"
    else:
        if well.status != "completed":
            raise HTTPException(status_code=409, detail="Only a completed well can be reactivated")
        well.status = "active"
        label = "active"
    _record_audit(
        db, user=user, action="update", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Changed well {well.well_code} to {label}: {data.remarks.strip()}",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out(well)


# ---------------------------------------------------------------------------
# Well sub activities
# ---------------------------------------------------------------------------


def _activity_from_import(db: Session, reference: Any, organization_id: str) -> Activity | None:
    text = _string(reference)
    if not text:
        return None
    activity = db.scalar(
        select(Activity).where(
            Activity.organization_id == organization_id,
            Activity.activity_code == text.upper(),
            Activity.is_deleted.is_(False),
        )
    )
    if activity:
        return activity
    matches = list(
        db.scalars(
            select(Activity).where(
                Activity.organization_id == organization_id,
                func.lower(Activity.activity_name) == text.lower(),
                Activity.is_deleted.is_(False),
            )
        ).all()
    )
    if len(matches) == 1:
        return matches[0]
    return None


@router.get(
    "/sub-activities",
    response_model=list[WellSubActivityOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_sub_activities(
    db: Db,
    user: Current,
    well_id: str = Query(min_length=1, max_length=36),
    search: str | None = Query(default=None, max_length=200),
) -> list[WellSubActivityOut]:
    _well_for_sub_activity(db, well_id, user.organization_id)
    statement = (
        select(WellSubActivity)
        .options(joinedload(WellSubActivity.well).joinedload(Well.rig), joinedload(WellSubActivity.activity))
        .where(
            WellSubActivity.organization_id == user.organization_id,
            WellSubActivity.well_id == well_id,
            WellSubActivity.is_deleted.is_(False),
        )
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                WellSubActivity.sub_activity_code.ilike(pattern),
                WellSubActivity.sub_activity_name.ilike(pattern),
                WellSubActivity.responsible_party.ilike(pattern),
                WellSubActivity.description.ilike(pattern),
            )
        )
    records = db.scalars(statement.order_by(WellSubActivity.sub_activity_code)).all()
    return [_sub_activity_out(record) for record in records]


@router.get(
    "/sub-activities/deleted",
    response_model=list[WellSubActivityOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_deleted_sub_activities(
    db: Db,
    user: Current,
    well_id: str | None = Query(default=None, max_length=36),
) -> list[WellSubActivityOut]:
    statement = (
        select(WellSubActivity)
        .options(joinedload(WellSubActivity.well).joinedload(Well.rig), joinedload(WellSubActivity.activity))
        .where(
            WellSubActivity.organization_id == user.organization_id,
            WellSubActivity.is_deleted.is_(True),
        )
    )
    if well_id:
        _well_or_404(db, well_id, user.organization_id)
        statement = statement.where(WellSubActivity.well_id == well_id)
    records = db.scalars(statement.order_by(WellSubActivity.deleted_at.desc())).all()
    return [_sub_activity_out(record) for record in records]


@router.get(
    "/sub-activities/activity-options",
    response_model=list[RigWellMasterDataOption],
    dependencies=[Depends(require("rig-well:read"))],
)
def sub_activity_options(db: Db, user: Current) -> list[RigWellMasterDataOption]:
    activities = db.scalars(
        select(Activity)
        .where(Activity.organization_id == user.organization_id, Activity.is_deleted.is_(False))
        .order_by(Activity.activity_code)
    ).all()
    return [RigWellMasterDataOption(id=item.id, code=item.activity_code, name=item.activity_name) for item in activities]


@router.post(
    "/sub-activities",
    response_model=WellSubActivityOut,
    status_code=201,
    dependencies=[Depends(require("rig-well:create"))],
)
def create_sub_activity(
    data: WellSubActivityCreate,
    request: Request,
    db: Db,
    user: Current,
) -> WellSubActivityOut:
    well = _well_for_sub_activity(db, data.well_id, user.organization_id)
    activity = _master_record_or_422(db, Activity, data.activity_id, user.organization_id, "Activity")
    existing = db.scalar(
        select(WellSubActivity).where(
            WellSubActivity.organization_id == user.organization_id,
            WellSubActivity.well_id == well.id,
            WellSubActivity.sub_activity_code == data.sub_activity_code,
        )
    )
    if existing is not None:
        if not existing.is_deleted:
            raise HTTPException(
                status_code=409,
                detail=f"Sub activity code '{data.sub_activity_code}' already exists for well {well.well_code}",
            )
        existing.sub_activity_name = data.sub_activity_name
        existing.activity_id = activity.id
        existing.responsible_party = data.responsible_party
        existing.description = data.description
        existing.is_deleted = False
        existing.deleted_at = None
        _record_audit(
            db, user=user, action="restore", entity_type="well_sub_activity", record_id=existing.id,
            entity_label=f"{well.well_code} / {existing.sub_activity_code}",
            summary=f"Restored and updated sub activity {existing.sub_activity_code} for well {well.well_code} on create",
            request=request,
        )
        _commit(db)
        return _sub_activity_out(_sub_activity_or_404(db, existing.id, user.organization_id))
    record = WellSubActivity(
        organization_id=user.organization_id,
        well_id=well.id,
        sub_activity_code=data.sub_activity_code,
        sub_activity_name=data.sub_activity_name,
        activity_id=activity.id,
        responsible_party=data.responsible_party,
        description=data.description,
    )
    db.add(record)
    db.flush()
    _record_audit(
        db, user=user, action="create", entity_type="well_sub_activity", record_id=record.id,
        entity_label=f"{well.well_code} / {record.sub_activity_code}",
        summary=f"Created sub activity {record.sub_activity_code} — {record.sub_activity_name} under Activity {activity.activity_code} for well {well.well_code}",
        request=request,
    )
    _commit(db)
    return _sub_activity_out(_sub_activity_or_404(db, record.id, user.organization_id))


@router.patch(
    "/sub-activities/{record_id}",
    response_model=WellSubActivityOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def update_sub_activity(
    record_id: str,
    data: WellSubActivityUpdate,
    request: Request,
    db: Db,
    user: Current,
    well_id: str = Query(min_length=1, max_length=36),
) -> WellSubActivityOut:
    well = _well_for_sub_activity(db, well_id, user.organization_id)
    record = _sub_activity_or_404(
        db, record_id, user.organization_id, well_id=well.id, include_deleted=False
    )
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field, value in payload.items():
        if value is None or getattr(record, field) == value:
            continue
        if field == "activity_id":
            _master_record_or_422(db, Activity, value, user.organization_id, "Activity")
        elif field == "sub_activity_code":
            duplicate = db.scalar(
                select(WellSubActivity).where(
                    WellSubActivity.organization_id == user.organization_id,
                    WellSubActivity.well_id == well.id,
                    WellSubActivity.sub_activity_code == value,
                    WellSubActivity.id != record.id,
                )
            )
            if duplicate:
                raise HTTPException(
                    status_code=409,
                    detail=f"Sub activity code '{value}' is already retained for well {well.well_code}; restore or permanently delete it first",
                )
        setattr(record, field, value)
        changed.append(field)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="well_sub_activity", record_id=record.id,
            entity_label=f"{well.well_code} / {record.sub_activity_code}",
            summary=f"Updated sub activity {record.sub_activity_code} for well {well.well_code}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
    return _sub_activity_out(_sub_activity_or_404(db, record.id, user.organization_id))


@router.delete(
    "/sub-activities/{record_id}",
    response_model=WellSubActivityOut,
    dependencies=[Depends(require("rig-well:delete"))],
)
def soft_delete_sub_activity(
    record_id: str,
    request: Request,
    db: Db,
    user: Current,
    well_id: str = Query(min_length=1, max_length=36),
) -> WellSubActivityOut:
    well = _well_for_sub_activity(db, well_id, user.organization_id)
    record = _sub_activity_or_404(
        db, record_id, user.organization_id, well_id=well.id, include_deleted=False
    )
    record.is_deleted = True
    record.deleted_at = _now()
    _record_audit(
        db, user=user, action="soft_delete", entity_type="well_sub_activity", record_id=record.id,
        entity_label=f"{well.well_code} / {record.sub_activity_code}",
        summary=f"Moved sub activity {record.sub_activity_code} for well {well.well_code} to Deleted Entries",
        request=request,
    )
    _commit(db)
    return _sub_activity_out(_sub_activity_or_404(db, record.id, user.organization_id))


@router.post(
    "/sub-activities/{record_id}/restore",
    response_model=WellSubActivityOut,
    dependencies=[Depends(require("rig-well:restore"))],
)
def restore_sub_activity(record_id: str, request: Request, db: Db, user: Current) -> WellSubActivityOut:
    record = _sub_activity_or_404(db, record_id, user.organization_id)
    if not record.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted sub activity can be restored")
    well = _well_for_sub_activity(db, record.well_id, user.organization_id)
    _master_record_or_422(db, Activity, record.activity_id, user.organization_id, "Activity")
    record.is_deleted = False
    record.deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="well_sub_activity", record_id=record.id,
        entity_label=f"{well.well_code} / {record.sub_activity_code}",
        summary=f"Restored sub activity {record.sub_activity_code} for well {well.well_code}",
        request=request,
    )
    _commit(db)
    return _sub_activity_out(_sub_activity_or_404(db, record.id, user.organization_id))


@router.delete(
    "/sub-activities/{record_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("rig-well:permanent-delete"))],
)
def permanently_delete_sub_activity(record_id: str, request: Request, db: Db, user: Current) -> None:
    record = _sub_activity_or_404(db, record_id, user.organization_id)
    if not record.is_deleted:
        raise HTTPException(status_code=409, detail="Move the sub activity to Deleted Entries before permanent deletion")
    label = f"{record.well.well_code} / {record.sub_activity_code}"
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="well_sub_activity", record_id=record.id,
        entity_label=label,
        summary=f"Permanently deleted sub activity {record.sub_activity_code} for well {record.well.well_code}",
        request=request,
    )
    db.delete(record)
    _commit(db)


@router.post(
    "/sub-activities/bulk-delete",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:delete"))],
)
def bulk_delete_sub_activities(
    data: RigWellIDs,
    request: Request,
    db: Db,
    user: Current,
    well_id: str = Query(min_length=1, max_length=36),
) -> RigWellBulkActionResponse:
    well = _well_for_sub_activity(db, well_id, user.organization_id)
    records = list(
        db.scalars(
            select(WellSubActivity).where(
                WellSubActivity.organization_id == user.organization_id,
                WellSubActivity.well_id == well.id,
                WellSubActivity.id.in_(data.ids),
                WellSubActivity.is_deleted.is_(False),
            )
        ).all()
    )
    if len(data.ids) != len(set(data.ids)):
        raise HTTPException(status_code=422, detail="Duplicate record IDs are not allowed")
    if len(records) != len(data.ids):
        raise HTTPException(status_code=404, detail="One or more sub activities do not belong to the selected well")
    deleted_at = _now()
    for record in records:
        record.is_deleted = True
        record.deleted_at = deleted_at
        _record_audit(
            db, user=user, action="soft_delete", entity_type="well_sub_activity", record_id=record.id,
            entity_label=f"{well.well_code} / {record.sub_activity_code}",
            summary=f"Moved sub activity {record.sub_activity_code} for well {well.well_code} to Deleted Entries (bulk action)",
            request=request,
        )
    _record_audit(
        db, user=user, action="delete", entity_type="well_sub_activity", record_id=None,
        entity_label=f"Well {well.well_code}",
        summary=f"Moved {len(records)} well sub activities for {well.well_code} to Deleted Entries",
        request=request,
    )
    _commit(db)
    return RigWellBulkActionResponse(affected_count=len(records))


@router.post(
    "/sub-activities/import",
    response_model=RigWellImportResponse,
    dependencies=[Depends(require("rig-well:import"))],
)
def import_sub_activities(
    data: RigWellImportRequest,
    request: Request,
    db: Db,
    user: Current,
    well_id: str = Query(min_length=1, max_length=36),
) -> RigWellImportResponse:
    well = _well_for_sub_activity(db, well_id, user.organization_id)
    imported = 0
    errors: list[str] = []
    seen_codes: set[str] = set()
    for row_number, row in enumerate(data.rows, start=1):
        code = _string(_row_value(row, "sub_activity_code", "code", "sub_activity")).upper()
        name = _string(_row_value(row, "sub_activity_name", "name"))
        responsible_party = _string(_row_value(row, "responsible_party", "responsible", "company"))
        description = _string(_row_value(row, "description", "remarks", "remark"))
        activity_ref = _row_value(row, "activity", "activity_code", "activity_name")
        try:
            payload = WellSubActivityCreate.model_validate(
                {
                    "well_id": well.id,
                    "sub_activity_code": code,
                    "sub_activity_name": name,
                    "activity_id": "pending",
                    "responsible_party": responsible_party,
                    "description": description,
                }
            )
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        if payload.sub_activity_code in seen_codes:
            errors.append(f"Row {row_number} ({payload.sub_activity_code}): duplicate sub_activity_code in this import")
            continue
        seen_codes.add(payload.sub_activity_code)
        activity = _activity_from_import(db, activity_ref, user.organization_id)
        if activity is None:
            errors.append(f"Row {row_number} ({payload.sub_activity_code}): Activity '{_string(activity_ref) or '—'}' is missing, ambiguous, or inactive in Master Data")
            continue
        existing = db.scalar(
            select(WellSubActivity).where(
                WellSubActivity.organization_id == user.organization_id,
                WellSubActivity.well_id == well.id,
                WellSubActivity.sub_activity_code == payload.sub_activity_code,
            )
        )
        if existing is None:
            existing = WellSubActivity(
                organization_id=user.organization_id,
                well_id=well.id,
                sub_activity_code=payload.sub_activity_code,
                sub_activity_name=payload.sub_activity_name,
                activity_id=activity.id,
                responsible_party=payload.responsible_party,
                description=payload.description,
            )
            db.add(existing)
            action = "create"
            summary = f"Created sub activity {payload.sub_activity_code} for well {well.well_code} from import"
        else:
            action = "restore" if existing.is_deleted else "update"
            existing.sub_activity_name = payload.sub_activity_name
            existing.activity_id = activity.id
            existing.responsible_party = payload.responsible_party
            existing.description = payload.description
            existing.is_deleted = False
            existing.deleted_at = None
            summary = f"{'Restored and updated' if action == 'restore' else 'Updated'} sub activity {payload.sub_activity_code} for well {well.well_code} from import"
        db.flush()
        _record_audit(
            db, user=user, action=action, entity_type="well_sub_activity", record_id=existing.id,
            entity_label=f"{well.well_code} / {payload.sub_activity_code}",
            summary=summary, request=request,
        )
        imported += 1
    _record_audit(
        db, user=user, action="import", entity_type="well_sub_activity", record_id=None,
        entity_label=f"Well {well.well_code}",
        summary=f"Imported {imported} sub activities for well {well.well_code} with {len(errors)} row error(s)",
        request=request,
    )
    _commit(db)
    return RigWellImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


# ---------------------------------------------------------------------------
# Deleted Entries: mixed entity listing and atomic bulk recovery/purge
# ---------------------------------------------------------------------------


@router.get(
    "/deleted",
    response_model=list[DeletedRigWellRecord],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_deleted_entries(db: Db, user: Current) -> list[DeletedRigWellRecord]:
    organization_id = user.organization_id
    output: list[DeletedRigWellRecord] = []
    rigs = db.scalars(
        select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(True))
    ).all()
    for rig in rigs:
        output.append(
            DeletedRigWellRecord(
                id=rig.id,
                entity_type="rig",
                code=rig.rig_code,
                name=rig.rig_name,
                parent_label="Rig register",
                deleted_at=rig.deleted_at or rig.updated_at,
                created_at=rig.created_at,
            )
        )
    wells = db.scalars(
        select(Well)
        .options(joinedload(Well.rig))
        .where(Well.organization_id == organization_id, Well.is_deleted.is_(True))
    ).all()
    for well in wells:
        output.append(
            DeletedRigWellRecord(
                id=well.id,
                entity_type="well",
                code=well.well_code,
                name=well.well_name,
                parent_label=(f"{well.rig.rig_code} — {well.rig.rig_name}" if well.rig else "Unknown rig"),
                deleted_at=well.deleted_at or well.updated_at,
                created_at=well.created_at,
            )
        )
    sub_activities = db.scalars(
        select(WellSubActivity)
        .options(joinedload(WellSubActivity.well).joinedload(Well.rig))
        .where(
            WellSubActivity.organization_id == organization_id,
            WellSubActivity.is_deleted.is_(True),
        )
    ).all()
    for item in sub_activities:
        well = item.well
        parent = f"{well.well_code} — {well.well_name}" if well else "Unknown well"
        if well and well.rig:
            parent = f"{well.rig.rig_code} / {parent}"
        output.append(
            DeletedRigWellRecord(
                id=item.id,
                entity_type="well_sub_activity",
                code=item.sub_activity_code,
                name=item.sub_activity_name,
                parent_label=parent,
                deleted_at=item.deleted_at or item.updated_at,
                created_at=item.created_at,
            )
        )
    output.sort(key=lambda record: record.deleted_at, reverse=True)
    return output


def _selected_deleted_records(
    db: Session,
    selections: list[Any],
    organization_id: str,
) -> dict[str, list[Any]]:
    pairs = [(item.entity_type, item.id) for item in selections]
    if len(pairs) != len(set(pairs)):
        raise HTTPException(status_code=422, detail="Duplicate entity and record selections are not allowed")
    grouped: dict[str, list[str]] = defaultdict(list)
    for entity_type, record_id in pairs:
        grouped[entity_type].append(record_id)
    result: dict[str, list[Any]] = {}
    for entity_type, ids in grouped.items():
        model = ENTITY_MODELS[entity_type]
        records = list(
            db.scalars(
                select(model).where(
                    model.organization_id == organization_id,
                    model.id.in_(ids),
                )
            ).all()
        )
        if len(records) != len(ids):
            raise HTTPException(status_code=404, detail="One or more selected records do not belong to this workspace")
        if any(not record.is_deleted for record in records):
            raise HTTPException(status_code=409, detail="Only records already in Deleted Entries can be changed here")
        result[entity_type] = records
    return result


def _selected_ids(records: dict[str, list[Any]], entity_type: str) -> set[str]:
    return {record.id for record in records.get(entity_type, [])}


@router.post(
    "/deleted/bulk-restore",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:restore"))],
)
def bulk_restore_deleted(
    data: DeletedSelection,
    request: Request,
    db: Db,
    user: Current,
) -> RigWellBulkActionResponse:
    records = _selected_deleted_records(db, data.records, user.organization_id)
    selected_rigs = _selected_ids(records, "rig")
    selected_wells = _selected_ids(records, "well")

    for well in records.get("well", []):
        rig = _rig_or_404(db, well.rig_id, user.organization_id)
        if rig.is_deleted and rig.id not in selected_rigs:
            raise HTTPException(status_code=409, detail=f"Restore rig {rig.rig_code} before restoring well {well.well_code}")
    for item in records.get("well_sub_activity", []):
        well = _well_or_404(db, item.well_id, user.organization_id)
        if well.is_deleted and well.id not in selected_wells:
            raise HTTPException(status_code=409, detail=f"Restore well {well.well_code} before restoring sub activity {item.sub_activity_code}")
        if well.rig.is_deleted and well.rig.id not in selected_rigs:
            raise HTTPException(status_code=409, detail=f"Restore rig {well.rig.rig_code} before restoring sub activity {item.sub_activity_code}")
        _master_record_or_422(db, Activity, item.activity_id, user.organization_id, "Activity")

    restored_count = 0
    for entity_type in ("rig", "well", "well_sub_activity"):
        for record in records.get(entity_type, []):
            record.is_deleted = False
            record.deleted_at = None
            if entity_type == "rig":
                label = record.rig_code
                summary = f"Restored rig {record.rig_code} (bulk action)"
            elif entity_type == "well":
                label = record.well_code
                summary = f"Restored well {record.well_code} (bulk action)"
            else:
                label = f"{record.well.well_code} / {record.sub_activity_code}"
                summary = f"Restored sub activity {record.sub_activity_code} for well {record.well.well_code} (bulk action)"
            _record_audit(
                db, user=user, action="restore", entity_type=entity_type, record_id=record.id,
                entity_label=label, summary=summary, request=request,
            )
            restored_count += 1
    _record_audit(
        db, user=user, action="restore", entity_type="rig_well_deleted", record_id=None,
        entity_label="Deleted Entries",
        summary=f"Restored {restored_count} Rig & Well Management record(s)",
        request=request,
    )
    _commit(db)
    return RigWellBulkActionResponse(affected_count=restored_count)


@router.post(
    "/deleted/bulk-permanent-delete",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:permanent-delete"))],
)
def bulk_permanently_delete(
    data: DeletedSelection,
    request: Request,
    db: Db,
    user: Current,
) -> RigWellBulkActionResponse:
    records = _selected_deleted_records(db, data.records, user.organization_id)
    selected_rigs = _selected_ids(records, "rig")
    selected_wells = _selected_ids(records, "well")
    selected_sub_activities = _selected_ids(records, "well_sub_activity")

    for rig in records.get("rig", []):
        remaining_wells = list(
            db.scalars(
                select(Well.id).where(
                    Well.organization_id == user.organization_id,
                    Well.rig_id == rig.id,
                )
            ).all()
        )
        if any(well_id not in selected_wells for well_id in remaining_wells):
            raise HTTPException(status_code=409, detail=f"Permanently delete every well under rig {rig.rig_code} first")
    for well in records.get("well", []):
        remaining_sub_activities = list(
            db.scalars(
                select(WellSubActivity.id).where(
                    WellSubActivity.organization_id == user.organization_id,
                    WellSubActivity.well_id == well.id,
                )
            ).all()
        )
        if any(item_id not in selected_sub_activities for item_id in remaining_sub_activities):
            raise HTTPException(status_code=409, detail=f"Permanently delete every sub activity under well {well.well_code} first")

    purged_count = 0
    # Child rows are flushed before their parents to respect RESTRICT constraints.
    for record in records.get("well_sub_activity", []):
        _record_audit(
            db, user=user, action="permanent_delete", entity_type="well_sub_activity", record_id=record.id,
            entity_label=f"{record.well.well_code} / {record.sub_activity_code}",
            summary=f"Permanently deleted sub activity {record.sub_activity_code} for well {record.well.well_code} (bulk action)",
            request=request,
        )
        db.delete(record)
        purged_count += 1
    db.flush()
    for record in records.get("well", []):
        _record_audit(
            db, user=user, action="permanent_delete", entity_type="well", record_id=record.id,
            entity_label=record.well_code,
            summary=f"Permanently deleted well {record.well_code} (bulk action)",
            request=request,
        )
        db.delete(record)
        purged_count += 1
    db.flush()
    for record in records.get("rig", []):
        _record_audit(
            db, user=user, action="permanent_delete", entity_type="rig", record_id=record.id,
            entity_label=record.rig_code,
            summary=f"Permanently deleted rig {record.rig_code} (bulk action)",
            request=request,
        )
        db.delete(record)
        purged_count += 1
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="rig_well_deleted", record_id=None,
        entity_label="Deleted Entries",
        summary=f"Permanently deleted {purged_count} Rig & Well Management record(s)",
        request=request,
    )
    _commit(db)
    return RigWellBulkActionResponse(affected_count=purged_count)


@router.post(
    "/export-audit",
    status_code=204,
    dependencies=[Depends(require("rig-well:export"))],
)
def audit_export(data: RigWellExportAudit, request: Request, db: Db, user: Current) -> Response:
    labels = {
        "rigs": "Rigs",
        "wells": "Wells",
        "well-sub-activities": "Well Sub Activities",
        "deleted": "Deleted Rig & Well Entries",
    }
    _record_audit(
        db, user=user, action="export", entity_type="rig_well_export", record_id=None,
        entity_label=labels[data.module],
        summary=f"Exported {data.record_count} {labels[data.module]} record(s) as {data.format.upper()}"
                f"{' including deleted entries' if data.include_deleted else ''}",
        request=request,
    )
    _commit(db)
    return Response(status_code=204)
