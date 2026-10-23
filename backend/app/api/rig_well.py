"""Tenant-scoped Rig & Well Management APIs.

Blocks group wells by concession / field area and rigs own wells. Well
configuration uses the workspace's Hole Sections and Phases master data, while
well sub activities are tied to one well and one workspace Activity. All
business rows are soft-deleted first, exports/imports and lifecycle changes
are audited, and every lookup is organization-scoped.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.deps import Current, Db, granted, owner, require
from app.core.units import depth_to_meters
from app.models import (
    Activity,
    Afe,
    AuditLog,
    Block,
    DailyCostConsumableLine,
    DailyCostEntry,
    DailyCostOtherExpenseLine,
    DailyCostServiceLine,
    DailyCostTangibleLine,
    HoleSection,
    LihCostEntry,
    MudCostEntry,
    MudCostSectionSetting,
    Phase,
    Rig,
    Well,
    WellPhase,
    WellPlanAdjustment,
    WellSection,
    WellSubActivity,
)
from app.services.daily_cost import classify_activity
from app.services.retention import (
    AFE_LABEL,
    DAILY_SHEET_LABEL,
    MUD_COST_LABEL,
    SUB_ACTIVITY_LABEL,
    WELL_LABEL,
    assert_purgeable,
    purge_owned_snapshots,
    snapshot_summary,
)
from app.schemas.rig_well import (
    BlockCreate,
    BlockDropdownOut,
    BlockOut,
    BlockUpdate,
    DeletedRigWellRecord,
    DeletedSelection,
    RigCreate,
    RigDropdownOut,
    RigUpdate,
    RigOut,
    RigWellActivityCount,
    RigWellBlockCount,
    RigWellBulkActionResponse,
    RigWellExportAudit,
    RigWellIDs,
    RigWellImportRequest,
    RigWellImportResponse,
    RigWellOverview,
    RigWellConfigurationOptions,
    RigWellMasterDataOption,
    RigWellRecentActivity,
    WellBulkDeleteRequest,
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
RECENT_AUDIT_TYPES = ("block", "rig", "well", "well_configuration", "well_sub_activity")
ENTITY_MODELS: dict[str, Any] = {
    "block": Block,
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


def _block_or_404(
    db: Session,
    block_id: str,
    organization_id: str,
    *,
    include_deleted: bool = True,
) -> Block:
    statement = select(Block).where(
        Block.id == block_id,
        Block.organization_id == organization_id,
    )
    if not include_deleted:
        statement = statement.where(Block.is_deleted.is_(False))
    block = db.scalar(statement)
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found in this workspace")
    return block


def _block_well_counts(db: Session, organization_id: str) -> dict[str, int]:
    """Active wells per block, used by the register, dropdown and overview."""
    rows = db.execute(
        select(Well.block_id, func.count(Well.id))
        .where(
            Well.organization_id == organization_id,
            Well.is_deleted.is_(False),
            Well.status == "active",
        )
        .group_by(Well.block_id)
    ).all()
    return {block_id: int(value) for block_id, value in rows}


def _block_out(block: Block, well_count: int = 0) -> BlockOut:
    return BlockOut(
        id=block.id,
        block_code=block.block_code,
        block_name=block.block_name,
        description=block.description or "",
        well_count=well_count,
        is_deleted=block.is_deleted,
        deleted_at=block.deleted_at,
        created_at=block.created_at,
        updated_at=block.updated_at,
    )


def _scope_label(scope: str) -> str:
    return "Completion" if scope == "completion" else "Drilling"


def _other_scope(scope: str) -> str:
    return "drilling" if scope == "completion" else "completion"


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
            selectinload(Well.completion_sections).selectinload(WellSection.phases),
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
    scope: str | None = None,
    include_deleted: bool = False,
) -> Well:
    well = _well_or_404(db, well_id, organization_id, include_deleted=include_deleted)
    if well.rig is None or well.rig.organization_id != organization_id or well.rig.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the well's rig before using this well")
    if scope is not None and not include_deleted and well.scope_is_deleted(scope):
        raise HTTPException(
            status_code=409,
            detail=f"Restore or add the {_scope_label(scope)} scope on well {well.well_code} before using it",
        )
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


def _well_totals(sections: Any) -> tuple[Decimal | None, Decimal]:
    total_depth: Decimal | None = None
    total_days = Decimal("0")
    for section in sections:
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


def _effective_plan_map(db: Session, organization_id: str, well_ids: list[str]) -> dict[str, Any]:
    """Latest approved drilling-scope plan adjustment per well, keyed by well id."""
    if not well_ids:
        return {}
    try:
        from app.models.sow_adjustment import WellPlanAdjustment

        rows = list(
            db.scalars(
                select(WellPlanAdjustment)
                .where(
                    WellPlanAdjustment.organization_id == organization_id,
                    WellPlanAdjustment.well_id.in_(well_ids),
                    WellPlanAdjustment.configuration_scope == "drilling",
                    WellPlanAdjustment.status == "approved",
                )
                .order_by(WellPlanAdjustment.well_id, WellPlanAdjustment.revision_number.desc())
            ).all()
        )
    except Exception:  # noqa: BLE001 - unmigrated database has no adjustment tables yet
        return {}
    effective: dict[str, Any] = {}
    for row in rows:
        effective.setdefault(row.well_id, row)
    return effective


def _scoped_sub_activity_counts(
    db: Session,
    organization_id: str,
    well_ids: list[str],
) -> dict[tuple[str, str], int]:
    if not well_ids:
        return {}
    rows = db.execute(
        select(WellSubActivity.well_id, WellSubActivity.scope, func.count(WellSubActivity.id))
        .where(
            WellSubActivity.organization_id == organization_id,
            WellSubActivity.is_deleted.is_(False),
            WellSubActivity.well_id.in_(well_ids),
        )
        .group_by(WellSubActivity.well_id, WellSubActivity.scope)
    ).all()
    return {(str(well_id), str(scope)): int(value) for well_id, scope, value in rows}


def _well_out_for(db: Session, organization_id: str, well: Well) -> WellOut:
    """Single-well output enriched with scoped sub-activity counts and effective plan adjustment."""
    scoped_counts = _scoped_sub_activity_counts(db, organization_id, [well.id])
    drilling_count = scoped_counts.get((well.id, "drilling"), 0)
    completion_count = scoped_counts.get((well.id, "completion"), 0)
    plan_map = _effective_plan_map(db, organization_id, [well.id])
    return _well_out(
        well,
        drilling_count + completion_count,
        drilling_sub_activity_count=drilling_count,
        completion_sub_activity_count=completion_count,
        plan_adjustment=plan_map.get(well.id),
    )


def _section_totals(sections: Any) -> tuple[Decimal | None, Decimal]:
    return _well_totals(list(sections))


def _well_out(
    well: Well,
    sub_activity_count: int = 0,
    *,
    drilling_sub_activity_count: int = 0,
    completion_sub_activity_count: int = 0,
    plan_adjustment: Any | None = None,
) -> WellOut:
    drilling_depth, drilling_days = _well_totals(well.sections)
    completion_depth, completion_days = _section_totals(well.completion_sections)
    rig = well.rig
    return WellOut(
        completion_status=well.completion_status,
        completion_config_status=well.completion_config_status,
        completion_section_count=len(well.completion_sections),
        id=well.id,
        rig_id=well.rig_id,
        rig_code=rig.rig_code if rig else "",
        rig_name=rig.rig_name if rig else "",
        rig_display=(f"{rig.rig_code} — {rig.rig_name}" if rig else ""),
        well_code=well.well_code,
        well_name=well.well_name,
        well_location=well.well_location,
        block_id=well.block_id,
        block_code=well.block_record.block_code if well.block_record else "",
        block_name=well.block_record.block_name if well.block_record else "",
        block=well.block,
        objective=well.objective,
        remarks=well.remarks or "",
        status=well.status,
        config_status=well.config_status,
        depth_unit=well.depth_unit,
        standard_depth_unit="m",
        total_depth=drilling_depth,
        total_depth_m=depth_to_meters(drilling_depth, well.depth_unit),
        total_days=drilling_days,
        completion_depth_unit=well.completion_depth_unit,
        completion_total_depth=completion_depth,
        completion_total_depth_m=depth_to_meters(completion_depth, well.completion_depth_unit),
        completion_total_days=completion_days,
        section_count=len(well.sections),
        sub_activity_count=sub_activity_count,
        drilling_sub_activity_count=drilling_sub_activity_count,
        completion_sub_activity_count=completion_sub_activity_count,
        drilling_is_deleted=well.drilling_is_deleted,
        drilling_deleted_at=well.drilling_deleted_at,
        drilling_purged=well.drilling_purged,
        completion_is_deleted=well.completion_is_deleted,
        completion_deleted_at=well.completion_deleted_at,
        completion_purged=well.completion_purged,
        is_deleted=well.is_deleted,
        deleted_at=well.deleted_at,
        created_at=well.created_at,
        updated_at=well.updated_at,
        adjusted_total_days=Decimal(plan_adjustment.planned_days_after) if plan_adjustment else None,
        has_plan_adjustment=plan_adjustment is not None,
        plan_revision=plan_adjustment.revision_number if plan_adjustment else None,
    )


def _well_configuration_out(well: Well, scope: str = "drilling") -> WellConfigurationOut:
    scoped_sections = well.sections_for_scope(scope)
    scope_unit = well.scope_value(scope, "depth_unit")
    total_depth = scoped_sections[-1].to_depth if scoped_sections else None
    total_days = sum((phase.days for section in scoped_sections for phase in section.phases), Decimal("0"))
    sections = []
    for section in scoped_sections:
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
                "from_depth_m": depth_to_meters(section.from_depth, scope_unit),
                "to_depth_m": depth_to_meters(section.to_depth, scope_unit),
                "remarks": section.remarks or "",
                "total_days": section_days,
                "phases": phases,
            }
        )
    return WellConfigurationOut(
        scope=scope,
        well_id=well.id,
        well_code=well.well_code,
        well_name=well.well_name,
        rig_code=well.rig.rig_code if well.rig else "",
        rig_name=well.rig.rig_name if well.rig else "",
        status=well.scope_value(scope, "status"),
        config_status=well.scope_value(scope, "config_status"),
        depth_unit=scope_unit,
        standard_depth_unit="m",
        total_depth=total_depth,
        total_depth_m=depth_to_meters(total_depth, scope_unit),
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
        scope=record.scope if record.scope in ("drilling", "completion") else "drilling",
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


def _counts_by_parent(
    db: Session,
    model: Any,
    parent_column: Any,
    organization_id: str,
    parent_ids: list[str],
    *,
    active_only: bool = False,
) -> dict[str, int]:
    if not parent_ids:
        return {}
    statement = select(parent_column, func.count(model.id)).where(
        model.organization_id == organization_id,
        parent_column.in_(parent_ids),
    )
    if active_only and hasattr(model, "is_deleted"):
        statement = statement.where(model.is_deleted.is_(False))
    return {str(parent_id): int(count) for parent_id, count in db.execute(statement.group_by(parent_column)).all()}


def _daily_cost_line_counts_by_sub_activity(
    db: Session,
    organization_id: str,
    sub_activity_ids: list[str],
    *,
    active_entries_only: bool,
) -> dict[str, int]:
    if not sub_activity_ids:
        return {}
    counts: dict[str, int] = defaultdict(int)
    line_models = (
        DailyCostServiceLine,
        DailyCostConsumableLine,
        DailyCostTangibleLine,
        DailyCostOtherExpenseLine,
    )
    for model in line_models:
        statement = select(model.sub_activity_id, func.count(model.id)).where(
            model.organization_id == organization_id,
            model.sub_activity_id.in_(sub_activity_ids),
        )
        if active_entries_only:
            statement = statement.join(DailyCostEntry, model.entry_id == DailyCostEntry.id).where(
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.is_deleted.is_(False),
            )
        for sub_activity_id, count in db.execute(statement.group_by(model.sub_activity_id)).all():
            counts[str(sub_activity_id)] += int(count)
    return dict(counts)


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
    whole_deleted_wells = count(
        Well,
        deleted=True,
        extra=(Well.drilling_is_deleted.is_(False), Well.completion_is_deleted.is_(False)),
    )
    deleted_drilling_scopes = count(
        Well,
        extra=(Well.drilling_is_deleted.is_(True), Well.drilling_purged.is_(False)),
    )
    deleted_completion_scopes = count(
        Well,
        extra=(Well.completion_is_deleted.is_(True), Well.completion_purged.is_(False)),
    )
    deleted_wells = whole_deleted_wells + deleted_drilling_scopes + deleted_completion_scopes
    active_sub_activities = count(WellSubActivity, deleted=False)
    deleted_sub_activities = count(WellSubActivity, deleted=True)
    configured_wells = count(
        Well, deleted=False, extra=(Well.config_status == "configured", Well.status == "active")
    )
    draft_wells = count(Well, deleted=False, extra=(Well.config_status == "draft", Well.status == "active"))
    final_review_wells = count(
        Well,
        deleted=False,
        extra=(
            Well.status == "active",
            or_(
                and_(Well.drilling_is_deleted.is_(False), Well.config_status == "final_review"),
                and_(Well.completion_is_deleted.is_(False), Well.completion_config_status == "final_review"),
            ),
        ),
    )
    completed_wells = count(Well, deleted=False, extra=(Well.status == "completed",))
    active_blocks = count(Block, deleted=False)
    deleted_blocks = count(Block, deleted=True)
    block_well_counts = _block_well_counts(db, org_id)
    block_rows = db.scalars(
        select(Block)
        .where(Block.organization_id == org_id, Block.is_deleted.is_(False))
        .order_by(Block.block_code)
    ).all()
    block_counts = [
        RigWellBlockCount(
            block_id=block.id,
            block_code=block.block_code,
            block_name=block.block_name,
            well_count=block_well_counts.get(block.id, 0),
        )
        for block in block_rows
    ]

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
        active_blocks=active_blocks,
        deleted_blocks=deleted_blocks,
        block_counts=block_counts,
        active_rigs=active_rigs,
        deleted_rigs=deleted_rigs,
        active_wells=active_wells,
        deleted_wells=deleted_wells,
        active_sub_activities=active_sub_activities,
        deleted_sub_activities=deleted_sub_activities,
        configured_wells=configured_wells,
        draft_wells=draft_wells,
        final_review_wells=final_review_wells,
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
    active_afes = _count_children(db, Afe, user.organization_id, rig_id=rig.id, is_deleted=False)
    active_daily_sheets = _count_children(db, DailyCostEntry, user.organization_id, rig_id=rig.id, is_deleted=False)
    active_mud_entries = _count_children(db, MudCostEntry, user.organization_id, rig_id=rig.id, is_deleted=False)
    dependencies = []
    if active_wells:
        dependencies.append(f"{active_wells} active well(s)")
    if active_afes:
        dependencies.append(f"{active_afes} active AFE(s)")
    if active_daily_sheets:
        dependencies.append(f"{active_daily_sheets} active daily-cost sheet(s)")
    if active_mud_entries:
        dependencies.append(f"{active_mud_entries} active Mud Cost entry/entries")
    if dependencies:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Rig {rig.rig_code} still has {', '.join(dependencies)}. "
                "Move dependent wells and costing records to their respective Deleted Entries first."
            ),
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
    afes = _count_children(db, Afe, user.organization_id, rig_id=rig.id)
    daily_sheets = _count_children(db, DailyCostEntry, user.organization_id, rig_id=rig.id)
    mud_entries = _count_children(db, MudCostEntry, user.organization_id, rig_id=rig.id)
    if wells or afes or daily_sheets or mud_entries:
        dependencies = []
        if wells:
            dependencies.append(f"{wells} well record(s)")
        if afes:
            dependencies.append(f"{afes} AFE record(s)")
        if daily_sheets:
            dependencies.append(f"{daily_sheets} daily-cost sheet(s)")
        if mud_entries:
            dependencies.append(f"{mud_entries} Mud Cost entry/entries")
        raise HTTPException(
            status_code=409,
            detail=(
                f"Rig {rig.rig_code} retains {', '.join(dependencies)}. Permanently delete the dependent "
                "wells, AFEs, and daily-cost sheets first in their respective Deleted Entries."
            ),
        )
    # Fuel, LIH and SOW records also point at the rig. Naming them here keeps the
    # purge actionable instead of ending in a database integrity error.
    assert_purgeable(
        db, user.organization_id, rig,
        entity_label=f"rig {rig.rig_code}",
        next_step=(
            "Permanently delete the dependent fuel, LIH and SOW adjustment records from their own module first."
        ),
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
    rig_ids = [rig.id for rig in rigs]
    well_counts = _counts_by_parent(db, Well, Well.rig_id, user.organization_id, rig_ids, active_only=True)
    afe_counts = _counts_by_parent(db, Afe, Afe.rig_id, user.organization_id, rig_ids, active_only=True)
    daily_counts = _counts_by_parent(db, DailyCostEntry, DailyCostEntry.rig_id, user.organization_id, rig_ids, active_only=True)
    mud_counts = _counts_by_parent(db, MudCostEntry, MudCostEntry.rig_id, user.organization_id, rig_ids, active_only=True)
    blocked = [
        (rig, [
            *( [f"{well_counts[rig.id]} active well(s)"] if well_counts.get(rig.id) else [] ),
            *( [f"{afe_counts[rig.id]} active AFE(s)"] if afe_counts.get(rig.id) else [] ),
            *( [f"{daily_counts[rig.id]} active daily-cost sheet(s)"] if daily_counts.get(rig.id) else [] ),
            *( [f"{mud_counts[rig.id]} active Mud Cost entry/entries"] if mud_counts.get(rig.id) else [] ),
        ])
        for rig in rigs
        if well_counts.get(rig.id) or afe_counts.get(rig.id) or daily_counts.get(rig.id) or mud_counts.get(rig.id)
    ]
    if blocked:
        rig, dependencies = blocked[0]
        raise HTTPException(
            status_code=409,
            detail=f"Rig {rig.rig_code} still has {', '.join(dependencies)}. Delete or move each dependent record first.",
        )
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
# Blocks
# ---------------------------------------------------------------------------


@router.get(
    "/blocks/dropdown",
    response_model=list[BlockDropdownOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_blocks_dropdown(db: Db, user: Current) -> list[BlockDropdownOut]:
    counts = _block_well_counts(db, user.organization_id)
    blocks = db.scalars(
        select(Block)
        .where(Block.organization_id == user.organization_id, Block.is_deleted.is_(False))
        .order_by(Block.block_code)
    ).all()
    return [
        BlockDropdownOut(
            id=block.id,
            block_code=block.block_code,
            block_name=block.block_name,
            description=block.description or "",
            display_name=f"{block.block_code} — {block.block_name}",
            well_count=counts.get(block.id, 0),
        )
        for block in blocks
    ]


@router.get("/blocks", response_model=list[BlockOut], dependencies=[Depends(require("rig-well:read"))])
def list_blocks(
    db: Db,
    user: Current,
    search: str | None = Query(default=None, max_length=200),
) -> list[BlockOut]:
    statement = select(Block).where(
        Block.organization_id == user.organization_id,
        Block.is_deleted.is_(False),
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        statement = statement.where(
            or_(Block.block_code.ilike(like), Block.block_name.ilike(like), Block.description.ilike(like))
        )
    records = db.scalars(statement.order_by(Block.block_code)).all()
    counts = _block_well_counts(db, user.organization_id)
    return [_block_out(record, counts.get(record.id, 0)) for record in records]


@router.post(
    "/blocks",
    response_model=BlockOut,
    status_code=201,
    dependencies=[Depends(require("rig-well:create"))],
)
def create_block(data: BlockCreate, request: Request, db: Db, user: Current) -> BlockOut:
    existing = db.scalar(
        select(Block).where(
            Block.organization_id == user.organization_id,
            Block.block_code == data.block_code,
        )
    )
    if existing is not None:
        if not existing.is_deleted:
            raise HTTPException(status_code=409, detail=_code_conflict_message("Block", data.block_code))
        existing.block_name = data.block_name
        existing.description = data.description
        existing.is_deleted = False
        existing.deleted_at = None
        _record_audit(
            db, user=user, action="restore", entity_type="block", record_id=existing.id,
            entity_label=existing.block_code,
            summary=f"Restored and updated block {existing.block_code} from create",
            request=request,
        )
        _commit(db)
        db.refresh(existing)
        return _block_out(existing)

    block = Block(
        organization_id=user.organization_id,
        block_code=data.block_code,
        block_name=data.block_name,
        description=data.description,
    )
    db.add(block)
    db.flush()
    _record_audit(
        db, user=user, action="create", entity_type="block", record_id=block.id,
        entity_label=block.block_code,
        summary=f"Created block {block.block_code} — {block.block_name}",
        request=request,
    )
    _commit(db)
    db.refresh(block)
    return _block_out(block)


@router.patch(
    "/blocks/{block_id}",
    response_model=BlockOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def update_block(block_id: str, data: BlockUpdate, request: Request, db: Db, user: Current) -> BlockOut:
    block = _block_or_404(db, block_id, user.organization_id, include_deleted=False)
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field, value in payload.items():
        if value is None:
            continue
        if field == "description":
            value = value or ""
        if getattr(block, field) == value:
            continue
        if field == "block_code":
            duplicate = db.scalar(
                select(Block).where(
                    Block.organization_id == user.organization_id,
                    Block.block_code == value,
                    Block.id != block.id,
                )
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409,
                    detail=_code_conflict_message("Block", value, deleted=duplicate.is_deleted),
                )
        setattr(block, field, value)
        changed.append(field)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="block", record_id=block.id,
            entity_label=block.block_code,
            summary=f"Updated block {block.block_code}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
        db.refresh(block)
    return _block_out(block)


@router.delete(
    "/blocks/{block_id}",
    response_model=BlockOut,
    dependencies=[Depends(require("rig-well:delete"))],
)
def soft_delete_block(block_id: str, request: Request, db: Db, user: Current) -> BlockOut:
    block = _block_or_404(db, block_id, user.organization_id, include_deleted=False)
    active_wells = _count_children(db, Well, user.organization_id, block_id=block.id, is_deleted=False)
    if active_wells:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Block {block.block_code} still owns {active_wells} well(s). Move those wells to "
                "Deleted Entries or reassign them to another block first."
            ),
        )
    block.is_deleted = True
    block.deleted_at = _now()
    _record_audit(
        db, user=user, action="soft_delete", entity_type="block", record_id=block.id,
        entity_label=block.block_code,
        summary=f"Moved block {block.block_code} to Deleted Entries",
        request=request,
    )
    _commit(db)
    db.refresh(block)
    return _block_out(block)


@router.post(
    "/blocks/{block_id}/restore",
    response_model=BlockOut,
    dependencies=[Depends(require("rig-well:restore"))],
)
def restore_block(block_id: str, request: Request, db: Db, user: Current) -> BlockOut:
    block = _block_or_404(db, block_id, user.organization_id)
    if not block.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted block can be restored")
    block.is_deleted = False
    block.deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="block", record_id=block.id,
        entity_label=block.block_code,
        summary=f"Restored block {block.block_code}",
        request=request,
    )
    _commit(db)
    db.refresh(block)
    return _block_out(block)


@router.delete(
    "/blocks/{block_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("rig-well:permanent-delete"))],
)
def permanently_delete_block(block_id: str, request: Request, db: Db, user: Current) -> None:
    block = _block_or_404(db, block_id, user.organization_id)
    if not block.is_deleted:
        raise HTTPException(status_code=409, detail="Move the block to Deleted Entries before permanent deletion")
    retained_wells = _count_children(db, Well, user.organization_id, block_id=block.id)
    if retained_wells:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Block {block.block_code} still has {retained_wells} well record(s). Permanently delete those "
                "wells from Deleted Entries first."
            ),
        )
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="block", record_id=block.id,
        entity_label=block.block_code,
        summary=f"Permanently deleted block {block.block_code}",
        request=request,
    )
    db.delete(block)
    _commit(db)


@router.post(
    "/blocks/bulk-delete",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:delete"))],
)
def bulk_delete_blocks(data: RigWellIDs, request: Request, db: Db, user: Current) -> RigWellBulkActionResponse:
    blocks = _records_for_ids(db, Block, data.ids, user.organization_id, deleted=False)
    block_ids = [block.id for block in blocks]
    well_counts = _counts_by_parent(
        db, Well, Well.block_id, user.organization_id, block_ids, active_only=True
    )
    blocked = [(block, well_counts[block.id]) for block in blocks if well_counts.get(block.id)]
    if blocked:
        block, count = blocked[0]
        raise HTTPException(
            status_code=409,
            detail=(
                f"Block {block.block_code} still owns {count} well(s). Move or reassign them "
                "before deleting the block."
            ),
        )
    deleted_at = _now()
    for block in blocks:
        block.is_deleted = True
        block.deleted_at = deleted_at
        _record_audit(
            db, user=user, action="soft_delete", entity_type="block", record_id=block.id,
            entity_label=block.block_code,
            summary=f"Moved block {block.block_code} to Deleted Entries (bulk action)",
            request=request,
        )
    _record_audit(
        db, user=user, action="delete", entity_type="block", record_id=None,
        entity_label="Block register",
        summary=f"Moved {len(blocks)} blocks to Deleted Entries",
        request=request,
    )
    _commit(db)
    return RigWellBulkActionResponse(affected_count=len(blocks))


@router.post(
    "/blocks/import",
    response_model=RigWellImportResponse,
    dependencies=[Depends(require("rig-well:import"))],
)
def import_blocks(data: RigWellImportRequest, request: Request, db: Db, user: Current) -> RigWellImportResponse:
    imported = 0
    errors: list[str] = []
    seen_codes: set[str] = set()
    for row_number, row in enumerate(data.rows, start=1):
        code = _string(_row_value(row, "block_code", "code", "blockcode")).upper()
        name = _string(_row_value(row, "block_name", "name", "blockname"))
        description = _string(_row_value(row, "description", "remarks", "remark"))
        if not code:
            errors.append(f"Row {row_number}: block_code is required")
            continue
        if not name:
            errors.append(f"Row {row_number} ({code}): block_name is required")
            continue
        if code in seen_codes:
            errors.append(f"Row {row_number} ({code}): duplicate block_code in this import")
            continue
        seen_codes.add(code)
        try:
            payload = BlockCreate.model_validate(
                {"block_code": code, "block_name": name, "description": description}
            )
        except ValidationError as error:
            errors.append(f"Row {row_number} ({code}): {_validation_message(error)}")
            continue
        existing = db.scalar(
            select(Block).where(
                Block.organization_id == user.organization_id,
                Block.block_code == payload.block_code,
            )
        )
        if existing is None:
            existing = Block(
                organization_id=user.organization_id,
                block_code=payload.block_code,
                block_name=payload.block_name,
                description=payload.description,
            )
            db.add(existing)
            action = "create"
            summary = f"Created block {payload.block_code} from import"
        else:
            action = "restore" if existing.is_deleted else "update"
            existing.block_name = payload.block_name
            existing.description = payload.description
            existing.is_deleted = False
            existing.deleted_at = None
            summary = (
                f"{'Restored and updated' if action == 'restore' else 'Updated'} block "
                f"{payload.block_code} from import"
            )
        db.flush()
        _record_audit(
            db, user=user, action=action, entity_type="block", record_id=existing.id,
            entity_label=payload.block_code, summary=summary, request=request,
        )
        imported += 1
    _record_audit(
        db, user=user, action="import", entity_type="block", record_id=None,
        entity_label="Block register",
        summary=f"Imported {imported} blocks with {len(errors)} row error(s)",
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


def _scope_active_dependencies(
    db: Session,
    organization_id: str,
    well: Well,
    scope: str,
) -> list[str]:
    active_children = _count_children(
        db, WellSubActivity, organization_id, well_id=well.id, scope=scope, is_deleted=False
    )
    active_afes = _count_children(
        db, Afe, organization_id, well_id=well.id, configuration_scope=scope, is_deleted=False
    )
    active_daily_sheets = int(
        db.scalar(
            select(func.count(DailyCostEntry.id))
            .join(Afe, DailyCostEntry.afe_id == Afe.id)
            .where(
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.well_id == well.id,
                DailyCostEntry.is_deleted.is_(False),
                Afe.organization_id == organization_id,
                Afe.configuration_scope == scope,
            )
        )
        or 0
    )
    active_mud_entries = _count_children(
        db, MudCostEntry, organization_id, well_id=well.id, section_scope=scope, is_deleted=False
    )
    active_lih_entries = int(
        db.scalar(
            select(func.count(LihCostEntry.id))
            .join(Afe, LihCostEntry.afe_id == Afe.id)
            .where(
                LihCostEntry.organization_id == organization_id,
                LihCostEntry.well_id == well.id,
                LihCostEntry.is_deleted.is_(False),
                Afe.organization_id == organization_id,
                Afe.configuration_scope == scope,
            )
        )
        or 0
    )
    dependencies: list[str] = []
    if active_children:
        dependencies.append(f"{active_children} active sub activity record(s)")
    if active_afes:
        dependencies.append(f"{active_afes} active AFE(s)")
    if active_daily_sheets:
        dependencies.append(f"{active_daily_sheets} active daily-cost sheet(s)")
    if active_mud_entries:
        dependencies.append(f"{active_mud_entries} active Mud Cost entry/entries")
    if active_lih_entries:
        dependencies.append(f"{active_lih_entries} active LIH cost entry/entries")
    return dependencies


def _scope_retained_dependencies(
    db: Session,
    organization_id: str,
    well: Well,
    scope: str,
    *,
    ignore_sub_activity_ids: set[str] | None = None,
) -> list[str]:
    sub_activity_stmt = select(func.count(WellSubActivity.id)).where(
        WellSubActivity.organization_id == organization_id,
        WellSubActivity.well_id == well.id,
        WellSubActivity.scope == scope,
    )
    if ignore_sub_activity_ids:
        sub_activity_stmt = sub_activity_stmt.where(WellSubActivity.id.notin_(ignore_sub_activity_ids))
    sub_activities = int(db.scalar(sub_activity_stmt) or 0)
    afes = _count_children(db, Afe, organization_id, well_id=well.id, configuration_scope=scope)
    daily_sheets = int(
        db.scalar(
            select(func.count(DailyCostEntry.id))
            .join(Afe, DailyCostEntry.afe_id == Afe.id)
            .where(
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.well_id == well.id,
                Afe.organization_id == organization_id,
                Afe.configuration_scope == scope,
            )
        )
        or 0
    )
    mud_entries = _count_children(
        db, MudCostEntry, organization_id, well_id=well.id, section_scope=scope
    )
    lih_entries = int(
        db.scalar(
            select(func.count(LihCostEntry.id))
            .join(Afe, LihCostEntry.afe_id == Afe.id)
            .where(
                LihCostEntry.organization_id == organization_id,
                LihCostEntry.well_id == well.id,
                Afe.organization_id == organization_id,
                Afe.configuration_scope == scope,
            )
        )
        or 0
    )
    plan_adjustments = _count_children(
        db, WellPlanAdjustment, organization_id, well_id=well.id, configuration_scope=scope
    )
    dependencies: list[str] = []
    if sub_activities:
        dependencies.append(f"{sub_activities} sub activity record(s)")
    if afes:
        dependencies.append(f"{afes} AFE record(s)")
    if daily_sheets:
        dependencies.append(f"{daily_sheets} daily-cost sheet(s)")
    if mud_entries:
        dependencies.append(f"{mud_entries} Mud Cost entry/entries")
    if lih_entries:
        dependencies.append(f"{lih_entries} LIH cost entry/entries")
    if plan_adjustments:
        dependencies.append(f"{plan_adjustments} well-plan adjustment(s)")
    return dependencies


def _purge_well_scope_data(
    db: Session,
    organization_id: str,
    well: Well,
    scope: str,
) -> str:
    """Purge owned configuration rows for one well scope; remove the Well row if both scopes are purged."""
    mud_settings = list(
        db.scalars(
            select(MudCostSectionSetting).where(
                MudCostSectionSetting.organization_id == organization_id,
                MudCostSectionSetting.well_id == well.id,
                MudCostSectionSetting.section_scope == scope,
            )
        ).all()
    )
    for item in mud_settings:
        db.delete(item)
    for section in list(well.sections_for_scope(scope)):
        db.delete(section)
    db.flush()
    well.set_scope_value(scope, "status", "active")
    well.set_scope_value(scope, "config_status", "draft")
    well.set_scope_value(scope, "depth_unit", "m")
    if scope == "completion":
        well.completion_spud_at = None
        well.completion_progress_completed_at = None
        well.completion_is_deleted = True
        well.completion_purged = True
    else:
        well.drilling_spud_at = None
        well.drilling_progress_completed_at = None
        well.drilling_is_deleted = True
        well.drilling_purged = True

    other = _other_scope(scope)
    if well.scope_is_purged(other):
        assert_purgeable(
            db,
            organization_id,
            well,
            entity_label=f"well {well.well_code}",
            next_step=(
                "Permanently delete the dependent LIH cost entries and SOW/well-plan revisions from their own "
                "module first."
            ),
        )
        removed = purge_owned_snapshots(db, organization_id, well_ids=[well.id])
        snapshot_note = snapshot_summary(removed)
        db.delete(well)
        return snapshot_note

    well.sync_deleted_from_scopes()
    return ""


@router.get(
    "/wells",
    response_model=list[WellOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_wells(
    db: Db,
    user: Current,
    rig_id: str | None = None,
    block_id: str | None = None,
    status: Literal["active", "completed"] | None = None,
    config_status: Literal["draft", "configured"] | None = None,
    block: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
) -> list[WellOut]:
    statement = (
        select(Well)
        .options(
            joinedload(Well.rig),
            joinedload(Well.block_record),
            selectinload(Well.sections).selectinload(WellSection.phases),
            selectinload(Well.completion_sections).selectinload(WellSection.phases),
        )
        .join(Block, Well.block_id == Block.id)
        .where(
            Well.organization_id == user.organization_id,
            Well.is_deleted.is_(False),
            Block.organization_id == user.organization_id,
        )
    )
    if rig_id:
        _rig_or_404(db, rig_id, user.organization_id, include_deleted=False)
        statement = statement.where(Well.rig_id == rig_id)
    if block_id:
        _block_or_404(db, block_id, user.organization_id, include_deleted=False)
        statement = statement.where(Well.block_id == block_id)
    if status:
        statement = statement.where(Well.status == status)
    if config_status:
        statement = statement.where(Well.config_status == config_status)
    if block and block.strip():
        text = block.strip()
        statement = statement.where(
            or_(Block.block_code.ilike(text), Block.block_name.ilike(text))
        )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Well.well_code.ilike(pattern),
                Well.well_name.ilike(pattern),
                Well.well_location.ilike(pattern),
                Block.block_code.ilike(pattern),
                Block.block_name.ilike(pattern),
                Well.objective.ilike(pattern),
                Well.remarks.ilike(pattern),
            )
        )
    # Block-first ordering keeps each block's wells together in the register, so
    # the list reads as a block-by-block segregation by default.
    wells = db.scalars(statement.order_by(Block.block_code, Well.well_code)).all()
    well_ids = [well.id for well in wells]
    scoped_counts = _scoped_sub_activity_counts(db, user.organization_id, well_ids)
    plan_map = _effective_plan_map(db, user.organization_id, well_ids)
    return [
        _well_out(
            well,
            scoped_counts.get((well.id, "drilling"), 0) + scoped_counts.get((well.id, "completion"), 0),
            drilling_sub_activity_count=scoped_counts.get((well.id, "drilling"), 0),
            completion_sub_activity_count=scoped_counts.get((well.id, "completion"), 0),
            plan_adjustment=plan_map.get(well.id),
        )
        for well in wells
    ]


@router.post(
    "/wells",
    response_model=WellOut,
    status_code=201,
    dependencies=[Depends(require("rig-well:create"))],
)
def create_well(data: WellCreate, request: Request, db: Db, user: Current) -> WellOut:
    rig = _rig_or_404(db, data.rig_id, user.organization_id, include_deleted=False)
    block = _block_or_404(db, data.block_id, user.organization_id, include_deleted=False)
    include_drilling = "drilling" in data.scopes
    include_completion = "completion" in data.scopes
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
        existing.block_record = block
        existing.well_name = data.well_name
        existing.well_location = data.well_location
        existing.objective = data.objective
        existing.remarks = data.remarks
        existing.drilling_is_deleted = not include_drilling
        existing.drilling_deleted_at = None
        existing.drilling_purged = not include_drilling
        existing.completion_is_deleted = not include_completion
        existing.completion_deleted_at = None
        existing.completion_purged = not include_completion
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
        return _well_out_for(db, user.organization_id, existing)
    well = Well(
        organization_id=user.organization_id,
        rig_id=rig.id,
        block_id=block.id,
        well_code=data.well_code,
        well_name=data.well_name,
        well_location=data.well_location,
        objective=data.objective,
        remarks=data.remarks,
        drilling_is_deleted=not include_drilling,
        drilling_purged=not include_drilling,
        completion_is_deleted=not include_completion,
        completion_purged=not include_completion,
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
    return _well_out_for(db, user.organization_id, well)


@router.post(
    "/wells/{well_id}/scopes/{scope}/activate",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:update"))],
)
def activate_well_scope(
    well_id: str,
    scope: Literal["drilling", "completion"],
    request: Request,
    db: Db,
    user: Current,
) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    _rig_or_404(db, well.rig_id, user.organization_id, include_deleted=False)
    if not well.scope_is_deleted(scope):
        raise HTTPException(status_code=409, detail=f"The {_scope_label(scope)} scope is already active")
    if scope == "completion":
        well.completion_is_deleted = False
        well.completion_deleted_at = None
        well.completion_purged = False
    else:
        well.drilling_is_deleted = False
        well.drilling_deleted_at = None
        well.drilling_purged = False
    well.sync_deleted_from_scopes()
    _record_audit(
        db,
        user=user,
        action="update",
        entity_type="well",
        record_id=well.id,
        entity_label=well.well_code,
        summary=f"Enabled {_scope_label(scope)} scope on well {well.well_code}",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out_for(db, user.organization_id, well)


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
            retained_mud_entries = _count_children(db, MudCostEntry, user.organization_id, well_id=well.id)
            if retained_mud_entries:
                raise HTTPException(
                    status_code=409,
                    detail="This well has retained Mud Cost Analysis history. Permanently delete those entries before changing its rig.",
                )
            well.rig = _rig_or_404(db, value, user.organization_id, include_deleted=False)
            changed.append(field)
            continue
        elif field == "block_id":
            well.block_record = _block_or_404(
                db, value, user.organization_id, include_deleted=False
            )
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
    return _well_out_for(db, user.organization_id, well)


@router.delete(
    "/wells/{well_id}",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:delete"))],
)
def soft_delete_well(
    well_id: str,
    request: Request,
    db: Db,
    user: Current,
    scope: Literal["drilling", "completion"] | None = Query(default=None),
) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    if scope is not None:
        if well.scope_is_deleted(scope):
            raise HTTPException(
                status_code=404,
                detail=f"{_scope_label(scope)} scope on well {well.well_code} is already deleted",
            )
        dependencies = _scope_active_dependencies(db, user.organization_id, well, scope)
        if dependencies:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Well {well.well_code} ({_scope_label(scope)}) still has {', '.join(dependencies)}. "
                    "Move dependent sub activities and costing records for this scope to their respective Deleted Entries first."
                ),
            )
        ts = _now()
        if scope == "completion":
            well.completion_is_deleted = True
            well.completion_deleted_at = ts
            well.completion_purged = False
        else:
            well.drilling_is_deleted = True
            well.drilling_deleted_at = ts
            well.drilling_purged = False
        well.sync_deleted_from_scopes(ts)
        _record_audit(
            db,
            user=user,
            action="soft_delete",
            entity_type="well",
            record_id=well.id,
            entity_label=f"{well.well_code} ({_scope_label(scope)})",
            summary=f"Moved {_scope_label(scope)} scope of well {well.well_code} to Deleted Entries",
            request=request,
        )
        _commit(db)
        db.refresh(well)
        return _well_out_for(db, user.organization_id, well)

    active_children = _count_children(
        db, WellSubActivity, user.organization_id, well_id=well.id, is_deleted=False
    )
    active_afes = _count_children(db, Afe, user.organization_id, well_id=well.id, is_deleted=False)
    active_daily_sheets = _count_children(db, DailyCostEntry, user.organization_id, well_id=well.id, is_deleted=False)
    active_mud_entries = _count_children(db, MudCostEntry, user.organization_id, well_id=well.id, is_deleted=False)
    dependencies = []
    if active_children:
        dependencies.append(f"{active_children} active sub activity record(s)")
    if active_afes:
        dependencies.append(f"{active_afes} active AFE(s)")
    if active_daily_sheets:
        dependencies.append(f"{active_daily_sheets} active daily-cost sheet(s)")
    if active_mud_entries:
        dependencies.append(f"{active_mud_entries} active Mud Cost entry/entries")
    if dependencies:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Well {well.well_code} still has {', '.join(dependencies)}. "
                "Move dependent sub activities and costing records to their respective Deleted Entries first."
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
    return _well_out_for(db, user.organization_id, well)


@router.post(
    "/wells/{well_id}/restore",
    response_model=WellOut,
    dependencies=[Depends(require("rig-well:restore"))],
)
def restore_well(
    well_id: str,
    request: Request,
    db: Db,
    user: Current,
    scope: Literal["drilling", "completion"] | None = Query(default=None),
) -> WellOut:
    well = _well_or_404(db, well_id, user.organization_id)
    if scope is not None:
        if not well.scope_is_deleted(scope) or well.scope_is_purged(scope):
            raise HTTPException(status_code=409, detail="Only a deleted well scope can be restored")
        _rig_or_404(db, well.rig_id, user.organization_id, include_deleted=False)
        other = _other_scope(scope)
        if well.is_deleted and not well.drilling_is_deleted and not well.completion_is_deleted:
            # Whole-well soft-deleted row where one scope is restored individually.
            if other == "completion":
                well.completion_is_deleted = True
                well.completion_deleted_at = well.deleted_at or _now()
            else:
                well.drilling_is_deleted = True
                well.drilling_deleted_at = well.deleted_at or _now()
        if scope == "completion":
            well.completion_is_deleted = False
            well.completion_deleted_at = None
            well.completion_purged = False
        else:
            well.drilling_is_deleted = False
            well.drilling_deleted_at = None
            well.drilling_purged = False
        well.sync_deleted_from_scopes()
        _record_audit(
            db,
            user=user,
            action="restore",
            entity_type="well",
            record_id=well.id,
            entity_label=f"{well.well_code} ({_scope_label(scope)})",
            summary=f"Restored {_scope_label(scope)} scope of well {well.well_code}",
            request=request,
        )
        _commit(db)
        db.refresh(well)
        return _well_out_for(db, user.organization_id, well)

    if not well.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted well can be restored")
    _rig_or_404(db, well.rig_id, user.organization_id, include_deleted=False)
    well.is_deleted = False
    well.deleted_at = None
    if not well.drilling_purged:
        well.drilling_is_deleted = False
        well.drilling_deleted_at = None
    if not well.completion_purged:
        well.completion_is_deleted = False
        well.completion_deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Restored well {well.well_code}",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out_for(db, user.organization_id, well)


@router.delete(
    "/wells/{well_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("rig-well:permanent-delete"))],
)
def permanently_delete_well(
    well_id: str,
    request: Request,
    db: Db,
    user: Current,
    scope: Literal["drilling", "completion"] | None = Query(default=None),
) -> None:
    well = _well_or_404(db, well_id, user.organization_id)
    if scope is not None:
        if not well.scope_is_deleted(scope) or well.scope_is_purged(scope):
            raise HTTPException(status_code=409, detail="Move the well scope to Deleted Entries before permanent deletion")
        dependencies = _scope_retained_dependencies(db, user.organization_id, well, scope)
        if dependencies:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Well {well.well_code} ({_scope_label(scope)}) retains {', '.join(dependencies)}. "
                    "Move them to Deleted Entries if they are still active, then permanently delete them there first."
                ),
            )
        well_code = well.well_code
        well_id_copy = well.id
        snapshot_note = _purge_well_scope_data(db, user.organization_id, well, scope)
        _record_audit(
            db,
            user=user,
            action="permanent_delete",
            entity_type="well",
            record_id=well_id_copy,
            entity_label=f"{well_code} ({_scope_label(scope)})",
            summary=(
                f"Permanently deleted {_scope_label(scope)} scope of well {well_code}"
                + (f", together with {snapshot_note}" if snapshot_note else "")
            ),
            request=request,
        )
        _commit(db)
        return

    if not well.is_deleted:
        raise HTTPException(status_code=409, detail="Move the well to Deleted Entries before permanent deletion")
    sub_activities = _count_children(db, WellSubActivity, user.organization_id, well_id=well.id)
    afes = _count_children(db, Afe, user.organization_id, well_id=well.id)
    daily_sheets = _count_children(db, DailyCostEntry, user.organization_id, well_id=well.id)
    mud_entries = _count_children(db, MudCostEntry, user.organization_id, well_id=well.id)
    if sub_activities or afes or daily_sheets or mud_entries:
        dependencies = []
        if sub_activities:
            dependencies.append(f"{sub_activities} sub activity record(s)")
        if afes:
            dependencies.append(f"{afes} AFE record(s)")
        if daily_sheets:
            dependencies.append(f"{daily_sheets} daily-cost sheet(s)")
        if mud_entries:
            dependencies.append(f"{mud_entries} Mud Cost entry/entries")
        raise HTTPException(
            status_code=409,
            detail=(
                f"Well {well.well_code} retains {', '.join(dependencies)}. Move them to Deleted Entries if they "
                "are still active, then permanently delete them there. The well's own locked rate snapshots are "
                "removed with the well once those records are gone."
            ),
        )
    # LIH entries, SOW/plan revisions and any other RESTRICT reference are named
    # explicitly; only an actionable 409 leaves this endpoint.
    assert_purgeable(
        db, user.organization_id, well,
        entity_label=f"well {well.well_code}",
        next_step=(
            "Permanently delete the dependent LIH cost entries and SOW/well-plan revisions from their own "
            "module first."
        ),
    )
    # The well's locked rate book and any AFE baselines it still owns are audit
    # snapshots of this well. They are purged with it, now that every sheet that
    # priced from them is gone, so the well itself can be permanently removed.
    removed = purge_owned_snapshots(db, user.organization_id, well_ids=[well.id])
    snapshot_note = snapshot_summary(removed)
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=(
            f"Permanently deleted well {well.well_code}"
            + (f", together with {snapshot_note}" if snapshot_note else "")
        ),
        request=request,
    )
    db.delete(well)
    _commit(db)


@router.post(
    "/wells/bulk-delete",
    response_model=RigWellBulkActionResponse,
    dependencies=[Depends(require("rig-well:delete"))],
)
def bulk_delete_wells(
    data: WellBulkDeleteRequest,
    request: Request,
    db: Db,
    user: Current,
) -> RigWellBulkActionResponse:
    if data.items:
        pairs = [(item.id, item.scope) for item in data.items]
        if len(pairs) != len(set(pairs)):
            raise HTTPException(status_code=422, detail="Duplicate well scope selections are not allowed")
        unique_ids = list({item.id for item in data.items})
        wells_by_id = {
            well.id: well
            for well in db.scalars(
                select(Well).where(
                    Well.organization_id == user.organization_id,
                    Well.id.in_(unique_ids),
                )
            ).all()
        }
        if len(wells_by_id) != len(unique_ids):
            raise HTTPException(status_code=404, detail="One or more records do not belong to this workspace")
        for item in data.items:
            well = wells_by_id[item.id]
            if well.scope_is_deleted(item.scope):
                raise HTTPException(status_code=409, detail="This bulk action requires only active well scopes")
            dependencies = _scope_active_dependencies(db, user.organization_id, well, item.scope)
            if dependencies:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Well {well.well_code} ({_scope_label(item.scope)}) still has {', '.join(dependencies)}. "
                        "Delete or move each dependent record for this scope first."
                    ),
                )
        deleted_at = _now()
        for item in data.items:
            well = wells_by_id[item.id]
            if item.scope == "completion":
                well.completion_is_deleted = True
                well.completion_deleted_at = deleted_at
                well.completion_purged = False
            else:
                well.drilling_is_deleted = True
                well.drilling_deleted_at = deleted_at
                well.drilling_purged = False
            well.sync_deleted_from_scopes(deleted_at)
            _record_audit(
                db,
                user=user,
                action="soft_delete",
                entity_type="well",
                record_id=well.id,
                entity_label=f"{well.well_code} ({_scope_label(item.scope)})",
                summary=f"Moved {_scope_label(item.scope)} scope of well {well.well_code} to Deleted Entries (bulk action)",
                request=request,
            )
        _record_audit(
            db,
            user=user,
            action="delete",
            entity_type="well",
            record_id=None,
            entity_label="Well register",
            summary=f"Moved {len(data.items)} well scope(s) to Deleted Entries",
            request=request,
        )
        _commit(db)
        return RigWellBulkActionResponse(affected_count=len(data.items))

    wells = _records_for_ids(db, Well, data.ids, user.organization_id, deleted=False)
    well_ids = [well.id for well in wells]
    sub_activity_counts = _counts_by_parent(
        db, WellSubActivity, WellSubActivity.well_id, user.organization_id, well_ids, active_only=True
    )
    afe_counts = _counts_by_parent(db, Afe, Afe.well_id, user.organization_id, well_ids, active_only=True)
    daily_counts = _counts_by_parent(
        db, DailyCostEntry, DailyCostEntry.well_id, user.organization_id, well_ids, active_only=True
    )
    mud_counts = _counts_by_parent(
        db, MudCostEntry, MudCostEntry.well_id, user.organization_id, well_ids, active_only=True
    )
    blocked = []
    for well in wells:
        dependencies = []
        if sub_activity_counts.get(well.id):
            dependencies.append(f"{sub_activity_counts[well.id]} active sub activity record(s)")
        if afe_counts.get(well.id):
            dependencies.append(f"{afe_counts[well.id]} active AFE(s)")
        if daily_counts.get(well.id):
            dependencies.append(f"{daily_counts[well.id]} active daily-cost sheet(s)")
        if mud_counts.get(well.id):
            dependencies.append(f"{mud_counts[well.id]} active Mud Cost entry/entries")
        if dependencies:
            blocked.append((well, dependencies))
    if blocked:
        well, dependencies = blocked[0]
        raise HTTPException(
            status_code=409,
            detail=f"Well {well.well_code} still has {', '.join(dependencies)}. Delete or move each dependent record first.",
        )
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
        block_ref = _string(_row_value(row, "block_code", "block", "block_name"))
        block = None
        if block_ref:
            block = db.scalar(
                select(Block).where(
                    Block.organization_id == user.organization_id,
                    Block.is_deleted.is_(False),
                    or_(
                        Block.block_code == block_ref.upper(),
                        Block.block_name.ilike(block_ref),
                    ),
                )
            )
        if block is None:
            errors.append(
                f"Row {row_number}: block_code '{block_ref or '—'}' is missing or is not an active block "
                "in this workspace. Add the block in Rig & Well Management → Blocks first."
            )
            continue
        raw = {
            "rig_id": rig.id,
            "block_id": block.id,
            "well_code": _row_value(row, "well_code", "code", "wellcode"),
            "well_name": _row_value(row, "well_name", "name", "wellname"),
            "well_location": _row_value(row, "well_location", "location"),
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
                block_id=block.id,
                well_code=payload.well_code,
                well_name=payload.well_name,
                well_location=payload.well_location,
                objective=payload.objective,
                remarks=payload.remarks,
            )
            db.add(existing)
            action = "create"
            summary = f"Created well {payload.well_code} under rig {rig.rig_code} from import"
        else:
            action = "restore" if existing.is_deleted else "update"
            existing.rig = rig
            existing.block_record = block
            existing.well_name = payload.well_name
            existing.well_location = payload.well_location
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
def get_well_configuration(well_id: str, db: Db, user: Current, scope: Literal["drilling", "completion"] = "drilling") -> WellConfigurationOut:
    well = _well_or_404(db, well_id, user.organization_id, include_deleted=False)
    if well.scope_is_deleted(scope):
        raise HTTPException(
            status_code=409,
            detail=f"Restore or add the {_scope_label(scope)} scope on well {well.well_code} before viewing or editing its configuration",
        )
    return _well_configuration_out(well, scope)


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
    if well.scope_is_deleted(data.scope):
        raise HTTPException(
            status_code=409,
            detail=f"Restore or add the {_scope_label(data.scope)} scope on well {well.well_code} before editing its configuration",
        )
    if well.scope_value(data.scope, "status") == "completed":
        raise HTTPException(status_code=409, detail="Reactivate the completed well before editing its configuration")
    if well.scope_value(data.scope, "config_status") != "draft":
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
    for old_section in list(well.sections_for_scope(data.scope)):
        db.delete(old_section)
    db.flush()
    well.set_scope_value(data.scope, "depth_unit", data.depth_unit)
    for section_order, (master_section, phase_rows) in enumerate(resolved):
        section_row = WellSection(
            organization_id=user.organization_id,
            well_id=well.id,
            scope=data.scope,
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
        summary=f"Saved {data.scope} draft configuration for well {well.well_code}: {len(data.sections)} section(s)",
        request=request,
    )
    _commit(db)
    db.expire(well, ["sections", "completion_sections"])
    return _well_configuration_out(well, data.scope)


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
    if well.scope_is_deleted(data.scope):
        raise HTTPException(
            status_code=409,
            detail=f"Restore or add the {_scope_label(data.scope)} scope on well {well.well_code} before changing its lifecycle state",
        )
    action = data.action
    if action == "configure":
        if well.scope_value(data.scope, "status") != "active":
            raise HTTPException(status_code=409, detail="Reactivate the well before marking it configured")
        if well.scope_value(data.scope, "config_status") != "draft":
            raise HTTPException(status_code=409, detail="The well is already configured")
        if not well.sections_for_scope(data.scope):
            raise HTTPException(status_code=409, detail="Save at least one section and phase before marking the well configured")
        well.set_scope_value(data.scope, "config_status", "configured")
        label = "configured"
    elif action == "draft":
        if well.scope_value(data.scope, "status") != "active":
            raise HTTPException(status_code=409, detail="Reactivate the well before reopening its configuration")
        if well.scope_value(data.scope, "config_status") != "configured":
            raise HTTPException(status_code=409, detail="The well is already in Draft")
        well.set_scope_value(data.scope, "config_status", "draft")
        label = "Draft"
    elif action == "final_review":
        if well.scope_value(data.scope, "status") != "active":
            raise HTTPException(status_code=409, detail="Reactivate the well before marking its scope for final review")
        if well.scope_value(data.scope, "config_status") != "configured":
            raise HTTPException(status_code=409, detail="The well is already marked for final review")
        if not well.sections_for_scope(data.scope):
            raise HTTPException(status_code=409, detail="Save at least one section and phase before marking the scope for final review")
        well.set_scope_value(data.scope, "config_status", "final_review")
        label = "marked for final review"
    elif action == "complete":
        if well.scope_value(data.scope, "status") != "active":
            raise HTTPException(status_code=409, detail="The well is already completed")
        if (
            well.scope_value(data.scope, "config_status") != "final_review"
            or not well.sections_for_scope(data.scope)
        ):
            raise HTTPException(status_code=409, detail="Mark the scope for final review before marking it completed")
        well.set_scope_value(data.scope, "status", "completed")
        label = "completed"
    else:
        if well.scope_value(data.scope, "status") != "completed":
            raise HTTPException(status_code=409, detail="Only a completed well can be reactivated")
        well.set_scope_value(data.scope, "status", "active")
        well.set_scope_value(data.scope, "config_status", "configured")
        label = "reactivated"
    _record_audit(
        db, user=user, action="update", entity_type="well", record_id=well.id,
        entity_label=well.well_code,
        summary=f"Changed well {well.well_code} {data.scope} scope to {label}: {data.remarks.strip()}",
        request=request,
    )
    _commit(db)
    db.refresh(well)
    return _well_out_for(db, user.organization_id, well)


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
    scope: Literal["drilling", "completion"] | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
) -> list[WellSubActivityOut]:
    well = _well_for_sub_activity(db, well_id, user.organization_id, scope=scope)
    statement = (
        select(WellSubActivity)
        .options(joinedload(WellSubActivity.well).joinedload(Well.rig), joinedload(WellSubActivity.activity))
        .where(
            WellSubActivity.organization_id == user.organization_id,
            WellSubActivity.well_id == well_id,
            WellSubActivity.is_deleted.is_(False),
        )
    )
    if scope is not None:
        statement = statement.where(WellSubActivity.scope == scope)
    else:
        active_scopes = [item for item in ("drilling", "completion") if not well.scope_is_deleted(item)]
        statement = statement.where(WellSubActivity.scope.in_(active_scopes or [""]))
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
    scope: Literal["drilling", "completion"] | None = Query(default=None),
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
    if scope is not None:
        statement = statement.where(WellSubActivity.scope == scope)
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
    well = _well_for_sub_activity(db, data.well_id, user.organization_id, scope=data.scope)
    activity = _master_record_or_422(db, Activity, data.activity_id, user.organization_id, "Activity")
    classification = classify_activity(activity)
    responsible_party = (data.responsible_party or "").strip()
    if classification == "Planned":
        if not responsible_party or responsible_party in ("-", "N/A", "n/a", "None"):
            responsible_party = "Not Applicable"
    else:
        if not responsible_party or responsible_party in ("Not Applicable", "N/A", "n/a", "None", "-"):
            raise HTTPException(
                status_code=422,
                detail=f"Responsible party / company is required for {classification} sub activities",
            )
    data.responsible_party = responsible_party
    existing = db.scalar(
        select(WellSubActivity).where(
            WellSubActivity.organization_id == user.organization_id,
            WellSubActivity.well_id == well.id,
            WellSubActivity.scope == data.scope,
            WellSubActivity.sub_activity_code == data.sub_activity_code,
        )
    )
    if existing is not None:
        if not existing.is_deleted:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Sub activity code '{data.sub_activity_code}' already exists for well "
                    f"{well.well_code} ({_scope_label(data.scope)})"
                ),
            )
        existing.sub_activity_name = data.sub_activity_name
        existing.activity_id = activity.id
        existing.responsible_party = data.responsible_party
        existing.description = data.description
        existing.is_deleted = False
        existing.deleted_at = None
        _record_audit(
            db, user=user, action="restore", entity_type="well_sub_activity", record_id=existing.id,
            entity_label=f"{well.well_code} ({_scope_label(data.scope)}) / {existing.sub_activity_code}",
            summary=(
                f"Restored and updated sub activity {existing.sub_activity_code} for well "
                f"{well.well_code} ({_scope_label(data.scope)}) on create"
            ),
            request=request,
        )
        _commit(db)
        return _sub_activity_out(_sub_activity_or_404(db, existing.id, user.organization_id))
    record = WellSubActivity(
        organization_id=user.organization_id,
        well_id=well.id,
        scope=data.scope,
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
        entity_label=f"{well.well_code} ({_scope_label(data.scope)}) / {record.sub_activity_code}",
        summary=(
            f"Created sub activity {record.sub_activity_code} — {record.sub_activity_name} "
            f"under Activity {activity.activity_code} for well {well.well_code} ({_scope_label(data.scope)})"
        ),
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
    record = _sub_activity_or_404(
        db, record_id, user.organization_id, well_id=well_id, include_deleted=False
    )
    well = _well_for_sub_activity(db, well_id, user.organization_id, scope=record.scope)
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field, value in payload.items():
        if value is None or getattr(record, field) == value:
            continue
        if field == "activity_id":
            _master_record_or_422(db, Activity, value, user.organization_id, "Activity")
        elif field == "responsible_party":
            target_act_id = payload.get("activity_id") or record.activity_id
            target_act = _master_record_or_422(db, Activity, target_act_id, user.organization_id, "Activity")
            classification = classify_activity(target_act)
            party_str = str(value or "").strip()
            if classification == "Planned":
                if not party_str or party_str in ("-", "N/A", "n/a", "None"):
                    party_str = "Not Applicable"
            else:
                if not party_str or party_str in ("Not Applicable", "N/A", "n/a", "None", "-"):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Responsible party / company is required for {classification} sub activities",
                    )
            value = party_str
        elif field == "sub_activity_code":
            duplicate = db.scalar(
                select(WellSubActivity).where(
                    WellSubActivity.organization_id == user.organization_id,
                    WellSubActivity.well_id == well.id,
                    WellSubActivity.scope == record.scope,
                    WellSubActivity.sub_activity_code == value,
                    WellSubActivity.id != record.id,
                )
            )
            if duplicate:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Sub activity code '{value}' is already retained for well "
                        f"{well.well_code} ({_scope_label(record.scope)}); restore or permanently delete it first"
                    ),
                )
        setattr(record, field, value)
        changed.append(field)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="well_sub_activity", record_id=record.id,
            entity_label=f"{well.well_code} ({_scope_label(record.scope)}) / {record.sub_activity_code}",
            summary=(
                f"Updated sub activity {record.sub_activity_code} for well "
                f"{well.well_code} ({_scope_label(record.scope)}): {', '.join(changed)}"
            ),
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
    record = _sub_activity_or_404(
        db, record_id, user.organization_id, well_id=well_id, include_deleted=False
    )
    well = _well_for_sub_activity(db, well_id, user.organization_id, scope=record.scope)
    costing_lines = _daily_cost_line_counts_by_sub_activity(
        db, user.organization_id, [record.id], active_entries_only=True
    ).get(record.id, 0)
    if costing_lines:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Sub activity {record.sub_activity_code} is used by {costing_lines} line(s) on active daily-cost sheets. "
                "Delete or complete those daily-cost sheets before moving the sub activity to Deleted Entries."
            ),
        )
    record.is_deleted = True
    record.deleted_at = _now()
    _record_audit(
        db, user=user, action="soft_delete", entity_type="well_sub_activity", record_id=record.id,
        entity_label=f"{well.well_code} ({_scope_label(record.scope)}) / {record.sub_activity_code}",
        summary=(
            f"Moved sub activity {record.sub_activity_code} for well "
            f"{well.well_code} ({_scope_label(record.scope)}) to Deleted Entries"
        ),
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
    well = _well_for_sub_activity(db, record.well_id, user.organization_id, scope=record.scope)
    _master_record_or_422(db, Activity, record.activity_id, user.organization_id, "Activity")
    record.is_deleted = False
    record.deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="well_sub_activity", record_id=record.id,
        entity_label=f"{well.well_code} ({_scope_label(record.scope)}) / {record.sub_activity_code}",
        summary=f"Restored sub activity {record.sub_activity_code} for well {well.well_code} ({_scope_label(record.scope)})",
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
    costing_lines = _daily_cost_line_counts_by_sub_activity(
        db, user.organization_id, [record.id], active_entries_only=False
    ).get(record.id, 0)
    if costing_lines:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Sub activity {record.sub_activity_code} is retained by {costing_lines} daily-cost line(s). "
                "Permanently delete the linked daily-cost sheets first; submitted and deleted sheets keep their line history."
            ),
        )
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
    scope: Literal["drilling", "completion"] | None = Query(default=None),
) -> RigWellBulkActionResponse:
    well = _well_for_sub_activity(db, well_id, user.organization_id, scope=scope)
    statement = select(WellSubActivity).where(
        WellSubActivity.organization_id == user.organization_id,
        WellSubActivity.well_id == well.id,
        WellSubActivity.id.in_(data.ids),
        WellSubActivity.is_deleted.is_(False),
    )
    if scope is not None:
        statement = statement.where(WellSubActivity.scope == scope)
    records = list(db.scalars(statement).all())
    if len(data.ids) != len(set(data.ids)):
        raise HTTPException(status_code=422, detail="Duplicate record IDs are not allowed")
    if len(records) != len(data.ids):
        raise HTTPException(status_code=404, detail="One or more sub activities do not belong to the selected well scope")
    costing_line_counts = _daily_cost_line_counts_by_sub_activity(
        db, user.organization_id, [record.id for record in records], active_entries_only=True
    )
    blocked = [(record, costing_line_counts.get(record.id, 0)) for record in records if costing_line_counts.get(record.id)]
    if blocked:
        record, count = blocked[0]
        raise HTTPException(
            status_code=409,
            detail=(
                f"Sub activity {record.sub_activity_code} is used by {count} line(s) on active daily-cost sheets. "
                "Delete or complete those sheets before moving selected sub activities to Deleted Entries."
            ),
        )
    deleted_at = _now()
    for record in records:
        record.is_deleted = True
        record.deleted_at = deleted_at
        _record_audit(
            db, user=user, action="soft_delete", entity_type="well_sub_activity", record_id=record.id,
            entity_label=f"{well.well_code} ({_scope_label(record.scope)}) / {record.sub_activity_code}",
            summary=(
                f"Moved sub activity {record.sub_activity_code} for well "
                f"{well.well_code} ({_scope_label(record.scope)}) to Deleted Entries (bulk action)"
            ),
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
    scope: Literal["drilling", "completion"] = Query(default="drilling"),
) -> RigWellImportResponse:
    well = _well_for_sub_activity(db, well_id, user.organization_id, scope=scope)
    imported = 0
    errors: list[str] = []
    seen_codes: set[tuple[str, str]] = set()
    for row_number, row in enumerate(data.rows, start=1):
        code = _string(_row_value(row, "sub_activity_code", "code", "sub_activity")).upper()
        name = _string(_row_value(row, "sub_activity_name", "name"))
        responsible_party = _string(_row_value(row, "responsible_party", "responsible", "company"))
        description = _string(_row_value(row, "description", "remarks", "remark"))
        activity_ref = _row_value(row, "activity", "activity_code", "activity_name")
        raw_scope = _string(_row_value(row, "scope", "well_scope", "configuration_scope")).lower()
        row_scope = raw_scope if raw_scope else scope
        if row_scope not in ("drilling", "completion"):
            errors.append(
                f"Row {row_number} ({code or '—'}): scope must be 'drilling' or 'completion'"
            )
            continue
        if well.scope_is_deleted(row_scope):
            errors.append(
                f"Row {row_number} ({code or '—'}): {_scope_label(row_scope)} scope on well {well.well_code} is deleted"
            )
            continue
        try:
            payload = WellSubActivityCreate.model_validate(
                {
                    "well_id": well.id,
                    "scope": row_scope,
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
        key = (payload.scope, payload.sub_activity_code)
        if key in seen_codes:
            errors.append(
                f"Row {row_number} ({payload.sub_activity_code}): duplicate sub_activity_code in {_scope_label(payload.scope)} import"
            )
            continue
        seen_codes.add(key)
        activity = _activity_from_import(db, activity_ref, user.organization_id)
        if activity is None:
            errors.append(f"Row {row_number} ({payload.sub_activity_code}): Activity '{_string(activity_ref) or '—'}' is missing, ambiguous, or inactive in Master Data")
            continue
        classification = classify_activity(activity)
        if classification == "Planned":
            if not payload.responsible_party or payload.responsible_party in ("-", "N/A", "n/a", "None"):
                payload.responsible_party = "Not Applicable"
        else:
            if not payload.responsible_party or payload.responsible_party in ("Not Applicable", "N/A", "n/a", "None", "-"):
                errors.append(f"Row {row_number} ({payload.sub_activity_code}): Responsible party is required for {classification} sub activity")
                continue
        existing = db.scalar(
            select(WellSubActivity).where(
                WellSubActivity.organization_id == user.organization_id,
                WellSubActivity.well_id == well.id,
                WellSubActivity.scope == payload.scope,
                WellSubActivity.sub_activity_code == payload.sub_activity_code,
            )
        )
        if existing is None:
            existing = WellSubActivity(
                organization_id=user.organization_id,
                well_id=well.id,
                scope=payload.scope,
                sub_activity_code=payload.sub_activity_code,
                sub_activity_name=payload.sub_activity_name,
                activity_id=activity.id,
                responsible_party=payload.responsible_party,
                description=payload.description,
            )
            db.add(existing)
            action = "create"
            summary = f"Created sub activity {payload.sub_activity_code} for well {well.well_code} ({_scope_label(payload.scope)}) from import"
        else:
            action = "restore" if existing.is_deleted else "update"
            existing.sub_activity_name = payload.sub_activity_name
            existing.activity_id = activity.id
            existing.responsible_party = payload.responsible_party
            existing.description = payload.description
            existing.is_deleted = False
            existing.deleted_at = None
            summary = (
                f"{'Restored and updated' if action == 'restore' else 'Updated'} sub activity "
                f"{payload.sub_activity_code} for well {well.well_code} ({_scope_label(payload.scope)}) from import"
            )
        db.flush()
        _record_audit(
            db, user=user, action=action, entity_type="well_sub_activity", record_id=existing.id,
            entity_label=f"{well.well_code} ({_scope_label(payload.scope)}) / {payload.sub_activity_code}",
            summary=summary, request=request,
        )
        imported += 1
    _record_audit(
        db, user=user, action="import", entity_type="well_sub_activity", record_id=None,
        entity_label=f"Well {well.well_code} ({_scope_label(scope)})",
        summary=f"Imported {imported} sub activities for well {well.well_code} ({_scope_label(scope)}) with {len(errors)} row error(s)",
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
    blocks = db.scalars(
        select(Block).where(Block.organization_id == organization_id, Block.is_deleted.is_(True))
    ).all()
    for block in blocks:
        output.append(
            DeletedRigWellRecord(
                id=block.id,
                entity_type="block",
                code=block.block_code,
                name=block.block_name,
                parent_label="Block register",
                deleted_at=block.deleted_at or block.updated_at,
                created_at=block.created_at,
            )
        )
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
        .where(
            Well.organization_id == organization_id,
            or_(
                Well.is_deleted.is_(True),
                Well.drilling_is_deleted.is_(True),
                Well.completion_is_deleted.is_(True),
            ),
        )
    ).all()
    for well in wells:
        rig_label = f"{well.rig.rig_code} — {well.rig.rig_name}" if well.rig else "Unknown rig"
        if well.drilling_is_deleted or well.completion_is_deleted:
            for item_scope in ("drilling", "completion"):
                if well.scope_is_deleted(item_scope) and not well.scope_is_purged(item_scope):
                    output.append(
                        DeletedRigWellRecord(
                            id=well.id,
                            entity_type="well",
                            scope=item_scope,
                            code=well.well_code,
                            name=f"{well.well_name} — {_scope_label(item_scope)}",
                            parent_label=f"{rig_label} · {_scope_label(item_scope)} scope",
                            deleted_at=well.scope_deleted_at(item_scope) or well.deleted_at or well.updated_at,
                            created_at=well.created_at,
                        )
                    )
        elif well.is_deleted:
            output.append(
                DeletedRigWellRecord(
                    id=well.id,
                    entity_type="well",
                    scope=None,
                    code=well.well_code,
                    name=well.well_name,
                    parent_label=rig_label,
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
        item_scope = item.scope if item.scope in ("drilling", "completion") else "drilling"
        parent = f"{parent} · {_scope_label(item_scope)}"
        output.append(
            DeletedRigWellRecord(
                id=item.id,
                entity_type="well_sub_activity",
                scope=item_scope,
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
    keys = [(item.entity_type, item.id, item.scope if item.entity_type == "well" else None) for item in selections]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Duplicate entity and record selections are not allowed")
    grouped: dict[str, list[Any]] = defaultdict(list)
    for item in selections:
        grouped[item.entity_type].append(item)
    result: dict[str, list[Any]] = {}
    for entity_type in ("block", "rig", "well_sub_activity"):
        items = grouped.get(entity_type, [])
        if not items:
            continue
        ids = [item.id for item in items]
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

    well_items = grouped.get("well", [])
    if well_items:
        well_ids = list({item.id for item in well_items})
        wells_by_id = {
            well.id: well
            for well in db.scalars(
                select(Well)
                .options(
                    joinedload(Well.rig),
                    selectinload(Well.sections).selectinload(WellSection.phases),
                    selectinload(Well.completion_sections).selectinload(WellSection.phases),
                )
                .where(
                    Well.organization_id == organization_id,
                    Well.id.in_(well_ids),
                )
            ).all()
        }
        if len(wells_by_id) != len(well_ids):
            raise HTTPException(status_code=404, detail="One or more selected records do not belong to this workspace")
        resolved_wells: list[tuple[Well, str | None]] = []
        for item in well_items:
            well = wells_by_id[item.id]
            if item.scope is not None:
                if not well.scope_is_deleted(item.scope) or well.scope_is_purged(item.scope):
                    raise HTTPException(
                        status_code=409,
                        detail="Only records already in Deleted Entries can be changed here",
                    )
            elif not well.is_deleted:
                raise HTTPException(
                    status_code=409,
                    detail="Only records already in Deleted Entries can be changed here",
                )
            resolved_wells.append((well, item.scope))
        result["well"] = resolved_wells
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
    selected_whole_wells = {well.id for well, item_scope in records.get("well", []) if item_scope is None}
    selected_well_scopes = {
        (well.id, item_scope) for well, item_scope in records.get("well", []) if item_scope is not None
    }

    for well, _item_scope in records.get("well", []):
        rig = _rig_or_404(db, well.rig_id, user.organization_id)
        if rig.is_deleted and rig.id not in selected_rigs:
            raise HTTPException(status_code=409, detail=f"Restore rig {rig.rig_code} before restoring well {well.well_code}")
    for item in records.get("well_sub_activity", []):
        well = _well_or_404(db, item.well_id, user.organization_id)
        item_scope = item.scope if item.scope in ("drilling", "completion") else "drilling"
        if (
            well.scope_is_deleted(item_scope)
            and well.id not in selected_whole_wells
            and (well.id, item_scope) not in selected_well_scopes
        ):
            raise HTTPException(
                status_code=409,
                detail=f"Restore well {well.well_code} ({_scope_label(item_scope)}) before restoring sub activity {item.sub_activity_code}",
            )
        if well.rig.is_deleted and well.rig.id not in selected_rigs:
            raise HTTPException(status_code=409, detail=f"Restore rig {well.rig.rig_code} before restoring sub activity {item.sub_activity_code}")
        _master_record_or_422(db, Activity, item.activity_id, user.organization_id, "Activity")

    restored_count = 0
    for entity_type in ("block", "rig", "well", "well_sub_activity"):
        if entity_type == "well":
            for well, item_scope in records.get("well", []):
                if item_scope is not None:
                    other = _other_scope(item_scope)
                    if well.is_deleted and not well.drilling_is_deleted and not well.completion_is_deleted:
                        if other == "completion":
                            well.completion_is_deleted = True
                            well.completion_deleted_at = well.deleted_at or _now()
                        else:
                            well.drilling_is_deleted = True
                            well.drilling_deleted_at = well.deleted_at or _now()
                    if item_scope == "completion":
                        well.completion_is_deleted = False
                        well.completion_deleted_at = None
                        well.completion_purged = False
                    else:
                        well.drilling_is_deleted = False
                        well.drilling_deleted_at = None
                        well.drilling_purged = False
                    well.sync_deleted_from_scopes()
                    label = f"{well.well_code} ({_scope_label(item_scope)})"
                    summary = f"Restored {_scope_label(item_scope)} scope of well {well.well_code} (bulk action)"
                else:
                    well.is_deleted = False
                    well.deleted_at = None
                    if not well.drilling_purged:
                        well.drilling_is_deleted = False
                        well.drilling_deleted_at = None
                    if not well.completion_purged:
                        well.completion_is_deleted = False
                        well.completion_deleted_at = None
                    label = well.well_code
                    summary = f"Restored well {well.well_code} (bulk action)"
                _record_audit(
                    db, user=user, action="restore", entity_type="well", record_id=well.id,
                    entity_label=label, summary=summary, request=request,
                )
                restored_count += 1
            continue
        for record in records.get(entity_type, []):
            record.is_deleted = False
            record.deleted_at = None
            if entity_type == "block":
                label = record.block_code
                summary = f"Restored block {record.block_code} (bulk action)"
            elif entity_type == "rig":
                label = record.rig_code
                summary = f"Restored rig {record.rig_code} (bulk action)"
            else:
                label = f"{record.well.well_code} ({_scope_label(record.scope)}) / {record.sub_activity_code}"
                summary = (
                    f"Restored sub activity {record.sub_activity_code} for well "
                    f"{record.well.well_code} ({_scope_label(record.scope)}) (bulk action)"
                )
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
    selected_sub_activities = _selected_ids(records, "well_sub_activity")
    selected_rig_ids = [record.id for record in records.get("rig", [])]
    well_entries: list[tuple[Well, str | None]] = records.get("well", [])

    scopes_being_purged_by_well: dict[str, set[str]] = defaultdict(set)
    whole_wells_being_purged: set[str] = set()
    wells_seen: dict[str, Well] = {}
    for well, item_scope in well_entries:
        wells_seen[well.id] = well
        if item_scope is None:
            whole_wells_being_purged.add(well.id)
        else:
            scopes_being_purged_by_well[well.id].add(item_scope)

    completely_purged_well_ids: set[str] = set(whole_wells_being_purged)
    for well_id, scopes_to_purge in scopes_being_purged_by_well.items():
        well = wells_seen[well_id]
        drilling_gone = "drilling" in scopes_to_purge or well.drilling_purged
        completion_gone = "completion" in scopes_to_purge or well.completion_purged
        if drilling_gone and completion_gone:
            completely_purged_well_ids.add(well_id)

    for block_record in records.get("block", []):
        remaining_block_wells = list(
            db.scalars(
                select(Well.id).where(
                    Well.organization_id == user.organization_id,
                    Well.block_id == block_record.id,
                )
            ).all()
        )
        unpurged_block_wells = [wid for wid in remaining_block_wells if wid not in completely_purged_well_ids]
        if unpurged_block_wells:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Block {block_record.block_code} retains {len(unpurged_block_wells)} well record(s). "
                    "Permanently delete those wells first."
                ),
            )

    rig_afe_counts = _counts_by_parent(db, Afe, Afe.rig_id, user.organization_id, selected_rig_ids)
    rig_daily_counts = _counts_by_parent(
        db, DailyCostEntry, DailyCostEntry.rig_id, user.organization_id, selected_rig_ids
    )
    rig_mud_counts = _counts_by_parent(
        db, MudCostEntry, MudCostEntry.rig_id, user.organization_id, selected_rig_ids
    )
    whole_well_ids = list(whole_wells_being_purged)
    well_afe_counts = _counts_by_parent(db, Afe, Afe.well_id, user.organization_id, whole_well_ids)
    well_daily_counts = _counts_by_parent(
        db, DailyCostEntry, DailyCostEntry.well_id, user.organization_id, whole_well_ids
    )
    well_mud_counts = _counts_by_parent(
        db, MudCostEntry, MudCostEntry.well_id, user.organization_id, whole_well_ids
    )
    sub_activity_line_counts = _daily_cost_line_counts_by_sub_activity(
        db,
        user.organization_id,
        [record.id for record in records.get("well_sub_activity", [])],
        active_entries_only=False,
    )
    blocked_sub_activities = [
        (record, sub_activity_line_counts.get(record.id, 0))
        for record in records.get("well_sub_activity", [])
        if sub_activity_line_counts.get(record.id)
    ]
    if blocked_sub_activities:
        record, count = blocked_sub_activities[0]
        raise HTTPException(
            status_code=409,
            detail=(
                f"Sub activity {record.sub_activity_code} is retained by {count} daily-cost line(s). "
                "Permanently delete the linked daily-cost sheets first; historical line records are retained "
                "until their sheet is purged."
            ),
        )

    for rig in records.get("rig", []):
        if rig_afe_counts.get(rig.id) or rig_daily_counts.get(rig.id) or rig_mud_counts.get(rig.id):
            dependencies = []
            if rig_afe_counts.get(rig.id):
                dependencies.append(f"{rig_afe_counts[rig.id]} AFE record(s)")
            if rig_daily_counts.get(rig.id):
                dependencies.append(f"{rig_daily_counts[rig.id]} daily-cost sheet(s)")
            if rig_mud_counts.get(rig.id):
                dependencies.append(f"{rig_mud_counts[rig.id]} Mud Cost entry/entries")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Rig {rig.rig_code} retains {', '.join(dependencies)}. Permanently delete those records "
                    "in AFE Management or Daily Cost Management first."
                ),
            )
        remaining_wells = list(
            db.scalars(
                select(Well.id).where(
                    Well.organization_id == user.organization_id,
                    Well.rig_id == rig.id,
                )
            ).all()
        )
        if any(well_id not in completely_purged_well_ids for well_id in remaining_wells):
            raise HTTPException(status_code=409, detail=f"Permanently delete every well under rig {rig.rig_code} first")
        assert_purgeable(
            db, user.organization_id, rig,
            entity_label=f"rig {rig.rig_code}",
            ignore=(WELL_LABEL,),
            next_step=(
                "Permanently delete the dependent fuel, LIH and SOW adjustment records from their own module first."
            ),
        )
    for well, item_scope in well_entries:
        if item_scope is not None:
            dependencies = _scope_retained_dependencies(
                db,
                user.organization_id,
                well,
                item_scope,
                ignore_sub_activity_ids=selected_sub_activities,
            )
            if dependencies:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Well {well.well_code} ({_scope_label(item_scope)}) retains {', '.join(dependencies)}. "
                        "Permanently delete the linked records for this scope in their own Deleted Entries first."
                    ),
                )
            continue
        if (
            well_afe_counts.get(well.id)
            or well_daily_counts.get(well.id)
            or well_mud_counts.get(well.id)
        ):
            dependencies = []
            if well_afe_counts.get(well.id):
                dependencies.append(f"{well_afe_counts[well.id]} AFE record(s)")
            if well_daily_counts.get(well.id):
                dependencies.append(f"{well_daily_counts[well.id]} daily-cost sheet(s)")
            if well_mud_counts.get(well.id):
                dependencies.append(f"{well_mud_counts[well.id]} Mud Cost entry/entries")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Well {well.well_code} retains {', '.join(dependencies)}. Permanently delete the linked "
                    "AFEs, daily-cost sheets and Mud Cost entries in their own Deleted Entries first."
                ),
            )
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
        assert_purgeable(
            db, user.organization_id, well,
            entity_label=f"well {well.well_code}",
            ignore=(SUB_ACTIVITY_LABEL, AFE_LABEL, DAILY_SHEET_LABEL, MUD_COST_LABEL),
            next_step=(
                "Permanently delete the dependent LIH cost entries and SOW/well-plan revisions from their own "
                "module first."
            ),
        )

    purged_count = 0
    # Child rows are flushed before their parents to respect RESTRICT constraints.
    for record in records.get("well_sub_activity", []):
        _record_audit(
            db, user=user, action="permanent_delete", entity_type="well_sub_activity", record_id=record.id,
            entity_label=f"{record.well.well_code} ({_scope_label(record.scope)}) / {record.sub_activity_code}",
            summary=(
                f"Permanently deleted sub activity {record.sub_activity_code} for well "
                f"{record.well.well_code} ({_scope_label(record.scope)}) (bulk action)"
            ),
            request=request,
        )
        db.delete(record)
        purged_count += 1
    db.flush()

    snapshot_notes: list[str] = []
    if whole_well_ids:
        removed_snapshots = purge_owned_snapshots(db, user.organization_id, well_ids=whole_well_ids)
        whole_note = snapshot_summary(removed_snapshots)
        if whole_note:
            snapshot_notes.append(whole_note)

    for well, item_scope in well_entries:
        if item_scope is not None:
            well_code = well.well_code
            well_id_copy = well.id
            scoped_note = _purge_well_scope_data(db, user.organization_id, well, item_scope)
            if scoped_note:
                snapshot_notes.append(scoped_note)
            _record_audit(
                db, user=user, action="permanent_delete", entity_type="well", record_id=well_id_copy,
                entity_label=f"{well_code} ({_scope_label(item_scope)})",
                summary=f"Permanently deleted {_scope_label(item_scope)} scope of well {well_code} (bulk action)",
                request=request,
            )
            purged_count += 1
        else:
            _record_audit(
                db, user=user, action="permanent_delete", entity_type="well", record_id=well.id,
                entity_label=well.well_code,
                summary=f"Permanently deleted well {well.well_code} (bulk action)",
                request=request,
            )
            db.delete(well)
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
    db.flush()
    for record in records.get("block", []):
        _record_audit(
            db, user=user, action="permanent_delete", entity_type="block", record_id=record.id,
            entity_label=record.block_code,
            summary=f"Permanently deleted block {record.block_code} (bulk action)",
            request=request,
        )
        db.delete(record)
        purged_count += 1
    snapshot_note = "; ".join(snapshot_notes)
    _record_audit(
        db, user=user, action="permanent_delete", entity_type="rig_well_deleted", record_id=None,
        entity_label="Deleted Entries",
        summary=(
            f"Permanently deleted {purged_count} Rig & Well Management record(s)"
            + (f", together with {snapshot_note}" if snapshot_note else "")
        ),
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
        "blocks": "Blocks",
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
