"""Persistence, reconciliation and workflow services for Mud Cost Analysis."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.units import depth_to_meters
from app.domain.mud_cost import (
    MUD_COST_LINE_SPECS,
    MUD_LOSS_REPORT_LINES,
    MUD_COST_MUD_TYPE_LABELS,
    ZERO,
    closing_stock,
    group_total,
    line_amounts,
    loss_breakdown,
    reconcile_mud,
)
from app.models import (
    Afe,
    Currency,
    DailyCostBaseline,
    DailyCostBaselineBudgetLine,
    DailyCostConsumableLine,
    DailyCostEntry,
    MudCostEntry,
    MudCostEntryLine,
    MudCostSectionSetting,
    Rig,
    Well,
    WellSection,
)
from app.models.rig_well import now
from app.models.entities import User
from app.schemas.mud_cost import (
    MudCostBalanceRowOut,
    MudCostEntryCreate,
    MudCostEntryOut,
    MudCostEntryUpdate,
    MudCostOpeningStockIn,
    MudCostExportAudit,
    MudCostImportRequest,
    MudCostImportResponse,
    MudCostLineOut,
    MudCostLossReportOut,
    MudCostLossRowOut,
    MudCostMaterialBalanceOut,
    MudCostReconciliationOut,
    MudCostReconciliationRowOut,
    MudCostReconciliationSectionOut,
    MudCostReference,
    MudCostRigOption,
    MudCostSectionSettingIn,
    MudCostSectionSettingOut,
    MudCostSectionOption,
    MudCostWellOption,
)
from app.services import audit

IMPORT_MAX_ROWS = 5000


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This entry conflicts with an existing record. A well can have only one Mud Cost entry per date.",
        ) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Mud Cost Analysis could not be saved because of a database error.") from error


def _audit(
    db: Session,
    *,
    user: User,
    action: str,
    entity_type: str,
    entity_id: str | None,
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
        entity_id=entity_id,
        entity_label=entity_label,
        summary=summary,
        request=request,
    )


def _depth_text(value: Decimal | int | str) -> str:
    """Plain depth text: 0E-10 becomes 0 and 1000.0000000000 becomes 1000."""
    try:
        return format(Decimal(value).normalize(), "f")
    except (ArithmeticError, ValueError):
        return str(value)


def _section_label(
    scope: str,
    code: str,
    name: str,
    from_depth: Decimal | None = None,
    to_depth: Decimal | None = None,
) -> str:
    interval = ""
    if from_depth is not None and to_depth is not None:
        interval = f" · {_depth_text(from_depth)}–{_depth_text(to_depth)}"
    return f"{code} · {name} · {scope.title()}{interval}"


def _section_option(row: WellSection, *, depth_unit: str = "m", is_current: bool = True) -> MudCostSectionOption:
    master = row.hole_section
    code = master.section_code if master else ""
    name = master.section_name if master else ""
    from_m = depth_to_meters(row.from_depth, depth_unit) or Decimal("0.00")
    to_m = depth_to_meters(row.to_depth, depth_unit) or Decimal("0.00")
    return MudCostSectionOption(
        id=row.id,
        hole_section_id=row.hole_section_id,
        section_code=code,
        section_name=name,
        scope=row.scope,
        from_depth=from_m,
        to_depth=to_m,
        is_current=is_current,
        display_name=_section_label(row.scope, code, name, from_m, to_m),
    )


def reference_data(db: Session, organization_id: str) -> MudCostReference:
    """Active and retained rig/well options plus current and historical sections."""
    rigs = db.scalars(
        select(Rig).where(Rig.organization_id == organization_id).order_by(Rig.rig_code)
    ).all()
    wells = db.scalars(
        select(Well)
        .options(joinedload(Well.rig))
        .where(Well.organization_id == organization_id)
        .order_by(Well.well_code)
    ).unique().all()
    well_ids = [well.id for well in wells]
    current_sections = db.scalars(
        select(WellSection)
        .options(joinedload(WellSection.hole_section))
        .where(WellSection.organization_id == organization_id, WellSection.well_id.in_(well_ids or [""]))
        .order_by(WellSection.well_id, WellSection.scope, WellSection.sort_order)
    ).unique().all()
    well_by_id = {well.id: well for well in wells}
    section_options: dict[str, dict[str, MudCostSectionOption]] = defaultdict(dict)
    for section in current_sections:
        well_obj = well_by_id.get(section.well_id)
        if well_obj is not None and well_obj.scope_is_deleted(section.scope):
            continue
        unit = well_obj.scope_value(section.scope, "depth_unit") if well_obj else "m"
        section_options[section.well_id][section.id] = _section_option(section, depth_unit=unit)

    historical = db.scalars(
        select(MudCostEntry).where(MudCostEntry.organization_id == organization_id)
        .order_by(MudCostEntry.entry_date, MudCostEntry.id)
    ).all()
    for entry in historical:
        if entry.section_id in section_options[entry.well_id]:
            continue
        section_options[entry.well_id][entry.section_id] = MudCostSectionOption(
            id=entry.section_id,
            hole_section_id=entry.hole_section_id,
            section_code=entry.section_code_snapshot,
            section_name=entry.section_name_snapshot,
            scope=entry.section_scope,
            from_depth=Decimal(entry.section_from_depth),
            to_depth=Decimal(entry.section_to_depth),
            is_current=False,
            display_name=(
                _section_label(
                    entry.section_scope,
                    entry.section_code_snapshot,
                    entry.section_name_snapshot,
                    Decimal(entry.section_from_depth),
                    Decimal(entry.section_to_depth),
                ) + " · historical"
            ),
        )

    rig_options = [
        MudCostRigOption(
            id=rig.id,
            rig_code=rig.rig_code,
            rig_name=rig.rig_name,
            display_name=f"{rig.rig_code} — {rig.rig_name}" + (" · deleted" if rig.is_deleted else ""),
            is_deleted=rig.is_deleted,
        )
        for rig in rigs
    ]
    well_options = [
        MudCostWellOption(
            id=well.id,
            rig_id=well.rig_id,
            well_code=well.well_code,
            well_name=well.well_name,
            display_name=f"{well.well_code} — {well.well_name}" + (" · deleted" if well.is_deleted else ""),
            status=well.status,
            config_status=well.config_status,
            is_deleted=well.is_deleted,
            sections=list(section_options.get(well.id, {}).values()),
        )
        for well in wells
        if well.rig is not None and well.rig.organization_id == organization_id
    ]
    return MudCostReference(rigs=rig_options, wells=well_options)


def _scope_or_404(
    db: Session,
    organization_id: str,
    rig_id: str,
    well_id: str,
    section_id: str | None = None,
    *,
    allow_deleted: bool = False,
    require_current_section: bool = False,
) -> tuple[Rig, Well, WellSection | None]:
    rig = db.scalar(select(Rig).where(Rig.id == rig_id, Rig.organization_id == organization_id))
    if rig is None:
        raise HTTPException(status_code=404, detail="Rig not found in this workspace")
    well = db.scalar(
        select(Well).options(joinedload(Well.rig)).where(
            Well.id == well_id,
            Well.organization_id == organization_id,
        )
    )
    if well is None or well.rig is None or well.rig.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    if well.rig_id != rig.id:
        raise HTTPException(status_code=422, detail="Select a well that belongs to the selected rig")
    if not allow_deleted and (rig.is_deleted or well.is_deleted or well.rig.is_deleted):
        raise HTTPException(status_code=409, detail="Restore the rig and well before entering active Mud Cost data")

    section = None
    if section_id:
        section = db.scalar(
            select(WellSection)
            .options(joinedload(WellSection.hole_section))
            .where(
                WellSection.id == section_id,
                WellSection.organization_id == organization_id,
                WellSection.well_id == well.id,
            )
        )
        if section is None:
            if require_current_section:
                raise HTTPException(status_code=422, detail="Choose a section configured for this well")
            # Historical section IDs are intentionally independent snapshots. Callers
        elif not allow_deleted and well.scope_is_deleted(section.scope):
            raise HTTPException(status_code=409, detail="Restore this well scope before entering active Mud Cost data")
            # that filter old entries validate them against the retained entry rows.
        elif require_current_section and section.hole_section and section.hole_section.is_deleted:
            raise HTTPException(status_code=409, detail="Restore the section in Master Data before entering new Mud Cost data")
    return rig, well, section


def _entry_query(organization_id: str):
    return select(MudCostEntry).options(selectinload(MudCostEntry.lines)).where(
        MudCostEntry.organization_id == organization_id
    )


def _entry_or_404(
    db: Session,
    organization_id: str,
    entry_id: str,
    *,
    deleted: bool | None = False,
) -> MudCostEntry:
    statement = _entry_query(organization_id).where(MudCostEntry.id == entry_id)
    if deleted is not None:
        statement = statement.where(MudCostEntry.is_deleted.is_(deleted))
    entry = db.scalar(statement)
    if entry is None:
        raise HTTPException(status_code=404, detail="Mud Cost entry not found in this workspace")
    return entry


def _line_map(entry: MudCostEntry) -> dict[str, MudCostEntryLine]:
    return {line.line_code: line for line in entry.lines}


def _values_for_entry(entry: MudCostEntry) -> dict[str, Decimal]:
    return line_amounts({code: row.amount for code, row in _line_map(entry).items()})


def _ensure_line_rows(
    db: Session,
    entry: MudCostEntry,
    rows: Iterable[Any],
) -> None:
    incoming = {item.line_code: item for item in rows}
    existing = _line_map(entry)
    initial_opening = None
    supplied_opening = incoming.get("opening_stock")
    if "opening_stock" in existing and supplied_opening is not None and supplied_opening.amount is not None:
        raise HTTPException(
            status_code=409,
            detail=("Opening stock can only be corrected on the first active entry of the section "
                    "using Edit opening stock. Daily entry edits use the calculated carry-forward."),
        )
    if "opening_stock" not in existing:
        # Once this scope has an opening, even a back-dated insert must reuse it.
        peers = [row for row in _entries_for_section(db, entry.organization_id, entry.section_id)
                 if row.id != entry.id and row.rig_id == entry.rig_id and row.well_id == entry.well_id]
        if peers:
            initial_opening = _line_map(peers[0]).get("opening_stock")
            if supplied_opening is not None and supplied_opening.amount is not None:
                raise HTTPException(
                    status_code=409,
                    detail=("Opening stock has already been entered for this section. Leave it blank; "
                            "this day's opening is calculated from the preceding closing stock."),
                )
    for sort_order, spec in enumerate(MUD_COST_LINE_SPECS):
        if spec.code == "opening_stock" and spec.code in existing:
            continue  # Saved openings are owned by the carry-forward calculation.
        input_row = incoming.get(spec.code)
        amount = ZERO if input_row is None or input_row.amount is None else Decimal(input_row.amount)
        remarks = "" if input_row is None else input_row.remarks.strip()
        if spec.code == "opening_stock" and initial_opening is not None:
            amount, remarks = initial_opening.amount, initial_opening.remarks
        line = existing.get(spec.code)
        if line is None:
            line = MudCostEntryLine(
                organization_id=entry.organization_id,
                entry_id=entry.id,
                line_code=spec.code,
                category=spec.category,
                line_label=spec.label,
                amount=amount,
                remarks=remarks,
                sort_order=sort_order,
            )
            entry.lines.append(line)
        else:
            line.category = spec.category
            line.line_label = spec.label
            line.amount = amount
            line.remarks = remarks
            line.sort_order = sort_order
            line.updated_at = now()


def _entries_for_section(
    db: Session,
    organization_id: str,
    section_id: str,
    *,
    deleted: bool = False,
) -> list[MudCostEntry]:
    return list(db.scalars(
        _entry_query(organization_id)
        .where(MudCostEntry.section_id == section_id, MudCostEntry.is_deleted.is_(deleted))
        .order_by(MudCostEntry.entry_date, MudCostEntry.id)
    ).unique().all())


def _recalculate_section_opening_stock(db: Session, organization_id: str, section_id: str) -> None:
    """Persist calculated carry-forward, including across days without transactions."""
    entries = _entries_for_section(db, organization_id, section_id, deleted=False)
    balances = _balance_values(entries)
    for entry in entries:
        opening = _line_map(entry).get("opening_stock")
        if opening is not None:
            opening.amount = balances[entry.id]["opening_stock"]
            opening.remarks = balances[entry.id]["opening_stock_remarks"]
            opening.updated_at = now()
    db.flush()


def _balance_values(entries: Iterable[MudCostEntry]) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[MudCostEntry]] = defaultdict(list)
    for entry in entries:
        grouped[(entry.rig_id, entry.well_id, entry.section_id)].append(entry)
    result: dict[str, dict[str, Any]] = {}
    for section_entries in grouped.values():
        section_entries.sort(key=lambda item: (item.entry_date, item.id))
        previous_closing: Decimal | None = None
        for entry in section_entries:
            lines = _line_map(entry)
            raw = _values_for_entry(entry)
            if previous_closing is None:
                opening = raw["opening_stock"]
                opening_remarks = lines.get("opening_stock").remarks if lines.get("opening_stock") else ""
            else:
                opening = previous_closing
                opening_remarks = ""
            receipt = group_total(raw, "receipt")
            additions = group_total(raw, "additions")
            consumption_losses = group_total(raw, "consumption_losses")
            others = group_total(raw, "others")
            closing = closing_stock(opening, receipt, additions, consumption_losses, others)
            result[entry.id] = {
                "opening_stock": opening,
                "opening_stock_remarks": opening_remarks,
                "receipt": receipt,
                "additions": additions,
                "consumption_losses": consumption_losses,
                "others": others,
                "closing_stock": closing,
            }
            previous_closing = closing
    return result


def _entry_label(entry: MudCostEntry) -> str:
    return f"{entry.well_code_snapshot} · {entry.entry_date.isoformat()} · {entry.section_code_snapshot}"


def _entry_out(entry: MudCostEntry, balance: Mapping[str, Any] | None = None) -> MudCostEntryOut:
    raw = _values_for_entry(entry)
    if balance is None:
        opening = raw["opening_stock"]
        opening_line = _line_map(entry).get("opening_stock")
        opening_remarks = opening_line.remarks if opening_line else ""
        receipt = group_total(raw, "receipt")
        additions = group_total(raw, "additions")
        consumption_losses = group_total(raw, "consumption_losses")
        others = group_total(raw, "others")
        closing = closing_stock(opening, receipt, additions, consumption_losses, others)
    else:
        opening = balance["opening_stock"]
        opening_remarks = balance["opening_stock_remarks"]
        receipt = balance["receipt"]
        additions = balance["additions"]
        consumption_losses = balance["consumption_losses"]
        others = balance["others"]
        closing = balance["closing_stock"]

    lines = []
    line_rows = _line_map(entry)
    for sort_order, spec in enumerate(MUD_COST_LINE_SPECS):
        line = line_rows.get(spec.code)
        amount = Decimal(line.amount) if line else ZERO
        remarks = line.remarks if line else ""
        if spec.code == "opening_stock":
            amount = opening
            remarks = opening_remarks
        lines.append(MudCostLineOut(
            line_code=spec.code,
            category=spec.category,
            label=spec.label,
            amount=amount,
            remarks=remarks,
            sort_order=sort_order,
        ))

    return MudCostEntryOut(
        id=entry.id,
        rig_id=entry.rig_id,
        rig_code=entry.rig_code_snapshot,
        rig_name=entry.rig_name_snapshot,
        well_id=entry.well_id,
        well_code=entry.well_code_snapshot,
        well_name=entry.well_name_snapshot,
        section_id=entry.section_id,
        hole_section_id=entry.hole_section_id,
        section_scope=entry.section_scope,
        section_code=entry.section_code_snapshot,
        section_name=entry.section_name_snapshot,
        section_label=_section_label(
            entry.section_scope, entry.section_code_snapshot, entry.section_name_snapshot,
            Decimal(entry.section_from_depth), Decimal(entry.section_to_depth),
        ),
        section_from_depth=Decimal(entry.section_from_depth),
        section_to_depth=Decimal(entry.section_to_depth),
        entry_date=entry.entry_date,
        opening_stock=opening,
        opening_stock_remarks=opening_remarks,
        receipt=receipt,
        additions=additions,
        consumption_losses=consumption_losses,
        others=others,
        closing_stock=closing,
        lines=lines,
        is_deleted=entry.is_deleted,
        deleted_at=entry.deleted_at,
        created_by=entry.created_by,
        updated_by=entry.updated_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _create_entry_record(
    db: Session,
    organization_id: str,
    data: MudCostEntryCreate,
    user: User,
    request: Request | None,
    *,
    action: str = "create",
) -> MudCostEntry:
    rig, well, section = _scope_or_404(
        db, organization_id, data.rig_id, data.well_id, data.section_id,
        require_current_section=True,
    )
    if section is None or section.hole_section is None:
        raise HTTPException(status_code=422, detail="Choose a current section configured for this well")
    duplicate = db.scalar(select(MudCostEntry.id).where(
        MudCostEntry.organization_id == organization_id,
        MudCostEntry.well_id == well.id,
        MudCostEntry.entry_date == data.entry_date,
    ))
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=f"A Mud Cost entry already exists for {well.well_code} on {data.entry_date.isoformat()}. Open or restore that entry instead.",
        )
    entry = MudCostEntry(
        organization_id=organization_id,
        rig_id=rig.id,
        rig_code_snapshot=rig.rig_code,
        rig_name_snapshot=rig.rig_name,
        well_id=well.id,
        well_code_snapshot=well.well_code,
        well_name_snapshot=well.well_name,
        section_id=section.id,
        hole_section_id=section.hole_section_id,
        section_scope=section.scope,
        section_code_snapshot=section.hole_section.section_code,
        section_name_snapshot=section.hole_section.section_name,
        section_from_depth=depth_to_meters(section.from_depth, well.scope_value(section.scope, "depth_unit")) or Decimal("0.00"),
        section_to_depth=depth_to_meters(section.to_depth, well.scope_value(section.scope, "depth_unit")) or Decimal("0.00"),
        entry_date=data.entry_date,
        created_by=user.email,
        updated_by=user.email,
    )
    db.add(entry)
    db.flush()
    _ensure_line_rows(db, entry, data.lines)
    db.flush()
    _recalculate_section_opening_stock(db, organization_id, section.id)
    label = _entry_label(entry)
    verb = "Created" if action == "create" else "Imported"
    _audit(
        db,
        user=user,
        action=action,
        entity_type="mud_cost_entry",
        entity_id=entry.id,
        entity_label=label,
        summary=f"{verb} Mud Cost entry for {well.well_code} on {data.entry_date.isoformat()} in {entry.section_code_snapshot}",
        request=request,
    )
    return entry


def create_entry(
    db: Session,
    organization_id: str,
    data: MudCostEntryCreate,
    user: User,
    request: Request | None,
) -> MudCostEntryOut:
    entry = _create_entry_record(db, organization_id, data, user, request)
    _commit(db)
    return get_entry(db, organization_id, entry.id)


def get_entry(db: Session, organization_id: str, entry_id: str) -> MudCostEntryOut:
    entry = _entry_or_404(db, organization_id, entry_id, deleted=False)
    active = _entries_for_section(db, organization_id, entry.section_id)
    balances = _balance_values(active)
    return _entry_out(entry, balances.get(entry.id))


def update_opening_stock(
    db: Session,
    organization_id: str,
    entry_id: str,
    data: MudCostOpeningStockIn,
    user: User,
    request: Request | None,
) -> MudCostEntryOut:
    """Correct only the initial inventory, never a daily carry-forward balance."""
    entry = _entry_or_404(db, organization_id, entry_id, deleted=False)
    peers = _entries_for_section(db, organization_id, entry.section_id)
    if not peers or peers[0].id != entry.id:
        raise HTTPException(status_code=409, detail="Edit opening stock on the first active entry of this section. Later openings are calculated from closing stock.")
    opening = _line_map(entry)["opening_stock"]
    old_amount = opening.amount
    old_remarks = opening.remarks
    opening.amount = data.amount
    opening.remarks = data.remarks.strip()
    entry.updated_by = user.email
    entry.updated_at = now()
    db.flush()
    _recalculate_section_opening_stock(db, organization_id, entry.section_id)
    _audit(
        db, user=user, action="update", entity_type="mud_cost_opening_stock",
        entity_id=entry.id, entity_label=_entry_label(entry),
        summary=(f"Corrected initial opening stock for {entry.well_code_snapshot} / "
                 f"{entry.section_code_snapshot} from {old_amount} to {data.amount}; "
                 f"remarks: {old_remarks!r} -> {opening.remarks!r}; recalculated section balances"),
        request=request,
    )
    _commit(db)
    return get_entry(db, organization_id, entry.id)


def get_deleted_entry(db: Session, organization_id: str, entry_id: str) -> MudCostEntryOut:
    entry = _entry_or_404(db, organization_id, entry_id, deleted=True)
    return _entry_out(entry)


def update_entry(
    db: Session,
    organization_id: str,
    entry_id: str,
    data: MudCostEntryUpdate,
    user: User,
    request: Request | None,
) -> MudCostEntryOut:
    entry = _entry_or_404(db, organization_id, entry_id, deleted=False)
    duplicate = db.scalar(select(MudCostEntry.id).where(
        MudCostEntry.organization_id == organization_id,
        MudCostEntry.well_id == entry.well_id,
        MudCostEntry.entry_date == data.entry_date,
        MudCostEntry.id != entry.id,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="A Mud Cost entry already exists for this well and date")
    old_date = entry.entry_date
    entry.entry_date = data.entry_date
    entry.updated_by = user.email
    entry.updated_at = now()
    _ensure_line_rows(db, entry, data.lines)
    db.flush()
    _recalculate_section_opening_stock(db, organization_id, entry.section_id)
    changed_rows = sum(
        1 for line in entry.lines
        if line.line_code in {item.line_code for item in data.lines}
    )
    _audit(
        db,
        user=user,
        action="update",
        entity_type="mud_cost_entry",
        entity_id=entry.id,
        entity_label=_entry_label(entry),
        summary=(
            f"Updated Mud Cost entry for {entry.well_code_snapshot}; date "
            f"{old_date.isoformat()} → {entry.entry_date.isoformat()}; {changed_rows} configured rows saved"
        ),
        request=request,
    )
    _commit(db)
    return get_entry(db, organization_id, entry.id)


def _entries_for_well(
    db: Session,
    organization_id: str,
    well_id: str,
    *,
    deleted: bool = False,
) -> list[MudCostEntry]:
    return list(db.scalars(
        _entry_query(organization_id)
        .where(MudCostEntry.well_id == well_id, MudCostEntry.is_deleted.is_(deleted))
        .order_by(MudCostEntry.entry_date, MudCostEntry.section_id, MudCostEntry.id)
    ).unique().all())


def list_entries(
    db: Session,
    organization_id: str,
    *,
    rig_id: str = "",
    well_id: str = "",
    section_id: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    deleted: bool = False,
) -> list[MudCostEntryOut]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    if rig_id and well_id:
        _scope_or_404(db, organization_id, rig_id, well_id, allow_deleted=deleted)
    statement = _entry_query(organization_id).where(MudCostEntry.is_deleted.is_(deleted))
    if rig_id:
        statement = statement.where(MudCostEntry.rig_id == rig_id)
    if well_id:
        statement = statement.where(MudCostEntry.well_id == well_id)
    if section_id:
        statement = statement.where(MudCostEntry.section_id == section_id)
    if date_from:
        statement = statement.where(MudCostEntry.entry_date >= date_from)
    if date_to:
        statement = statement.where(MudCostEntry.entry_date <= date_to)
    records = list(db.scalars(statement.order_by(MudCostEntry.entry_date.desc(), MudCostEntry.section_id)).unique().all())
    if deleted:
        return [_entry_out(entry) for entry in records]

    if well_id:
        all_active = _entries_for_well(db, organization_id, well_id, deleted=False)
    else:
        # The browser normally scopes to one well, but the API still handles an
        # unfiltered authorized list without deriving across tenant boundaries.
        all_active = list(db.scalars(
            _entry_query(organization_id).where(MudCostEntry.is_deleted.is_(False))
            .order_by(MudCostEntry.entry_date, MudCostEntry.section_id)
        ).unique().all())
    balances = _balance_values(all_active)
    return [_entry_out(entry, balances.get(entry.id)) for entry in records]


def _persisted_balance_row(entry: MudCostEntry, balance: Mapping[str, Any]) -> MudCostBalanceRowOut:
    section_label = _section_label(
        entry.section_scope,
        entry.section_code_snapshot,
        entry.section_name_snapshot,
        Decimal(entry.section_from_depth),
        Decimal(entry.section_to_depth),
    )
    return MudCostBalanceRowOut(
        id=entry.id,
        rig_id=entry.rig_id,
        rig_code=entry.rig_code_snapshot,
        well_id=entry.well_id,
        well_code=entry.well_code_snapshot,
        section_id=entry.section_id,
        section_scope=entry.section_scope,
        section_code=entry.section_code_snapshot,
        section_name=entry.section_name_snapshot,
        section_label=section_label,
        period_label=entry.entry_date.isoformat(),
        cost_date=entry.entry_date,
        first_entry_date=entry.entry_date,
        last_entry_date=entry.entry_date,
        entry_count=1,
        opening_stock=balance["opening_stock"],
        receipt=balance["receipt"],
        additions=balance["additions"],
        consumption_losses=balance["consumption_losses"],
        others=balance["others"],
        closing_stock=balance["closing_stock"],
    )


def _aggregate_balance_rows(
    daily_rows: list[MudCostBalanceRowOut],
    view: str,
) -> list[MudCostBalanceRowOut]:
    if view == "daily":
        return daily_rows
    groups: dict[tuple[str, str], list[MudCostBalanceRowOut]] = defaultdict(list)
    for row in daily_rows:
        period = row.cost_date.strftime("%Y-%m") if view == "monthly" else "all"
        groups[(row.section_id, period)].append(row)

    output: list[MudCostBalanceRowOut] = []
    for (section_id, period), rows in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        rows.sort(key=lambda row: (row.cost_date, row.id))
        first, last = rows[0], rows[-1]
        receipt = sum((row.receipt for row in rows), ZERO)
        additions = sum((row.additions for row in rows), ZERO)
        consumption_losses = sum((row.consumption_losses for row in rows), ZERO)
        others = sum((row.others for row in rows), ZERO)
        opening = first.opening_stock
        closing = closing_stock(opening, receipt, additions, consumption_losses, others)
        if view == "monthly":
            month_date = date(first.cost_date.year, first.cost_date.month, 1)
            period_label = month_date.strftime("%B %Y")
            row_id = f"{section_id}:month:{period}"
        elif view == "inception":
            period_label = f"Inception · {first.cost_date.isoformat()} to {last.cost_date.isoformat()}"
            row_id = f"{section_id}:inception"
        else:
            period_label = f"Section total · {first.cost_date.isoformat()} to {last.cost_date.isoformat()}"
            row_id = f"{section_id}:section"
        output.append(MudCostBalanceRowOut(
            id=row_id,
            rig_id=first.rig_id,
            rig_code=first.rig_code,
            well_id=first.well_id,
            well_code=first.well_code,
            section_id=first.section_id,
            section_scope=first.section_scope,
            section_code=first.section_code,
            section_name=first.section_name,
            section_label=first.section_label,
            period_label=period_label,
            cost_date=first.cost_date,
            first_entry_date=first.cost_date,
            last_entry_date=last.cost_date,
            entry_count=sum(row.entry_count for row in rows),
            opening_stock=opening,
            receipt=receipt,
            additions=additions,
            consumption_losses=consumption_losses,
            others=others,
            closing_stock=closing,
        ))
    return output


def material_balance(
    db: Session,
    organization_id: str,
    *,
    rig_id: str,
    well_id: str,
    section_id: str = "",
    view: str = "daily",
    date_from: date | None = None,
    date_to: date | None = None,
) -> MudCostMaterialBalanceOut:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    rig, well, _ = _scope_or_404(db, organization_id, rig_id, well_id)
    if section_id:
        current_section = db.scalar(select(WellSection.id).where(
            WellSection.id == section_id,
            WellSection.organization_id == organization_id,
            WellSection.well_id == well_id,
        ))
        historical_section = db.scalar(select(MudCostEntry.id).where(
            MudCostEntry.organization_id == organization_id,
            MudCostEntry.well_id == well_id,
            MudCostEntry.section_id == section_id,
        ).limit(1))
        if not current_section and not historical_section:
            raise HTTPException(status_code=404, detail="Section not found for this well")

    entries = _entries_for_well(db, organization_id, well_id, deleted=False)
    if any(entry.rig_id != rig.id for entry in entries):
        # Historical rig snapshots are retained, but a well cannot be re-assigned
        # while Mud Cost records exist. This guard catches inconsistent legacy data.
        entries = [entry for entry in entries if entry.rig_id == rig.id]
    balances = _balance_values(entries)
    daily_rows = [
        _persisted_balance_row(entry, balances[entry.id])
        for entry in entries
        if entry.id in balances and (not section_id or entry.section_id == section_id)
    ]
    if view != "inception":
        if date_from:
            daily_rows = [row for row in daily_rows if row.cost_date >= date_from]
    if date_to:
        daily_rows = [row for row in daily_rows if row.cost_date <= date_to]
    rows = _aggregate_balance_rows(daily_rows, view)
    rows.sort(key=lambda row: (row.section_label.casefold(), row.cost_date, row.period_label))
    return MudCostMaterialBalanceOut(
        view=view,
        from_date=None if view == "inception" else date_from,
        to_date=date_to,
        selected_section_count=len({row.section_id for row in rows}),
        entry_count=sum(row.entry_count for row in rows),
        rows=rows,
    )


_LOSS_VALUE_FIELDS = tuple(code for code, _label, _sources in MUD_LOSS_REPORT_LINES) + (
    "surface_loss_total", "other_loss_total", "total_losses",
)


def _loss_values_for_entries(entries: Iterable[MudCostEntry]) -> dict[str, Decimal]:
    totals = {field: ZERO for field in _LOSS_VALUE_FIELDS}
    for entry in entries:
        values = loss_breakdown(_values_for_entry(entry))
        for field in _LOSS_VALUE_FIELDS:
            totals[field] += values[field]
    return {field: _recon_amount(value) for field, value in totals.items()}


def _loss_row_for_entry(
    entry: MudCostEntry, setting: MudCostSectionSetting | None,
) -> MudCostLossRowOut:
    values = _loss_values_for_entries([entry])
    mud_type = setting.mud_type if setting else None
    section_label = _section_label(
        entry.section_scope, entry.section_code_snapshot, entry.section_name_snapshot,
        Decimal(entry.section_from_depth), Decimal(entry.section_to_depth),
    )
    return MudCostLossRowOut(
        id=entry.id,
        period_label=entry.entry_date.isoformat(),
        cost_date=entry.entry_date,
        first_entry_date=entry.entry_date,
        last_entry_date=entry.entry_date,
        entry_count=1,
        rig_id=entry.rig_id,
        rig_code=entry.rig_code_snapshot,
        rig_name=entry.rig_name_snapshot,
        well_id=entry.well_id,
        well_code=entry.well_code_snapshot,
        well_name=entry.well_name_snapshot,
        section_id=setting.section_id if setting else entry.section_id,
        hole_section_id=entry.hole_section_id,
        section_scope=entry.section_scope,
        section_code=entry.section_code_snapshot,
        section_name=entry.section_name_snapshot,
        section_label=section_label,
        mud_type=mud_type,
        mud_type_label=MUD_COST_MUD_TYPE_LABELS.get(mud_type or "", "Not configured"),
        **values,
    )


def _aggregate_loss_rows(rows: list[MudCostLossRowOut], view: str) -> list[MudCostLossRowOut]:
    if view == "daily":
        return rows
    groups: dict[tuple[str, str, str], list[MudCostLossRowOut]] = defaultdict(list)
    for row in rows:
        period = row.cost_date.strftime("%Y-%m") if view == "monthly" else "all"
        groups[(row.section_scope, row.hole_section_id, period)].append(row)
    output: list[MudCostLossRowOut] = []
    for (scope, hole_section_id, period), members in sorted(groups.items()):
        members.sort(key=lambda item: (item.cost_date, item.id))
        first, last = members[0], members[-1]
        values = {
            field: _recon_amount(sum((getattr(row, field) for row in members), ZERO))
            for field in _LOSS_VALUE_FIELDS
        }
        if view == "monthly":
            month_date = date(first.cost_date.year, first.cost_date.month, 1)
            label = month_date.strftime("%B %Y")
            row_id = f"{scope}:{hole_section_id}:month:{period}"
            cost_date = month_date
        elif view == "inception":
            label = f"Inception · {first.cost_date.isoformat()} to {last.cost_date.isoformat()}"
            row_id = f"{scope}:{hole_section_id}:inception"
            cost_date = first.cost_date
        else:
            label = f"Selected range · {first.cost_date.isoformat()} to {last.cost_date.isoformat()}"
            row_id = f"{scope}:{hole_section_id}:section"
            cost_date = first.cost_date
        output.append(MudCostLossRowOut(
            **first.model_dump(exclude={*_LOSS_VALUE_FIELDS, "id", "period_label", "cost_date", "first_entry_date", "last_entry_date", "entry_count"}),
            id=row_id,
            period_label=label,
            cost_date=cost_date,
            first_entry_date=first.cost_date,
            last_entry_date=last.cost_date,
            entry_count=sum(row.entry_count for row in members),
            **values,
        ))
    return output


def consumption_loss_report(
    db: Session,
    organization_id: str,
    *,
    rig_id: str,
    well_id: str,
    section_id: str = "",
    view: str = "daily",
    date_from: date | None = None,
    date_to: date | None = None,
) -> MudCostLossReportOut:
    """Loss matrix and date/month/section drill rows from the normalized ledger."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    rig, well, selected_section = _scope_or_404(
        db, organization_id, rig_id, well_id, section_id or None,
    )
    if section_id and selected_section is None:
        historical_section = db.scalar(select(MudCostEntry.id).where(
            MudCostEntry.organization_id == organization_id,
            MudCostEntry.well_id == well.id,
            MudCostEntry.section_id == section_id,
        ).limit(1))
        if historical_section is None:
            raise HTTPException(status_code=404, detail="Section not found for this well")
    settings = _setting_map(db, organization_id, well.id)
    entries = [
        entry for entry in _entries_for_well(db, organization_id, well.id, deleted=False)
        if entry.rig_id == rig.id
    ]
    if section_id:
        entries = [
            entry for entry in entries
            if entry.section_id == section_id
            or (settings.get(_setting_key(entry.section_scope, entry.hole_section_id)) is not None
                and settings[_setting_key(entry.section_scope, entry.hole_section_id)].section_id == section_id)
        ]
    if view != "inception" and date_from:
        entries = [entry for entry in entries if entry.entry_date >= date_from]
    if date_to:
        entries = [entry for entry in entries if entry.entry_date <= date_to]
    daily = [
        _loss_row_for_entry(entry, settings.get(_setting_key(entry.section_scope, entry.hole_section_id)))
        for entry in entries
    ]
    rows = _aggregate_loss_rows(daily, view)
    rows.sort(key=lambda row: (row.section_scope, row.section_label.casefold(), row.cost_date, row.period_label))
    return MudCostLossReportOut(
        view=view,
        from_date=None if view == "inception" else date_from,
        to_date=date_to,
        selected_section_count=len({(row.section_scope, row.hole_section_id) for row in rows}),
        entry_count=sum(row.entry_count for row in rows),
        surface_loss_total=_recon_amount(sum((row.surface_loss_total for row in rows), ZERO)),
        other_loss_total=_recon_amount(sum((row.other_loss_total for row in rows), ZERO)),
        total_losses=_recon_amount(sum((row.total_losses for row in rows), ZERO)),
        rows=rows,
    )


def _normalise_import_row(row: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        normalized = str(key or "").strip().lower().replace("/", "_").replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        if normalized:
            output[normalized] = value
    return output


def _import_entry_payload(
    raw: Mapping[str, Any],
    *,
    rig_id: str,
    well_id: str,
    section_id: str,
) -> MudCostEntryCreate:
    row = _normalise_import_row(raw)
    entry_date = row.get("entry_date") or row.get("cost_date") or row.get("date")
    lines = []
    for spec in MUD_COST_LINE_SPECS:
        if spec.code == "opening_stock":
            amount = row.get("opening_stock")
            remarks = row.get("opening_stock_remarks", row.get("opening_stock_remark", ""))
        else:
            amount = row.get(spec.code)
            remarks = row.get(f"{spec.code}_remarks", row.get(f"{spec.code}_remark", ""))
        lines.append({"line_code": spec.code, "amount": amount, "remarks": remarks or ""})
    return MudCostEntryCreate.model_validate({
        "rig_id": rig_id,
        "well_id": well_id,
        "section_id": section_id,
        "entry_date": entry_date,
        "lines": lines,
    })


def _validation_detail(error: ValidationError) -> str:
    return "; ".join(
        ".".join(str(part) for part in issue["loc"]) + f": {issue['msg']}"
        for issue in error.errors()
    )


def import_entries(
    db: Session,
    organization_id: str,
    data: MudCostImportRequest,
    user: User,
    request: Request | None,
) -> MudCostImportResponse:
    if len(data.rows) > IMPORT_MAX_ROWS:
        raise HTTPException(status_code=422, detail=f"Import is limited to {IMPORT_MAX_ROWS} rows")
    _scope_or_404(db, organization_id, data.rig_id, data.well_id, data.section_id, require_current_section=True)
    parsed: list[tuple[int, MudCostEntryCreate]] = []
    errors: list[str] = []
    for number, raw in enumerate(data.rows, start=1):
        try:
            parsed.append((number, _import_entry_payload(
                raw, rig_id=data.rig_id, well_id=data.well_id, section_id=data.section_id,
            )))
        except ValidationError as error:
            errors.append(f"Row {number}: {_validation_detail(error)}")
        except (ValueError, TypeError) as error:
            errors.append(f"Row {number}: {error}")

    imported_count = 0
    # Import in date order so the first section entry captures its initial stock,
    # regardless of the order rows happened to appear in the workbook.
    for number, payload in sorted(parsed, key=lambda item: (item[1].entry_date, item[0])):
        try:
            with db.begin_nested():
                _create_entry_record(db, organization_id, payload, user, request, action="import")
                db.flush()
            imported_count += 1
        except HTTPException as error:
            errors.append(f"Row {number}: {error.detail}")
        except IntegrityError:
            errors.append(f"Row {number}: a well/date entry already exists")
        except SQLAlchemyError:
            errors.append(f"Row {number}: the row could not be saved")

    _audit(
        db,
        user=user,
        action="import",
        entity_type="mud_cost_import",
        entity_id=None,
        entity_label=f"{data.well_id} / {data.section_id}",
        summary=f"Imported {imported_count} Mud Cost row(s); {len(errors)} row error(s)",
        request=request,
    )
    _commit(db)
    return MudCostImportResponse(
        imported_count=imported_count,
        error_count=len(errors),
        errors=errors,
        success=not errors,
    )


def _records_for_ids(
    db: Session,
    organization_id: str,
    ids: list[str],
    *,
    deleted: bool,
) -> list[MudCostEntry]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Select each Mud Cost entry only once")
    records = list(db.scalars(
        _entry_query(organization_id).where(MudCostEntry.id.in_(ids))
    ).unique().all())
    if len(records) != len(ids):
        raise HTTPException(status_code=404, detail="One or more entries do not belong to this workspace")
    if any(entry.is_deleted is not deleted for entry in records):
        state = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"This bulk action requires only {state} Mud Cost entries")
    return records


def _recalculate_sections(db: Session, organization_id: str, entries: Iterable[MudCostEntry]) -> None:
    section_ids = {entry.section_id for entry in entries}
    for section_id in section_ids:
        _recalculate_section_opening_stock(db, organization_id, section_id)


def soft_delete_entries(
    db: Session,
    organization_id: str,
    ids: list[str],
    user: User,
    request: Request | None,
) -> int:
    records = _records_for_ids(db, organization_id, ids, deleted=False)
    deleted_at = now()
    for entry in records:
        entry.is_deleted = True
        entry.deleted_at = deleted_at
        entry.updated_by = user.email
        _audit(
            db, user=user, action="soft_delete", entity_type="mud_cost_entry", entity_id=entry.id,
            entity_label=_entry_label(entry), summary=f"Moved Mud Cost entry {_entry_label(entry)} to Deleted Entries",
            request=request,
        )
    db.flush()
    _recalculate_sections(db, organization_id, records)
    _audit(
        db, user=user, action="delete", entity_type="mud_cost_entry", entity_id=None,
        entity_label="Mud Cost Analysis entries",
        summary=f"Moved {len(records)} Mud Cost entry/entries to Deleted Entries",
        request=request,
    )
    _commit(db)
    return len(records)


def restore_entries(
    db: Session,
    organization_id: str,
    ids: list[str],
    user: User,
    request: Request | None,
) -> int:
    records = _records_for_ids(db, organization_id, ids, deleted=True)
    for entry in records:
        rig = db.scalar(select(Rig).where(Rig.id == entry.rig_id, Rig.organization_id == organization_id))
        well = db.scalar(select(Well).where(Well.id == entry.well_id, Well.organization_id == organization_id))
        if rig is None or well is None or rig.is_deleted or well.is_deleted:
            raise HTTPException(status_code=409, detail=f"Restore rig and well before restoring {_entry_label(entry)}")
    for entry in records:
        entry.is_deleted = False
        entry.deleted_at = None
        entry.updated_by = user.email
        entry.updated_at = now()
        _audit(
            db, user=user, action="restore", entity_type="mud_cost_entry", entity_id=entry.id,
            entity_label=_entry_label(entry), summary=f"Restored Mud Cost entry {_entry_label(entry)}",
            request=request,
        )
    db.flush()
    _recalculate_sections(db, organization_id, records)
    _audit(
        db, user=user, action="restore", entity_type="mud_cost_entry", entity_id=None,
        entity_label="Mud Cost Analysis entries", summary=f"Restored {len(records)} Mud Cost entry/entries",
        request=request,
    )
    _commit(db)
    return len(records)


def permanently_delete_entries(
    db: Session,
    organization_id: str,
    ids: list[str],
    user: User,
    request: Request | None,
) -> int:
    records = _records_for_ids(db, organization_id, ids, deleted=True)
    affected_sections = {entry.section_id for entry in records}
    for entry in records:
        _audit(
            db, user=user, action="permanent_delete", entity_type="mud_cost_entry", entity_id=entry.id,
            entity_label=_entry_label(entry), summary=f"Permanently deleted Mud Cost entry {_entry_label(entry)}",
            request=request,
        )
        db.delete(entry)
    db.flush()
    # If a purged record supplied the stored starting opening of a later active
    # row, that row already retains its last opening snapshot. Recalculation uses
    # that row's retained value when it becomes the first active record.
    for section_id in affected_sections:
        _recalculate_section_opening_stock(db, organization_id, section_id)
    _audit(
        db, user=user, action="permanent_delete", entity_type="mud_cost_entry", entity_id=None,
        entity_label="Mud Cost Analysis entries",
        summary=f"Permanently deleted {len(records)} Mud Cost entry/entries",
        request=request,
    )
    _commit(db)
    return len(records)


def record_export(db: Session, user: User, data: MudCostExportAudit, request: Request | None) -> None:
    module_label = {
        "entries": "daily entries", "deleted": "deleted entries",
        "material_balance": "material balance", "reconciliation": "mud cost reconciliation",
        "consumption_losses": "consumption and losses",
    }[data.module]
    scope = ", ".join(value for value in (data.rig_id, data.well_id, data.section_id) if value) or "all scopes"
    _audit(
        db,
        user=user,
        action="export",
        entity_type="mud_cost_export",
        entity_id=None,
        entity_label="Mud Cost Analysis",
        summary=(
            f"Exported {data.record_count} {module_label} row(s) as {data.format.upper()} for {scope}; "
            f"view={data.view or 'list'}; dates={data.date_from or 'start'} to {data.date_to or 'today'}"
        ),
        request=request,
    )
    _commit(db)


def record_print(db: Session, user: User, data: MudCostExportAudit, request: Request | None) -> None:
    if data.format != "print":
        raise HTTPException(status_code=422, detail="Print audit requests must use the print format")
    record_export(db, user, data, request)


# ---------------------------------------------------------------------------
# Section-scoped mud configuration and reconciliation
# ---------------------------------------------------------------------------
RECONCILIATION_QUANT = Decimal("0.0000000001")
MUD_CHEMICAL_CATEGORY = "Mud Chemicals"


def _recon_amount(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(RECONCILIATION_QUANT)


def _setting_key(scope: str, hole_section_id: str) -> tuple[str, str]:
    return scope, hole_section_id


def _setting_map(db: Session, organization_id: str, well_id: str) -> dict[tuple[str, str], MudCostSectionSetting]:
    rows = db.scalars(
        select(MudCostSectionSetting).where(
            MudCostSectionSetting.organization_id == organization_id,
            MudCostSectionSetting.well_id == well_id,
        )
    ).all()
    return {_setting_key(row.section_scope, row.hole_section_id): row for row in rows}


def _workspace_currency(db: Session, organization_id: str) -> str:
    """The workspace default currency, then any active currency, then USD."""
    default = db.scalar(select(Currency.currency_code).where(
        Currency.organization_id == organization_id,
        Currency.is_default.is_(True),
        Currency.is_deleted.is_(False),
    ))
    if default:
        return str(default)
    fallback = db.scalar(select(Currency.currency_code).where(
        Currency.organization_id == organization_id,
        Currency.is_deleted.is_(False),
    ).order_by(Currency.currency_code))
    return str(fallback or "USD")


def well_standard_currency(db: Session, organization_id: str, well_id: str, *, strict: bool = True) -> str:
    """The AFE standard currency every daily sheet on this well uses.

    Mud reconciliation values the actual mud chemicals in the same currency as
    the daily register. A well whose AFEs use different standard currencies has
    no single comparable figure, so the caller is told to fix that instead of
    silently adding unlike amounts.
    """
    currencies = {
        str(value) for value in db.scalars(select(DailyCostEntry.standard_currency).where(
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.well_id == well_id,
            DailyCostEntry.is_deleted.is_(False),
        )).all()
        if value
    }
    if len(currencies) > 1 and strict:
        raise HTTPException(status_code=409, detail=(
            "This well has daily cost sheets in different standard currencies. "
            "Mud cost reconciliation cannot combine them; align the AFE standard currency first."
        ))
    if len(currencies) == 1:
        return next(iter(currencies))
    return _workspace_currency(db, organization_id)


def section_settings(
    db: Session,
    organization_id: str,
    rig_id: str,
    well_id: str,
) -> list[MudCostSectionSettingOut]:
    """Every configured section plus current sections that still need setup."""
    rig, well, _ = _scope_or_404(db, organization_id, rig_id, well_id, allow_deleted=True)
    currency = well_standard_currency(db, organization_id, well_id, strict=False)
    settings = _setting_map(db, organization_id, well_id)
    current_sections = db.scalars(
        select(WellSection)
        .options(joinedload(WellSection.hole_section))
        .where(WellSection.organization_id == organization_id, WellSection.well_id == well_id)
        .order_by(WellSection.scope, WellSection.sort_order)
    ).unique().all()
    rows: list[MudCostSectionSettingOut] = []
    seen: set[tuple[str, str]] = set()
    for section in current_sections:
        key = _setting_key(section.scope, section.hole_section_id)
        seen.add(key)
        master = section.hole_section
        code = master.section_code if master else ""
        name = master.section_name if master else ""
        from_m = depth_to_meters(section.from_depth, well.scope_value(section.scope, "depth_unit")) or Decimal("0")
        to_m = depth_to_meters(section.to_depth, well.scope_value(section.scope, "depth_unit")) or Decimal("0")
        setting = settings.get(key)
        rows.append(MudCostSectionSettingOut(
            id=setting.id if setting else None,
            rig_id=rig.id,
            rig_code=rig.rig_code,
            well_id=well.id,
            well_code=well.well_code,
            section_id=section.id,
            hole_section_id=section.hole_section_id,
            section_scope=section.scope,
            section_code=code,
            section_name=name,
            section_label=_section_label(section.scope, code, name, from_m, to_m),
            display_name=_section_label(section.scope, code, name, from_m, to_m),
            mud_type=setting.mud_type if setting else None,
            mud_type_label=MUD_COST_MUD_TYPE_LABELS.get(setting.mud_type, "Not configured") if setting else "Not configured",
            remarks=setting.remarks if setting else "",
            base_rate=_recon_amount(setting.base_rate if setting else 0),
            currency=(setting.currency if setting and setting.currency else currency),
            is_configured=setting is not None,
            is_current=True,
            created_by=setting.created_by if setting else "",
            updated_by=setting.updated_by if setting else "",
            created_at=setting.created_at if setting else None,
            updated_at=setting.updated_at if setting else None,
        ))
    # Retain configuration for a section that a later well-plan edit replaced.
    for key, setting in sorted(settings.items(), key=lambda item: (item[0][0], item[1].section_name_snapshot)):
        if key in seen:
            continue
        rows.append(MudCostSectionSettingOut(
            id=setting.id,
            rig_id=rig.id,
            rig_code=rig.rig_code,
            well_id=well.id,
            well_code=well.well_code,
            section_id=setting.section_id,
            hole_section_id=setting.hole_section_id,
            section_scope=setting.section_scope,
            section_code=setting.section_code_snapshot,
            section_name=setting.section_name_snapshot,
            section_label=_section_label(
                setting.section_scope, setting.section_code_snapshot, setting.section_name_snapshot,
            ),
            display_name=_section_label(
                setting.section_scope, setting.section_code_snapshot, setting.section_name_snapshot,
            ) + " · historical",
            mud_type=setting.mud_type,
            mud_type_label=MUD_COST_MUD_TYPE_LABELS.get(setting.mud_type, setting.mud_type),
            remarks=setting.remarks,
            base_rate=_recon_amount(setting.base_rate),
            currency=setting.currency or currency,
            is_configured=True,
            is_current=False,
            created_by=setting.created_by,
            updated_by=setting.updated_by,
            created_at=setting.created_at,
            updated_at=setting.updated_at,
        ))
    return rows


def upsert_section_setting(
    db: Session,
    organization_id: str,
    data: MudCostSectionSettingIn,
    user: User,
    request: Request | None,
) -> MudCostSectionSettingOut:
    """Create or update the one mud configuration that belongs to a section."""
    rig, well, section = _scope_or_404(
        db, organization_id, data.rig_id, data.well_id, data.section_id, require_current_section=True,
    )
    if section is None or section.hole_section is None:
        raise HTTPException(status_code=422, detail="Choose a current section configured for this well")
    if section.hole_section.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the section in Master Data before configuring its mud type")
    currency = well_standard_currency(db, organization_id, well.id)
    existing = db.scalar(select(MudCostSectionSetting).where(
        MudCostSectionSetting.organization_id == organization_id,
        MudCostSectionSetting.well_id == well.id,
        MudCostSectionSetting.section_scope == section.scope,
        MudCostSectionSetting.hole_section_id == section.hole_section_id,
    ))
    base_rate = data.base_rate if data.mud_type != "WBM" and data.base_rate is not None else Decimal("0")
    if existing is None:
        existing = MudCostSectionSetting(
            organization_id=organization_id,
            rig_id=rig.id,
            well_id=well.id,
            section_scope=section.scope,
            hole_section_id=section.hole_section_id,
            mud_type=data.mud_type,
            created_by=user.email,
        )
        db.add(existing)
        action = "create"
    else:
        action = "update"
    existing.rig_id = rig.id
    existing.section_id = section.id
    existing.section_code_snapshot = section.hole_section.section_code
    existing.section_name_snapshot = section.hole_section.section_name
    existing.mud_type = data.mud_type
    existing.remarks = data.remarks.strip()
    existing.base_rate = base_rate
    existing.currency = currency
    existing.updated_by = user.email
    existing.updated_at = now()
    db.flush()
    label = _section_label(
        section.scope,
        section.hole_section.section_code,
        section.hole_section.section_name,
    )
    _audit(
        db,
        user=user,
        action=action,
        entity_type="mud_cost_section_setting",
        entity_id=existing.id,
        entity_label=label,
        summary=(
            f"{'Configured' if action == 'create' else 'Updated'} mud type {data.mud_type} "
            f"({MUD_COST_MUD_TYPE_LABELS.get(data.mud_type, data.mud_type)}) for {label}; "
            f"Cost/BBL base rate {currency} {base_rate:,.10f}"
            + (f"; remarks: {existing.remarks}" if existing.remarks else "")
        ),
        request=request,
    )
    _commit(db)
    return MudCostSectionSettingOut(
        id=existing.id,
        rig_id=rig.id,
        rig_code=rig.rig_code,
        well_id=well.id,
        well_code=well.well_code,
        section_id=section.id,
        hole_section_id=section.hole_section_id,
        section_scope=section.scope,
        section_code=section.hole_section.section_code,
        section_name=section.hole_section.section_name,
        section_label=label,
        display_name=label,
        mud_type=existing.mud_type,
        mud_type_label=MUD_COST_MUD_TYPE_LABELS.get(existing.mud_type, existing.mud_type),
        remarks=existing.remarks,
        base_rate=_recon_amount(existing.base_rate),
        currency=existing.currency,
        is_configured=True,
        is_current=True,
        created_by=existing.created_by,
        updated_by=existing.updated_by,
        created_at=existing.created_at,
        updated_at=existing.updated_at,
    )


def _mud_actual_cost_map(
    db: Session,
    organization_id: str,
    well_id: str,
    *,
    date_to: date,
    include_draft: bool,
) -> dict[tuple[str, date], Decimal]:
    """Mud Chemicals cost from the Daily Cost register, by hole section and date."""
    statement = select(
        DailyCostEntry.cost_date,
        DailyCostConsumableLine.hole_section_id,
        func.sum(DailyCostConsumableLine.standard_amount),
    ).join(
        DailyCostEntry, DailyCostEntry.id == DailyCostConsumableLine.entry_id,
    ).where(
        DailyCostConsumableLine.organization_id == organization_id,
        DailyCostEntry.organization_id == organization_id,
        DailyCostEntry.well_id == well_id,
        DailyCostEntry.is_deleted.is_(False),
        DailyCostConsumableLine.category == MUD_CHEMICAL_CATEGORY,
        DailyCostEntry.cost_date <= date_to,
    )
    if not include_draft:
        statement = statement.where(DailyCostEntry.status == "submitted")
    statement = statement.group_by(DailyCostEntry.cost_date, DailyCostConsumableLine.hole_section_id)
    result: dict[tuple[str, date], Decimal] = {}
    for cost_date, hole_section_id, amount in db.execute(statement).all():
        if not hole_section_id:
            continue
        result[(str(hole_section_id), cost_date)] = _recon_amount(amount)
    return result


def _planned_mud_cost_map(
    db: Session,
    organization_id: str,
    well_id: str,
) -> tuple[dict[tuple[str, str], Decimal], bool]:
    """The AFE mud chemicals allowance of each section, keyed by scope and section.

    Daily Cost freezes every AFE estimate into an immutable baseline when tracking
    starts, and the whole cost report plans against that snapshot. The mud
    allowance is therefore the section's own ``Mud Chemicals`` consumable line of
    the frozen estimate — never the section's entire AFE plan, which also carries
    its services, tangible items and other consumable categories.

    The second value reports whether the well has any locked AFE plan at all. When
    it does not, a planned amount is unknown and must not be printed as zero.
    """
    locked_plan = db.scalar(
        select(DailyCostBaseline.id).where(
            DailyCostBaseline.organization_id == organization_id,
            DailyCostBaseline.well_id == well_id,
            select(DailyCostEntry.id).where(
                DailyCostEntry.baseline_id == DailyCostBaseline.id,
                DailyCostEntry.is_deleted.is_(False),
            ).exists(),
        ).limit(1)
    )
    if locked_plan is None:
        return {}, False
    rows = db.execute(
        select(
            Afe.configuration_scope,
            DailyCostBaselineBudgetLine.section_id,
            func.sum(DailyCostBaselineBudgetLine.planned_amount),
        )
        .join(DailyCostBaseline, DailyCostBaseline.id == DailyCostBaselineBudgetLine.baseline_id)
        .join(Afe, Afe.id == DailyCostBaseline.afe_id)
        .where(
            DailyCostBaselineBudgetLine.organization_id == organization_id,
            DailyCostBaseline.well_id == well_id,
            DailyCostBaselineBudgetLine.cost_group == "Consumables",
            DailyCostBaselineBudgetLine.budget_kind == "consumable_category",
            DailyCostBaselineBudgetLine.item_key == MUD_CHEMICAL_CATEGORY,
            select(DailyCostEntry.id).where(
                DailyCostEntry.baseline_id == DailyCostBaseline.id,
                DailyCostEntry.is_deleted.is_(False),
            ).exists(),
        )
        .group_by(Afe.configuration_scope, DailyCostBaselineBudgetLine.section_id)
    ).all()
    planned: dict[tuple[str, str], Decimal] = {}
    for scope, hole_section_id, amount in rows:
        if not scope or not hole_section_id:
            continue
        key = _setting_key(str(scope), str(hole_section_id))
        planned[key] = planned.get(key, ZERO) + _recon_amount(amount)
    return planned, True


def reconcile_well(
    db: Session,
    organization_id: str,
    well: Well,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    include_draft: bool = True,
    section_id: str = "",
) -> MudCostReconciliationOut:
    """Reconcile mud cost section by section, day by day, to ``date_to``.

    Every day carries the cumulative position to that date: total mud, ALPHA,
    BETA and Cost/BBL. The cumulative reconciled cost applies that day's latest
    Cost/BBL to the mud consumed to date, exactly as the well cost comparison
    consumes it. Sections are never combined in a row.
    """
    effective_to = date_to or date.today()
    if date_from and date_from > effective_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    currency = well_standard_currency(db, organization_id, well.id)
    actuals = _mud_actual_cost_map(
        db, organization_id, well.id, date_to=effective_to, include_draft=include_draft,
    )
    settings = _setting_map(db, organization_id, well.id)
    planned_mud, has_locked_plan = _planned_mud_cost_map(db, organization_id, well.id)
    for key, setting in settings.items():
        if setting.currency and setting.currency != currency and any(
            hole == key[1] for (hole, _date) in actuals
        ):
            raise HTTPException(status_code=409, detail=(
                f"The Cost/BBL base rate for {setting.section_code_snapshot} {setting.section_name_snapshot} "
                f"was saved in {setting.currency}, but this well's daily cost standard currency is {currency}. "
                "Open the section mud configuration and save it again to use the current currency."
            ))

    entries = [
        entry for entry in _entries_for_well(db, organization_id, well.id, deleted=False)
        if entry.entry_date <= effective_to
    ]
    current_sections = db.scalars(
        select(WellSection).where(
            WellSection.organization_id == organization_id,
            WellSection.well_id == well.id,
        )
    ).all()
    current_by_key = {_setting_key(row.scope, row.hole_section_id): row for row in current_sections}

    grouped: dict[tuple[str, str], list[MudCostEntry]] = defaultdict(list)
    for entry in entries:
        grouped[_setting_key(entry.section_scope, entry.hole_section_id)].append(entry)
    if section_id:
        matching = {
            key for key, rows in grouped.items()
            if section_id in {row.section_id for row in rows}
            or (key in settings and settings[key].section_id == section_id)
            or (key in current_by_key and current_by_key[key].id == section_id)
        }
        grouped = {key: grouped[key] for key in matching}

    section_rows: list[MudCostReconciliationSectionOut] = []
    daily_rows: list[MudCostReconciliationRowOut] = []
    for key in sorted(grouped, key=lambda value: (value[0], value[1])):
        section_entries = sorted(grouped[key], key=lambda row: (row.entry_date, row.id))
        latest_entry = section_entries[-1]
        opening_stock = _values_for_entry(section_entries[0])["opening_stock"]
        scope, hole_section_id = key
        setting = settings.get(key)
        mud_type = setting.mud_type if setting else None
        base_rate = _recon_amount(setting.base_rate if setting else 0)
        is_wbm = mud_type == "WBM"
        is_configured = setting is not None and mud_type is not None
        current_section = current_by_key.get(key)
        output_section_id = (
            current_section.id if current_section is not None
            else (setting.section_id if setting else latest_entry.section_id)
        )
        section_label = _section_label(
            scope,
            latest_entry.section_code_snapshot,
            latest_entry.section_name_snapshot,
            Decimal(latest_entry.section_from_depth),
            Decimal(latest_entry.section_to_depth),
        )
        entries_by_date = {row.entry_date: row for row in section_entries}
        dates = sorted(set(entries_by_date) | {day for (hole, day) in actuals if hole == hole_section_id})
        cumulative_additions = ZERO
        cumulative_extra = ZERO
        cumulative_actual = ZERO
        cumulative_consumption = ZERO
        latest_rate: Decimal | None = None
        section_daily_rows: list[MudCostReconciliationRowOut] = []
        for cost_date in dates:
            entry = entries_by_date.get(cost_date)
            raw = _values_for_entry(entry) if entry is not None else line_amounts({})
            additions = group_total(raw, "additions")
            extra_obm = raw["extra_obm_received"]
            consumption = group_total(raw, "consumption_losses")
            actual = actuals.get((hole_section_id, cost_date), ZERO)
            cumulative_additions += additions
            cumulative_extra += extra_obm
            cumulative_actual += actual
            cumulative_consumption += consumption
            calc = reconcile_mud(
                mud_type=mud_type,
                base_rate=base_rate if is_configured else None,
                opening_stock=opening_stock,
                additions=cumulative_additions,
                extra_obm_received=cumulative_extra,
                actual_cost=cumulative_actual,
                consumption_losses=cumulative_consumption,
            )
            if calc.cost_per_bbl is not None:
                latest_rate = calc.cost_per_bbl
            if not is_configured:
                day_reconciled = None
                cumulative_reconciled = None
            elif is_wbm:
                day_reconciled = _recon_amount(actual)
                cumulative_reconciled = _recon_amount(cumulative_actual)
            elif latest_rate is not None:
                day_reconciled = _recon_amount(consumption * latest_rate)
                cumulative_reconciled = _recon_amount(cumulative_consumption * latest_rate)
            else:
                day_reconciled = None
                cumulative_reconciled = None
            section_daily_rows.append(MudCostReconciliationRowOut(
                id=f"{output_section_id}:{cost_date.isoformat()}",
                rig_id=latest_entry.rig_id,
                rig_code=latest_entry.rig_code_snapshot,
                well_id=latest_entry.well_id,
                well_code=latest_entry.well_code_snapshot,
                section_id=output_section_id,
                section_scope=scope,
                section_code=latest_entry.section_code_snapshot,
                section_name=latest_entry.section_name_snapshot,
                section_label=section_label,
                mud_type=mud_type,
                mud_type_label=MUD_COST_MUD_TYPE_LABELS.get(mud_type or "", "Not configured"),
                is_configured=is_configured,
                is_wbm=is_wbm,
                cost_date=cost_date,
                currency=currency,
                base_rate=base_rate,
                opening_stock=_recon_amount(opening_stock),
                additions=_recon_amount(additions),
                extra_obm_received=_recon_amount(extra_obm),
                actual_cost=_recon_amount(actual),
                total_mud=calc.total_mud,
                alpha=calc.alpha,
                beta=calc.beta,
                cost_per_bbl=latest_rate,
                consumption_losses=_recon_amount(consumption),
                reconciled_cost=day_reconciled,
                cumulative_additions=_recon_amount(cumulative_additions),
                cumulative_extra_obm_received=_recon_amount(cumulative_extra),
                cumulative_actual_cost=_recon_amount(cumulative_actual),
                cumulative_total_mud=calc.total_mud,
                cumulative_alpha=calc.alpha,
                cumulative_beta=calc.beta,
                cumulative_consumption_losses=_recon_amount(cumulative_consumption),
                cumulative_reconciled_cost=cumulative_reconciled,
            ))
        section_daily_rows.sort(key=lambda row: row.cost_date)
        window = [
            row for row in section_daily_rows
            if (date_from is None or row.cost_date >= date_from)
        ]
        additions = sum((row.additions for row in window), ZERO)
        extra_obm = sum((row.extra_obm_received for row in window), ZERO)
        actual = sum((row.actual_cost for row in window), ZERO)
        consumption = sum((row.consumption_losses for row in window), ZERO)
        latest_rate = section_daily_rows[-1].cost_per_bbl if section_daily_rows else None
        total_mud = _recon_amount(opening_stock + extra_obm + additions)
        alpha = _recon_amount((opening_stock + extra_obm) * base_rate) if is_configured and not is_wbm else None
        beta = _recon_amount(alpha + actual) if alpha is not None else None
        if not is_configured:
            reconciled = None
        elif is_wbm:
            reconciled = _recon_amount(actual)
        elif latest_rate is not None:
            reconciled = _recon_amount(consumption * latest_rate)
        else:
            reconciled = None
        loss_values = _loss_values_for_entries(
            entry for entry in section_entries
            if date_from is None or entry.entry_date >= date_from
        )
        section_rows.append(MudCostReconciliationSectionOut(
            section_id=output_section_id,
            hole_section_id=hole_section_id,
            rig_id=latest_entry.rig_id,
            rig_code=latest_entry.rig_code_snapshot,
            well_id=latest_entry.well_id,
            well_code=latest_entry.well_code_snapshot,
            section_scope=scope,
            section_code=latest_entry.section_code_snapshot,
            section_name=latest_entry.section_name_snapshot,
            section_label=section_label,
            mud_type=mud_type,
            mud_type_label=MUD_COST_MUD_TYPE_LABELS.get(mud_type or "", "Not configured"),
            remarks=setting.remarks if setting else "",
            is_configured=is_configured,
            is_current=current_section is not None,
            is_wbm=is_wbm,
            currency=currency,
            base_rate=base_rate,
            opening_stock=_recon_amount(opening_stock),
            first_date=window[0].cost_date if window else None,
            last_date=window[-1].cost_date if window else None,
            entry_count=len(window),
            additions=_recon_amount(additions),
            extra_obm_received=_recon_amount(extra_obm),
            actual_cost=_recon_amount(actual),
            planned_cost=planned_mud.get(key) if has_locked_plan else None,
            total_mud=total_mud,
            alpha=alpha,
            beta=beta,
            consumption_losses=_recon_amount(consumption),
            cost_per_bbl=latest_rate,
            reconciled_cost=reconciled,
            adjustment=(
                _recon_amount(reconciled - actual)
                if reconciled is not None else None
            ),
            **loss_values,
        ))
        daily_rows.extend(
            row for row in section_daily_rows
            if (date_from is None or row.cost_date >= date_from)
        )

    section_rows.sort(key=lambda row: (row.section_scope, row.section_code.casefold(), row.section_label))
    daily_rows.sort(key=lambda row: (row.section_scope, row.section_label.casefold(), row.cost_date))
    latest_row = next(
        (row for row in sorted(
            daily_rows,
            key=lambda item: (item.cost_date, item.section_label.casefold()),
            reverse=True,
        ) if row.cost_per_bbl is not None),
        None,
    )
    total_actual = sum((row.actual_cost for row in section_rows), ZERO)
    reconciled_rows = [row for row in section_rows if row.reconciled_cost is not None]
    total_reconciled = sum((row.reconciled_cost for row in reconciled_rows if row.reconciled_cost is not None), ZERO)
    total_adjustment = sum(
        (row.reconciled_cost - row.actual_cost for row in reconciled_rows if row.reconciled_cost is not None),
        ZERO,
    )
    return MudCostReconciliationOut(
        from_date=date_from,
        to_date=effective_to,
        currency=currency,
        selected_section_count=len(section_rows),
        configured_section_count=sum(1 for row in section_rows if row.is_configured),
        unconfigured_section_count=sum(1 for row in section_rows if not row.is_configured),
        entry_count=len(daily_rows),
        latest_cost_per_bbl=latest_row.cost_per_bbl if latest_row else None,
        latest_cost_per_bbl_section=latest_row.section_label if latest_row else "",
        latest_cost_per_bbl_date=latest_row.cost_date if latest_row else None,
        total_actual_cost=_recon_amount(total_actual),
        total_reconciled_cost=_recon_amount(total_reconciled),
        total_adjustment=_recon_amount(total_adjustment),
        total_consumption_losses=_recon_amount(sum((row.consumption_losses for row in section_rows), ZERO)),
        total_planned_cost=(
            _recon_amount(sum(planned_mud.values(), ZERO)) if has_locked_plan else None
        ),
        sections=section_rows,
        rows=daily_rows,
    )


def mud_cost_reconciliation(
    db: Session,
    organization_id: str,
    *,
    rig_id: str,
    well_id: str,
    section_id: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    include_draft: bool = True,
) -> MudCostReconciliationOut:
    _rig, well, _ = _scope_or_404(db, organization_id, rig_id, well_id)
    if section_id:
        current_section = db.scalar(select(WellSection.id).where(
            WellSection.id == section_id,
            WellSection.organization_id == organization_id,
            WellSection.well_id == well_id,
        ))
        historical_section = db.scalar(select(MudCostEntry.id).where(
            MudCostEntry.organization_id == organization_id,
            MudCostEntry.well_id == well_id,
            MudCostEntry.section_id == section_id,
        ).limit(1))
        configured_section = db.scalar(select(MudCostSectionSetting.id).where(
            MudCostSectionSetting.organization_id == organization_id,
            MudCostSectionSetting.well_id == well_id,
            MudCostSectionSetting.section_id == section_id,
        ).limit(1))
        if not current_section and not historical_section and not configured_section:
            raise HTTPException(status_code=404, detail="Section not found for this well")
    return reconcile_well(
        db, organization_id, well,
        date_from=date_from, date_to=date_to, include_draft=include_draft, section_id=section_id,
    )
