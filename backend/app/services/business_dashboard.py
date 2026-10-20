"""Business Dashboard: one read-only projection of the costing workflow.

The dashboard answers, for every rig and well, what was planned, what was
authorized and what has actually been spent:

* rig and well identity and status (Rig & Well Management);
* planned days and planned depth from the well configuration, including an
  approved plan adjustment when one exists;
* the AFE amount (the saved estimate in the AFE standard currency) and the
  latest approved SOW-adjusted amount;
* actual cost, actual days (first to last day of the cost register), NPT and
  UPA days and amounts from the classified daily cost lines;
* depth progress from the deepest configured hole section that carries
  recorded cost.

Every figure is a plain column-wise aggregation of existing tables; the
dashboard stores nothing and rewrites nothing. Amounts are only added when the
AFE/daily-sheet standard currency matches the currency selected on the
dashboard, and the response reports how many records were left out, so mixed
currencies can never be silently summed.

Authorization mirrors the source modules: a caller needs at least one of
``rig-well:read``, ``afe:read`` or ``daily-cost:read``, and each section is
returned only when its own read capability is granted.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    Afe,
    Currency,
    DailyCostEntry,
    Rig,
    User,
    Well,
    WellPlanAdjustment,
    WellSection,
)
from app.schemas.business_dashboard import (
    BusinessDashboardOut,
    DashboardActivityRow,
    DashboardAfeOption,
    DashboardAfeRow,
    DashboardAlert,
    DashboardCapabilities,
    DashboardDailyPoint,
    DashboardDaySheet,
    DashboardFilterOptions,
    DashboardKpis,
    DashboardRigOption,
    DashboardRigRow,
    DashboardSectionRow,
    DashboardSlice,
    DashboardWellDetail,
    DashboardWellOption,
    DashboardWellRow,
)
from app.services import afe as afe_service
from app.services import audit

log = logging.getLogger(__name__)

MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ACCESS_KEYS = ("rig-well:read", "afe:read", "daily-cost:read")
EXPORT_KEYS = ("rig-well:export", "afe:export", "daily-cost:export")
AFE_STATUS_LABELS = {
    "draft": "Draft",
    "submitted": "Submitted",
    "review": "In review",
    "approval": "Approved",
}
GROUP_LABELS = ("Services", "Consumables", "Tangibles", "Other Expenses")
CLASSIFICATIONS = ("Planned", "UPA", "NPT")
CLASSIFICATION_DETAIL = {
    "Planned": "Planned work",
    "UPA": "Unplanned activity",
    "NPT": "Non-productive time",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _permissions(user: User) -> set[str]:
    return {permission.key for role in user.roles for permission in role.permissions}


def _is_owner(user: User) -> bool:
    return any(role.is_owner for role in user.roles)


def capabilities(user: User) -> DashboardCapabilities:
    keys, own = _permissions(user), _is_owner(user)
    return DashboardCapabilities(
        plan=own or "rig-well:read" in keys,
        budget=own or "afe:read" in keys,
        actuals=own or "daily-cost:read" in keys,
    )


def access_allowed(user: User) -> bool:
    """Any source module read capability opens the dashboard."""
    keys, own = _permissions(user), _is_owner(user)
    return own or bool(keys & set(ACCESS_KEYS))


def export_allowed(user: User) -> bool:
    keys, own = _permissions(user), _is_owner(user)
    return own or bool(keys & set(EXPORT_KEYS))


def _money(value: Decimal | int | str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _percent(part: Decimal, whole: Decimal) -> Decimal | None:
    if whole == 0:
        return None
    return (part / whole * Decimal("100")).quantize(PERCENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Loading the workspace state
# ---------------------------------------------------------------------------


def _load_wells(db: Session, organization_id: str) -> list[Well]:
    rows = db.scalars(
        select(Well)
        .options(
            joinedload(Well.rig),
            selectinload(Well.sections).selectinload(WellSection.phases),
            selectinload(Well.completion_sections).selectinload(WellSection.phases),
        )
        .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
        .order_by(Well.well_code)
    ).unique().all()
    # A well whose rig was removed is not an operating record any more.
    return [well for well in rows if well.rig is not None and not well.rig.is_deleted]


def _default_currency(db: Session, organization_id: str) -> str:
    code = db.scalar(
        select(Currency.currency_code).where(
            Currency.organization_id == organization_id,
            Currency.is_deleted.is_(False),
            Currency.is_default.is_(True),
        )
    )
    return str(code or "")


def _plan_map(
    db: Session, organization_id: str, well_ids: Sequence[str]
) -> dict[tuple[str, str], Any]:
    """Latest approved plan adjustment per (well, configuration scope)."""
    if not well_ids:
        return {}
    try:
        rows = list(
            db.scalars(
                select(WellPlanAdjustment)
                .where(
                    WellPlanAdjustment.organization_id == organization_id,
                    WellPlanAdjustment.well_id.in_(list(well_ids)),
                    WellPlanAdjustment.status == "approved",
                )
                .order_by(
                    WellPlanAdjustment.well_id,
                    WellPlanAdjustment.configuration_scope,
                    WellPlanAdjustment.revision_number.desc(),
                )
            ).all()
        )
    except Exception:  # noqa: BLE001 - an unmigrated database has no adjustment tables yet
        return {}
    effective: dict[tuple[str, str], Any] = {}
    for row in rows:
        effective.setdefault((row.well_id, row.configuration_scope), row)
    return effective


def _scope_plan(well: Well, scope: str) -> tuple[Decimal, Decimal, int]:
    """(planned days, deepest planned depth, section count) for one scope."""
    sections = well.sections_for_scope(scope)
    days = sum(
        (Decimal(phase.days) for section in sections for phase in section.phases),
        Decimal("0"),
    )
    depth = max((Decimal(section.to_depth) for section in sections), default=Decimal("0"))
    return days, depth, len(sections)


def _plan_for_well(well: Well, adjustments: dict[tuple[str, str], Any]) -> dict[str, Any]:
    drilling_days, drilling_depth, drilling_sections = _scope_plan(well, "drilling")
    completion_days, completion_depth, completion_sections = _scope_plan(well, "completion")
    drilling_adjustment = adjustments.get((well.id, "drilling"))
    completion_adjustment = adjustments.get((well.id, "completion"))
    planned_completion = (
        Decimal(completion_adjustment.planned_days_after) if completion_adjustment else completion_days
    )
    return {
        # An approved plan adjustment replaces the configured day count for its scope.
        "drilling_days": Decimal(drilling_adjustment.planned_days_after) if drilling_adjustment else drilling_days,
        "completion_days": planned_completion,
        "drilling_adjusted": drilling_adjustment is not None,
        "completion_adjusted": completion_adjustment is not None,
        "depth": max(drilling_depth, completion_depth),
        "section_count": drilling_sections,
        "completion_section_count": completion_sections,
    }


def _line_subquery(
    db: Session,
    organization_id: str,
    well_ids: Sequence[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    currency: str = "",
) -> Any:
    """One row per daily cost line, with the entry's well, AFE, date and currency.

    The four line tables (services, consumables, tangibles, other expenses)
    share the columns the dashboard needs, so a UNION ALL keeps a single
    column-wise shape. No JSON is read or written anywhere.
    """
    from app.services.daily_cost import LINE_MODELS

    parts = []
    for model, group in LINE_MODELS:
        statement = (
            select(
                DailyCostEntry.well_id.label("well_id"),
                DailyCostEntry.afe_id.label("afe_id"),
                DailyCostEntry.cost_date.label("cost_date"),
                DailyCostEntry.standard_currency.label("standard_currency"),
                literal(group).label("cost_group"),
                model.hole_section_id.label("hole_section_id"),
                model.section_code_snapshot.label("section_code"),
                model.section_name_snapshot.label("section_name"),
                model.activity_id.label("activity_id"),
                model.activity_code_snapshot.label("activity_code"),
                model.activity_name_snapshot.label("activity_name"),
                model.classification.label("classification"),
                model.standard_amount.label("standard_amount"),
            )
            .select_from(model)
            .join(DailyCostEntry, model.entry_id == DailyCostEntry.id)
            .where(
                model.organization_id == organization_id,
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.well_id.in_(list(well_ids)),
                DailyCostEntry.is_deleted.is_(False),
            )
        )
        if not include_draft:
            statement = statement.where(DailyCostEntry.status == "submitted")
        if date_from is not None:
            statement = statement.where(DailyCostEntry.cost_date >= date_from)
        if date_to is not None:
            statement = statement.where(DailyCostEntry.cost_date <= date_to)
        if currency:
            statement = statement.where(DailyCostEntry.standard_currency == currency)
        parts.append(statement)
    return union_all(*parts).subquery("dashboard_daily_lines")


def _entry_conditions(
    organization_id: str,
    well_ids: Sequence[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    afe_id: str = "",
) -> list[Any]:
    conditions: list[Any] = [
        DailyCostEntry.organization_id == organization_id,
        DailyCostEntry.is_deleted.is_(False),
        DailyCostEntry.well_id.in_(list(well_ids)),
    ]
    if afe_id:
        conditions.append(DailyCostEntry.afe_id == afe_id)
    if date_from is not None:
        conditions.append(DailyCostEntry.cost_date >= date_from)
    if date_to is not None:
        conditions.append(DailyCostEntry.cost_date <= date_to)
    if not include_draft:
        conditions.append(DailyCostEntry.status == "submitted")
    return conditions


def _entry_totals(
    db: Session,
    organization_id: str,
    well_ids: Sequence[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    afe_id: str = "",
) -> list[Any]:
    """Daily sheet totals grouped by well, AFE and standard currency."""
    if not well_ids:
        return []
    return list(
        db.execute(
            select(
                DailyCostEntry.well_id,
                DailyCostEntry.afe_id,
                DailyCostEntry.standard_currency,
                func.min(DailyCostEntry.cost_date),
                func.max(DailyCostEntry.cost_date),
                func.count(func.distinct(DailyCostEntry.cost_date)),
                func.count(DailyCostEntry.id),
                func.count(case((DailyCostEntry.status == "draft", DailyCostEntry.id))),
                func.sum(DailyCostEntry.services_total),
                func.sum(DailyCostEntry.consumables_total),
                func.sum(DailyCostEntry.tangibles_total),
                func.sum(DailyCostEntry.other_expenses_total),
                func.sum(DailyCostEntry.total_cost),
                func.sum(DailyCostEntry.upa_total),
                func.sum(DailyCostEntry.npt_total),
            )
            .where(*_entry_conditions(
                organization_id, well_ids,
                date_from=date_from, date_to=date_to, include_draft=include_draft, afe_id=afe_id,
            ))
            .group_by(DailyCostEntry.well_id, DailyCostEntry.afe_id, DailyCostEntry.standard_currency)
        ).all()
    )


def _daily_sheets(
    db: Session,
    organization_id: str,
    well_ids: Sequence[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    afe_id: str = "",
) -> dict[date, int]:
    if not well_ids:
        return {}
    return {
        row[0]: int(row[1])
        for row in db.execute(
            select(DailyCostEntry.cost_date, func.count(DailyCostEntry.id))
            .where(*_entry_conditions(
                organization_id, well_ids,
                date_from=date_from, date_to=date_to, include_draft=include_draft, afe_id=afe_id,
            ))
            .group_by(DailyCostEntry.cost_date)
        ).all()
    }


def _empty_afe_bucket() -> dict[str, Any]:
    return {
        "count": 0, "drilling": 0, "completion": 0,
        "amount": Decimal("0"), "adjusted": Decimal("0"), "effective": Decimal("0"),
        "has_adjustment": False, "over_budget": False,
    }


# ---------------------------------------------------------------------------
# The dashboard
# ---------------------------------------------------------------------------


def dashboard(
    db: Session,
    organization_id: str,
    user: User,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    rig_id: str = "",
    well_id: str = "",
    afe_id: str = "",
    afe_type: str = "",
    well_status: str = "",
    currency: str = "",
    include_draft: bool = True,
) -> BusinessDashboardOut:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    if not access_allowed(user):
        raise HTTPException(status_code=403, detail="Permission denied")

    caps = capabilities(user)
    generated_at = _now()

    # ---- scope: rigs and wells ------------------------------------------------
    all_wells = _load_wells(db, organization_id)
    default_currency = _default_currency(db, organization_id)

    requested_afe: Afe | None = None
    if afe_id:
        requested_afe = db.scalar(
            select(Afe).where(
                Afe.id == afe_id,
                Afe.organization_id == organization_id,
                Afe.is_deleted.is_(False),
            )
        )
        if requested_afe is None:
            raise HTTPException(status_code=404, detail="AFE not found in this workspace")

    all_afes: list[Afe] = []
    if caps.budget:
        all_afes = list(
            db.scalars(
                select(Afe)
                .where(Afe.organization_id == organization_id, Afe.is_deleted.is_(False))
                .order_by(Afe.afe_code)
            ).all()
        )

    wells = all_wells
    if rig_id:
        wells = [well for well in wells if well.rig_id == rig_id]
    if well_id:
        if not any(well.id == well_id for well in all_wells):
            raise HTTPException(status_code=404, detail="Well not found in this workspace")
        wells = [well for well in wells if well.id == well_id]
    if requested_afe is not None:
        wells = [well for well in wells if well.id == requested_afe.well_id]
    if afe_type:
        typed_wells = {afe.well_id for afe in all_afes if afe.afe_type == afe_type}
        wells = [well for well in wells if well.id in typed_wells]
    if well_status:
        wells = [well for well in wells if well.status == well_status]

    well_ids = [well.id for well in wells]

    # ---- AFEs -----------------------------------------------------------------
    afes: list[Afe] = []
    afe_outs: dict[str, Any] = {}
    sow_map: dict[str, Any] = {}
    afe_read_error = False
    conversion_pending_afes = 0
    if caps.budget:
        scope = set(well_ids)
        afes = [afe for afe in all_afes if afe.well_id in scope]
        if afe_id:
            afes = [afe for afe in afes if afe.id == afe_id]
        if afe_type:
            afes = [afe for afe in afes if afe.afe_type == afe_type]
        if afes:
            try:
                # The pricing helper is shared with the AFE register and overview so the
                # dashboard shows exactly the same saved estimate totals.
                afe_outs = {row.id: row for row in afe_service._outs_for(db, organization_id, afes)}
                sow_map = afe_service._effective_sow_map(db, organization_id, [afe.id for afe in afes])
            except Exception:  # noqa: BLE001 - one malformed legacy estimate must not blank the page
                log.exception("Business dashboard could not price saved AFE estimates")
                afe_read_error = True
                afe_outs = {}
                sow_map = {}
        conversion_pending_afes = sum(
            1 for row in afe_outs.values() if getattr(row, "total_cost", None) is None
        )

    # ---- currency --------------------------------------------------------------
    entry_currencies: set[str] = set()
    if caps.actuals and well_ids:
        entry_currencies = {
            str(code)
            for code in db.scalars(
                select(DailyCostEntry.standard_currency)
                .where(*_entry_conditions(
                    organization_id, well_ids,
                    date_from=date_from, date_to=date_to, include_draft=include_draft, afe_id=afe_id,
                ))
                .distinct()
            ).all()
            if code
        }
    afe_currencies = {
        str(row.standard_currency) for row in afe_outs.values() if getattr(row, "standard_currency", "")
    }
    available = sorted({*afe_currencies, *entry_currencies, *([default_currency] if default_currency else [])})
    selected = (currency or "").strip().upper()
    if not selected:
        selected = default_currency or (available[0] if available else "")
    if selected and selected not in available:
        available = sorted({*available, selected})

    # ---- plan ------------------------------------------------------------------
    plan_map = _plan_map(db, organization_id, well_ids) if caps.plan else {}
    plans = {well.id: _plan_for_well(well, plan_map) for well in wells}

    # ---- actuals ---------------------------------------------------------------
    per_well: dict[str, dict[str, Any]] = {}
    per_afe: dict[str, dict[str, Any]] = {}
    excluded_entry_count = 0
    sheets_by_day: dict[date, int] = {}
    if caps.actuals and well_ids:
        for row in _entry_totals(
            db, organization_id, well_ids,
            date_from=date_from, date_to=date_to, include_draft=include_draft, afe_id=afe_id,
        ):
            code = str(row[2] or "")
            if code != selected:
                excluded_entry_count += int(row[6] or 0)
                continue
            well_bucket = per_well.setdefault(row[0], {
                "first": None, "last": None, "recorded_days": 0, "sheets": 0, "draft_sheets": 0,
                "services": Decimal("0"), "consumables": Decimal("0"), "tangibles": Decimal("0"),
                "other": Decimal("0"), "total": Decimal("0"), "upa": Decimal("0"), "npt": Decimal("0"),
            })
            well_bucket["first"] = min(filter(None, [well_bucket["first"], row[3]]), default=None)
            well_bucket["last"] = max(filter(None, [well_bucket["last"], row[4]]), default=None)
            well_bucket["recorded_days"] += int(row[5] or 0)
            well_bucket["sheets"] += int(row[6] or 0)
            well_bucket["draft_sheets"] += int(row[7] or 0)
            well_bucket["services"] += Decimal(row[8] or 0)
            well_bucket["consumables"] += Decimal(row[9] or 0)
            well_bucket["tangibles"] += Decimal(row[10] or 0)
            well_bucket["other"] += Decimal(row[11] or 0)
            well_bucket["total"] += Decimal(row[12] or 0)
            well_bucket["upa"] += Decimal(row[13] or 0)
            well_bucket["npt"] += Decimal(row[14] or 0)
            afe_bucket = per_afe.setdefault(row[1], {
                "first": None, "last": None, "recorded_days": 0, "sheets": 0,
                "total": Decimal("0"), "upa": Decimal("0"), "npt": Decimal("0"),
            })
            afe_bucket["first"] = min(filter(None, [afe_bucket["first"], row[3]]), default=None)
            afe_bucket["last"] = max(filter(None, [afe_bucket["last"], row[4]]), default=None)
            afe_bucket["recorded_days"] += int(row[5] or 0)
            afe_bucket["sheets"] += int(row[6] or 0)
            afe_bucket["total"] += Decimal(row[12] or 0)
            afe_bucket["upa"] += Decimal(row[13] or 0)
            afe_bucket["npt"] += Decimal(row[14] or 0)
        sheets_by_day = _daily_sheets(
            db, organization_id, well_ids,
            date_from=date_from, date_to=date_to, include_draft=include_draft, afe_id=afe_id,
        )

    # ---- line facts: classification days, sections, depth, daily trend --------
    well_classification: dict[tuple[str, str], int] = defaultdict(int)
    afe_classification: dict[tuple[str, str], int] = defaultdict(int)
    section_facts: dict[tuple[str, str | None], dict[str, Any]] = {}
    daily_facts: dict[date, dict[str, Decimal]] = {}
    group_actual: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    classification_amounts: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    if caps.actuals and well_ids:
        lines = _line_subquery(
            db, organization_id, well_ids,
            date_from=date_from, date_to=date_to, include_draft=include_draft, currency=selected,
        )
        for well_key, classification, days_count, amount in db.execute(
            select(
                lines.c.well_id,
                lines.c.classification,
                func.count(func.distinct(lines.c.cost_date)),
                func.sum(lines.c.standard_amount),
            )
            .select_from(lines)
            .group_by(lines.c.well_id, lines.c.classification)
        ).all():
            well_classification[(well_key, str(classification or "Planned"))] = int(days_count or 0)
            classification_amounts[str(classification or "Planned")] += Decimal(amount or 0)
        for afe_key, classification, days_count in db.execute(
            select(
                lines.c.afe_id,
                lines.c.classification,
                func.count(func.distinct(lines.c.cost_date)),
            )
            .select_from(lines)
            .group_by(lines.c.afe_id, lines.c.classification)
        ).all():
            afe_classification[(afe_key, str(classification or "Planned"))] = int(days_count or 0)
        for well_key, section_id, code, name, active_days, amount in db.execute(
            select(
                lines.c.well_id,
                lines.c.hole_section_id,
                func.min(lines.c.section_code),
                func.min(lines.c.section_name),
                func.count(func.distinct(lines.c.cost_date)),
                func.sum(lines.c.standard_amount),
            )
            .select_from(lines)
            .group_by(lines.c.well_id, lines.c.hole_section_id)
        ).all():
            section_facts[(well_key, section_id)] = {
                "code": str(code or ""),
                "name": str(name or ""),
                "active_days": int(active_days or 0),
                "amount": Decimal(amount or 0),
            }
        for cost_day, amount, npt, upa in db.execute(
            select(
                lines.c.cost_date,
                func.sum(lines.c.standard_amount),
                func.sum(case((lines.c.classification == "NPT", lines.c.standard_amount), else_=Decimal("0"))),
                func.sum(case((lines.c.classification == "UPA", lines.c.standard_amount), else_=Decimal("0"))),
            )
            .select_from(lines)
            .group_by(lines.c.cost_date)
            .order_by(lines.c.cost_date)
        ).all():
            daily_facts[cost_day] = {
                "actual": Decimal(amount or 0),
                "npt": Decimal(npt or 0),
                "upa": Decimal(upa or 0),
            }
        for group, amount in db.execute(
            select(lines.c.cost_group, func.sum(lines.c.standard_amount))
            .select_from(lines)
            .group_by(lines.c.cost_group)
        ).all():
            group_actual[str(group)] += Decimal(amount or 0)

    # ---- AFE totals by well and currency --------------------------------------
    afe_totals: dict[str, dict[str, Any]] = defaultdict(_empty_afe_bucket)
    excluded_afe_count = 0
    afe_rows: list[DashboardAfeRow] = []
    # AFE group totals feed the cost-group reconciliation and are currency-scoped too.
    planned_by_group: dict[str, Decimal] = {"Services": Decimal("0"), "Consumables": Decimal("0"), "Tangibles": Decimal("0")}
    for afe in afes:
        out = afe_outs.get(afe.id)
        code = str(getattr(out, "standard_currency", "") or afe.standard_currency or "")
        pending = out is None or getattr(out, "total_cost", None) is None
        if out is not None and code != selected:
            excluded_afe_count += 1
        amount = None if pending else _money(getattr(out, "total_cost", None))
        adjusted = None
        if out is not None and getattr(out, "has_sow_adjustment", False):
            adjustment = sow_map.get(afe.id)
            if adjustment is not None and str(adjustment.standard_currency or "") == code:
                adjusted = _money(Decimal(adjustment.adjusted_total))
        effective = adjusted if adjusted is not None else amount
        actual_bucket = per_afe.get(afe.id)
        actual = _money(actual_bucket["total"]) if actual_bucket else (
            _money(Decimal("0")) if caps.actuals else None
        )
        balance = _money(effective - actual) if effective is not None and actual is not None else None
        afe_rows.append(DashboardAfeRow(
            afe_id=afe.id,
            afe_code=afe.afe_code,
            afe_name=afe.afe_name,
            afe_type=afe.afe_type,
            configuration_scope=afe.configuration_scope,
            status=afe.status,
            well_id=afe.well_id,
            well_code=_well_field(wells, afe.well_id, "well_code"),
            well_name=_well_field(wells, afe.well_id, "well_name"),
            rig_id=afe.rig_id,
            rig_code=_rig_field(wells, afe.well_id, "rig_code"),
            rig_name=_rig_field(wells, afe.well_id, "rig_name"),
            currency=code,
            afe_amount=amount,
            sow_adjusted_amount=adjusted,
            has_sow_adjustment=adjusted is not None,
            sow_revision=getattr(out, "sow_revision", None),
            effective_afe_amount=effective,
            actual_amount=actual,
            afe_balance=balance,
            utilisation_percent=_percent(actual, effective) if actual is not None and effective else None,
            over_budget=bool(effective is not None and actual is not None and actual > effective),
            conversion_pending=pending,
            first_cost_date=actual_bucket["first"] if actual_bucket else None,
            last_cost_date=actual_bucket["last"] if actual_bucket else None,
            actual_days=_span(actual_bucket) if caps.actuals else None,
            recorded_days=actual_bucket["recorded_days"] if actual_bucket else (0 if caps.actuals else None),
            sheets=actual_bucket["sheets"] if actual_bucket else (0 if caps.actuals else None),
            npt_days=afe_classification.get((afe.id, "NPT"), 0) if caps.actuals else None,
            upa_days=afe_classification.get((afe.id, "UPA"), 0) if caps.actuals else None,
            npt_amount=_money(actual_bucket["npt"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            upa_amount=_money(actual_bucket["upa"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
        ))
        if code != selected or pending:
            continue
        bucket = afe_totals[afe.well_id]
        bucket["count"] += 1
        bucket["drilling" if afe.afe_type == "Drilling" else "completion"] += 1
        bucket["amount"] += Decimal(amount or 0)
        if adjusted is not None:
            bucket["adjusted"] += adjusted
            bucket["has_adjustment"] = True
        bucket["effective"] += Decimal(effective or 0)
        if actual is not None and effective is not None and actual > effective:
            bucket["over_budget"] = True
        for group, value in (
            ("Services", getattr(out, "services_total", 0)),
            ("Consumables", getattr(out, "consumables_total", 0)),
            ("Tangibles", getattr(out, "tangibles_total", 0)),
        ):
            planned_by_group[group] += Decimal(value or 0)

    # ---- well rows -------------------------------------------------------------
    well_rows: list[DashboardWellRow] = []
    for well in wells:
        plan = plans[well.id]
        afe_bucket = afe_totals.get(well.id) or _empty_afe_bucket()
        actual_bucket = per_well.get(well.id)
        first_day = actual_bucket["first"] if actual_bucket else None
        last_day = actual_bucket["last"] if actual_bucket else None
        actual_amount = _money(actual_bucket["total"]) if actual_bucket else (
            _money(Decimal("0")) if caps.actuals else None
        )
        effective = _money(afe_bucket["effective"]) if caps.budget else None
        balance = _money(effective - actual_amount) if effective is not None and actual_amount is not None else None
        actual_depth = None
        if caps.plan and caps.actuals:
            depths = _section_depths(well)
            reached = [
                depths[section_id]
                for (well_key, section_id), values in section_facts.items()
                if well_key == well.id and section_id in depths and values["active_days"]
            ]
            actual_depth = _money(max(reached)) if reached else _money(Decimal("0"))
        planned_depth = _money(plan["depth"]) if caps.plan else None
        progress = (
            _percent(actual_depth, planned_depth)
            if planned_depth and planned_depth > 0 and actual_depth is not None else None
        )
        well_rows.append(DashboardWellRow(
            well_id=well.id,
            well_code=well.well_code,
            well_name=well.well_name,
            well_location=well.well_location,
            block=well.block,
            status=well.status,
            config_status=well.config_status,
            depth_unit=well.depth_unit,
            rig_id=well.rig_id,
            rig_code=well.rig.rig_code if well.rig else "",
            rig_name=well.rig.rig_name if well.rig else "",
            drilling_planned_days=_money(plan["drilling_days"]) if caps.plan else None,
            completion_planned_days=_money(plan["completion_days"]) if caps.plan and plan["completion_section_count"] else None,
            planned_days=_money(plan["drilling_days"] + plan["completion_days"]) if caps.plan else None,
            drilling_plan_adjusted=plan["drilling_adjusted"],
            completion_plan_adjusted=plan["completion_adjusted"],
            section_count=plan["section_count"] if caps.plan else None,
            planned_depth=planned_depth,
            actual_depth=actual_depth,
            depth_progress_percent=progress,
            afe_count=afe_bucket["count"] if caps.budget else None,
            drilling_afe_count=afe_bucket["drilling"] if caps.budget else None,
            completion_afe_count=afe_bucket["completion"] if caps.budget else None,
            afe_amount=_money(afe_bucket["amount"]) if caps.budget else None,
            sow_adjusted_amount=_money(afe_bucket["adjusted"]) if caps.budget and afe_bucket["has_adjustment"] else None,
            has_sow_adjustment=bool(afe_bucket["has_adjustment"]) if caps.budget else False,
            effective_afe_amount=effective,
            afe_balance=balance,
            utilisation_percent=_percent(actual_amount, effective) if actual_amount is not None and effective else None,
            over_budget=bool(balance is not None and balance < 0),
            actual_amount=actual_amount,
            services_amount=_money(actual_bucket["services"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            consumables_amount=_money(actual_bucket["consumables"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            tangibles_amount=_money(actual_bucket["tangibles"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            other_expenses_amount=_money(actual_bucket["other"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            npt_amount=_money(actual_bucket["npt"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            upa_amount=_money(actual_bucket["upa"]) if actual_bucket else (_money(Decimal("0")) if caps.actuals else None),
            first_cost_date=first_day,
            last_cost_date=last_day,
            actual_days=_span(actual_bucket) if caps.actuals else None,
            recorded_days=actual_bucket["recorded_days"] if actual_bucket else (0 if caps.actuals else None),
            sheets=actual_bucket["sheets"] if actual_bucket else (0 if caps.actuals else None),
            draft_sheets=actual_bucket["draft_sheets"] if actual_bucket else (0 if caps.actuals else None),
            npt_days=well_classification.get((well.id, "NPT"), 0) if caps.actuals else None,
            upa_days=well_classification.get((well.id, "UPA"), 0) if caps.actuals else None,
            currency=selected if (caps.budget or caps.actuals) else "",
        ))

    # ---- rigs -------------------------------------------------------------------
    rigs = {well.rig.id: well.rig for well in wells if well.rig is not None}
    rig_rows: list[DashboardRigRow] = []
    for rig in sorted(rigs.values(), key=lambda row: row.rig_code):
        rows = [row for row in well_rows if row.rig_id == rig.id]
        rig_rows.append(DashboardRigRow(
            rig_id=rig.id,
            rig_code=rig.rig_code,
            rig_name=rig.rig_name,
            wells=len(rows),
            active_wells=sum(1 for row in rows if row.status == "active"),
            completed_wells=sum(1 for row in rows if row.status == "completed"),
            planned_days=_money(sum((row.planned_days or Decimal("0") for row in rows), Decimal("0"))) if caps.plan else None,
            actual_days=sum((row.actual_days or 0 for row in rows)) if caps.actuals else None,
            recorded_days=sum((row.recorded_days or 0 for row in rows)) if caps.actuals else None,
            npt_days=sum((row.npt_days or 0 for row in rows)) if caps.actuals else None,
            upa_days=sum((row.upa_days or 0 for row in rows)) if caps.actuals else None,
            afe_amount=_money(sum((row.afe_amount or Decimal("0") for row in rows), Decimal("0"))) if caps.budget else None,
            effective_afe_amount=_money(sum((row.effective_afe_amount or Decimal("0") for row in rows), Decimal("0"))) if caps.budget else None,
            actual_amount=_money(sum((row.actual_amount or Decimal("0") for row in rows), Decimal("0"))) if caps.actuals else None,
            afe_balance=_money(sum((row.afe_balance or Decimal("0") for row in rows), Decimal("0")))
            if caps.budget and caps.actuals else None,
            planned_depth=_money(sum((row.planned_depth or Decimal("0") for row in rows), Decimal("0"))) if caps.plan else None,
            actual_depth=_money(sum((row.actual_depth or Decimal("0") for row in rows), Decimal("0")))
            if caps.plan and caps.actuals else None,
            draft_sheets=sum((row.draft_sheets or 0 for row in rows)) if caps.actuals else None,
        ))

    # ---- totals -----------------------------------------------------------------
    planned_days_total = sum((row.planned_days or Decimal("0") for row in well_rows), Decimal("0"))
    actual_days_total = sum((row.actual_days or 0 for row in well_rows))
    recorded_days_total = sum((row.recorded_days or 0 for row in well_rows))
    npt_days_total = sum((row.npt_days or 0 for row in well_rows))
    upa_days_total = sum((row.upa_days or 0 for row in well_rows))
    afe_amount_total = sum((row.afe_amount or Decimal("0") for row in well_rows), Decimal("0"))
    sow_adjusted_total = sum((row.sow_adjusted_amount or Decimal("0") for row in well_rows), Decimal("0"))
    effective_total = sum((row.effective_afe_amount or Decimal("0") for row in well_rows), Decimal("0"))
    actual_total = sum((row.actual_amount or Decimal("0") for row in well_rows), Decimal("0"))
    # Depth is only additive when every well uses the same unit.
    depth_units = {row.depth_unit for row in well_rows}
    depth_unit = depth_units.pop() if len(depth_units) == 1 else ("mixed" if depth_units else "")
    depths_comparable = depth_unit != "mixed"
    planned_depth_total = sum((row.planned_depth or Decimal("0") for row in well_rows), Decimal("0")) if depths_comparable else Decimal("0")
    actual_depth_total = sum((row.actual_depth or Decimal("0") for row in well_rows), Decimal("0")) if depths_comparable else Decimal("0")

    kpis = DashboardKpis(
        rigs=len(rig_rows),
        wells=len(well_rows),
        active_wells=sum(1 for row in well_rows if row.status == "active"),
        completed_wells=sum(1 for row in well_rows if row.status == "completed"),
        configured_wells=sum(1 for row in well_rows if row.config_status == "configured") if caps.plan else None,
        draft_wells=sum(1 for row in well_rows if row.config_status == "draft") if caps.plan else None,
        afes=len(afe_rows) if caps.budget else None,
        wells_with_actuals=sum(1 for row in well_rows if (row.sheets or 0) > 0) if caps.actuals else None,
        planned_days=_money(planned_days_total) if caps.plan else None,
        actual_days=actual_days_total if caps.actuals else None,
        recorded_days=recorded_days_total if caps.actuals else None,
        npt_days=npt_days_total if caps.actuals else None,
        upa_days=upa_days_total if caps.actuals else None,
        day_variance=_money(Decimal(actual_days_total) - planned_days_total) if caps.plan and caps.actuals else None,
        afe_amount=_money(afe_amount_total) if caps.budget else None,
        sow_adjusted_amount=_money(sow_adjusted_total) if caps.budget and sow_adjusted_total else None,
        effective_afe_amount=_money(effective_total) if caps.budget else None,
        actual_amount=_money(actual_total) if caps.actuals else None,
        afe_balance=_money(effective_total - actual_total) if caps.budget and caps.actuals else None,
        utilisation_percent=_percent(actual_total, effective_total) if caps.budget and caps.actuals else None,
        npt_amount=_money(sum((row.npt_amount or Decimal("0") for row in well_rows), Decimal("0"))) if caps.actuals else None,
        upa_amount=_money(sum((row.upa_amount or Decimal("0") for row in well_rows), Decimal("0"))) if caps.actuals else None,
        other_expenses_amount=_money(sum((row.other_expenses_amount or Decimal("0") for row in well_rows), Decimal("0")))
        if caps.actuals else None,
        planned_depth=_money(planned_depth_total) if caps.plan and depths_comparable else None,
        actual_depth=_money(actual_depth_total) if caps.plan and caps.actuals and depths_comparable else None,
        depth_progress_percent=_percent(actual_depth_total, planned_depth_total)
        if caps.plan and caps.actuals and depths_comparable and planned_depth_total > 0 else None,
        depth_unit=depth_unit,
        over_budget_wells=sum(1 for row in well_rows if row.over_budget),
        over_budget_afes=sum(1 for row in afe_rows if row.over_budget),
        conversion_pending_afes=conversion_pending_afes,
    )

    # ---- slices -----------------------------------------------------------------
    well_statuses = [
        DashboardSlice(key="active", label="Active wells", count=sum(1 for row in well_rows if row.status == "active")),
        DashboardSlice(key="completed", label="Completed wells", count=sum(1 for row in well_rows if row.status == "completed")),
        DashboardSlice(
            key="configured", label="Configuration complete",
            count=sum(1 for row in well_rows if row.config_status == "configured"),
        ),
        DashboardSlice(
            key="draft", label="Configuration in draft",
            count=sum(1 for row in well_rows if row.config_status == "draft"),
        ),
        DashboardSlice(key="tracking", label="Cost tracking started", count=kpis.wells_with_actuals or 0),
    ]
    afe_statuses = [
        DashboardSlice(
            key=status,
            label=label,
            count=sum(1 for row in afe_rows if row.status == status),
        )
        for status, label in AFE_STATUS_LABELS.items()
    ]

    total_group_actual = sum(group_actual.values(), Decimal("0"))
    cost_groups: list[DashboardSlice] = []
    for group in GROUP_LABELS:
        planned = _money(planned_by_group.get(group, Decimal("0"))) if caps.budget else None
        actual = _money(group_actual.get(group, Decimal("0"))) if caps.actuals else None
        cost_groups.append(DashboardSlice(
            key=group.lower().replace(" ", "_"),
            label=group,
            planned=planned,
            actual=actual,
            balance=_money(planned - actual) if planned is not None and actual is not None else None,
            share=_percent(group_actual.get(group, Decimal("0")), total_group_actual)
            if caps.actuals and total_group_actual else None,
        ))

    total_classification = sum(classification_amounts.values(), Decimal("0"))
    classification = [
        DashboardSlice(
            key=key,
            label=CLASSIFICATION_DETAIL[key],
            days=sum(
                days for (well_key, classification_key), days in well_classification.items()
                if classification_key == key
            ) if caps.actuals else None,
            actual=_money(classification_amounts.get(key, Decimal("0"))) if caps.actuals else None,
            share=_percent(classification_amounts.get(key, Decimal("0")), total_classification)
            if caps.actuals and total_classification else None,
        )
        for key in CLASSIFICATIONS
    ]

    daily: list[DashboardDailyPoint] = []
    if caps.actuals:
        cumulative = Decimal("0")
        for cost_day in sorted(daily_facts):
            bucket = daily_facts[cost_day]
            cumulative += bucket["actual"]
            daily.append(DashboardDailyPoint(
                cost_date=cost_day,
                actual=_money(bucket["actual"]) or Decimal("0.00"),
                cumulative=_money(cumulative) or Decimal("0.00"),
                npt=_money(bucket["npt"]) or Decimal("0.00"),
                upa=_money(bucket["upa"]) or Decimal("0.00"),
                sheets=sheets_by_day.get(cost_day, 0),
            ))

    # ---- alerts -----------------------------------------------------------------
    alerts: list[DashboardAlert] = []
    over_budget = [row for row in well_rows if row.over_budget]
    if over_budget:
        overspend = sum((-(row.afe_balance or Decimal("0")) for row in over_budget), Decimal("0"))
        alerts.append(DashboardAlert(
            kind="over_budget",
            severity="error",
            title=f"{len(over_budget)} well{'s' if len(over_budget) != 1 else ''} over the AFE amount",
            detail=(
                f"Actual cost exceeds the effective AFE by {selected} {overspend:,.2f}. "
                "Open a well to see the cost lines behind it."
            ),
        ))
    if afe_read_error:
        alerts.append(DashboardAlert(
            kind="afe_unreadable",
            severity="error",
            title="Saved AFE estimates could not be priced",
            detail="Their amounts are left out of this view. Open AFE cost estimation to repair the affected estimate.",
        ))
    if conversion_pending_afes:
        alerts.append(DashboardAlert(
            kind="conversion_pending",
            severity="warning",
            title=f"{conversion_pending_afes} AFE{'s' if conversion_pending_afes != 1 else ''} without a converted total",
            detail="Those AFEs are left out of the money totals until their currency conversion rates are entered in AFE cost estimation.",
        ))
    if caps.budget and not afe_read_error:
        without_afe = [row for row in well_rows if not row.afe_count]
        if without_afe:
            alerts.append(DashboardAlert(
                kind="missing_afe",
                severity="info",
                title=f"{len(without_afe)} well{'s' if len(without_afe) != 1 else ''} without an active AFE in {selected or 'this currency'}",
                detail="These wells have no authorized budget to compare against. Create the AFE in AFE Management.",
            ))
    if caps.plan and caps.actuals:
        tracking_without_plan = [
            row for row in well_rows if (row.sheets or 0) > 0 and (row.planned_days or 0) == 0
        ]
        if tracking_without_plan:
            alerts.append(DashboardAlert(
                kind="missing_plan",
                severity="warning",
                title=f"{len(tracking_without_plan)} tracked well{'s' if len(tracking_without_plan) != 1 else ''} without planned days",
                detail="Cost is being recorded but the well configuration has no planned days, so day variance cannot be measured.",
            ))
    if not depths_comparable:
        alerts.append(DashboardAlert(
            kind="mixed_depth_units",
            severity="warning",
            title="Wells use different depth units",
            detail="Depth totals are hidden because metres and feet are never added together; each well row keeps its own unit.",
        ))
    if excluded_afe_count or excluded_entry_count:
        alerts.append(DashboardAlert(
            kind="currency_excluded",
            severity="warning",
            title=f"Mixed currencies: figures outside {selected or 'the selected currency'} are excluded",
            detail=(
                f"{excluded_afe_count} AFE{'s' if excluded_afe_count != 1 else ''} and "
                f"{excluded_entry_count} daily sheet{'s' if excluded_entry_count != 1 else ''} use another standard currency. "
                "Their rows still show their own currency; totals never add different currencies together."
            ),
        ))
    if include_draft and (kpis.wells_with_actuals or 0) > 0:
        alerts.append(DashboardAlert(
            kind="drafts_included",
            severity="info",
            title="Draft daily sheets are included",
            detail="Turn off “Include drafts” to reconcile the dashboard with submitted sheets only.",
        ))

    # ---- filter options ---------------------------------------------------------
    filter_options = DashboardFilterOptions(
        rigs=sorted(
            {
                well.rig.id: DashboardRigOption(
                    id=well.rig.id, code=well.rig.rig_code, name=well.rig.rig_name,
                )
                for well in all_wells if well.rig is not None
            }.values(),
            key=lambda row: row.code,
        ),
        wells=[
            DashboardWellOption(
                id=well.id, code=well.well_code, name=well.well_name, rig_id=well.rig_id,
                rig_code=well.rig.rig_code if well.rig else "", status=well.status,
            )
            for well in all_wells
        ],
        afes=[
            DashboardAfeOption(
                id=afe.id, code=afe.afe_code, name=afe.afe_name, well_id=afe.well_id,
                rig_id=afe.rig_id, afe_type=afe.afe_type, status=afe.status,
                currency=str(afe.standard_currency or ""),
            )
            for afe in all_afes
        ],
        currencies=available,
        default_currency=default_currency,
        afe_types=sorted({afe.afe_type for afe in all_afes}),
    )

    return BusinessDashboardOut(
        generated_at=generated_at,
        date_from=date_from,
        date_to=date_to,
        include_draft=include_draft,
        currency=selected,
        available_currencies=available,
        default_currency=default_currency,
        capabilities=caps,
        filters=filter_options,
        kpis=kpis,
        alerts=alerts,
        well_statuses=well_statuses,
        afe_statuses=afe_statuses,
        cost_groups=cost_groups,
        classification=classification,
        daily=daily,
        rigs=rig_rows,
        wells=well_rows,
        afes=afe_rows,
        excluded_afe_count=excluded_afe_count,
        excluded_entry_count=excluded_entry_count,
        conversion_pending_afes=conversion_pending_afes,
    )


# ---------------------------------------------------------------------------
# Drill-through helpers
# ---------------------------------------------------------------------------


def _span(bucket: dict[str, Any] | None) -> int:
    """Calendar days from the first to the last sheet of the cost register."""
    if not bucket or not bucket["first"] or not bucket["last"]:
        return 0
    return (bucket["last"] - bucket["first"]).days + 1


def _section_depths(well: Well) -> dict[str | None, Decimal]:
    """Deepest reachable depth for each configured hole section of one well."""
    depths: dict[str | None, Decimal] = {}
    for scope in ("drilling", "completion"):
        for section in well.sections_for_scope(scope):
            depth = Decimal(section.to_depth)
            if section.hole_section_id not in depths or depth > depths[section.hole_section_id]:
                depths[section.hole_section_id] = depth
    return depths


def _well_field(wells: Sequence[Well], well_id: str, field: str) -> str:
    for well in wells:
        if well.id == well_id:
            return str(getattr(well, field, "") or "")
    return ""


def _rig_field(wells: Sequence[Well], well_id: str, field: str) -> str:
    for well in wells:
        if well.id == well_id and well.rig is not None:
            return str(getattr(well.rig, field, "") or "")
    return ""


def well_detail(
    db: Session,
    organization_id: str,
    user: User,
    well_id: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    currency: str = "",
    include_draft: bool = True,
) -> DashboardWellDetail:
    """One well's plan, budget and actuals, cut by activity, section and day."""
    payload = dashboard(
        db, organization_id, user,
        date_from=date_from, date_to=date_to, well_id=well_id,
        currency=currency, include_draft=include_draft,
    )
    row = next((item for item in payload.wells if item.well_id == well_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    caps = payload.capabilities
    well = db.scalars(
        select(Well)
        .options(
            joinedload(Well.rig),
            selectinload(Well.sections).selectinload(WellSection.phases),
            selectinload(Well.completion_sections).selectinload(WellSection.phases),
        )
        .where(Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False))
    ).unique().first()
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")

    notes: list[str] = [
        "Actual days run from the first to the last day of this well's cost register (calendar days), so any missing sheet inside that span is included.",
        "NPT and UPA days count the distinct cost dates on which a line classified Non-Productive Time or Unplanned Activity was recorded.",
    ]

    activities: list[DashboardActivityRow] = []
    sections: list[DashboardSectionRow] = []
    if caps.actuals:
        lines = _line_subquery(
            db, organization_id, [well_id],
            date_from=date_from, date_to=date_to, include_draft=include_draft,
            currency=payload.currency,
        )
        activity_rows = db.execute(
            select(
                lines.c.activity_id,
                func.min(lines.c.activity_code),
                func.min(lines.c.activity_name),
                func.min(lines.c.classification),
                func.count(func.distinct(lines.c.cost_date)),
                func.sum(lines.c.standard_amount),
            )
            .select_from(lines)
            .group_by(lines.c.activity_id)
        ).all()
        total_activity = sum((Decimal(values[5] or 0) for values in activity_rows), Decimal("0"))
        for values in activity_rows:
            amount = Decimal(values[5] or 0)
            activities.append(DashboardActivityRow(
                activity_id=values[0],
                activity_code=str(values[1] or ""),
                activity_name=str(values[2] or ""),
                classification=str(values[3] or "Planned"),
                active_days=int(values[4] or 0),
                amount=_money(amount),
                share=_percent(amount, total_activity) if total_activity else None,
            ))
        activities.sort(key=lambda item: item.amount or Decimal("0"), reverse=True)

        section_totals = db.execute(
            select(
                lines.c.hole_section_id,
                func.min(lines.c.section_code),
                func.min(lines.c.section_name),
                func.count(func.distinct(lines.c.cost_date)),
                func.sum(lines.c.standard_amount),
            )
            .select_from(lines)
            .group_by(lines.c.hole_section_id)
        ).all()
        total_section = sum((Decimal(values[4] or 0) for values in section_totals), Decimal("0"))
        used = {values[0]: values for values in section_totals}
        depths = _section_depths(well)
        reached_depth = max(
            (depths.get(section_id, Decimal("0")) for section_id, values in used.items() if values[3]),
            default=Decimal("0"),
        )
        for scope in ("drilling", "completion"):
            for section in well.sections_for_scope(scope):
                values = used.get(section.hole_section_id)
                amount = Decimal(values[4] or 0) if values else Decimal("0")
                active_days = int(values[3] or 0) if values else 0
                planned_days = sum((Decimal(phase.days) for phase in section.phases), Decimal("0"))
                sections.append(DashboardSectionRow(
                    hole_section_id=section.hole_section_id,
                    section_code=section.hole_section.section_code if section.hole_section else "",
                    section_name=section.hole_section.section_name if section.hole_section else "",
                    scope=scope,
                    from_depth=_money(section.from_depth),
                    to_depth=_money(section.to_depth),
                    planned_days=_money(planned_days),
                    active_days=active_days,
                    amount=_money(amount),
                    share=_percent(amount, total_section) if total_section else None,
                    reached=bool(active_days) or (reached_depth > 0 and Decimal(section.to_depth) <= reached_depth),
                    planned_phase_count=len(section.phases),
                ))
        # Cost booked to a section that has since left the configuration stays visible.
        configured = {
            section.hole_section_id
            for scope in ("drilling", "completion")
            for section in well.sections_for_scope(scope)
        }
        for section_id, values in used.items():
            if section_id in configured:
                continue
            amount = Decimal(values[4] or 0)
            sections.append(DashboardSectionRow(
                hole_section_id=section_id,
                section_code=str(values[1] or "Unassigned"),
                section_name=str(values[2] or "Section no longer in the configuration"),
                scope="",
                active_days=int(values[3] or 0),
                amount=_money(amount),
                share=_percent(amount, total_section) if total_section else None,
                reached=True,
            ))
        notes.append(
            "Actual depth progress uses the deepest configured hole section that carries recorded daily cost; "
            "sections at or above that depth are shown as reached."
        )
    else:
        notes.append("Actual cost figures are hidden because daily cost read access is not granted.")

    day_sheets: list[DashboardDaySheet] = []
    if caps.actuals:
        entry_query = (
            select(
                DailyCostEntry.id,
                DailyCostEntry.cost_date,
                DailyCostEntry.afe_code_snapshot,
                DailyCostEntry.status,
                DailyCostEntry.total_cost,
                DailyCostEntry.npt_total,
                DailyCostEntry.upa_total,
                DailyCostEntry.warning_count,
            )
            .where(
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.well_id == well_id,
                DailyCostEntry.is_deleted.is_(False),
                DailyCostEntry.standard_currency == payload.currency,
            )
            .order_by(DailyCostEntry.cost_date.desc())
            .limit(180)
        )
        if date_from:
            entry_query = entry_query.where(DailyCostEntry.cost_date >= date_from)
        if date_to:
            entry_query = entry_query.where(DailyCostEntry.cost_date <= date_to)
        if not include_draft:
            entry_query = entry_query.where(DailyCostEntry.status != "draft")
        day_sheets = [
            DashboardDaySheet(
                entry_id=values[0],
                cost_date=values[1],
                afe_code=str(values[2] or ""),
                status=str(values[3] or "draft"),
                total=_money(values[4]),
                npt=_money(values[5]),
                upa=_money(values[6]),
                warning_count=int(values[7] or 0),
            )
            for values in db.execute(entry_query).all()
        ]
        notes.append(
            "Every daily cost sheet in the current range is listed with a link to the sheet itself."
        )

    if not caps.budget:
        notes.append("AFE figures are hidden because AFE read access is not granted.")
    if not caps.plan:
        notes.append("Planned days and depth are hidden because rig and well read access is not granted.")

    return DashboardWellDetail(
        well=row,
        afes=[item for item in payload.afes if item.well_id == well_id],
        daily=list(payload.daily),
        sheets=day_sheets,
        classification=list(payload.classification),
        cost_groups=list(payload.cost_groups),
        activities=activities,
        sections=sections,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Audited export
# ---------------------------------------------------------------------------


def record_export(
    db: Session,
    user: User,
    *,
    fmt: str,
    record_count: int,
    request: Request | None = None,
) -> None:
    if not export_allowed(user):
        raise HTTPException(status_code=403, detail="Permission denied")
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="business_dashboard",
        entity_label="Business dashboard",
        summary=f"Exported the business dashboard as {fmt.upper()} ({record_count} rows)",
        request=request,
    )
    db.commit()
