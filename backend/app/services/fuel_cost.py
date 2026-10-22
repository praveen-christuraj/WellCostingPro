"""Fuel Cost Register services (Daily Cost Management).

The register is rig-scoped and manual. A user picks a rig and a date, captures
that day's AGO consumption, gas recording, stock and receipts, and allocates the
company-wise consumption to registered companies (and optionally to each
company's own categories). The whole day is saved in one transaction.

Material balance rules implemented here (the API never accepts these figures):

* **Opening stock** is captured once, on the rig's first active day. Every later
  day carries the preceding day's **actual closing stock** forward. The Override
  opening stock action is the only way to break the chain; the difference from
  the carried closing is an *opening adjustment*.
* **Receipts** are a daily entry, zero when empty.
* **AGO consumption** is the rig engines' litres plus every company line's
  litres. Gas is recorded in its own column and never joins this total.
* **Book closing** = opening + receipts − AGO consumption.
* **Actual closing** is the physical count; when it is not taken the book closing
  stands and the closing adjustment is zero.
* **Adjustments** = opening adjustment + closing adjustment.

Nothing is stored as JSON, and the balance is never persisted: it is recomputed
from the active chain on every read, so a back-dated insert, edit, deletion or
restore always produces a consistent carry-forward.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.models import (
    FuelCompany,
    FuelCompanyCategory,
    FuelCostCompanyLine,
    FuelCostEntry,
    Rig,
    Vendor,
)
from app.models.entities import User
from app.models.rig_well import uid
from app.schemas.fuel_cost import (
    FuelCompanyCategoryIn,
    FuelCompanyCategoryOut,
    FuelCompanyCategoryUpdate,
    FuelCompanyIn,
    FuelCompanyOut,
    FuelCompanyUpdate,
    FuelCostBalance,
    FuelCostBulkActionOut,
    FuelCostCompanyConsumptionOut,
    FuelCostCompanyConsumptionRow,
    FuelCostCompanyLineIn,
    FuelCostCompanyLineOut,
    FuelCostDayOut,
    FuelCostEntryOut,
    FuelCostEntrySave,
    FuelCostExportAudit,
    FuelCostImportRequest,
    FuelCostImportResponse,
    FuelCostOpeningStockUpdate,
    FuelCostReference,
    FuelCostRigOption,
    FuelCostVendorOption,
)
from app.services import audit

TEN_PLACES = Decimal("0.0000000001")
ZERO = Decimal("0")
MAX_IMPORT_ERRORS = 200


def _quantity(value: Decimal | int | str | None) -> Decimal:
    return Decimal(value or 0).quantize(TEN_PLACES, rounding=ROUND_HALF_UP)


def _litres_text(value: Decimal | int | str | None) -> str:
    return f"{_quantity(value):,.2f}"


def _actor_name(user: User) -> str:
    return user.full_name or user.email


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "This fuel record conflicts with an existing one. A rig can have only one "
                "fuel entry per date, and a company/category can appear once per day."
            ),
        ) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="The fuel cost register could not be saved because of a database error.",
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


def _day_label(entry: FuelCostEntry) -> str:
    return f"{entry.rig_code_snapshot} · {entry.cost_date.isoformat()}"[:255]


# ---------------------------------------------------------------------------
# Lookups and validation
# ---------------------------------------------------------------------------


def _rig_or_404(db: Session, organization_id: str, rig_id: str) -> Rig:
    rig = db.scalar(
        select(Rig).where(
            Rig.id == rig_id,
            Rig.organization_id == organization_id,
            Rig.is_deleted.is_(False),
        )
    )
    if rig is None:
        raise HTTPException(status_code=404, detail="Rig not found in this workspace")
    return rig


def _vendor_or_404(db: Session, organization_id: str, vendor_id: str) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if vendor is None:
        raise HTTPException(status_code=422, detail="The selected vendor is not available in this workspace")
    return vendor


def _company_or_404(
    db: Session, organization_id: str, company_id: str, *, deleted: bool = False
) -> FuelCompany:
    company = db.scalar(
        select(FuelCompany).where(
            FuelCompany.id == company_id,
            FuelCompany.organization_id == organization_id,
            FuelCompany.is_deleted.is_(deleted),
        )
    )
    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Fuel company not found in this workspace" if not deleted else "Deleted fuel company not found",
        )
    return company


def _category_or_404(
    db: Session, organization_id: str, category_id: str, *, deleted: bool = False
) -> FuelCompanyCategory:
    category = db.scalar(
        select(FuelCompanyCategory).where(
            FuelCompanyCategory.id == category_id,
            FuelCompanyCategory.organization_id == organization_id,
            FuelCompanyCategory.is_deleted.is_(deleted),
        )
    )
    if category is None:
        raise HTTPException(
            status_code=404,
            detail="Fuel company category not found in this workspace" if not deleted else "Deleted category not found",
        )
    return category


def _company_any_state(db: Session, organization_id: str, company_id: str) -> FuelCompany:
    """Load a company whether or not it is archived.

    Categories live under companies, and a company can be archived before its
    categories are tidied up, so category maintenance must not depend on the
    parent still being live.
    """
    company = db.scalar(
        select(FuelCompany).where(
            FuelCompany.id == company_id,
            FuelCompany.organization_id == organization_id,
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Fuel company not found in this workspace")
    return company


def _company_named(
    db: Session,
    organization_id: str,
    name: str,
    *,
    include_deleted: bool = True,
) -> FuelCompany | None:
    query = select(FuelCompany).where(
        FuelCompany.organization_id == organization_id,
        func.lower(FuelCompany.company_name) == name.strip().lower(),
    )
    if not include_deleted:
        query = query.where(FuelCompany.is_deleted.is_(False))
    return db.scalars(query).unique().first()


def _category_named(
    db: Session,
    organization_id: str,
    company_id: str,
    name: str,
    *,
    include_deleted: bool = True,
) -> FuelCompanyCategory | None:
    query = select(FuelCompanyCategory).where(
        FuelCompanyCategory.organization_id == organization_id,
        FuelCompanyCategory.company_id == company_id,
        func.lower(FuelCompanyCategory.category_name) == name.strip().lower(),
    )
    if not include_deleted:
        query = query.where(FuelCompanyCategory.is_deleted.is_(False))
    return db.scalars(query).unique().first()


# ---------------------------------------------------------------------------
# Output mappers
# ---------------------------------------------------------------------------


def _category_out(category: FuelCompanyCategory) -> FuelCompanyCategoryOut:
    return FuelCompanyCategoryOut(
        id=category.id,
        company_id=category.company_id,
        category_name=category.category_name,
        remarks=category.remarks,
        is_deleted=category.is_deleted,
        deleted_at=category.deleted_at,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def _company_out(company: FuelCompany, *, include_deleted_categories: bool = False) -> FuelCompanyOut:
    categories = [
        _category_out(category)
        for category in company.categories
        if include_deleted_categories or not category.is_deleted
    ]
    return FuelCompanyOut(
        id=company.id,
        company_name=company.company_name,
        vendor_id=company.vendor_id,
        vendor_code=company.vendor_code_snapshot,
        is_default=company.is_default,
        source=company.source,
        remarks=company.remarks,
        is_deleted=company.is_deleted,
        deleted_at=company.deleted_at,
        categories=categories,
        display_name=company.company_name,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


def _line_out(line: FuelCostCompanyLine) -> FuelCostCompanyLineOut:
    company_name = line.company.company_name if line.company else line.company_name_snapshot
    category_name = ""
    if line.category_id:
        category_name = line.category.category_name if line.category else line.category_name_snapshot
    elif line.category_name_snapshot:
        category_name = line.category_name_snapshot
    display = company_name if not category_name else f"{company_name} · {category_name}"
    return FuelCostCompanyLineOut(
        id=line.id,
        company_id=line.company_id,
        company_name=company_name,
        category_id=line.category_id,
        category_name=category_name,
        litres=_quantity(line.litres),
        remarks=line.remarks,
        source=line.source,
        sort_order=line.sort_order,
        display_name=display,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


def _company_total(entry: FuelCostEntry) -> Decimal:
    return _quantity(sum((Decimal(line.litres) for line in entry.lines), ZERO))


def _balance_out(values: dict[str, Any]) -> FuelCostBalance:
    return FuelCostBalance(**values)


def _entry_out(entry: FuelCostEntry, balance: dict[str, Any]) -> FuelCostEntryOut:
    company_total = _company_total(entry)
    return FuelCostEntryOut(
        id=entry.id,
        rig_id=entry.rig_id,
        rig_code=entry.rig_code_snapshot,
        rig_name=entry.rig_name_snapshot,
        cost_date=entry.cost_date,
        rig_engine_consumption=_quantity(entry.rig_engine_consumption),
        rig_engine_remarks=entry.rig_engine_remarks,
        gas_consumption=_quantity(entry.gas_consumption),
        gas_remarks=entry.gas_remarks,
        opening_stock=_quantity(entry.opening_stock) if entry.opening_stock is not None else None,
        opening_overridden=entry.opening_overridden,
        opening_remarks=entry.opening_remarks,
        receipt_quantity=_quantity(entry.receipt_quantity),
        receipt_remarks=entry.receipt_remarks,
        closing_stock=_quantity(entry.closing_stock) if entry.closing_stock is not None else None,
        closing_remarks=entry.closing_remarks,
        remarks=entry.remarks,
        revision=entry.revision or 0,
        line_count=len(entry.lines),
        company_consumption=company_total,
        total_consumption=_quantity(balance["total_consumption"]),
        balance=_balance_out(balance),
        display_name=_day_label(entry),
        is_deleted=entry.is_deleted,
        deleted_at=entry.deleted_at,
        created_by=entry.created_by,
        updated_by=entry.updated_by,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


# ---------------------------------------------------------------------------
# Material balance
# ---------------------------------------------------------------------------


def _balance_for_entries(entries: Iterable[FuelCostEntry]) -> dict[str, dict[str, Any]]:
    """Compute the material balance for one rig's entries, in date order."""
    ordered = sorted(entries, key=lambda item: (item.cost_date, item.id))
    result: dict[str, dict[str, Any]] = {}
    previous_closing: Decimal | None = None
    previous_date: date | None = None
    for entry in ordered:
        carried = previous_closing if previous_closing is not None else ZERO
        is_first = previous_closing is None
        stored_opening = _quantity(entry.opening_stock) if entry.opening_stock is not None else None
        if stored_opening is not None and (is_first or entry.opening_overridden):
            opening = stored_opening
        else:
            opening = carried
        opening_adjustment = ZERO if is_first else opening - carried

        receipt = _quantity(entry.receipt_quantity)
        engine = _quantity(entry.rig_engine_consumption)
        company = _company_total(entry)
        total_consumption = engine + company
        book_closing = opening + receipt - total_consumption
        actual_closing = (
            _quantity(entry.closing_stock) if entry.closing_stock is not None else book_closing
        )
        closing_adjustment = actual_closing - book_closing

        result[entry.id] = {
            "is_first_entry": is_first,
            "opening_overridden": bool(entry.opening_overridden) and not is_first,
            "carried_opening": _quantity(carried),
            "previous_date": previous_date,
            "opening_stock": _quantity(opening),
            "opening_adjustment": _quantity(opening_adjustment),
            "receipt": _quantity(receipt),
            "rig_engine_consumption": _quantity(engine),
            "company_consumption": _quantity(company),
            "total_consumption": _quantity(total_consumption),
            "book_closing_stock": _quantity(book_closing),
            "actual_closing_stock": _quantity(actual_closing),
            "closing_adjustment": _quantity(closing_adjustment),
            "adjustments": _quantity(opening_adjustment + closing_adjustment),
            "gas_consumption": _quantity(entry.gas_consumption),
        }
        previous_closing = actual_closing
        previous_date = entry.cost_date
    return result


def _balances_for_rigs(
    db: Session, organization_id: str, rig_ids: set[str]
) -> dict[str, dict[str, Any]]:
    """Balances for every active entry of the given rigs (date filtering never
    breaks the carry-forward chain, so all active days are considered)."""
    if not rig_ids:
        return {}
    rows = db.scalars(
        select(FuelCostEntry)
        .where(
            FuelCostEntry.organization_id == organization_id,
            FuelCostEntry.is_deleted.is_(False),
            FuelCostEntry.rig_id.in_(rig_ids),
        )
        .order_by(FuelCostEntry.rig_id, FuelCostEntry.cost_date, FuelCostEntry.id)
    ).unique().all()
    grouped: dict[str, list[FuelCostEntry]] = defaultdict(list)
    for row in rows:
        grouped[row.rig_id].append(row)
    balances: dict[str, dict[str, Any]] = {}
    for entries in grouped.values():
        balances.update(_balance_for_entries(entries))
    return balances


def _isolated_balance(entry: FuelCostEntry) -> dict[str, Any]:
    """A deleted day's own figures, outside the active chain."""
    opening = _quantity(entry.opening_stock) if entry.opening_stock is not None else ZERO
    receipt = _quantity(entry.receipt_quantity)
    engine = _quantity(entry.rig_engine_consumption)
    company = _company_total(entry)
    total_consumption = engine + company
    book_closing = opening + receipt - total_consumption
    actual_closing = _quantity(entry.closing_stock) if entry.closing_stock is not None else book_closing
    closing_adjustment = actual_closing - book_closing
    return {
        "is_first_entry": False,
        "opening_overridden": bool(entry.opening_overridden),
        "carried_opening": opening,
        "previous_date": None,
        "opening_stock": _quantity(opening),
        "opening_adjustment": ZERO,
        "receipt": _quantity(receipt),
        "rig_engine_consumption": _quantity(engine),
        "company_consumption": _quantity(company),
        "total_consumption": _quantity(total_consumption),
        "book_closing_stock": _quantity(book_closing),
        "actual_closing_stock": _quantity(actual_closing),
        "closing_adjustment": _quantity(closing_adjustment),
        "adjustments": _quantity(closing_adjustment),
        "gas_consumption": _quantity(entry.gas_consumption),
    }


def _day_balance_preview(
    db: Session,
    organization_id: str,
    rig_id: str,
    cost_date: date,
    *,
    exclude_entry_id: str | None = None,
) -> dict[str, Any]:
    """What the balance will look like for a day that is not saved yet."""
    conditions = [
        FuelCostEntry.organization_id == organization_id,
        FuelCostEntry.rig_id == rig_id,
        FuelCostEntry.is_deleted.is_(False),
    ]
    if exclude_entry_id:
        conditions.append(FuelCostEntry.id != exclude_entry_id)
    entries = list(db.scalars(select(FuelCostEntry).where(*conditions)).unique().all())
    balances = _balance_for_entries(entries)
    earlier = [entry for entry in entries if entry.cost_date < cost_date]
    if not earlier:
        return {
            "is_first_entry": True,
            "opening_overridden": False,
            "carried_opening": ZERO,
            "previous_date": None,
            "opening_stock": ZERO,
            "opening_adjustment": ZERO,
            "receipt": ZERO,
            "rig_engine_consumption": ZERO,
            "company_consumption": ZERO,
            "total_consumption": ZERO,
            "book_closing_stock": ZERO,
            "actual_closing_stock": ZERO,
            "closing_adjustment": ZERO,
            "adjustments": ZERO,
            "gas_consumption": ZERO,
        }
    previous = max(earlier, key=lambda item: (item.cost_date, item.id))
    carried = _quantity(balances[previous.id]["actual_closing_stock"])
    return {
        "is_first_entry": False,
        "opening_overridden": False,
        "carried_opening": carried,
        "previous_date": previous.cost_date,
        "opening_stock": carried,
        "opening_adjustment": ZERO,
        "receipt": ZERO,
        "rig_engine_consumption": ZERO,
        "company_consumption": ZERO,
        "total_consumption": ZERO,
        "book_closing_stock": carried,
        "actual_closing_stock": carried,
        "closing_adjustment": ZERO,
        "adjustments": ZERO,
        "gas_consumption": ZERO,
    }


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def reference_data(db: Session, organization_id: str) -> FuelCostReference:
    rigs = db.scalars(
        select(Rig)
        .where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False))
        .order_by(Rig.rig_code)
    ).all()
    companies = db.scalars(
        select(FuelCompany)
        .where(
            FuelCompany.organization_id == organization_id, FuelCompany.is_deleted.is_(False)
        )
        .order_by(FuelCompany.company_name)
    ).unique().all()
    linked_vendors = {company.vendor_id for company in companies if company.vendor_id}
    vendors = db.scalars(
        select(Vendor)
        .where(Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False))
        .order_by(Vendor.vendor_name)
    ).all()
    return FuelCostReference(
        rigs=[
            FuelCostRigOption(
                id=rig.id,
                rig_code=rig.rig_code,
                rig_name=rig.rig_name,
                display_name=f"{rig.rig_code} · {rig.rig_name}",
            )
            for rig in rigs
        ],
        companies=[_company_out(company) for company in companies],
        vendors=[
            FuelCostVendorOption(
                id=vendor.id,
                vendor_code=vendor.vendor_code,
                vendor_name=vendor.vendor_name,
                vendor_type=vendor.vendor_type,
                status=vendor.status,
                registered=vendor.id in linked_vendors,
                display_name=f"{vendor.vendor_code} · {vendor.vendor_name}",
            )
            for vendor in vendors
        ],
    )


# ---------------------------------------------------------------------------
# Companies and categories
# ---------------------------------------------------------------------------


def list_companies(
    db: Session, organization_id: str, *, deleted: bool = False
) -> list[FuelCompanyOut]:
    rows = db.scalars(
        select(FuelCompany)
        .where(
            FuelCompany.organization_id == organization_id,
            FuelCompany.is_deleted.is_(deleted),
        )
        .order_by(FuelCompany.company_name)
    ).unique().all()
    return [_company_out(company, include_deleted_categories=True) for company in rows]


def create_company(
    db: Session, organization_id: str, data: FuelCompanyIn, user: User, request: Request | None
) -> FuelCompanyOut:
    name = data.company_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Company name is mandatory")
    vendor = _vendor_or_404(db, organization_id, data.vendor_id) if data.vendor_id else None
    existing = _company_named(db, organization_id, name)
    if existing is not None and not existing.is_deleted:
        raise HTTPException(
            status_code=409, detail=f"“{existing.company_name}” is already registered for fuel consumption"
        )
    if existing is not None:
        # Revive the soft-deleted company rather than blocking a familiar name.
        existing.is_deleted = False
        existing.deleted_at = None
        existing.company_name = name
        existing.vendor_id = vendor.id if vendor else existing.vendor_id
        existing.vendor_code_snapshot = vendor.vendor_code if vendor else existing.vendor_code_snapshot
        existing.is_default = data.is_default
        existing.remarks = data.remarks
        existing.source = "vendor" if vendor else "manual"
        existing.updated_by = _actor_name(user)
        company = existing
        action = "restore"
        summary = f"Restored fuel company “{name}”" + (" to the daily entry set" if data.is_default else "")
    else:
        company = FuelCompany(
            id=uid(),
            organization_id=organization_id,
            company_name=name,
            vendor_id=vendor.id if vendor else None,
            vendor_code_snapshot=vendor.vendor_code if vendor else "",
            is_default=data.is_default,
            source="vendor" if vendor else "manual",
            remarks=data.remarks,
            created_by=_actor_name(user),
            updated_by=_actor_name(user),
        )
        db.add(company)
        action = "create"
        summary = (
            f"Registered fuel company “{name}”"
            + (f" from vendor {vendor.vendor_code}" if vendor else "")
            + (" in the daily entry set" if data.is_default else "")
        )
    db.flush()
    _audit(
        db,
        user=user,
        action=action,
        entity_type="fuel_company",
        entity_id=company.id,
        entity_label=name,
        summary=summary,
        request=request,
    )
    _commit(db)
    return _company_out(_company_or_404(db, organization_id, company.id))


def update_company(
    db: Session,
    organization_id: str,
    company_id: str,
    data: FuelCompanyUpdate,
    user: User,
    request: Request | None,
) -> FuelCompanyOut:
    company = _company_or_404(db, organization_id, company_id)
    changes: list[str] = []
    if data.company_name is not None:
        name = data.company_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Company name is mandatory")
        clash = _company_named(db, organization_id, name)
        if clash is not None and clash.id != company.id:
            raise HTTPException(status_code=409, detail=f"“{clash.company_name}” is already registered")
        if name != company.company_name:
            changes.append(f"name → “{name}”")
            company.company_name = name
    if data.vendor_id is not None:
        if data.vendor_id:
            vendor = _vendor_or_404(db, organization_id, data.vendor_id)
            if company.vendor_id != vendor.id:
                changes.append(f"vendor → {vendor.vendor_code}")
            company.vendor_id = vendor.id
            company.vendor_code_snapshot = vendor.vendor_code
        else:
            if company.vendor_id:
                changes.append("vendor link removed")
            company.vendor_id = None
            company.vendor_code_snapshot = ""
    if data.is_default is not None and data.is_default != company.is_default:
        changes.append(
            "added to the daily entry set" if data.is_default else "removed from the daily entry set"
        )
        company.is_default = data.is_default
    if data.remarks is not None:
        company.remarks = data.remarks
    company.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action="update",
        entity_type="fuel_company",
        entity_id=company.id,
        entity_label=company.company_name,
        summary=f"Updated fuel company “{company.company_name}”"
        + (f": {'; '.join(changes)}" if changes else ""),
        request=request,
    )
    _commit(db)
    return _company_out(_company_or_404(db, organization_id, company.id))


def delete_company(
    db: Session, organization_id: str, company_id: str, user: User, request: Request | None
) -> FuelCompanyOut:
    company = _company_or_404(db, organization_id, company_id)
    company.is_deleted = True
    company.deleted_at = datetime.now(timezone.utc)
    company.is_default = False
    company.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action="delete",
        entity_type="fuel_company",
        entity_id=company.id,
        entity_label=company.company_name,
        summary=(
            f"Removed fuel company “{company.company_name}” from the register; "
            "its recorded consumption is kept"
        ),
        request=request,
    )
    _commit(db)
    return _company_out(company, include_deleted_categories=True)


def restore_company(
    db: Session, organization_id: str, company_id: str, user: User, request: Request | None
) -> FuelCompanyOut:
    company = _company_or_404(db, organization_id, company_id, deleted=True)
    company.is_deleted = False
    company.deleted_at = None
    company.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action="restore",
        entity_type="fuel_company",
        entity_id=company.id,
        entity_label=company.company_name,
        summary=f"Restored fuel company “{company.company_name}”",
        request=request,
    )
    _commit(db)
    return _company_out(company)


def create_category(
    db: Session,
    organization_id: str,
    company_id: str,
    data: FuelCompanyCategoryIn,
    user: User,
    request: Request | None,
) -> FuelCompanyOut:
    company = _company_or_404(db, organization_id, company_id)
    name = data.category_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Category name is mandatory")
    existing = _category_named(db, organization_id, company.id, name)
    if existing is not None and not existing.is_deleted:
        raise HTTPException(
            status_code=409, detail=f"“{name}” is already a category of {company.company_name}"
        )
    if existing is not None:
        existing.is_deleted = False
        existing.deleted_at = None
        existing.category_name = name
        existing.remarks = data.remarks
        existing.updated_by = _actor_name(user)
        category = existing
        action, summary = "restore", f"Restored category “{name}” under {company.company_name}"
    else:
        category = FuelCompanyCategory(
            id=uid(),
            organization_id=organization_id,
            company_id=company.id,
            category_name=name,
            remarks=data.remarks,
            created_by=_actor_name(user),
            updated_by=_actor_name(user),
        )
        action, summary = "create", f"Added category “{name}” under {company.company_name}"
    if all(row.id != category.id for row in company.categories):
        company.categories.append(category)
    db.flush()
    _audit(
        db,
        user=user,
        action=action,
        entity_type="fuel_company_category",
        entity_id=company.id,
        entity_label=f"{company.company_name} · {name}",
        summary=summary,
        request=request,
    )
    _commit(db)
    return _company_out(_company_or_404(db, organization_id, company.id))


def update_category(
    db: Session,
    organization_id: str,
    category_id: str,
    data: FuelCompanyCategoryUpdate,
    user: User,
    request: Request | None,
) -> FuelCompanyOut:
    category = _category_or_404(db, organization_id, category_id)
    company = _company_any_state(db, organization_id, category.company_id)
    changes: list[str] = []
    if data.category_name is not None:
        name = data.category_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Category name is mandatory")
        clash = _category_named(db, organization_id, company.id, name)
        if clash is not None and clash.id != category.id:
            raise HTTPException(status_code=409, detail=f"“{clash.category_name}” already exists under this company")
        if name != category.category_name:
            changes.append(f"name → “{name}”")
            category.category_name = name
    if data.remarks is not None:
        category.remarks = data.remarks
    category.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action="update",
        entity_type="fuel_company_category",
        entity_id=category.id,
        entity_label=f"{company.company_name} · {category.category_name}",
        summary=f"Updated category “{category.category_name}” under {company.company_name}"
        + (f": {'; '.join(changes)}" if changes else ""),
        request=request,
    )
    _commit(db)
    return _company_out(company)


def delete_category(
    db: Session, organization_id: str, category_id: str, user: User, request: Request | None
) -> FuelCompanyOut:
    category = _category_or_404(db, organization_id, category_id)
    company = _company_any_state(db, organization_id, category.company_id)
    category.is_deleted = True
    category.deleted_at = datetime.now(timezone.utc)
    category.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action="delete",
        entity_type="fuel_company_category",
        entity_id=category.id,
        entity_label=f"{company.company_name} · {category.category_name}",
        summary=f"Removed category “{category.category_name}” under {company.company_name}; recorded consumption is kept",
        request=request,
    )
    _commit(db)
    return _company_out(company)


def restore_category(
    db: Session, organization_id: str, category_id: str, user: User, request: Request | None
) -> FuelCompanyOut:
    category = _category_or_404(db, organization_id, category_id, deleted=True)
    # The company may itself be live or still deleted; either way its category
    # can be restored (the dialog shows both in one place).
    company = db.scalar(
        select(FuelCompany).where(
            FuelCompany.id == category.company_id,
            FuelCompany.organization_id == organization_id,
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Fuel company not found in this workspace")
    category.is_deleted = False
    category.deleted_at = None
    category.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action="restore",
        entity_type="fuel_company_category",
        entity_id=category.id,
        entity_label=f"{company.company_name} · {category.category_name}",
        summary=f"Restored category “{category.category_name}” under {company.company_name}",
        request=request,
    )
    _commit(db)
    return _company_out(company, include_deleted_categories=True)


# ---------------------------------------------------------------------------
# Fuel days
# ---------------------------------------------------------------------------


def _entry_query(organization_id: str, *, deleted: bool):
    return select(FuelCostEntry).where(
        FuelCostEntry.organization_id == organization_id,
        FuelCostEntry.is_deleted.is_(deleted),
    )


def _entry_or_404(
    db: Session, organization_id: str, entry_id: str, *, deleted: bool = False
) -> FuelCostEntry:
    entry = db.scalars(
        _entry_query(organization_id, deleted=deleted)
        .options(joinedload(FuelCostEntry.lines))
        .where(FuelCostEntry.id == entry_id)
    ).unique().first()
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Fuel register entry not found in this workspace" if not deleted else "Deleted fuel entry not found",
        )
    return entry


def _has_earlier(
    db: Session,
    organization_id: str,
    rig_id: str,
    cost_date: date,
    *,
    exclude_entry_id: str | None = None,
) -> FuelCostEntry | None:
    query = select(FuelCostEntry).where(
        FuelCostEntry.organization_id == organization_id,
        FuelCostEntry.rig_id == rig_id,
        FuelCostEntry.is_deleted.is_(False),
        FuelCostEntry.cost_date < cost_date,
    )
    if exclude_entry_id:
        query = query.where(FuelCostEntry.id != exclude_entry_id)
    return db.scalars(query.order_by(FuelCostEntry.cost_date.desc(), FuelCostEntry.id)).first()


def _existing_day(
    db: Session, organization_id: str, rig_id: str, cost_date: date
) -> FuelCostEntry | None:
    return db.scalars(
        select(FuelCostEntry)
        .options(joinedload(FuelCostEntry.lines))
        .where(
            FuelCostEntry.organization_id == organization_id,
            FuelCostEntry.rig_id == rig_id,
            FuelCostEntry.cost_date == cost_date,
        )
    ).unique().first()


def _validate_line_payload(
    db: Session, organization_id: str, lines: Sequence[FuelCostCompanyLineIn]
) -> dict[str, FuelCompany]:
    """Check every company/category and reject duplicate (company, category) rows."""
    companies: dict[str, FuelCompany] = {}
    seen: dict[tuple[str, str | None], int] = {}
    for index, line in enumerate(lines, start=1):
        if line.company_id not in companies:
            companies[line.company_id] = _company_or_404(db, organization_id, line.company_id)
        company = companies[line.company_id]
        category_id: str | None = line.category_id or None
        if category_id:
            category = _category_or_404(db, organization_id, category_id)
            if category.company_id != company.id:
                raise HTTPException(
                    status_code=422,
                    detail=f"Row {index}: the category “{category.category_name}” belongs to another company",
                )
        key = (company.id, category_id)
        if key in seen:
            label = company.company_name + (
                f" · {_category_or_404(db, organization_id, category_id).category_name}" if category_id else ""
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Row {index}: {label} already appears on row {seen[key]}. Combine the litres into "
                    "one row or choose another category."
                ),
            )
        seen[key] = index
    return companies


def _apply_lines(
    db: Session,
    organization_id: str,
    entry: FuelCostEntry,
    lines: Sequence[FuelCostCompanyLineIn],
    companies: dict[str, FuelCompany],
) -> tuple[int, int, int]:
    """Make the payload authoritative for the day's company lines."""
    existing = {line.id: line for line in entry.lines}
    kept: set[str] = set()
    added = updated = 0
    for order, payload in enumerate(lines):
        if payload.id and payload.id not in existing:
            raise HTTPException(
                status_code=422,
                detail="A company consumption line does not belong to this fuel day. Reload the day and retry.",
            )
        category_id = payload.category_id or None
        category = _category_or_404(db, organization_id, category_id) if category_id else None
        company = companies[payload.company_id]
        if payload.id:
            line = existing[payload.id]
            kept.add(line.id)
            line.company_id = company.id
            line.company_name_snapshot = company.company_name
            line.category_id = category.id if category else None
            line.category_name_snapshot = category.category_name if category else ""
            line.litres = _quantity(payload.litres)
            line.remarks = payload.remarks
            line.source = payload.source
            line.sort_order = order
            line.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            entry.lines.append(
                FuelCostCompanyLine(
                    id=uid(),
                    organization_id=organization_id,
                    company_id=company.id,
                    company_name_snapshot=company.company_name,
                    category_id=category.id if category else None,
                    category_name_snapshot=category.category_name if category else "",
                    litres=_quantity(payload.litres),
                    remarks=payload.remarks,
                    source=payload.source,
                    sort_order=order,
                )
            )
            added += 1
    removed = 0
    for line_id, line in existing.items():
        if line_id not in kept:
            entry.lines.remove(line)
            removed += 1
    return added, updated, removed


def _meaningful_day(
    engine: Decimal,
    gas: Decimal,
    receipt: Decimal,
    closing: Decimal | None,
    lines: Sequence[FuelCostCompanyLineIn],
) -> bool:
    return bool(engine or gas or receipt or closing is not None or lines)


def save_entry(
    db: Session,
    organization_id: str,
    data: FuelCostEntrySave,
    user: User,
    request: Request | None,
    *,
    entry_id: str | None = None,
    can_override_opening: bool = False,
) -> FuelCostDayOut:
    """Create or replace one rig day in a single transaction."""
    rig = _rig_or_404(db, organization_id, data.rig_id)
    if entry_id:
        entry = _entry_or_404(db, organization_id, entry_id)
        if data.expected_revision is not None and data.expected_revision != (entry.revision or 0):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This fuel day was changed by someone else after you opened it. Reload the day "
                    "to see the current figures before saving."
                ),
            )
        day = _existing_day(db, organization_id, rig.id, data.cost_date)
        if day is not None and day.id != entry.id:
            raise HTTPException(
                status_code=409,
                detail=f"{rig.rig_code} already has a fuel entry on {data.cost_date.isoformat()}",
            )
        entry.rig_id = rig.id
        entry.rig_code_snapshot = rig.rig_code
        entry.rig_name_snapshot = rig.rig_name
        entry.cost_date = data.cost_date
        action = "update"
    else:
        if _existing_day(db, organization_id, rig.id, data.cost_date) is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{rig.rig_code} already has a fuel entry on {data.cost_date.isoformat()}. "
                    "Open that day to edit it, or restore it from Deleted Entries."
                ),
            )
        entry = FuelCostEntry(
            id=uid(),
            organization_id=organization_id,
            rig_id=rig.id,
            rig_code_snapshot=rig.rig_code,
            rig_name_snapshot=rig.rig_name,
            cost_date=data.cost_date,
            created_by=_actor_name(user),
        )
        db.add(entry)
        action = "create"

    companies = _validate_line_payload(db, organization_id, data.lines)
    if not _meaningful_day(
        data.rig_engine_consumption,
        data.gas_consumption,
        data.receipt_quantity,
        data.closing_stock,
        data.lines,
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Record at least one of: rig engine consumption, gas consumption, a receipt, "
                "a closing stock or a company consumption line."
            ),
        )

    earlier = _has_earlier(
        db, organization_id, rig.id, data.cost_date, exclude_entry_id=entry.id if entry_id else None
    )
    is_first = earlier is None

    if data.clear_opening_override:
        if is_first:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The first day of a rig keeps its opening stock; it is the anchor the material "
                    "balance starts from."
                ),
            )
        if not can_override_opening:
            raise HTTPException(
                status_code=403,
                detail="Clearing an opening-stock override needs the fuel opening-stock override permission.",
            )
        entry.opening_stock = None
        entry.opening_overridden = False
        entry.opening_remarks = ""
    elif data.opening_stock is None:
        if is_first and data.opening_overridden:
            raise HTTPException(status_code=422, detail="Enter the opening stock for the first day of this rig")
        if entry_id:
            # Omitted opening keeps what is stored; the Override action is the only
            # way to change it. A first day must still carry an anchor.
            if is_first and entry.opening_stock is None:
                raise HTTPException(
                    status_code=422,
                    detail="Enter the opening stock for the first day of this rig",
                )
        elif is_first:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Opening stock is mandatory on the first fuel entry for this rig. "
                    "Every later day carries the previous actual closing stock forward."
                ),
            )
    else:
        if is_first:
            entry.opening_stock = _quantity(data.opening_stock)
            entry.opening_overridden = False
        else:
            if not can_override_opening:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Changing the opening stock needs the fuel opening-stock override permission. "
                        "Leave it blank to carry the previous closing stock."
                    ),
                )
            if not data.opening_overridden:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "This day already has an earlier entry. Set the override flag or leave the "
                        "opening stock blank so it is carried forward."
                    ),
                )
            entry.opening_stock = _quantity(data.opening_stock)
            entry.opening_overridden = True
        if data.opening_remarks:
            entry.opening_remarks = data.opening_remarks
    if data.opening_remarks and data.opening_stock is not None:
        entry.opening_remarks = data.opening_remarks

    entry.rig_engine_consumption = _quantity(data.rig_engine_consumption)
    entry.rig_engine_remarks = data.rig_engine_remarks
    entry.gas_consumption = _quantity(data.gas_consumption)
    entry.gas_remarks = data.gas_remarks
    entry.receipt_quantity = _quantity(data.receipt_quantity)
    entry.receipt_remarks = data.receipt_remarks
    entry.closing_stock = _quantity(data.closing_stock) if data.closing_stock is not None else None
    entry.closing_remarks = data.closing_remarks
    entry.remarks = data.remarks
    entry.updated_by = _actor_name(user)
    entry.revision = (entry.revision or 0) + 1

    added, updated, removed = _apply_lines(db, organization_id, entry, data.lines, companies)
    db.flush()

    db.refresh(entry)
    balances = _balance_for_entries(
        db.scalars(
            select(FuelCostEntry).where(
                FuelCostEntry.organization_id == organization_id,
                FuelCostEntry.rig_id == rig.id,
                FuelCostEntry.is_deleted.is_(False),
            )
        ).unique().all()
    )
    balance = balances[entry.id]
    total = _quantity(balance["total_consumption"])
    _audit(
        db,
        user=user,
        action=action,
        entity_type="fuel_cost",
        entity_id=entry.id,
        entity_label=_day_label(entry),
        summary=(
            f"{'Saved' if action == 'update' else 'Created'} the fuel day of {rig.rig_code} on "
            f"{entry.cost_date.isoformat()}: {_litres_text(entry.rig_engine_consumption)} L rig engines, "
            f"{_litres_text(balance['company_consumption'])} L companies, {_litres_text(total)} L AGO total, "
            f"{_litres_text(entry.gas_consumption)} L gas, opening {_litres_text(balance['opening_stock'])} L, "
            f"book closing {_litres_text(balance['book_closing_stock'])} L, actual closing "
            f"{_litres_text(balance['actual_closing_stock'])} L, adjustments "
            f"{_litres_text(balance['adjustments'])} L"
            + (f"; {added} company line(s) added, {updated} updated, {removed} removed" if added or updated or removed else "")
        ),
        request=request,
    )
    _commit(db)
    return day_for_rig_date(db, organization_id, rig.id, entry.cost_date)


def set_opening_stock(
    db: Session,
    organization_id: str,
    entry_id: str,
    data: FuelCostOpeningStockUpdate,
    user: User,
    request: Request | None,
) -> FuelCostDayOut:
    """Override, correct or clear a day's opening stock (separately grantable)."""
    entry = _entry_or_404(db, organization_id, entry_id)
    earlier = _has_earlier(db, organization_id, entry.rig_id, entry.cost_date, exclude_entry_id=entry.id)
    is_first = earlier is None
    previous = _quantity(entry.opening_stock) if entry.opening_stock is not None else None
    siblings = list(
        db.scalars(
            select(FuelCostEntry).where(
                FuelCostEntry.organization_id == organization_id,
                FuelCostEntry.rig_id == entry.rig_id,
                FuelCostEntry.is_deleted.is_(False),
            )
        ).unique().all()
    )
    sibling_balances = _balance_for_entries(siblings)
    earlier_entries = [
        row for row in siblings if row.id != entry.id and row.cost_date < entry.cost_date
    ]
    carried_opening = (
        _quantity(
            sibling_balances[
                max(earlier_entries, key=lambda row: (row.cost_date, row.id)).id
            ]["actual_closing_stock"]
        )
        if earlier_entries
        else ZERO
    )

    if data.clear_override:
        if is_first:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The first day of a rig keeps its opening stock; it is the anchor the material "
                    "balance starts from. Enter a corrected opening stock instead."
                ),
            )
        entry.opening_stock = None
        entry.opening_overridden = False
        entry.opening_remarks = ""
        summary = (
            f"Cleared the opening-stock override on {_day_label(entry)}; the opening is carried from "
            "the previous actual closing stock"
        )
    else:
        if data.opening_stock is None:
            raise HTTPException(status_code=422, detail="Enter the opening stock to apply")
        if is_first:
            entry.opening_stock = _quantity(data.opening_stock)
            entry.opening_overridden = False
            summary = (
                f"Corrected the first-day opening stock of {_day_label(entry)} "
                f"from {_litres_text(previous)} L to {_litres_text(data.opening_stock)} L"
            )
        else:
            entry.opening_stock = _quantity(data.opening_stock)
            entry.opening_overridden = True
            summary = (
                f"Overrode the opening stock of {_day_label(entry)} from the carried "
                f"{_litres_text(carried_opening)} L to {_litres_text(data.opening_stock)} L "
                f"(adjustment {_litres_text(_quantity(data.opening_stock) - carried_opening)} L)"
            )
        entry.opening_remarks = data.remarks
    entry.updated_by = _actor_name(user)
    entry.revision = (entry.revision or 0) + 1
    _audit(
        db,
        user=user,
        action="opening-stock",
        entity_type="fuel_cost",
        entity_id=entry.id,
        entity_label=_day_label(entry),
        summary=summary,
        request=request,
    )
    _commit(db)
    return day_for_rig_date(db, organization_id, entry.rig_id, entry.cost_date)


def day_for_rig_date(
    db: Session, organization_id: str, rig_id: str, cost_date: date
) -> FuelCostDayOut:
    rig = _rig_or_404(db, organization_id, rig_id)
    entry = _existing_day(db, organization_id, rig.id, cost_date)
    if entry is None:
        preview = _day_balance_preview(db, organization_id, rig.id, cost_date)
        return FuelCostDayOut(
            rig_id=rig.id,
            rig_code=rig.rig_code,
            rig_name=rig.rig_name,
            cost_date=cost_date,
            entry=None,
            lines=[],
            balance=_balance_out(preview),
        )
    balances = _balance_for_entries(
        db.scalars(
            select(FuelCostEntry).where(
                FuelCostEntry.organization_id == organization_id,
                FuelCostEntry.rig_id == rig.id,
                FuelCostEntry.is_deleted.is_(False),
            )
        ).unique().all()
    )
    balance = balances[entry.id]
    return FuelCostDayOut(
        rig_id=rig.id,
        rig_code=rig.rig_code,
        rig_name=rig.rig_name,
        cost_date=cost_date,
        entry=_entry_out(entry, balance),
        lines=[_line_out(line) for line in entry.lines],
        balance=_balance_out(balance),
    )


def list_entries(
    db: Session,
    organization_id: str,
    *,
    rig_id: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    deleted: bool = False,
) -> list[FuelCostEntryOut]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    query = _entry_query(organization_id, deleted=deleted)
    if rig_id:
        query = query.where(FuelCostEntry.rig_id == rig_id)
    date_conditions = []
    if date_from is not None:
        date_conditions.append(FuelCostEntry.cost_date >= date_from)
    if date_to is not None:
        date_conditions.append(FuelCostEntry.cost_date <= date_to)
    rows = db.scalars(
        query.where(*date_conditions).order_by(FuelCostEntry.cost_date.desc(), FuelCostEntry.rig_code_snapshot)
    ).unique().all()
    if deleted:
        return [_entry_out(row, _isolated_balance(row)) for row in rows]
    # Carry-forward is computed over every active day of the involved rigs, so a
    # date filter never changes an opening stock.
    rig_ids = {row.rig_id for row in rows}
    balances = _balances_for_rigs(db, organization_id, rig_ids)
    return [_entry_out(row, balances[row.id]) for row in rows]


def _selected_entries(
    db: Session, organization_id: str, ids: Sequence[str], *, deleted: bool
) -> list[FuelCostEntry]:
    rows = db.scalars(
        _entry_query(organization_id, deleted=deleted)
        .options(joinedload(FuelCostEntry.lines))
        .where(FuelCostEntry.id.in_(list(ids)))
    ).unique().all()
    if len(rows) != len(set(ids)):
        raise HTTPException(
            status_code=404,
            detail="One or more selected fuel entries were not found in this workspace",
        )
    return rows


def _reanchor_after_removal(
    db: Session, organization_id: str, rows: Sequence[FuelCostEntry], user: User
) -> dict[str, str]:
    """Keep the stock chain intact when the earliest day of a rig is removed.

    The earliest active day holds the opening anchor. If it is deleted, the next
    surviving day becomes the first day; its carried opening is persisted as the
    new anchor so the physical stock is not reset to zero.
    """
    removed_ids = {row.id for row in rows}
    notes: dict[str, str] = {}
    for rig_id in {row.rig_id for row in rows}:
        entries = list(
            db.scalars(
                select(FuelCostEntry).where(
                    FuelCostEntry.organization_id == organization_id,
                    FuelCostEntry.rig_id == rig_id,
                    FuelCostEntry.is_deleted.is_(False),
                )
            ).unique().all()
        )
        ordered = sorted(entries, key=lambda item: (item.cost_date, item.id))
        if not ordered or ordered[0].id not in removed_ids:
            continue
        survivors = [entry for entry in ordered if entry.id not in removed_ids]
        if not survivors:
            continue
        balances = _balance_for_entries(ordered)
        new_first = survivors[0]
        if new_first.opening_stock is not None and not new_first.opening_overridden:
            continue
        opening = _quantity(balances[new_first.id]["opening_stock"])
        new_first.opening_stock = opening
        new_first.opening_overridden = False
        new_first.opening_remarks = (
            new_first.opening_remarks
            or "Opening stock re-anchored when the earlier fuel day was removed"
        )
        new_first.updated_by = _actor_name(user)
        notes[rig_id] = (
            f" Opening stock of {new_first.cost_date.isoformat()} re-anchored at {_litres_text(opening)} L."
        )
    return notes


def soft_delete_entries(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None
) -> FuelCostBulkActionOut:
    rows = _selected_entries(db, organization_id, ids, deleted=False)
    notes = _reanchor_after_removal(db, organization_id, rows, user)
    for entry in rows:
        entry.is_deleted = True
        entry.deleted_at = datetime.now(timezone.utc)
        entry.updated_by = _actor_name(user)
        _audit(
            db,
            user=user,
            action="delete",
            entity_type="fuel_cost",
            entity_id=entry.id,
            entity_label=_day_label(entry),
            summary=f"Moved the fuel day of {_day_label(entry)} to Deleted Entries"
            + notes.get(entry.rig_id, ""),
            request=request,
        )
    _commit(db)
    return FuelCostBulkActionOut(affected_count=len(rows))


def restore_entries(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None
) -> FuelCostBulkActionOut:
    rows = _selected_entries(db, organization_id, ids, deleted=True)
    for entry in rows:
        duplicate = db.scalar(
            select(FuelCostEntry.id).where(
                FuelCostEntry.organization_id == organization_id,
                FuelCostEntry.rig_id == entry.rig_id,
                FuelCostEntry.cost_date == entry.cost_date,
                FuelCostEntry.id != entry.id,
                FuelCostEntry.is_deleted.is_(False),
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot restore the fuel day of {entry.rig_code_snapshot} on "
                    f"{entry.cost_date.isoformat()}: an active entry already exists for that date."
                ),
            )
    for entry in rows:
        entry.is_deleted = False
        entry.deleted_at = None
        entry.updated_by = _actor_name(user)
        _audit(
            db,
            user=user,
            action="restore",
            entity_type="fuel_cost",
            entity_id=entry.id,
            entity_label=_day_label(entry),
            summary=f"Restored the fuel day of {_day_label(entry)}",
            request=request,
        )
    _commit(db)
    return FuelCostBulkActionOut(affected_count=len(rows))


def permanently_delete_entries(
    db: Session, organization_id: str, ids: Sequence[str], user: User, request: Request | None
) -> FuelCostBulkActionOut:
    rows = _selected_entries(db, organization_id, ids, deleted=True)
    count = len(rows)
    for entry in rows:
        _audit(
            db,
            user=user,
            action="permanent-delete",
            entity_type="fuel_cost",
            entity_id=entry.id,
            entity_label=_day_label(entry),
            summary=f"Permanently deleted the fuel day of {_day_label(entry)}",
            request=request,
        )
        db.delete(entry)
    _commit(db)
    return FuelCostBulkActionOut(affected_count=count)


# ---------------------------------------------------------------------------
# Company / category classification
# ---------------------------------------------------------------------------


def company_consumption(
    db: Session,
    organization_id: str,
    rig_id: str,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> FuelCostCompanyConsumptionOut:
    rig = _rig_or_404(db, organization_id, rig_id)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    lines = db.scalars(
        select(FuelCostCompanyLine)
        .join(FuelCostEntry, FuelCostEntry.id == FuelCostCompanyLine.entry_id)
        .options(joinedload(FuelCostCompanyLine.company), joinedload(FuelCostCompanyLine.category))
        .where(
            FuelCostCompanyLine.organization_id == organization_id,
            FuelCostEntry.rig_id == rig.id,
            FuelCostEntry.is_deleted.is_(False),
            *([FuelCostEntry.cost_date >= date_from] if date_from else []),
            *([FuelCostEntry.cost_date <= date_to] if date_to else []),
        )
        .order_by(FuelCostCompanyLine.sort_order)
    ).unique().all()
    buckets: dict[tuple[str, str | None], dict[str, Any]] = {}
    for line in lines:
        key = (line.company_id, line.category_id)
        company_name = line.company.company_name if line.company else line.company_name_snapshot
        category_name = ""
        if line.category_id:
            category_name = line.category.category_name if line.category else line.category_name_snapshot
        bucket = buckets.setdefault(
            key,
            {
                "company_id": line.company_id,
                "company_name": company_name,
                "category_id": line.category_id,
                "category_name": category_name,
                "litres": ZERO,
                "days": set(),
                "lines": 0,
            },
        )
        bucket["litres"] += Decimal(line.litres or 0)
        bucket["days"].add(line.entry_id)
        bucket["lines"] += 1
    rows = [
        FuelCostCompanyConsumptionRow(
            company_id=bucket["company_id"],
            company_name=bucket["company_name"],
            category_id=bucket["category_id"],
            category_name=bucket["category_name"],
            litres=_quantity(bucket["litres"]),
            day_count=len(bucket["days"]),
            line_count=bucket["lines"],
        )
        for bucket in buckets.values()
    ]
    rows.sort(key=lambda row: (row.company_name.lower(), row.category_name.lower()))
    return FuelCostCompanyConsumptionOut(
        rig_id=rig.id,
        rig_code=rig.rig_code,
        rig_name=rig.rig_name,
        from_date=date_from,
        to_date=date_to,
        total_litres=_quantity(sum((row.litres for row in rows), ZERO)),
        rows=rows,
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _decimal_cell(value: Any, label: str, row_number: int) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=422, detail=f"Row {row_number}: {label} must be a number") from None
    if number < 0:
        raise HTTPException(status_code=422, detail=f"Row {row_number}: {label} cannot be negative")
    return _quantity(number)


def _date_cell(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(text)


NUMERIC_DAY_FIELDS = (
    "rig_engine_consumption",
    "gas_consumption",
    "opening_stock",
    "receipt_quantity",
    "closing_stock",
)


def import_rows(
    db: Session,
    organization_id: str,
    data: FuelCostImportRequest,
    user: User,
    request: Request | None,
) -> FuelCostImportResponse:
    """Import day-level values and company lines from a spreadsheet.

    Rows are grouped by rig and date. Every group first validates as a whole —
    nothing is written when a group has an error. A second import of the same
    file updates the same days and lines instead of duplicating them.
    """
    errors: list[str] = []
    rigs = {
        rig.rig_code.strip().upper(): rig
        for rig in db.scalars(
            select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False))
        ).all()
    }
    default_rig = _rig_or_404(db, organization_id, data.rig_id) if data.rig_id else None

    groups: dict[tuple[str, date], dict[str, Any]] = {}
    for number, row in enumerate(data.rows, start=2):
        if len(errors) >= MAX_IMPORT_ERRORS:
            break
        rig_code = str(row.rig_code or "").strip().upper()
        rig = rigs.get(rig_code) if rig_code else default_rig
        if rig is None:
            errors.append(
                f"Row {number}: rig code “{rig_code}” was not found in this workspace."
                if rig_code
                else f"Row {number}: Rig code is required when no rig is selected on the page."
            )
            continue
        try:
            cost_date = _date_cell(row.cost_date)
        except ValueError:
            errors.append(f"Row {number}: date “{row.cost_date}” is not a valid date (use YYYY-MM-DD).")
            continue
        if cost_date is None:
            errors.append(f"Row {number}: Date is mandatory.")
            continue
        try:
            numeric = {
                "rig_engine_consumption": _decimal_cell(row.rig_engine_consumption, "Rig engine consumption", number),
                "gas_consumption": _decimal_cell(row.gas_consumption, "Gas consumption", number),
                "opening_stock": _decimal_cell(row.opening_stock, "Opening stock", number),
                "receipt_quantity": _decimal_cell(row.receipt_quantity, "Receipt", number),
                "closing_stock": _decimal_cell(row.closing_stock, "Actual closing stock", number),
                "litres": _decimal_cell(row.litres, "Consumption", number),
            }
        except HTTPException as error:
            errors.append(str(error.detail))
            continue

        group = groups.setdefault(
            (rig.id, cost_date),
            {"rig": rig, "date": cost_date, "day": {}, "lines": [], "rows": [], "error": ""},
        )
        group["rows"].append(number)
        texts = {
            "rig_engine_remarks": row.rig_engine_remarks,
            "gas_remarks": row.gas_remarks,
            "opening_remarks": row.opening_remarks,
            "receipt_remarks": row.receipt_remarks,
            "closing_remarks": row.closing_remarks,
            "remarks": row.remarks,
        }
        for field, value in numeric.items():
            if field == "litres" or value is None:
                continue
            existing = group["day"].get(field)
            if existing is not None and Decimal(existing) != value and not group["error"]:
                group["error"] = (
                    f"Row {number}: {field.replace('_', ' ')} conflicts with another row of the same "
                    f"rig and date ({rig.rig_code} · {cost_date.isoformat()}). Keep one value per day."
                )
            group["day"][field] = value
        for field, value in texts.items():
            text = str(value or "").strip()
            if not text:
                continue
            existing = group["day"].get(field)
            if existing is not None and str(existing).strip() and str(existing).strip() != text and not group["error"]:
                group["error"] = (
                    f"Row {number}: {field.replace('_', ' ')} conflicts with another row of the same "
                    f"rig and date ({rig.rig_code} · {cost_date.isoformat()}). Keep one value per day."
                )
            group["day"][field] = text

        company_name = str(row.company_name or "").strip()
        if company_name:
            group["lines"].append(
                {
                    "row": number,
                    "company_name": company_name,
                    "category_name": str(row.category_name or "").strip(),
                    "litres": numeric["litres"] if numeric["litres"] is not None else ZERO,
                    "remarks": str(row.line_remarks or "").strip(),
                }
            )
        elif numeric["litres"] is not None:
            group["error"] = f"Row {number}: Company name is required when consumption litres are entered."

    for group in groups.values():
        if group["error"]:
            errors.append(group["error"])

    # Order each rig's groups so the first-day anchor and its carry-forward are known.
    by_rig: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups.values():
        by_rig[group["rig"].id].append(group)

    valid: list[dict[str, Any]] = []
    for rig_id, rig_groups in by_rig.items():
        rig_groups.sort(key=lambda item: item["date"])
        existing_dates = set(
            db.scalars(
                select(FuelCostEntry.cost_date).where(
                    FuelCostEntry.organization_id == organization_id,
                    FuelCostEntry.rig_id == rig_id,
                    FuelCostEntry.is_deleted.is_(False),
                )
            ).all()
        )
        imported_dates: set[date] = set()
        for group in rig_groups:
            if group["error"]:
                continue
            day = group["day"]
            if not (
                day.get("rig_engine_consumption")
                or day.get("gas_consumption")
                or day.get("receipt_quantity")
                or day.get("closing_stock") is not None
                or group["lines"]
            ):
                group["error"] = (
                    f"{group['rig'].rig_code} · {group['date'].isoformat()}: record at least one of rig engine "
                    "consumption, gas consumption, a receipt, a closing stock or a company line."
                )
                errors.append(group["error"])
                continue
            earlier_exists = any(day_date < group["date"] for day_date in existing_dates | imported_dates)
            supplied_opening = day.get("opening_stock")
            if not earlier_exists and supplied_opening is None:
                group["error"] = (
                    f"{group['rig'].rig_code} · {group['date'].isoformat()}: Opening stock is mandatory on "
                    f"the first fuel entry for a rig (rows {', '.join(str(n) for n in group['rows'])})."
                )
            elif earlier_exists and supplied_opening is not None:
                group["error"] = (
                    f"{group['rig'].rig_code} · {group['date'].isoformat()}: the opening stock is carried from "
                    f"the previous actual closing stock. Use Override opening stock on the page to change it "
                    f"(rows {', '.join(str(n) for n in group['rows'])})."
                )
            seen: dict[tuple[str, str], int] = {}
            for line in group["lines"]:
                key = (line["company_name"].lower(), line["category_name"].lower())
                if key in seen:
                    group["error"] = (
                        f"Row {line['row']}: {line['company_name']}"
                        + (f" · {line['category_name']}" if line["category_name"] else "")
                        + f" already appears on row {seen[key]} for the same day."
                    )
                seen[key] = line["row"]
            if group["error"]:
                errors.append(group["error"])
                continue
            imported_dates.add(group["date"])
            valid.append(group)

    imported = 0
    line_count = 0
    if valid:
        for group in valid:
            rig = group["rig"]
            day = group["day"]
            entry = _existing_day(db, organization_id, rig.id, group["date"])
            if entry is None:
                entry = FuelCostEntry(
                    id=uid(),
                    organization_id=organization_id,
                    rig_id=rig.id,
                    rig_code_snapshot=rig.rig_code,
                    rig_name_snapshot=rig.rig_name,
                    cost_date=group["date"],
                    created_by=_actor_name(user),
                )
                db.add(entry)
            entry.rig_engine_consumption = _quantity(day.get("rig_engine_consumption") or 0)
            entry.rig_engine_remarks = str(day.get("rig_engine_remarks") or "").strip()
            entry.gas_consumption = _quantity(day.get("gas_consumption") or 0)
            entry.gas_remarks = str(day.get("gas_remarks") or "").strip()
            entry.receipt_quantity = _quantity(day.get("receipt_quantity") or 0)
            entry.receipt_remarks = str(day.get("receipt_remarks") or "").strip()
            entry.closing_stock = (
                _quantity(day["closing_stock"]) if day.get("closing_stock") is not None else None
            )
            entry.closing_remarks = str(day.get("closing_remarks") or "").strip()
            entry.remarks = str(day.get("remarks") or "").strip()
            if day.get("opening_stock") is not None:
                entry.opening_stock = _quantity(day["opening_stock"])
                entry.opening_overridden = False
                entry.opening_remarks = str(day.get("opening_remarks") or "").strip()
            entry.updated_by = _actor_name(user)
            entry.revision = (entry.revision or 0) + 1
            db.flush()

            existing_lines = {(line.company_id, line.category_id): line for line in entry.lines}
            kept: set[tuple[str, str | None]] = set()
            for order, payload in enumerate(group["lines"]):
                company = _company_named(db, organization_id, payload["company_name"])
                if company is not None and company.is_deleted:
                    company.is_deleted = False
                    company.deleted_at = None
                    company.updated_by = _actor_name(user)
                if company is None:
                    company = FuelCompany(
                        id=uid(),
                        organization_id=organization_id,
                        company_name=payload["company_name"],
                        is_default=False,
                        source="import",
                        created_by=_actor_name(user),
                        updated_by=_actor_name(user),
                    )
                    db.add(company)
                    db.flush()
                category: FuelCompanyCategory | None = None
                if payload["category_name"]:
                    category = _category_named(db, organization_id, company.id, payload["category_name"])
                    if category is not None and category.is_deleted:
                        category.is_deleted = False
                        category.deleted_at = None
                        category.updated_by = _actor_name(user)
                    if category is None:
                        category = FuelCompanyCategory(
                            id=uid(),
                            organization_id=organization_id,
                            company_id=company.id,
                            category_name=payload["category_name"],
                            created_by=_actor_name(user),
                            updated_by=_actor_name(user),
                        )
                        db.add(category)
                        db.flush()
                key = (company.id, category.id if category else None)
                kept.add(key)
                line = existing_lines.get(key)
                if line is None:
                    line = FuelCostCompanyLine(
                        id=uid(),
                        organization_id=organization_id,
                        entry_id=entry.id,
                        company_id=company.id,
                        company_name_snapshot=company.company_name,
                        category_id=category.id if category else None,
                        category_name_snapshot=category.category_name if category else "",
                        source="import",
                    )
                    db.add(line)
                line.litres = _quantity(payload["litres"])
                line.remarks = payload["remarks"]
                line.source = "import"
                line.sort_order = order
                line.updated_at = datetime.now(timezone.utc)
                line_count += 1
            for key, line in existing_lines.items():
                if key not in kept:
                    db.delete(line)
            imported += 1
        _audit(
            db,
            user=user,
            action="import",
            entity_type="fuel_cost_import",
            entity_id=None,
            entity_label=f"{imported} fuel day(s)",
            summary=(
                f"Imported {imported} fuel day(s) with {line_count} company consumption line(s)"
                + (f"; {len(errors)} row problem(s) reported" if errors else "")
            ),
            request=request,
        )
        _commit(db)
    return FuelCostImportResponse(
        imported_count=imported,
        line_count=line_count,
        error_count=len(errors),
        success=not errors,
        day_count=imported,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Export audit
# ---------------------------------------------------------------------------


def record_export(
    db: Session, user: User, data: FuelCostExportAudit, request: Request | None
) -> None:
    _audit(
        db,
        user=user,
        action="export",
        entity_type="fuel_cost_export",
        entity_id=None,
        entity_label=data.module,
        summary=f"Exported {data.record_count} {data.module} fuel record(s) as {data.format.upper()}"
        + (" including deleted records" if data.include_deleted else "")
        + (f"; rig {data.rig_id}" if data.rig_id else "")
        + (f"; register entry {data.entry_id}" if data.entry_id else "")
        + (
            f"; period {data.date_from or 'inception'} to {data.date_to or date.today()}"
            if data.date_from or data.date_to
            else ""
        ),
        request=request,
    )
    _commit(db)
