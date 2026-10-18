"""Persistence, reconciliation and workflow services for Mud Cost Analysis."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.mud_cost import (
    MUD_COST_LINE_SPECS,
    ZERO,
    book_closing_stock,
    group_total,
    line_amounts,
    variance,
)
from app.models import MudCostEntry, MudCostEntryLine, Rig, Well, WellSection
from app.models.rig_well import now
from app.models.entities import User
from app.schemas.mud_cost import (
    MudCostBalanceRowOut,
    MudCostEntryCreate,
    MudCostEntryOut,
    MudCostEntryUpdate,
    MudCostExportAudit,
    MudCostImportRequest,
    MudCostImportResponse,
    MudCostLineOut,
    MudCostMaterialBalanceOut,
    MudCostReference,
    MudCostRigOption,
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


def _section_label(
    scope: str,
    code: str,
    name: str,
    from_depth: Decimal | None = None,
    to_depth: Decimal | None = None,
) -> str:
    interval = ""
    if from_depth is not None and to_depth is not None:
        interval = f" · {from_depth:g}–{to_depth:g}"
    return f"{code} · {name} · {scope.title()}{interval}"


def _section_option(row: WellSection, *, is_current: bool = True) -> MudCostSectionOption:
    master = row.hole_section
    code = master.section_code if master else ""
    name = master.section_name if master else ""
    return MudCostSectionOption(
        id=row.id,
        hole_section_id=row.hole_section_id,
        section_code=code,
        section_name=name,
        scope=row.scope,
        from_depth=Decimal(row.from_depth),
        to_depth=Decimal(row.to_depth),
        is_current=is_current,
        display_name=_section_label(row.scope, code, name, Decimal(row.from_depth), Decimal(row.to_depth)),
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
    section_options: dict[str, dict[str, MudCostSectionOption]] = defaultdict(dict)
    for section in current_sections:
        section_options[section.well_id][section.id] = _section_option(section)

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
    for sort_order, spec in enumerate(MUD_COST_LINE_SPECS):
        input_row = incoming.get(spec.code)
        amount = ZERO if input_row is None or input_row.amount is None else Decimal(input_row.amount)
        remarks = "" if input_row is None else input_row.remarks.strip()
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
    """Persist each later day's opening as the previous actual closing.

    The earliest active row retains its own stored opening stock. This makes a
    back-dated insert, edit, delete or restore deterministic while preserving the
    first stock observation when an earlier row is temporarily deleted.
    """
    entries = _entries_for_section(db, organization_id, section_id, deleted=False)
    previous_actual: Decimal | None = None
    previous_actual_remarks = ""
    for entry in entries:
        lines = _line_map(entry)
        opening = lines.get("opening_stock")
        actual = lines.get("actual_closing_stock")
        if opening is None or actual is None:
            continue
        if previous_actual is not None:
            opening.amount = previous_actual
            opening.remarks = previous_actual_remarks
            opening.updated_at = now()
        previous_actual = Decimal(actual.amount)
        previous_actual_remarks = actual.remarks
    db.flush()


def _balance_values(entries: Iterable[MudCostEntry]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[MudCostEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.section_id].append(entry)
    result: dict[str, dict[str, Any]] = {}
    for section_entries in grouped.values():
        section_entries.sort(key=lambda item: (item.entry_date, item.id))
        previous_actual: Decimal | None = None
        previous_actual_remarks = ""
        for entry in section_entries:
            lines = _line_map(entry)
            raw = _values_for_entry(entry)
            if previous_actual is None:
                opening = raw["opening_stock"]
                opening_remarks = lines.get("opening_stock").remarks if lines.get("opening_stock") else ""
            else:
                opening = previous_actual
                opening_remarks = previous_actual_remarks
            receipt = group_total(raw, "receipt")
            additions = group_total(raw, "additions")
            consumption_losses = group_total(raw, "consumption_losses")
            others = group_total(raw, "others")
            actual_closing = raw["actual_closing_stock"]
            book_closing = book_closing_stock(opening, receipt, additions, consumption_losses, others)
            actual_line = lines.get("actual_closing_stock")
            result[entry.id] = {
                "opening_stock": opening,
                "opening_stock_remarks": opening_remarks,
                "receipt": receipt,
                "additions": additions,
                "consumption_losses": consumption_losses,
                "others": others,
                "book_closing_stock": book_closing,
                "actual_closing_stock": actual_closing,
                "actual_closing_stock_remarks": actual_line.remarks if actual_line else "",
                "variance": variance(actual_closing, book_closing),
            }
            previous_actual = actual_closing
            previous_actual_remarks = actual_line.remarks if actual_line else ""
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
        actual_closing = raw["actual_closing_stock"]
        actual_line = _line_map(entry).get("actual_closing_stock")
        book_closing = book_closing_stock(opening, receipt, additions, consumption_losses, others)
        actual_remarks = actual_line.remarks if actual_line else ""
        variance_value = variance(actual_closing, book_closing)
    else:
        opening = balance["opening_stock"]
        opening_remarks = balance["opening_stock_remarks"]
        receipt = balance["receipt"]
        additions = balance["additions"]
        consumption_losses = balance["consumption_losses"]
        others = balance["others"]
        actual_closing = balance["actual_closing_stock"]
        actual_remarks = balance["actual_closing_stock_remarks"]
        book_closing = balance["book_closing_stock"]
        variance_value = balance["variance"]

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
        book_closing_stock=book_closing,
        actual_closing_stock=actual_closing,
        actual_closing_stock_remarks=actual_remarks,
        variance=variance_value,
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
        section_from_depth=Decimal(section.from_depth),
        section_to_depth=Decimal(section.to_depth),
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
        book_closing_stock=balance["book_closing_stock"],
        actual_closing_stock=balance["actual_closing_stock"],
        variance=balance["variance"],
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
        book = book_closing_stock(opening, receipt, additions, consumption_losses, others)
        actual = last.actual_closing_stock
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
            book_closing_stock=book,
            actual_closing_stock=actual,
            variance=variance(actual, book),
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
        elif spec.code == "actual_closing_stock":
            amount = row.get("actual_closing_stock") or row.get("closing_stock")
            remarks = row.get("actual_closing_stock_remarks", row.get("actual_closing_stock_remark", ""))
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
    module_label = {"entries": "daily entries", "deleted": "deleted entries", "material_balance": "material balance"}[data.module]
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
