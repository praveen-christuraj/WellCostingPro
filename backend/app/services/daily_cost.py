"""Daily Cost Management domain services.

The first sheet for an AFE snapshots the saved AFE estimate, its FX factors,
the well plan, service charge cards and all active catalogue rates. Daily lines
are then priced from those immutable inputs (or a user-entered, justified
rate override), never from a live master-data price. All amounts are stored in
both their native currency and the AFE's standard currency for reconciliation.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from typing import Any, Iterable, Sequence
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import Select, func, literal, select, union_all
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    Activity, Afe, AuditLog, CementAdditive, Currency, DailyCostBaseline,
    DailyCostBaselineBudgetLine, DailyCostBaselineExchangeRate, DailyCostBaselinePhase,
    DailyCostBaselineSection, DailyCostBaselineServiceRate, DailyCostCatalogueRateSnapshot,
    DailyCostConsumableLine, DailyCostEntry, DailyCostServiceLine, DailyCostTangibleLine,
    DailyCostWellRateBaseline, DrillBit, FuelType, HoleSection, MudChemical, Phase, Rig,
    Service, Tangible, Vendor, Well, WellPhase, WellSection, WellSubActivity,
)
from app.models.entities import User
from app.models.rig_well import now as _model_now, uid
from app.schemas.afe import AfeEstimateOut
from app.schemas.daily_cost import (
    DailyCostAfeOption, DailyCostAfePosition, DailyCostBaselineBudgetOut, DailyCostBaselineOut,
    DailyCostBudgetComparison, DailyCostCatalogueOption, DailyCostComparison,
    DailyCostComparisonGroup, DailyCostConsumableLineIn, DailyCostConsumableLineOut,
    DailyCostDailyRow, DailyCostDayOut, DailyCostEntryCreate, DailyCostEntryOut, DailyCostExportAudit,
    DailyCostFactorGroup, DailyCostFactorRow, DailyCostGroupSummary, DailyCostIDs,
    DailyCostImportRequest, DailyCostImportResponse, DailyCostOverview, DailyCostPreviewOut,
    DailyCostRateOut, DailyCostReference, DailyCostReopenIn, DailyCostRigOption, DailyCostSaveIn,
    DailyCostSectionOption, DailyCostServiceLineIn, DailyCostServiceLineOut, DailyCostStatusIn,
    DailyCostSubActivityOption, DailyCostTangibleLineIn, DailyCostTangibleLineOut,
    DailyCostTrendPoint, DailyCostVendorOption, DailyCostWarnings, DailyCostWellHeader,
    DailyCostWellOption, DailyCostWellSummary, DailyCostWellTotals,
)
from app.services import afe as afe_service
from app.services import audit
from app.models.catalogue import CatalogueOption

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
FX = Decimal("0.000001")
# Every money column is Numeric(18, 2). PostgreSQL rejects anything larger with a
# driver error, which would surface as an opaque 500, so the limit is checked here
# and reported to the user as ordinary validation.
MONEY_LIMIT = Decimal("9999999999999999.99")
MAX_IMPORT_ERRORS = 100
SERVICE_ONE_TIME = {"Mobilization", "Demobilization", "Fixed Charge"}
SERVICE_DAY_BASED = {"Operation", "Standby", "Personnel-Operation", "Personnel-Standby", "Others"}
QUANTITY_UNIT_FOR_BASIS = {"Day Rate": "days", "Per Service Rate": "service", "Per Section Rate": "section"}
BASIS_ALIASES = {
    "day rate": "Day Rate", "dayrate": "Day Rate", "day": "Day Rate",
    "per service rate": "Per Service Rate", "perservicerate": "Per Service Rate", "service": "Per Service Rate",
    "per section rate": "Per Section Rate", "persectionrate": "Per Section Rate", "section": "Per Section Rate",
}
CONSUMABLE_KIND_MODEL: dict[str, tuple[type[Any], str, str, str]] = {
    "mud_chemical": (MudChemical, "chemical_code", "chemical_name", "Mud Chemicals"),
    "cement_additive": (CementAdditive, "additive_code", "additive_name", "Cement Additives"),
    "fuel": (FuelType, "fuel_code", "fuel_name", "Fuel"),
    "drill_bit": (DrillBit, "bit_code", "bit_name", "Drill Bits"),
    "tangible": (Tangible, "tangible_code", "tangible_name", "Tangibles"),
}
LINE_MODELS: tuple[tuple[type[Any], str], ...] = (
    (DailyCostServiceLine, "Services"),
    (DailyCostConsumableLine, "Consumables"),
    (DailyCostTangibleLine, "Tangibles"),
)

log = logging.getLogger("app.daily_cost")

# SQLite ignores SELECT FOR UPDATE. These process locks also serialize snapshot
# creation and whole-sheet replacements in single-process local deployments.
_WRITE_LOCK = threading.RLock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: Decimal | int | str) -> Decimal:
    amount = Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)
    if abs(amount) > MONEY_LIMIT:
        raise HTTPException(
            status_code=422,
            detail="This amount is too large for the cost ledger. Reduce the quantity or rate, "
                   "or record the cost in a more suitable unit.",
        )
    return amount


def _rate(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(RATE, rounding=ROUND_HALF_UP)


def _fx(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(FX, rounding=ROUND_HALF_UP)


def _label(code: str, name: str) -> str:
    return " — ".join(part for part in (code, name) if part)


def classify_activity(activity: Any) -> str:
    """Derive the Planned / UPA / NPT classification from a Master Data Activity.

    The daily cost entry has no separate classification field: the selected
    Activity already carries that meaning (organizations name/code their
    activities accordingly), so the line classification is derived from the
    activity's code and name and stored with each priced line.
    """
    text = f"{getattr(activity, 'activity_code', '')} {getattr(activity, 'activity_name', '')}".lower()
    if re.search(r"\bnpt\b", text) or re.search(r"non[ -]?productive", text):
        return "NPT"
    if re.search(r"\bupa\b", text) or "unplanned" in text:
        return "UPA"
    return "Planned"


def _normalise_basis(value: Any) -> str:
    """Accept charging bases as written in an imported sheet, case and spacing aside."""
    text = str(value or "").strip()
    return BASIS_ALIASES.get(text.casefold(), text)


def _actor_name(user: User) -> str:
    return user.full_name or user.email


def _database_http_error(error: SQLAlchemyError, *, operation: str) -> HTTPException:
    """Turn SQLAlchemy write failures into actionable API errors.

    Flushes are deliberately handled the same way as commits.  A flush is a
    write too, and baseline creation performs several flushes before the final
    commit.  Letting one escape as a raw driver exception was the source of
    opaque HTTP 500 responses for otherwise recoverable daily-sheet errors.
    """
    if isinstance(error, IntegrityError):
        return HTTPException(
            status_code=409,
            detail="This daily cost change conflicts with an existing entry or dependent workspace record. "
                   "Refresh the register and retry.",
        )
    if isinstance(error, DataError):
        return HTTPException(
            status_code=422,
            detail="A value on this daily sheet is outside the range the cost ledger accepts. "
                   "Reduce the quantity or rate and save again.",
        )
    reference = uuid4().hex[:12]
    # The traceback is the only place the real driver error survives; the reference
    # ties this log line to the message the user sees, so an administrator can find
    # the failing statement without asking the user to reproduce anything.
    log.exception("Daily cost %s failed with a database error [%s]", operation, reference)
    return HTTPException(
        status_code=503,
        detail="The daily cost ledger could not complete this change because the database rejected it. "
               f"Retry; if it continues, contact the administrator quoting reference {reference}.",
    )


def _flush(db: Session, *, operation: str) -> None:
    """Flush a Daily Cost write without leaking a driver exception as HTTP 500."""
    try:
        db.flush()
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation=operation) from error


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation="save") from error


def _audit(
    db: Session,
    *,
    user: User,
    action: str,
    entity_type: str,
    entity_id: str | None,
    label: str,
    summary: str,
    request: Request | None,
) -> None:
    audit.record(
        db, organization_id=user.organization_id, actor=user, action=action,
        entity_type=entity_type, entity_id=entity_id, entity_label=label,
        summary=summary, request=request,
    )


def _lock_row_id(db: Session, model: type[Any], *criteria: Any) -> str | None:
    """Row-lock one workspace row with a statement PostgreSQL will accept.

    ``SELECT ... FOR UPDATE`` is rejected by PostgreSQL when the statement joins
    the nullable side of an outer join ("FOR UPDATE cannot be applied to the
    nullable side of an outer join").  The Daily Cost models declare several
    ``lazy="joined"`` many-to-one references, so locking an entity-shaped SELECT
    -- or any SELECT that eager-loads one -- raises a driver error on PostgreSQL
    while SQLite silently ignores the locking clause, which is why the SQLite
    test suite stayed green.  Selecting only the primary key keeps the locking
    statement single-table by construction, no matter which loader strategies the
    models declare now or later.  The row is then read normally inside the same
    transaction, while the lock is held.

    Returns the locked row id, or ``None`` when no row matched.
    """
    return db.scalar(select(model.id).where(*criteria).with_for_update())  # type: ignore[attr-defined]


def _get_entry(
    db: Session,
    entry_id: str,
    organization_id: str,
    *,
    deleted: bool | None = False,
    lock: bool = False,
) -> DailyCostEntry:
    if lock:
        # Lock first, load second: the lock must not join (see _lock_row_id) while
        # the sheet and its baseline still need their usual eager loading.
        criteria: list[Any] = [
            DailyCostEntry.id == entry_id, DailyCostEntry.organization_id == organization_id,
        ]
        if deleted is not None:
            criteria.append(DailyCostEntry.is_deleted.is_(deleted))
        if _lock_row_id(db, DailyCostEntry, *criteria) is None:
            raise HTTPException(status_code=404, detail="Daily cost entry not found in this workspace")
    statement = (
        select(DailyCostEntry)
        .options(
            joinedload(DailyCostEntry.rig), joinedload(DailyCostEntry.well), joinedload(DailyCostEntry.afe),
            selectinload(DailyCostEntry.baseline).selectinload(DailyCostBaseline.budget_lines),
            selectinload(DailyCostEntry.baseline).selectinload(DailyCostBaseline.service_rates),
            selectinload(DailyCostEntry.baseline).selectinload(DailyCostBaseline.well_sections).selectinload(DailyCostBaselineSection.phases),
            selectinload(DailyCostEntry.baseline).selectinload(DailyCostBaseline.exchange_rates),
            selectinload(DailyCostEntry.rate_baseline).selectinload(DailyCostWellRateBaseline.catalogue_rates),
            selectinload(DailyCostEntry.service_lines), selectinload(DailyCostEntry.consumable_lines),
            selectinload(DailyCostEntry.tangible_lines),
        )
        .where(DailyCostEntry.id == entry_id, DailyCostEntry.organization_id == organization_id)
    )
    if deleted is not None:
        statement = statement.where(DailyCostEntry.is_deleted.is_(deleted))
    entry = db.scalars(statement.execution_options(populate_existing=True)).unique().first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Daily cost entry not found in this workspace")
    return entry


def _section_map(baseline: DailyCostBaseline) -> dict[str, DailyCostBaselineSection]:
    return {section.hole_section_id: section for section in baseline.well_sections}


def _section_option(section: DailyCostBaselineSection) -> DailyCostSectionOption:
    return DailyCostSectionOption(
        hole_section_id=section.hole_section_id, section_code=section.section_code_snapshot,
        section_name=section.section_name_snapshot, from_depth=section.from_depth,
        to_depth=section.to_depth, total_days=section.total_days,
        phases=[{
            "phase_id": phase.phase_id, "phase_code": phase.phase_code_snapshot,
            "phase_name": phase.phase_name_snapshot, "days": phase.days,
        } for phase in section.phases],
    )


def _active_master(db: Session, model: Any, record_id: str, organization_id: str, label: str, *, allow_deleted: bool = False) -> Any:
    row = db.scalar(select(model).where(model.id == record_id, model.organization_id == organization_id))
    if row is None:
        raise HTTPException(status_code=422, detail=f"Select a {label} from this workspace")
    if row.is_deleted and not allow_deleted:
        raise HTTPException(status_code=422, detail=f"{label.capitalize()} is in Deleted Entries; choose an active record")
    return row


def _well_or_422(db: Session, organization_id: str, well_id: str) -> Well:
    well = db.scalars(
        select(Well)
        .options(
            joinedload(Well.rig), selectinload(Well.sections).selectinload(WellSection.hole_section),
            selectinload(Well.sections).selectinload(WellSection.phases).joinedload(WellPhase.phase),
        )
        .where(Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False))
    ).unique().first()
    if well is None:
        raise HTTPException(status_code=422, detail="Select an active well from this workspace")
    if well.rig is None or well.rig.organization_id != organization_id or well.rig.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the well's rig before tracking daily costs")
    if well.status != "active":
        raise HTTPException(status_code=409, detail="Daily costs cannot be started for a completed well")
    if well.config_status != "configured" or not well.sections:
        raise HTTPException(status_code=422, detail="Configure and sign off the well's section and phase plan before tracking costs")
    return well


def _estimate_for_daily_cost(db: Session, organization_id: str, afe: Afe) -> AfeEstimateOut:
    """Load an AFE estimate with a user-facing error for malformed legacy data.

    Daily-sheet creation is a workflow boundary. A stale or partially migrated
    AFE must not make that boundary return an unhelpful driver/serialization
    500; it should tell the operator which prerequisite needs attention.
    """
    afe_code = afe.afe_code
    try:
        return afe_service.get_estimate(db, organization_id, afe.id)
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation="reading the AFE estimate") from error
    except Exception as error:  # noqa: BLE001 - isolate malformed legacy AFE data from Daily Cost
        db.rollback()
        log.exception("Unable to load AFE %s while starting a daily cost sheet", afe_code)
        raise HTTPException(
            status_code=422,
            detail=f"The saved estimate for {afe_code} cannot be used for Daily Cost Management. "
                   "Open the AFE, correct or resave its estimate, then retry.",
        ) from error


def _afe_or_422(db: Session, organization_id: str, afe_id: str, well_id: str) -> Afe:
    afe = db.scalar(select(Afe).where(Afe.id == afe_id, Afe.organization_id == organization_id))
    if afe is None or afe.is_deleted:
        raise HTTPException(status_code=422, detail="Select an active AFE from this workspace")
    if afe.well_id != well_id:
        raise HTTPException(status_code=422, detail="The selected AFE does not belong to this well")
    if afe.estimate_saved_at is None:
        raise HTTPException(status_code=422, detail=f"Save the estimate for {afe.afe_code} before starting daily cost tracking")
    estimate = _estimate_for_daily_cost(db, organization_id, afe)
    if estimate.summary.total is None or not estimate.summary.currency.converted:
        raise HTTPException(status_code=422, detail=f"Complete the AFE currency setup for {afe.afe_code} before comparing daily costs")
    return afe


def _catalogue_rate_value(item: Any, kind: str) -> Decimal:
    if kind in ("drill_bit", "tangible") and item.final_cost is not None:
        return Decimal(item.final_cost)
    return Decimal(item.unit_rate)


def _capture_catalogue_rates(db: Session, organization_id: str, well: Well, baseline: DailyCostWellRateBaseline) -> list[DailyCostCatalogueRateSnapshot]:
    specs = (
        ("mud_chemical", MudChemical, "chemical_code", "chemical_name"),
        ("cement_additive", CementAdditive, "additive_code", "additive_name"),
        ("fuel", FuelType, "fuel_code", "fuel_name"),
        ("drill_bit", DrillBit, "bit_code", "bit_name"),
        ("tangible", Tangible, "tangible_code", "tangible_name"),
    )
    snapshots: list[DailyCostCatalogueRateSnapshot] = []
    for kind_order, (kind, model, code_attr, name_attr) in enumerate(specs):
        rows = db.scalars(
            select(model).where(model.organization_id == organization_id, model.is_deleted.is_(False))
            .order_by(getattr(model, code_attr), model.id)
        ).all()
        for index, row in enumerate(rows):
            snapshots.append(DailyCostCatalogueRateSnapshot(
                id=uid(), organization_id=organization_id, rate_baseline_id=baseline.id, well_id=well.id,
                item_kind=kind, item_id=row.id, item_code=getattr(row, code_attr), item_name=getattr(row, name_attr),
                unit_rate=_rate(_catalogue_rate_value(row, kind)), currency=(row.currency or "").strip().upper(),
                uom=getattr(row, "uom", "") or "unit", revision_number=int(getattr(row, "current_revision_number", 0) or 0),
                effective_date=getattr(row, "effective_date", None), sort_order=kind_order * 100000 + index,
            ))
    return snapshots


def _rate_baseline_by_id(
    db: Session, organization_id: str, rate_baseline_id: str,
) -> DailyCostWellRateBaseline:
    """The well's immutable catalogue-rate snapshot, with its captured rates."""
    baseline = db.scalars(
        select(DailyCostWellRateBaseline)
        .options(selectinload(DailyCostWellRateBaseline.catalogue_rates))
        .where(DailyCostWellRateBaseline.id == rate_baseline_id,
               DailyCostWellRateBaseline.organization_id == organization_id)
        .execution_options(populate_existing=True)
    ).unique().first()
    if baseline is None:
        raise HTTPException(status_code=404, detail="Daily cost rate baseline not found in this workspace")
    return baseline


def _baseline_for(db: Session, organization_id: str, baseline_id: str) -> DailyCostBaseline:
    """The AFE's locked baseline snapshot, with every child the day sheet prices from."""
    baseline = db.scalars(
        select(DailyCostBaseline)
        .options(
            selectinload(DailyCostBaseline.budget_lines), selectinload(DailyCostBaseline.service_rates),
            selectinload(DailyCostBaseline.well_sections).selectinload(DailyCostBaselineSection.phases),
            selectinload(DailyCostBaseline.exchange_rates),
            selectinload(DailyCostBaseline.rate_baseline).selectinload(DailyCostWellRateBaseline.catalogue_rates),
        )
        .where(DailyCostBaseline.id == baseline_id, DailyCostBaseline.organization_id == organization_id)
        .execution_options(populate_existing=True)
    ).unique().first()
    if baseline is None:
        raise HTTPException(status_code=404, detail="Daily cost baseline not found in this workspace")
    return baseline


def _ensure_rate_baseline(db: Session, organization_id: str, well: Well, user: User) -> DailyCostWellRateBaseline:
    with _WRITE_LOCK:
        locked_id = _lock_row_id(
            db, DailyCostWellRateBaseline,
            DailyCostWellRateBaseline.organization_id == organization_id,
            DailyCostWellRateBaseline.well_id == well.id,
        )
        if locked_id is not None:
            return _rate_baseline_by_id(db, organization_id, locked_id)
        baseline = DailyCostWellRateBaseline(
            id=uid(), organization_id=organization_id, well_id=well.id, locked_at=_now(), locked_by=_actor_name(user)
        )
        baseline.catalogue_rates = _capture_catalogue_rates(db, organization_id, well, baseline)
        db.add(baseline)
        try:
            _flush(db, operation="locking the well catalogue-rate baseline")
        except HTTPException as error:
            # Another application worker may have created the immutable
            # well-level snapshot between our existence check and flush. The
            # winner's snapshot is safe to reuse; only re-raise if it cannot be
            # found after the transaction was rolled back.
            if error.status_code != 409:
                raise
            existing_id = db.scalar(select(DailyCostWellRateBaseline.id).where(
                DailyCostWellRateBaseline.organization_id == organization_id,
                DailyCostWellRateBaseline.well_id == well.id,
            ))
            if existing_id is None:
                raise
            return _rate_baseline_by_id(db, organization_id, existing_id)
        return baseline


def _make_budget_line(
    organization_id: str, baseline: DailyCostBaseline, *, cost_group: str, budget_kind: str,
    item_key: str, item_code: str, item_name: str, source_line_id: str,
    section_id: str | None, phase_id: str | None, quantity: Decimal,
    unit_rate: Decimal, native_amount: Decimal, currency: str, fx_rate: Decimal,
    uom: str, sort_order: int,
) -> DailyCostBaselineBudgetLine:
    return DailyCostBaselineBudgetLine(
        id=uid(), organization_id=organization_id, baseline_id=baseline.id, cost_group=cost_group,
        budget_kind=budget_kind, item_key=item_key, item_code_snapshot=item_code, item_name_snapshot=item_name,
        source_afe_line_id=source_line_id, section_id=section_id, phase_id=phase_id,
        quantity=Decimal(quantity), unit_rate=_rate(unit_rate), native_amount=_money(native_amount),
        currency=(currency or "").strip().upper(), exchange_rate=_fx(fx_rate),
        planned_amount=_money(Decimal(native_amount) * Decimal(fx_rate)), uom=uom or "", sort_order=sort_order,
    )


def _ensure_afe_baseline(
    db: Session, organization_id: str, well: Well, afe: Afe,
    rate_baseline: DailyCostWellRateBaseline, user: User,
) -> DailyCostBaseline:
    with _WRITE_LOCK:
        # Lock the AFE's baseline row (if it exists) without joining: the baseline
        # model loads its rate baseline with ``lazy="joined"``, and PostgreSQL
        # refuses ``FOR UPDATE`` over the nullable side of an outer join.
        locked_id = _lock_row_id(
            db, DailyCostBaseline,
            DailyCostBaseline.organization_id == organization_id, DailyCostBaseline.afe_id == afe.id,
        )
        if locked_id is not None:
            return _baseline_for(db, organization_id, locked_id)
        estimate = _estimate_for_daily_cost(db, organization_id, afe)
        if estimate.summary.total is None or not estimate.summary.currency.converted:
            raise HTTPException(status_code=422, detail="AFE estimate must have a complete standard-currency total")
        standard = estimate.summary.currency.standard_currency.upper()
        conversion: dict[str, Decimal] = {standard: Decimal("1")}
        for row in estimate.summary.currency.exchange_rates:
            conversion[row.currency_code.upper()] = Decimal(row.rate)
        for currency in estimate.summary.currency.currencies:
            conversion.setdefault(currency.upper(), Decimal("1") if currency.upper() == standard else Decimal("0"))
        if any(value <= 0 for value in conversion.values()):
            raise HTTPException(status_code=422, detail="AFE estimate is missing one or more currency conversion factors")

        baseline = DailyCostBaseline(
            id=uid(), organization_id=organization_id, well_id=well.id, afe_id=afe.id,
            rate_baseline_id=rate_baseline.id, afe_code_snapshot=afe.afe_code, afe_name_snapshot=afe.afe_name,
            standard_currency=standard,
            services_total=_money(estimate.summary.services_total or Decimal("0")),
            consumables_total=_money(estimate.summary.consumables_total or Decimal("0")),
            tangibles_total=_money(estimate.summary.tangibles_total or Decimal("0")),
            total_amount=_money(estimate.summary.total), afe_estimate_saved_at=afe.estimate_saved_at,
            locked_at=_now(), locked_by=_actor_name(user),
        )
        baseline.exchange_rates = [
            DailyCostBaselineExchangeRate(
                id=uid(), organization_id=organization_id, currency_code=code, rate=_fx(value), sort_order=index,
            ) for index, (code, value) in enumerate(sorted(conversion.items()))
        ]
        section_snapshots: dict[str, DailyCostBaselineSection] = {}
        for section_index, section in enumerate(estimate.well.sections):
            snapshot = DailyCostBaselineSection(
                id=uid(), organization_id=organization_id, hole_section_id=section.hole_section_id,
                section_code_snapshot=section.section_code, section_name_snapshot=section.section_name,
                from_depth=Decimal(section.from_depth), to_depth=Decimal(section.to_depth),
                total_days=Decimal(section.total_days), sort_order=section_index,
            )
            snapshot.phases = [
                DailyCostBaselinePhase(
                    id=uid(), organization_id=organization_id, phase_id=phase.phase_id,
                    phase_code_snapshot=phase.phase_code, phase_name_snapshot=phase.phase_name,
                    days=Decimal(phase.days), sort_order=phase_index,
                ) for phase_index, phase in enumerate(section.phases)
            ]
            section_snapshots[section.hole_section_id] = snapshot
        baseline.well_sections = list(section_snapshots.values())

        budgets: list[DailyCostBaselineBudgetLine] = []
        service_rates: list[DailyCostBaselineServiceRate] = []
        order = 0
        for line in estimate.services:
            if not line.id:
                raise HTTPException(status_code=409, detail="A saved AFE service line has no stable identifier")
            currency, factor = line.currency.upper(), conversion.get(line.currency.upper())
            if factor is None or factor <= 0:
                raise HTTPException(status_code=422, detail=f"AFE is missing a conversion factor for {currency}")
            budgets.append(_make_budget_line(
                organization_id, baseline, cost_group="Services", budget_kind="service", item_key=line.id,
                item_code=line.service_code, item_name=line.service_name, source_line_id=line.id,
                section_id=line.hole_section_id, phase_id=line.phase_id, quantity=Decimal("1"),
                unit_rate=Decimal(line.service_amount), native_amount=Decimal(line.amount), currency=currency,
                fx_rate=factor, uom="", sort_order=order,
            ))
            order += 1
            if line.charging_basis == "Day Rate":
                for index, row in enumerate(line.rates):
                    service_rates.append(DailyCostBaselineServiceRate(
                        id=uid(), organization_id=organization_id, baseline=baseline, service_id=line.service_id,
                        source_afe_line_id=line.id, service_code_snapshot=line.service_code,
                        service_name_snapshot=line.service_name, charging_basis=line.charging_basis,
                        rate_kind="day_rate", charge_category=row.category, hole_section_id=line.hole_section_id,
                        phase_id=line.phase_id, unit_rate=_rate(row.unit_rate), currency=currency,
                        sort_order=order * 100 + index,
                    ))
            elif line.charging_basis == "Per Service Rate":
                service_rates.append(DailyCostBaselineServiceRate(
                    id=uid(), organization_id=organization_id, baseline=baseline, service_id=line.service_id,
                    source_afe_line_id=line.id, service_code_snapshot=line.service_code,
                    service_name_snapshot=line.service_name, charging_basis=line.charging_basis,
                    rate_kind="per_service", charge_category="Operation", hole_section_id=line.hole_section_id,
                    phase_id=line.phase_id, unit_rate=_rate(line.service_amount), currency=currency,
                    sort_order=order * 100,
                ))
            else:
                for index, row in enumerate(line.section_rates):
                    service_rates.append(DailyCostBaselineServiceRate(
                        id=uid(), organization_id=organization_id, baseline=baseline, service_id=line.service_id,
                        source_afe_line_id=line.id, service_code_snapshot=line.service_code,
                        service_name_snapshot=line.service_name, charging_basis=line.charging_basis,
                        rate_kind="per_section", charge_category="Operation", hole_section_id=row.hole_section_id,
                        phase_id=row.phase_id, unit_rate=_rate(row.amount), currency=currency,
                        sort_order=order * 100 + index,
                    ))

        for line in estimate.consumables:
            if not line.id:
                raise HTTPException(status_code=409, detail="A saved AFE consumable line has no stable identifier")
            currency, factor = line.currency.upper(), conversion.get(line.currency.upper())
            if factor is None or factor <= 0:
                raise HTTPException(status_code=422, detail=f"AFE is missing a conversion factor for {currency}")
            if line.category == "Drill Bits":
                kind, item_key = "drill_bit", line.drill_bit_id or ""
                item_code, item_name = line.bit_code or "DRILL-BIT", line.bit_name or "Drill bit allowance"
                rate_value, uom = Decimal(line.effective_rate or line.captured_rate or Decimal("0")), "unit"
            else:
                kind, item_key = "consumable_category", line.category
                item_code = f"BULK-{line.category.upper().replace(' ', '-')}"
                item_name, rate_value, uom = f"{line.category} allowance", Decimal("0"), ""
            budgets.append(_make_budget_line(
                organization_id, baseline, cost_group="Consumables", budget_kind=kind, item_key=item_key,
                item_code=item_code, item_name=item_name, source_line_id=line.id,
                section_id=line.hole_section_id, phase_id=line.phase_id, quantity=Decimal(line.quantity),
                unit_rate=rate_value, native_amount=Decimal(line.amount), currency=currency,
                fx_rate=factor, uom=uom, sort_order=order,
            ))
            order += 1

        for line in estimate.tangibles:
            if not line.id:
                raise HTTPException(status_code=409, detail="A saved AFE tangible line has no stable identifier")
            currency, factor = line.currency.upper(), conversion.get(line.currency.upper())
            if factor is None or factor <= 0:
                raise HTTPException(status_code=422, detail=f"AFE is missing a conversion factor for {currency}")
            budgets.append(_make_budget_line(
                organization_id, baseline, cost_group="Tangibles", budget_kind="tangible", item_key=line.tangible_id,
                item_code=line.tangible_code, item_name=line.tangible_name, source_line_id=line.id,
                section_id=None, phase_id=None, quantity=Decimal(line.quantity), unit_rate=Decimal(line.effective_rate),
                native_amount=Decimal(line.amount), currency=currency, fx_rate=factor, uom=line.uom, sort_order=order,
            ))
            order += 1
        baseline.budget_lines = budgets
        baseline.service_rates = service_rates
        db.add(baseline)
        try:
            _flush(db, operation="locking the AFE baseline")
        except HTTPException as error:
            # A second worker can race the first sheet for the same AFE. Once
            # the insert conflict rolls back, reuse the immutable baseline that
            # won the race instead of presenting a transient server failure.
            if error.status_code != 409:
                raise
            existing_id = db.scalar(select(DailyCostBaseline.id).where(
                DailyCostBaseline.organization_id == organization_id,
                DailyCostBaseline.afe_id == afe.id,
            ))
            if existing_id is None:
                raise
            return _baseline_for(db, organization_id, existing_id)
        return baseline


def _rate_snapshot_index(rate_baseline: DailyCostWellRateBaseline) -> dict[tuple[str, str], DailyCostCatalogueRateSnapshot]:
    return {(row.item_kind, row.item_id): row for row in rate_baseline.catalogue_rates}


def _daily_rate_option(row: DailyCostBaselineServiceRate, section_names: dict[str, str], phase_names: dict[tuple[str, str], str]) -> DailyCostRateOut:
    label = _label(row.service_code_snapshot, row.service_name_snapshot)
    if row.charge_category and row.rate_kind == "day_rate":
        label += f" · {row.charge_category}"
    if row.hole_section_id:
        label += f" · {section_names.get(row.hole_section_id, 'Section')}"
    if row.phase_id and row.hole_section_id:
        label += f" / {phase_names.get((row.hole_section_id, row.phase_id), 'Phase')}"
    return DailyCostRateOut(
        id=row.id, service_id=row.service_id, source_afe_line_id=row.source_afe_line_id,
        service_code=row.service_code_snapshot, service_name=row.service_name_snapshot,
        charging_basis=row.charging_basis, rate_kind=row.rate_kind, charge_category=row.charge_category,
        hole_section_id=row.hole_section_id, section_label=section_names.get(row.hole_section_id or "", ""),
        phase_id=row.phase_id, phase_label=phase_names.get((row.hole_section_id or "", row.phase_id or ""), ""),
        unit_rate=Decimal(row.unit_rate), currency=row.currency,
        display_name=f"{label} · {row.currency} {Decimal(row.unit_rate):,.4f}",
    )


def _snapshot_option(row: DailyCostCatalogueRateSnapshot) -> DailyCostCatalogueOption:
    _, _, _, category = CONSUMABLE_KIND_MODEL[row.item_kind]
    return DailyCostCatalogueOption(
        id=row.item_id, item_kind=row.item_kind, category=category, item_code=row.item_code,
        item_name=row.item_name, description="", uom=row.uom, captured_rate=Decimal(row.unit_rate),
        currency=row.currency, revision_number=row.revision_number, effective_date=row.effective_date,
        display_name=_label(row.item_code, row.item_name),
    )


def _baseline_out(baseline: DailyCostBaseline, rate_baseline: DailyCostWellRateBaseline) -> DailyCostBaselineOut:
    sections = _section_map(baseline)
    section_names = {key: _label(row.section_code_snapshot, row.section_name_snapshot) for key, row in sections.items()}
    phase_names = {
        (section.hole_section_id, phase.phase_id): _label(phase.phase_code_snapshot, phase.phase_name_snapshot)
        for section in baseline.well_sections for phase in section.phases
    }
    return DailyCostBaselineOut(
        id=baseline.id, rate_baseline_id=rate_baseline.id, afe_id=baseline.afe_id,
        afe_code=baseline.afe_code_snapshot, afe_name=baseline.afe_name_snapshot,
        standard_currency=baseline.standard_currency, total_amount=Decimal(baseline.total_amount),
        locked_at=baseline.locked_at, locked_by=baseline.locked_by,
        afe_estimate_saved_at=baseline.afe_estimate_saved_at,
        catalogue_rates=[_snapshot_option(row) for row in rate_baseline.catalogue_rates],
        service_rates=[_daily_rate_option(row, section_names, phase_names) for row in baseline.service_rates],
        budget_lines=[DailyCostBaselineBudgetOut(
            id=row.id, cost_group=row.cost_group, budget_kind=row.budget_kind, item_key=row.item_key,
            item_code=row.item_code_snapshot, item_name=row.item_name_snapshot, source_afe_line_id=row.source_afe_line_id,
            section_id=row.section_id, phase_id=row.phase_id, quantity=Decimal(row.quantity), unit_rate=Decimal(row.unit_rate),
            native_amount=Decimal(row.native_amount), currency=row.currency, exchange_rate=Decimal(row.exchange_rate),
            planned_amount=Decimal(row.planned_amount), uom=row.uom,
        ) for row in baseline.budget_lines],
        sections=[_section_option(section) for section in baseline.well_sections],
        exchange_rates={row.currency_code: Decimal(row.rate) for row in baseline.exchange_rates},
    )


def context_for_entry(db: Session, organization_id: str, entry_id: str) -> DailyCostBaselineOut:
    entry = _get_entry(db, entry_id, organization_id, deleted=False)
    return _baseline_out(entry.baseline, entry.rate_baseline)


def reference_data(db: Session, organization_id: str) -> DailyCostReference:
    rigs = db.scalars(select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)).all()
    wells = db.scalars(
        select(Well).options(
            joinedload(Well.rig), selectinload(Well.sections).selectinload(WellSection.hole_section),
            selectinload(Well.sections).selectinload(WellSection.phases).joinedload(WellPhase.phase),
        ).where(Well.organization_id == organization_id, Well.is_deleted.is_(False)).order_by(Well.well_code)
    ).unique().all()
    activities = db.scalars(select(Activity).where(Activity.organization_id == organization_id, Activity.is_deleted.is_(False)).order_by(Activity.activity_code)).all()
    sub_activities = db.scalars(
        select(WellSubActivity).options(joinedload(WellSubActivity.activity))
        .where(WellSubActivity.organization_id == organization_id, WellSubActivity.is_deleted.is_(False))
        .order_by(WellSubActivity.well_id, WellSubActivity.sub_activity_code)
    ).all()
    services = db.scalars(
        select(Service).options(joinedload(Service.vendor))
        .where(Service.organization_id == organization_id, Service.is_deleted.is_(False)).order_by(Service.service_code)
    ).unique().all()
    vendors = db.scalars(select(Vendor).where(
        Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False), Vendor.status == "active"
    ).order_by(Vendor.vendor_code)).all()
    currencies = db.scalars(select(Currency).where(
        Currency.organization_id == organization_id, Currency.is_deleted.is_(False)
    ).order_by(Currency.currency_code)).all()
    afe_rows = db.scalars(select(Afe).where(
        Afe.organization_id == organization_id, Afe.is_deleted.is_(False), Afe.estimate_saved_at.is_not(None)
    ).order_by(Afe.afe_code)).all()
    afe_options: list[DailyCostAfeOption] = []
    for afe in afe_rows:
        try:
            estimate = afe_service.get_estimate(db, organization_id, afe.id)
        except HTTPException:
            continue
        except Exception:  # noqa: BLE001 - one unusable AFE must not break the whole module
            db.rollback()  # a failed read would otherwise poison the rest of this request
            log.exception("Skipping AFE %s while building daily cost reference data", afe.afe_code)
            continue
        if estimate.summary.total is None or not estimate.summary.currency.converted:
            continue
        afe_options.append(DailyCostAfeOption(
            id=afe.id, well_id=afe.well_id, afe_code=afe.afe_code, afe_name=afe.afe_name,
            afe_type=afe.afe_type, status=afe.status, standard_currency=estimate.summary.currency.standard_currency,
            total_cost=Decimal(estimate.summary.total), estimate_saved_at=afe.estimate_saved_at,
            display_name=f"{afe.afe_code} — {afe.afe_name} · {estimate.summary.currency.standard_currency} {Decimal(estimate.summary.total):,.2f}",
        ))

    catalogue_items: list[DailyCostCatalogueOption] = []
    specs = (
        ("mud_chemical", MudChemical, "chemical_code", "chemical_name", "Mud Chemicals"),
        ("cement_additive", CementAdditive, "additive_code", "additive_name", "Cement Additives"),
        ("fuel", FuelType, "fuel_code", "fuel_name", "Fuel"),
        ("drill_bit", DrillBit, "bit_code", "bit_name", "Drill Bits"),
        ("tangible", Tangible, "tangible_code", "tangible_name", "Tangibles"),
    )
    for kind, model, code_attr, name_attr, category in specs:
        rows = db.scalars(select(model).where(
            model.organization_id == organization_id, model.is_deleted.is_(False)
        ).order_by(getattr(model, code_attr))).all()
        for row in rows:
            catalogue_items.append(DailyCostCatalogueOption(
                id=row.id, item_kind=kind, category=category, item_code=getattr(row, code_attr),
                item_name=getattr(row, name_attr), description=getattr(row, "description", "") or "",
                uom=getattr(row, "uom", "") or "unit", captured_rate=_rate(_catalogue_rate_value(row, kind)),
                currency=(getattr(row, "currency", "") or "").upper(),
                revision_number=int(getattr(row, "current_revision_number", 0) or 0),
                effective_date=getattr(row, "effective_date", None),
                display_name=_label(getattr(row, code_attr), getattr(row, name_attr)),
            ))
    rig_ids = {row.id for row in rigs}
    return DailyCostReference(
        rigs=[DailyCostRigOption(id=row.id, rig_code=row.rig_code, rig_name=row.rig_name, display_name=_label(row.rig_code, row.rig_name)) for row in rigs],
        wells=[DailyCostWellOption(
            id=well.id, rig_id=well.rig_id, well_code=well.well_code, well_name=well.well_name,
            display_name=_label(well.well_code, well.well_name), status=well.status, config_status=well.config_status,
            sections=[DailyCostSectionOption(
                hole_section_id=section.hole_section_id, section_code=section.hole_section.section_code,
                section_name=section.hole_section.section_name, from_depth=Decimal(section.from_depth),
                to_depth=Decimal(section.to_depth), total_days=sum((Decimal(phase.days) for phase in section.phases), Decimal("0")),
                phases=[{
                    "phase_id": phase.phase_id, "phase_code": phase.phase.phase_code,
                    "phase_name": phase.phase.phase_name, "days": Decimal(phase.days),
                } for phase in section.phases],
            ) for section in well.sections],
        ) for well in wells if well.rig_id in rig_ids and well.rig and not well.rig.is_deleted],
        afes=afe_options,
        activities=[{"id": row.id, "activity_code": row.activity_code, "activity_name": row.activity_name, "display_name": _label(row.activity_code, row.activity_name)} for row in activities],
        sub_activities=[DailyCostSubActivityOption(
            id=row.id, well_id=row.well_id, activity_id=row.activity_id, sub_activity_code=row.sub_activity_code,
            sub_activity_name=row.sub_activity_name, responsible_party=row.responsible_party,
            display_name=_label(row.sub_activity_code, row.sub_activity_name),
        ) for row in sub_activities],
        services=[{
            "id": row.id, "service_code": row.service_code, "service_name": row.service_name,
            "service_category": row.service_category, "provider_type": row.provider_type,
            "vendor_id": row.vendor_id, "vendor_code": row.vendor.vendor_code if row.vendor else "",
            "vendor_name": row.vendor.vendor_name if row.vendor else "",
            "display_name": _label(row.service_code, row.service_name),
        } for row in services],
        catalogue_items=catalogue_items,
        vendors=[DailyCostVendorOption(
            id=row.id, vendor_code=row.vendor_code, vendor_name=row.vendor_name, vendor_type=row.vendor_type,
            status=row.status, display_name=_label(row.vendor_code, row.vendor_name),
        ) for row in vendors],
        currencies=[row.currency_code.upper() for row in currencies],
        charge_categories=["Mobilization", "Demobilization", "Operation", "Standby", "Personnel-Operation", "Personnel-Standby", "Fixed Charge", "Others"],
        charge_bases=["Day Rate", "Per Service Rate", "Per Section Rate"],
        quantity_units=["days", "hours", "service", "section", "unit"],
        classifications=["Planned", "UPA", "NPT"],
        consumable_categories=["Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits"],
    )


def _created_day_or_503(db: Session, organization_id: str, entry_id: str) -> DailyCostDayOut:
    """Read the newly committed sheet without turning a read failure into a raw 500."""
    try:
        return get_day(db, organization_id, entry_id)
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation="reading the created daily cost sheet") from error
    except Exception as error:  # noqa: BLE001 - response hydration is a workflow boundary
        db.rollback()
        log.exception("Daily cost %s was committed but could not be read back", entry_id)
        raise HTTPException(
            status_code=503,
            detail="The daily cost sheet was created, but the server could not load its details. "
                   "Refresh the register before trying again.",
        ) from error


def create_entry(db: Session, organization_id: str, data: DailyCostEntryCreate, user: User, request: Request | None) -> DailyCostDayOut:
    try:
        with _WRITE_LOCK:
            well = _well_or_422(db, organization_id, data.well_id)
            has_sub_activity = db.scalar(
                select(WellSubActivity.id).where(
                    WellSubActivity.organization_id == organization_id,
                    WellSubActivity.well_id == well.id,
                    WellSubActivity.is_deleted.is_(False),
                ).limit(1)
            )
            if not has_sub_activity:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Configure the well sub activities for {well.well_code} in Rig & Well Management "
                        "before entering daily costs. Every daily cost line needs the Activity and Sub activity."
                    ),
                )
            afe = _afe_or_422(db, organization_id, data.afe_id, well.id)
            duplicate = db.scalar(select(DailyCostEntry.id).where(
                DailyCostEntry.organization_id == organization_id, DailyCostEntry.well_id == well.id,
                DailyCostEntry.afe_id == afe.id, DailyCostEntry.cost_date == data.cost_date,
                DailyCostEntry.is_deleted.is_(False),
            ))
            if duplicate:
                raise HTTPException(status_code=409, detail="A daily cost sheet already exists for this well, AFE and date")
            rate_baseline = _ensure_rate_baseline(db, organization_id, well, user)
            baseline = _ensure_afe_baseline(db, organization_id, well, afe, rate_baseline, user)
            cost_code = f"DC-{well.well_code[:35]}-{data.cost_date:%Y%m%d}-{afe.afe_code[:35]}"[:100]
            entry = DailyCostEntry(
                id=uid(), organization_id=organization_id, rig_id=well.rig_id,
                rig_code_snapshot=well.rig.rig_code, rig_name_snapshot=well.rig.rig_name,
                well_id=well.id, well_code_snapshot=well.well_code, well_name_snapshot=well.well_name,
                afe_id=afe.id, afe_code_snapshot=afe.afe_code, afe_name_snapshot=afe.afe_name,
                afe_status_at_create=afe.status, rate_baseline_id=rate_baseline.id, baseline_id=baseline.id,
                daily_cost_code=cost_code, cost_date=data.cost_date, standard_currency=baseline.standard_currency,
                remarks=data.remarks, status="draft", created_by=_actor_name(user), updated_by=_actor_name(user),
            )
            db.add(entry)
            _audit(
                db, user=user, action="create", entity_type="daily_cost", entity_id=entry.id, label=cost_code,
                summary=f"Started daily cost tracking for {well.well_code} on {data.cost_date.isoformat()} under AFE {afe.afe_code}; locked AFE budget and well catalogue rates",
                request=request,
            )
            _commit(db)
    except HTTPException:
        # Baseline construction can have flushed rows waiting in this
        # transaction. Always clear them before the request returns an error so
        # a dependency/session reuse cannot poison the next Daily Cost call.
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation="creating a daily cost sheet") from error
    except (DecimalException, ValidationError, ValueError, TypeError, KeyError, AttributeError) as error:
        db.rollback()
        log.exception("Daily cost creation rejected data for organization %s", organization_id)
        raise HTTPException(
            status_code=422,
            detail="The selected well or AFE contains data that cannot be used to start a Daily Cost Sheet. "
                   "Correct the AFE estimate or well setup, then retry.",
        ) from error
    except Exception as error:  # noqa: BLE001 - do not expose an opaque 500 at this workflow boundary
        db.rollback()
        log.exception("Unexpected Daily Cost creation failure for organization %s", organization_id)
        raise HTTPException(
            status_code=503,
            detail="Daily Cost Management could not start this sheet right now. "
                   "Refresh the register and retry; if it continues, contact the administrator.",
        ) from error
    return _created_day_or_503(db, organization_id, entry.id)


# The remaining validators, save/read lifecycles and dashboard functions follow below.


def _validate_scope(
    baseline: DailyCostBaseline,
    *,
    hole_section_id: str | None,
    phase_id: str | None,
    require_section: bool = False,
) -> tuple[DailyCostBaselineSection | None, DailyCostBaselinePhase | None]:
    sections = _section_map(baseline)
    if require_section and not hole_section_id:
        raise HTTPException(status_code=422, detail="Select a hole section for this daily cost line")
    section = sections.get(hole_section_id or "")
    if hole_section_id and section is None:
        raise HTTPException(status_code=422, detail="The selected hole section is not in this AFE's locked well plan")
    phase = None
    if phase_id:
        if section is None:
            raise HTTPException(status_code=422, detail="Choose a hole section before selecting a phase")
        phase = next((row for row in section.phases if row.phase_id == phase_id), None)
        if phase is None:
            raise HTTPException(status_code=422, detail="The selected phase is not configured under this hole section")
    return section, phase


def _existing_line_maps(entry: DailyCostEntry) -> dict[type[Any], dict[str, Any]]:
    return {
        DailyCostServiceLine: {row.id: row for row in entry.service_lines},
        DailyCostConsumableLine: {row.id: row for row in entry.consumable_lines},
        DailyCostTangibleLine: {row.id: row for row in entry.tangible_lines},
    }


def _check_line_id(line_id: str | None, existing: dict[str, Any], label: str) -> Any | None:
    if not line_id:
        return None
    row = existing.get(line_id)
    if row is None:
        raise HTTPException(status_code=422, detail=f"{label} line {line_id} does not belong to this daily sheet")
    return row


def _get_activity(
    db: Session, organization_id: str, activity_id: str, *, existing: bool, label: str
) -> Activity:
    row = _active_master(db, Activity, activity_id, organization_id, "Activity", allow_deleted=existing)
    if row.is_deleted and not existing:
        raise HTTPException(status_code=422, detail=f"{label}: select an active Master Data Activity")
    return row


def _get_vendor(
    db: Session, organization_id: str, vendor_id: str | None, *, existing: bool, label: str
) -> Vendor | None:
    if not vendor_id:
        return None
    vendor = _active_master(db, Vendor, vendor_id, organization_id, "vendor", allow_deleted=existing)
    if vendor.is_deleted and not existing:
        raise HTTPException(status_code=422, detail=f"{label}: select an active vendor")
    if vendor.status != "active" and not existing:
        raise HTTPException(status_code=422, detail=f"{label}: select an active vendor")
    return vendor


def _get_sub_activity(
    db: Session,
    organization_id: str,
    well_id: str,
    sub_activity_id: str | None,
    activity_id: str,
    *,
    existing: bool,
    label: str,
) -> WellSubActivity:
    if not sub_activity_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{label}: select the well sub activity for this line. Configuring the well's sub activities "
                "in Rig & Well Management is mandatory before daily cost entry."
            ),
        )
    row = db.scalar(
        select(WellSubActivity).where(
            WellSubActivity.id == sub_activity_id,
            WellSubActivity.organization_id == organization_id,
            WellSubActivity.well_id == well_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=422, detail=f"{label}: select a sub activity configured for this well")
    if row.is_deleted and not existing:
        raise HTTPException(status_code=422, detail=f"{label}: the selected sub activity is inactive")
    if row.activity_id != activity_id:
        raise HTTPException(status_code=422, detail=f"{label}: the sub activity must belong to the selected Master Data Activity")
    return row


def _rate_factor(baseline: DailyCostBaseline, currency: str, label: str) -> Decimal:
    code = (currency or "").strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail=f"{label}: enter a currency")
    conversion = {row.currency_code.upper(): Decimal(row.rate) for row in baseline.exchange_rates}
    factor = conversion.get(code)
    if factor is None or factor <= 0:
        raise HTTPException(
            status_code=422,
            detail=f"{label}: {code} is not in the locked AFE currency setup. Use an AFE currency or reopen tracking with a new AFE.",
        )
    return _fx(factor)


def _scope_snapshots(
    baseline: DailyCostBaseline, section: DailyCostBaselineSection | None
) -> tuple[str, str, str, str]:
    if section is None:
        return "", "", "", ""
    phase = next(
        (row for row in section.phases if row.phase_id == getattr(section, "_daily_phase_id", None)),
        None,
    )
    # Callers supply the phase separately below; this helper intentionally only
    # returns the section snapshots and keeps the return shape uniform.
    return section.section_code_snapshot, section.section_name_snapshot, "", ""


def _base_fields(
    db: Session,
    entry: DailyCostEntry,
    data: Any,
    *,
    label: str,
    require_section: bool = False,
    quantity_unit: str = "unit",
    existing_row: Any | None,
    snapshots: dict[tuple[str, str], DailyCostCatalogueRateSnapshot],
) -> tuple[dict[str, Any], Activity, DailyCostBaselineSection | None, DailyCostBaselinePhase | None, Vendor | None, WellSubActivity]:
    existing = existing_row is not None
    activity = _get_activity(db, entry.organization_id, data.activity_id, existing=existing, label=label)
    # Classification (Planned / UPA / NPT) comes from the Master Data Activity,
    # which already serves that job; nothing is entered on the daily line.
    classification = classify_activity(activity)
    section, phase = _validate_scope(
        entry.baseline,
        hole_section_id=data.hole_section_id,
        phase_id=data.phase_id,
        require_section=require_section,
    )
    sub_activity = _get_sub_activity(
        db, entry.organization_id, entry.well_id, data.sub_activity_id, activity.id,
        existing=existing, label=label,
    )
    vendor = _get_vendor(db, entry.organization_id, data.vendor_id, existing=existing, label=label)
    party = data.party_name or (vendor.vendor_name if vendor else "")
    if classification in ("UPA", "NPT") and not (vendor or party):
        raise HTTPException(status_code=422, detail=f"{label}: identify the vendor or responsible party for UPA/NPT")

    code_currency = (data.currency or "").strip().upper()
    override = Decimal(data.override_rate) if data.override_rate is not None else None
    catalogue_snapshot = None
    base_currency = ""
    revision_number = None
    effective_date = None
    if data.override_rate is None and data.currency:
        code_currency = data.currency.strip().upper()
    fx_factor = _rate_factor(entry.baseline, code_currency, label) if code_currency else Decimal("0")
    section_code = section.section_code_snapshot if section else ""
    section_name = section.section_name_snapshot if section else ""
    phase_code = phase.phase_code_snapshot if phase else ""
    phase_name = phase.phase_name_snapshot if phase else ""
    return (
        {
            "organization_id": entry.organization_id,
            "entry_id": entry.id,
            "activity_id": activity.id,
            "activity_code_snapshot": activity.activity_code,
            "activity_name_snapshot": activity.activity_name,
            "section_code_snapshot": section_code,
            "section_name_snapshot": section_name,
            "phase_code_snapshot": phase_code,
            "phase_name_snapshot": phase_name,
            "sub_activity_id": sub_activity.id if sub_activity else None,
            "sub_activity_code_snapshot": sub_activity.sub_activity_code if sub_activity else "",
            "sub_activity_name_snapshot": sub_activity.sub_activity_name if sub_activity else "",
            "sub_activity_party_snapshot": sub_activity.responsible_party if sub_activity else "",
            "hole_section_id": section.hole_section_id if section else None,
            "phase_id": phase.phase_id if phase else None,
            "classification": classification,
            "vendor_id": vendor.id if vendor else None,
            "vendor_code_snapshot": vendor.vendor_code if vendor else "",
            "vendor_name_snapshot": vendor.vendor_name if vendor else "",
            "party_name": party,
            "quantity": Decimal(data.quantity),
            "quantity_unit": quantity_unit,
            "captured_rate": Decimal("0"),
            "override_rate": override,
            "currency": code_currency,
            "exchange_rate": fx_factor,
            "amount": Decimal("0.00"),
            "standard_amount": Decimal("0.00"),
            "rate_source": "",
            "rate_revision_number": revision_number,
            "rate_effective_date": effective_date,
            "baseline_budget_line_id": None,
            "budget_key": "",
            "override_reason": data.override_reason,
            "remarks": data.remarks,
            "sort_order": 0,
        },
        activity,
        section,
        phase,
        vendor,
        sub_activity,
    )


def _budget_by_key(baseline: DailyCostBaseline) -> dict[str, list[DailyCostBaselineBudgetLine]]:
    result: dict[str, list[DailyCostBaselineBudgetLine]] = defaultdict(list)
    for row in baseline.budget_lines:
        result[f"{row.budget_kind}:{row.item_key}"].append(row)
    return result


def _service_rate_or_422(
    entry: DailyCostEntry,
    line: DailyCostServiceLineIn,
    service: Service,
    classification: str,
) -> DailyCostBaselineServiceRate | None:
    baseline = entry.baseline
    if line.baseline_service_rate_id:
        rate = next((row for row in baseline.service_rates if row.id == line.baseline_service_rate_id), None)
        if rate is None or rate.service_id != service.id:
            raise HTTPException(status_code=422, detail=f"Service {service.service_code}: choose a rate from this AFE's locked estimate")
        if line.charging_basis and line.charging_basis != rate.charging_basis:
            raise HTTPException(status_code=422, detail=f"Service {service.service_code}: charging basis must match the saved AFE rate")
        if rate.hole_section_id and line.hole_section_id != rate.hole_section_id:
            raise HTTPException(status_code=422, detail=f"Service {service.service_code}: the AFE rate applies to a different hole section")
        if rate.phase_id and line.phase_id != rate.phase_id:
            raise HTTPException(status_code=422, detail=f"Service {service.service_code}: the AFE rate applies to a different phase")
        if rate.rate_kind == "day_rate" and line.charge_category != rate.charge_category:
            raise HTTPException(status_code=422, detail=f"Service {service.service_code}: charge category must match the selected Day Rate")
        return rate
    if classification == "Planned":
        raise HTTPException(
            status_code=422,
            detail=f"Service {service.service_code}: select its saved AFE rate, or record the service under a UPA/NPT Master Data Activity with a justified rate.",
        )
    if line.override_rate is None:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: an unplanned service needs an entered rate and reason")
    if not line.charging_basis:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: select a charging basis for the manual UPA/NPT rate")
    return None


def _validate_service_unit(line: DailyCostServiceLineIn, basis: str, label: str) -> None:
    if basis == "Day Rate":
        if line.charge_category in SERVICE_ONE_TIME:
            if line.quantity_unit != "unit":
                raise HTTPException(status_code=422, detail=f"{label}: {line.charge_category} is a one-time unit charge")
        elif line.quantity_unit not in ("days", "hours"):
            raise HTTPException(status_code=422, detail=f"{label}: use days or hours for this Day Rate category")
        if line.quantity_unit == "hours" and line.quantity > Decimal("24"):
            raise HTTPException(status_code=422, detail=f"{label}: hours cannot exceed 24 for one daily line; enter days instead")
    elif basis == "Per Service Rate":
        if line.quantity_unit != "service":
            raise HTTPException(status_code=422, detail=f"{label}: select service as the quantity unit for a Per Service Rate")
    elif line.quantity_unit not in ("section", "unit"):
        raise HTTPException(status_code=422, detail=f"{label}: select section as the quantity unit for a Per Section Rate")


def _normalise_service(
    db: Session,
    entry: DailyCostEntry,
    line: DailyCostServiceLineIn,
    existing_rows: dict[str, Any],
    snapshots: dict[tuple[str, str], DailyCostCatalogueRateSnapshot],
    budgets: dict[str, list[DailyCostBaselineBudgetLine]],
) -> tuple[dict[str, Any], Any | None, str]:
    old = _check_line_id(line.id, existing_rows, "Service")
    service = _active_master(
        db, Service, line.service_id, entry.organization_id, "service", allow_deleted=old is not None
    )
    if service.is_deleted and old is None:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code} is inactive in Master Data")
    base, activity, section, phase, selected_vendor, sub_activity = _base_fields(
        db,
        entry,
        line,
        label=f"Service {service.service_code}",
        quantity_unit=line.quantity_unit,
        existing_row=old,
        snapshots=snapshots,
    )
    rate = _service_rate_or_422(entry, line, service, base["classification"])
    basis = rate.charging_basis if rate else line.charging_basis
    if not basis:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: select a charging basis for this line")
    _validate_service_unit(line, basis, f"Service {service.service_code}")
    if basis in ("Per Service Rate", "Per Section Rate") and not line.hole_section_id:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: select a hole section for this charging basis")
    default_vendor = None
    if line.vendor_id is None and service.vendor_id:
        default_vendor = _get_vendor(db, entry.organization_id, service.vendor_id, existing=old is not None, label=f"Service {service.service_code}")
    vendor = selected_vendor or default_vendor
    base["vendor_id"] = vendor.id if vendor else None
    base["vendor_code_snapshot"] = vendor.vendor_code if vendor else ""
    base["vendor_name_snapshot"] = vendor.vendor_name if vendor else ""
    if not base["party_name"] and vendor:
        base["party_name"] = vendor.vendor_name
    if rate:
        base_rate = Decimal(rate.unit_rate)
        base_currency = rate.currency.upper()
        source = "afe_baseline"
        rate_id = rate.id
        budget_key = f"service:{rate.source_afe_line_id}"
        matching = budgets.get(budget_key, [])
        budget = matching[0] if matching else None
        if line.hole_section_id:
            _validate_scope(entry.baseline, hole_section_id=line.hole_section_id, phase_id=line.phase_id, require_section=True)
    else:
        base_rate = Decimal("0")
        base_currency = (line.currency or "").upper()
        source = "manual_unplanned"
        rate_id = None
        budget_key = f"unplanned:service:{service.id}"
        budget = None
    currency = (line.currency or base_currency).upper()
    if not currency:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: a currency is required")
    if base_currency and currency != base_currency:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: daily rate currency must match the locked AFE rate ({base_currency})")
    factor = _rate_factor(entry.baseline, currency, f"Service {service.service_code}")
    selected_rate = _rate(line.override_rate if line.override_rate is not None else base_rate)
    if line.override_rate is not None:
        source = "daily_override" if rate else "manual_unplanned"
    quantity = Decimal(line.quantity)
    if basis == "Day Rate" and line.charge_category in SERVICE_ONE_TIME:
        # Mobilization, demobilization and fixed charges are unit-priced events,
        # not quantities of days.  The UI still accepts a positive quantity so
        # the line schema remains consistent, but the ledger must charge the
        # selected rate exactly once.
        billable_quantity = Decimal("1")
    else:
        billable_quantity = quantity / Decimal("24") if basis == "Day Rate" and line.quantity_unit == "hours" else quantity
    amount = _money(billable_quantity * selected_rate)
    old_override = Decimal(old.override_rate) if old and old.override_rate is not None else None
    old_reason = old.override_reason if old else ""
    label = _label(service.service_code, service.service_name)
    audit_change = None
    if line.override_rate is not None and (old_override != Decimal(line.override_rate) or old_reason != line.override_reason):
        audit_change = (old_override, Decimal(line.override_rate), line.override_reason, currency, label)
    elif old_override is not None and line.override_rate is None:
        audit_change = (old_override, None, old_reason, currency, label)
    base.update(
        {
            "service_id": service.id,
            "service_code_snapshot": service.service_code,
            "service_name_snapshot": service.service_name,
            "charging_basis": basis,
            "charge_category": line.charge_category,
            "baseline_service_rate_id": rate_id,
            "captured_rate": _rate(base_rate),
            "override_rate": _rate(line.override_rate) if line.override_rate is not None else None,
            "currency": currency,
            "exchange_rate": factor,
            "amount": amount,
            "standard_amount": _money(amount * factor),
            "rate_source": source,
            "baseline_budget_line_id": budget.id if budget else None,
            "budget_key": budget_key,
            "sort_order": 0,
            "override_reason": line.override_reason,
            "remarks": line.remarks,
            "quantity": quantity,
            "quantity_unit": line.quantity_unit,
        }
    )
    if audit_change:
        base["_override_audit"] = audit_change
    return base, old, label


def _weighted_rate(lines: Sequence[DailyCostBaselineBudgetLine]) -> Decimal:
    quantity = sum((Decimal(row.quantity) for row in lines), Decimal("0"))
    if quantity > 0:
        return _rate(sum((Decimal(row.quantity) * Decimal(row.unit_rate) for row in lines), Decimal("0")) / quantity)
    return _rate(lines[0].unit_rate) if lines else Decimal("0")


def _normalise_catalogue_line(
    db: Session,
    entry: DailyCostEntry,
    line: DailyCostConsumableLineIn | DailyCostTangibleLineIn,
    model: type[Any],
    kind: str,
    item_id: str,
    existing_rows: dict[str, Any],
    snapshots: dict[tuple[str, str], DailyCostCatalogueRateSnapshot],
    budgets: dict[str, list[DailyCostBaselineBudgetLine]],
    *,
    tangible: bool,
) -> tuple[dict[str, Any], Any | None, str]:
    label_group = "Tangible" if tangible else "Consumable"
    old = _check_line_id(line.id, existing_rows, label_group)
    item = _active_master(db, model, item_id, entry.organization_id, label_group.lower(), allow_deleted=old is not None)
    if item.is_deleted and old is None:
        raise HTTPException(status_code=422, detail=f"{label_group} {getattr(item, 'tangible_code', getattr(item, 'chemical_code', getattr(item, 'additive_code', getattr(item, 'fuel_code', getattr(item, 'bit_code', '')))))} is inactive in Master Data")
    item_code = getattr(item, "tangible_code", getattr(item, "chemical_code", getattr(item, "additive_code", getattr(item, "fuel_code", getattr(item, "bit_code", "")))))
    item_name = getattr(item, "tangible_name", getattr(item, "chemical_name", getattr(item, "additive_name", getattr(item, "fuel_name", getattr(item, "bit_name", "")))))
    base, activity, section, phase, vendor, sub_activity = _base_fields(
        db,
        entry,
        line,
        label=f"{label_group} {item_code}",
        require_section=not tangible,
        quantity_unit="unit",
        existing_row=old,
        snapshots=snapshots,
    )
    snapshot = snapshots.get((kind, item.id))
    if kind == "drill_bit":
        item_key = f"drill_bit:{item.id}"
        matching_budget = budgets.get(item_key, [])
    elif tangible:
        item_key = f"tangible:{item.id}"
        matching_budget = budgets.get(item_key, [])
    else:
        item_key = f"consumable_category:{line.category}"
        matching_budget = budgets.get(item_key, [])
    if kind in ("mud_chemical", "cement_additive", "fuel"):
        # Bulk AFE allowances are budget envelopes, not unit prices. Price each
        # daily chemical/item from the frozen well catalogue, while mapping the
        # actual to its category allowance so the AFE balance still reconciles.
        budget = matching_budget[0] if matching_budget else None
        if snapshot:
            base_rate = Decimal(snapshot.unit_rate)
            base_currency = snapshot.currency.upper()
            source = "catalogue_baseline"
        elif line.override_rate is not None:
            base_rate = Decimal("0")
            base_currency = ""
            source = "manual_unplanned"
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Consumable {item_code}: this item was added after the well's rate snapshot; enter a justified daily rate override.",
            )
    elif matching_budget:
        base_rate = _weighted_rate(matching_budget)
        base_currency = matching_budget[0].currency.upper()
        budget = matching_budget[0]
        source = "afe_baseline"
    elif snapshot:
        base_rate = Decimal(snapshot.unit_rate)
        base_currency = snapshot.currency.upper()
        budget = budgets.get(item_key, [None])[0]
        source = "catalogue_baseline"
    else:
        base_rate = Decimal("0")
        base_currency = ""
        budget = None
        source = "manual_unplanned"
        if line.override_rate is None:
            raise HTTPException(
                status_code=422,
                detail=f"{label_group} {item_code}: this item was added after the well's rate snapshot; enter a justified daily rate override.",
            )
    currency = (line.currency or base_currency).upper()
    if not currency:
        raise HTTPException(status_code=422, detail=f"{label_group} {item_code}: enter a currency")
    if base_currency and currency != base_currency:
        raise HTTPException(status_code=422, detail=f"{label_group} {item_code}: daily rate currency must match the locked baseline rate ({base_currency})")
    factor = _rate_factor(entry.baseline, currency, f"{label_group} {item_code}")
    effective_rate = _rate(line.override_rate if line.override_rate is not None else base_rate)
    quantity = Decimal(line.quantity)
    amount = _money(quantity * effective_rate)
    if line.override_rate is not None:
        source = "daily_override" if base_currency else "manual_unplanned"
    old_override = Decimal(old.override_rate) if old and old.override_rate is not None else None
    old_reason = old.override_reason if old else ""
    label = _label(item_code, item_name)
    audit_change = None
    if line.override_rate is not None and (old_override != Decimal(line.override_rate) or old_reason != line.override_reason):
        audit_change = (old_override, Decimal(line.override_rate), line.override_reason, currency, label)
    elif old_override is not None and line.override_rate is None:
        audit_change = (old_override, None, old_reason, currency, label)
    base.update(
        {
            "captured_rate": _rate(base_rate),
            "override_rate": _rate(line.override_rate) if line.override_rate is not None else None,
            "currency": currency,
            "exchange_rate": factor,
            "amount": amount,
            "standard_amount": _money(amount * factor),
            "rate_source": source,
            "rate_revision_number": snapshot.revision_number if snapshot else None,
            "rate_effective_date": snapshot.effective_date if snapshot else None,
            "baseline_budget_line_id": budget.id if budget else None,
            "budget_key": item_key if budget else f"unplanned:{item_key}",
            "override_reason": line.override_reason,
            "remarks": line.remarks,
            "quantity": quantity,
            "quantity_unit": "unit",
            "catalogue_rate_snapshot_id": snapshot.id if snapshot else None,
        }
    )
    if audit_change:
        base["_override_audit"] = audit_change
    if tangible:
        base.update(
            {
                "tangible_id": item.id,
                "tangible_code_snapshot": item_code,
                "tangible_name_snapshot": item_name,
                "uom": snapshot.uom if snapshot else (getattr(item, "uom", "") or "unit"),
            }
        )
    else:
        assert isinstance(line, DailyCostConsumableLineIn)
        base.update(
            {
                "category": line.category,
                "item_kind": kind,
                "item_id": item.id,
                "item_code_snapshot": item_code,
                "item_name_snapshot": item_name,
                "uom": snapshot.uom if snapshot else (getattr(item, "uom", "") or "unit"),
            }
        )
    return base, old, label


def _reject_duplicate_service_sub_activity(services: list[dict[str, Any]]) -> None:
    """One service may repeat on a date only under a different well sub activity.

    A service operated 18h under sub activity 1, 3h under sub activity 2 and
    3h under sub activity 3 is three separate lines; the same service recorded
    twice for the same sub activity on the same well/date is a duplicate entry.
    """
    seen: dict[tuple[str, str], str] = {}
    for fields in services:
        key = (fields["service_id"], fields.get("sub_activity_id") or "")
        code = fields.get("service_code_snapshot") or fields["service_id"]
        sub_label = fields.get("sub_activity_code_snapshot") or "the same sub activity"
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Service {code} is already entered for sub activity {sub_label} on this date. "
                    "The same service can be recorded again only with a different sub activity."
                ),
            )
        seen[key] = code


def _normalize_payload(
    db: Session,
    entry: DailyCostEntry,
    payload: DailyCostSaveIn,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    existing_maps = _existing_line_maps(entry)
    snapshots = _rate_snapshot_index(entry.rate_baseline)
    budgets = _budget_by_key(entry.baseline)
    services: list[dict[str, Any]] = []
    consumables: list[dict[str, Any]] = []
    tangibles: list[dict[str, Any]] = []
    for order, line in enumerate(payload.services):
        fields, old, label = _normalise_service(
            db, entry, line, existing_maps[DailyCostServiceLine], snapshots, budgets
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        services.append(fields)
    _reject_duplicate_service_sub_activity(services)
    for order, line in enumerate(payload.consumables):
        fields, old, label = _normalise_catalogue_line(
            db, entry, line, CONSUMABLE_KIND_MODEL[line.item_kind][0], line.item_kind, line.item_id,
            existing_maps[DailyCostConsumableLine], snapshots, budgets, tangible=False,
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        consumables.append(fields)
    for order, line in enumerate(payload.tangibles):
        fields, old, label = _normalise_catalogue_line(
            db, entry, line, Tangible, "tangible", line.tangible_id,
            existing_maps[DailyCostTangibleLine], snapshots, budgets, tangible=True,
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        tangibles.append(fields)
    return services, consumables, tangibles


def _sum_group(lines: Sequence[Any]) -> Decimal:
    return _money(sum((Decimal(row.standard_amount) for row in lines), Decimal("0")))


def _sum_classification(lines: Iterable[Any], classification: str) -> Decimal:
    return _money(sum((Decimal(row.standard_amount) for row in lines if row.classification == classification), Decimal("0")))


def _line_snapshot_for_audit(fields: dict[str, Any]) -> tuple[Decimal | None, str, str]:
    value = fields.pop("_override_audit", None)
    if value is None:
        return None, "", ""
    old_rate, new_rate, reason, currency, label = value
    # Kept in the transient dictionary only for the same-transaction audit below.
    fields["_override_audit_data"] = value
    return new_rate, reason, label


def _persist_group(entry: DailyCostEntry, model: type[Any], fields_group: list[dict[str, Any]]) -> tuple[list[Any], list[tuple[Any, Any]]]:
    existing = {row.id: row for row in getattr(entry, {DailyCostServiceLine: "service_lines", DailyCostConsumableLine: "consumable_lines", DailyCostTangibleLine: "tangible_lines"}[model])}
    persisted: list[Any] = []
    overrides: list[tuple[Any, Any]] = []
    for fields in fields_group:
        clean = {key: value for key, value in fields.items() if not key.startswith("_")}
        row_id = clean["id"]
        row = existing.get(row_id)
        audit_change = fields.get("_override_audit")
        if row is None:
            row = model(**clean)
        else:
            for key, value in clean.items():
                if key not in ("id", "created_at"):
                    setattr(row, key, value)
        persisted.append(row)
        if audit_change:
            overrides.append((row, audit_change))
    attr = {DailyCostServiceLine: "service_lines", DailyCostConsumableLine: "consumable_lines", DailyCostTangibleLine: "tangible_lines"}[model]
    setattr(entry, attr, persisted)
    return persisted, overrides


def _upsert_lines(
    db: Session,
    entry: DailyCostEntry,
    services: list[dict[str, Any]],
    consumables: list[dict[str, Any]],
    tangibles: list[dict[str, Any]],
    *,
    user: User,
    request: Request | None,
) -> None:
    _, service_overrides = _persist_group(entry, DailyCostServiceLine, services)
    _, consumable_overrides = _persist_group(entry, DailyCostConsumableLine, consumables)
    _, tangible_overrides = _persist_group(entry, DailyCostTangibleLine, tangibles)
    _flush(db, operation="saving daily cost lines")
    all_lines = [*entry.service_lines, *entry.consumable_lines, *entry.tangible_lines]
    entry.services_total = _sum_group(entry.service_lines)
    entry.consumables_total = _sum_group(entry.consumable_lines)
    entry.tangibles_total = _sum_group(entry.tangible_lines)
    entry.total_cost = _money(entry.services_total + entry.consumables_total + entry.tangibles_total)
    entry.upa_total = _sum_classification(all_lines, "UPA")
    entry.npt_total = _sum_classification(all_lines, "NPT")
    entry.updated_by = _actor_name(user)
    entry.updated_at = _now()
    for line, change in [*service_overrides, *consumable_overrides, *tangible_overrides]:
        old_rate, new_rate, reason, currency, label = change
        if new_rate is None:
            action = "rate_override_removed"
            summary = f"Removed daily override for {label}; prior rate {old_rate} {currency}; reason on prior entry: {reason}"
        else:
            action = "rate_override"
            old_text = f" (previously {old_rate} {currency})" if old_rate is not None else ""
            summary = f"Daily unit-rate override for {label}: {new_rate} {currency}{old_text}. Reason: {reason}"
        _audit(
            db, user=user, action=action, entity_type="daily_cost_line", entity_id=line.id,
            label=entry.daily_cost_code, summary=summary, request=request,
        )


def _budget_label_map(baseline: DailyCostBaseline) -> dict[str, DailyCostBaselineBudgetLine]:
    labels: dict[str, DailyCostBaselineBudgetLine] = {}
    for row in baseline.budget_lines:
        key = f"{row.budget_kind}:{row.item_key}"
        labels.setdefault(key, row)
    return labels


def _line_budget_name(line: Any, labels: dict[str, DailyCostBaselineBudgetLine]) -> str:
    budget = labels.get(line.budget_key)
    if budget:
        return budget.item_name_snapshot
    if isinstance(line, DailyCostServiceLine):
        return _label(line.service_code_snapshot, line.service_name_snapshot)
    if isinstance(line, DailyCostConsumableLine):
        return _label(line.item_code_snapshot, line.item_name_snapshot)
    return _label(line.tangible_code_snapshot, line.tangible_name_snapshot)


def _daily_line_common(line: Any, labels: dict[str, DailyCostBaselineBudgetLine]) -> dict[str, Any]:
    return {
        "id": line.id,
        "activity_id": line.activity_id,
        "activity_code": line.activity_code_snapshot,
        "activity_name": line.activity_name_snapshot,
        "hole_section_id": line.hole_section_id,
        "section_code": line.section_code_snapshot,
        "section_name": line.section_name_snapshot,
        "phase_id": line.phase_id,
        "phase_code": line.phase_code_snapshot,
        "phase_name": line.phase_name_snapshot,
        "sub_activity_id": line.sub_activity_id,
        "sub_activity_code": line.sub_activity_code_snapshot,
        "sub_activity_name": line.sub_activity_name_snapshot,
        "sub_activity_party": line.sub_activity_party_snapshot,
        "classification": line.classification,
        "vendor_id": line.vendor_id,
        "vendor_code": line.vendor_code_snapshot,
        "vendor_name": line.vendor_name_snapshot,
        "party_name": line.party_name,
        "quantity": Decimal(line.quantity),
        "quantity_unit": line.quantity_unit,
        "captured_rate": Decimal(line.captured_rate),
        "override_rate": Decimal(line.override_rate) if line.override_rate is not None else None,
        "effective_rate": Decimal(line.override_rate) if line.override_rate is not None else Decimal(line.captured_rate),
        "currency": line.currency,
        "exchange_rate": Decimal(line.exchange_rate),
        "amount": Decimal(line.amount),
        "standard_amount": Decimal(line.standard_amount),
        "rate_source": line.rate_source,
        "rate_revision_number": line.rate_revision_number,
        "rate_effective_date": line.rate_effective_date,
        "baseline_budget_line_id": line.baseline_budget_line_id,
        "budget_key": line.budget_key,
        "budget_name": _line_budget_name(line, labels),
        "override_reason": line.override_reason,
        "remarks": line.remarks,
    }


def _line_outputs(entry: DailyCostEntry) -> tuple[list[DailyCostServiceLineOut], list[DailyCostConsumableLineOut], list[DailyCostTangibleLineOut]]:
    labels = _budget_label_map(entry.baseline)
    services = [
        DailyCostServiceLineOut(
            **_daily_line_common(row, labels),
            service_id=row.service_id,
            service_code=row.service_code_snapshot,
            service_name=row.service_name_snapshot,
            charging_basis=row.charging_basis,
            charge_category=row.charge_category,
            baseline_service_rate_id=row.baseline_service_rate_id,
        )
        for row in entry.service_lines
    ]
    consumables = [
        DailyCostConsumableLineOut(
            **_daily_line_common(row, labels),
            category=row.category,
            item_kind=row.item_kind,
            item_id=row.item_id,
            item_code=row.item_code_snapshot,
            item_name=row.item_name_snapshot,
            uom=row.uom,
            catalogue_rate_snapshot_id=row.catalogue_rate_snapshot_id,
        )
        for row in entry.consumable_lines
    ]
    tangibles = [
        DailyCostTangibleLineOut(
            **_daily_line_common(row, labels),
            tangible_id=row.tangible_id,
            tangible_code=row.tangible_code_snapshot,
            tangible_name=row.tangible_name_snapshot,
            uom=row.uom,
            catalogue_rate_snapshot_id=row.catalogue_rate_snapshot_id,
        )
        for row in entry.tangible_lines
    ]
    return services, consumables, tangibles


def _entry_out(entry: DailyCostEntry) -> DailyCostEntryOut:
    return DailyCostEntryOut(
        id=entry.id,
        daily_cost_code=entry.daily_cost_code,
        rig_id=entry.rig_id,
        rig_code=entry.rig_code_snapshot,
        rig_name=entry.rig_name_snapshot,
        well_id=entry.well_id,
        well_code=entry.well_code_snapshot,
        well_name=entry.well_name_snapshot,
        afe_id=entry.afe_id,
        afe_code=entry.afe_code_snapshot,
        afe_name=entry.afe_name_snapshot,
        afe_status=entry.afe_status_at_create,
        cost_date=entry.cost_date,
        standard_currency=entry.standard_currency,
        remarks=entry.remarks,
        status=entry.status,
        submitted_at=entry.submitted_at,
        submitted_by=entry.submitted_by,
        status_remarks=entry.status_remarks,
        services_count=len(entry.service_lines),
        consumables_count=len(entry.consumable_lines),
        tangibles_count=len(entry.tangible_lines),
        services_total=Decimal(entry.services_total),
        consumables_total=Decimal(entry.consumables_total),
        tangibles_total=Decimal(entry.tangibles_total),
        total_cost=Decimal(entry.total_cost),
        upa_total=Decimal(entry.upa_total),
        npt_total=Decimal(entry.npt_total),
        rate_baseline_locked_at=entry.rate_baseline.locked_at,
        budget_baseline_locked_at=entry.baseline.locked_at,
        warning_count=entry.warning_count,
        is_deleted=entry.is_deleted,
        deleted_at=entry.deleted_at,
        created_by=entry.created_by,
        updated_by=entry.updated_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _comparison(db: Session, entry: DailyCostEntry, effective_on: date | None = None) -> DailyCostComparison:
    as_of = effective_on or entry.cost_date
    group_names = ("Services", "Consumables", "Tangibles")
    planned_by_group: dict[str, Decimal] = {key: Decimal("0") for key in group_names}
    planned_by_key: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    budget_meta: dict[tuple[str, str], DailyCostBaselineBudgetLine] = {}
    planned_keys: set[tuple[str, str]] = set()
    for row in entry.baseline.budget_lines:
        key = (row.cost_group, f"{row.budget_kind}:{row.item_key}")
        planned_amount = Decimal(row.planned_amount)
        planned_by_group[row.cost_group] += planned_amount
        planned_by_key[key] += planned_amount
        budget_meta.setdefault(key, row)
        planned_keys.add(key)

    entries = list(
        db.scalars(
            select(DailyCostEntry.id).where(
                DailyCostEntry.organization_id == entry.organization_id,
                DailyCostEntry.baseline_id == entry.baseline_id,
                DailyCostEntry.is_deleted.is_(False),
                DailyCostEntry.cost_date <= as_of,
            )
        ).all()
    )
    actual_by_group: dict[str, Decimal] = {key: Decimal("0") for key in group_names}
    actual_by_key: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    unplanned_meta: dict[tuple[str, str], tuple[str, str]] = {}
    actual_all: list[tuple[str, Any]] = []
    if entries:
        for model, group in (
            (DailyCostServiceLine, "Services"),
            (DailyCostConsumableLine, "Consumables"),
            (DailyCostTangibleLine, "Tangibles"),
        ):
            rows = db.scalars(
                select(model)
                .join(DailyCostEntry, model.entry_id == DailyCostEntry.id)
                .where(
                    model.organization_id == entry.organization_id,
                    model.entry_id.in_(entries),
                    DailyCostEntry.is_deleted.is_(False),
                    DailyCostEntry.cost_date <= as_of,
                )
            ).all()
            for row in rows:
                amount = Decimal(row.standard_amount)
                actual_by_group[group] += amount
                actual_by_key[(group, row.budget_key)] += amount
                actual_all.append((group, row))
                if (group, row.budget_key) not in planned_keys:
                    if isinstance(row, DailyCostServiceLine):
                        code, name = row.service_code_snapshot, row.service_name_snapshot
                        kind = "service"
                    elif isinstance(row, DailyCostConsumableLine):
                        code, name = row.item_code_snapshot, row.item_name_snapshot
                        kind = "consumable"
                    else:
                        code, name = row.tangible_code_snapshot, row.tangible_name_snapshot
                        kind = "tangible"
                    unplanned_meta[(group, row.budget_key)] = (code, name or kind)

    comparison_lines: list[DailyCostBudgetComparison] = []
    keys = set(planned_keys) | set(actual_by_key)
    for group, key in sorted(keys, key=lambda item: (group_names.index(item[0]), item[1])):
        metadata = budget_meta.get((group, key))
        actual = _money(actual_by_key[(group, key)])
        planned = _money(planned_by_key[(group, key)])
        if metadata:
            code, name = metadata.item_code_snapshot, metadata.item_name_snapshot
            kind = metadata.budget_kind
        else:
            code, name = unplanned_meta.get((group, key), ("", "Unbudgeted actual"))
            kind = key.split(":", 1)[0]
        comparison_lines.append(
            DailyCostBudgetComparison(
                budget_key=key,
                cost_group=group,
                budget_kind=kind,
                item_code=code,
                item_name=name,
                planned=planned,
                actual_to_date=actual,
                balance=_money(planned - actual),
                is_planned=(group, key) in planned_keys,
            )
        )

    groups = [
        DailyCostComparisonGroup(
            cost_group=group,
            planned=_money(planned_by_group[group]),
            actual_to_date=_money(actual_by_group[group]),
            balance=_money(planned_by_group[group] - actual_by_group[group]),
        )
        for group in group_names
    ]
    planned_total = _money(sum(planned_by_group.values(), Decimal("0")))
    actual_to_date = _money(sum(actual_by_group.values(), Decimal("0")))
    upa = _money(sum((Decimal(row.standard_amount) for _, row in actual_all if row.classification == "UPA"), Decimal("0")))
    npt = _money(sum((Decimal(row.standard_amount) for _, row in actual_all if row.classification == "NPT"), Decimal("0")))
    return DailyCostComparison(
        effective_on=as_of,
        currency=entry.standard_currency,
        planned_total=planned_total,
        actual_to_date=actual_to_date,
        balance=_money(planned_total - actual_to_date),
        over_budget=actual_to_date > planned_total,
        includes_draft_entries=True,
        upa_to_date=upa,
        npt_to_date=npt,
        groups=groups,
        budget_lines=comparison_lines,
    )


def _warnings(entry: DailyCostEntry, comparison: DailyCostComparison) -> list[DailyCostWarnings]:
    warnings: list[DailyCostWarnings] = []
    if comparison.over_budget:
        warnings.append(
            DailyCostWarnings(
                code="afe-over-budget", severity="warning",
                message=f"Actual cost to {comparison.effective_on.isoformat()} is over the AFE budget by {entry.standard_currency} {abs(comparison.balance):,.2f}.",
            )
        )
    if entry.upa_total:
        warnings.append(
            DailyCostWarnings(code="upa-recorded", severity="info", message=f"UPA charges recorded: {entry.standard_currency} {entry.upa_total:,.2f}.")
        )
    if entry.npt_total:
        warnings.append(
            DailyCostWarnings(code="npt-recorded", severity="warning", message=f"NPT charges recorded: {entry.standard_currency} {entry.npt_total:,.2f}.")
        )
    overrides = sum(
        1 for row in [*entry.service_lines, *entry.consumable_lines, *entry.tangible_lines]
        if row.override_rate is not None
    )
    if overrides:
        warnings.append(
            DailyCostWarnings(code="rate-overrides", severity="info", message=f"{overrides} daily rate override(s) are recorded with a reason.")
        )
    return warnings


def get_day(db: Session, organization_id: str, entry_id: str) -> DailyCostDayOut:
    entry = _get_entry(db, entry_id, organization_id, deleted=False)
    services, consumables, tangibles = _line_outputs(entry)
    comparison = _comparison(db, entry)
    return DailyCostDayOut(
        entry=_entry_out(entry),
        services=services,
        consumables=consumables,
        tangibles=tangibles,
        comparison=comparison,
        warnings=_warnings(entry, comparison),
    )


def save_day(
    db: Session,
    organization_id: str,
    entry_id: str,
    payload: DailyCostSaveIn,
    user: User,
    request: Request | None,
    *,
    action: str = "update",
) -> DailyCostDayOut:
    try:
        with _WRITE_LOCK:
            entry = _get_entry(db, entry_id, organization_id, deleted=False, lock=True)
            if entry.status != "draft":
                raise HTTPException(status_code=409, detail="Submitted daily cost sheets are read-only. Reopen the sheet with the authorized workflow first.")
            service_rows, consumable_rows, tangible_rows = _normalize_payload(db, entry, payload)
            entry.remarks = payload.remarks
            _upsert_lines(db, entry, service_rows, consumable_rows, tangible_rows, user=user, request=request)
            entry.warning_count = int(bool(entry.upa_total)) + int(bool(entry.npt_total))
            _audit(
                db,
                user=user,
                action=action,
                entity_type="daily_cost",
                entity_id=entry.id,
                label=entry.daily_cost_code,
                summary=(
                    f"{'Imported' if action == 'import' else 'Saved'} daily costs for {entry.well_code_snapshot} on {entry.cost_date.isoformat()}: "
                    f"{len(service_rows)} service, {len(consumable_rows)} consumable and {len(tangible_rows)} tangible line(s); "
                    f"{entry.standard_currency} {entry.total_cost:,.2f}"
                ),
                request=request,
            )
            _commit(db)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation="saving a daily cost sheet") from error
    except (DecimalException, ValidationError, ValueError, TypeError, KeyError, AttributeError) as error:
        db.rollback()
        log.exception("Daily cost save rejected data for entry %s", entry_id)
        raise HTTPException(
            status_code=422,
            detail="The daily cost lines contain a value that cannot be saved. Review the highlighted line data and retry.",
        ) from error
    except Exception as error:  # noqa: BLE001 - protect the editing workflow from opaque 500s
        db.rollback()
        log.exception("Unexpected Daily Cost save failure for entry %s", entry_id)
        raise HTTPException(
            status_code=503,
            detail="The daily cost sheet could not be saved right now. Refresh the sheet and retry; if it continues, contact the administrator.",
        ) from error
    return _created_day_or_503(db, organization_id, entry.id)


def preview_day(
    db: Session,
    organization_id: str,
    entry_id: str,
    payload: DailyCostSaveIn,
) -> DailyCostPreviewOut:
    entry = _get_entry(db, entry_id, organization_id, deleted=False)
    if entry.status != "draft":
        raise HTTPException(status_code=409, detail="Submitted daily cost sheets cannot be previewed for editing")
    services_in, consumables_in, tangibles_in = _normalize_payload(db, entry, payload)
    existing_maps = _existing_line_maps(entry)
    labels = _budget_label_map(entry.baseline)

    def output(model: type[Any], group: list[dict[str, Any]]) -> list[Any]:
        rows: list[Any] = []
        for fields in group:
            clean = {key: value for key, value in fields.items() if not key.startswith("_")}
            row = model(**clean)
            # Transient request lines use their stored name snapshots. No lookup
            # can alter the rate or label from the immutable baseline.
            rows.append(row)
        return rows

    service_rows = output(DailyCostServiceLine, services_in)
    consumable_rows = output(DailyCostConsumableLine, consumables_in)
    tangible_rows = output(DailyCostTangibleLine, tangibles_in)
    temp = type("PreviewEntry", (), {})()
    temp.baseline = entry.baseline
    temp.service_lines = service_rows
    temp.consumable_lines = consumable_rows
    temp.tangible_lines = tangible_rows
    temp.standard_currency = entry.standard_currency
    # Mirror the stored output mapping without attaching preview rows to the session.
    services_out = [
        DailyCostServiceLineOut(
            **_daily_line_common(row, labels), service_id=row.service_id, service_code=row.service_code_snapshot,
            service_name=row.service_name_snapshot, charging_basis=row.charging_basis, charge_category=row.charge_category,
            baseline_service_rate_id=row.baseline_service_rate_id,
        )
        for row in service_rows
    ]
    consumables_out = [
        DailyCostConsumableLineOut(
            **_daily_line_common(row, labels), category=row.category, item_kind=row.item_kind, item_id=row.item_id,
            item_code=row.item_code_snapshot, item_name=row.item_name_snapshot, uom=row.uom,
            catalogue_rate_snapshot_id=row.catalogue_rate_snapshot_id,
        )
        for row in consumable_rows
    ]
    tangibles_out = [
        DailyCostTangibleLineOut(
            **_daily_line_common(row, labels), tangible_id=row.tangible_id, tangible_code=row.tangible_code_snapshot,
            tangible_name=row.tangible_name_snapshot, uom=row.uom, catalogue_rate_snapshot_id=row.catalogue_rate_snapshot_id,
        )
        for row in tangible_rows
    ]
    all_rows = [*service_rows, *consumable_rows, *tangible_rows]
    service_total = _sum_group(service_rows)
    consumable_total = _sum_group(consumable_rows)
    tangible_total = _sum_group(tangible_rows)
    upa_total = _sum_classification(all_rows, "UPA")
    npt_total = _sum_classification(all_rows, "NPT")
    warnings: list[DailyCostWarnings] = []
    total = _money(service_total + consumable_total + tangible_total)
    if total > entry.baseline.total_amount:
        warnings.append(DailyCostWarnings(code="daily-over-budget", severity="warning", message="This day's actual costs alone exceed the full AFE budget."))
    if upa_total:
        warnings.append(DailyCostWarnings(code="upa-preview", severity="info", message=f"UPA charges in this preview: {entry.standard_currency} {upa_total:,.2f}."))
    if npt_total:
        warnings.append(DailyCostWarnings(code="npt-preview", severity="warning", message=f"NPT charges in this preview: {entry.standard_currency} {npt_total:,.2f}."))
    override_count = sum(1 for row in all_rows if row.override_rate is not None)
    if override_count:
        warnings.append(DailyCostWarnings(code="override-preview", severity="info", message=f"{override_count} daily rate override(s) are priced and will be auditable."))
    return DailyCostPreviewOut(
        services=services_out,
        consumables=consumables_out,
        tangibles=tangibles_out,
        services_total=service_total,
        consumables_total=consumable_total,
        tangibles_total=tangible_total,
        total_cost=total,
        upa_total=upa_total,
        npt_total=npt_total,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Register, status transitions, soft delete/restore and overview
# ---------------------------------------------------------------------------


def list_entries(
    db: Session,
    organization_id: str,
    *,
    deleted: bool = False,
    well_id: str = "",
    afe_id: str = "",
    status: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DailyCostEntryOut]:
    """Daily register, optionally narrowed to one well, AFE, status or date range."""
    rows = db.scalars(
        select(DailyCostEntry)
        .options(
            joinedload(DailyCostEntry.rig), joinedload(DailyCostEntry.well), joinedload(DailyCostEntry.afe),
            joinedload(DailyCostEntry.rate_baseline), joinedload(DailyCostEntry.baseline),
            selectinload(DailyCostEntry.service_lines), selectinload(DailyCostEntry.consumable_lines),
            selectinload(DailyCostEntry.tangible_lines),
        )
        .where(DailyCostEntry.organization_id == organization_id, DailyCostEntry.is_deleted.is_(deleted))
        .order_by(DailyCostEntry.cost_date.desc(), DailyCostEntry.created_at.desc(), DailyCostEntry.id)
    ).unique().all()
    if well_id:
        rows = [row for row in rows if row.well_id == well_id]
    if afe_id:
        rows = [row for row in rows if row.afe_id == afe_id]
    if status:
        rows = [row for row in rows if row.status == status]
    if date_from is not None:
        rows = [row for row in rows if row.cost_date >= date_from]
    if date_to is not None:
        rows = [row for row in rows if row.cost_date <= date_to]
    return [_entry_out(row) for row in rows]


def submit_entry(
    db: Session,
    organization_id: str,
    entry_id: str,
    data: DailyCostStatusIn,
    user: User,
    request: Request | None,
) -> DailyCostDayOut:
    with _WRITE_LOCK:
        entry = _get_entry(db, entry_id, organization_id, deleted=False, lock=True)
        if entry.status != "draft":
            raise HTTPException(status_code=409, detail="Only a Draft daily cost sheet can be submitted")
        entry.status = "submitted"
        entry.submitted_at = _now()
        entry.submitted_by = _actor_name(user)
        entry.status_remarks = data.remarks
        entry.updated_by = _actor_name(user)
        entry.updated_at = _now()
        _audit(
            db, user=user, action="submit", entity_type="daily_cost", entity_id=entry.id,
            label=entry.daily_cost_code,
            summary=f"Submitted daily cost sheet {entry.daily_cost_code} ({entry.standard_currency} {entry.total_cost:,.2f})" + (f": {data.remarks}" if data.remarks else ""),
            request=request,
        )
        _commit(db)
    return _created_day_or_503(db, organization_id, entry.id)


def reopen_entry(
    db: Session,
    organization_id: str,
    entry_id: str,
    data: DailyCostReopenIn,
    user: User,
    request: Request | None,
) -> DailyCostDayOut:
    with _WRITE_LOCK:
        entry = _get_entry(db, entry_id, organization_id, deleted=False, lock=True)
        if entry.status != "submitted":
            raise HTTPException(status_code=409, detail="Only a Submitted daily cost sheet can be reopened")
        entry.status = "draft"
        entry.status_remarks = data.remarks
        entry.updated_by = _actor_name(user)
        entry.updated_at = _now()
        _audit(
            db, user=user, action="reopen", entity_type="daily_cost", entity_id=entry.id,
            label=entry.daily_cost_code,
            summary=f"Reopened submitted daily cost sheet {entry.daily_cost_code} as Draft: {data.remarks}",
            request=request,
        )
        _commit(db)
    return _created_day_or_503(db, organization_id, entry.id)


def soft_delete_entry(
    db: Session,
    organization_id: str,
    entry_id: str,
    user: User,
    request: Request | None,
) -> DailyCostEntryOut:
    with _WRITE_LOCK:
        entry = _get_entry(db, entry_id, organization_id, deleted=False, lock=True)
        if entry.status != "draft":
            raise HTTPException(status_code=409, detail="Reopen a submitted daily sheet before moving it to Deleted Entries")
        entry.is_deleted = True
        entry.deleted_at = _now()
        entry.updated_by = _actor_name(user)
        entry.updated_at = _now()
        _audit(
            db, user=user, action="soft_delete", entity_type="daily_cost", entity_id=entry.id,
            label=entry.daily_cost_code, summary=f"Moved daily cost sheet {entry.daily_cost_code} to Deleted Entries",
            request=request,
        )
        _commit(db)
    return _entry_out(_get_entry(db, entry_id, organization_id, deleted=True))


def _selected_entries(db: Session, organization_id: str, ids: Sequence[str], *, deleted: bool) -> list[DailyCostEntry]:
    unique = list(dict.fromkeys(ids))
    rows = list(db.scalars(
        select(DailyCostEntry)
        .options(joinedload(DailyCostEntry.rate_baseline), joinedload(DailyCostEntry.baseline),
                 selectinload(DailyCostEntry.service_lines), selectinload(DailyCostEntry.consumable_lines),
                 selectinload(DailyCostEntry.tangible_lines))
        .where(DailyCostEntry.organization_id == organization_id, DailyCostEntry.id.in_(unique), DailyCostEntry.is_deleted.is_(deleted))
    ).unique().all())
    if len(rows) != len(unique):
        raise HTTPException(status_code=404, detail="One or more selected daily cost sheets were not found in this workspace")
    return rows


def bulk_soft_delete(
    db: Session, organization_id: str, data: DailyCostIDs, user: User, request: Request | None,
) -> int:
    with _WRITE_LOCK:
        rows = _selected_entries(db, organization_id, data.ids, deleted=False)
        if any(row.status != "draft" for row in rows):
            raise HTTPException(status_code=409, detail="Submitted sheets must be reopened before they can be deleted")
        timestamp = _now()
        for row in rows:
            row.is_deleted = True
            row.deleted_at = timestamp
            row.updated_at = timestamp
            row.updated_by = _actor_name(user)
            _audit(db, user=user, action="soft_delete", entity_type="daily_cost", entity_id=row.id,
                   label=row.daily_cost_code, summary=f"Moved daily cost sheet {row.daily_cost_code} to Deleted Entries", request=request)
        _commit(db)
    return len(rows)


def restore_entry(
    db: Session, organization_id: str, entry_id: str, user: User, request: Request | None,
) -> DailyCostEntryOut:
    with _WRITE_LOCK:
        entry = _get_entry(db, entry_id, organization_id, deleted=True, lock=True)
        duplicate = db.scalar(select(DailyCostEntry.id).where(
            DailyCostEntry.organization_id == organization_id, DailyCostEntry.well_id == entry.well_id,
            DailyCostEntry.afe_id == entry.afe_id, DailyCostEntry.cost_date == entry.cost_date,
            DailyCostEntry.is_deleted.is_(False), DailyCostEntry.id != entry.id,
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="Another active daily sheet already uses this well, AFE and date")
        entry.is_deleted = False
        entry.deleted_at = None
        entry.updated_at = _now()
        entry.updated_by = _actor_name(user)
        _audit(db, user=user, action="restore", entity_type="daily_cost", entity_id=entry.id,
               label=entry.daily_cost_code, summary=f"Restored daily cost sheet {entry.daily_cost_code}", request=request)
        _commit(db)
    return _entry_out(_get_entry(db, entry_id, organization_id, deleted=False))


def bulk_restore(
    db: Session, organization_id: str, data: DailyCostIDs, user: User, request: Request | None,
) -> int:
    with _WRITE_LOCK:
        rows = _selected_entries(db, organization_id, data.ids, deleted=True)
        for row in rows:
            duplicate = db.scalar(select(DailyCostEntry.id).where(
                DailyCostEntry.organization_id == organization_id, DailyCostEntry.well_id == row.well_id,
                DailyCostEntry.afe_id == row.afe_id, DailyCostEntry.cost_date == row.cost_date,
                DailyCostEntry.is_deleted.is_(False),
            ))
            if duplicate:
                raise HTTPException(status_code=409, detail=f"A daily sheet already exists for {row.well_code_snapshot}, {row.afe_code_snapshot} and {row.cost_date}")
        timestamp = _now()
        for row in rows:
            row.is_deleted = False
            row.deleted_at = None
            row.updated_at = timestamp
            row.updated_by = _actor_name(user)
            _audit(db, user=user, action="restore", entity_type="daily_cost", entity_id=row.id,
                   label=row.daily_cost_code, summary=f"Restored daily cost sheet {row.daily_cost_code}", request=request)
        _commit(db)
    return len(rows)


def permanently_delete(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None,
) -> int:
    with _WRITE_LOCK:
        rows = _selected_entries(db, organization_id, ids, deleted=True)
        for row in rows:
            _audit(db, user=user, action="permanent_delete", entity_type="daily_cost", entity_id=row.id,
                   label=row.daily_cost_code, summary=f"Permanently deleted daily cost sheet {row.daily_cost_code}; immutable AFE and well-rate baselines are retained", request=request)
            db.delete(row)
        _commit(db)
    return len(rows)


def _has_audit_access(user: User) -> bool:
    return any(role.is_owner for role in user.roles) or any(
        permission.key == "audit:read" for role in user.roles for permission in role.permissions
    )


def overview(db: Session, organization_id: str, user: User) -> DailyCostOverview:
    active = list(db.scalars(
        select(DailyCostEntry).where(DailyCostEntry.organization_id == organization_id, DailyCostEntry.is_deleted.is_(False))
    ).all())
    deleted_count = int(db.scalar(select(func.count(DailyCostEntry.id)).where(
        DailyCostEntry.organization_id == organization_id, DailyCostEntry.is_deleted.is_(True)
    )) or 0)
    baseline_ids = sorted({row.baseline_id for row in active})
    baselines = list(db.scalars(select(DailyCostBaseline).where(
        DailyCostBaseline.organization_id == organization_id, DailyCostBaseline.id.in_(baseline_ids)
    )).all()) if baseline_ids else []
    planned: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    actual: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    group_planned: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    group_actual: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    planned_by_baseline = {row.id: Decimal(row.total_amount) for row in baselines}
    for baseline in baselines:
        currency = baseline.standard_currency
        planned[currency] += Decimal(baseline.total_amount)
        group_planned[(currency, "Services")] += Decimal(baseline.services_total)
        group_planned[(currency, "Consumables")] += Decimal(baseline.consumables_total)
        group_planned[(currency, "Tangibles")] += Decimal(baseline.tangibles_total)
    actual_by_baseline: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in active:
        currency = row.standard_currency
        amount = Decimal(row.total_cost)
        actual[currency] += amount
        actual_by_baseline[row.baseline_id] += amount
        group_actual[(currency, "Services")] += Decimal(row.services_total)
        group_actual[(currency, "Consumables")] += Decimal(row.consumables_total)
        group_actual[(currency, "Tangibles")] += Decimal(row.tangibles_total)
    currencies = sorted(set(planned) | set(actual))
    planned_out = {code: _money(planned[code]) for code in currencies}
    actual_out = {code: _money(actual[code]) for code in currencies}
    remaining_out = {code: _money(planned[code] - actual[code]) for code in currencies}
    groups = [
        DailyCostGroupSummary(
            currency=currency, cost_group=group, planned=_money(group_planned[(currency, group)]),
            actual=_money(group_actual[(currency, group)]),
            balance=_money(group_planned[(currency, group)] - group_actual[(currency, group)]),
        )
        for currency in currencies for group in ("Services", "Consumables", "Tangibles")
    ]
    over_budget = sum(1 for baseline_id, amount in actual_by_baseline.items() if amount > planned_by_baseline.get(baseline_id, Decimal("0")))
    today = date.today()
    start = today - timedelta(days=29)
    trend_rows = db.execute(
        select(
            DailyCostEntry.cost_date, DailyCostEntry.standard_currency,
            func.sum(DailyCostEntry.total_cost), func.sum(DailyCostEntry.upa_total), func.sum(DailyCostEntry.npt_total),
        ).where(
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.is_deleted.is_(False), DailyCostEntry.cost_date >= start,
        ).group_by(DailyCostEntry.cost_date, DailyCostEntry.standard_currency)
        .order_by(DailyCostEntry.cost_date, DailyCostEntry.standard_currency)
    ).all()
    trend = [DailyCostTrendPoint(
        cost_date=row[0], currency=row[1], actual=_money(row[2] or 0), upa=_money(row[3] or 0), npt=_money(row[4] or 0)
    ) for row in trend_rows]
    recent = []
    if _has_audit_access(user):
        rows = db.scalars(select(AuditLog).where(
            AuditLog.organization_id == organization_id,
            AuditLog.entity_type.in_(("daily_cost", "daily_cost_line", "daily_cost_export")),
        ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(8)).all()
        recent = [{
            "id": row.id, "action": row.action, "entity_type": row.entity_type,
            "entity_label": row.entity_label, "summary": row.summary, "created_at": row.created_at,
        } for row in rows]
    return DailyCostOverview(
        active_entries=len(active), deleted_entries=deleted_count,
        submitted_entries=sum(1 for row in active if row.status == "submitted"),
draft_entries=sum(1 for row in active if row.status == "draft"),
        wells_tracked=len({row.well_id for row in active}), active_baselines=len(baselines),
        over_budget_afes=over_budget, total_planned_by_currency=planned_out,
        actual_to_date_by_currency=actual_out, remaining_by_currency=remaining_out,
        groups=groups, trend=trend, recent_activity=recent,
    )


# ---------------------------------------------------------------------------
# Whole-well cost analysis
# ---------------------------------------------------------------------------

FACTOR_LABELS = {
    "cost_group": "Cost group",
    "classification": "Planned / UPA / NPT",
    "section": "Hole section",
    "phase": "Phase",
    "activity": "Master Data activity",
    "sub_activity": "Well sub activity",
    "party": "Responsible party",
    "rate_source": "Rate source",
    "currency": "Currency (as charged)",
    "item": "Service, consumable and tangible",
}
FACTOR_COLUMNS: dict[str, tuple[str, ...]] = {
    "cost_group": ("cost_group",),
    "classification": ("classification",),
    "section": ("section_code", "section_name"),
    "phase": ("section_code", "phase_code", "phase_name"),
    "activity": ("activity_code", "activity_name"),
    "sub_activity": ("sub_activity_code", "sub_activity_name", "sub_activity_party"),
    "party": ("vendor_code", "vendor_name", "party_name"),
    "rate_source": ("rate_source",),
    "currency": ("currency", "exchange_rate"),
    "item": ("cost_group", "item_code", "item_name"),
}
RATE_SOURCE_LABELS = {
    "afe_baseline": "Locked AFE rate",
    "catalogue_baseline": "Locked catalogue rate",
    "daily_override": "Daily override (justified)",
    "manual_unplanned": "Manual rate (unplanned)",
    "": "Unrated",
}
NO_SECTION = "Well level (no hole section)"
NO_PHASE = "Whole section"
UNASSIGNED = "Unassigned"


def _line_union(
    organization_id: str,
    well_id: str,
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
) -> Any:
    """One row per daily cost line, whatever its group, with every captured factor.

    The three line tables share the same factor columns, so a UNION ALL keeps one
    column-wise shape for every cut of the ledger (day, section, activity, party).
    """
    parts = []
    for model, group in LINE_MODELS:
        statement = select(
            literal(group).label("cost_group"),
            _item_columns(model).label("item_code"),
            _item_columns(model, name=True).label("item_name"),
            DailyCostEntry.cost_date.label("cost_date"),
            DailyCostEntry.status.label("entry_status"),
            model.section_code_snapshot.label("section_code"),
            model.section_name_snapshot.label("section_name"),
            model.phase_code_snapshot.label("phase_code"),
            model.phase_name_snapshot.label("phase_name"),
            model.activity_code_snapshot.label("activity_code"),
            model.activity_name_snapshot.label("activity_name"),
            model.sub_activity_code_snapshot.label("sub_activity_code"),
            model.sub_activity_name_snapshot.label("sub_activity_name"),
            model.sub_activity_party_snapshot.label("sub_activity_party"),
            model.vendor_code_snapshot.label("vendor_code"),
            model.vendor_name_snapshot.label("vendor_name"),
            model.party_name.label("party_name"),
            model.classification.label("classification"),
            model.rate_source.label("rate_source"),
            model.currency.label("currency"),
            model.exchange_rate.label("exchange_rate"),
            model.budget_key.label("budget_key"),
            model.quantity.label("quantity"),
            model.amount.label("amount"),
            model.standard_amount.label("standard_amount"),
        ).select_from(model).join(DailyCostEntry, model.entry_id == DailyCostEntry.id).where(
            model.organization_id == organization_id,
            DailyCostEntry.well_id == well_id,
            DailyCostEntry.is_deleted.is_(False),
        )
        if not include_draft:
            statement = statement.where(DailyCostEntry.status == "submitted")
        if date_from is not None:
            statement = statement.where(DailyCostEntry.cost_date >= date_from)
        if date_to is not None:
            statement = statement.where(DailyCostEntry.cost_date <= date_to)
        parts.append(statement)
    return union_all(*parts).subquery("daily_cost_lines")


def _item_columns(model: type[Any], name: bool = False) -> Any:
    if model is DailyCostServiceLine:
        return model.service_name_snapshot if name else model.service_code_snapshot
    if model is DailyCostConsumableLine:
        return model.item_name_snapshot if name else model.item_code_snapshot
    return model.tangible_name_snapshot if name else model.tangible_code_snapshot


def _factor_row_labels(dimension: str, values: list[str]) -> tuple[str, str, str]:
    """Return (code, name, detail) for one grouped factor row."""
    if dimension == "cost_group":
        return values[0], values[0], ""
    if dimension == "classification":
        return values[0], values[0], "Planned work" if values[0] == "Planned" else (
            "Unplanned Activity" if values[0] == "UPA" else "Non-Productive Time" if values[0] == "NPT" else "")
    if dimension == "section":
        if not values[0]:
            return UNASSIGNED, NO_SECTION, "Costs not booked to a hole section"
        return values[0], values[1] or values[0], ""
    if dimension == "phase":
        code = " · ".join(value for value in values[:2] if value)
        return code or UNASSIGNED, values[2] or NO_PHASE, values[0] or NO_SECTION
    if dimension == "activity":
        return values[0] or UNASSIGNED, values[1] or values[0] or UNASSIGNED, ""
    if dimension == "sub_activity":
        name = values[1] or values[0] or UNASSIGNED
        return values[0] or UNASSIGNED, name, values[2]
    if dimension == "party":
        name = values[1] or values[2] or UNASSIGNED
        detail = values[2] if values[2] and values[2] != name else ""
        return values[0] or values[2] or UNASSIGNED, name, detail
    if dimension == "rate_source":
        return values[0] or UNASSIGNED, RATE_SOURCE_LABELS.get(values[0], values[0] or UNASSIGNED), ""
    if dimension == "currency":
        factor = Decimal(values[1] or "1")
        return values[0] or UNASSIGNED, values[0] or UNASSIGNED, f"1 {values[0] or '?'} = {factor:,.6f} standard"
    # item
    group = values[0] or ""
    name = values[2] or values[1] or UNASSIGNED
    return values[1] or UNASSIGNED, name, group


def _factor_rows(
    db: Session,
    lines: Any,
    dimension: str,
    *,
    currency: str,
    total: Decimal,
    planned_lookup: Any = None,
    native: bool = False,
) -> list[DailyCostFactorRow]:
    """Group the ledger by one factor. Every grouping column is a stored column."""
    columns = [getattr(lines.c, name) for name in FACTOR_COLUMNS[dimension]]
    amount = lines.c.amount if native else lines.c.standard_amount
    rows = db.execute(
        select(*columns, func.sum(amount).label("total"), func.sum(lines.c.quantity).label("quantity"))
        .select_from(lines)
        .group_by(*columns)
    ).all()
    grouped = [(tuple(str(value or "") for value in row[:-2]), Decimal(row[-2] or 0), Decimal(row[-1] or 0)) for row in rows]
    grouped.sort(key=lambda row: (-row[1], row[0]))
    result: list[DailyCostFactorRow] = []
    for key, amount_value, quantity in grouped:
        code, name, detail = _factor_row_labels(dimension, list(key))
        planned = planned_lookup(list(key)) if planned_lookup else None
        result.append(DailyCostFactorRow(
            key="|".join(key), code=code, name=name, detail=detail,
            amount=_money(amount_value),
            planned=_money(planned) if planned is not None else None,
            balance=_money(planned - amount_value) if planned is not None else None,
            share=(amount_value / total * Decimal("100")).quantize(Decimal("0.01")) if total > 0 else Decimal("0.00"),
            quantity=quantity,
        ))
    return result


def well_cost_summary(
    db: Session,
    organization_id: str,
    well_id: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    include_draft: bool = True,
) -> DailyCostWellSummary:
    """Cost the whole well: daily run sheet, AFE positions and every captured factor."""
    well = db.scalars(
        select(Well).options(joinedload(Well.rig))
        .where(Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False))
    ).unique().first()
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")

    entries = list(db.scalars(
        select(DailyCostEntry)
        .options(joinedload(DailyCostEntry.afe), joinedload(DailyCostEntry.baseline))
        .where(
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.well_id == well_id,
            DailyCostEntry.is_deleted.is_(False),
        )
        .order_by(DailyCostEntry.cost_date, DailyCostEntry.id)
    ).unique().all())
    windowed = [
        row for row in entries
        if (date_from is None or row.cost_date >= date_from) and (date_to is None or row.cost_date <= date_to)
    ]
    baseline_ids = {row.baseline_id for row in entries}
    baselines = list(db.scalars(
        select(DailyCostBaseline).options(
            selectinload(DailyCostBaseline.budget_lines), selectinload(DailyCostBaseline.well_sections)
        ).where(DailyCostBaseline.organization_id == organization_id, DailyCostBaseline.id.in_(baseline_ids))
    ).unique().all()) if baseline_ids else []
    currency = baselines[0].standard_currency if baselines else ""
    for baseline in sorted(baselines, key=lambda row: row.locked_at):
        if baseline.standard_currency != currency:
            currency = ""  # mixed standard currencies cannot be added together
    if len({row.standard_currency for row in entries}) > 1:
        currency = ""

    afe_options: list[DailyCostAfeOption] = []
    for afe in sorted({row.afe_id: row.afe for row in entries}.values(), key=lambda row: row.afe_code):
        entry_rows = [row for row in entries if row.afe_id == afe.id]
        planned_total = sum(
            (Decimal(baseline.total_amount) for baseline in baselines if baseline.afe_id == afe.id), Decimal("0")
        )
        afe_options.append(DailyCostAfeOption(
            id=afe.id, well_id=afe.well_id, afe_code=afe.afe_code, afe_name=afe.afe_name,
            afe_type=afe.afe_type, status=afe.status,
            standard_currency=entry_rows[0].standard_currency if entry_rows else currency,
            total_cost=planned_total, estimate_saved_at=afe.estimate_saved_at,
            display_name=f"{afe.afe_code} — {afe.afe_name} · {entry_rows[0].standard_currency if entry_rows else currency} {planned_total:,.2f}",
        ))

    lines = _line_union(organization_id, well_id, date_from=date_from, date_to=date_to, include_draft=include_draft)
    totals_by_group = {
        str(row[0] or ""): Decimal(row[1] or 0)
        for row in db.execute(
            select(lines.c.cost_group, func.sum(lines.c.standard_amount)).select_from(lines).group_by(lines.c.cost_group)
        ).all()
    }
    services = totals_by_group.get("Services", Decimal("0"))
    consumables = totals_by_group.get("Consumables", Decimal("0"))
    tangibles = totals_by_group.get("Tangibles", Decimal("0"))
    actual_total = _money(services + consumables + tangibles)
    upa = _money(sum((
        Decimal(row[0] or 0) for row in db.execute(
            select(func.sum(lines.c.standard_amount)).select_from(lines).where(lines.c.classification == "UPA")
        ).all()
    ), Decimal("0")))
    npt = _money(sum((
        Decimal(row[0] or 0) for row in db.execute(
            select(func.sum(lines.c.standard_amount)).select_from(lines).where(lines.c.classification == "NPT")
        ).all()
    ), Decimal("0")))

    planned_by_group: dict[str, Decimal] = {}
    planned_days = Decimal("0")
    for baseline in baselines:
        planned_by_group["Services"] = planned_by_group.get("Services", Decimal("0")) + Decimal(baseline.services_total)
        planned_by_group["Consumables"] = planned_by_group.get("Consumables", Decimal("0")) + Decimal(baseline.consumables_total)
        planned_by_group["Tangibles"] = planned_by_group.get("Tangibles", Decimal("0")) + Decimal(baseline.tangibles_total)
        planned_days += sum((Decimal(section.total_days) for section in baseline.well_sections), Decimal("0"))
    planned_total = _money(sum(planned_by_group.values(), Decimal("0")))

    # ---- daily run sheet -----------------------------------------------------
    per_day: dict[date, dict[str, Any]] = {}
    for row in db.execute(
        select(lines.c.cost_date, lines.c.cost_group, func.sum(lines.c.standard_amount))
        .select_from(lines).group_by(lines.c.cost_date, lines.c.cost_group).order_by(lines.c.cost_date)
    ).all():
        day = per_day.setdefault(row[0], {
            "Services": Decimal("0"), "Consumables": Decimal("0"), "Tangibles": Decimal("0"),
            "UPA": Decimal("0"), "NPT": Decimal("0"), "sheets": set(), "statuses": set(),
        })
        day[row[1]] = Decimal(row[2] or 0)
    for row in db.execute(
        select(lines.c.cost_date, lines.c.classification, func.sum(lines.c.standard_amount))
        .select_from(lines).where(lines.c.classification.in_(("UPA", "NPT")))
        .group_by(lines.c.cost_date, lines.c.classification)
    ).all():
        per_day[row[0]][row[1]] = Decimal(row[2] or 0)
    for entry in windowed:
        day = per_day.setdefault(entry.cost_date, {
            "Services": Decimal("0"), "Consumables": Decimal("0"), "Tangibles": Decimal("0"),
            "UPA": Decimal("0"), "NPT": Decimal("0"), "sheets": set(), "statuses": set(),
        })
        day["sheets"].add(entry.id)
        day["statuses"].add(entry.status)
    cumulative = Decimal("0")
    daily: list[DailyCostDailyRow] = []
    for day_date in sorted(per_day):
        values = per_day[day_date]
        total = _money(values["Services"] + values["Consumables"] + values["Tangibles"])
        cumulative = _money(cumulative + total)
        statuses = values["statuses"]
        daily.append(DailyCostDailyRow(
            cost_date=day_date,
            services=_money(values["Services"]), consumables=_money(values["Consumables"]),
            tangibles=_money(values["Tangibles"]), total=total,
            upa=_money(values["UPA"]), npt=_money(values["NPT"]), cumulative=cumulative,
            budget_balance=_money(planned_total - cumulative),
            sheets=len(values["sheets"]),
            status=("submitted" if statuses == {"submitted"} else "draft" if statuses == {"draft"} else "mixed"),
        ))

    # ---- AFE positions -------------------------------------------------------
    positions: list[DailyCostAfePosition] = []
    for option in afe_options:
        entry_rows = [row for row in windowed if row.afe_id == option.id]
        planned = Decimal("0")
        for baseline in baselines:
            if baseline.afe_id == option.id:
                planned += Decimal(baseline.total_amount)
        actual = _money(sum((Decimal(row.total_cost) for row in entry_rows), Decimal("0")))
        days_recorded = sorted({row.cost_date for row in entry_rows})
        positions.append(DailyCostAfePosition(
            afe_id=option.id, afe_code=option.afe_code, afe_name=option.afe_name,
            afe_status=option.status, currency=option.standard_currency,
            planned_total=_money(planned), actual=actual, balance=_money(planned - actual),
            over_budget=actual > planned, sheets=len(entry_rows), days_recorded=len(days_recorded),
            first_day=days_recorded[0] if days_recorded else None,
            last_day=days_recorded[-1] if days_recorded else None,
        ))

    # ---- factors -------------------------------------------------------------
    section_planned: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for baseline in baselines:
        section_labels = {
            section.hole_section_id: (section.section_code_snapshot, section.section_name_snapshot)
            for section in baseline.well_sections
        }
        for budget_line in baseline.budget_lines:
            label = section_labels.get(budget_line.section_id or "", (None, None))
            if label[0]:
                section_planned[(label[0], label[1] or label[0])] += Decimal(budget_line.planned_amount)

    def planned_by_group_lookup(values: list[str]) -> Decimal | None:
        return planned_by_group.get(values[0])

    def planned_by_section_lookup(values: list[str]) -> Decimal | None:
        return section_planned.get((values[0], values[1] or values[0])) if values[0] else None

    factors = [
        DailyCostFactorGroup(
            dimension="cost_group", label=FACTOR_LABELS["cost_group"], currency=currency, total=planned_total,
            rows=_factor_rows(db, lines, "cost_group", currency=currency, total=actual_total,
                              planned_lookup=planned_by_group_lookup),
        ),
        DailyCostFactorGroup(
            dimension="classification", label=FACTOR_LABELS["classification"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "classification", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="section", label=FACTOR_LABELS["section"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "section", currency=currency, total=actual_total,
                              planned_lookup=planned_by_section_lookup),
        ),
        DailyCostFactorGroup(
            dimension="phase", label=FACTOR_LABELS["phase"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "phase", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="activity", label=FACTOR_LABELS["activity"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "activity", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="sub_activity", label=FACTOR_LABELS["sub_activity"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "sub_activity", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="party", label=FACTOR_LABELS["party"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "party", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="rate_source", label=FACTOR_LABELS["rate_source"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "rate_source", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="item", label=FACTOR_LABELS["item"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "item", currency=currency, total=actual_total),
        ),
        DailyCostFactorGroup(
            dimension="currency", label=FACTOR_LABELS["currency"], currency=currency, total=actual_total,
            rows=_factor_rows(db, lines, "currency", currency=currency, total=actual_total, native=True),
        ),
    ]

    # ---- budget reconciliation ----------------------------------------------
    budget_rows = db.execute(
        select(lines.c.budget_key, lines.c.cost_group, func.sum(lines.c.standard_amount))
        .select_from(lines).group_by(lines.c.budget_key, lines.c.cost_group)
    ).all()
    actual_by_key = {str(row[0] or ""): Decimal(row[2] or 0) for row in budget_rows}
    group_by_key = {str(row[0] or ""): str(row[1] or "Services") for row in budget_rows}
    planned_by_key: dict[str, Decimal] = {}
    meta: dict[str, DailyCostBaselineBudgetLine] = {}
    for baseline in baselines:
        for budget_line in baseline.budget_lines:
            key = f"{budget_line.budget_kind}:{budget_line.item_key}"
            planned_by_key[key] = planned_by_key.get(key, Decimal("0")) + Decimal(budget_line.planned_amount)
            meta.setdefault(key, budget_line)
    unplanned_names: dict[tuple[str, str], str] = {}
    for row in db.execute(
        select(
            lines.c.cost_group, lines.c.budget_key,
            # PostgreSQL rejects ungrouped projections (SQLite silently picks an
            # arbitrary row), so the representative activity and party labels are
            # aggregated. min() keeps the same one-label-per-budget-key shape and
            # makes the chosen label deterministic on every dialect.
            func.min(lines.c.activity_name), func.min(lines.c.party_name),
        )
        .select_from(lines)
        .where(lines.c.budget_key.like("unplanned:%"))
        .group_by(lines.c.cost_group, lines.c.budget_key)
    ).all():
        unplanned_names[(str(row[0]), str(row[1]))] = f"Unbudgeted {row[0].lower()} — {row[2] or row[3] or UNASSIGNED}"
    budget_lines: list[DailyCostBudgetComparison] = []
    for key in sorted(set(planned_by_key) | set(actual_by_key), key=lambda value: -abs(actual_by_key.get(value, Decimal("0")))):
        budget_line = meta.get(key)
        if budget_line is not None:
            group = budget_line.cost_group
            code, name, kind = budget_line.item_code_snapshot, budget_line.item_name_snapshot, budget_line.budget_kind
        else:
            group = group_by_key.get(key, "Services")
            kind = key.split(":", 1)[0] if key else "unplanned"
            code = "" if key.startswith("unplanned:") else key.split(":", 1)[-1][:50]
            name = unplanned_names.get((str(group), key), f"Unbudgeted {str(group).lower()}")
        planned_value = planned_by_key.get(key)
        actual_value = _money(actual_by_key.get(key, Decimal("0")))
        budget_lines.append(DailyCostBudgetComparison(
            budget_key=key, cost_group=group, budget_kind=kind, item_code=code, item_name=name,
            planned=_money(planned_value) if planned_value is not None else Decimal("0.00"),
            actual_to_date=actual_value,
            balance=_money((planned_value or Decimal("0")) - actual_value),
            is_planned=key in planned_by_key,
        ))

    # ---- warnings and totals -------------------------------------------------
    warnings: list[DailyCostWarnings] = []
    if actual_total > planned_total and planned_total > 0:
        warnings.append(DailyCostWarnings(
            code="well-over-budget", severity="warning",
            message=f"Actual cost exceeds the locked AFE budget by {currency} {actual_total - planned_total:,.2f}."))
    over_afe = [row for row in positions if row.over_budget]
    if over_afe:
        warnings.append(DailyCostWarnings(
            code="afe-over-budget", severity="warning",
            message=f"{len(over_afe)} AFE on this well is over its locked budget."))
    if upa or npt:
        warnings.append(DailyCostWarnings(
            code="upa-npt", severity="warning",
            message=f"Unplanned and non-productive charges so far: {currency} {upa + npt:,.2f} "
                    f"(UPA {upa:,.2f} · NPT {npt:,.2f})."))
    unrated = next((group for group in factors if group.dimension == "rate_source"
                    and any(row.key == "" for row in group.rows)), None)
    if unrated:
        warnings.append(DailyCostWarnings(
            code="unrated-lines", severity="info",
            message="Some daily lines carry no rate source. Review them before closing the well."))
    if not entries:
        warnings.append(DailyCostWarnings(
            code="no-daily-sheets", severity="info",
            message="No daily cost sheet has been started for this well yet."))
    if include_draft:
        draft_count = sum(1 for row in windowed if row.status == "draft")
        if draft_count:
            warnings.append(DailyCostWarnings(
                code="draft-included", severity="info",
                message=f"{draft_count} draft sheet(s) are included in these figures."))

    days = [row.cost_date for row in windowed]
    recorded_days = len(set(days))
    elapsed_days = (max(days) - min(days)).days + 1 if days else 0
    average = _money(actual_total / recorded_days) if recorded_days else Decimal("0.00")
    remaining = planned_total - actual_total
    days_to_budget = (
        Decimal(str(round(float(remaining / average), 1))) if average > 0 and remaining > 0 else None
    )
    totals = DailyCostWellTotals(
        currency=currency, planned=planned_total, actual=actual_total, balance=_money(remaining),
        used_percent=(actual_total / planned_total * Decimal("100")).quantize(Decimal("0.01")) if planned_total > 0 else Decimal("0.00"),
        services=_money(services), consumables=_money(consumables), tangibles=_money(tangibles),
        upa=upa, npt=npt, planned_days=_rate(planned_days), recorded_days=recorded_days,
        elapsed_days=elapsed_days, average_per_day=average, days_to_budget=days_to_budget,
        first_day=min(days) if days else None, last_day=max(days) if days else None,
        sheets=len(windowed),
        draft_sheets=sum(1 for row in windowed if row.status == "draft"),
        submitted_sheets=sum(1 for row in windowed if row.status == "submitted"),
        lines=int(db.execute(select(func.count()).select_from(lines)).scalar() or 0),
    )
    return DailyCostWellSummary(
        well=DailyCostWellHeader(
            id=well.id, well_code=well.well_code, well_name=well.well_name,
            rig_code=well.rig.rig_code if well.rig else "", rig_name=well.rig.rig_name if well.rig else "",
            status=well.status, config_status=well.config_status, afes=afe_options,
        ),
        from_date=date_from, to_date=date_to, as_of=max(days) if days else None,
        include_draft=include_draft, totals=totals, afes=positions, daily=daily,
        factors=factors, budget_lines=budget_lines, warnings=warnings,
    )


def daily_cost_wells(db: Session, organization_id: str) -> list[DailyCostWellOption]:
    """Wells that carry daily costs, for the module's well picker."""
    tracked = {
        str(row[0]): int(row[1]) for row in db.execute(
            select(DailyCostEntry.well_id, func.count(DailyCostEntry.id))
            .where(DailyCostEntry.organization_id == organization_id, DailyCostEntry.is_deleted.is_(False))
            .group_by(DailyCostEntry.well_id)
        ).all()
    }
    return [well for well in reference_data(db, organization_id).wells if well.id in tracked]



def _import_row(raw: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in raw.items():
        normalized = str(key or "").strip().lower().replace(" ", "_").replace("-", "_")
        if normalized and value is not None:
            row[normalized] = value
    return row


def _import_value(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, float) and value != value:  # spreadsheet NaN
            continue
        text = str(value).strip() if not isinstance(value, (int, float, Decimal)) else value
        if text != "":
            return text
    return default


def _import_lookup(rows: Sequence[Any], value: Any, code_attr: str, label: str) -> Any:
    if value is None or str(value).strip() == "":
        return None
    needle = str(value).strip().casefold()
    matches = [row for row in rows if row.id.casefold() == needle or str(getattr(row, code_attr, "")).strip().casefold() == needle]
    if not matches:
        raise ValueError(f"{label} '{value}' was not found among active records in this workspace")
    if len(matches) > 1:
        raise ValueError(f"{label} '{value}' is ambiguous; use its record ID")
    return matches[0]


def _saved_inputs(entry: DailyCostEntry) -> tuple[list[DailyCostServiceLineIn], list[DailyCostConsumableLineIn], list[DailyCostTangibleLineIn]]:
    def common(row: Any) -> dict[str, Any]:
        return {
            "id": row.id, "activity_id": row.activity_id, "hole_section_id": row.hole_section_id,
            "phase_id": row.phase_id, "sub_activity_id": row.sub_activity_id,
            "vendor_id": row.vendor_id, "party_name": row.party_name,
            "quantity": row.quantity, "currency": row.currency, "override_rate": row.override_rate,
            "override_reason": row.override_reason, "remarks": row.remarks,
        }
    services = [DailyCostServiceLineIn(
        **common(row), service_id=row.service_id, baseline_service_rate_id=row.baseline_service_rate_id,
        charging_basis=row.charging_basis, charge_category=row.charge_category,
        quantity_unit=row.quantity_unit,
    ) for row in entry.service_lines]
    consumables = [DailyCostConsumableLineIn(
        **common(row), category=row.category, item_kind=row.item_kind, item_id=row.item_id,
    ) for row in entry.consumable_lines]
    tangibles = [DailyCostTangibleLineIn(
        **common(row), tangible_id=row.tangible_id,
    ) for row in entry.tangible_lines]
    return services, consumables, tangibles


def import_daily_cost(
    db: Session,
    organization_id: str,
    entry_id: str,
    data: DailyCostImportRequest,
    user: User,
    request: Request | None,
) -> DailyCostImportResponse:
    """Validate a whole CSV/XLSX-import payload before appending any lines."""
    entry = _get_entry(db, entry_id, organization_id, deleted=False)
    if entry.status != "draft":
        raise HTTPException(status_code=409, detail="Submitted daily cost sheets are read-only")
    activity_rows = db.scalars(select(Activity).where(
        Activity.organization_id == organization_id, Activity.is_deleted.is_(False)
    )).all()
    service_rows = db.scalars(select(Service).where(
        Service.organization_id == organization_id, Service.is_deleted.is_(False)
    )).all()
    vendor_rows = db.scalars(select(Vendor).where(
        Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False), Vendor.status == "active"
    )).all()
    sub_activity_rows = db.scalars(select(WellSubActivity).where(
        WellSubActivity.organization_id == organization_id, WellSubActivity.well_id == entry.well_id,
        WellSubActivity.is_deleted.is_(False),
    )).all()
    section_map: dict[str, DailyCostBaselineSection] = {}
    phase_map: dict[tuple[str, str], DailyCostBaselinePhase] = {}
    for section in entry.baseline.well_sections:
        section_map[section.hole_section_id.casefold()] = section
        section_map[section.section_code_snapshot.casefold()] = section
        for phase in section.phases:
            phase_map[(section.hole_section_id.casefold(), phase.phase_id.casefold())] = phase
            phase_map[(section.hole_section_id.casefold(), phase.phase_code_snapshot.casefold())] = phase
            phase_map[(section.section_code_snapshot.casefold(), phase.phase_id.casefold())] = phase
            phase_map[(section.section_code_snapshot.casefold(), phase.phase_code_snapshot.casefold())] = phase

    kind_rows: dict[str, list[Any]] = {}
    for kind, (model, _, _, _) in CONSUMABLE_KIND_MODEL.items():
        kind_rows[kind] = db.scalars(select(model).where(
            model.organization_id == organization_id, model.is_deleted.is_(False)
        )).all()

    service_inputs: list[DailyCostServiceLineIn] = []
    consumable_inputs: list[DailyCostConsumableLineIn] = []
    tangible_inputs: list[DailyCostTangibleLineIn] = []
    errors: list[str] = []
    category_kind = {
        "mud chemicals": "mud_chemical", "mud_chemical": "mud_chemical",
        "cement additives": "cement_additive", "cement_additive": "cement_additive",
        "fuel": "fuel", "drill bits": "drill_bit", "drill_bit": "drill_bit",
    }

    for index, raw in enumerate(data.rows, start=2):
        if len(errors) >= MAX_IMPORT_ERRORS:
            errors.append(f"Stopped after {MAX_IMPORT_ERRORS} errors; correct these rows and import again.")
            break
        try:
            row = _import_row(raw)
            line_type = str(_import_value(row, "line_type", "type", default="")).strip().lower().replace(" ", "_")
            activity = _import_lookup(activity_rows, _import_value(row, "activity_code", "activity_id", "activity"), "activity_code", "Activity")
            if activity is None:
                raise ValueError("Activity code is required")
            section_value = _import_value(row, "section_code", "hole_section_code", "hole_section_id", "section")
            section = section_map.get(str(section_value).strip().casefold()) if section_value else None
            if section_value and section is None:
                raise ValueError(f"Hole section '{section_value}' is not part of this AFE's locked well plan")
            phase_value = _import_value(row, "phase_code", "phase_id", "phase")
            phase = None
            if phase_value:
                if section is None:
                    raise ValueError("Choose a hole section before selecting a phase")
                phase = phase_map.get((section.hole_section_id.casefold(), str(phase_value).strip().casefold()))
                if phase is None:
                    raise ValueError(f"Phase '{phase_value}' is not configured under section {section.section_code_snapshot}")
            sub_value = _import_value(row, "sub_activity_code", "sub_activity_id", "sub_activity")
            if not sub_value:
                raise ValueError(
                    "Sub Activity code is required; configure the well's sub activities "
                    "in Rig & Well Management first"
                )
            sub_activity = _import_lookup(sub_activity_rows, sub_value, "sub_activity_code", "Sub Activity")
            if sub_activity.activity_id != activity.id:
                raise ValueError("The selected Sub Activity does not belong to the selected Activity")
            vendor_value = _import_value(row, "vendor_code", "vendor_id", "vendor")
            vendor = _import_lookup(vendor_rows, vendor_value, "vendor_code", "Vendor") if vendor_value else None
            # Classification (Planned / UPA / NPT) is derived from the Master Data
            # Activity; a legacy "classification" column in the file is ignored.
            classification = classify_activity(activity)
            quantity = _import_value(row, "quantity", "qty", default="1")
            currency = str(_import_value(row, "currency", "currency_code", default="")).strip().upper()
            override_value = _import_value(row, "override_rate", "daily_rate_override", default=None)
            override_rate = Decimal(str(override_value)) if override_value is not None else None
            override_reason = str(_import_value(row, "override_reason", "rate_override_reason", default=""))
            party_name = str(_import_value(row, "party_name", "responsible_party", default=""))
            common = {
                "activity_id": activity.id,
                "hole_section_id": section.hole_section_id if section else None,
                "phase_id": phase.phase_id if phase else None,
                "sub_activity_id": sub_activity.id,
                "vendor_id": vendor.id if vendor else None,
                "party_name": party_name,
                "quantity": quantity,
                "currency": currency,
                "override_rate": override_rate,
                "override_reason": override_reason,
                "remarks": str(_import_value(row, "remarks", "line_remarks", default="")),
            }

            if line_type in ("service", "services"):
                service = _import_lookup(service_rows, _import_value(row, "service_code", "service_id", "service"), "service_code", "Service")
                if service is None:
                    raise ValueError("Service code is required")
                rate_id = str(_import_value(row, "baseline_service_rate_id", "afe_rate_id", "rate_id", default="")) or None
                basis_value = _normalise_basis(_import_value(row, "charging_basis", "basis", default="")) or None
                charge_category = str(_import_value(row, "charge_category", "category", default="Operation"))
                candidates = [rate for rate in entry.baseline.service_rates if rate.service_id == service.id]
                if rate_id:
                    chosen_rate = next((rate for rate in candidates if rate.id == rate_id), None)
                    if chosen_rate is None:
                        raise ValueError("AFE rate ID does not belong to this service and locked AFE")
                elif classification == "Planned":
                    if basis_value:
                        candidates = [rate for rate in candidates if rate.charging_basis == basis_value]
                    else:
                        bases = {rate.charging_basis for rate in candidates}
                        if len(bases) == 1:
                            basis_value = next(iter(bases))
                    if basis_value == "Day Rate":
                        candidates = [rate for rate in candidates if rate.rate_kind == "day_rate" and rate.charge_category == charge_category]
                    if section is not None:
                        candidates = [rate for rate in candidates if rate.hole_section_id in (None, section.hole_section_id)]
                    if phase is not None:
                        candidates = [rate for rate in candidates if rate.phase_id in (None, phase.phase_id)]
                    if len(candidates) != 1:
                        raise ValueError("AFE service rate is ambiguous; include baseline_service_rate_id from this AFE")
                    chosen_rate = candidates[0]
                    rate_id = chosen_rate.id
                else:
                    chosen_rate = next((rate for rate in candidates if rate.id == rate_id), None) if rate_id else None
                basis = chosen_rate.charging_basis if chosen_rate else (basis_value or "Day Rate")
                charge_category = chosen_rate.charge_category if chosen_rate and chosen_rate.rate_kind == "day_rate" else charge_category
                unit = str(_import_value(row, "quantity_unit", "unit", default="")).strip().lower()
                if basis not in QUANTITY_UNIT_FOR_BASIS:
                    raise ValueError(
                        f"Charging basis '{basis}' is not one of Day Rate, Per Service Rate or Per Section Rate"
                    )
                if not unit:
                    unit = "unit" if basis == "Day Rate" and charge_category in SERVICE_ONE_TIME else QUANTITY_UNIT_FOR_BASIS[basis]
                if not currency:
                    currency = chosen_rate.currency if chosen_rate else ""
                service_vendor_id = vendor.id if vendor else service.vendor_id
                if service_vendor_id and not common["vendor_id"]:
                    common["vendor_id"] = service_vendor_id
                service_inputs.append(DailyCostServiceLineIn(
                    **{**common, "currency": currency}, service_id=service.id,
                    baseline_service_rate_id=rate_id, charging_basis=basis,
                    charge_category=charge_category, quantity_unit=unit,
                ))
            else:
                category_value = str(_import_value(row, "category", "consumable_category", default="")).strip()
                if line_type in ("tangible", "tangibles"):
                    item_kind, category = "tangible", "Tangibles"
                elif line_type in ("consumable", "consumables", "chemical", "drill_bit", "drill_bits"):
                    item_kind = str(_import_value(row, "item_kind", "kind", default="")).strip().lower()
                    if not item_kind:
                        item_kind = category_kind.get(category_value.lower())
                    if item_kind not in ("mud_chemical", "cement_additive", "fuel", "drill_bit"):
                        raise ValueError("For a consumable, category must be Mud Chemicals, Cement Additives, Fuel or Drill Bits")
                    category = {
                        "mud_chemical": "Mud Chemicals", "cement_additive": "Cement Additives",
                        "fuel": "Fuel", "drill_bit": "Drill Bits",
                    }[item_kind]
                else:
                    raise ValueError("Line Type must be Service, Consumable or Tangible")
                item_code = _import_value(row, "item_code", "catalogue_code", "tangible_code", "item_id", "tangible_id")
                if line_type in ("tangible", "tangibles"):
                    item = _import_lookup(kind_rows["tangible"], item_code, "tangible_code", "Tangible")
                else:
                    _, code_attr, _, _ = CONSUMABLE_KIND_MODEL[item_kind]
                    item = _import_lookup(kind_rows[item_kind], item_code, code_attr, "Catalogue item")
                if item is None:
                    raise ValueError("Catalogue item code is required")
                if not currency:
                    snap = _rate_snapshot_index(entry.rate_baseline).get((item_kind, item.id))
                    currency = (snap.currency if snap else getattr(item, "currency", "") or "").upper()
                common["currency"] = currency
                if item_kind == "tangible":
                    tangible_inputs.append(DailyCostTangibleLineIn(**common, tangible_id=item.id))
                else:
                    consumable_inputs.append(DailyCostConsumableLineIn(
                        **common, category=category, item_kind=item_kind, item_id=item.id,
                    ))
        except (ValueError, ValidationError, ArithmeticError) as error:
            if isinstance(error, ValidationError):
                message = "; ".join(item["msg"] for item in error.errors())
            else:
                message = str(error)
            errors.append(f"Row {index}: {message}")

    if errors:
        return DailyCostImportResponse(imported_count=0, error_count=len(errors), errors=errors[:MAX_IMPORT_ERRORS], success=False)
    current_services, current_consumables, current_tangibles = _saved_inputs(entry)
    payload = DailyCostSaveIn(
        remarks=entry.remarks,
        services=[*current_services, *service_inputs],
        consumables=[*current_consumables, *consumable_inputs],
        tangibles=[*current_tangibles, *tangible_inputs],
    )
    save_day(db, organization_id, entry.id, payload, user, request, action="import")
    return DailyCostImportResponse(
        imported_count=len(service_inputs) + len(consumable_inputs) + len(tangible_inputs),
        error_count=0, errors=[], success=True,
    )

def record_export(db: Session, user: User, data: DailyCostExportAudit, request: Request | None) -> None:
    _audit(
        db, user=user, action="export", entity_type="daily_cost_export", entity_id=None,
        label=data.module, summary=f"Exported {data.record_count} {data.module} record(s) as {data.format.upper()}" + (" including deleted records" if data.include_deleted else ""),
        request=request,
    )
    _commit(db)
