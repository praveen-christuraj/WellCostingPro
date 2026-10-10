"""Tenant-scoped Master Data Management APIs."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Current, Db, require
from app.models import (
    Activity,
    AuditLog,
    Currency,
    HoleSection,
    Phase,
    PurchaseOrder,
    UnitOfMeasurement,
    Vendor,
)
from app.services import audit
from app.schemas.master_data import (
    MasterDataActivity,
    MasterDataBulkActionResponse,
    MasterDataBulkSelection,
    MasterDataCreate,
    MasterDataExportAudit,
    MasterDataIDs,
    MasterDataImportRequest,
    MasterDataImportResponse,
    MasterDataModuleStats,
    MasterDataOverview,
    MasterDataRecordOut,
    MasterDataSelection,
    MasterDataUpdate,
)

router = APIRouter(prefix="/master-data", tags=["Master Data Management"])

MODULES: dict[str, dict[str, Any]] = {
    "uom": {
        "model": UnitOfMeasurement,
        "label": "Units of Measurement",
        "code_field": "unit_code",
        "name_field": "unit_name",
        "symbol_field": "unit_symbol",
        "code_max": 50,
        "name_max": 150,
        "symbol_max": 50,
    },
    "currencies": {
        "model": Currency,
        "label": "Currency",
        "code_field": "currency_code",
        "name_field": "currency_name",
        "symbol_field": "currency_symbol",
        "code_max": 10,
        "name_max": 100,
        "symbol_max": 20,
    },
    "phases": {
        "model": Phase,
        "label": "Phases",
        "code_field": "phase_code",
        "name_field": "phase_name",
        "symbol_field": None,
        "code_max": 50,
        "name_max": 150,
        "symbol_max": 0,
    },
    "hole-sections": {
        "model": HoleSection,
        "label": "Hole Sections",
        "code_field": "section_code",
        "name_field": "section_name",
        "symbol_field": None,
        "code_max": 50,
        "name_max": 150,
        "symbol_max": 0,
    },
    "activities": {
        "model": Activity,
        "label": "Activities",
        "code_field": "activity_code",
        "name_field": "activity_name",
        "symbol_field": None,
        "code_max": 50,
        "name_max": 150,
        "symbol_max": 0,
    },
}


# Vendors and PO/SO Orders belong to this module but have their own richer
# endpoints (see app/api/vendor_master.py); they still appear on the dashboard.
EXTENDED_MODULES: dict[str, tuple[Any, str]] = {
    "vendors": (Vendor, "Vendors"),
    "po-so-orders": (PurchaseOrder, "PO/SO Orders"),
}

AUDIT_ENTITY_TYPES = ("master_data", "vendor", "po_so_order", "po_so_document")


class MasterDataAction:
    """Action labels are centralized so summaries stay consistent in the audit trail."""

    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
    PERMANENT_DELETE = "permanent_delete"


def _config(module: str) -> dict[str, Any]:
    config = MODULES.get(module)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Master data module '{module}' not found")
    return config


def _normalize_payload(config: dict[str, Any], payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Validate per-module field lengths and normalize common API attributes."""
    result = dict(payload)
    code = result.get("code")
    name = result.get("name")
    if not partial or "code" in result:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Code is required")
        code = code.strip().upper()
        if len(code) > config["code_max"]:
            raise ValueError(f"Code must be {config['code_max']} characters or fewer")
        result["code"] = code
    if not partial or "name" in result:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Name is required")
        name = name.strip()
        if len(name) > config["name_max"]:
            raise ValueError(f"Name must be {config['name_max']} characters or fewer")
        result["name"] = name
    if "description" in result:
        description = result["description"]
        result["description"] = "" if description is None else str(description).strip()
    if "symbol" in result:
        symbol = result["symbol"]
        symbol = symbol.strip() if isinstance(symbol, str) else ""
        if config["symbol_field"] is None and symbol:
            raise ValueError("Symbol is not supported for this master data module")
        if config["symbol_field"] is not None and len(symbol) > config["symbol_max"]:
            raise ValueError(f"Symbol must be {config['symbol_max']} characters or fewer")
        result["symbol"] = symbol or None
    return result


def _model_values(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    values = {
        config["code_field"]: payload["code"],
        config["name_field"]: payload["name"],
        "description": payload.get("description", ""),
    }
    if config["symbol_field"]:
        values[config["symbol_field"]] = payload.get("symbol") or payload["code"]
    return values


def _output(config: dict[str, Any], record: Any) -> MasterDataRecordOut:
    symbol_field = config["symbol_field"]
    return MasterDataRecordOut(
        id=record.id,
        code=getattr(record, config["code_field"]),
        name=getattr(record, config["name_field"]),
        symbol=getattr(record, symbol_field) if symbol_field else None,
        description=record.description or "",
        is_deleted=record.is_deleted,
        deleted_at=record.deleted_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _audit_record(
    db: Session,
    *,
    config: dict[str, Any],
    record: Any,
    user: Any,
    action: str,
    summary: str,
    request: Request,
) -> None:
    code = getattr(record, config["code_field"])
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type="master_data",
        entity_id=record.id,
        entity_label=f"{config['label']} · {code}",
        summary=summary,
        request=request,
    )


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this code already exists in this workspace") from error


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A record with this code already exists in this workspace") from error


def _record_for_user(
    db: Session,
    *,
    config: dict[str, Any],
    record_id: str,
    organization_id: str,
    include_deleted: bool = True,
) -> Any:
    model = config["model"]
    statement = select(model).where(model.id == record_id, model.organization_id == organization_id)
    if not include_deleted:
        statement = statement.where(model.is_deleted.is_(False))
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(status_code=404, detail="Master data record not found")
    return record


def _records_for_ids(
    db: Session,
    *,
    config: dict[str, Any],
    ids: list[str],
    organization_id: str,
    deleted: bool,
) -> list[Any]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate record IDs are not allowed")
    model = config["model"]
    records = list(
        db.scalars(
            select(model).where(
                model.organization_id == organization_id,
                model.id.in_(ids),
            )
        ).all()
    )
    if len(records) != len(ids):
        raise HTTPException(status_code=404, detail="One or more records were not found in this workspace")
    if any(record.is_deleted is not deleted for record in records):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"Bulk action requires only {expected} records")
    return records


def _records_for_selection(
    db: Session,
    *,
    selections: list[MasterDataSelection],
    organization_id: str,
    deleted: bool,
) -> list[tuple[dict[str, Any], Any]]:
    pairs = [(item.module, item.id) for item in selections]
    if len(pairs) != len(set(pairs)):
        raise HTTPException(status_code=422, detail="Duplicate module and record selections are not allowed")
    groups: dict[str, list[str]] = {}
    for module, record_id in pairs:
        groups.setdefault(module, []).append(record_id)

    selected_records: list[tuple[dict[str, Any], Any]] = []
    for module, ids in groups.items():
        config = _config(module)
        records = _records_for_ids(
            db,
            config=config,
            ids=ids,
            organization_id=organization_id,
            deleted=deleted,
        )
        selected_records.extend((config, record) for record in records)
    return selected_records


def _import_row(config: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Accept this app's generic headers and the legacy module-specific headers."""
    normalized = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
    canonical = {
        "code": normalized.get("code", normalized.get(config["code_field"])),
        "name": normalized.get("name", normalized.get(config["name_field"])),
        "description": normalized.get("description", normalized.get("desc", "")),
    }
    if config["symbol_field"]:
        canonical["symbol"] = normalized.get("symbol", normalized.get(config["symbol_field"]))
    return canonical


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )


@router.get("/overview", response_model=MasterDataOverview, dependencies=[Depends(require("master-data:read"))])
def overview(db: Db, user: Current) -> MasterDataOverview:
    """Module KPIs and recent activity for the authenticated workspace."""
    modules: list[MasterDataModuleStats] = []
    active_total = 0
    deleted_total = 0
    for key, config in MODULES.items():
        model = config["model"]
        active_count = db.scalar(
            select(func.count(model.id)).where(
                model.organization_id == user.organization_id,
                model.is_deleted.is_(False),
            )
        ) or 0
        deleted_count = db.scalar(
            select(func.count(model.id)).where(
                model.organization_id == user.organization_id,
                model.is_deleted.is_(True),
            )
        ) or 0
        active_total += active_count
        deleted_total += deleted_count
        modules.append(
            MasterDataModuleStats(
                key=key,
                label=config["label"],
                active_count=active_count,
                deleted_count=deleted_count,
            )
        )

    for key, (model, label) in EXTENDED_MODULES.items():
        active_count = db.scalar(
            select(func.count(model.id)).where(
                model.organization_id == user.organization_id,
                model.is_deleted.is_(False),
            )
        ) or 0
        deleted_count = db.scalar(
            select(func.count(model.id)).where(
                model.organization_id == user.organization_id,
                model.is_deleted.is_(True),
            )
        ) or 0
        active_total += active_count
        deleted_total += deleted_count
        modules.append(
            MasterDataModuleStats(
                key=key,
                label=label,
                active_count=active_count,
                deleted_count=deleted_count,
            )
        )

    recent = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == user.organization_id,
            AuditLog.entity_type.in_(AUDIT_ENTITY_TYPES),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(8)
    ).all()
    return MasterDataOverview(
        active_records=active_total,
        deleted_records=deleted_total,
        module_count=len(MODULES) + len(EXTENDED_MODULES),
        modules=modules,
        recent_activity=[
            MasterDataActivity(
                id=entry.id,
                action=entry.action,
                entity_label=entry.entity_label,
                summary=entry.summary,
                created_at=entry.created_at,
            )
            for entry in recent
        ],
    )


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("master-data:export"))])
def audit_export(data: MasterDataExportAudit, request: Request, db: Db, user: Current) -> None:
    """Record a client-side CSV/XLSX/PDF export in the audit trail."""
    if data.module != "all":
        config = MODULES.get(data.module)
        if config is not None:
            module_label = config["label"]
        elif data.module in EXTENDED_MODULES:
            module_label = EXTENDED_MODULES[data.module][1]
        else:
            raise HTTPException(status_code=404, detail="Master data module not found")
    else:
        module_label = "All master data"
    inclusion = "including deleted entries" if data.include_deleted else "active entries only"
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="master_data",
        entity_label=module_label,
        summary=f"Exported {data.record_count} {module_label} records as {data.format.upper()} ({inclusion})",
        request=request,
    )
    db.commit()
    return None


@router.get("/{module}", response_model=list[MasterDataRecordOut], dependencies=[Depends(require("master-data:read"))])
def list_records(module: str, db: Db, user: Current) -> list[MasterDataRecordOut]:
    """List active records from one tenant-scoped master-data table."""
    config = _config(module)
    model = config["model"]
    records = db.scalars(
        select(model)
        .where(model.organization_id == user.organization_id, model.is_deleted.is_(False))
        .order_by(model.created_at.desc(), model.id.desc())
    ).all()
    return [_output(config, record) for record in records]


@router.get("/{module}/deleted", response_model=list[MasterDataRecordOut], dependencies=[Depends(require("master-data:read"))])
def list_deleted_records(module: str, db: Db, user: Current) -> list[MasterDataRecordOut]:
    """List only soft-deleted rows for the authenticated workspace."""
    config = _config(module)
    model = config["model"]
    records = db.scalars(
        select(model)
        .where(model.organization_id == user.organization_id, model.is_deleted.is_(True))
        .order_by(model.deleted_at.desc(), model.id.desc())
    ).all()
    return [_output(config, record) for record in records]


@router.post("/bulk-restore", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:restore"))])
def bulk_restore_across_modules(
    data: MasterDataBulkSelection,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataBulkActionResponse:
    selected = _records_for_selection(db, selections=data.records, organization_id=user.organization_id, deleted=True)
    for config, record in selected:
        record.is_deleted = False
        record.deleted_at = None
        _audit_record(
            db,
            config=config,
            record=record,
            user=user,
            action=MasterDataAction.RESTORE,
            summary=f"Restored {config['label']} record {getattr(record, config['code_field'])} (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(selected))


@router.post("/bulk-permanent-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:permanent-delete"))])
def bulk_permanent_delete_across_modules(
    data: MasterDataBulkSelection,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataBulkActionResponse:
    selected = _records_for_selection(db, selections=data.records, organization_id=user.organization_id, deleted=True)
    for config, record in selected:
        _audit_record(
            db,
            config=config,
            record=record,
            user=user,
            action=MasterDataAction.PERMANENT_DELETE,
            summary=f"Permanently deleted {config['label']} record {getattr(record, config['code_field'])} (bulk action)",
            request=request,
        )
        db.delete(record)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(selected))



@router.post("/{module}", response_model=MasterDataRecordOut, status_code=201, dependencies=[Depends(require("master-data:create"))])
def create_record(module: str, data: MasterDataCreate, request: Request, db: Db, user: Current) -> MasterDataRecordOut:
    config = _config(module)
    try:
        payload = _normalize_payload(config, data.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    model = config["model"]
    code_field = config["code_field"]
    existing = db.scalar(
        select(model).where(
            model.organization_id == user.organization_id,
            getattr(model, code_field) == payload["code"],
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Code '{payload['code']}' already exists; restore or permanently remove its deleted entry first")

    record = model(organization_id=user.organization_id, **_model_values(config, payload))
    db.add(record)
    _flush(db)
    _audit_record(
        db,
        config=config,
        record=record,
        user=user,
        action="create",
        summary=f"Created {config['label']} record {payload['code']}",
        request=request,
    )
    _commit(db)
    db.refresh(record)
    return _output(config, record)


@router.patch("/{module}/{record_id}", response_model=MasterDataRecordOut, dependencies=[Depends(require("master-data:update"))])
def update_record(
    module: str,
    record_id: str,
    data: MasterDataUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataRecordOut:
    config = _config(module)
    record = _record_for_user(db, config=config, record_id=record_id, organization_id=user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    try:
        payload = _normalize_payload(config, supplied, partial=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    model = config["model"]
    code_field = config["code_field"]
    new_code = payload.get("code")
    if new_code is not None:
        duplicate = db.scalar(
            select(model).where(
                model.organization_id == user.organization_id,
                getattr(model, code_field) == new_code,
                model.id != record.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail=f"Code '{new_code}' already exists in this workspace")

    changed_fields: list[str] = []
    for common, model_field in (("code", code_field), ("name", config["name_field"])):
        if common in payload:
            value = payload[common]
            if getattr(record, model_field) != value:
                setattr(record, model_field, value)
                changed_fields.append(common)
    symbol_field = config["symbol_field"]
    if "symbol" in payload and symbol_field:
        value = payload["symbol"] or payload.get("code") or getattr(record, code_field)
        if getattr(record, symbol_field) != value:
            setattr(record, symbol_field, value)
            changed_fields.append("symbol")
    if "description" in payload:
        value = payload["description"] or ""
        if record.description != value:
            record.description = value
            changed_fields.append("description")

    if changed_fields:
        _audit_record(
            db,
            config=config,
            record=record,
            user=user,
            action="update",
            summary=f"Updated {config['label']} record {getattr(record, code_field)}: {', '.join(changed_fields)}",
            request=request,
        )
        _commit(db)
        db.refresh(record)
    return _output(config, record)


@router.delete("/{module}/{record_id}", response_model=MasterDataRecordOut, dependencies=[Depends(require("master-data:delete"))])
def soft_delete_record(module: str, record_id: str, request: Request, db: Db, user: Current) -> MasterDataRecordOut:
    config = _config(module)
    record = _record_for_user(db, config=config, record_id=record_id, organization_id=user.organization_id, include_deleted=False)
    record.is_deleted = True
    record.deleted_at = datetime.now(timezone.utc)
    _audit_record(
        db,
        config=config,
        record=record,
        user=user,
        action=MasterDataAction.SOFT_DELETE,
        summary=f"Moved {config['label']} record {getattr(record, config['code_field'])} to deleted entries",
        request=request,
    )
    _commit(db)
    db.refresh(record)
    return _output(config, record)


@router.post("/{module}/{record_id}/restore", response_model=MasterDataRecordOut, dependencies=[Depends(require("master-data:restore"))])
def restore_record(module: str, record_id: str, request: Request, db: Db, user: Current) -> MasterDataRecordOut:
    config = _config(module)
    record = _record_for_user(db, config=config, record_id=record_id, organization_id=user.organization_id)
    if not record.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted master data record can be restored")
    record.is_deleted = False
    record.deleted_at = None
    _audit_record(
        db,
        config=config,
        record=record,
        user=user,
        action=MasterDataAction.RESTORE,
        summary=f"Restored {config['label']} record {getattr(record, config['code_field'])}",
        request=request,
    )
    _commit(db)
    db.refresh(record)
    return _output(config, record)


@router.delete("/{module}/{record_id}/permanent", status_code=204, dependencies=[Depends(require("master-data:permanent-delete"))])
def permanently_delete_record(module: str, record_id: str, request: Request, db: Db, user: Current) -> None:
    config = _config(module)
    record = _record_for_user(db, config=config, record_id=record_id, organization_id=user.organization_id)
    if not record.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted master data record can be permanently deleted")
    _audit_record(
        db,
        config=config,
        record=record,
        user=user,
        action=MasterDataAction.PERMANENT_DELETE,
        summary=f"Permanently deleted {config['label']} record {getattr(record, config['code_field'])}",
        request=request,
    )
    db.delete(record)
    _commit(db)
    return None


@router.post("/{module}/bulk-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:delete"))])
def bulk_soft_delete(module: str, data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
    config = _config(module)
    records = _records_for_ids(db, config=config, ids=data.ids, organization_id=user.organization_id, deleted=False)
    deleted_at = datetime.now(timezone.utc)
    for record in records:
        record.is_deleted = True
        record.deleted_at = deleted_at
        _audit_record(
            db,
            config=config,
            record=record,
            user=user,
            action=MasterDataAction.SOFT_DELETE,
            summary=f"Moved {config['label']} record {getattr(record, config['code_field'])} to deleted entries (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(records))


@router.post("/{module}/bulk-restore", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:restore"))])
def bulk_restore(module: str, data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
    config = _config(module)
    records = _records_for_ids(db, config=config, ids=data.ids, organization_id=user.organization_id, deleted=True)
    for record in records:
        record.is_deleted = False
        record.deleted_at = None
        _audit_record(
            db,
            config=config,
            record=record,
            user=user,
            action=MasterDataAction.RESTORE,
            summary=f"Restored {config['label']} record {getattr(record, config['code_field'])} (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(records))


@router.post("/{module}/bulk-permanent-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:permanent-delete"))])
def bulk_permanent_delete(module: str, data: MasterDataIDs, request: Request, db: Db, user: Current) -> MasterDataBulkActionResponse:
    config = _config(module)
    records = _records_for_ids(db, config=config, ids=data.ids, organization_id=user.organization_id, deleted=True)
    for record in records:
        _audit_record(
            db,
            config=config,
            record=record,
            user=user,
            action=MasterDataAction.PERMANENT_DELETE,
            summary=f"Permanently deleted {config['label']} record {getattr(record, config['code_field'])} (bulk action)",
            request=request,
        )
        db.delete(record)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(records))


@router.post("/{module}/import", response_model=MasterDataImportResponse, dependencies=[Depends(require("master-data:import"))])
def import_records(
    module: str,
    data: MasterDataImportRequest,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataImportResponse:
    """Import a previewed list with row-level validation and an audit trail."""
    config = _config(module)
    model = config["model"]
    code_field = config["code_field"]
    imported_count = 0
    errors: list[str] = []
    seen_codes: set[str] = set()

    for row_number, row in enumerate(data.rows, start=1):
        try:
            payload = _normalize_payload(config, MasterDataCreate.model_validate(_import_row(config, row)).model_dump())
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        code = payload["code"]
        if code in seen_codes:
            errors.append(f"Row {row_number} ({code}): duplicate code in this import file")
            continue
        seen_codes.add(code)
        record = db.scalar(
            select(model).where(
                model.organization_id == user.organization_id,
                getattr(model, code_field) == code,
            )
        )
        if record is None:
            record = model(organization_id=user.organization_id, **_model_values(config, payload))
            db.add(record)
            _flush(db)
            action = "create"
            summary = f"Created {config['label']} record {code} from import"
        else:
            for field, value in _model_values(config, payload).items():
                setattr(record, field, value)
            if record.is_deleted:
                record.is_deleted = False
                record.deleted_at = None
                action = MasterDataAction.RESTORE
                summary = f"Restored and updated {config['label']} record {code} from import"
            else:
                action = "update"
                summary = f"Updated {config['label']} record {code} from import"
        _audit_record(db, config=config, record=record, user=user, action=action, summary=summary, request=request)
        imported_count += 1

    error_count = len(errors)
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="import",
        entity_type="master_data",
        entity_label=config["label"],
        summary=f"Imported {imported_count} {config['label']} rows with {error_count} validation errors",
        request=request,
    )
    _commit(db)
    return MasterDataImportResponse(
        imported_count=imported_count,
        error_count=error_count,
        errors=errors[:100],
        success=error_count == 0,
    )

