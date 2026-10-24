"""Private or workspace-shared costing sets and their catalogue options."""

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Current, Db, require
from app.models import (
    AuditLog,
    CementAdditive,
    DrillBit,
    FuelType,
    MudChemical,
    Service,
    Tangible,
    UserCostingSet,
    UserCostingSetItem,
)
from app.schemas.costing_set import (
    CostingSetCreate,
    CostingSetExportAuditIn,
    CostingSetImportError,
    CostingSetImportRequest,
    CostingSetImportResult,
    CostingSetItemIn,
    CostingSetItemOut,
    CostingSetOptionOut,
    CostingSetOut,
    CostingSetUpdate,
)
from app.services import audit

router = APIRouter(prefix="/costing-sets", tags=["Reusable Costing Sets"])

# item_kind -> (group, model, code column, name column)
ITEM_SPECS: dict[str, tuple[str, Any, str, str]] = {
    "service": ("services", Service, "service_code", "service_name"),
    "tangible": ("tangibles", Tangible, "tangible_code", "tangible_name"),
    "mud_chemical": ("consumables", MudChemical, "chemical_code", "chemical_name"),
    "cement_additive": ("consumables", CementAdditive, "additive_code", "additive_name"),
    "fuel": ("consumables", FuelType, "fuel_code", "fuel_name"),
    "drill_bit": ("consumables", DrillBit, "bit_code", "bit_name"),
}


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A costing set with this name or item already exists in your workspace.",
        ) from error


def _get_set(db: Session, user: Any, set_id: str) -> UserCostingSet:
    costing_set = db.scalar(
        select(UserCostingSet)
        .options(selectinload(UserCostingSet.items))
        .where(
            UserCostingSet.id == set_id,
            UserCostingSet.organization_id == user.organization_id,
            UserCostingSet.user_id == user.id,
        )
    )
    if costing_set is None:
        raise HTTPException(status_code=404, detail="Costing set not found for this user")
    return costing_set


def _available_keys(db: Session, organization_id: str, item_kinds: set[str]) -> set[tuple[str, str]]:
    available: set[tuple[str, str]] = set()
    for kind in item_kinds:
        _, model, _, _ = ITEM_SPECS[kind]
        ids = db.scalars(
            select(model.id).where(
                model.organization_id == organization_id,
                model.is_deleted.is_(False),
            )
        ).all()
        available.update((kind, item_id) for item_id in ids)
    return available


def _set_out(costing_set: UserCostingSet, available: set[tuple[str, str]]) -> dict[str, Any]:
    items = [
        CostingSetItemOut(
            id=item.id,
            item_kind=item.item_kind,
            item_id=item.item_id,
            item_code=item.item_code_snapshot,
            item_name=item.item_name_snapshot,
            display_name=f"{item.item_code_snapshot} · {item.item_name_snapshot}",
            is_available=(item.item_kind, item.item_id) in available,
        )
        for item in costing_set.items
    ]
    return CostingSetOut(
        id=costing_set.id,
        is_global=costing_set.is_global,
        owner_id=costing_set.user_id,
        name=costing_set.name,
        item_group=costing_set.item_group,
        description=costing_set.description,
        item_count=len(items),
        items=items,
        created_at=costing_set.created_at,
        updated_at=costing_set.updated_at,
    ).model_dump()


def _validate_items(
    db: Session,
    *,
    organization_id: str,
    item_group: str,
    items: list[CostingSetItemIn],
    current_set: UserCostingSet | None = None,
) -> list[tuple[str, Any]]:
    seen: set[tuple[str, str]] = set()
    validated: list[tuple[str, Any]] = []
    for item in items:
        spec = ITEM_SPECS.get(item.item_kind)
        if spec is None or spec[0] != item_group:
            raise HTTPException(
                status_code=422,
                detail=f"{item.item_kind} items do not belong to the {item_group} group.",
            )
        key = (item.item_kind, item.item_id)
        if key in seen:
            raise HTTPException(status_code=422, detail="A costing set cannot contain the same item twice.")
        seen.add(key)
        _, model, code_field, name_field = spec
        record = db.scalar(
            select(model).where(
                model.id == item.item_id,
                model.organization_id == organization_id,
                model.is_deleted.is_(False),
            )
        )
        if record is None and current_set is not None:
            # Keep an existing stale reference only when the caller owns this set
            # and the exact membership was already attached to it. This lets the
            # editor preserve historical snapshots or deliberately remove them.
            existing_item = next((
                current for current in current_set.items
                if current.item_kind == item.item_kind and current.item_id == item.item_id
            ), None)
            if existing_item is not None:
                record = db.scalar(select(model).where(
                    model.id == item.item_id,
                    model.organization_id == organization_id,
                )) or existing_item
        if record is None:
            raise HTTPException(
                status_code=422,
                detail=f"{item.item_kind.replace('_', ' ').title()} {item.item_id} is missing, deleted, or belongs to another workspace.",
            )
        validated.append((item.item_kind, record))
    return validated


def _replace_items(
    db: Session,
    *,
    costing_set: UserCostingSet,
    organization_id: str,
    resolved_items: list[tuple[str, Any]],
) -> None:
    # Reuse unchanged membership rows. That avoids a transient unique-key clash
    # when a user edits the description or ordering without changing item ids.
    existing = {(item.item_kind, item.item_id): item for item in costing_set.items}
    replacement: list[UserCostingSetItem] = []
    for order, (kind, record) in enumerate(resolved_items):
        _, _, code_field, name_field = ITEM_SPECS[kind]
        # Catalogue models identify themselves with ``id``; a snapshot row is a
        # UserCostingSetItem and its own ``id`` is distinct from its polymorphic
        # ``item_id``. Prefer the snapshot's target key when a purged item is kept.
        item_id = getattr(record, "item_id", None) or getattr(record, "id", "")
        code = getattr(record, code_field, getattr(record, "item_code_snapshot", ""))
        name = getattr(record, name_field, getattr(record, "item_name_snapshot", ""))
        key = (kind, item_id)
        item = existing.pop(key, None)
        if item is None:
            item = UserCostingSetItem(
                organization_id=organization_id,
                item_kind=kind,
                item_id=item_id,
                item_code_snapshot=str(code),
                item_name_snapshot=str(name),
                sort_order=order,
            )
        else:
            item.item_code_snapshot = str(code)
            item.item_name_snapshot = str(name)
            item.sort_order = order
        replacement.append(item)
    costing_set.items = replacement


def _audit_set(db: Session, *, user: Any, costing_set: UserCostingSet, action: str, summary: str, request: Request) -> None:
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type="costing_set",
        entity_id=costing_set.id,
        entity_label=f"{costing_set.item_group.title()} · {costing_set.name}",
        summary=summary,
        request=request,
    )


@router.get("", response_model=list[CostingSetOut], dependencies=[Depends(require("costing-sets:read"))])
def list_costing_sets(db: Db, user: Current):
    """Return owned shortcuts plus explicitly shared shortcuts in this workspace."""
    records = db.scalars(
        select(UserCostingSet)
        .options(selectinload(UserCostingSet.items))
        .where(
            UserCostingSet.organization_id == user.organization_id,
            or_(UserCostingSet.user_id == user.id, UserCostingSet.is_global.is_(True)),
        )
        .order_by(UserCostingSet.item_group, UserCostingSet.name_key, UserCostingSet.id)
    ).all()
    kinds = {item.item_kind for costing_set in records for item in costing_set.items}
    available = _available_keys(db, user.organization_id, kinds)
    return [_set_out(costing_set, available) for costing_set in records]


@router.get("/options", response_model=list[CostingSetOptionOut], dependencies=[Depends(require("costing-sets:read"))])
def list_item_options(db: Db, user: Current, item_group: str | None = None):
    """Active catalogue choices, scoped to the caller's workspace."""
    if item_group is not None and item_group not in {"services", "tangibles", "consumables"}:
        raise HTTPException(status_code=422, detail="Choose services, tangibles, or consumables.")
    options: list[CostingSetOptionOut] = []
    for kind, (group, model, code_field, name_field) in ITEM_SPECS.items():
        if item_group is not None and group != item_group:
            continue
        records = db.scalars(
            select(model)
            .where(model.organization_id == user.organization_id, model.is_deleted.is_(False))
            .order_by(getattr(model, code_field), model.id)
        ).all()
        options.extend(
            CostingSetOptionOut(
                item_group=group,
                item_kind=kind,
                item_id=record.id,
                item_code=str(getattr(record, code_field)),
                item_name=str(getattr(record, name_field)),
                display_name=f"{getattr(record, code_field)} · {getattr(record, name_field)}",
            )
            for record in records
        )
    return options


@router.post("", response_model=CostingSetOut, status_code=201, dependencies=[Depends(require("costing-sets:create"))])
def create_costing_set(data: CostingSetCreate, request: Request, db: Db, user: Current):
    duplicate = db.scalar(
        select(UserCostingSet.id).where(
            UserCostingSet.organization_id == user.organization_id,
            UserCostingSet.user_id == user.id,
            UserCostingSet.item_group == data.item_group,
            UserCostingSet.name_key == data.name.casefold(),
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="You already have a costing set with this name in that item group.")
    resolved = _validate_items(
        db, organization_id=user.organization_id, item_group=data.item_group, items=data.items
    )
    costing_set = UserCostingSet(
        organization_id=user.organization_id,
        user_id=user.id,
        name=data.name,
        name_key=data.name.casefold(),
        item_group=data.item_group,
        description=data.description,
        is_global=data.is_global,
    )
    _replace_items(db, costing_set=costing_set, organization_id=user.organization_id, resolved_items=resolved)
    db.add(costing_set)
    db.flush()
    _audit_set(
        db,
        user=user,
        costing_set=costing_set,
        action="create",
        summary=f"Created {data.item_group} costing set with {len(resolved)} catalogue items; workspace global={data.is_global}",
        request=request,
    )
    _commit(db)
    available = {(kind, record.id) for kind, record in resolved}
    return _set_out(costing_set, available)


@router.put("/{set_id}", response_model=CostingSetOut, dependencies=[Depends(require("costing-sets:update"))])
def update_costing_set(set_id: str, data: CostingSetUpdate, request: Request, db: Db, user: Current):
    costing_set = _get_set(db, user, set_id)
    duplicate = db.scalar(
        select(UserCostingSet.id).where(
            UserCostingSet.organization_id == user.organization_id,
            UserCostingSet.user_id == user.id,
            UserCostingSet.item_group == data.item_group,
            UserCostingSet.name_key == data.name.casefold(),
            UserCostingSet.id != set_id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="You already have a costing set with this name in that item group.")
    resolved = _validate_items(
        db,
        organization_id=user.organization_id,
        item_group=data.item_group,
        items=data.items,
        current_set=costing_set,
    )
    old_name, old_group, old_count = costing_set.name, costing_set.item_group, len(costing_set.items)
    costing_set.name = data.name
    costing_set.name_key = data.name.casefold()
    costing_set.item_group = data.item_group
    costing_set.description = data.description
    costing_set.is_global = data.is_global
    _replace_items(db, costing_set=costing_set, organization_id=user.organization_id, resolved_items=resolved)
    _audit_set(
        db,
        user=user,
        costing_set=costing_set,
        action="update",
        summary=f"Updated costing set {old_name} ({old_group}; {old_count} items) to {data.name} ({data.item_group}; {len(resolved)} items); workspace global={data.is_global}",
        request=request,
    )
    _commit(db)
    kinds = {kind for kind, _record in resolved}
    return _set_out(costing_set, _available_keys(db, user.organization_id, kinds))


@router.delete("/{set_id}", status_code=204, dependencies=[Depends(require("costing-sets:delete"))])
def delete_costing_set(set_id: str, request: Request, db: Db, user: Current) -> None:
    costing_set = _get_set(db, user, set_id)
    label = costing_set.name
    group = costing_set.item_group
    db.delete(costing_set)
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="delete",
        entity_type="costing_set",
        entity_id=costing_set.id,
        entity_label=f"{group.title()} · {label}",
        summary=f"Deleted {group} costing set",
        request=request,
    )
    _commit(db)
    return None


@router.post("/import", response_model=CostingSetImportResult, dependencies=[Depends(require("costing-sets:import"))])
def import_costing_sets(data: CostingSetImportRequest, request: Request, db: Db, user: Current):
    """Import CSV/XLSX-export rows by resolving item codes in this workspace.

    Existing same-name sets are merged; invalid rows are reported independently,
    and no row can attach a foreign-tenant or soft-deleted catalogue record.
    """
    errors: list[CostingSetImportError] = []
    groups: dict[tuple[str, str], list[tuple[str, Any, str]]] = defaultdict(list)
    seen_rows: set[tuple[str, str, str, str]] = set()

    for row_number, row in enumerate(data.rows, start=1):
        spec = ITEM_SPECS.get(row.item_kind)
        if spec is None or spec[0] != row.item_group:
            errors.append(CostingSetImportError(
                row=row_number,
                set_name=row.set_name,
                item_code=row.item_code,
                message=f"{row.item_kind.replace('_', ' ').title()} does not belong to the {row.item_group} group.",
            ))
            continue
        duplicate_key = (row.item_group, row.set_name.casefold(), row.item_kind, row.item_code.casefold())
        if duplicate_key in seen_rows:
            errors.append(CostingSetImportError(
                row=row_number,
                set_name=row.set_name,
                item_code=row.item_code,
                message="Duplicate set item in this import file.",
            ))
            continue
        seen_rows.add(duplicate_key)
        _, model, code_field, _ = spec
        record = db.scalar(
            select(model).where(
                model.organization_id == user.organization_id,
                model.is_deleted.is_(False),
                func.upper(getattr(model, code_field)) == row.item_code.strip().upper(),
            )
        )
        if record is None:
            errors.append(CostingSetImportError(
                row=row_number,
                set_name=row.set_name,
                item_code=row.item_code,
                message="No active item with this code exists in the current workspace.",
            ))
            continue
        groups[(row.item_group, row.set_name.casefold())].append((row.item_kind, record, row.description))

    created_sets = updated_sets = imported_items = 0
    for (item_group, name_key), memberships in groups.items():
        set_name = next(row.set_name for row in data.rows if row.item_group == item_group and row.set_name.casefold() == name_key)
        costing_set = db.scalar(
            select(UserCostingSet)
            .options(selectinload(UserCostingSet.items))
            .where(
                UserCostingSet.organization_id == user.organization_id,
                UserCostingSet.user_id == user.id,
                UserCostingSet.item_group == item_group,
                UserCostingSet.name_key == name_key,
            )
        )
        is_new = costing_set is None
        if is_new:
            description = next((description for _, _, description in memberships if description), "")
            costing_set = UserCostingSet(
                organization_id=user.organization_id,
                user_id=user.id,
                name=set_name,
                name_key=name_key,
                item_group=item_group,
                description=description,
                items=[],
            )
            db.add(costing_set)
            created_sets += 1
        existing = {(item.item_kind, item.item_id) for item in costing_set.items}
        for kind, record, description in memberships:
            key = (kind, record.id)
            if key in existing:
                continue
            _, _, code_field, name_field = ITEM_SPECS[kind]
            costing_set.items.append(UserCostingSetItem(
                organization_id=user.organization_id,
                item_kind=kind,
                item_id=record.id,
                item_code_snapshot=str(getattr(record, code_field)),
                item_name_snapshot=str(getattr(record, name_field)),
                sort_order=len(costing_set.items),
            ))
            existing.add(key)
            imported_items += 1
        if is_new:
            pass
        else:
            updated_sets += 1
            if not costing_set.description:
                costing_set.description = next((description for _, _, description in memberships if description), "")
        _audit_set(
            db,
            user=user,
            costing_set=costing_set,
            action="create" if is_new else "update",
            summary=f"Imported {len(memberships)} rows into {item_group} costing set",
            request=request,
        )

    if groups:
        _commit(db)
    return CostingSetImportResult(
        created_sets=created_sets,
        updated_sets=updated_sets,
        imported_items=imported_items,
        errors=errors,
    )


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("costing-sets:export"))])
def audit_export(data: CostingSetExportAuditIn, request: Request, db: Db, user: Current) -> None:
    count = db.scalar(
        select(func.count(UserCostingSet.id)).where(
            UserCostingSet.organization_id == user.organization_id,
            or_(UserCostingSet.user_id == user.id, UserCostingSet.is_global.is_(True)),
        )
    ) or 0
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="costing_set",
        entity_label="Reusable costing sets",
        summary=f"Exported {data.record_count} of {count} visible costing sets as {data.format.upper()}",
        request=request,
    )
    db.commit()
    return None
