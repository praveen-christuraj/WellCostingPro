"""AFE SOW adjustments, well plan adjustments and daily cost amendments.

All helpers are additive: original AFE estimates, well configurations and
daily baselines are never rewritten. When no *approved* adjustment exists,
callers fall back to the original totals and planned days.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    Afe,
    AuditLog,
    DailyCostEntry,
    Rig,
    Well,
    WellSection,
)
from app.models.entities import User
from app.models.sow_adjustment import (
    AfeSowAdjustment,
    DailyCostAmendment,
    WellPlanAdjustment,
)
from app.schemas.sow_adjustment import (
    AfeSowAdjustmentCreate,
    AfeSowAdjustmentOut,
    AfeSowAdjustmentUpdate,
    DailyCostAmendmentOut,
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
    if well.is_deleted:
        raise HTTPException(status_code=409, detail="Restore this well before recording plan adjustments")
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


def _adjustment_out(row: AfeSowAdjustment, afe: Afe | None = None, well: Well | None = None) -> AfeSowAdjustmentOut:
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


def _plan_out(row: WellPlanAdjustment, well: Well | None = None) -> WellPlanAdjustmentOut:
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
        well_code=well.well_code if well else "",
        well_name=well.well_name if well else "",
        created_by=row.created_by or "",
        approved_by=row.approved_by or "",
        approved_at=row.approved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# AFE SOW adjustments
# ---------------------------------------------------------------------------


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
    return [_adjustment_out(row, afe, well) for row in rows]


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
    revision = int(
        db.scalar(
            select(func.coalesce(func.max(AfeSowAdjustment.revision_number), 0)).where(
                AfeSowAdjustment.organization_id == organization_id,
                AfeSowAdjustment.afe_id == afe_id,
            )
        )
        or 0
    ) + 1
    adjusted_services = Decimal(data.adjusted_services_total)
    adjusted_consumables = Decimal(data.adjusted_consumables_total)
    adjusted_tangibles = Decimal(data.adjusted_tangibles_total)
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
        standard_currency=currency,
        original_services_total=services,
        original_consumables_total=consumables,
        original_tangibles_total=tangibles,
        original_total=total,
        adjusted_services_total=adjusted_services,
        adjusted_consumables_total=adjusted_consumables,
        adjusted_tangibles_total=adjusted_tangibles,
        adjusted_total=adjusted_services + adjusted_consumables + adjusted_tangibles,
        created_by=_actor_name(user),
    )
    db.add(row)
    db.flush()
    well = db.get(Well, afe.well_id)
    _record_audit(
        db, user=user, action="create", entity_type="afe_sow_adjustment", record_id=row.id,
        entity_label=f"{afe.afe_code} Rev {revision}",
        summary=(
            f"Recorded SOW adjustment Rev {revision} (draft) for AFE {afe.afe_code}: "
            f"{currency} {Decimal(row.adjusted_total):,.2f} vs original {currency} {Decimal(total):,.2f}. "
            f"Reason: {row.reason}"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(row)
    return _adjustment_out(row, afe, well)


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
    payload = data.model_dump(exclude_unset=True)
    changed: list[str] = []
    for field in ("adjusted_services_total", "adjusted_consumables_total", "adjusted_tangibles_total"):
        if payload.get(field) is not None and Decimal(payload[field]) != Decimal(getattr(row, field)):
            setattr(row, field, Decimal(payload[field]))
            changed.append(field)
    if changed:
        row.adjusted_total = (
            Decimal(row.adjusted_services_total)
            + Decimal(row.adjusted_consumables_total)
            + Decimal(row.adjusted_tangibles_total)
        )
    for field in ("reason", "sow_summary"):
        if payload.get(field) is not None and payload[field] != getattr(row, field):
            setattr(row, field, payload[field])
            changed.append(field)
    afe = db.get(Afe, row.afe_id)
    well = db.get(Well, row.well_id)
    if changed:
        _record_audit(
            db, user=user, action="update", entity_type="afe_sow_adjustment", record_id=row.id,
            entity_label=f"{afe.afe_code if afe else row.afe_id} Rev {row.revision_number}",
            summary=f"Updated SOW adjustment Rev {row.revision_number} for AFE {afe.afe_code if afe else ''}: {', '.join(changed)}",
            request=request,
        )
        _commit(db)
        db.refresh(row)
    return _adjustment_out(row, afe, well)


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
    return _adjustment_out(row, afe, well)


def approve_afe_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> AfeSowAdjustmentOut:
    return _set_afe_adjustment_status(db, organization_id, adjustment_id, "approved", user, request, remarks)


def void_afe_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> AfeSowAdjustmentOut:
    return _set_afe_adjustment_status(db, organization_id, adjustment_id, "void", user, request, remarks)


# ---------------------------------------------------------------------------
# Well plan adjustments
# ---------------------------------------------------------------------------


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
    return [_plan_out(row, well) for row in rows]


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
    before_days, before_sections = _well_scope_days(well, data.configuration_scope)
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
        planned_days_before=before_days,
        planned_days_after=Decimal(data.planned_days_after),
        section_count_before=before_sections,
        section_count_after=data.section_count_after or before_sections,
        created_by=_actor_name(user),
    )
    db.add(row)
    db.flush()
    _record_audit(
        db, user=user, action="create", entity_type="well_plan_adjustment", record_id=row.id,
        entity_label=f"{well.well_code} {data.configuration_scope} Rev {revision}",
        summary=(
            f"Recorded {data.configuration_scope} plan adjustment Rev {revision} (draft) for well {well.well_code}: "
            f"{Decimal(row.planned_days_after):,.2f} days vs configured {before_days:,.2f} days. Reason: {row.reason}"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(row)
    return _plan_out(row, well)


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
    for field in ("planned_days_after", "section_count_after", "reason", "sow_summary"):
        if payload.get(field) is not None and payload[field] != getattr(row, field):
            setattr(row, field, payload[field])
            changed.append(field)
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
    return _plan_out(row, well)


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
    return _plan_out(row, well)


def approve_well_plan_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> WellPlanAdjustmentOut:
    return _set_well_plan_status(db, organization_id, adjustment_id, "approved", user, request, remarks)


def void_well_plan_adjustment(
    db: Session, organization_id: str, adjustment_id: str, user: User, request: Request | None, remarks: str = ""
) -> WellPlanAdjustmentOut:
    return _set_well_plan_status(db, organization_id, adjustment_id, "void", user, request, remarks)


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
            afe_id: _adjustment_out(row, afes.get(afe_id), well) for afe_id, row in afe_rows.items()
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
