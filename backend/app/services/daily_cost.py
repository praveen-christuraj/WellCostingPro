"""Daily Cost Management domain services.

The first sheet for an AFE snapshots the saved AFE estimate, its FX factors,
the well plan, service charge cards and all active catalogue rates. Daily lines
are then priced from those immutable inputs (or a user-entered, justified
rate override), never from a live master-data price. All amounts are stored in
both their native currency and the AFE's standard currency for reconciliation.

Services, consumables and tangibles are reconciled against the AFE budget lines.
Other expenses (Lost In Hole, hole problems, claims) have no allowance to be
reconciled against: they are kept in their own group and deducted from the locked
AFE total, and each one carries a mandatory remark.
"""

from __future__ import annotations

from app.models.daily_cost import DailyCostServiceCostItem

import logging
import re
import threading
from collections import defaultdict
from datetime import date, datetime, time as dt_time, timedelta, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from typing import Any, Iterable, Sequence
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import Select, case, func, literal, select, union_all
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.units import depth_to_meters, normalize_depth_unit
from app.models import (
    Activity, Afe, AuditLog, CementAdditive, Currency, DailyCostBaseline,
    DailyCostBaselineBudgetLine, DailyCostBaselineExchangeRate, DailyCostBaselinePhase,
    DailyCostBaselineSection, DailyCostBaselineServiceRate, DailyCostCatalogueRateSnapshot,
    DailyCostConsumableLine, DailyCostEntry, DailyCostOtherExpenseLine, DailyCostServiceLine,
    DailyCostTangibleLine,
    DailyCostWellRateBaseline, DrillBit, FuelType, HoleSection, LihCostEntry, MudChemical, Phase, Rig,
    Service, Tangible, Vendor, Well, WellPhase, WellSection, WellSubActivity,
)
from app.models.daily_cost import OTHER_EXPENSE_TYPE_LABELS
from app.models.entities import User
from app.models.rig_well import now as _model_now, uid
from app.schemas.afe import AfeEstimateOut
from app.schemas.daily_cost import (
    ALL_COST_GROUPS, OTHER_EXPENSE_MIN_REMARKS, TRACKED_COST_GROUPS,
    DailyCostAfeOption, DailyCostAfePosition, DailyCostBaselineBudgetOut, DailyCostBaselineOut,
    DailyCostBudgetComparison, DailyCostCatalogueOption, DailyCostComparison,
    DailyCostComparisonGroup, DailyCostConsumableLineIn, DailyCostConsumableLineOut,
    DailyCostDailyRow, DailyCostDayOut, DailyCostEntryCreate, DailyCostEntryOut, DailyCostExportAudit,
    DailyCostFactorGroup, DailyCostFactorRow, DailyCostGroupSummary, DailyCostIDs,
    DailyCostLihDay, DailyCostLihDeduction, DailyCostLihSummary,
    DailyCostImportRequest, DailyCostImportResponse, DailyCostOtherExpenseLineIn,
    DailyCostOtherExpenseLineOut, DailyCostOtherExpenseTypeOption, DailyCostOverview, DailyCostPreviewOut,
    DailyCostRateOut, DailyCostReference, DailyCostReopenIn, DailyCostRigOption, DailyCostSaveIn,
    DailyCostSectionDepthOut, DailyCostSectionOption, DailyCostServiceLineIn, DailyCostServiceLineOut, DailyCostStatusIn,
    DailyCostSubActivityOption, DailyCostTangibleLineIn, DailyCostTangibleLineOut,
    DailyCostTrendPoint, DailyCostVendorOption, DailyCostWarnings, DailyCostWellHeader,
    DailyCostWellOption, DailyCostWellProgress, DailyCostWellProgressReport,
    DailyCostMudReconciliation, DailyCostMudSectionReconciliation,
    DailyCostWellProgressUpdate, DailyCostWellSummary, DailyCostWellTotals,
)
from app.services import afe as afe_service
from app.services import audit
from app.services import lih_cost as lih_cost_service
from app.services import mud_cost as mud_cost_service
from app.models.catalogue import CatalogueOption
from app.core.precision import DECIMAL_QUANT
from app.domain.service_groups import service_group_rank

MONEY = DECIMAL_QUANT
RATE = DECIMAL_QUANT
FX = DECIMAL_QUANT
# Decimal ledger columns are Numeric(28, 10). PostgreSQL rejects anything larger with a
# driver error, which would surface as an opaque 500, so the limit is checked here
# and reported to the user as ordinary validation.
MONEY_LIMIT = Decimal("9999999999999999.9999999999")
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
    # No AFE budget lines exist for this group; it is deducted from the AFE total.
    (DailyCostOtherExpenseLine, "Other Expenses"),
)
# Entry relationship that owns each line model, used wherever a whole sheet is
# replaced or read back.
LINE_RELATIONSHIP: dict[type[Any], str] = {
    DailyCostServiceLine: "service_lines",
    DailyCostConsumableLine: "consumable_lines",
    DailyCostTangibleLine: "tangible_lines",
    DailyCostOtherExpenseLine: "other_expense_lines",
}
OTHER_EXPENSE_RATE_SOURCE = "other_expense"
OTHER_EXPENSE_UNITS = ("unit", "days", "hours")
# Line-type labels accepted by the daily-sheet importer for an unbudgeted charge.
OTHER_EXPENSE_LINE_TYPES = ("other", "others", "other_expense", "other_expenses", "unbudgeted", "other_cost")
# Spoken aliases an importer is likely to type instead of the stored code.
OTHER_EXPENSE_TYPE_ALIASES = {
    "lost in hole": "LIH", "lost_in_hole": "LIH", "lih": "LIH",
    "hole problem": "HOLE_PROBLEM", "hole problems": "HOLE_PROBLEM", "hole_problem": "HOLE_PROBLEM",
    "fishing": "FISHING", "fishing & recovery": "FISHING", "fishing and recovery": "FISHING",
    "recovery": "FISHING", "fishing_recovery": "FISHING",
    "side track": "SIDE_TRACK", "sidetrack": "SIDE_TRACK", "side_track": "SIDE_TRACK",
    "equipment damage": "EQUIPMENT_DAMAGE", "damage": "EQUIPMENT_DAMAGE", "equipment": "EQUIPMENT_DAMAGE",
    "third party claim": "THIRD_PARTY_CLAIM", "third-party claim": "THIRD_PARTY_CLAIM", "claim": "THIRD_PARTY_CLAIM",
    "penalty": "PENALTY", "fine": "PENALTY", "penalty / fine": "PENALTY",
    "misc": "MISC", "miscellaneous": "MISC", "other": "MISC",
}

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
            selectinload(DailyCostEntry.tangible_lines), selectinload(DailyCostEntry.other_expense_lines),
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
    uom: str, sort_order: int, service_group: str = "",
) -> DailyCostBaselineBudgetLine:
    return DailyCostBaselineBudgetLine(
        id=uid(), organization_id=organization_id, baseline_id=baseline.id, cost_group=cost_group,
        budget_kind=budget_kind, item_key=item_key, item_code_snapshot=item_code, item_name_snapshot=item_name,
        service_group=(service_group or "").strip(),
        source_afe_line_id=source_line_id, section_id=section_id, phase_id=phase_id,
        quantity=Decimal(quantity), unit_rate=_rate(unit_rate), native_amount=_money(native_amount),
        currency=(currency or "").strip().upper(), exchange_rate=_fx(fx_rate),
        planned_amount=_money(Decimal(native_amount) * Decimal(fx_rate)), uom=uom or "", sort_order=sort_order,
    )


def _service_rate_snapshots(organization_id: str, line: Any, order: int) -> list[DailyCostBaselineServiceRate]:
    service_rates: list[DailyCostBaselineServiceRate] = []
    currency = line.currency.upper()
    if line.charging_basis == "Day Rate":
        for index, row in enumerate(line.rates):
            service_rates.append(DailyCostBaselineServiceRate(
                id=uid(), organization_id=organization_id, service_id=line.service_id,
                source_afe_line_id=line.id, service_code_snapshot=line.service_code,
                service_name_snapshot=line.service_name, charging_basis=line.charging_basis,
                rate_kind="day_rate", charge_category=row.category, hole_section_id=line.hole_section_id,
                phase_id=line.phase_id, unit_rate=_rate(row.unit_rate), currency=currency,
                sort_order=order * 100 + index,
            ))
    elif line.charging_basis == "Per Service Rate":
        service_rates.append(DailyCostBaselineServiceRate(
            id=uid(), organization_id=organization_id, service_id=line.service_id,
            source_afe_line_id=line.id, service_code_snapshot=line.service_code,
            service_name_snapshot=line.service_name, charging_basis=line.charging_basis,
            rate_kind="per_service", charge_category="Operation", hole_section_id=line.hole_section_id,
            phase_id=line.phase_id, unit_rate=_rate(line.service_amount), currency=currency,
            sort_order=order * 100,
        ))
    else:
        for index, row in enumerate(line.section_rates):
            service_rates.append(DailyCostBaselineServiceRate(
                id=uid(), organization_id=organization_id, service_id=line.service_id,
                source_afe_line_id=line.id, service_code_snapshot=line.service_code,
                service_name_snapshot=line.service_name, charging_basis=line.charging_basis,
                rate_kind="per_section", charge_category="Operation", hole_section_id=row.hole_section_id,
                phase_id=row.phase_id, unit_rate=_rate(row.amount), currency=currency,
                sort_order=order * 100 + index,
            ))
    return service_rates


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
                from_depth=depth_to_meters(section.from_depth, estimate.well.depth_unit) or Decimal("0.00"),
                to_depth=depth_to_meters(section.to_depth, estimate.well.depth_unit) or Decimal("0.00"),
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
                fx_rate=factor, uom="", sort_order=order, service_group=line.service_group,
            ))
            order += 1
            service_rates.extend(_service_rate_snapshots(organization_id, line, order))

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
        charging_basis=row.charging_basis, rate_kind=row.rate_kind, charge_category=row.charge_category, is_current=row.is_current,
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
            item_code=row.item_code_snapshot, item_name=row.item_name_snapshot, service_group=row.service_group,
            source_afe_line_id=row.source_afe_line_id,
            section_id=row.section_id, phase_id=row.phase_id, quantity=Decimal(row.quantity), unit_rate=Decimal(row.unit_rate),
            native_amount=Decimal(row.native_amount), currency=row.currency, exchange_rate=Decimal(row.exchange_rate),
            planned_amount=Decimal(row.planned_amount), uom=row.uom,
        ) for row in baseline.budget_lines],
        sections=[_section_option(section) for section in baseline.well_sections],
        exchange_rates={row.currency_code: Decimal(row.rate) for row in baseline.exchange_rates},
    )


def refresh_service_rates(db: Session, organization_id: str, entry_id: str, user: User, request: Request | None) -> DailyCostBaselineOut:
    """Append rate versions; never rewrite the budgets or an existing actual line."""
    with _WRITE_LOCK:
        entry = _get_entry(db, entry_id, organization_id, deleted=False)
        _lock_row_id(db, DailyCostBaseline, DailyCostBaseline.id == entry.baseline_id)
        baseline = _baseline_for(db, organization_id, entry.baseline_id)
        afe = _afe_or_422(db, organization_id, entry.afe_id, entry.well_id)
        estimate = _estimate_for_daily_cost(db, organization_id, afe)
        def signature(row: Any) -> tuple:
            return (row.service_id, row.source_afe_line_id, row.charging_basis, row.rate_kind,
                    row.charge_category, row.hole_section_id, row.phase_id, Decimal(row.unit_rate), row.currency)
        existing = {signature(row): row for row in baseline.service_rates}
        wanted = [_service_rate_snapshots(organization_id, line, index)
                  for index, line in enumerate(estimate.services)]
        wanted_keys = {signature(row) for rows in wanted for row in rows}
        changed = any(row.is_current != (signature(row) in wanted_keys) for row in baseline.service_rates)
        for row in baseline.service_rates:
            row.is_current = signature(row) in wanted_keys
        for rows in wanted:
            for row in rows:
                if signature(row) not in existing:
                    row.is_current = True
                    baseline.service_rates.append(row)
                    changed = True
        if changed:
            _audit(db, user=user, action="update", entity_type="daily_cost", entity_id=entry.id, label=entry.daily_cost_code, summary="Refreshed current AFE service rates; historical actuals and AFE budget retained", request=request)
        _commit(db)
        return _baseline_out(baseline, entry.rate_baseline)


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
    services = sorted(services, key=lambda service: (service_group_rank(service.service_group), service.service_code))
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
            afe_type=afe.afe_type, status=afe.status, configuration_scope=afe.configuration_scope,
            standard_currency=estimate.summary.currency.standard_currency,
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
            completion_status=well.completion_status,
            completion_config_status=well.completion_config_status,
            drilling_is_deleted=well.drilling_is_deleted,
            completion_is_deleted=well.completion_is_deleted,
            sections=[DailyCostSectionOption(
                hole_section_id=section.hole_section_id, section_code=section.hole_section.section_code,
                section_name=section.hole_section.section_name,
                from_depth=depth_to_meters(section.from_depth, well.depth_unit) or Decimal("0.00"),
                to_depth=depth_to_meters(section.to_depth, well.depth_unit) or Decimal("0.00"),
                total_days=sum((Decimal(phase.days) for phase in section.phases), Decimal("0")),
                phases=[{
                    "phase_id": phase.phase_id, "phase_code": phase.phase.phase_code,
                    "phase_name": phase.phase.phase_name, "days": Decimal(phase.days),
                } for phase in section.phases],
            ) for section in well.sections],
        ) for well in wells if well.rig_id in rig_ids and well.rig and not well.rig.is_deleted],
        afes=afe_options,
        activities=[{"id": row.id, "activity_code": row.activity_code, "activity_name": row.activity_name, "display_name": _label(row.activity_code, row.activity_name)} for row in activities],
        sub_activities=[DailyCostSubActivityOption(
            id=row.id, well_id=row.well_id,
            scope=(row.scope if row.scope in ("drilling", "completion") else "drilling"),
            activity_id=row.activity_id, sub_activity_code=row.sub_activity_code,
            sub_activity_name=row.sub_activity_name, responsible_party=row.responsible_party,
            display_name=_label(row.sub_activity_code, row.sub_activity_name),
        ) for row in sub_activities],
        services=[{
            "id": row.id, "service_code": row.service_code, "service_name": row.service_name,
            "service_category": row.service_category, "service_group": row.service_group,
            "provider_type": row.provider_type,
            "vendor_id": row.vendor_id, "vendor_code": row.vendor.vendor_code if row.vendor else "",
            "vendor_name": row.vendor.vendor_name if row.vendor else "",
            "display_name": _label(row.service_code, row.service_name),
        } for row in services],
        catalogue_items=catalogue_items,
        vendors=[DailyCostVendorOption(
            id=row.id, vendor_code=row.vendor_code, vendor_name=row.vendor_name, vendor_type=row.vendor_type,
            status=row.status, display_name=_label(row.vendor_code, row.vendor_name),
        ) for row in vendors],
        currencies=sorted({*(row.currency_code.upper() for row in currencies), "USD"}),
        charge_categories=["Mobilization", "Demobilization", "Operation", "Standby", "Personnel-Operation", "Personnel-Standby", "Fixed Charge", "Others"],
        charge_bases=["Day Rate", "Per Service Rate", "Per Section Rate"],
        quantity_units=["days", "hours", "service", "section", "unit"],
        classifications=["Planned", "UPA", "NPT"],
        consumable_categories=["Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits"],
        other_expense_types=[
            DailyCostOtherExpenseTypeOption(code=code, label=label)
            for code, label in OTHER_EXPENSE_TYPE_LABELS.items()
        ],
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
            afe = _afe_or_422(db, organization_id, data.afe_id, well.id)
            entry_scope = afe.configuration_scope if afe.configuration_scope in ("drilling", "completion") else "drilling"
            if well.scope_is_deleted(entry_scope):
                raise HTTPException(
                    status_code=409,
                    detail=f"Restore the {entry_scope} scope on {well.well_code} in Rig & Well Management before entering daily costs.",
                )
            has_sub_activity = db.scalar(
                select(WellSubActivity.id).where(
                    WellSubActivity.organization_id == organization_id,
                    WellSubActivity.well_id == well.id,
                    WellSubActivity.scope == entry_scope,
                    WellSubActivity.is_deleted.is_(False),
                ).limit(1)
            )
            if not has_sub_activity:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Configure the {entry_scope} well sub activities for {well.well_code} in Rig & Well Management "
                        "before entering daily costs. Every daily cost line needs the Activity and Sub activity."
                    ),
                )
            duplicate = db.scalar(select(DailyCostEntry.id).where(
                DailyCostEntry.organization_id == organization_id, DailyCostEntry.well_id == well.id,
                DailyCostEntry.afe_id == afe.id, DailyCostEntry.cost_date == data.cost_date,
                DailyCostEntry.is_deleted.is_(False),
            ))
            if duplicate:
                raise HTTPException(status_code=409, detail="A daily cost sheet already exists for this well, AFE and date")
            rate_baseline = _ensure_rate_baseline(db, organization_id, well, user)
            baseline = _ensure_afe_baseline(db, organization_id, well, afe, rate_baseline, user)
            entry_usd_fx = Decimal("1.000000")
            if baseline.standard_currency.upper() != "USD":
                if data.usd_exchange_rate is not None:
                    entry_usd_fx = _fx(data.usd_exchange_rate)
                else:
                    baseline_fx = {row.currency_code.upper(): Decimal(row.rate) for row in baseline.exchange_rates}
                    if baseline_fx.get("USD") and baseline_fx["USD"] > 0:
                        entry_usd_fx = _fx(Decimal("1") / baseline_fx["USD"])
                    else:
                        prior_usd_fx = db.scalar(
                            select(DailyCostEntry.usd_exchange_rate)
                            .where(
                                DailyCostEntry.organization_id == organization_id,
                                DailyCostEntry.well_id == well.id,
                                DailyCostEntry.standard_currency == baseline.standard_currency,
                                DailyCostEntry.is_deleted.is_(False),
                                DailyCostEntry.usd_exchange_rate > 0,
                            )
                            .order_by(DailyCostEntry.cost_date.desc(), DailyCostEntry.created_at.desc())
                            .limit(1)
                        )
                        if prior_usd_fx is not None:
                            entry_usd_fx = _fx(prior_usd_fx)
            cost_code = f"DC-{well.well_code[:35]}-{data.cost_date:%Y%m%d}-{afe.afe_code[:35]}"[:100]
            entry = DailyCostEntry(
                id=uid(), organization_id=organization_id, rig_id=well.rig_id,
                rig_code_snapshot=well.rig.rig_code, rig_name_snapshot=well.rig.rig_name,
                well_id=well.id, well_code_snapshot=well.well_code, well_name_snapshot=well.well_name,
                afe_id=afe.id, afe_code_snapshot=afe.afe_code, afe_name_snapshot=afe.afe_name,
                afe_status_at_create=afe.status, rate_baseline_id=rate_baseline.id, baseline_id=baseline.id,
                daily_cost_code=cost_code, cost_date=data.cost_date, standard_currency=baseline.standard_currency,
                usd_exchange_rate=entry_usd_fx,
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
    return {model: {row.id: row for row in getattr(entry, attr)} for model, attr in LINE_RELATIONSHIP.items()}


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
    expected_scope: str | None = None,
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
    if not existing and expected_scope in ("drilling", "completion") and row.scope != expected_scope:
        raise HTTPException(
            status_code=422,
            detail=f"{label}: select a sub activity configured for this sheet's {expected_scope} scope",
        )
    if row.activity_id != activity_id:
        raise HTTPException(status_code=422, detail=f"{label}: the sub activity must belong to the selected Master Data Activity")
    return row


def _resolve_fx(
    baseline: DailyCostBaseline,
    currency: str,
    label: str,
    *,
    line_exchange_rate: Decimal | None = None,
    entry_usd_fx: Decimal = Decimal("1"),
    extra_rates: dict[str, Decimal] | None = None,
) -> tuple[Decimal, Decimal]:
    """Return ``(factor_to_entry_standard, factor_to_usd)`` for ``currency``.

    When ``currency`` differs from ``USD`` / the locked currency setup, an
    explicit ``line_exchange_rate`` (1 unit of ``currency`` in ``USD``) satisfies
    conversion directly and can be stored column-wise on ``baseline.exchange_rates``.
    """
    code = (currency or "").strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail=f"{label}: enter a currency")
    entry_std = (baseline.standard_currency or "USD").strip().upper()
    conversion = {row.currency_code.upper(): Decimal(row.rate) for row in baseline.exchange_rates}
    if extra_rates:
        conversion.update(extra_rates)

    # 1. Resolve factor to the sheet's standard currency.
    if code == entry_std:
        factor = _fx(Decimal("1"))
    elif line_exchange_rate is not None:
        if entry_std == "USD":
            factor = _fx(line_exchange_rate)
        elif code == "USD":
            factor = _fx(Decimal("1") / entry_usd_fx)
        else:
            factor = _fx(Decimal(line_exchange_rate) / entry_usd_fx)
    else:
        raw = conversion.get(code)
        if raw is None or raw <= 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{label}: currency {code} requires a USD conversion rate (exchange_rate) "
                    f"because {code} is not in the locked AFE currency setup."
                ),
            )
        factor = _fx(raw)

    # 2. Resolve standardized USD factor (1 unit of `code` = `usd_fx` USD).
    if code == "USD":
        usd_fx = _fx(Decimal("1"))
    elif line_exchange_rate is not None:
        usd_fx = _fx(line_exchange_rate)
    elif entry_std == "USD":
        usd_fx = factor
    else:
        usd_fx = _fx(factor * entry_usd_fx)
    return factor, usd_fx


def _rate_factor(
    baseline: DailyCostBaseline,
    currency: str,
    label: str,
    *,
    line_exchange_rate: Decimal | None = None,
    entry_usd_fx: Decimal = Decimal("1"),
    extra_rates: dict[str, Decimal] | None = None,
) -> Decimal:
    factor, _ = _resolve_fx(
        baseline,
        currency,
        label,
        line_exchange_rate=line_exchange_rate,
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
    )
    return factor


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
    entry_usd_fx: Decimal = Decimal("1"),
    extra_rates: dict[str, Decimal] | None = None,
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
    entry_scope = (
        entry.afe.configuration_scope
        if entry.afe is not None and entry.afe.configuration_scope in ("drilling", "completion")
        else None
    )
    sub_activity = _get_sub_activity(
        db, entry.organization_id, entry.well_id, data.sub_activity_id, activity.id,
        expected_scope=entry_scope,
        existing=existing, label=label,
    )
    vendor = _get_vendor(db, entry.organization_id, data.vendor_id, existing=existing, label=label)
    party = data.party_name or (vendor.vendor_name if vendor else "")
    if classification in ("UPA", "NPT") and not (vendor or party):
        raise HTTPException(status_code=422, detail=f"{label}: identify the vendor or responsible party for UPA/NPT")

    code_currency = (data.currency or "").strip().upper()
    override = Decimal(data.override_rate) if data.override_rate is not None else None
    revision_number = None
    effective_date = None
    if data.override_rate is None and data.currency:
        code_currency = data.currency.strip().upper()
    fx_factor = Decimal("0")
    usd_fx_factor = Decimal("1")
    if code_currency:
        fx_factor, usd_fx_factor = _resolve_fx(
            entry.baseline,
            code_currency,
            label,
            line_exchange_rate=data.exchange_rate,
            entry_usd_fx=entry_usd_fx,
            extra_rates=extra_rates,
        )
    depth_unit = normalize_depth_unit(getattr(data, "actual_depth_unit", "m"))
    depth_input = (
        Decimal(data.actual_depth).quantize(MONEY, rounding=ROUND_HALF_UP)
        if getattr(data, "actual_depth", None) is not None
        else None
    )
    depth_meters = depth_to_meters(depth_input, depth_unit)
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
            "usd_exchange_rate": usd_fx_factor,
            "usd_amount": Decimal("0.00"),
            "actual_depth": depth_meters,
            "actual_depth_input": depth_input,
            "actual_depth_unit": depth_unit,
            "depth_entry_seq": 0,
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
    *,
    entry_usd_fx: Decimal = Decimal("1"),
    extra_rates: dict[str, Decimal] | None = None,
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
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
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
        # AFE saves replace their source rows. Reconnect a revised service to
        # its original locked allowance only when the mapping is unambiguous.
        # Do not inflate or rewrite the locked budget when a basis changes.
        if not matching:
            candidates = {row.id: row for previous in entry.baseline.service_rates
                          if previous.service_id == service.id
                          for row in budgets.get(f"service:{previous.source_afe_line_id}", [])}
            scoped = [row for row in candidates.values()
                      if row.section_id == line.hole_section_id and row.phase_id == line.phase_id]
            resolved = scoped if len(scoped) == 1 else list(candidates.values())
            if len(resolved) == 1:
                matching = resolved
                budget_key = f"service:{resolved[0].item_key}"
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
    if line.override_rate is None and base_currency and currency != base_currency:
        raise HTTPException(status_code=422, detail=f"Service {service.service_code}: daily rate currency must match the locked AFE rate ({base_currency})")
    factor, usd_fx = _resolve_fx(
        entry.baseline,
        currency,
        f"Service {service.service_code}",
        line_exchange_rate=line.exchange_rate,
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
    )
    if line.exchange_rate is not None and extra_rates is not None:
        extra_rates[currency] = factor
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
    amount = _money(sum((item.amount for item in line.cost_items), Decimal("0"))) if line.cost_items else _money(billable_quantity * selected_rate)
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
            "cost_items": [DailyCostServiceCostItem(description=item.description, amount=item.amount, sort_order=index) for index, item in enumerate(line.cost_items)],
            "service_id": service.id,
            "service_code_snapshot": service.service_code,
            "service_name_snapshot": service.service_name,
            "service_group_snapshot": service.service_group,
            "charging_basis": basis,
            "charge_category": line.charge_category,
            "baseline_service_rate_id": rate_id,
            "captured_rate": _rate(base_rate),
            "override_rate": _rate(line.override_rate) if line.override_rate is not None else None,
            "currency": currency,
            "exchange_rate": factor,
            "amount": amount,
            "standard_amount": _money(amount * factor),
            "usd_exchange_rate": usd_fx,
            "usd_amount": _money(amount * usd_fx),
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
    entry_usd_fx: Decimal = Decimal("1"),
    extra_rates: dict[str, Decimal] | None = None,
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
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
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
    if line.override_rate is None and base_currency and currency != base_currency:
        raise HTTPException(status_code=422, detail=f"{label_group} {item_code}: daily rate currency must match the locked baseline rate ({base_currency})")
    factor, usd_fx = _resolve_fx(
        entry.baseline,
        currency,
        f"{label_group} {item_code}",
        line_exchange_rate=line.exchange_rate,
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
    )
    if line.exchange_rate is not None and extra_rates is not None:
        extra_rates[currency] = factor
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
            "usd_exchange_rate": usd_fx,
            "usd_amount": _money(amount * usd_fx),
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


def _normalise_other_expense(
    db: Session,
    entry: DailyCostEntry,
    line: DailyCostOtherExpenseLineIn,
    existing_rows: dict[str, Any],
    *,
    entry_usd_fx: Decimal = Decimal("1"),
    extra_rates: dict[str, Decimal] | None = None,
) -> tuple[dict[str, Any], Any | None, str]:
    """Price one unexpected charge (Lost In Hole, hole problem, claim) on the sheet.

    These costs have no AFE or catalogue allowance, so the entered unit rate is the
    price, the line never carries a rate override, and the amount is deducted from
    the locked AFE total instead of reconciled against a budget line. The remark is
    mandatory because it is the only narrative that explains the charge.
    """
    old = _check_line_id(line.id, existing_rows, "Other expense")
    type_label = OTHER_EXPENSE_TYPE_LABELS.get(line.expense_type, line.expense_type)
    remarks = line.remarks.strip()
    if len(remarks) < OTHER_EXPENSE_MIN_REMARKS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Other expense {type_label}: remarks are mandatory (at least "
                f"{OTHER_EXPENSE_MIN_REMARKS} characters). State what was lost in hole, the incident, "
                "or the claim this charge covers."
            ),
        )
    base, _activity, _section, _phase, _vendor, _sub_activity = _base_fields(
        db,
        entry,
        line,
        label=f"Other expense {type_label}",
        quantity_unit=line.quantity_unit,
        existing_row=old,
        snapshots={},  # no catalogue rate book applies to an unbudgeted charge
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
    )
    currency = (line.currency or entry.standard_currency).upper()
    factor, usd_fx = _resolve_fx(
        entry.baseline,
        currency,
        f"Other expense {type_label}",
        line_exchange_rate=line.exchange_rate,
        entry_usd_fx=entry_usd_fx,
        extra_rates=extra_rates,
    )
    if line.exchange_rate is not None and extra_rates is not None:
        extra_rates[currency] = factor
    quantity = Decimal(line.quantity)
    amount = _money(quantity * _rate(line.unit_rate))
    base.update(
        {
            "captured_rate": _rate(line.unit_rate),
            "override_rate": None,
            "override_reason": "",
            "currency": currency,
            "exchange_rate": factor,
            "amount": amount,
            "standard_amount": _money(amount * factor),
            "usd_exchange_rate": usd_fx,
            "usd_amount": _money(amount * usd_fx),
            "rate_source": OTHER_EXPENSE_RATE_SOURCE,
            "baseline_budget_line_id": None,
            "budget_key": f"other:{line.expense_type}",
            "remarks": remarks,
            "quantity": quantity,
            "quantity_unit": line.quantity_unit,
            "expense_type": line.expense_type,
            "expense_type_label": type_label,
            "expense_description": line.expense_description,
        }
    )
    return base, old, _label(line.expense_type, type_label)


def _reject_duplicate_service_sub_activity(services: list[dict[str, Any]]) -> None:
    """One service may repeat on a date only under a different well sub activity.

    A service operated 18h under sub activity 1, 3h under sub activity 2 and
    3h under sub activity 3 is three separate ledger allocations. Different
    charge categories or section/phase scopes can coexist under a sub activity;
    an identical service/sub-activity/category/scope tuple is still a duplicate.
    Time-based hourly allocations are limited to 24 hours per service/category.
    """
    hours: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for fields in services:
        if fields["charging_basis"] == "Day Rate" and fields["quantity_unit"] == "hours" and fields["charge_category"] not in SERVICE_ONE_TIME:
            key = (fields["service_id"], fields["charge_category"])
            hours[key] += Decimal(fields["quantity"])
            if hours[key] > 24:
                raise HTTPException(status_code=422, detail=f"Service {fields['service_code_snapshot']}: total allocated {fields['charge_category']} hours cannot exceed 24 on one daily sheet")
    seen: dict[tuple, str] = {}
    for fields in services:
        key = (fields["service_id"], fields.get("sub_activity_id") or "", fields.get("charge_category"), fields.get("hole_section_id"), fields.get("phase_id"))
        code = fields.get("service_code_snapshot") or fields["service_id"]
        sub_label = fields.get("sub_activity_code_snapshot") or "the same sub activity"
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Service {code} is already entered for sub activity {sub_label} on this date. "
                    "Use a different sub activity, charge category or section/phase for a distinct allocation."
                ),
            )
        seen[key] = code


def _max_depth_seq_for_well_date(
    db: Session,
    organization_id: str,
    well_id: str,
    cost_date: date,
) -> int:
    highest = 0
    for model, _group in LINE_MODELS:
        val = db.scalar(
            select(func.max(model.depth_entry_seq))
            .join(DailyCostEntry, model.entry_id == DailyCostEntry.id)
            .where(
                model.organization_id == organization_id,
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.well_id == well_id,
                DailyCostEntry.cost_date == cost_date,
                DailyCostEntry.is_deleted.is_(False),
            )
        )
        if val is not None and int(val) > highest:
            highest = int(val)
    return highest


def _normalize_payload(
    db: Session,
    entry: DailyCostEntry,
    payload: DailyCostSaveIn,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Decimal],
    Decimal,
]:
    entry_usd_fx = (
        _fx(payload.usd_exchange_rate)
        if payload.usd_exchange_rate is not None and entry.standard_currency.upper() != "USD"
        else _fx(Decimal(entry.usd_exchange_rate or Decimal("1")))
    )
    if entry.standard_currency.upper() == "USD":
        entry_usd_fx = _fx(Decimal("1"))

    extra_rates: dict[str, Decimal] = {}
    existing_maps = _existing_line_maps(entry)
    snapshots = _rate_snapshot_index(entry.rate_baseline)
    budgets = _budget_by_key(entry.baseline)
    services: list[dict[str, Any]] = []
    consumables: list[dict[str, Any]] = []
    tangibles: list[dict[str, Any]] = []
    other_expenses: list[dict[str, Any]] = []
    staged: list[tuple[int, Any, Any | None, dict[str, Any]]] = []
    payload_pos = 0

    for order, line in enumerate(payload.services):
        fields, old, label = _normalise_service(
            db, entry, line, existing_maps[DailyCostServiceLine], snapshots, budgets,
            entry_usd_fx=entry_usd_fx, extra_rates=extra_rates,
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        services.append(fields)
        staged.append((payload_pos, line, old, fields))
        payload_pos += 1
    _reject_duplicate_service_sub_activity(services)
    for order, line in enumerate(payload.consumables):
        fields, old, label = _normalise_catalogue_line(
            db, entry, line, CONSUMABLE_KIND_MODEL[line.item_kind][0], line.item_kind, line.item_id,
            existing_maps[DailyCostConsumableLine], snapshots, budgets, tangible=False,
            entry_usd_fx=entry_usd_fx, extra_rates=extra_rates,
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        consumables.append(fields)
        staged.append((payload_pos, line, old, fields))
        payload_pos += 1
    for order, line in enumerate(payload.tangibles):
        fields, old, label = _normalise_catalogue_line(
            db, entry, line, Tangible, "tangible", line.tangible_id,
            existing_maps[DailyCostTangibleLine], snapshots, budgets, tangible=True,
            entry_usd_fx=entry_usd_fx, extra_rates=extra_rates,
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        tangibles.append(fields)
        staged.append((payload_pos, line, old, fields))
        payload_pos += 1
    for order, line in enumerate(payload.other_expenses):
        fields, old, label = _normalise_other_expense(
            db, entry, line, existing_maps[DailyCostOtherExpenseLine],
            entry_usd_fx=entry_usd_fx, extra_rates=extra_rates,
        )
        fields["sort_order"] = order
        fields["id"] = old.id if old else uid()
        other_expenses.append(fields)
        staged.append((payload_pos, line, old, fields))
        payload_pos += 1

    # Assign monotonic depth_entry_seq so the actual depth for (date, well, section)
    # strictly equals the LAST depth value entered in the daily cost register.
    next_seq = _max_depth_seq_for_well_date(db, entry.organization_id, entry.well_id, entry.cost_date)
    to_sequence: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for pos, line, old, fields in staged:
        same_existing = (
            old is not None
            and old.actual_depth_input == fields["actual_depth_input"]
            and old.actual_depth_unit == fields["actual_depth_unit"]
            and old.hole_section_id == fields["hole_section_id"]
            and line.depth_seq is None
            and int(old.depth_entry_seq or 0) > 0
        )
        if same_existing:
            fields["depth_entry_seq"] = int(old.depth_entry_seq)
        else:
            sort_key = (0, int(line.depth_seq), pos) if line.depth_seq is not None else (1, pos, pos)
            to_sequence.append((sort_key, fields))
    to_sequence.sort(key=lambda item: item[0])
    for _, fields in to_sequence:
        next_seq += 1
        fields["depth_entry_seq"] = next_seq

    return services, consumables, tangibles, other_expenses, extra_rates, entry_usd_fx


def _sum_group(lines: Sequence[Any]) -> Decimal:
    return _money(sum((Decimal(row.standard_amount) for row in lines), Decimal("0")))


def _sum_group_usd(lines: Sequence[Any]) -> Decimal:
    return _money(sum((Decimal(row.usd_amount) for row in lines), Decimal("0")))


def _sum_classification(lines: Iterable[Any], classification: str) -> Decimal:
    return _money(sum((Decimal(row.standard_amount) for row in lines if row.classification == classification), Decimal("0")))


def _sum_classification_usd(lines: Iterable[Any], classification: str) -> Decimal:
    return _money(sum((Decimal(row.usd_amount) for row in lines if row.classification == classification), Decimal("0")))


def _line_snapshot_for_audit(fields: dict[str, Any]) -> tuple[Decimal | None, str, str]:
    value = fields.pop("_override_audit", None)
    if value is None:
        return None, "", ""
    old_rate, new_rate, reason, currency, label = value
    # Kept in the transient dictionary only for the same-transaction audit below.
    fields["_override_audit_data"] = value
    return new_rate, reason, label


def _persist_group(entry: DailyCostEntry, model: type[Any], fields_group: list[dict[str, Any]]) -> tuple[list[Any], list[tuple[Any, Any]]]:
    existing = {row.id: row for row in getattr(entry, LINE_RELATIONSHIP[model])}
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
    setattr(entry, LINE_RELATIONSHIP[model], persisted)
    return persisted, overrides


def _upsert_lines(
    db: Session,
    entry: DailyCostEntry,
    services: list[dict[str, Any]],
    consumables: list[dict[str, Any]],
    tangibles: list[dict[str, Any]],
    other_expenses: list[dict[str, Any]],
    *,
    extra_rates: dict[str, Decimal] | None = None,
    entry_usd_fx: Decimal = Decimal("1"),
    user: User,
    request: Request | None,
) -> None:
    if extra_rates:
        by_code = {row.currency_code.upper(): row for row in entry.baseline.exchange_rates}
        next_sort = max((row.sort_order for row in entry.baseline.exchange_rates), default=-1) + 1
        for code, rate_val in sorted(extra_rates.items()):
            existing_rate = by_code.get(code.upper())
            if existing_rate is not None:
                existing_rate.rate = _fx(rate_val)
            else:
                entry.baseline.exchange_rates.append(
                    DailyCostBaselineExchangeRate(
                        id=uid(),
                        organization_id=entry.organization_id,
                        currency_code=code.upper(),
                        rate=_fx(rate_val),
                        sort_order=next_sort,
                    )
                )
                next_sort += 1
    _, service_overrides = _persist_group(entry, DailyCostServiceLine, services)
    _, consumable_overrides = _persist_group(entry, DailyCostConsumableLine, consumables)
    _, tangible_overrides = _persist_group(entry, DailyCostTangibleLine, tangibles)
    _, other_overrides = _persist_group(entry, DailyCostOtherExpenseLine, other_expenses)
    _flush(db, operation="saving daily cost lines")
    all_lines = [*entry.service_lines, *entry.consumable_lines, *entry.tangible_lines, *entry.other_expense_lines]
    entry.usd_exchange_rate = _fx(entry_usd_fx)
    entry.services_total = _sum_group(entry.service_lines)
    entry.consumables_total = _sum_group(entry.consumable_lines)
    entry.tangibles_total = _sum_group(entry.tangible_lines)
    # Other expenses are totalled on their own so the AFE reconciliation can show
    # the deduction, then they join the day's actual cost like any other group.
    entry.other_expenses_total = _sum_group(entry.other_expense_lines)
    entry.total_cost = _money(
        entry.services_total + entry.consumables_total + entry.tangibles_total + entry.other_expenses_total
    )
    entry.upa_total = _sum_classification(all_lines, "UPA")
    entry.npt_total = _sum_classification(all_lines, "NPT")
    entry.services_total_usd = _sum_group_usd(entry.service_lines)
    entry.consumables_total_usd = _sum_group_usd(entry.consumable_lines)
    entry.tangibles_total_usd = _sum_group_usd(entry.tangible_lines)
    entry.other_expenses_total_usd = _sum_group_usd(entry.other_expense_lines)
    entry.total_cost_usd = _money(
        entry.services_total_usd + entry.consumables_total_usd + entry.tangibles_total_usd + entry.other_expenses_total_usd
    )
    entry.upa_total_usd = _sum_classification_usd(all_lines, "UPA")
    entry.npt_total_usd = _sum_classification_usd(all_lines, "NPT")
    entry.updated_by = _actor_name(user)
    entry.updated_at = _now()
    for line, change in [*service_overrides, *consumable_overrides, *tangible_overrides, *other_overrides]:
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
    if isinstance(line, DailyCostOtherExpenseLine):
        # No allowance to match: the AFE total is reduced by this amount instead.
        return f"Other expenses — {line.expense_type_label}"
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
        "usd_exchange_rate": Decimal(line.usd_exchange_rate),
        "usd_amount": Decimal(line.usd_amount),
        "actual_depth": Decimal(line.actual_depth) if line.actual_depth is not None else None,
        "actual_depth_entered": Decimal(line.actual_depth_input) if line.actual_depth_input is not None else None,
        "actual_depth_unit": normalize_depth_unit(line.actual_depth_unit),
        "depth_seq": int(line.depth_entry_seq or 0),
        "rate_source": line.rate_source,
        "rate_revision_number": line.rate_revision_number,
        "rate_effective_date": line.rate_effective_date,
        "baseline_budget_line_id": line.baseline_budget_line_id,
        "budget_key": line.budget_key,
        "budget_name": _line_budget_name(line, labels),
        "override_reason": line.override_reason,
        "remarks": line.remarks,
    }


def _line_out(line: Any, labels: dict[str, DailyCostBaselineBudgetLine]) -> Any:
    """Map one line onto its API output shape.

    Saved rows and transient preview rows are instances of the same models, so the
    sheet and the unsaved preview are described by exactly the same fields.
    """
    common = _daily_line_common(line, labels)
    if isinstance(line, DailyCostServiceLine):
        return DailyCostServiceLineOut(
            **common, cost_items=[{"description": item.description, "amount": item.amount} for item in line.cost_items], service_id=line.service_id, service_code=line.service_code_snapshot,
            service_name=line.service_name_snapshot, service_group=line.service_group_snapshot, charging_basis=line.charging_basis,
            charge_category=line.charge_category, baseline_service_rate_id=line.baseline_service_rate_id,
        )
    if isinstance(line, DailyCostConsumableLine):
        return DailyCostConsumableLineOut(
            **common, category=line.category, item_kind=line.item_kind, item_id=line.item_id,
            item_code=line.item_code_snapshot, item_name=line.item_name_snapshot, uom=line.uom,
            catalogue_rate_snapshot_id=line.catalogue_rate_snapshot_id,
        )
    if isinstance(line, DailyCostOtherExpenseLine):
        return DailyCostOtherExpenseLineOut(
            **common, expense_type=line.expense_type, expense_type_label=line.expense_type_label,
            expense_description=line.expense_description,
        )
    return DailyCostTangibleLineOut(
        **common, tangible_id=line.tangible_id, tangible_code=line.tangible_code_snapshot,
        tangible_name=line.tangible_name_snapshot, uom=line.uom,
        catalogue_rate_snapshot_id=line.catalogue_rate_snapshot_id,
    )


def _line_outputs(entry: DailyCostEntry) -> tuple[
    list[DailyCostServiceLineOut], list[DailyCostConsumableLineOut],
    list[DailyCostTangibleLineOut], list[DailyCostOtherExpenseLineOut],
]:
    labels = _budget_label_map(entry.baseline)
    return (
        [_line_out(row, labels) for row in entry.service_lines],
        [_line_out(row, labels) for row in entry.consumable_lines],
        [_line_out(row, labels) for row in entry.tangible_lines],
        [_line_out(row, labels) for row in entry.other_expense_lines],
    )


def resolve_actual_depths(
    db: Session,
    organization_id: str,
    *,
    well_ids: Sequence[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    exclude_entry_id: str | None = None,
    preview_entry: tuple[str, date, str, Sequence[Any]] | None = None,
) -> tuple[
    dict[tuple[str, date, str | None], DailyCostSectionDepthOut],
    dict[tuple[str, date], DailyCostSectionDepthOut],
    dict[tuple[str, str | None], DailyCostSectionDepthOut],
]:
    """Resolve standardized meter actual depths from the daily cost register.

    Rule:
      * Every entered depth is stored standardized in metres (``feet / 3.281``).
      * For a selected date, selected well, and selected section, actual depth
        always takes the **last depth value entered** ordered by ``depth_entry_seq``
        (with ``sort_order`` / ``id`` tie-breaking).
      * Across multiple dates on a well/section, the latest date's last-entered
        depth governs cumulative section progress.
    """
    branches = []
    for group_idx, (model, _group) in enumerate(LINE_MODELS):
        stmt = (
            select(
                DailyCostEntry.well_id.label("well_id"),
                DailyCostEntry.cost_date.label("cost_date"),
                DailyCostEntry.daily_cost_code.label("daily_cost_code"),
                model.hole_section_id.label("hole_section_id"),
                model.section_code_snapshot.label("section_code"),
                model.section_name_snapshot.label("section_name"),
                model.actual_depth.label("actual_depth"),
                model.actual_depth_input.label("actual_depth_input"),
                model.actual_depth_unit.label("actual_depth_unit"),
                model.depth_entry_seq.label("depth_entry_seq"),
                literal(group_idx).label("group_idx"),
                model.sort_order.label("sort_order"),
                model.id.label("line_id"),
            )
            .join(DailyCostEntry, model.entry_id == DailyCostEntry.id)
            .where(
                model.organization_id == organization_id,
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.is_deleted.is_(False),
                model.actual_depth.is_not(None),
            )
        )
        if well_ids is not None:
            if not well_ids:
                return {}, {}, {}
            stmt = stmt.where(DailyCostEntry.well_id.in_(list(well_ids)))
        if date_from is not None:
            stmt = stmt.where(DailyCostEntry.cost_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(DailyCostEntry.cost_date <= date_to)
        if exclude_entry_id is not None:
            stmt = stmt.where(DailyCostEntry.id != exclude_entry_id)
        branches.append(stmt)

    combined = union_all(*branches).subquery()
    ordered_rows: list[tuple[str, date, str, str | None, str, str, Decimal, Decimal | None, str, int, int, int, str]] = [
        (
            str(r.well_id),
            r.cost_date,
            str(r.daily_cost_code or ""),
            str(r.hole_section_id) if r.hole_section_id else None,
            str(r.section_code or ""),
            str(r.section_name or ""),
            Decimal(r.actual_depth),
            Decimal(r.actual_depth_input) if r.actual_depth_input is not None else None,
            normalize_depth_unit(r.actual_depth_unit),
            int(r.depth_entry_seq or 0),
            int(r.group_idx or 0),
            int(r.sort_order or 0),
            str(r.line_id or ""),
        )
        for r in db.execute(select(combined)).all()
    ]

    if preview_entry is not None:
        p_well_id, p_cost_date, p_code, p_lines = preview_entry
        for idx, p_line in enumerate(p_lines):
            if getattr(p_line, "actual_depth", None) is not None:
                ordered_rows.append(
                    (
                        p_well_id,
                        p_cost_date,
                        p_code,
                        p_line.hole_section_id,
                        p_line.section_code_snapshot or "",
                        p_line.section_name_snapshot or "",
                        Decimal(p_line.actual_depth),
                        Decimal(p_line.actual_depth_input) if p_line.actual_depth_input is not None else None,
                        normalize_depth_unit(p_line.actual_depth_unit),
                        int(p_line.depth_entry_seq or 0),
                        99,
                        idx,
                        str(p_line.id or ""),
                    )
                )

    ordered_rows.sort(key=lambda item: (item[0], item[1], item[9], item[10], item[11], item[12]))

    by_well_date_section: dict[tuple[str, date, str | None], DailyCostSectionDepthOut] = {}
    by_well_date: dict[tuple[str, date], DailyCostSectionDepthOut] = {}
    by_well_section: dict[tuple[str, str | None], DailyCostSectionDepthOut] = {}
    for (
        w_id,
        c_date,
        dc_code,
        sec_id,
        sec_code,
        sec_name,
        act_depth,
        ent_depth,
        ent_unit,
        _seq,
        _gidx,
        _sord,
        _lid,
    ) in ordered_rows:
        out = DailyCostSectionDepthOut(
            hole_section_id=sec_id,
            section_code=sec_code,
            section_name=sec_name,
            actual_depth=_money(act_depth),
            depth_unit="m",
            entered_depth=_money(ent_depth) if ent_depth is not None else None,
            entered_unit=ent_unit,
            daily_cost_code=dc_code,
        )
        by_well_date_section[(w_id, c_date, sec_id)] = out
        by_well_date[(w_id, c_date)] = out
        by_well_section[(w_id, sec_id)] = out
    return by_well_date_section, by_well_date, by_well_section


def _entry_out(
    entry: DailyCostEntry,
    *,
    day_depth: DailyCostSectionDepthOut | None = None,
    section_depths: list[DailyCostSectionDepthOut] | None = None,
    cumulative_cost: Decimal | None = None,
) -> DailyCostEntryOut:
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
        lead_lag_kind=entry.lead_lag_kind or "",
        lead_lag_days=Decimal(entry.lead_lag_days) if entry.lead_lag_days is not None else None,
        status=entry.status,
        submitted_at=entry.submitted_at,
        submitted_by=entry.submitted_by,
        status_remarks=entry.status_remarks,
        services_count=len(entry.service_lines),
        consumables_count=len(entry.consumable_lines),
        tangibles_count=len(entry.tangible_lines),
        other_expenses_count=len(entry.other_expense_lines),
        services_total=Decimal(entry.services_total),
        consumables_total=Decimal(entry.consumables_total),
        tangibles_total=Decimal(entry.tangibles_total),
        other_expenses_total=Decimal(entry.other_expenses_total),
        total_cost=Decimal(entry.total_cost),
        upa_total=Decimal(entry.upa_total),
        npt_total=Decimal(entry.npt_total),
        usd_exchange_rate=Decimal(entry.usd_exchange_rate),
        services_total_usd=Decimal(entry.services_total_usd),
        consumables_total_usd=Decimal(entry.consumables_total_usd),
        tangibles_total_usd=Decimal(entry.tangibles_total_usd),
        other_expenses_total_usd=Decimal(entry.other_expenses_total_usd),
        total_cost_usd=Decimal(entry.total_cost_usd),
        upa_total_usd=Decimal(entry.upa_total_usd),
        npt_total_usd=Decimal(entry.npt_total_usd),
        actual_depth=day_depth.actual_depth if day_depth is not None else None,
        depth_unit="m",
        section_depths=section_depths or [],
        rate_baseline_locked_at=entry.rate_baseline.locked_at,
        budget_baseline_locked_at=entry.baseline.locked_at,
        warning_count=entry.warning_count,
        # Filled by the register listing, which knows the running well/AFE total
        # through each sheet date. A single-sheet response leaves it unknown.
        cumulative_cost=_money(cumulative_cost if cumulative_cost is not None else Decimal("0")),
        is_deleted=entry.is_deleted,
        deleted_at=entry.deleted_at,
        created_by=entry.created_by,
        updated_by=entry.updated_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _comparison(db: Session, entry: DailyCostEntry, effective_on: date | None = None) -> DailyCostComparison:
    """The locked AFE plan against every actual recorded through the sheet date.

    Other-expense lines have no budget line to reconcile to, so they are summed as
    their own group and charged against the AFE total: the returned ``balance`` is
    the planned amount less the tracked actuals less those unexpected charges.
    """
    as_of = effective_on or entry.cost_date
    group_names = ALL_COST_GROUPS
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
    entry_dates = {
        entry_id: cost_date
        for entry_id, cost_date in db.execute(
            select(DailyCostEntry.id, DailyCostEntry.cost_date).where(DailyCostEntry.id.in_(entries))
        ).all()
    }
    actual_by_group: dict[str, Decimal] = {key: Decimal("0") for key in group_names}
    # The same actuals cut by whether they were recorded on the report date or
    # before it, so a cost report can print "up to last day", "cost on this
    # day" and the cumulative total as separate columns.
    actual_by_group_today: dict[str, Decimal] = {key: Decimal("0") for key in group_names}
    actual_by_key_today: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    actual_by_key: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    # The same actuals cut by the activity classification of each line, so the
    # service-wise report can print planned / UPA / NPT actuals per budget line.
    actual_by_class: dict[tuple[str, str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    actual_by_group_class: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    unplanned_meta: dict[tuple[str, str], tuple[str, str, str]] = {}
    actual_all: list[tuple[str, Any]] = []
    if entries:
        for model, group in LINE_MODELS:
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
                on_report_date = entry_dates.get(row.entry_id) == as_of
                actual_by_group[group] += amount
                actual_by_key[(group, row.budget_key)] += amount
                if on_report_date:
                    actual_by_group_today[group] += amount
                    actual_by_key_today[(group, row.budget_key)] += amount
                actual_by_class[(group, row.budget_key, row.classification)] += amount
                actual_by_group_class[(group, row.classification)] += amount
                actual_all.append((group, row))
                if (group, row.budget_key) not in planned_keys:
                    line_group = ""
                    if isinstance(row, DailyCostServiceLine):
                        code, name = row.service_code_snapshot, row.service_name_snapshot
                        kind, line_group = "service", row.service_group_snapshot
                    elif isinstance(row, DailyCostConsumableLine):
                        code, name = row.item_code_snapshot, row.item_name_snapshot
                        kind = "consumable"
                    elif isinstance(row, DailyCostOtherExpenseLine):
                        # Grouped per expense type, so the deduction names the event.
                        code, name = row.expense_type, row.expense_type_label
                        kind = "other_expense"
                    else:
                        code, name = row.tangible_code_snapshot, row.tangible_name_snapshot
                        kind = "tangible"
                    unplanned_meta[(group, row.budget_key)] = (code, name or kind, line_group)

    comparison_lines: list[DailyCostBudgetComparison] = []
    keys = set(planned_keys) | set(actual_by_key)
    for group, key in sorted(keys, key=lambda item: (group_names.index(item[0]), item[1])):
        metadata = budget_meta.get((group, key))
        actual = _money(actual_by_key[(group, key)])
        planned = _money(planned_by_key[(group, key)])
        if metadata:
            code, name = metadata.item_code_snapshot, metadata.item_name_snapshot
            kind = metadata.budget_kind
            service_group = metadata.service_group
        else:
            code, name, service_group = unplanned_meta.get(
                (group, key), ("", "Unbudgeted actual", "")
            )
            kind = key.split(":", 1)[0]
        comparison_lines.append(
            DailyCostBudgetComparison(
                budget_key=key,
                cost_group=group,
                budget_kind=kind,
                item_code=code,
                item_name=name,
                service_group=service_group,
                planned=planned,
                actual_to_date=actual,
                actual_prior=_money(actual - _money(actual_by_key_today[(group, key)])),
                actual_today=_money(actual_by_key_today[(group, key)]),
                sort_order=metadata.sort_order if metadata else 9999,
                balance=_money(planned - actual),
                is_planned=(group, key) in planned_keys,
                actual_planned=_money(actual_by_class[(group, key, "Planned")]),
                actual_upa=_money(actual_by_class[(group, key, "UPA")]),
                actual_npt=_money(actual_by_class[(group, key, "NPT")]),
            )
        )

    groups = [
        DailyCostComparisonGroup(
            cost_group=group,
            planned=_money(planned_by_group[group]),
            actual_to_date=_money(actual_by_group[group]),
            actual_prior=_money(actual_by_group[group] - actual_by_group_today[group]),
            actual_today=_money(actual_by_group_today[group]),
            balance=_money(planned_by_group[group] - actual_by_group[group]),
            actual_planned=_money(actual_by_group_class[(group, "Planned")]),
            actual_upa=_money(actual_by_group_class[(group, "UPA")]),
            actual_npt=_money(actual_by_group_class[(group, "NPT")]),
        )
        for group in group_names
    ]
    tracked_actual_to_date = _money(sum(actual_by_group[group] for group in TRACKED_COST_GROUPS))
    other_expenses_to_date = actual_by_group["Other Expenses"]
    planned_total = _money(sum(planned_by_group.values(), Decimal("0")))
    actual_to_date = _money(tracked_actual_to_date + other_expenses_to_date)
    # ---- LIH Cost Register ---------------------------------------------------
    # The register is manual and lives outside the daily cost groups. Its cost is
    # added to the actual cost and deducted from the AFE amount explicitly, so
    # the balance is (AFE total − LIH) − daily actuals.
    lih_to_date = lih_cost_service.lih_total_for_afe(
        db, entry.organization_id, entry.afe_id, through_date=as_of, currency=entry.standard_currency,
    )
    afe_available = _money(planned_total - lih_to_date)
    actual_including_lih = _money(actual_to_date + lih_to_date)
    upa = _money(sum((Decimal(row.standard_amount) for _, row in actual_all if row.classification == "UPA"), Decimal("0")))
    npt = _money(sum((Decimal(row.standard_amount) for _, row in actual_all if row.classification == "NPT"), Decimal("0")))
    # An approved SOW adjustment revises the plan; the locked planned_total stays
    # the original AFE amount and the adjusted amount is reported alongside it.
    adjusted_total: Decimal | None = None
    sow_map = _effective_sow_map(db, entry.organization_id, [entry.afe_id])
    adjustment = sow_map.get(entry.afe_id)
    if adjustment is not None and str(adjustment.standard_currency) == entry.standard_currency:
        adjusted_total = _money(Decimal(adjustment.adjusted_total))
    return DailyCostComparison(
        effective_on=as_of,
        currency=entry.standard_currency,
        planned_total=planned_total,
        actual_to_date=actual_to_date,
        tracked_actual_to_date=tracked_actual_to_date,
        other_expenses_to_date=_money(other_expenses_to_date),
        lih_cost_to_date=lih_to_date,
        actual_including_lih=actual_including_lih,
        afe_available=afe_available,
        balance=_money(planned_total - lih_to_date - actual_to_date),
        over_budget=actual_including_lih > planned_total,
        includes_draft_entries=True,
        upa_to_date=upa,
        npt_to_date=npt,
        groups=groups,
        budget_lines=comparison_lines,
        adjusted_planned_total=adjusted_total,
        adjusted_balance=(
            _money(adjusted_total - lih_to_date - actual_to_date) if adjusted_total is not None else None
        ),
        has_adjustment=adjusted_total is not None,
    )


def _other_expense_label(lines: Sequence[Any]) -> str:
    """A short, de-duplicated description of the recorded expense types."""
    seen: list[str] = []
    for row in lines:
        label = getattr(row, "expense_type_label", "")
        if label and label not in seen:
            seen.append(label)
    if not seen:
        return "unbudgeted charges"
    text = ", ".join(seen[:3])
    return text + (f" and {len(seen) - 3} more" if len(seen) > 3 else "")


def _warnings(entry: DailyCostEntry, comparison: DailyCostComparison) -> list[DailyCostWarnings]:
    warnings: list[DailyCostWarnings] = []
    if entry.other_expense_lines:
        warnings.append(
            DailyCostWarnings(
                code="other-expenses-deducted", severity="warning",
                message=(
                    f"Other expenses recorded on this sheet ({_other_expense_label(entry.other_expense_lines)}): "
                    f"{entry.standard_currency} {entry.other_expenses_total:,.2f}. These have no AFE allowance and are "
                    f"deducted from the AFE total, leaving {entry.standard_currency} {comparison.balance:,.2f}."
                ),
            )
        )
    elif comparison.other_expenses_to_date:
        warnings.append(
            DailyCostWarnings(
                code="other-expenses-deducted", severity="info",
                message=(
                    f"Other expenses of {entry.standard_currency} {comparison.other_expenses_to_date:,.2f} recorded "
                    "on earlier sheets of this AFE are deducted from the AFE total."
                ),
            )
        )
    if comparison.lih_cost_to_date:
        warnings.append(
            DailyCostWarnings(
                code="lih-cost-deducted", severity="warning",
                message=(
                    f"LIH Cost Register: {entry.standard_currency} {comparison.lih_cost_to_date:,.2f} filed against "
                    f"this AFE is added to the actual cost and deducted from the AFE total. AFE available after "
                    f"LIH: {entry.standard_currency} {comparison.afe_available:,.2f}; actual cost including LIH: "
                    f"{entry.standard_currency} {comparison.actual_including_lih:,.2f}."
                ),
            )
        )
    if comparison.over_budget:
        warnings.append(
            DailyCostWarnings(
                code="afe-over-budget", severity="warning",
                message=f"Actual cost to {comparison.effective_on.isoformat()} (including LIH) is over the AFE budget by {entry.standard_currency} {abs(comparison.balance):,.2f}.",
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
        1 for row in [*entry.service_lines, *entry.consumable_lines, *entry.tangible_lines, *entry.other_expense_lines]
        if row.override_rate is not None
    )
    if overrides:
        warnings.append(
            DailyCostWarnings(code="rate-overrides", severity="info", message=f"{overrides} daily rate override(s) are recorded with a reason.")
        )
    return warnings


def get_day(
    db: Session, organization_id: str, entry_id: str, *, progress_cache: dict | None = None,
) -> DailyCostDayOut:
    entry = _get_entry(db, organization_id=organization_id, entry_id=entry_id, deleted=False)
    services, consumables, tangibles, other_expenses = _line_outputs(entry)
    comparison = _comparison(db, entry)
    by_section, by_day, _ = resolve_actual_depths(
        db,
        organization_id,
        well_ids=[entry.well_id],
        date_from=entry.cost_date,
        date_to=entry.cost_date,
    )
    sec_depths = [
        val for (w_id, c_date, _sec), val in by_section.items()
        if w_id == entry.well_id and c_date == entry.cost_date
    ]
    return DailyCostDayOut(
        entry=_entry_out(
            entry,
            day_depth=by_day.get((entry.well_id, entry.cost_date)),
            section_depths=sec_depths,
        ),
        services=services,
        consumables=consumables,
        tangibles=tangibles,
        other_expenses=other_expenses,
        comparison=comparison,
        warnings=_warnings(entry, comparison),
        progress=_entry_progress_row(db, entry, progress_cache),
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
            service_rows, consumable_rows, tangible_rows, other_rows, extra_rates, entry_usd_fx = _normalize_payload(db, entry, payload)
            entry.remarks = payload.remarks
            # Lead / lag belongs to the sheet, entered once with the register.
            entry.lead_lag_kind = payload.lead_lag_kind
            entry.lead_lag_days = _rate(payload.lead_lag_days) if payload.lead_lag_days is not None else None
            other_before = Decimal(entry.other_expenses_total)
            _upsert_lines(
                db, entry, service_rows, consumable_rows, tangible_rows, other_rows,
                extra_rates=extra_rates, entry_usd_fx=entry_usd_fx,
                user=user, request=request,
            )
            entry.warning_count = (
                int(bool(entry.upa_total)) + int(bool(entry.npt_total)) + int(bool(entry.other_expenses_total))
            )
            _audit(
                db,
                user=user,
                action=action,
                entity_type="daily_cost",
                entity_id=entry.id,
                label=entry.daily_cost_code,
                summary=(
                    f"{'Imported' if action == 'import' else 'Saved'} daily costs for {entry.well_code_snapshot} on {entry.cost_date.isoformat()}: "
                    f"{len(service_rows)} service, {len(consumable_rows)} consumable, {len(tangible_rows)} tangible "
                    f"and {len(other_rows)} other-expense line(s); "
                    f"{entry.standard_currency} {entry.total_cost:,.2f}"
                ),
                request=request,
            )
            if entry.other_expenses_total != other_before:
                # An unexpected charge changes what the AFE can still be spent on,
                # so it is worth its own audit entry next to the save itself.
                _audit(
                    db,
                    user=user,
                    action="other_expense",
                    entity_type="daily_cost",
                    entity_id=entry.id,
                    label=entry.daily_cost_code,
                    summary=(
                        f"Other expenses for {entry.daily_cost_code} changed from "
                        f"{entry.standard_currency} {other_before:,.2f} to {entry.standard_currency} "
                        f"{entry.other_expenses_total:,.2f} ({_other_expense_label(entry.other_expense_lines)}); "
                        f"deducted from AFE {entry.afe_code_snapshot}"
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
    services_in, consumables_in, tangibles_in, other_in, _extra_rates, _entry_usd_fx = _normalize_payload(db, entry, payload)
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
    other_rows = output(DailyCostOtherExpenseLine, other_in)
    temp = type("PreviewEntry", (), {})()
    temp.baseline = entry.baseline
    temp.service_lines = service_rows
    temp.consumable_lines = consumable_rows
    temp.tangible_lines = tangible_rows
    temp.other_expense_lines = other_rows
    temp.standard_currency = entry.standard_currency
    # Mirror the stored output mapping without attaching preview rows to the session.
    services_out = [_line_out(row, labels) for row in service_rows]
    consumables_out = [_line_out(row, labels) for row in consumable_rows]
    tangibles_out = [_line_out(row, labels) for row in tangible_rows]
    other_out = [_line_out(row, labels) for row in other_rows]
    all_rows = [*service_rows, *consumable_rows, *tangible_rows, *other_rows]
    service_total = _sum_group(service_rows)
    consumable_total = _sum_group(consumable_rows)
    tangible_total = _sum_group(tangible_rows)
    other_total = _sum_group(other_rows)
    upa_total = _sum_classification(all_rows, "UPA")
    npt_total = _sum_classification(all_rows, "NPT")
    warnings: list[DailyCostWarnings] = []
    total = _money(service_total + consumable_total + tangible_total + other_total)
    total_usd = _money(
        _sum_group_usd(service_rows)
        + _sum_group_usd(consumable_rows)
        + _sum_group_usd(tangible_rows)
        + _sum_group_usd(other_rows)
    )
    by_section, by_day, _ = resolve_actual_depths(
        db,
        organization_id,
        well_ids=[entry.well_id],
        date_from=entry.cost_date,
        date_to=entry.cost_date,
        exclude_entry_id=entry.id,
        preview_entry=(entry.well_id, entry.cost_date, entry.daily_cost_code, all_rows),
    )
    preview_section_depths = [
        val for (w_id, c_date, _sec), val in by_section.items()
        if w_id == entry.well_id and c_date == entry.cost_date
    ]
    preview_day_depth = by_day.get((entry.well_id, entry.cost_date))
    if other_total:
        warnings.append(DailyCostWarnings(
            code="other-expenses-preview", severity="warning",
            message=(
                f"Other expenses in this preview: {entry.standard_currency} {other_total:,.2f} "
                f"({_other_expense_label(other_rows)}). They have no AFE allowance and reduce the AFE amount."
            ),
        ))
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
        other_expenses=other_out,
        services_total=service_total,
        consumables_total=consumable_total,
        tangibles_total=tangible_total,
        other_expenses_total=other_total,
        total_cost=total,
        upa_total=upa_total,
        npt_total=npt_total,
        total_cost_usd=total_usd,
        actual_depth=preview_day_depth.actual_depth if preview_day_depth is not None else None,
        depth_unit="m",
        section_depths=preview_section_depths,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Register, status transitions, soft delete/restore and overview
# ---------------------------------------------------------------------------


def _cumulative_cost_index(db: Session, organization_id: str) -> dict[tuple[str, str, date], Decimal]:
    """Running total cost per well + AFE through each cost date (active sheets)."""
    totals = db.execute(
        select(
            DailyCostEntry.well_id, DailyCostEntry.afe_id, DailyCostEntry.cost_date,
            func.sum(DailyCostEntry.total_cost),
        )
        .where(
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.is_deleted.is_(False),
        )
        .group_by(DailyCostEntry.well_id, DailyCostEntry.afe_id, DailyCostEntry.cost_date)
        .order_by(DailyCostEntry.well_id, DailyCostEntry.afe_id, DailyCostEntry.cost_date)
    ).all()
    running: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    index: dict[tuple[str, str, date], Decimal] = {}
    for well_id, afe_id, cost_date, total in totals:
        key = (str(well_id), str(afe_id))
        running[key] += Decimal(total or 0)
        index[(key[0], key[1], cost_date)] = _money(running[key])
    return index


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
            selectinload(DailyCostEntry.tangible_lines), selectinload(DailyCostEntry.other_expense_lines),
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
    if not rows:
        return []
    distinct_wells = list({row.well_id for row in rows})
    by_section, by_day, _ = resolve_actual_depths(
        db,
        organization_id,
        well_ids=distinct_wells,
        date_from=date_from,
        date_to=date_to,
    )
    sections_for_key: dict[tuple[str, date], list[DailyCostSectionDepthOut]] = defaultdict(list)
    for (w_id, c_date, _sec), val in by_section.items():
        sections_for_key[(w_id, c_date)].append(val)
    cumulative = _cumulative_cost_index(db, organization_id)
    return [
        _entry_out(
            row,
            day_depth=by_day.get((row.well_id, row.cost_date)),
            section_depths=sections_for_key.get((row.well_id, row.cost_date), []),
            # The day's own cost stays on the row; this is the running total of
            # the same well + AFE through that date, shown beside it.
            cumulative_cost=cumulative.get(
                (row.well_id, row.afe_id, row.cost_date), Decimal(row.total_cost)
            ),
        )
        for row in rows
    ]


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
        # Late reopens (older than the amendment threshold) are amendments:
        # they need the dedicated amendment right and are logged separately
        # from the ordinary audit trail. Recent reopens keep working exactly
        # as before for anyone with the reopen right.
        days_old = (date.today() - entry.cost_date).days
        amendment_threshold = 30
        try:
            from app.services.sow_adjustment import AMENDMENT_THRESHOLD_DAYS

            amendment_threshold = AMENDMENT_THRESHOLD_DAYS
        except Exception:  # noqa: BLE001 - fall back to the default window
            pass
        if days_old > amendment_threshold and not _has_permission(db, user, "daily-cost:amend"):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This sheet is {days_old} days old. Reopening a sheet older than "
                    f"{amendment_threshold} days needs the daily-cost amendment right."
                ),
            )
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
        try:
            from app.services.sow_adjustment import record_amendment

            record_amendment(db, entry=entry, user=user, reason=data.remarks)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - unmigrated database has no amendment table yet
            pass
        _commit(db)
    return _created_day_or_503(db, organization_id, entry.id)


def _has_permission(db: Session, user: User, permission: str) -> bool:
    """True when the user is an owner or holds the named permission key.

    Mirrors api.deps.require: owners bypass, everyone else needs the key on
    one of their roles. The roles are already loaded on the request user.
    """
    roles = list(user.roles or ())
    if any(role.is_owner for role in roles):
        return True
    return permission in {item.key for role in roles for item in (role.permissions or ())}


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
                 selectinload(DailyCostEntry.tangible_lines), selectinload(DailyCostEntry.other_expense_lines))
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
        # Other expenses are never budgeted in an AFE: planned stays at zero so the
        # group balance is the amount taken off the AFE total.
    actual_by_baseline: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in active:
        currency = row.standard_currency
        amount = Decimal(row.total_cost)
        actual[currency] += amount
        actual_by_baseline[row.baseline_id] += amount
        group_actual[(currency, "Services")] += Decimal(row.services_total)
        group_actual[(currency, "Consumables")] += Decimal(row.consumables_total)
        group_actual[(currency, "Tangibles")] += Decimal(row.tangibles_total)
        group_actual[(currency, "Other Expenses")] += Decimal(row.other_expenses_total)
    currencies = sorted(set(planned) | set(actual))
    planned_out = {code: _money(planned[code]) for code in currencies}
    actual_out = {code: _money(actual[code]) for code in currencies}
    remaining_out = {code: _money(planned[code] - actual[code]) for code in currencies}
    # The LIH Cost Register is reported apart: it is deducted from the AFE total,
    # not reconciled against a budget line.
    lih_out = lih_cost_service.lih_currency_totals(db, organization_id)
    lih_entries_count, lih_lines_count = db.execute(
        select(func.count(LihCostEntry.id), func.coalesce(func.sum(LihCostEntry.line_count), 0)).where(
            LihCostEntry.organization_id == organization_id, LihCostEntry.is_deleted.is_(False)
        )
    ).one()
    groups = [
        DailyCostGroupSummary(
            currency=currency, cost_group=group, planned=_money(group_planned[(currency, group)]),
            actual=_money(group_actual[(currency, group)]),
            balance=_money(group_planned[(currency, group)] - group_actual[(currency, group)]),
        )
        for currency in currencies for group in ALL_COST_GROUPS
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
        lih_cost_by_currency={code: _money(value) for code, value in sorted(lih_out.items())},
        lih_entries=int(lih_entries_count or 0), lih_lines=int(lih_lines_count or 0),
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
    OTHER_EXPENSE_RATE_SOURCE: "Other expense (entered rate)",
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

    All four line tables share the same factor columns, so a UNION ALL keeps one
    column-wise shape for every cut of the ledger (day, section, activity, party).
    Other-expense lines appear under the "Other Expenses" group, which has no AFE
    allowance, so their planned amount stays empty in every reconciliation cut.
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
            _service_group_column(model).label("service_group"),
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


def _service_group_column(model: type[Any]) -> Any:
    """Reporting group where the line stores one; blank for non-service costs."""
    return model.service_group_snapshot if model is DailyCostServiceLine else literal("")


def _item_columns(model: type[Any], name: bool = False) -> Any:
    if model is DailyCostServiceLine:
        return model.service_name_snapshot if name else model.service_code_snapshot
    if model is DailyCostConsumableLine:
        return model.item_name_snapshot if name else model.item_code_snapshot
    if model is DailyCostOtherExpenseLine:
        # The expense type is what an analyst groups an unexpected charge by.
        return model.expense_type_label if name else model.expense_type
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


def well_cost_report(
    db: Session, organization_id: str, well_id: str, *,
    date_from: date | None = None, date_to: date | None = None, include_draft: bool = True,
) -> list[DailyCostDayOut]:
    """Return every persisted section, including empty sheets, in date order."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    well = db.scalar(select(Well).where(
        Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False),
    ))
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    query = select(DailyCostEntry.id).where(
        DailyCostEntry.organization_id == organization_id, DailyCostEntry.well_id == well_id,
        DailyCostEntry.is_deleted.is_(False), DailyCostEntry.cost_date <= (date_to or date.today()),
    )
    if date_from:
        query = query.where(DailyCostEntry.cost_date >= date_from)
    if not include_draft:
        query = query.where(DailyCostEntry.status == "submitted")
    entry_ids = db.scalars(query.order_by(DailyCostEntry.cost_date, DailyCostEntry.afe_id, DailyCostEntry.id)).all()
    # One shared cache: the whole register reads the same milestones and plan days.
    progress_cache: dict = {}
    return [get_day(db, organization_id, entry_id, progress_cache=progress_cache) for entry_id in entry_ids]


def _effective_sow_map(db: Session, organization_id: str, afe_ids: list[str]) -> dict[str, Any]:
    """Latest approved SOW adjustment per AFE, keyed by AFE id.

    Queried directly (not via the sow_adjustment service) to avoid a service
    import cycle. Missing tables on an unmigrated database mean no
    adjustments exist yet.
    """
    if not afe_ids:
        return {}
    try:
        from app.models.sow_adjustment import AfeSowAdjustment

        rows = list(
            db.scalars(
                select(AfeSowAdjustment)
                .where(
                    AfeSowAdjustment.organization_id == organization_id,
                    AfeSowAdjustment.afe_id.in_(afe_ids),
                    AfeSowAdjustment.status == "approved",
                )
                .order_by(AfeSowAdjustment.afe_id, AfeSowAdjustment.revision_number.desc())
            ).all()
        )
    except Exception:  # noqa: BLE001 - unmigrated database has no adjustment tables yet
        return {}
    effective: dict[str, Any] = {}
    for row in rows:
        effective.setdefault(row.afe_id, row)
    return effective


def _effective_plan_map_for_well(db: Session, organization_id: str, well_id: str) -> dict[str, Any]:
    """Latest approved plan adjustment per configuration scope for one well."""
    try:
        from app.models.sow_adjustment import WellPlanAdjustment

        rows = list(
            db.scalars(
                select(WellPlanAdjustment)
                .where(
                    WellPlanAdjustment.organization_id == organization_id,
                    WellPlanAdjustment.well_id == well_id,
                    WellPlanAdjustment.status == "approved",
                )
                .order_by(WellPlanAdjustment.configuration_scope, WellPlanAdjustment.revision_number.desc())
            ).all()
        )
    except Exception:  # noqa: BLE001 - unmigrated database has no adjustment tables yet
        return {}
    effective: dict[str, Any] = {}
    for row in rows:
        effective.setdefault(row.configuration_scope, row)
    return effective


# ---------------------------------------------------------------------------
# Well progress milestones: Well Spud Date & Time → Progress Completed Date & Time
# ---------------------------------------------------------------------------
# The daily cost register counts actual days from the spud instant — not from
# the first recorded sheet — to the end of the report date, in fractional days
# (spudded 19/10 10:00 hrs, the 19/10 report counts 0.583 days). Once the
# Progress Completed Date & Time is entered it is the final instant of that
# whole progress (drilling operations completion for a drilling well,
# completion operations completion for a completion well): the count stops and
# the difference against the planned days is frozen.

PROGRESS_SCOPES: tuple[str, ...] = ("drilling", "completion")
PROGRESS_SCOPE_LABELS = {"drilling": "Drilling", "completion": "Completion"}
PROGRESS_COMPLETED_LABELS = {
    "drilling": "Drilling operations completion date & time",
    "completion": "Completion operations completion date & time",
}
PROGRESS_DAY_QUANT = Decimal("0.001")
PROGRESS_DATE_FORMAT = "%Y-%m-%d %H:%M"
_SECONDS_PER_DAY = Decimal(86400)


def _fractional_days(delta: timedelta) -> Decimal:
    """Elapsed days at three decimals, half up: 14 hours → 0.583 days."""
    return (Decimal(delta.total_seconds()) / _SECONDS_PER_DAY).quantize(
        PROGRESS_DAY_QUANT, rounding=ROUND_HALF_UP
    )


def _progress_datetime_text(value: datetime | None) -> str:
    return value.strftime(PROGRESS_DATE_FORMAT) if value else "—"


def _progress_now() -> datetime:
    """Naive UTC now, comparable with the naive site-entered milestone values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _reject_future_milestone(value: datetime, label: str) -> None:
    if value > _progress_now() + timedelta(days=1):
        raise HTTPException(
            status_code=422,
            detail=f"The {label} cannot be in the future. Enter the date & time the operation actually happened.",
        )


def _progress_planned_days(
    db: Session, organization_id: str, well: Well, scope: str, cache: dict | None = None,
) -> Decimal:
    """Planned days of one scope: an approved plan adjustment replaces the configured phase days."""
    if cache is not None and ("planned", well.id, scope) in cache:
        return cache[("planned", well.id, scope)]
    plan_map = (cache or {}).get(("plan_map", well.id))
    if plan_map is None:
        plan_map = _effective_plan_map_for_well(db, organization_id, well.id)
        if cache is not None:
            cache[("plan_map", well.id)] = plan_map
    adjustment = plan_map.get(scope)
    if adjustment is not None:
        days = _rate(Decimal(adjustment.planned_days_after))
    else:
        days = _rate(sum(
            (Decimal(phase.days) for section in well.sections_for_scope(scope) for phase in section.phases),
            Decimal("0"),
        ))
    if cache is not None:
        cache[("planned", well.id, scope)] = days
    return days


def _well_progress_row(
    db: Session, organization_id: str, well: Well, scope: str, *, as_of: date | None, cache: dict | None = None,
) -> DailyCostWellProgress:
    """One scope's milestones counted to its last cost sheet (or exact completion)."""
    spud: datetime | None = getattr(well, f"{scope}_spud_at")
    completed: datetime | None = getattr(well, f"{scope}_progress_completed_at")
    milestone_label: str = getattr(well, f"{scope}_milestone_label", "") or ""
    planned_days = _progress_planned_days(db, organization_id, well, scope, cache)
    actual_days: Decimal | None = None
    days_variance: Decimal | None = None
    if spud is not None and (completed is not None or as_of is not None):
        # Completion freezes the count at its exact time. While progress is open,
        # the latest cost sheet date is inclusive, so count through its end.
        if completed is not None:
            end = completed
        else:
            assert as_of is not None
            end = datetime.combine(as_of + timedelta(days=1), dt_time.min)
        actual_days = _fractional_days(end - spud) if end > spud else Decimal("0.000")
        days_variance = (actual_days - planned_days).quantize(PROGRESS_DAY_QUANT, rounding=ROUND_HALF_UP)
    return DailyCostWellProgress(
        scope=scope,  # type: ignore[arg-type]
        scope_label=PROGRESS_SCOPE_LABELS[scope],
        progress_label=PROGRESS_COMPLETED_LABELS[scope],
        spud_at=spud,
        progress_completed_at=completed,
        milestone_label=milestone_label,
        is_completed=completed is not None,
        planned_days=planned_days,
        actual_days=actual_days,
        days_variance=days_variance,
        as_of_date=as_of,
    )


def _entry_progress_row(db: Session, entry: DailyCostEntry, cache: dict | None = None) -> DailyCostWellProgress | None:
    """The sheet's progress row: its AFE scope, counted to the sheet's cost date."""
    well = entry.well
    if well is None:
        return None
    scope = entry.afe.configuration_scope if entry.afe else "drilling"
    return _well_progress_row(db, entry.organization_id, well, scope, as_of=entry.cost_date, cache=cache)


def _latest_cost_dates_by_scope(
    db: Session, organization_id: str, well_id: str,
) -> dict[str, date]:
    """Latest active daily-sheet date for each AFE configuration scope."""
    return {
        str(scope or "drilling"): last_date
        for scope, last_date in db.execute(
            select(Afe.configuration_scope, func.max(DailyCostEntry.cost_date))
            .join(Afe, Afe.id == DailyCostEntry.afe_id)
            .where(
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.well_id == well_id,
                DailyCostEntry.is_deleted.is_(False),
                Afe.organization_id == organization_id,
            )
            .group_by(Afe.configuration_scope)
        ).all()
        if last_date is not None
    }


def _progress_report_for_well(
    db: Session, organization_id: str, well: Well, *, as_of: date | None = None, cache: dict | None = None,
) -> DailyCostWellProgressReport:
    cache = cache if cache is not None else {}
    as_of_by_scope = ({scope: as_of for scope in PROGRESS_SCOPES}
                      if as_of is not None else _latest_cost_dates_by_scope(db, organization_id, well.id))
    return DailyCostWellProgressReport(
        well_id=well.id, well_code=well.well_code, well_name=well.well_name,
        scopes=[
            _well_progress_row(db, organization_id, well, scope, as_of=as_of_by_scope.get(scope), cache=cache)
            for scope in PROGRESS_SCOPES
        ],
    )


def well_progress_report(
    db: Session, organization_id: str, well_id: str, *, as_of: date | None = None,
) -> DailyCostWellProgressReport:
    """Milestones and day counts for both progresses of one well."""
    well = db.scalar(select(Well).where(
        Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False),
    ))
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    return _progress_report_for_well(db, organization_id, well, as_of=as_of)


def update_well_progress(
    db: Session, organization_id: str, well_id: str, data: DailyCostWellProgressUpdate,
    user: User, request: Request | None, *, as_of: date | None = None,
) -> DailyCostWellProgressReport:
    """Enter or edit the register's milestones; the spud date can only be edited, never cleared."""
    try:
        with _WRITE_LOCK:
            well = db.scalar(select(Well).where(
                Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False),
            ))
            if well is None:
                raise HTTPException(status_code=404, detail="Well not found in this workspace")
            _lock_row_id(db, Well, Well.id == well.id, Well.organization_id == organization_id)
            attr_spud = f"{data.scope}_spud_at"
            attr_completed = f"{data.scope}_progress_completed_at"
            attr_label = f"{data.scope}_milestone_label"
            scope_label = PROGRESS_SCOPE_LABELS[data.scope]
            current_spud: datetime | None = getattr(well, attr_spud)
            current_completed: datetime | None = getattr(well, attr_completed)
            current_label: str = getattr(well, attr_label, "") or ""
            fields_set = data.model_fields_set

            new_spud = current_spud
            spud_changed = False
            if "spud_at" in fields_set:
                if data.spud_at is None:
                    raise HTTPException(
                        status_code=422,
                        detail="The Well Spud Date & Time cannot be cleared once entered. Edit it instead — "
                               "the actual days recalculate from the edited date & time.",
                    )
                _reject_future_milestone(data.spud_at, "Well Spud Date & Time")
                new_spud = data.spud_at.replace(second=0, microsecond=0)
                spud_changed = new_spud != current_spud
            elif current_spud is None and data.progress_completed_at is not None:
                # The label can be saved before the spud date; a completion
                # instant cannot, because there would be nothing to count from.
                raise HTTPException(
                    status_code=422,
                    detail="Enter the Well Spud Date & Time first — actual days count from the spud instant, "
                           "not from the first daily cost sheet.",
                )

            new_completed = current_completed
            completed_changed = False
            if "progress_completed_at" in fields_set:
                new_completed = data.progress_completed_at
                completed_changed = new_completed != current_completed
                if new_completed is not None:
                    _reject_future_milestone(new_completed, "Progress Completed Date & Time")
            if new_spud is None and new_completed is not None:
                raise HTTPException(
                    status_code=422,
                    detail="Enter the Well Spud Date & Time before the Progress Completed Date & Time; "
                           "actual days count from the spud instant.",
                )
            if new_spud is not None and new_completed is not None and new_completed < new_spud:
                raise HTTPException(
                    status_code=422,
                    detail="The Progress Completed Date & Time cannot be before the Well Spud Date & Time.",
                )

            # The printed report wording is saved once here, so it never has to
            # be retyped for every print. Blank restores the default wording.
            new_label = current_label
            label_changed = False
            if data.milestone_label is not None:
                new_label = data.milestone_label.strip()[:80]
                label_changed = new_label != current_label

            if not spud_changed and not completed_changed and not label_changed:
                return _progress_report_for_well(db, organization_id, well, as_of=as_of)

            setattr(well, attr_spud, new_spud)
            setattr(well, attr_completed, new_completed)
            setattr(well, attr_label, new_label)
            db.flush()

            label = f"{well.well_code} · {scope_label.lower()} progress"
            if spud_changed and current_spud is None:
                summary = (f"Set the Well Spud Date & Time for {well.well_code} ({scope_label.lower()}) to "
                           f"{_progress_datetime_text(new_spud)}; actual days now count from the spud instant")
            elif spud_changed:
                summary = (f"Edited the Well Spud Date & Time for {well.well_code} ({scope_label.lower()}) from "
                           f"{_progress_datetime_text(current_spud)} to {_progress_datetime_text(new_spud)}; "
                           "actual days recalculated from the edited date & time")
            elif completed_changed and new_completed is not None:
                last_cost_date = _latest_cost_dates_by_scope(db, organization_id, well.id).get(data.scope)
                row = _well_progress_row(db, organization_id, well, data.scope, as_of=last_cost_date)
                summary = (f"Set the {PROGRESS_COMPLETED_LABELS[data.scope]} for {well.well_code} to "
                           f"{_progress_datetime_text(new_completed)}; the day count stopped at "
                           f"{row.actual_days} actual days against {row.planned_days} planned days "
                           f"(difference {row.days_variance})")
            elif completed_changed:
                summary = (f"Removed the {PROGRESS_COMPLETED_LABELS[data.scope]} for {well.well_code}; "
                           "the day count resumed from the spud instant")
            else:
                summary = (f"Set the {scope_label.lower()} milestone label printed on the daily cost report for "
                           f"{well.well_code} to \"{new_label or 'Spud date & time'}\"; the milestone date & time is unchanged")
            if label_changed and (spud_changed or completed_changed):
                summary += f"; printed milestone label is \"{new_label or 'Spud date & time'}\""
            _audit(
                db, user=user, action="update", entity_type="well_progress", entity_id=well.id,
                label=label, summary=summary, request=request,
            )
            report = _progress_report_for_well(db, organization_id, well, as_of=as_of)
            _commit(db)
            return report
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise _database_http_error(error, operation="saving the well progress milestones") from error


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
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
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
        and (include_draft or row.status == "submitted")
    ]
    baseline_ids = {row.baseline_id for row in entries}
    baselines = list(db.scalars(
        select(DailyCostBaseline).options(
            selectinload(DailyCostBaseline.budget_lines), selectinload(DailyCostBaseline.well_sections)
        ).where(DailyCostBaseline.organization_id == organization_id, DailyCostBaseline.id.in_(baseline_ids))
    ).unique().all()) if baseline_ids else []
    currencies = {row.standard_currency for row in baselines} | {row.standard_currency for row in entries}
    if len(currencies) > 1:
        raise HTTPException(status_code=409, detail=(
            "This well has AFEs in different standard currencies. Combined totals are not valid. "
            "Open individual daily sheets or print the well costing sheet for separate AFE/currency totals."
        ))
    currency = next(iter(currencies), "")

    afe_options: list[DailyCostAfeOption] = []
    for afe in sorted({row.afe_id: row.afe for row in entries}.values(), key=lambda row: row.afe_code):
        entry_rows = [row for row in entries if row.afe_id == afe.id]
        planned_total = sum(
            (Decimal(baseline.total_amount) for baseline in baselines if baseline.afe_id == afe.id), Decimal("0")
        )
        afe_options.append(DailyCostAfeOption(
            id=afe.id, well_id=afe.well_id, afe_code=afe.afe_code, afe_name=afe.afe_name,
            afe_type=afe.afe_type, status=afe.status, configuration_scope=afe.configuration_scope,
            standard_currency=entry_rows[0].standard_currency if entry_rows else currency,
            total_cost=planned_total, estimate_saved_at=afe.estimate_saved_at,
            display_name=f"{afe.afe_code} — {afe.afe_name} · {entry_rows[0].standard_currency if entry_rows else currency} {planned_total:,.2f}",
        ))

    # ---- SOW adjustments ----------------------------------------------------
    # The locked baselines above stay the original plan. Approved adjustments
    # revise the plan alongside them; only currency-matching adjustments apply.
    sow_map = _effective_sow_map(db, organization_id, [option.id for option in afe_options])
    plan_map = _effective_plan_map_for_well(db, organization_id, well_id)
    afe_scope = {row.afe_id: (row.afe.configuration_scope if row.afe else "drilling") for row in entries}
    adjusted_by_afe: dict[str, Decimal] = {}
    for option in afe_options:
        adjustment = sow_map.get(option.id)
        if adjustment is not None and str(adjustment.standard_currency) == option.standard_currency:
            adjusted_by_afe[option.id] = _money(Decimal(adjustment.adjusted_total))

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
    other_expenses = totals_by_group.get("Other Expenses", Decimal("0"))
    # ---- LIH Cost Register ---------------------------------------------------
    # The manual LIH register is read as its own block. Only entries recorded in
    # this well's comparison currency are added, so unlike currencies are never
    # summed; anything left out is reported as a warning.
    lih_by_currency = lih_cost_service.lih_totals_by_currency(
        db, organization_id, well_id, date_from=date_from, date_to=date_to,
    )
    lih_total, lih_lines, lih_entries = lih_cost_service.lih_totals_for_well(
        db, organization_id, well_id, date_from=date_from, date_to=date_to, currency=currency,
    )
    lih_by_afe = lih_cost_service.lih_totals_by_afe(
        db, organization_id, well_id, date_from=date_from, date_to=date_to, currency=currency,
    )
    lih_by_day = lih_cost_service.lih_totals_by_day(
        db, organization_id, well_id, date_from=date_from, date_to=date_to, currency=currency,
    )
    lih_excluded = {
        code or "Currency not specified": _money(amount)
        for code, amount in lih_by_currency.items() if code != currency and amount
    }
    # Services split by the activity classification of each daily line. The cost
    # report prints actual under Planned, UPA and NPT beside the whole group.
    classification_by_group: dict[tuple[str, str], Decimal] = {}
    for row in db.execute(
        select(lines.c.cost_group, lines.c.classification, func.sum(lines.c.standard_amount))
        .select_from(lines).group_by(lines.c.cost_group, lines.c.classification)
    ).all():
        classification_by_group[(str(row[0] or ""), str(row[1] or ""))] = Decimal(row[2] or 0)
    services_actual_planned = classification_by_group.get(("Services", "Planned"), Decimal("0"))
    services_actual_upa = classification_by_group.get(("Services", "UPA"), Decimal("0"))
    services_actual_npt = classification_by_group.get(("Services", "NPT"), Decimal("0"))
    # Other expenses have no planned counterpart, so they only ever widen the gap
    # between the AFE total and what has actually been spent.
    actual_total = _money(services + consumables + tangibles + other_expenses)
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

    # Other expenses start at zero rather than being absent, so the cost-group cut
    # shows an explicit "nothing was budgeted, this was deducted" balance.
    planned_by_group: dict[str, Decimal] = {"Other Expenses": Decimal("0")}
    planned_days = Decimal("0")
    for baseline in baselines:
        planned_by_group["Services"] = planned_by_group.get("Services", Decimal("0")) + Decimal(baseline.services_total)
        planned_by_group["Consumables"] = planned_by_group.get("Consumables", Decimal("0")) + Decimal(baseline.consumables_total)
        planned_by_group["Tangibles"] = planned_by_group.get("Tangibles", Decimal("0")) + Decimal(baseline.tangibles_total)
        planned_days += sum((Decimal(section.total_days) for section in baseline.well_sections), Decimal("0"))
    planned_total = _money(sum(planned_by_group.values(), Decimal("0")))

    # Revised plan: per-AFE adjusted totals replace the locked baseline totals
    # for AFEs with an approved, currency-matching adjustment.
    adjusted_planned: Decimal | None = None
    if adjusted_by_afe:
        adjusted_total = Decimal("0")
        for baseline in baselines:
            if baseline.afe_id in adjusted_by_afe:
                adjusted_total += adjusted_by_afe[baseline.afe_id]
            else:
                adjusted_total += Decimal(baseline.total_amount)
        adjusted_planned = _money(adjusted_total)

    # Revised planned days: per-scope adjusted totals replace the locked
    # baseline days for scopes with an approved plan adjustment.
    planned_days_by_scope: dict[str, Decimal] = {}
    for baseline in baselines:
        scope = afe_scope.get(baseline.afe_id, "drilling")
        planned_days_by_scope[scope] = planned_days_by_scope.get(scope, Decimal("0")) + sum(
            (Decimal(section.total_days) for section in baseline.well_sections), Decimal("0")
        )
    adjusted_planned_days: Decimal | None = None
    if any(scope in plan_map for scope in planned_days_by_scope):
        adjusted_days = Decimal("0")
        for scope, days in planned_days_by_scope.items():
            if scope in plan_map:
                adjusted_days += Decimal(plan_map[scope].planned_days_after)
            else:
                adjusted_days += days
        adjusted_planned_days = _rate(adjusted_days)

    # ---- mud chemicals reconciliation ---------------------------------------
    # Mud Cost Analysis reconciles each section independently. The final AFE
    # comparison uses the reconciled mud chemicals amount, while the recorded
    # actual stays available here and in the daily ledger. Sections that cannot
    # be reconciled keep their actual cost so nothing is silently dropped.
    mud_window_to = date_to or (max((row.cost_date for row in windowed), default=date.today()))
    mud_statement = select(
        func.coalesce(func.sum(DailyCostConsumableLine.standard_amount), 0)
    ).join(
        DailyCostEntry, DailyCostEntry.id == DailyCostConsumableLine.entry_id,
    ).where(
        DailyCostConsumableLine.organization_id == organization_id,
        DailyCostEntry.organization_id == organization_id,
        DailyCostEntry.well_id == well_id,
        DailyCostEntry.is_deleted.is_(False),
        DailyCostConsumableLine.category == "Mud Chemicals",
        DailyCostEntry.cost_date <= mud_window_to,
    )
    if date_from is not None:
        mud_statement = mud_statement.where(DailyCostEntry.cost_date >= date_from)
    if not include_draft:
        mud_statement = mud_statement.where(DailyCostEntry.status == "submitted")
    actual_mud_chemicals = _money(Decimal(db.scalar(mud_statement) or 0))
    mud_warnings: list[DailyCostWarnings] = []
    mud_reconciliation: DailyCostMudReconciliation | None = None
    comparison_mud_cost = actual_mud_chemicals
    reconciled_mud_cost = Decimal("0.00")
    if entries:
        try:
            reconciliation = mud_cost_service.reconcile_well(
                db, organization_id, well,
                date_from=date_from, date_to=mud_window_to, include_draft=include_draft,
            )
        except HTTPException as error:
            mud_warnings.append(DailyCostWarnings(
                code="mud-reconciliation-unavailable", severity="warning",
                message=f"Mud cost reconciliation is unavailable: {error.detail}",
            ))
            reconciliation = None
        if reconciliation is not None:
            covered_actual = sum(
                (row.actual_cost for row in reconciliation.sections
                 if row.reconciled_cost is not None),
                Decimal("0"),
            )
            reconciled_mud_cost = _money(sum(
                (row.reconciled_cost for row in reconciliation.sections
                 if row.reconciled_cost is not None),
                Decimal("0"),
            ))
            unreconciled_actual = _money(max(actual_mud_chemicals - covered_actual, Decimal("0")))
            comparison_mud_cost = _money(reconciled_mud_cost + unreconciled_actual)
            notes: list[str] = []
            if any(row.reconciled_cost is not None for row in reconciliation.sections):
                notes.append("The final comparison uses the reconciled mud chemicals cost; the recorded actual remains visible.")
            if reconciliation.unconfigured_section_count:
                notes.append(
                    f"{reconciliation.unconfigured_section_count} section(s) have no mud configuration and remain at actual cost."
                )
            mud_reconciliation = DailyCostMudReconciliation(
                available=bool(reconciliation.sections) and any(
                    row.reconciled_cost is not None for row in reconciliation.sections
                ),
                currency=currency,
                actual_cost=actual_mud_chemicals,
                reconciled_cost=reconciled_mud_cost,
                unreconciled_actual_cost=unreconciled_actual,
                comparison_cost=comparison_mud_cost,
                adjustment=_money(comparison_mud_cost - actual_mud_chemicals),
                latest_cost_per_bbl=reconciliation.latest_cost_per_bbl,
                latest_cost_per_bbl_section=reconciliation.latest_cost_per_bbl_section,
                latest_cost_per_bbl_date=reconciliation.latest_cost_per_bbl_date,
                configured_section_count=reconciliation.configured_section_count,
                unconfigured_section_count=reconciliation.unconfigured_section_count,
                sections=[
                    DailyCostMudSectionReconciliation(
                        section_id=row.section_id,
                        section_label=row.section_label,
                        mud_type=row.mud_type,
                        mud_type_label=row.mud_type_label,
                        is_configured=row.is_configured,
                        is_wbm=row.is_wbm,
                        currency=row.currency,
                        base_rate=row.base_rate,
                        actual_cost=row.actual_cost,
                        reconciled_cost=row.reconciled_cost,
                        cost_per_bbl=row.cost_per_bbl,
                        consumption_losses=row.consumption_losses,
                        adjustment=row.adjustment,
                        remarks=row.remarks,
                    )
                    for row in reconciliation.sections
                ],
                note=" ".join(notes) or (
                    "No section has both a mud type and reconcilable quantities; the comparison keeps actual mud cost."
                ),
            )
            if reconciliation.unconfigured_section_count:
                mud_warnings.append(DailyCostWarnings(
                    code="mud-sections-unconfigured", severity="info",
                    message=(
                        f"{reconciliation.unconfigured_section_count} mud section(s) have no mud type configured. "
                        "Their mud chemicals remain at the recorded actual cost in the comparison."
                    ),
                ))
            if mud_reconciliation.available and mud_reconciliation.adjustment != 0:
                mud_warnings.append(DailyCostWarnings(
                    code="mud-cost-reconciled", severity="info",
                    message=(
                        f"Mud chemicals compare at {currency} {comparison_mud_cost:,.2f} reconciled "
                        f"(recorded actual {currency} {actual_mud_chemicals:,.2f}; "
                        f"adjustment {currency} {mud_reconciliation.adjustment:,.2f})."
                    ),
                ))
    comparison_actual = _money(actual_total - actual_mud_chemicals + comparison_mud_cost)
    comparison_consumables = _money(consumables - actual_mud_chemicals + comparison_mud_cost)
    # LIH is added to the actual cost and deducted from the AFE amount explicitly.
    actual_including_lih = _money(actual_total + lih_total)
    comparison_actual_including_lih = _money(comparison_actual + lih_total)
    comparison_balance = _money(planned_total - comparison_actual)
    comparison_balance_including_lih = _money(planned_total - lih_total - comparison_actual)
    comparison_used = (
        (comparison_actual / planned_total * Decimal("100")).quantize(Decimal("0.01"))
        if planned_total > 0 else Decimal("0.00")
    )
    comparison_used_including_lih = (
        (comparison_actual_including_lih / planned_total * Decimal("100")).quantize(Decimal("0.01"))
        if planned_total > 0 else Decimal("0.00")
    )
    comparison_adjusted_balance = (
        _money(adjusted_planned - comparison_actual) if adjusted_planned is not None else None
    )
    comparison_adjusted_balance_including_lih = (
        _money(adjusted_planned - lih_total - comparison_actual) if adjusted_planned is not None else None
    )

    # ---- daily run sheet -----------------------------------------------------
    per_day: dict[date, dict[str, Any]] = {}
    for row in db.execute(
        select(lines.c.cost_date, lines.c.cost_group, func.sum(lines.c.standard_amount))
        .select_from(lines).group_by(lines.c.cost_date, lines.c.cost_group).order_by(lines.c.cost_date)
    ).all():
        day = per_day.setdefault(row[0], {
            "Services": Decimal("0"), "Consumables": Decimal("0"), "Tangibles": Decimal("0"),
            "Other Expenses": Decimal("0"),
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
            "Other Expenses": Decimal("0"),
            "UPA": Decimal("0"), "NPT": Decimal("0"), "usd_total": Decimal("0"), "sheets": set(), "statuses": set(),
        })
        day["usd_total"] = Decimal(day.get("usd_total", Decimal("0"))) + Decimal(entry.total_cost_usd)
        day["sheets"].add(entry.id)
        day["statuses"].add(entry.status)
    _, summary_day_depths, _ = resolve_actual_depths(
        db,
        organization_id,
        well_ids=[well_id],
        date_from=date_from,
        date_to=date_to,
    )
    cumulative = Decimal("0")
    cumulative_usd = Decimal("0")
    cumulative_lih = Decimal("0")
    daily: list[DailyCostDailyRow] = []
    for day_date in sorted(per_day):
        values = per_day[day_date]
        total = _money(
            values["Services"] + values["Consumables"] + values["Tangibles"] + values["Other Expenses"]
        )
        day_usd = _money(Decimal(values.get("usd_total", Decimal("0"))))
        cumulative = _money(cumulative + total)
        cumulative_usd = _money(cumulative_usd + day_usd)
        day_lih = lih_by_day.get(day_date, Decimal("0.00"))
        cumulative_lih = _money(cumulative_lih + day_lih)
        statuses = values["statuses"]
        day_depth = summary_day_depths.get((well_id, day_date))
        daily.append(DailyCostDailyRow(
            cost_date=day_date,
            services=_money(values["Services"]), consumables=_money(values["Consumables"]),
            tangibles=_money(values["Tangibles"]), other_expenses=_money(values["Other Expenses"]),
            total=total,
            upa=_money(values["UPA"]), npt=_money(values["NPT"]), cumulative=cumulative,
            budget_balance=_money(planned_total - cumulative),
            lih=day_lih,
            cumulative_including_lih=_money(cumulative + cumulative_lih),
            budget_balance_including_lih=_money(planned_total - cumulative - cumulative_lih),
            sheets=len(values["sheets"]),
            status=("submitted" if statuses == {"submitted"} else "draft" if statuses == {"draft"} else "mixed"),
            adjusted_budget_balance=_money(adjusted_planned - cumulative) if adjusted_planned is not None else None,
            actual_depth=day_depth.actual_depth if day_depth is not None else None,
            total_usd=day_usd,
            cumulative_usd=cumulative_usd,
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
        # total_cost already contains the other expenses, so the balance below is the
        # AFE total net of those deductions; the split is reported alongside it.
        other_for_afe = _money(sum((Decimal(row.other_expenses_total) for row in entry_rows), Decimal("0")))
        lih_for_afe = lih_by_afe.get(option.id, Decimal("0.00"))
        days_recorded = sorted({row.cost_date for row in entry_rows})
        adjusted_for_afe = adjusted_by_afe.get(option.id)
        positions.append(DailyCostAfePosition(
            afe_id=option.id, afe_code=option.afe_code, afe_name=option.afe_name,
            afe_status=option.status, currency=option.standard_currency,
            planned_total=_money(planned), actual=actual, other_expenses=other_for_afe,
            lih_cost=lih_for_afe,
            actual_including_lih=_money(actual + lih_for_afe),
            afe_available=_money(planned - lih_for_afe),
            balance=_money(planned - actual),
            balance_including_lih=_money(planned - lih_for_afe - actual),
            over_budget=actual + lih_for_afe > planned, sheets=len(entry_rows), days_recorded=len(days_recorded),
            first_day=days_recorded[0] if days_recorded else None,
            last_day=days_recorded[-1] if days_recorded else None,
            adjusted_planned_total=adjusted_for_afe,
            adjusted_balance=(
                _money(adjusted_for_afe - lih_for_afe - actual) if adjusted_for_afe is not None else None
            ),
            has_adjustment=adjusted_for_afe is not None,
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

    # LIH cost has no activity, section or phase, so it is only added to the
    # cost-group cut. It is shown as its own group with no AFE allowance.
    if lih_total:
        cost_group_factor = next((group for group in factors if group.dimension == "cost_group"), None)
        if cost_group_factor is not None:
            factor_base = _money(actual_total + lih_total)
            cost_group_factor.total = factor_base
            cost_group_factor.rows.append(DailyCostFactorRow(
                key="lih",
                code="LIH",
                name="LIH Cost Register",
                detail="No AFE allowance · deducted from the AFE total",
                amount=lih_total,
                planned=Decimal("0.00"),
                balance=_money(-lih_total),
                share=(
                    (lih_total / factor_base * Decimal("100")).quantize(Decimal("0.01"))
                    if factor_base > 0 else Decimal("0.00")
                ),
                quantity=Decimal(lih_lines),
            ))
            cost_group_factor.rows.sort(key=lambda row: (-row.amount, row.code))

    # ---- budget reconciliation ----------------------------------------------
    budget_rows = db.execute(
        select(
            lines.c.budget_key, lines.c.cost_group, func.sum(lines.c.standard_amount),
            func.sum(case((lines.c.classification == "Planned", lines.c.standard_amount), else_=Decimal("0"))),
            func.sum(case((lines.c.classification == "UPA", lines.c.standard_amount), else_=Decimal("0"))),
            func.sum(case((lines.c.classification == "NPT", lines.c.standard_amount), else_=Decimal("0"))),
        )
        .select_from(lines).group_by(lines.c.budget_key, lines.c.cost_group)
    ).all()
    actual_by_key = {str(row[0] or ""): Decimal(row[2] or 0) for row in budget_rows}
    # Cost recorded on the last report day, split out of the cumulative column so
    # the printed report shows "up to last day", "this day" and the total.
    report_day = max((row.cost_date for row in windowed), default=None)
    today_rows = db.execute(
        select(lines.c.budget_key, func.sum(lines.c.standard_amount))
        .select_from(lines)
        .where(lines.c.cost_date == report_day)
        .group_by(lines.c.budget_key)
    ).all() if report_day is not None else []
    actual_today_by_key = {str(row[0] or ""): _money(row[1] or 0) for row in today_rows}
    class_by_key = {
        str(row[0] or ""): (
            Decimal(row[3] or 0), Decimal(row[4] or 0), Decimal(row[5] or 0),
        )
        for row in budget_rows
    }
    group_by_key = {str(row[0] or ""): str(row[1] or "Services") for row in budget_rows}
    planned_by_key: dict[str, Decimal] = {}
    meta: dict[str, DailyCostBaselineBudgetLine] = {}
    for baseline in baselines:
        for budget_line in baseline.budget_lines:
            key = f"{budget_line.budget_kind}:{budget_line.item_key}"
            planned_by_key[key] = planned_by_key.get(key, Decimal("0")) + Decimal(budget_line.planned_amount)
            meta.setdefault(key, budget_line)
    unplanned_names: dict[tuple[str, str], str] = {}
    unplanned_groups: dict[tuple[str, str], str] = {}
    for row in db.execute(
        select(
            lines.c.cost_group, lines.c.budget_key,
            # PostgreSQL rejects ungrouped projections (SQLite silently picks an
            # arbitrary row), so the representative activity and party labels are
            # aggregated. min() keeps the same one-label-per-budget-key shape and
            # makes the chosen label deterministic on every dialect.
            func.min(lines.c.activity_name), func.min(lines.c.party_name),
            func.min(lines.c.service_group),
        )
        .select_from(lines)
        .where(lines.c.budget_key.like("unplanned:%"))
        .group_by(lines.c.cost_group, lines.c.budget_key)
    ).all():
        unplanned_names[(str(row[0]), str(row[1]))] = f"Unbudgeted {row[0].lower()} — {row[2] or row[3] or UNASSIGNED}"
        unplanned_groups[(str(row[0]), str(row[1]))] = str(row[4] or "")
    budget_lines: list[DailyCostBudgetComparison] = []
    for key in sorted(set(planned_by_key) | set(actual_by_key), key=lambda value: -abs(actual_by_key.get(value, Decimal("0")))):
        budget_line = meta.get(key)
        if budget_line is not None:
            group = budget_line.cost_group
            code, name, kind = budget_line.item_code_snapshot, budget_line.item_name_snapshot, budget_line.budget_kind
            service_group = budget_line.service_group
        else:
            group = group_by_key.get(key, "Services")
            kind = key.split(":", 1)[0] if key else "unplanned"
            code = "" if key.startswith("unplanned:") else key.split(":", 1)[-1][:50]
            name = unplanned_names.get((str(group), key), f"Unbudgeted {str(group).lower()}")
            service_group = unplanned_groups.get((str(group), key), "")
        planned_value = planned_by_key.get(key)
        actual_value = _money(actual_by_key.get(key, Decimal("0")))
        split_planned, split_upa, split_npt = class_by_key.get(key, (Decimal("0"),) * 3)
        budget_lines.append(DailyCostBudgetComparison(
            budget_key=key, cost_group=group, budget_kind=kind, item_code=code, item_name=name,
            service_group=service_group,
            planned=_money(planned_value) if planned_value is not None else Decimal("0.00"),
            actual_to_date=actual_value,
            actual_today=actual_today_by_key.get(key, Decimal("0")),
            actual_prior=_money(actual_value - actual_today_by_key.get(key, Decimal("0"))),
            sort_order=budget_line.sort_order if budget_line is not None else 9999,
            balance=_money((planned_value or Decimal("0")) - actual_value),
            is_planned=key in planned_by_key,
            actual_planned=_money(split_planned),
            actual_upa=_money(split_upa),
            actual_npt=_money(split_npt),
        ))

    # ---- warnings and totals -------------------------------------------------
    warnings: list[DailyCostWarnings] = []
    warnings.extend(mud_warnings)
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
    if other_expenses:
        warnings.append(DailyCostWarnings(
            code="other-expenses-deducted", severity="warning",
            message=f"Other expenses (LIH, hole problems and similar) so far: {currency} {other_expenses:,.2f}. "
                    "They have no AFE allowance and are deducted from the AFE total above."))
    if lih_total:
        warnings.append(DailyCostWarnings(
            code="lih-cost-deducted", severity="warning",
            message=(
                f"LIH Cost Register: {currency} {lih_total:,.2f} across {lih_entries} day(s) and "
                f"{lih_lines} item(s) is added to the actual cost and deducted explicitly from the AFE "
                f"total. AFE available after LIH: {currency} {_money(planned_total - lih_total):,.2f}; "
                f"actual cost including LIH: {currency} {actual_including_lih:,.2f}."
            )))
    if lih_excluded:
        warnings.append(DailyCostWarnings(
            code="lih-cost-currency-excluded", severity="info",
            message=(
                "LIH cost recorded in another currency is not added to this "
                f"{currency} comparison: "
                + ", ".join(f"{code} {amount:,.2f}" for code, amount in sorted(lih_excluded.items()))
                + ". Align the register AFE with the well's standard currency."
            )))
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
    adjusted_balance = _money(adjusted_planned - actual_total) if adjusted_planned is not None else None
    adjusted_used = (
        (actual_total / adjusted_planned * Decimal("100")).quantize(Decimal("0.01"))
        if adjusted_planned is not None and adjusted_planned > 0
        else None
    )
    # Progress milestones count through the last cost sheet included in this
    # report for each scope. An entered completion timestamp overrides that date
    # inside _well_progress_row and freezes the count at the exact completion time.
    progress_cache: dict = {}
    progress_as_of: dict[str, date] = {}
    for entry in windowed:
        scope = afe_scope.get(entry.afe_id, "drilling")
        if scope not in progress_as_of or entry.cost_date > progress_as_of[scope]:
            progress_as_of[scope] = entry.cost_date
    progress_rows = [
        _well_progress_row(db, organization_id, well, scope, as_of=progress_as_of.get(scope), cache=progress_cache)
        for scope in PROGRESS_SCOPES
    ]
    spudded_rows = [row for row in progress_rows if row.actual_days is not None]
    spud_actual_days = sum((row.actual_days for row in spudded_rows), Decimal("0.000"))
    spud_days_variance = sum((row.days_variance for row in spudded_rows), Decimal("0.000"))
    totals = DailyCostWellTotals(
        currency=currency, planned=planned_total, actual=actual_total, balance=_money(remaining),
        used_percent=(actual_total / planned_total * Decimal("100")).quantize(Decimal("0.01")) if planned_total > 0 else Decimal("0.00"),
        services=_money(services), consumables=_money(consumables), tangibles=_money(tangibles),
        other_expenses=_money(other_expenses),
        services_actual_planned=_money(services_actual_planned),
        services_actual_upa=_money(services_actual_upa),
        services_actual_npt=_money(services_actual_npt),
        upa=upa, npt=npt, planned_days=_rate(planned_days), recorded_days=recorded_days,
        elapsed_days=elapsed_days, average_per_day=average, days_to_budget=days_to_budget,
        first_day=min(days) if days else None, last_day=max(days) if days else None,
        sheets=len(windowed),
        draft_sheets=sum(1 for row in windowed if row.status == "draft"),
        submitted_sheets=sum(1 for row in windowed if row.status == "submitted"),
        lines=int(db.execute(select(func.count()).select_from(lines)).scalar() or 0),
        adjusted_planned=adjusted_planned,
        adjusted_balance=adjusted_balance,
        adjusted_used_percent=adjusted_used,
        adjusted_planned_days=adjusted_planned_days,
        has_adjustment=adjusted_planned is not None or adjusted_planned_days is not None,
        spud_actual_days=spud_actual_days if spudded_rows else None,
        spud_days_variance=spud_days_variance if spudded_rows else None,
        actual_mud_chemicals=actual_mud_chemicals,
        reconciled_mud_cost=_money(reconciled_mud_cost),
        comparison_mud_cost=_money(comparison_mud_cost),
        mud_cost_adjustment=_money(comparison_mud_cost - actual_mud_chemicals),
        lih_cost=lih_total,
        lih_line_count=lih_lines,
        lih_entries=lih_entries,
        afe_available=_money(planned_total - lih_total),
        actual_including_lih=actual_including_lih,
        comparison_actual_including_lih=comparison_actual_including_lih,
        comparison_balance_including_lih=comparison_balance_including_lih,
        comparison_used_percent_including_lih=comparison_used_including_lih,
        comparison_adjusted_balance_including_lih=comparison_adjusted_balance_including_lih,
        comparison_actual=comparison_actual,
        comparison_consumables=comparison_consumables,
        comparison_balance=comparison_balance,
        comparison_used_percent=comparison_used,
        comparison_adjusted_balance=comparison_adjusted_balance,
        has_mud_reconciliation=bool(mud_reconciliation and mud_reconciliation.available),
    )
    # ---- LIH Cost Register block --------------------------------------------
    lih_day_rows: list[Any] = []
    if lih_entries:
        lih_query = select(LihCostEntry).where(
            LihCostEntry.organization_id == organization_id,
            LihCostEntry.well_id == well_id,
            LihCostEntry.is_deleted.is_(False),
            LihCostEntry.currency == currency,
        )
        if date_from is not None:
            lih_query = lih_query.where(LihCostEntry.cost_date >= date_from)
        if date_to is not None:
            lih_query = lih_query.where(LihCostEntry.cost_date <= date_to)
        lih_day_rows = list(db.scalars(lih_query.order_by(LihCostEntry.cost_date, LihCostEntry.id)).all())
    # Label every AFE that carries an LIH deduction, including one that has no
    # daily sheet yet, so the deduction always names its AFE.
    lih_afe_labels = {
        row.id: row for row in db.scalars(
            select(Afe).where(Afe.organization_id == organization_id, Afe.well_id == well_id)
        ).all()
    }
    lih_summary = DailyCostLihSummary(
        available=bool(lih_entries),
        currency=currency,
        total=lih_total,
        line_count=lih_lines,
        entry_count=lih_entries,
        deductions_by_afe=[
            DailyCostLihDeduction(
                afe_id=afe_id,
                afe_code=lih_afe_labels[afe_id].afe_code if afe_id in lih_afe_labels else "",
                afe_name=lih_afe_labels[afe_id].afe_name if afe_id in lih_afe_labels else "",
                currency=currency,
                lih_cost=amount,
                afes_total=next(
                    (position.planned_total for position in positions if position.afe_id == afe_id), Decimal("0.00")
                ),
            )
            for afe_id, amount in sorted(lih_by_afe.items())
        ],
        days=[
            DailyCostLihDay(
                entry_id=row.id,
                cost_date=row.cost_date,
                afe_id=row.afe_id,
                afe_code=row.afe_code_snapshot,
                currency=row.currency,
                line_count=row.line_count,
                total_cost=_money(row.total_cost),
            )
            for row in lih_day_rows
        ],
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
        progress=progress_rows, mud_cost=mud_reconciliation, lih_cost=lih_summary,
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



def _other_expense_type(value: Any) -> str:
    """Resolve an imported expense type to a stored code, accepting plain wording.

    Unknown labels are rejected with the accepted list, because a misfiled LIH
    charge would silently change what is deducted from the AFE total.
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(
            "Other expenses need an expense_type (" + ", ".join(OTHER_EXPENSE_TYPE_LABELS) + ")"
        )
    needle = raw.casefold()
    for code, label in OTHER_EXPENSE_TYPE_LABELS.items():
        if needle in (code.casefold(), label.casefold()):
            return code
    alias = OTHER_EXPENSE_TYPE_ALIASES.get(needle)
    if alias:
        return alias
    raise ValueError(
        f"Unknown expense type '{raw}'. Use one of: "
        + ", ".join(f"{code} ({label})" for code, label in OTHER_EXPENSE_TYPE_LABELS.items())
    )


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


def _saved_inputs(
    entry: DailyCostEntry,
) -> tuple[
    list[DailyCostServiceLineIn], list[DailyCostConsumableLineIn],
    list[DailyCostTangibleLineIn], list[DailyCostOtherExpenseLineIn],
]:
    def common(row: Any) -> dict[str, Any]:
        return {
            "id": row.id, "activity_id": row.activity_id, "hole_section_id": row.hole_section_id,
            "phase_id": row.phase_id, "sub_activity_id": row.sub_activity_id,
            "vendor_id": row.vendor_id, "party_name": row.party_name,
            "quantity": row.quantity, "currency": row.currency,
            "exchange_rate": Decimal(row.usd_exchange_rate) if (row.currency or "").upper() != "USD" else None,
            "actual_depth": Decimal(row.actual_depth_input) if row.actual_depth_input is not None else None,
            "actual_depth_unit": normalize_depth_unit(row.actual_depth_unit),
            "override_rate": row.override_rate,
            "override_reason": row.override_reason, "remarks": row.remarks,
        }
    services = [DailyCostServiceLineIn(
        **common(row), cost_items=[{"description": item.description, "amount": item.amount} for item in row.cost_items], service_id=row.service_id, baseline_service_rate_id=row.baseline_service_rate_id,
        charging_basis=row.charging_basis, charge_category=row.charge_category,
        quantity_unit=row.quantity_unit,
    ) for row in entry.service_lines]
    consumables = [DailyCostConsumableLineIn(
        **common(row), category=row.category, item_kind=row.item_kind, item_id=row.item_id,
    ) for row in entry.consumable_lines]
    tangibles = [DailyCostTangibleLineIn(
        **common(row), tangible_id=row.tangible_id,
    ) for row in entry.tangible_lines]
    # The entered unit rate of an other-expense line is stored as its captured rate.
    others = [DailyCostOtherExpenseLineIn(
        **common(row), expense_type=row.expense_type, expense_description=row.expense_description,
        quantity_unit=row.quantity_unit, unit_rate=Decimal(row.captured_rate),
    ) for row in entry.other_expense_lines]
    return services, consumables, tangibles, others


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
    entry_scope = (
        entry.afe.configuration_scope
        if entry.afe is not None and entry.afe.configuration_scope in ("drilling", "completion")
        else "drilling"
    )
    sub_activity_rows = db.scalars(select(WellSubActivity).where(
        WellSubActivity.organization_id == organization_id,
        WellSubActivity.well_id == entry.well_id,
        WellSubActivity.scope == entry_scope,
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
    other_inputs: list[DailyCostOtherExpenseLineIn] = []
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
            exchange_value = _import_value(row, "exchange_rate", "usd_exchange_rate", "usd_rate", "usd_conversion_rate", default=None)
            exchange_rate = Decimal(str(exchange_value)) if exchange_value is not None else None
            depth_value = _import_value(row, "actual_depth", "depth", "actual_depth_m", default=None)
            actual_depth = Decimal(str(depth_value)) if depth_value is not None else None
            actual_depth_unit = normalize_depth_unit(str(_import_value(row, "actual_depth_unit", "depth_unit", default="m")))
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
                "exchange_rate": exchange_rate,
                "actual_depth": actual_depth,
                "actual_depth_unit": actual_depth_unit,
                "depth_seq": index,
                "override_rate": override_rate,
                "override_reason": override_reason,
                "remarks": str(_import_value(row, "remarks", "line_remarks", default="")),
            }

            if line_type in OTHER_EXPENSE_LINE_TYPES:
                remarks = str(_import_value(row, "remarks", "line_remarks", default=""))
                expense_type = _other_expense_type(_import_value(row, "expense_type", "other_expense_type", "expense_category"))
                unit_value = _import_value(row, "unit_rate", "rate", "amount", "override_rate", default="")
                if unit_value == "":
                    raise ValueError("Other expenses need a unit_rate (the charge per unit)")
                unit = str(_import_value(row, "quantity_unit", "unit", default="unit")).strip().lower()
                if unit in ("each", "nos", "numbers", "no.", ""):
                    unit = "unit"
                if unit not in OTHER_EXPENSE_UNITS:
                    raise ValueError("For an other expense, quantity_unit must be unit, days or hours")
                other_inputs.append(DailyCostOtherExpenseLineIn(
                    **{**common, "currency": currency or entry.standard_currency, "remarks": remarks},
                    expense_type=expense_type,
                    expense_description=str(_import_value(row, "expense_description", "description", default="")),
                    quantity_unit=unit,  # type: ignore[arg-type]
                    unit_rate=Decimal(str(unit_value)),
                ))
            elif line_type in ("service", "services"):
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
                    raise ValueError("Line Type must be Service, Consumable, Tangible or Other")
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
    current_services, current_consumables, current_tangibles, current_others = _saved_inputs(entry)
    payload = DailyCostSaveIn(
        remarks=entry.remarks,
        # An import appends lines; it must not reset the report lead / lag that
        # was already saved with this sheet.
        lead_lag_kind=entry.lead_lag_kind or "",
        lead_lag_days=Decimal(entry.lead_lag_days) if entry.lead_lag_days is not None else None,
        services=[*current_services, *service_inputs],
        consumables=[*current_consumables, *consumable_inputs],
        tangibles=[*current_tangibles, *tangible_inputs],
        other_expenses=[*current_others, *other_inputs],
    )
    save_day(db, organization_id, entry.id, payload, user, request, action="import")
    return DailyCostImportResponse(
        imported_count=len(service_inputs) + len(consumable_inputs) + len(tangible_inputs) + len(other_inputs),
        error_count=0, errors=[], success=True,
    )

def record_export(db: Session, user: User, data: DailyCostExportAudit, request: Request | None) -> None:
    _audit(
        db, user=user, action="export", entity_type="daily_cost_export", entity_id=None,
        label=data.module, summary=f"Exported {data.record_count} {data.module} record(s) as {data.format.upper()}"
        + (" including deleted records" if data.include_deleted else "")
        + (f"; well {data.well_id}" if data.well_id else "")
        + (f"; daily sheet {data.entry_id}" if data.entry_id else "")
        + (f"; period {data.date_from or 'inception'} to {data.date_to or date.today()}; include drafts: {data.include_draft}"
           if data.module == "well-cost-sheet" else ""),
        request=request,
    )
    _commit(db)
