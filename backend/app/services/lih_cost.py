"""LIH Cost Register services (Daily Cost Management).

The register is deliberately manual: a user picks the rig, the well and the
date, adds the LIH items one by one, and the system sums them into the day's
LIH cost. Those totals are then read by Daily Cost Management:

* the daily sheet comparison and the whole-well cost analysis add LIH to the
  actual cost and deduct it from the AFE amount explicitly,
* the Daily Cost Report and Well Cost Report print it below the Tangibles cost,
* the well-wise cost comparison subtracts it from the AFE balance.

LIH cost is never written into the daily cost line tables, so it can never be
mistaken for a budgeted service, consumable or tangible line. Nothing here is
stored as JSON: every item attribute is its own typed column.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.models import Afe, Currency, LihCostEntry, LihCostLine, Rig, UnitOfMeasurement, Well
from app.models.entities import User
from app.models.rig_well import uid
from app.schemas.lih_cost import (
    LihCostAfeOption,
    LihCostBulkActionOut,
    LihCostCurrencyTotal,
    LihCostDayOut,
    LihCostEntryCreate,
    LihCostEntryOut,
    LihCostEntryUpdate,
    LihCostExportAudit,
    LihCostIDs,
    LihCostLineIn,
    LihCostLineOut,
    LihCostReference,
    LihCostReportOut,
    LihCostRigOption,
    LihCostUomOption,
    LihCostWellOption,
)
from app.services import audit

CENT = Decimal("0.01")
TEN_PLACES = Decimal("0.0000000001")


def _money(value: Decimal | int | str | None) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _quantity(value: Decimal | int | str | None) -> Decimal:
    return Decimal(value or 0).quantize(TEN_PLACES, rounding=ROUND_HALF_UP)


def _actor_name(user: User) -> str:
    return user.full_name or user.email


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This LIH record conflicts with an existing one. A well can have only one LIH register per date.",
        ) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="The LIH cost register could not be saved because of a database error."
        ) from error


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


def _workspace_default_currency(db: Session, organization_id: str) -> str:
    """The workspace default currency, then any active currency, then USD."""
    default = db.scalar(
        select(Currency.currency_code).where(
            Currency.organization_id == organization_id,
            Currency.is_default.is_(True),
            Currency.is_deleted.is_(False),
        ).limit(1)
    )
    if default:
        return str(default)
    first = db.scalar(
        select(Currency.currency_code).where(
            Currency.organization_id == organization_id, Currency.is_deleted.is_(False)
        ).order_by(Currency.currency_code).limit(1)
    )
    return str(first or "USD")


def _well_or_404(db: Session, organization_id: str, well_id: str) -> Well:
    well = db.scalars(
        select(Well).options(joinedload(Well.rig)).where(
            Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False)
        )
    ).unique().first()
    if well is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    return well


def _afe_for_well(db: Session, organization_id: str, well_id: str, afe_id: str) -> Afe:
    afe = db.scalar(
        select(Afe).where(
            Afe.id == afe_id, Afe.organization_id == organization_id, Afe.well_id == well_id,
            Afe.is_deleted.is_(False),
        )
    )
    if afe is None:
        raise HTTPException(status_code=422, detail="The selected AFE does not belong to this well")
    return afe


def _resolve_afe(db: Session, organization_id: str, well: Well, afe_id: str) -> Afe | None:
    """An explicit AFE wins; otherwise auto-assign the well's only AFE.

    A well with several AFEs must say which budget the LIH cost belongs to, so
    the register never guesses a deduction. A well without any AFE yet can still
    record LIH cost; the amount is then reported at well level.
    """
    if afe_id:
        return _afe_for_well(db, organization_id, well.id, afe_id)
    afes = db.scalars(
        select(Afe).where(
            Afe.organization_id == organization_id, Afe.well_id == well.id, Afe.is_deleted.is_(False),
        ).order_by(Afe.afe_code)
    ).all()
    if len(afes) == 1:
        return afes[0]
    if len(afes) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "This well has more than one AFE. Choose the AFE the LIH cost is deducted from "
                "before adding the register entry."
            ),
        )
    return None


def _entry_query(organization_id: str, *, deleted: bool):
    return select(LihCostEntry).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.is_deleted.is_(deleted),
    )


def _entry_or_404(db: Session, organization_id: str, entry_id: str, *, deleted: bool = False) -> LihCostEntry:
    entry = db.scalars(
        _entry_query(organization_id, deleted=deleted).where(LihCostEntry.id == entry_id)
    ).unique().first()
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="LIH register entry not found in this workspace" if not deleted else "Deleted LIH entry not found",
        )
    return entry


def _entry_out(entry: LihCostEntry) -> LihCostEntryOut:
    return LihCostEntryOut(
        id=entry.id,
        rig_id=entry.rig_id,
        rig_code=entry.rig_code_snapshot,
        rig_name=entry.rig_name_snapshot,
        well_id=entry.well_id,
        well_code=entry.well_code_snapshot,
        well_name=entry.well_name_snapshot,
        afe_id=entry.afe_id,
        afe_code=entry.afe_code_snapshot,
        afe_name=entry.afe_name_snapshot,
        cost_date=entry.cost_date,
        currency=entry.currency,
        remarks=entry.remarks,
        line_count=entry.line_count,
        total_cost=_money(entry.total_cost),
        display_name=f"{entry.well_code_snapshot} · {entry.cost_date.isoformat()}"
        + (f" · {entry.afe_code_snapshot}" if entry.afe_code_snapshot else " · No AFE"),
        is_deleted=entry.is_deleted,
        deleted_at=entry.deleted_at,
        created_by=entry.created_by,
        updated_by=entry.updated_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _line_out(line: LihCostLine) -> LihCostLineOut:
    return LihCostLineOut(
        id=line.id,
        item_description=line.item_description,
        od_size=_quantity(line.od_size) if line.od_size is not None else None,
        id_size=_quantity(line.id_size) if line.id_size is not None else None,
        fish_neck_od=_quantity(line.fish_neck_od) if line.fish_neck_od is not None else None,
        fish_neck_length=_quantity(line.fish_neck_length) if line.fish_neck_length is not None else None,
        serial_number=line.serial_number,
        connection=line.connection,
        length=_quantity(line.length) if line.length is not None else None,
        no_of_units=_quantity(line.no_of_units),
        unit=line.unit,
        unit_cost=_quantity(line.unit_cost),
        total_cost=_money(line.total_cost),
        remarks=line.remarks,
        sort_order=line.sort_order,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


def _day_out(entry: LihCostEntry) -> LihCostDayOut:
    return LihCostDayOut(
        entry=_entry_out(entry),
        lines=[_line_out(line) for line in entry.lines],
    )


def _recalculate(entry: LihCostEntry) -> None:
    """Keep the day's line count and total equal to its items, server-side."""
    entry.line_count = len(entry.lines)
    entry.total_cost = _money(sum((Decimal(line.total_cost) for line in entry.lines), Decimal("0")))


def reference_data(db: Session, organization_id: str) -> LihCostReference:
    rigs = db.scalars(
        select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)
    ).all()
    wells = db.scalars(
        select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False)).order_by(Well.well_code)
    ).all()
    afes = db.scalars(
        select(Afe).where(Afe.organization_id == organization_id, Afe.is_deleted.is_(False)).order_by(Afe.afe_code)
    ).all()
    uoms = db.scalars(
        select(UnitOfMeasurement).where(
            UnitOfMeasurement.organization_id == organization_id, UnitOfMeasurement.is_deleted.is_(False)
        ).order_by(UnitOfMeasurement.unit_code)
    ).all()
    return LihCostReference(
        rigs=[
            LihCostRigOption(
                id=row.id, rig_code=row.rig_code, rig_name=row.rig_name,
                display_name=f"{row.rig_code} · {row.rig_name}",
            )
            for row in rigs
        ],
        wells=[
            LihCostWellOption(
                id=row.id, rig_id=row.rig_id, well_code=row.well_code, well_name=row.well_name,
                status=row.status, config_status=row.config_status,
                display_name=f"{row.well_code} · {row.well_name}",
            )
            for row in wells
        ],
        afes=[
            LihCostAfeOption(
                id=row.id, well_id=row.well_id, afe_code=row.afe_code, afe_name=row.afe_name,
                status=row.status, configuration_scope=row.configuration_scope,
                standard_currency=row.standard_currency,
                display_name=f"{row.afe_code} · {row.afe_name} · {row.standard_currency}",
            )
            for row in afes
        ],
        uoms=[
            LihCostUomOption(
                code=row.unit_code, name=row.unit_name, symbol=row.unit_symbol,
                display_name=f"{row.unit_code} · {row.unit_name}"
                + (f" ({row.unit_symbol})" if row.unit_symbol and row.unit_symbol != row.unit_code else ""),
            )
            for row in uoms
        ],
        default_currency=_workspace_default_currency(db, organization_id),
    )


def create_entry(
    db: Session, organization_id: str, data: LihCostEntryCreate, user: User, request: Request | None
) -> LihCostDayOut:
    well = _well_or_404(db, organization_id, data.well_id)
    if data.rig_id and data.rig_id != well.rig_id:
        raise HTTPException(status_code=422, detail="The selected well does not belong to the selected rig")
    afe = _resolve_afe(db, organization_id, well, data.afe_id)
    duplicate = db.scalar(
        select(LihCostEntry.id).where(
            LihCostEntry.organization_id == organization_id,
            LihCostEntry.well_id == well.id,
            LihCostEntry.cost_date == data.cost_date,
            LihCostEntry.is_deleted.is_(False),
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=f"An LIH register already exists for {well.well_code} on {data.cost_date.isoformat()}",
        )
    currency = (
        str(afe.standard_currency).upper() if afe and afe.standard_currency
        else _workspace_default_currency(db, organization_id).upper()
    )
    entry = LihCostEntry(
        id=uid(),
        organization_id=organization_id,
        rig_id=well.rig_id,
        rig_code_snapshot=well.rig.rig_code if well.rig else "",
        rig_name_snapshot=well.rig.rig_name if well.rig else "",
        well_id=well.id,
        well_code_snapshot=well.well_code,
        well_name_snapshot=well.well_name,
        afe_id=afe.id if afe else None,
        afe_code_snapshot=afe.afe_code if afe else "",
        afe_name_snapshot=afe.afe_name if afe else "",
        cost_date=data.cost_date,
        currency=currency,
        remarks=data.remarks,
        line_count=0,
        total_cost=Decimal("0"),
        created_by=_actor_name(user),
        updated_by=_actor_name(user),
    )
    db.add(entry)
    _audit(
        db, user=user, action="create", entity_type="lih_cost", entity_id=entry.id,
        entity_label=f"LIH · {well.well_code} · {data.cost_date.isoformat()}",
        summary=(
            f"Opened the LIH register for {well.well_code} ({well.rig.rig_code if well.rig else 'rig'}) on "
            f"{data.cost_date.isoformat()}"
            + (f" against AFE {afe.afe_code} in {currency}" if afe else f" without an AFE in {currency}")
        ),
        request=request,
    )
    _commit(db)
    return _day_out(_entry_or_404(db, organization_id, entry.id))


def update_entry(
    db: Session, organization_id: str, entry_id: str, data: LihCostEntryUpdate, user: User, request: Request | None
) -> LihCostDayOut:
    entry = _entry_or_404(db, organization_id, entry_id)
    well = _well_or_404(db, organization_id, entry.well_id)
    changes: list[str] = []
    if data.afe_id is not None:
        afe = _afe_for_well(db, organization_id, well.id, data.afe_id) if data.afe_id else None
        entry.afe_id = afe.id if afe else None
        entry.afe_code_snapshot = afe.afe_code if afe else ""
        entry.afe_name_snapshot = afe.afe_name if afe else ""
        entry.currency = (
            str(afe.standard_currency).upper() if afe and afe.standard_currency
            else _workspace_default_currency(db, organization_id).upper()
        )
        changes.append(f"AFE {afe.afe_code}" if afe else "No AFE")
    if data.cost_date is not None and data.cost_date != entry.cost_date:
        duplicate = db.scalar(
            select(LihCostEntry.id).where(
                LihCostEntry.organization_id == organization_id,
                LihCostEntry.well_id == entry.well_id,
                LihCostEntry.cost_date == data.cost_date,
                LihCostEntry.id != entry.id,
                LihCostEntry.is_deleted.is_(False),
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"An LIH register already exists for {entry.well_code_snapshot} on {data.cost_date.isoformat()}",
            )
        changes.append(f"date {entry.cost_date.isoformat()} → {data.cost_date.isoformat()}")
        entry.cost_date = data.cost_date
    if data.remarks is not None:
        entry.remarks = data.remarks
        changes.append("remarks")
    entry.updated_by = _actor_name(user)
    _audit(
        db, user=user, action="update", entity_type="lih_cost", entity_id=entry.id,
        entity_label=f"LIH · {entry.well_code_snapshot} · {entry.cost_date.isoformat()}",
        summary="Updated the LIH register entry: " + (", ".join(changes) if changes else "no field changed"),
        request=request,
    )
    _commit(db)
    return _day_out(_entry_or_404(db, organization_id, entry.id))


def get_entry(db: Session, organization_id: str, entry_id: str) -> LihCostDayOut:
    return _day_out(_entry_or_404(db, organization_id, entry_id))


def get_deleted_entry(db: Session, organization_id: str, entry_id: str) -> LihCostEntryOut:
    return _entry_out(_entry_or_404(db, organization_id, entry_id, deleted=True))


def day_for_well_date(db: Session, organization_id: str, well_id: str, cost_date: date) -> LihCostDayOut | None:
    entry = db.scalars(
        _entry_query(organization_id, deleted=False).where(
            LihCostEntry.well_id == well_id, LihCostEntry.cost_date == cost_date,
        )
    ).unique().first()
    return _day_out(entry) if entry else None


def list_entries(
    db: Session,
    organization_id: str,
    *,
    rig_id: str = "",
    well_id: str = "",
    afe_id: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    deleted: bool = False,
) -> list[LihCostEntryOut]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    query = _entry_query(organization_id, deleted=deleted)
    if rig_id:
        query = query.where(LihCostEntry.rig_id == rig_id)
    if well_id:
        query = query.where(LihCostEntry.well_id == well_id)
    if afe_id:
        query = query.where(LihCostEntry.afe_id == afe_id)
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    rows = db.scalars(query.order_by(LihCostEntry.cost_date.desc(), LihCostEntry.id)).unique().all()
    return [_entry_out(row) for row in rows]


def add_line(
    db: Session, organization_id: str, entry_id: str, data: LihCostLineIn, user: User, request: Request | None
) -> LihCostDayOut:
    entry = _entry_or_404(db, organization_id, entry_id)
    total = _money(Decimal(data.no_of_units) * Decimal(data.unit_cost))
    line = LihCostLine(
        id=uid(),
        organization_id=organization_id,
        entry_id=entry.id,
        item_description=data.item_description,
        od_size=data.od_size,
        id_size=data.id_size,
        fish_neck_od=data.fish_neck_od,
        fish_neck_length=data.fish_neck_length,
        serial_number=data.serial_number,
        connection=data.connection,
        length=data.length,
        no_of_units=Decimal(data.no_of_units),
        unit=data.unit,
        unit_cost=Decimal(data.unit_cost),
        total_cost=total,
        remarks=data.remarks,
        sort_order=len(entry.lines),
    )
    entry.lines.append(line)
    _recalculate(entry)
    entry.updated_by = _actor_name(user)
    _audit(
        db, user=user, action="create", entity_type="lih_cost_line", entity_id=line.id,
        entity_label=f"LIH item · {data.item_description}"[:255],
        summary=(
            f"Added LIH item “{data.item_description}” to {entry.well_code_snapshot} on "
            f"{entry.cost_date.isoformat()}: {Decimal(data.no_of_units).normalize():f} "
            f"{data.unit or 'unit'} × {entry.currency} {Decimal(data.unit_cost):,.2f} = "
            f"{entry.currency} {total:,.2f}"
        ),
        request=request,
    )
    _commit(db)
    return _day_out(_entry_or_404(db, organization_id, entry.id))


def _line_or_404(db: Session, entry: LihCostEntry, line_id: str) -> LihCostLine:
    line = db.scalar(
        select(LihCostLine).where(
            LihCostLine.id == line_id,
            LihCostLine.entry_id == entry.id,
            LihCostLine.organization_id == entry.organization_id,
        )
    )
    if line is None:
        raise HTTPException(status_code=404, detail="LIH item not found on this register")
    return line


def update_line(
    db: Session, organization_id: str, entry_id: str, line_id: str, data: LihCostLineIn,
    user: User, request: Request | None,
) -> LihCostDayOut:
    entry = _entry_or_404(db, organization_id, entry_id)
    line = _line_or_404(db, entry, line_id)
    total = _money(Decimal(data.no_of_units) * Decimal(data.unit_cost))
    line.item_description = data.item_description
    line.od_size = data.od_size
    line.id_size = data.id_size
    line.fish_neck_od = data.fish_neck_od
    line.fish_neck_length = data.fish_neck_length
    line.serial_number = data.serial_number
    line.connection = data.connection
    line.length = data.length
    line.no_of_units = Decimal(data.no_of_units)
    line.unit = data.unit
    line.unit_cost = Decimal(data.unit_cost)
    line.total_cost = total
    line.remarks = data.remarks
    _recalculate(entry)
    entry.updated_by = _actor_name(user)
    _audit(
        db, user=user, action="update", entity_type="lih_cost_line", entity_id=line.id,
        entity_label=f"LIH item · {data.item_description}"[:255],
        summary=(
            f"Updated LIH item “{data.item_description}” on {entry.well_code_snapshot} "
            f"{entry.cost_date.isoformat()}: {entry.currency} {total:,.2f}"
        ),
        request=request,
    )
    _commit(db)
    return _day_out(_entry_or_404(db, organization_id, entry.id))


def delete_line(
    db: Session, organization_id: str, entry_id: str, line_id: str, user: User, request: Request | None
) -> LihCostDayOut:
    entry = _entry_or_404(db, organization_id, entry_id)
    line = _line_or_404(db, entry, line_id)
    description, amount = line.item_description, Decimal(line.total_cost)
    entry.lines.remove(line)
    db.delete(line)
    _recalculate(entry)
    entry.updated_by = _actor_name(user)
    _audit(
        db, user=user, action="delete", entity_type="lih_cost_line", entity_id=line_id,
        entity_label=f"LIH item · {description}"[:255],
        summary=(
            f"Removed LIH item “{description}” ({entry.currency} {amount:,.2f}) from "
            f"{entry.well_code_snapshot} {entry.cost_date.isoformat()}"
        ),
        request=request,
    )
    _commit(db)
    return _day_out(_entry_or_404(db, organization_id, entry.id))


def _selected_entries(db: Session, organization_id: str, ids: Sequence[str], *, deleted: bool) -> list[LihCostEntry]:
    if not ids:
        return []
    rows = db.scalars(
        _entry_query(organization_id, deleted=deleted).where(LihCostEntry.id.in_(list(ids)))
    ).unique().all()
    if len(rows) != len(set(ids)):
        raise HTTPException(status_code=404, detail="One or more selected LIH entries were not found")
    return list(rows)


def soft_delete_entries(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None
) -> LihCostBulkActionOut:
    rows = _selected_entries(db, organization_id, ids, deleted=False)
    for entry in rows:
        entry.is_deleted = True
        entry.deleted_at = datetime.now(timezone.utc)
        entry.updated_by = _actor_name(user)
        _audit(
            db, user=user, action="delete", entity_type="lih_cost", entity_id=entry.id,
            entity_label=f"LIH · {entry.well_code_snapshot} · {entry.cost_date.isoformat()}",
            summary=(
                f"Moved the LIH register of {entry.well_code_snapshot} on {entry.cost_date.isoformat()} "
                f"({entry.currency} {Decimal(entry.total_cost):,.2f}) to Deleted Entries"
            ),
            request=request,
        )
    _commit(db)
    return LihCostBulkActionOut(affected_count=len(rows))


def restore_entries(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None
) -> LihCostBulkActionOut:
    rows = _selected_entries(db, organization_id, ids, deleted=True)
    for entry in rows:
        duplicate = db.scalar(
            select(LihCostEntry.id).where(
                LihCostEntry.organization_id == organization_id,
                LihCostEntry.well_id == entry.well_id,
                LihCostEntry.cost_date == entry.cost_date,
                LihCostEntry.id != entry.id,
                LihCostEntry.is_deleted.is_(False),
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot restore the LIH register for {entry.well_code_snapshot} on "
                    f"{entry.cost_date.isoformat()}: an active register already exists for that date."
                ),
            )
    for entry in rows:
        entry.is_deleted = False
        entry.deleted_at = None
        entry.updated_by = _actor_name(user)
        _audit(
            db, user=user, action="restore", entity_type="lih_cost", entity_id=entry.id,
            entity_label=f"LIH · {entry.well_code_snapshot} · {entry.cost_date.isoformat()}",
            summary=(
                f"Restored the LIH register of {entry.well_code_snapshot} on {entry.cost_date.isoformat()} "
                f"({entry.currency} {Decimal(entry.total_cost):,.2f})"
            ),
            request=request,
        )
    _commit(db)
    return LihCostBulkActionOut(affected_count=len(rows))


def permanently_delete_entries(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None
) -> LihCostBulkActionOut:
    rows = _selected_entries(db, organization_id, ids, deleted=True)
    count = len(rows)
    total = _money(sum((Decimal(entry.total_cost) for entry in rows), Decimal("0")))
    for entry in rows:
        _audit(
            db, user=user, action="permanent-delete", entity_type="lih_cost", entity_id=entry.id,
            entity_label=f"LIH · {entry.well_code_snapshot} · {entry.cost_date.isoformat()}",
            summary=(
                f"Permanently deleted the LIH register of {entry.well_code_snapshot} on "
                f"{entry.cost_date.isoformat()} ({entry.currency} {Decimal(entry.total_cost):,.2f}, "
                f"{entry.line_count} item(s))"
            ),
            request=request,
        )
        db.delete(entry)
    _commit(db)
    return LihCostBulkActionOut(affected_count=count)


# ---------------------------------------------------------------------------
# Aggregations consumed by Daily Cost Management, cost analysis and reports
# ---------------------------------------------------------------------------


def lih_total_for_afe(
    db: Session, organization_id: str, afe_id: str, *, through_date: date | None = None,
    date_from: date | None = None, currency: str = "",
) -> Decimal:
    """Cumulative LIH cost filed against one AFE.

    ``currency`` restricts the sum to entries already recorded in the AFE's
    standard currency, so a comparison never adds unlike currencies.
    """
    if not afe_id:
        return Decimal("0.00")
    query = select(func.coalesce(func.sum(LihCostEntry.total_cost), 0)).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.afe_id == afe_id,
        LihCostEntry.is_deleted.is_(False),
    )
    if through_date is not None:
        query = query.where(LihCostEntry.cost_date <= through_date)
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if currency:
        query = query.where(LihCostEntry.currency == currency)
    return _money(Decimal(db.scalar(query) or 0))


def lih_totals_by_afe(
    db: Session, organization_id: str, well_id: str, *,
    date_from: date | None = None, date_to: date | None = None, currency: str = "",
) -> dict[str, Decimal]:
    """LIH cost per AFE for one well, so each AFE deducts exactly its own."""
    query = select(LihCostEntry.afe_id, func.coalesce(func.sum(LihCostEntry.total_cost), 0)).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.well_id == well_id,
        LihCostEntry.is_deleted.is_(False),
        LihCostEntry.afe_id.is_not(None),
    )
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    if currency:
        query = query.where(LihCostEntry.currency == currency)
    query = query.group_by(LihCostEntry.afe_id)
    return {str(row[0]): _money(Decimal(row[1] or 0)) for row in db.execute(query).all() if row[0]}


def lih_totals_by_day(
    db: Session, organization_id: str, well_id: str, *,
    date_from: date | None = None, date_to: date | None = None, currency: str = "",
) -> dict[date, Decimal]:
    query = select(LihCostEntry.cost_date, func.coalesce(func.sum(LihCostEntry.total_cost), 0)).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.well_id == well_id,
        LihCostEntry.is_deleted.is_(False),
    )
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    if currency:
        query = query.where(LihCostEntry.currency == currency)
    query = query.group_by(LihCostEntry.cost_date)
    return {row[0]: _money(Decimal(row[1] or 0)) for row in db.execute(query).all()}


def lih_totals_for_well(
    db: Session, organization_id: str, well_id: str, *,
    date_from: date | None = None, date_to: date | None = None, currency: str = "",
) -> tuple[Decimal, int, int]:
    """(total, line count, entry count) for a well over a period."""
    query = select(
        func.coalesce(func.sum(LihCostEntry.total_cost), 0),
        func.coalesce(func.sum(LihCostEntry.line_count), 0),
        func.count(LihCostEntry.id),
    ).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.well_id == well_id,
        LihCostEntry.is_deleted.is_(False),
    )
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    if currency:
        query = query.where(LihCostEntry.currency == currency)
    total, lines, entries = db.execute(query).one()
    return _money(Decimal(total or 0)), int(lines or 0), int(entries or 0)


def lih_totals_by_currency(
    db: Session, organization_id: str, well_id: str, *,
    date_from: date | None = None, date_to: date | None = None,
) -> dict[str, Decimal]:
    """LIH cost per currency for one well, so unlike amounts are never added."""
    query = select(LihCostEntry.currency, func.coalesce(func.sum(LihCostEntry.total_cost), 0)).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.well_id == well_id,
        LihCostEntry.is_deleted.is_(False),
    )
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    query = query.group_by(LihCostEntry.currency)
    return {str(row[0] or ""): _money(Decimal(row[1] or 0)) for row in db.execute(query).all()}


def lih_currency_totals(
    db: Session, organization_id: str, *,
    date_from: date | None = None, date_to: date | None = None,
) -> dict[str, Decimal]:
    """Workspace-wide LIH totals by currency, for the module dashboard."""
    query = select(LihCostEntry.currency, func.coalesce(func.sum(LihCostEntry.total_cost), 0)).where(
        LihCostEntry.organization_id == organization_id,
        LihCostEntry.is_deleted.is_(False),
    )
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    query = query.group_by(LihCostEntry.currency)
    return {str(row[0] or "Currency not specified"): _money(Decimal(row[1] or 0)) for row in db.execute(query).all()}


def well_report(
    db: Session, organization_id: str, well_id: str, *,
    date_from: date | None = None, date_to: date | None = None,
) -> LihCostReportOut:
    """Every saved LIH day for one well, with its items, for the printed reports."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    well = _well_or_404(db, organization_id, well_id)
    query = _entry_query(organization_id, deleted=False).where(LihCostEntry.well_id == well_id)
    if date_from is not None:
        query = query.where(LihCostEntry.cost_date >= date_from)
    if date_to is not None:
        query = query.where(LihCostEntry.cost_date <= date_to)
    entries = db.scalars(query.order_by(LihCostEntry.cost_date, LihCostEntry.id)).unique().all()
    totals: dict[str, LihCostCurrencyTotal] = {}
    for entry in entries:
        bucket = totals.setdefault(
            entry.currency or "Currency not specified",
            LihCostCurrencyTotal(currency=entry.currency or "Currency not specified", total=Decimal("0"), line_count=0, entry_count=0),
        )
        bucket.total = _money(bucket.total + Decimal(entry.total_cost))
        bucket.line_count += entry.line_count
        bucket.entry_count += 1
    ordered = [totals[key] for key in sorted(totals)]
    single = ordered[0] if len(ordered) == 1 else None
    return LihCostReportOut(
        well_id=well.id,
        well_code=well.well_code,
        well_name=well.well_name,
        from_date=date_from,
        to_date=date_to,
        currency=single.currency if single else "",
        total=single.total if single else _money(sum((row.total for row in ordered), Decimal("0"))),
        line_count=sum(row.line_count for row in ordered),
        entry_count=sum(row.entry_count for row in ordered),
        totals=ordered,
        days=[_day_out(entry) for entry in entries],
    )


def record_export(db: Session, user: User, data: LihCostExportAudit, request: Request | None) -> None:
    _audit(
        db, user=user, action="export", entity_type="lih_cost_export", entity_id=None,
        entity_label=data.module,
        summary=f"Exported {data.record_count} {data.module} LIH record(s) as {data.format.upper()}"
        + (" including deleted records" if data.include_deleted else "")
        + (f"; well {data.well_id}" if data.well_id else "")
        + (f"; register entry {data.entry_id}" if data.entry_id else "")
        + (f"; period {data.date_from or 'inception'} to {data.date_to or date.today()}" if data.date_from or data.date_to else ""),
        request=request,
    )
    _commit(db)
