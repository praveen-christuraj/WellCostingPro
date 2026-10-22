"""AFE SOW adjustments, well plan adjustments and daily cost amendments.

All helpers are additive: original AFE estimates, well configurations and
daily baselines are never rewritten. When no *approved* adjustment exists,
callers fall back to the original totals and planned days.

Adjustments are not simple aggregate edits. Each revision is entered through
the same modules as the record it revises — the section/phase grid for a well
plan, the service/consumable/tangible estimate lines for an AFE — and stored
as two-sided line rows: a ``before`` snapshot of the entered values and an
``after`` side holding the revised entries, linked by ``pair_key`` so every
revised line reads against the value it replaces. Planned days, section counts
and cost-group totals are derived from those lines server-side.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import afe_costing as engine
from app.models import (
    Afe,
    AuditLog,
    DailyCostEntry,
    HoleSection,
    Phase,
    Rig,
    Well,
    WellSection,
)
from app.models.entities import User
from app.models.sow_adjustment import (
    AfeSowAdjustment,
    AfeSowConsumableLine,
    AfeSowExchangeRate,
    AfeSowServiceCharge,
    AfeSowServiceLine,
    AfeSowServiceRate,
    AfeSowServiceSectionRate,
    AfeSowTangibleLine,
    DailyCostAmendment,
    WellPlanAdjustment,
    WellPlanAdjustmentPhase,
    WellPlanAdjustmentSection,
)
from app.schemas.afe import (
    ConsumableLineIn,
    EstimateIn,
    ServiceLineIn,
    TangibleLineIn,
)
from app.schemas.sow_adjustment import (
    AfeSowAdjustmentCreate,
    AfeSowAdjustmentOut,
    AfeSowAdjustmentPreviewOut,
    AfeSowAdjustmentUpdate,
    AfeSowBundleOut,
    DailyCostAmendmentOut,
    PlanSectionIn,
    PlanSectionOut,
    PlanPhaseOut,
    SowApprovalIn,
    WellAdjustedSummary,
    WellPlanAdjustmentCreate,
    WellPlanAdjustmentOut,
    WellPlanAdjustmentUpdate,
)
from app.services import afe as afe_service
from app.services import audit

# Reopening a submitted sheet whose cost date is older than this needs the
# dedicated daily-cost:amend capability in addition to daily-cost:reopen.
AMENDMENT_THRESHOLD_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _actor_name(user: User) -> str:
    return user.full_name or user.email


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This adjustment conflicts with an existing record. Refresh and retry.",
        ) from error


def _record_audit(
    db: Session,
    *,
    user: User,
    action: str,
    entity_type: str,
    record_id: str | None,
    entity_label: str,
    summary: str,
    request: Request | None,
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


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _afe_or_404(db: Session, afe_id: str, organization_id: str) -> Afe:
    afe = db.scalar(
        select(Afe).where(Afe.id == afe_id, Afe.organization_id == organization_id)
    )
    if afe is None:
        raise HTTPException(status_code=404, detail="AFE not found in this workspace")
    if afe.is_deleted:
        raise HTTPException(status_code=409, detail="Restore this AFE before recording SOW adjustments")
    return afe


def _well_or_404(db: Session, well_id: str, organization_id: str) -> Well:
    well = db.scalars(
        select(Well)
        .options(
            joinedload(Well.rig),
            selectinload(Well.sections).selectinload(WellSection.phases),
        )
        .where(Well.id == well_id, Well.organization_id == organization_id)
    ).unique().first()
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    return well


def _well_scope_days(well: Well, scope: str) -> tuple[Decimal, int]:
    sections = well.sections_for_scope(scope)
    total = sum((phase.days for section in sections for phase in section.phases), Decimal("0"))
    return Decimal(total), len(sections)


def _original_totals(db: Session, organization_id: str, afe: Afe) -> tuple[Decimal | None, ...]:
    """Snapshot the saved estimate totals; nulls mean pending conversion."""
    try:
        estimate = afe_service.get_estimate(db, organization_id, afe.id)
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - malformed legacy estimates surface as validation
        raise HTTPException(
            status_code=422,
            detail=f"The saved estimate for {afe.afe_code} cannot be read. Open the AFE and resave its estimate first.",
        ) from error
    summary = estimate.summary
    services = _money(summary.services_total)
    consumables = _money(summary.consumables_total)
    tangibles = _money(summary.tangibles_total)
    total = _money(summary.total)
    currency = summary.currency.standard_currency or ""
    converted = summary.currency.converted
    if not converted:
        return None, None, None, None, currency
    return services, consumables, tangibles, total, currency


# ---------------------------------------------------------------------------
# Pair keys: link each revised (after) line to the entered (before) value
# ---------------------------------------------------------------------------


def _assign_pair_keys(
    payloads: Sequence[Any], prefix: str, before_keys: set[str], kind: str
) -> list[str]:
    """Pair keys for the after rows, in payload order.

    Rows carrying a ``pair_key`` keep it (linking to the before row they
    replace). Keyless rows fall back to the before key at the same position
    when that one is still unclaimed, else they are recorded as additions.
    """
    keys: list[str] = []
    used: set[str] = set()
    any_explicit = any((getattr(payload, "pair_key", "") or "").strip() for payload in payloads)
    for index, payload in enumerate(payloads):
        incoming = (getattr(payload, "pair_key", "") or "").strip()
        if incoming:
            key = incoming
        elif any_explicit:
            # Mixed payloads: keyless rows are additions, never positional pairs.
            key = f"new-{prefix}{index}"
        else:
            key = f"{prefix}{index}" if f"{prefix}{index}" in before_keys and f"{prefix}{index}" not in used else f"new-{prefix}{index}"
        if key in used:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate {kind} line key '{key}' in the revised entries",
            )
        used.add(key)
        keys.append(key)
    return keys


# ---------------------------------------------------------------------------
# Well plan adjustments — the well-configuration grid, entered as a revision
# ---------------------------------------------------------------------------


def _validate_plan_grid(db: Session, organization_id: str, sections: Sequence[PlanSectionIn]) -> None:
    """Mirror the well-configuration save rules for the revised grid."""

    def record_or_422(model: Any, record_id: str, label: str) -> Any:
        record = db.scalar(
            select(model).where(model.id == record_id, model.organization_id == organization_id)
        )
        if record is None:
            raise HTTPException(status_code=422, detail=f"{label} not found in this workspace")
        return record

    seen_sections: set[str] = set()
    previous_to_depth: Decimal | None = None
    for section_index, section_input in enumerate(sections, start=1):
        section = record_or_422(HoleSection, section_input.hole_section_id, "Hole Section")
        if section.id in seen_sections:
            raise HTTPException(status_code=422, detail=f"Hole Section '{section.section_code}' is duplicated")
        seen_sections.add(section.id)
        if Decimal(section_input.from_depth) > Decimal(section_input.to_depth):
            raise HTTPException(status_code=422, detail=f"Section {section_index}: from depth must not exceed to depth")
        if previous_to_depth is not None and Decimal(section_input.from_depth) < previous_to_depth:
            raise HTTPException(
                status_code=422,
                detail=f"Section {section_index}: from depth must be at least the previous section's to depth ({previous_to_depth})",
            )
        previous_to_depth = Decimal(section_input.to_depth)
        seen_phases: set[str] = set()
        for phase_input in section_input.phases:
            phase = record_or_422(Phase, phase_input.phase_id, "Phase")
            if phase.id in seen_phases:
                raise HTTPException(
                    status_code=422,
                    detail=f"Section '{section.section_code}': phase '{phase.phase_code}' is duplicated",
                )
            seen_phases.add(phase.id)


def _before_plan_rows(
    well: Well, scope: str, organization_id: str, adjustment_id: str
) -> list[WellPlanAdjustmentSection]:
    rows: list[WellPlanAdjustmentSection] = []
    sections = sorted(well.sections_for_scope(scope), key=lambda row: row.sort_order)
    for section_index, section in enumerate(sections):
        row = WellPlanAdjustmentSection(
            organization_id=organization_id,
            adjustment_id=adjustment_id,
            plan_side="before",
            pair_key=f"s{section_index}",
            hole_section_id=section.hole_section_id,
            from_depth=section.from_depth,
            to_depth=section.to_depth,
            remarks=section.remarks or "",
            sort_order=section_index,
        )
        row.phases = [
            WellPlanAdjustmentPhase(
                organization_id=organization_id,
                adjustment_id=adjustment_id,
                plan_side="before",
                pair_key=f"p{section_index}-{phase_index}",
                phase_id=phase.phase_id,
                days=phase.days,
                remarks=phase.remarks or "",
                sort_order=phase_index,
            )
            for phase_index, phase in enumerate(sorted(section.phases, key=lambda row: row.sort_order))
        ]
        rows.append(row)
    return rows


def _after_plan_rows(
    sections: Sequence[PlanSectionIn],
    before_rows: Sequence[WellPlanAdjustmentSection],
    organization_id: str,
    adjustment_id: str,
) -> list[WellPlanAdjustmentSection]:
    before_section_keys = {row.pair_key for row in before_rows}
    before_phase_keys = {
        phase.pair_key for row in before_rows for phase in row.phases
    }
    section_keys = _assign_pair_keys(sections, "s", before_section_keys, "section")
    rows: list[WellPlanAdjustmentSection] = []
    for section_index, (payload, section_key) in enumerate(zip(sections, section_keys, strict=True)):
        phase_keys = _assign_pair_keys(payload.phases, f"p{section_index}-", before_phase_keys, "phase")
        row = WellPlanAdjustmentSection(
            organization_id=organization_id,
            adjustment_id=adjustment_id,
            plan_side="after",
            pair_key=section_key,
            hole_section_id=payload.hole_section_id,
            from_depth=Decimal(payload.from_depth),
            to_depth=Decimal(payload.to_depth),
            remarks=payload.remarks or "",
            sort_order=section_index,
        )
        row.phases = [
            WellPlanAdjustmentPhase(
                organization_id=organization_id,
                adjustment_id=adjustment_id,
                plan_side="after",
                pair_key=phase_key,
                phase_id=phase_payload.phase_id,
                days=Decimal(phase_payload.days),
                remarks=phase_payload.remarks or "",
                sort_order=phase_index,
            )
            for phase_index, (phase_payload, phase_key) in enumerate(
                zip(payload.phases, phase_keys, strict=True)
            )
        ]
        rows.append(row)
    return rows


def _plan_grid_totals(rows: Sequence[WellPlanAdjustmentSection]) -> tuple[Decimal, int]:
    days = sum(
        (Decimal(phase.days) for row in rows for phase in row.phases),
        Decimal("0"),
    )
    return Decimal(days), len(rows)


def _plan_labels(
    db: Session, organization_id: str, rows: Sequence[WellPlanAdjustmentSection]
) -> tuple[dict[str, HoleSection], dict[str, Phase]]:
    section_ids = {row.hole_section_id for row in rows}
    phase_ids = {phase.phase_id for row in rows for phase in row.phases}
    lookups = afe_service._load_lookups(
        db, organization_id, hole_section_ids=section_ids, phase_ids=phase_ids
    )
    return lookups.hole_sections, lookups.phases


def _plan_out(db: Session, row: WellPlanAdjustment, well: Well | None = None) -> WellPlanAdjustmentOut:
    before_rows = sorted(
        (section for section in row.sections if section.plan_side == "before"),
        key=lambda section: section.sort_order,
    )
    after_rows = sorted(
        (section for section in row.sections if section.plan_side == "after"),
        key=lambda section: section.sort_order,
    )
    section_labels, phase_labels = _plan_labels(db, row.organization_id, [*before_rows, *after_rows])
    before_sections = {section.pair_key: section for section in before_rows}
    after_sections = {section.pair_key: section for section in after_rows}
    before_phases = {phase.pair_key: phase for section in before_rows for phase in section.phases}
    after_phases = {phase.pair_key: phase for section in after_rows for phase in section.phases}

    def phase_signature(phase: WellPlanAdjustmentPhase, section_key: str) -> tuple[Any, ...]:
        return (phase.phase_id, Decimal(phase.days), phase.remarks or "", section_key)

    def section_signature(section: WellPlanAdjustmentSection) -> tuple[Any, ...]:
        return (
            section.hole_section_id,
            Decimal(section.from_depth),
            Decimal(section.to_depth),
            section.remarks or "",
        )

    def phase_change(
        phase: WellPlanAdjustmentPhase, section_key: str, side: str
    ) -> str:
        counterpart = before_phases if side == "after" else after_phases
        other = counterpart.get(phase.pair_key)
        if other is None:
            return "added" if side == "after" else "removed"
        other_section_key = next(
            (s.pair_key for s in (before_rows if side == "after" else after_rows) if other in s.phases),
            "",
        )
        if phase_signature(phase, section_key) != phase_signature(other, other_section_key):
            return "modified"
        return "kept"

    def build(side: str) -> list[PlanSectionOut]:
        rows = after_rows if side == "after" else before_rows
        counterparts = before_sections if side == "after" else after_sections
        result: list[PlanSectionOut] = []
        for section in rows:
            phase_change_any = False
            other = counterparts.get(section.pair_key)
            if other is None:
                change = "added" if side == "after" else "removed"
            else:
                change = "kept"
                if section_signature(section) != section_signature(other):
                    change = "modified"
            phase_rows: list[PlanPhaseOut] = []
            for phase in sorted(section.phases, key=lambda row: row.sort_order):
                change_phase = phase_change(phase, section.pair_key, side)
                if change_phase != "kept":
                    phase_change_any = True
                record = phase_labels.get(phase.phase_id)
                phase_rows.append(
                    PlanPhaseOut(
                        pair_key=phase.pair_key,
                        plan_side=side,
                        phase_id=phase.phase_id,
                        phase_code=record.phase_code if record else "",
                        phase_name=record.phase_name if record else "Removed phase",
                        days=Decimal(phase.days),
                        remarks=phase.remarks or "",
                        change=change_phase,
                    )
                )
            if change == "kept" and phase_change_any:
                change = "modified"
            hole = section_labels.get(section.hole_section_id)
            result.append(
                PlanSectionOut(
                    pair_key=section.pair_key,
                    plan_side=side,
                    hole_section_id=section.hole_section_id,
                    section_code=hole.section_code if hole else "",
                    section_name=hole.section_name if hole else "Removed section",
                    from_depth=Decimal(section.from_depth),
                    to_depth=Decimal(section.to_depth),
                    remarks=section.remarks or "",
                    total_days=sum((Decimal(phase.days) for phase in section.phases), Decimal("0")),
                    change=change,
                    phases=phase_rows,
                )
            )
        return result

    # Removed lines still matter to the before side: a before phase whose pair
    # moved to another section or changed values is 'modified', and one with no
    # after pair at all is 'removed' — both computed inside build().
    return WellPlanAdjustmentOut(
        id=row.id,
        well_id=row.well_id,
        configuration_scope=row.configuration_scope,
        revision_number=row.revision_number,
        status=row.status,
        reason=row.reason,
        sow_summary=row.sow_summary or "",
        planned_days_before=Decimal(row.planned_days_before),
        planned_days_after=Decimal(row.planned_days_after),
        delta_days=Decimal(row.planned_days_after) - Decimal(row.planned_days_before),
        section_count_before=row.section_count_before,
        section_count_after=row.section_count_after,
        sections_before=build("before"),
        sections_after=build("after"),
        depth_unit=(well.scope_value(row.configuration_scope, "depth_unit") if well else "m"),
        well_code=well.well_code if well else "",
        well_name=well.well_name if well else "",
        created_by=row.created_by or "",
        approved_by=row.approved_by or "",
        approved_at=row.approved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_well_plan_adjustments(
    db: Session, organization_id: str, well_id: str, scope: str | None = None
) -> list[WellPlanAdjustmentOut]:
    well = _well_or_404(db, well_id, organization_id)
    statement = select(WellPlanAdjustment).where(
        WellPlanAdjustment.organization_id == organization_id,
        WellPlanAdjustment.well_id == well_id,
    )
    if scope:
        statement = statement.where(WellPlanAdjustment.configuration_scope == scope)
    rows = list(db.scalars(statement.order_by(WellPlanAdjustment.revision_number.desc())).all())
    return [_plan_out(db, row, well) for row in rows]


def effective_well_plan_adjustment(
    db: Session, organization_id: str, well_id: str, scope: str
) -> WellPlanAdjustment | None:
    return db.scalar(
        select(WellPlanAdjustment)
        .where(
            WellPlanAdjustment.organization_id == organization_id,
            WellPlanAdjustment.well_id == well_id,
            WellPlanAdjustment.configuration_scope == scope,
            WellPlanAdjustment.status == "approved",
        )
        .order_by(WellPlanAdjustment.revision_number.desc())
        .limit(1)
    )


def create_well_plan_adjustment(
    db: Session,
    organization_id: str,
    well_id: str,
    data: WellPlanAdjustmentCreate,
    user: User,
    request: Request | None,
) -> WellPlanAdjustmentOut:
    well = _well_or_404(db, well_id, organization_id)
    if well.scope_value(data.configuration_scope, "config_status") != "configured":
        raise HTTPException(
            status_code=409,
            detail=f"Mark the {data.configuration_scope} plan of {well.well_code} as Configured before recording a plan adjustment",
        )
    open_draft = db.scalar(
        select(WellPlanAdjustment.revision_number).where(
            WellPlanAdjustment.organization_id == organization_id,
            WellPlanAdjustment.well_id == well_id,
            WellPlanAdjustment.configuration_scope == data.configuration_scope,
            WellPlanAdjustment.status == "draft",
        )
    )
    if open_draft is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Revision {open_draft} for {well.well_code} ({data.configuration_scope}) is still a draft. Approve or void it before starting another.",
        )
    _validate_plan_grid(db, organization_id, data.sections)
    revision = int(
        db.scalar(
            select(func.coalesce(func.max(WellPlanAdjustment.revision_number), 0)).where(
                WellPlanAdjustment.organization_id == organization_id,
                WellPlanAdjustment.well_id == well_id,
                WellPlanAdjustment.configuration_scope == data.configuration_scope,
            )
        )
        or 0
    ) + 1
    row = WellPlanAdjustment(
        organization_id=organization_id,
        well_id=well.id,
        configuration_scope=data.configuration_scope,
        revision_number=revision,
        status="draft",
        reason=data.reason.strip(),
        sow_summary=data.sow_summary.strip(),
        created_by=_actor_name(user),
    )
    db.add(row)
    db.flush()
    before_rows = _before_plan_rows(well, data.configuration_scope, organization_id, row.id)
    after_rows = _after_plan_rows(data.sections, before_rows, organization_id, row.id)
    for section in [*before_rows, *after_rows]:
        db.add(section)
    before_days, before_count = _plan_grid_totals(before_rows)
    after_days, after_count = _plan_grid_totals(after_rows)
    row.planned_days_before = before_days
    row.planned_days_after = after_days
    row.section_count_before = before_count
    row.section_count_after = after_count
    _record_audit(
        db, user=user, action="create", entity_type="well_plan_adjustment", record_id=row.id,
        entity_label=f"{well.well_code} {data.configuration_scope} Rev {revision}",
        summary=(
            f"Recorded {data.configuration_scope} plan adjustment Rev {revision} (draft) for well {well.well_code}: "
            f"{after_days:,.2f} days across {after_count} section(s) vs configured {before_days:,.2f} days "
            f"across {before_count} section(s). Reason: {row.reason}"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(row)
    return _plan_out(db, row, well)


def update_well_plan_adjustment(
    db: Session,
    organization_id: str,
    adjustment_id: str,
    data: WellPlanAdjustmentUpdate,
    user: User,
    request: Request | None,
) -> WellPlanAdjustmentOut:
    row = db.scalar(
        select(WellPlanAdjustment).where(
            WellPlanAdjustment.id == adjustment_id,
            WellPlanAdjustment.organization_id == organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Plan adjustment not found in this workspace")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft plan adjustment can be edited. Record a new revision instead.")
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field in ("reason", "sow_summary"):
        if payload.get(field) is not None and payload[field] != getattr(row, field):
            setattr(row, field, payload[field])
            changed.append(field)
    if data.sections is not None:
        _validate_plan_grid(db, organization_id, data.sections)
        before_rows = [section for section in row.sections if section.plan_side == "before"]
        for stale in [section for section in row.sections if section.plan_side == "after"]:
            db.delete(stale)
        db.flush()
        after_rows = _after_plan_rows(data.sections, before_rows, organization_id, row.id)
        for section in after_rows:
            db.add(section)
        after_days, after_count = _plan_grid_totals(after_rows)
        row.planned_days_after = after_days
        row.section_count_after = after_count
        changed.append("revised plan grid")
    well = db.get(Well, row.well_id)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="well_plan_adjustment", record_id=row.id,
            entity_label=f"{well.well_code if well else row.well_id} Rev {row.revision_number}",
            summary=f"Updated plan adjustment Rev {row.revision_number} for well {well.well_code if well else ''}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
        db.refresh(row)
    return _plan_out(db, row, well)


def _set_well_plan_status(
    db: Session,
    organization_id: str,
    adjustment_id: str,
    status: str,
    user: User,
    request: Request | None,
    remarks: str = "",
) -> WellPlanAdjustmentOut:
    row = db.scalar(
        select(WellPlanAdjustment).where(
            WellPlanAdjustment.id == adjustment_id,
            WellPlanAdjustment.organization_id == organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Plan adjustment not found in this workspace")
    well = db.get(Well, row.well_id)
    label = f"{well.well_code if well else row.well_id} {row.configuration_scope} Rev {row.revision_number}"
    if status == "approved":
        if row.status != "draft":
            raise HTTPException(status_code=409, detail="Only a draft plan adjustment can be approved")
        row.status = "approved"
        row.approved_by = _actor_name(user)
        row.approved_at = _now()
        action, summary = "approve", (
            f"Approved {row.configuration_scope} plan adjustment Rev {row.revision_number} for well "
            f"{well.well_code if well else ''}: {Decimal(row.planned_days_after):,.2f} days"
            + (f". {remarks.strip()}" if remarks.strip() else "")
        )
    else:
        if row.status == "void":
            raise HTTPException(status_code=409, detail="This plan adjustment is already void")
        row.status = "void"
        action, summary = "void", f"Voided plan adjustment {label}" + (f": {remarks.strip()}" if remarks.strip() else "")
    _record_audit(
        db, user=user, action=action, entity_type="well_plan_adjustment", record_id=row.id,
        entity_label=label, summary=summary, request=request,
    )
    _commit(db)
    db.refresh(row)
    return _plan_out(db, row, well)


def approve_well_plan_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> WellPlanAdjustmentOut:
    return _set_well_plan_status(db, organization_id, adjustment_id, "approved", user, request, remarks)


def void_well_plan_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> WellPlanAdjustmentOut:
    return _set_well_plan_status(db, organization_id, adjustment_id, "void", user, request, remarks)


# ---------------------------------------------------------------------------
# AFE SOW adjustments — the AFE estimate modules, entered as a revision
# ---------------------------------------------------------------------------


def _estimate_payload(data: Any) -> EstimateIn:
    """Strip pairing keys and hand the estimate modules to theAFE pipeline."""

    return EstimateIn(
        standard_currency=data.standard_currency or "",
        exchange_rates=[
            {"currency_code": rate.currency_code, "rate": rate.rate} for rate in data.exchange_rates
        ],
        services=[ServiceLineIn.model_validate(line.model_dump(exclude={"pair_key"})) for line in data.services],
        consumables=[
            ConsumableLineIn.model_validate(line.model_dump(exclude={"pair_key"})) for line in data.consumables
        ],
        tangibles=[TangibleLineIn.model_validate(line.model_dump(exclude={"pair_key"})) for line in data.tangibles],
    )


def _before_afe_rows(db: Session, afe: Afe, adjustment: AfeSowAdjustment) -> None:
    """Snapshot the saved estimate lines on the before side of the revision."""

    organization_id = adjustment.organization_id

    def line_meta(index: int, prefix: str) -> dict[str, Any]:
        return {
            "organization_id": organization_id,
            "adjustment_id": adjustment.id,
            "plan_side": "before",
            "pair_key": f"{prefix}{index}",
        }

    rows: list[Any] = []
    for index, line in enumerate(afe.service_lines):
        row = AfeSowServiceLine(
            **line_meta(index, "sv"),
            service_id=line.service_id,
            charging_basis=line.charging_basis,
            hole_section_id=line.hole_section_id,
            phase_id=line.phase_id,
            currency=line.currency,
            service_amount=Decimal(line.service_amount),
            remarks=line.remarks or "",
            sort_order=index,
        )
        row.rates = [
            AfeSowServiceRate(
                organization_id=organization_id,
                plan_side="before",
                pair_key=row.pair_key,
                charge_category=rate.charge_category,
                unit_rate=Decimal(rate.unit_rate),
                sort_order=rate.sort_order,
            )
            for rate in line.rates
        ]
        row.charges = [
            AfeSowServiceCharge(
                organization_id=organization_id,
                plan_side="before",
                pair_key=row.pair_key,
                charge_category=charge.charge_category,
                quantity=Decimal(charge.quantity),
                quantity_unit=charge.quantity_unit,
                sort_order=charge.sort_order,
            )
            for charge in line.charges
        ]
        row.section_rates = [
            AfeSowServiceSectionRate(
                organization_id=organization_id,
                plan_side="before",
                pair_key=row.pair_key,
                hole_section_id=entry.hole_section_id,
                phase_id=entry.phase_id,
                amount=Decimal(entry.amount),
                sort_order=entry.sort_order,
            )
            for entry in line.section_rates
        ]
        rows.append(row)
    for index, line in enumerate(afe.consumable_lines):
        rows.append(
            AfeSowConsumableLine(
                **line_meta(index, "cs"),
                category=line.category,
                hole_section_id=line.hole_section_id,
                phase_id=line.phase_id,
                drill_bit_id=line.drill_bit_id,
                quantity=Decimal(line.quantity),
                captured_rate=Decimal(line.captured_rate),
                override_rate=Decimal(line.override_rate) if line.override_rate is not None else None,
                estimated_amount=Decimal(line.estimated_amount) if line.estimated_amount is not None else None,
                currency=line.currency,
                remarks=line.remarks or "",
                sort_order=index,
            )
        )
    for index, line in enumerate(afe.tangible_lines):
        rows.append(
            AfeSowTangibleLine(
                **line_meta(index, "tg"),
                tangible_id=line.tangible_id,
                quantity=Decimal(line.quantity),
                captured_rate=Decimal(line.captured_rate),
                override_rate=Decimal(line.override_rate) if line.override_rate is not None else None,
                currency=line.currency,
                uom=line.uom or "",
                remarks=line.remarks or "",
                sort_order=index,
            )
        )
    for row in rows:
        db.add(row)


def _after_afe_rows(
    adjustment: AfeSowAdjustment,
    resolved: afe_service.Resolved,
    keys: dict[str, list[str]],
) -> None:
    """Store the validated revised lines on the after side of the revision."""

    organization_id = adjustment.organization_id
    rows: list[Any] = []
    for index, row in enumerate(resolved.services):
        pair_key = keys["services"][index]
        line = AfeSowServiceLine(
            organization_id=organization_id,
            adjustment_id=adjustment.id,
            plan_side="after",
            pair_key=pair_key,
            service_id=row.service.id,
            charging_basis=row.basis,
            hole_section_id=row.section_id,
            phase_id=row.phase_id,
            currency=row.currency,
            service_amount=Decimal(row.service_amount),
            remarks=row.remarks or "",
            sort_order=index,
        )
        line.rates = [
            AfeSowServiceRate(
                organization_id=organization_id,
                plan_side="after",
                pair_key=pair_key,
                charge_category=category,
                unit_rate=rate,
                sort_order=order,
            )
            for order, (category, rate) in enumerate(row.rates)
        ]
        line.charges = [
            AfeSowServiceCharge(
                organization_id=organization_id,
                plan_side="after",
                pair_key=pair_key,
                charge_category=category,
                quantity=quantity,
                quantity_unit=unit,
                sort_order=order,
            )
            for order, (category, quantity, unit) in enumerate(row.charges)
        ]
        line.section_rates = [
            AfeSowServiceSectionRate(
                organization_id=organization_id,
                plan_side="after",
                pair_key=pair_key,
                hole_section_id=section_id,
                phase_id=phase_id,
                amount=amount,
                sort_order=order,
            )
            for order, (section_id, phase_id, amount) in enumerate(row.section_rates)
        ]
        rows.append(line)
    for index, row in enumerate(resolved.consumables):
        rows.append(
            AfeSowConsumableLine(
                organization_id=organization_id,
                adjustment_id=adjustment.id,
                plan_side="after",
                pair_key=keys["consumables"][index],
                category=row.category,
                hole_section_id=row.section_id,
                phase_id=row.phase_id,
                drill_bit_id=row.drill_bit.id if row.drill_bit else None,
                quantity=Decimal(row.quantity),
                captured_rate=Decimal(row.captured_rate),
                override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                estimated_amount=Decimal(row.estimated_amount) if row.estimated_amount is not None else None,
                currency=row.currency,
                remarks=row.remarks or "",
                sort_order=index,
            )
        )
    for index, row in enumerate(resolved.tangibles):
        rows.append(
            AfeSowTangibleLine(
                organization_id=organization_id,
                adjustment_id=adjustment.id,
                plan_side="after",
                pair_key=keys["tangibles"][index],
                tangible_id=row.tangible.id,
                quantity=Decimal(row.quantity),
                captured_rate=Decimal(row.captured_rate),
                override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                currency=row.currency,
                uom=row.uom or "",
                remarks=row.remarks or "",
                sort_order=index,
            )
        )
    for row in rows:
        if isinstance(row, AfeSowServiceLine):
            adjustment.service_lines.append(row)
        elif isinstance(row, AfeSowConsumableLine):
            adjustment.consumable_lines.append(row)
        else:
            adjustment.tangible_lines.append(row)


def _sow_resolved(
    services: Sequence[AfeSowServiceLine],
    consumables: Sequence[AfeSowConsumableLine],
    tangibles: Sequence[AfeSowTangibleLine],
    lookups: afe_service.Lookups,
) -> afe_service.Resolved:
    """Rebuild priced-line inputs from stored revision rows (pair keys kept)."""

    resolved = afe_service.Resolved()
    for row in services:
        service = lookups.services.get(row.service_id)
        rates = tuple((rate.charge_category, Decimal(rate.unit_rate)) for rate in row.rates)
        charges = tuple(
            (charge.charge_category, Decimal(charge.quantity), charge.quantity_unit) for charge in row.charges
        )
        section_rates = tuple(
            (entry.hole_section_id, entry.phase_id, Decimal(entry.amount)) for entry in row.section_rates
        )
        resolved.services.append(
            afe_service.RService(
                key=row.pair_key,
                id=row.id,
                service=service,
                basis=row.charging_basis,
                section_id=row.hole_section_id,
                phase_id=row.phase_id,
                currency=row.currency,
                service_amount=Decimal(row.service_amount),
                remarks=row.remarks,
                rates=rates,
                charges=charges,
                section_rates=section_rates,
                line=engine.ServiceLine(
                    key=row.pair_key,
                    label=afe_service._service_label(service),
                    charging_basis=row.charging_basis,
                    currency=row.currency,
                    section_id=row.hole_section_id,
                    phase_id=row.phase_id,
                    service_amount=Decimal(row.service_amount),
                    rates=tuple(engine.RateInput(category, rate) for category, rate in rates),
                    charges=tuple(engine.ChargeInput(category, qty, unit) for category, qty, unit in charges),
                    section_rates=tuple(
                        engine.SectionRateInput(section_id, phase_id, amount)
                        for section_id, phase_id, amount in section_rates
                    ),
                ),
            )
        )
    for row in consumables:
        drill_bit = lookups.drill_bits.get(row.drill_bit_id or "")
        label = afe_service._label(drill_bit.bit_code, drill_bit.bit_name) if drill_bit else "Drill bit removed from master data"
        if row.category != engine.CONSUMABLE_DRILL_BITS:
            label = row.category
        resolved.consumables.append(
            afe_service.RConsumable(
                key=row.pair_key,
                id=row.id,
                category=row.category,
                section_id=row.hole_section_id,
                phase_id=row.phase_id,
                drill_bit=drill_bit,
                quantity=Decimal(row.quantity),
                captured_rate=Decimal(row.captured_rate),
                override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                estimated_amount=Decimal(row.estimated_amount) if row.estimated_amount is not None else None,
                currency=row.currency,
                remarks=row.remarks,
                line=engine.ConsumableLine(
                    key=row.pair_key,
                    label=label,
                    category=row.category,
                    section_id=row.hole_section_id,
                    phase_id=row.phase_id,
                    quantity=Decimal(row.quantity),
                    captured_rate=Decimal(row.captured_rate),
                    override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                    estimated_amount=Decimal(row.estimated_amount) if row.estimated_amount is not None else None,
                    currency=row.currency,
                ),
            )
        )
    for row in tangibles:
        tangible = lookups.tangibles.get(row.tangible_id)
        label = afe_service._label(tangible.tangible_code, tangible.tangible_name) if tangible else "Tangible removed from master data"
        resolved.tangibles.append(
            afe_service.RTangible(
                key=row.pair_key,
                id=row.id,
                tangible=tangible,
                quantity=Decimal(row.quantity),
                captured_rate=Decimal(row.captured_rate),
                override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                currency=row.currency,
                uom=row.uom,
                remarks=row.remarks,
                line=engine.TangibleLine(
                    key=row.pair_key,
                    label=label,
                    quantity=Decimal(row.quantity),
                    captured_rate=Decimal(row.captured_rate),
                    override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                    currency=row.currency,
                    uom=row.uom,
                ),
            )
        )
    return resolved


def _sow_line_lookups(
    db: Session,
    organization_id: str,
    services: Sequence[AfeSowServiceLine],
    consumables: Sequence[AfeSowConsumableLine],
    tangibles: Sequence[AfeSowTangibleLine],
) -> afe_service.Lookups:
    return afe_service._load_lookups(
        db,
        organization_id,
        service_ids=[row.service_id for row in services],
        drill_bit_ids=[row.drill_bit_id or "" for row in consumables],
        tangible_ids=[row.tangible_id for row in tangibles],
        hole_section_ids=[
            value
            for value in (
                *(row.hole_section_id or "" for row in services),
                *(row.hole_section_id for row in consumables),
                *(entry.hole_section_id for row in services for entry in row.section_rates),
            )
        ],
        phase_ids=[
            value
            for value in (
                *(row.phase_id or "" for row in services),
                *(row.phase_id or "" for row in consumables),
                *(entry.phase_id or "" for row in services for entry in row.section_rates),
            )
        ],
    )


def _side_rates(rows: Sequence[AfeSowExchangeRate], side: str) -> dict[str, Decimal]:
    return {
        row.currency_code: Decimal(row.rate)
        for row in rows
        if row.plan_side == side
    }


def _bundle_out(
    db: Session,
    organization_id: str,
    adjustment: AfeSowAdjustment,
    side: str,
) -> AfeSowBundleOut:
    """Reprice one side of the revision exactly as its lines were entered."""

    services = sorted(
        (row for row in adjustment.service_lines if row.plan_side == side), key=lambda row: row.sort_order
    )
    consumables = sorted(
        (row for row in adjustment.consumable_lines if row.plan_side == side), key=lambda row: row.sort_order
    )
    tangibles = sorted(
        (row for row in adjustment.tangible_lines if row.plan_side == side), key=lambda row: row.sort_order
    )
    lookups = _sow_line_lookups(db, organization_id, services, consumables, tangibles)
    resolved = _sow_resolved(services, consumables, tangibles, lookups)
    well = db.get(Well, adjustment.well_id)
    scope = afe_service._scope_for_well(well, adjustment.configuration_scope)
    priced = afe_service._price(
        scope,
        resolved,
        lookups,
        adjustment.standard_currency or "",
        _side_rates(adjustment.exchange_rates, side),
    )
    return AfeSowBundleOut(
        services=priced.services,
        consumables=priced.consumables,
        tangibles=priced.tangibles,
        summary=priced.summary,
    )


def _adjustment_out(
    db: Session,
    row: AfeSowAdjustment,
    afe: Afe | None = None,
    well: Well | None = None,
    *,
    include_lines: bool = True,
) -> AfeSowAdjustmentOut:
    original = row.original_total if row.original_total is not None else None
    delta = (Decimal(row.adjusted_total) - Decimal(original)) if original is not None else Decimal(row.adjusted_total)
    return AfeSowAdjustmentOut(
        id=row.id,
        afe_id=row.afe_id,
        well_id=row.well_id,
        rig_id=row.rig_id,
        configuration_scope=row.configuration_scope,
        revision_number=row.revision_number,
        status=row.status,
        reason=row.reason,
        sow_summary=row.sow_summary or "",
        standard_currency=row.standard_currency or "",
        original_services_total=row.original_services_total,
        original_consumables_total=row.original_consumables_total,
        original_tangibles_total=row.original_tangibles_total,
        original_total=row.original_total,
        adjusted_services_total=Decimal(row.adjusted_services_total),
        adjusted_consumables_total=Decimal(row.adjusted_consumables_total),
        adjusted_tangibles_total=Decimal(row.adjusted_tangibles_total),
        adjusted_total=Decimal(row.adjusted_total),
        delta_total=delta,
        before=_bundle_out(db, row.organization_id, row, "before") if include_lines else None,
        after=_bundle_out(db, row.organization_id, row, "after") if include_lines else None,
        afe_code=afe.afe_code if afe else "",
        afe_name=afe.afe_name if afe else "",
        well_code=well.well_code if well else "",
        well_name=well.well_name if well else "",
        created_by=row.created_by or "",
        approved_by=row.approved_by or "",
        approved_at=row.approved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_afe_adjustments(db: Session, organization_id: str, afe_id: str) -> list[AfeSowAdjustmentOut]:
    afe = _afe_or_404(db, afe_id, organization_id)
    well = db.get(Well, afe.well_id)
    rows = list(
        db.scalars(
            select(AfeSowAdjustment)
            .where(AfeSowAdjustment.organization_id == organization_id, AfeSowAdjustment.afe_id == afe_id)
            .order_by(AfeSowAdjustment.revision_number.desc())
        ).all()
    )
    return [_adjustment_out(db, row, afe, well) for row in rows]


def effective_afe_adjustment(db: Session, organization_id: str, afe_id: str) -> AfeSowAdjustment | None:
    """The latest approved adjustment for one AFE, or None when there is none."""
    return db.scalar(
        select(AfeSowAdjustment)
        .where(
            AfeSowAdjustment.organization_id == organization_id,
            AfeSowAdjustment.afe_id == afe_id,
            AfeSowAdjustment.status == "approved",
        )
        .order_by(AfeSowAdjustment.revision_number.desc())
        .limit(1)
    )


def effective_afe_adjustments_for_well(
    db: Session, organization_id: str, well_id: str
) -> dict[str, AfeSowAdjustment]:
    """Latest approved AFE adjustment per AFE of one well, keyed by AFE id."""
    rows = list(
        db.scalars(
            select(AfeSowAdjustment)
            .where(
                AfeSowAdjustment.organization_id == organization_id,
                AfeSowAdjustment.well_id == well_id,
                AfeSowAdjustment.status == "approved",
            )
            .order_by(AfeSowAdjustment.afe_id, AfeSowAdjustment.revision_number.desc())
        ).all()
    )
    effective: dict[str, AfeSowAdjustment] = {}
    for row in rows:
        effective.setdefault(row.afe_id, row)
    return effective


def _price_revision(
    db: Session,
    afe: Afe,
    data: Any,
    original_currency: str,
) -> tuple[afe_service.Resolved, afe_service.Lookups, afe_service.Priced, str]:
    """Validate and price the revised estimate lines through theAFE pipeline.

    The revision must price to the same standard currency as the saved
    estimate so original and adjusted totals compare like for like.
    """
    requested_standard = (data.standard_currency or "").strip()
    if requested_standard and original_currency and requested_standard != original_currency:
        raise HTTPException(
            status_code=422,
            detail=f"The revision must use the same standard currency as the saved estimate ({original_currency}).",
        )
    standard_currency = original_currency or requested_standard
    well = db.get(Well, afe.well_id)
    scope = afe_service._scope_for_well(well, afe.configuration_scope)
    payload = _estimate_payload(data)
    resolved = afe_service._validate_request(db, afe.organization_id, scope, payload)
    lookups = afe_service._load_lookups(
        db,
        afe.organization_id,
        service_ids=[row.service.id for row in resolved.services if row.service],
        drill_bit_ids=[row.drill_bit.id for row in resolved.consumables if row.drill_bit],
        tangible_ids=[row.tangible.id for row in resolved.tangibles if row.tangible],
        hole_section_ids=[row.section_id for row in resolved.consumables] + [row.section_id for row in resolved.services if row.section_id],
        phase_ids=[row.phase_id or "" for row in resolved.consumables] + [row.phase_id or "" for row in resolved.services],
    )
    rates = {rate.currency_code: Decimal(rate.rate) for rate in data.exchange_rates}
    priced = afe_service._price(scope, resolved, lookups, standard_currency, rates)
    if not priced.result.currency.converted:
        raise HTTPException(
            status_code=422,
            detail=f"The revised estimate is not fully convertible. {afe_service._conversion_problem(priced.result.currency)}",
        )
    return resolved, lookups, priced, standard_currency


def _derive_totals(priced: afe_service.Priced) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    services = _money(priced.result.services_total) or Decimal("0")
    consumables = _money(priced.result.consumables_total) or Decimal("0")
    tangibles = _money(priced.result.tangibles_total) or Decimal("0")
    return services, consumables, tangibles, services + consumables + tangibles


def preview_afe_adjustment(
    db: Session,
    organization_id: str,
    afe_id: str,
    data: AfeSowAdjustmentCreate,
) -> AfeSowAdjustmentPreviewOut:
    """Price a revision without saving it — the same derivation the save uses."""

    afe = _afe_or_404(db, afe_id, organization_id)
    if afe.estimate_saved_at is None:
        raise HTTPException(status_code=422, detail=f"Save the estimate for {afe.afe_code} before recording an SOW adjustment")
    services, consumables, tangibles, total, currency = _original_totals(db, organization_id, afe)
    if total is None:
        raise HTTPException(
            status_code=422,
            detail=f"The saved estimate for {afe.afe_code} mixes currencies without a complete conversion. Save it with a standard currency and rates first.",
        )
    resolved, _lookups, priced, standard_currency = _price_revision(db, afe, data, currency)
    adjusted_services, adjusted_consumables, adjusted_tangibles, adjusted_total = _derive_totals(priced)
    return AfeSowAdjustmentPreviewOut(
        standard_currency=standard_currency,
        services=priced.services,
        consumables=priced.consumables,
        tangibles=priced.tangibles,
        summary=priced.summary,
        adjusted_services_total=adjusted_services,
        adjusted_consumables_total=adjusted_consumables,
        adjusted_tangibles_total=adjusted_tangibles,
        adjusted_total=adjusted_total,
    )


def create_afe_adjustment(
    db: Session,
    organization_id: str,
    afe_id: str,
    data: AfeSowAdjustmentCreate,
    user: User,
    request: Request | None,
) -> AfeSowAdjustmentOut:
    afe = _afe_or_404(db, afe_id, organization_id)
    if afe.status == "draft":
        raise HTTPException(
            status_code=409,
            detail=f"{afe.afe_code} is still a Draft — edit the estimate directly instead of recording an SOW adjustment",
        )
    if afe.estimate_saved_at is None:
        raise HTTPException(status_code=422, detail=f"Save the estimate for {afe.afe_code} before recording an SOW adjustment")
    services, consumables, tangibles, total, currency = _original_totals(db, organization_id, afe)
    if total is None:
        raise HTTPException(
            status_code=422,
            detail=f"The saved estimate for {afe.afe_code} mixes currencies without a complete conversion. Save it with a standard currency and rates first.",
        )
    open_draft = db.scalar(
        select(AfeSowAdjustment.revision_number).where(
            AfeSowAdjustment.organization_id == organization_id,
            AfeSowAdjustment.afe_id == afe_id,
            AfeSowAdjustment.status == "draft",
        )
    )
    if open_draft is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Revision {open_draft} for {afe.afe_code} is still a draft. Approve or void it before starting another.",
        )
    resolved, _lookups, priced, standard_currency = _price_revision(db, afe, data, currency)
    adjusted_services, adjusted_consumables, adjusted_tangibles, adjusted_total = _derive_totals(priced)
    revision = int(
        db.scalar(
            select(func.coalesce(func.max(AfeSowAdjustment.revision_number), 0)).where(
                AfeSowAdjustment.organization_id == organization_id,
                AfeSowAdjustment.afe_id == afe_id,
            )
        )
        or 0
    ) + 1
    row = AfeSowAdjustment(
        organization_id=organization_id,
        afe_id=afe.id,
        well_id=afe.well_id,
        rig_id=afe.rig_id,
        configuration_scope=afe.configuration_scope,
        revision_number=revision,
        status="draft",
        reason=data.reason.strip(),
        sow_summary=data.sow_summary.strip(),
        standard_currency=standard_currency,
        original_services_total=services,
        original_consumables_total=consumables,
        original_tangibles_total=tangibles,
        original_total=total,
        adjusted_services_total=adjusted_services,
        adjusted_consumables_total=adjusted_consumables,
        adjusted_tangibles_total=adjusted_tangibles,
        adjusted_total=adjusted_total,
        created_by=_actor_name(user),
    )
    db.add(row)
    db.flush()
    before_keys = {
        "services": {f"sv{index}" for index in range(len(afe.service_lines))},
        "consumables": {f"cs{index}" for index in range(len(afe.consumable_lines))},
        "tangibles": {f"tg{index}" for index in range(len(afe.tangible_lines))},
    }
    keys = {
        "services": _assign_pair_keys(data.services, "sv", before_keys["services"], "service"),
        "consumables": _assign_pair_keys(data.consumables, "cs", before_keys["consumables"], "consumable"),
        "tangibles": _assign_pair_keys(data.tangibles, "tg", before_keys["tangibles"], "tangible"),
    }
    _before_afe_rows(db, afe, row)
    _after_afe_rows(row, resolved, keys)
    for index, rate in enumerate(sorted(afe.exchange_rates, key=lambda item: item.sort_order)):
        row.exchange_rates.append(
            AfeSowExchangeRate(
                organization_id=organization_id,
                plan_side="before",
                currency_code=rate.currency_code,
                rate=Decimal(rate.rate),
                sort_order=index,
            )
        )
    for index, rate in enumerate(data.exchange_rates):
        row.exchange_rates.append(
            AfeSowExchangeRate(
                organization_id=organization_id,
                plan_side="after",
                currency_code=rate.currency_code,
                rate=Decimal(rate.rate),
                sort_order=index,
            )
        )
    well = db.get(Well, afe.well_id)
    _record_audit(
        db, user=user, action="create", entity_type="afe_sow_adjustment", record_id=row.id,
        entity_label=f"{afe.afe_code} Rev {revision}",
        summary=(
            f"Recorded SOW adjustment Rev {revision} (draft) for AFE {afe.afe_code}: "
            f"{standard_currency} {adjusted_total:,.2f} vs original {standard_currency} {Decimal(total):,.2f} "
            f"({len(data.services)} service, {len(data.consumables)} consumable, {len(data.tangibles)} tangible revised line(s)). "
            f"Reason: {row.reason}"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(row)
    return _adjustment_out(db, row, afe, well)


def update_afe_adjustment(
    db: Session,
    organization_id: str,
    adjustment_id: str,
    data: AfeSowAdjustmentUpdate,
    user: User,
    request: Request | None,
) -> AfeSowAdjustmentOut:
    row = db.scalar(
        select(AfeSowAdjustment).where(
            AfeSowAdjustment.id == adjustment_id,
            AfeSowAdjustment.organization_id == organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="SOW adjustment not found in this workspace")
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft SOW adjustment can be edited. Record a new revision instead.")
    afe = db.get(Afe, row.afe_id)
    well = db.get(Well, row.well_id)
    changed: list[str] = []
    provided = data.model_fields_set
    for field in ("reason", "sow_summary"):
        value = getattr(data, field)
        if value is not None and value != getattr(row, field):
            setattr(row, field, value)
            changed.append(field)

    modules = ("services", "consumables", "tangibles")
    modules_provided = [module for module in modules if module in provided]
    if modules_provided and len(modules_provided) < len(modules):
        raise HTTPException(
            status_code=422,
            detail="Send all three estimate modules (services, consumables, tangibles) when updating the revised lines.",
        )

    if modules_provided:
        # Full replacement of the after side: validate the revised modules
        # through the estimate pipeline, then store the resolved lines.
        before_keys = {
            "services": {item.pair_key for item in row.service_lines if item.plan_side == "before"},
            "consumables": {item.pair_key for item in row.consumable_lines if item.plan_side == "before"},
            "tangibles": {item.pair_key for item in row.tangible_lines if item.plan_side == "before"},
        }
        keys = {
            "services": _assign_pair_keys(data.services, "sv", before_keys["services"], "service"),
            "consumables": _assign_pair_keys(data.consumables, "cs", before_keys["consumables"], "consumable"),
            "tangibles": _assign_pair_keys(data.tangibles, "tg", before_keys["tangibles"], "tangible"),
        }
        pricing_data = data if "exchange_rates" in provided else _RevisionView(data, row)
        resolved, _lookups, priced, standard_currency = _price_revision(
            db, afe, pricing_data, row.standard_currency or ""
        )
        for columns in ("service_lines", "consumable_lines", "tangible_lines"):
            for stale in [item for item in getattr(row, columns) if item.plan_side == "after"]:
                db.delete(stale)
        db.flush()
        _after_afe_rows(row, resolved, keys)
        changed.append("revised estimate lines")

        if "exchange_rates" in provided:
            for stale in [item for item in row.exchange_rates if item.plan_side == "after"]:
                db.delete(stale)
            db.flush()
            for index, rate in enumerate(data.exchange_rates):
                row.exchange_rates.append(
                    AfeSowExchangeRate(
                        organization_id=organization_id,
                        plan_side="after",
                        currency_code=rate.currency_code,
                        rate=Decimal(rate.rate),
                        sort_order=index,
                    )
                )
            changed.append("revised exchange rates")

        # Totals always derive from the full revised line set.
        adjusted_services, adjusted_consumables, adjusted_tangibles, adjusted_total = _derive_totals(priced)
        row.adjusted_services_total = adjusted_services
        row.adjusted_consumables_total = adjusted_consumables
        row.adjusted_tangibles_total = adjusted_tangibles
        row.adjusted_total = adjusted_total
        if standard_currency:
            row.standard_currency = standard_currency
    elif "exchange_rates" in provided:
        # Rates-only edit: the stored after lines are repriced with the new
        # conversion setup and the derived totals follow.
        for stale in [item for item in row.exchange_rates if item.plan_side == "after"]:
            db.delete(stale)
        db.flush()
        for index, rate in enumerate(data.exchange_rates):
            row.exchange_rates.append(
                AfeSowExchangeRate(
                    organization_id=organization_id,
                    plan_side="after",
                    currency_code=rate.currency_code,
                    rate=Decimal(rate.rate),
                    sort_order=index,
                )
            )
        after_services = [item for item in row.service_lines if item.plan_side == "after"]
        after_consumables = [item for item in row.consumable_lines if item.plan_side == "after"]
        after_tangibles = [item for item in row.tangible_lines if item.plan_side == "after"]
        lookups = _sow_line_lookups(db, organization_id, after_services, after_consumables, after_tangibles)
        resolved_rows = _sow_resolved(after_services, after_consumables, after_tangibles, lookups)
        scope = afe_service._scope_for_well(well, row.configuration_scope)
        rates = {rate.currency_code: Decimal(rate.rate) for rate in data.exchange_rates}
        priced = afe_service._price(
            scope, resolved_rows, lookups, row.standard_currency or "", rates
        )
        if not priced.result.currency.converted:
            raise HTTPException(
                status_code=422,
                detail=f"The revised estimate is not fully convertible. {afe_service._conversion_problem(priced.result.currency)}",
            )
        adjusted_services, adjusted_consumables, adjusted_tangibles, adjusted_total = _derive_totals(priced)
        row.adjusted_services_total = adjusted_services
        row.adjusted_consumables_total = adjusted_consumables
        row.adjusted_tangibles_total = adjusted_tangibles
        row.adjusted_total = adjusted_total
        changed.append("revised exchange rates")

    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="afe_sow_adjustment", record_id=row.id,
            entity_label=f"{afe.afe_code if afe else row.afe_id} Rev {row.revision_number}",
            summary=f"Updated SOW adjustment Rev {row.revision_number} for AFE {afe.afe_code if afe else ''}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
        db.refresh(row)
    return _adjustment_out(db, row, afe, well)


class _RevisionView:
    """A revision payload whose conversion rates come from stored after rows.

    Used when a draft edit replaces the estimate modules but leaves the
    exchange-rate setup untouched.
    """

    def __init__(self, data: Any, row: AfeSowAdjustment) -> None:
        self.standard_currency = data.standard_currency or row.standard_currency or ""
        self.exchange_rates = [item for item in row.exchange_rates if item.plan_side == "after"]
        self.services = data.services
        self.consumables = data.consumables
        self.tangibles = data.tangibles


def _set_afe_adjustment_status(
    db: Session,
    organization_id: str,
    adjustment_id: str,
    status: str,
    user: User,
    request: Request | None,
    remarks: str = "",
) -> AfeSowAdjustmentOut:
    row = db.scalar(
        select(AfeSowAdjustment).where(
            AfeSowAdjustment.id == adjustment_id,
            AfeSowAdjustment.organization_id == organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="SOW adjustment not found in this workspace")
    afe = db.get(Afe, row.afe_id)
    well = db.get(Well, row.well_id)
    if status == "approved":
        if row.status != "draft":
            raise HTTPException(status_code=409, detail="Only a draft SOW adjustment can be approved")
        if row.original_total is None:
            raise HTTPException(status_code=422, detail="This adjustment has no converted original total and cannot be approved")
        row.status = "approved"
        row.approved_by = _actor_name(user)
        row.approved_at = _now()
        action, summary = "approve", (
            f"Approved SOW adjustment Rev {row.revision_number} for AFE {afe.afe_code if afe else ''}: "
            f"{row.standard_currency} {Decimal(row.adjusted_total):,.2f}"
            + (f". {remarks.strip()}" if remarks.strip() else "")
        )
    else:
        if row.status == "void":
            raise HTTPException(status_code=409, detail="This SOW adjustment is already void")
        row.status = "void"
        action, summary = "void", (
            f"Voided SOW adjustment Rev {row.revision_number} for AFE {afe.afe_code if afe else ''}"
            + (f": {remarks.strip()}" if remarks.strip() else "")
        )
    _record_audit(
        db, user=user, action=action, entity_type="afe_sow_adjustment", record_id=row.id,
        entity_label=f"{afe.afe_code if afe else row.afe_id} Rev {row.revision_number}",
        summary=summary, request=request,
    )
    _commit(db)
    db.refresh(row)
    return _adjustment_out(db, row, afe, well)


def approve_afe_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> AfeSowAdjustmentOut:
    return _set_afe_adjustment_status(db, organization_id, adjustment_id, "approved", user, request, remarks)


def void_afe_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> AfeSowAdjustmentOut:
    return _set_afe_adjustment_status(db, organization_id, adjustment_id, "void", user, request, remarks)


def well_adjusted_summary(
    db: Session, organization_id: str, well_id: str, scope: str = "drilling"
) -> WellAdjustedSummary:
    """Effective adjustments for one well: latest approved plan + per-AFE costs."""
    well = _well_or_404(db, well_id, organization_id)
    plan = effective_well_plan_adjustment(db, organization_id, well_id, scope)
    afe_rows = effective_afe_adjustments_for_well(db, organization_id, well_id)
    afes = {
        row.id: row
        for row in db.scalars(
            select(Afe).where(Afe.organization_id == organization_id, Afe.id.in_(list(afe_rows) or [""]))
        ).all()
    }
    return WellAdjustedSummary(
        well_id=well.id,
        configuration_scope=scope,
        planned_days_before=Decimal(plan.planned_days_before) if plan else None,
        planned_days_after=Decimal(plan.planned_days_after) if plan else None,
        has_plan_adjustment=plan is not None,
        plan_revision=plan.revision_number if plan else None,
        afe_adjustments={
            afe_id: _adjustment_out(db, row, afes.get(afe_id), well, include_lines=False)
            for afe_id, row in afe_rows.items()
        },
    )


# ---------------------------------------------------------------------------
# Daily cost amendments (late reopens tracked separately)
# ---------------------------------------------------------------------------


def amendment_threshold_exceeded(cost_date: date, today: date | None = None) -> bool:
    today = today or date.today()
    return (today - cost_date).days > AMENDMENT_THRESHOLD_DAYS


def list_amendments(db: Session, organization_id: str, entry_id: str) -> list[DailyCostAmendmentOut]:
    rows = list(
        db.scalars(
            select(DailyCostAmendment)
            .where(DailyCostAmendment.organization_id == organization_id, DailyCostAmendment.entry_id == entry_id)
            .order_by(DailyCostAmendment.amendment_number)
        ).all()
    )
    return [DailyCostAmendmentOut.model_validate(row) for row in rows]


def record_amendment(
    db: Session,
    *,
    entry: DailyCostEntry,
    user: User,
    reason: str,
) -> DailyCostAmendment | None:
    """Log a late reopen separately. Returns None when the sheet is not late."""
    if not amendment_threshold_exceeded(entry.cost_date):
        return None
    number = int(
        db.scalar(
            select(func.coalesce(func.max(DailyCostAmendment.amendment_number), 0)).where(
                DailyCostAmendment.organization_id == entry.organization_id,
                DailyCostAmendment.entry_id == entry.id,
            )
        )
        or 0
    ) + 1
    row = DailyCostAmendment(
        organization_id=entry.organization_id,
        entry_id=entry.id,
        well_id=entry.well_id,
        afe_id=entry.afe_id,
        amendment_number=number,
        cost_date=entry.cost_date,
        days_after_cost_date=(date.today() - entry.cost_date).days,
        reason=reason.strip(),
        reopened_by=_actor_name(user),
        reopened_at=_now(),
    )
    db.add(row)
    db.flush()
    return row
