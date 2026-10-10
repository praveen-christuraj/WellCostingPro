"""Tenant-scoped Services register APIs for Master Data Management."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Current, Db, require
from app.models import Service, Vendor
from app.models.service_master import SERVICE_CATEGORIES, SERVICE_PROVIDER_TYPES
from app.schemas.master_data import MasterDataBulkActionResponse, MasterDataIDs, MasterDataImportRequest, MasterDataImportResponse
from app.schemas.service_master import (
    ServiceBreakdown,
    ServiceCreate,
    ServiceOut,
    ServiceOverview,
    ServiceUpdate,
    normalize_provider_type,
)
from app.services import audit

router = APIRouter(prefix="/master-data/services", tags=["Master Data Management · Services"])

SERVICE_ENTITY = "service"


class ServiceAction:
    CREATE = "create"
    UPDATE = "update"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
    PERMANENT_DELETE = "permanent_delete"


def _service_code_exists(db: Session, organization_id: str, code: str, *, exclude_id: str | None = None) -> Service | None:
    statement = select(Service).where(Service.organization_id == organization_id, func.upper(Service.service_code) == code)
    if exclude_id:
        statement = statement.where(Service.id != exclude_id)
    return db.scalar(statement)


def _service_out(service: Service) -> ServiceOut:
    vendor = service.vendor
    return ServiceOut(
        id=service.id,
        service_code=service.service_code,
        service_name=service.service_name,
        service_category=service.service_category,
        provider_type=service.provider_type,
        vendor_id=service.vendor_id,
        vendor_code=vendor.vendor_code if vendor else None,
        vendor_name=vendor.vendor_name if vendor else None,
        description=service.description or "",
        is_deleted=service.is_deleted,
        deleted_at=service.deleted_at,
        created_at=service.created_at,
        updated_at=service.updated_at,
    )


def _audit_service(
    db: Session,
    *,
    service: Service,
    user: Any,
    action: str,
    summary: str,
    request: Request,
) -> None:
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type=SERVICE_ENTITY,
        entity_id=service.id,
        entity_label=f"Services · {service.service_code}",
        summary=summary,
        request=request,
    )


def _service_or_404(
    db: Session,
    service_id: str,
    organization_id: str,
    *,
    include_deleted: bool = True,
) -> Service:
    statement = select(Service).where(
        Service.id == service_id,
        Service.organization_id == organization_id,
    )
    if not include_deleted:
        statement = statement.where(Service.is_deleted.is_(False))
    service = db.scalar(statement)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found in this workspace")
    return service


def _vendor_for_service(
    db: Session,
    *,
    organization_id: str,
    vendor_id: str | None,
    allow_deleted_existing: bool = False,
    existing_vendor_id: str | None = None,
) -> Vendor:
    if not vendor_id:
        raise ValueError("Select a vendor for every service")

    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if vendor is not None:
        return vendor

    # An already deleted service may be edited in Deleted Entries while its
    # vendor is also deleted. Keep that historical link, but it must be restored
    # only after the vendor itself has been restored.
    if allow_deleted_existing and vendor_id == existing_vendor_id:
        vendor = db.scalar(
            select(Vendor).where(
                Vendor.id == vendor_id,
                Vendor.organization_id == organization_id,
            )
        )
        if vendor is not None:
            return vendor
    raise ValueError("Select a vendor that exists in this workspace and is not deleted")


def _validate_service_payload(
    db: Session,
    *,
    organization_id: str,
    payload: dict[str, Any],
    service: Service | None = None,
) -> dict[str, Any]:
    vendor = _vendor_for_service(
        db,
        organization_id=organization_id,
        vendor_id=payload.get("vendor_id"),
        allow_deleted_existing=bool(service and service.is_deleted),
        existing_vendor_id=service.vendor_id if service else None,
    )
    return {
        "service_code": payload["service_code"].strip().upper(),
        "service_name": payload["service_name"].strip(),
        "service_category": payload["service_category"],
        "provider_type": payload["provider_type"],
        "vendor_id": vendor.id,
        "description": payload.get("description", "").strip() if payload.get("description") else "",
    }


def _service_name_exists(
    db: Session,
    organization_id: str,
    service_name: str,
    *,
    exclude_id: str | None = None,
) -> Service | None:
    statement = select(Service).where(
        Service.organization_id == organization_id,
        func.lower(Service.service_name) == service_name.casefold(),
    )
    if exclude_id:
        statement = statement.where(Service.id != exclude_id)
    return db.scalar(statement)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A service with this name or code already exists in this workspace",
        ) from error


def _flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A service with this name or code already exists in this workspace",
        ) from error


def _get_vendor_reference(db: Session, organization_id: str, reference: Any) -> Vendor:
    text_reference = str(reference or "").strip()
    if not text_reference:
        raise ValueError("Service Provider (vendor_code) is required for every service")

    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == text_reference,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if vendor is not None:
        return vendor

    vendor = db.scalar(
        select(Vendor).where(
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
            func.upper(Vendor.vendor_code) == text_reference.upper(),
        )
    )
    if vendor is not None:
        return vendor

    matching_names = list(
        db.scalars(
            select(Vendor).where(
                Vendor.organization_id == organization_id,
                Vendor.is_deleted.is_(False),
                func.lower(Vendor.vendor_name) == text_reference.casefold(),
            )
        ).all()
    )
    if len(matching_names) == 1:
        return matching_names[0]
    if len(matching_names) > 1:
        raise ValueError(f"Vendor name '{text_reference}' is ambiguous; use vendor_code")
    raise ValueError(f"Service Provider/Vendor '{text_reference}' not found in this workspace")


def _normalize_import_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        str(key).strip().casefold().replace(" ", "_").replace("-", "_"): value
        for key, value in row.items()
    }

    def first(*names: str) -> Any:
        for name in names:
            value = normalized.get(name)
            if value not in (None, ""):
                return value
        return None

    return {
        "service_code": first("service_code", "code"),
        "service_name": first("service_name", "name", "service"),
        # The legacy Services tab did not carry this category; its records keep
        # working on import by defaulting to the drilling-services catalogue.
        "service_category": first("service_category", "category", "service_group") or "Drilling Services",
        "provider_type": first("provider_type", "provider", "service_provider_type", "provider_type_name"),
        "vendor_reference": first("vendor_code", "vendor_id", "vendor", "supplier_code", "supplier", "service_provider"),
        "description": first("description", "desc", "remarks", "notes") or "",
    }


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )


def _services_for_ids(
    db: Session,
    ids: list[str],
    organization_id: str,
    *,
    deleted: bool,
) -> list[Service]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate service IDs are not allowed")
    services = list(
        db.scalars(
            select(Service).where(
                Service.organization_id == organization_id,
                Service.id.in_(ids),
            )
        ).all()
    )
    if len(services) != len(ids):
        raise HTTPException(status_code=404, detail="One or more services were not found in this workspace")
    if any(service.is_deleted is not deleted for service in services):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"Bulk action requires only {expected} services")
    return services


def _ensure_restorable_vendor(db: Session, service: Service, organization_id: str) -> None:
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == service.vendor_id,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if vendor is None:
        raise HTTPException(
            status_code=409,
            detail="Select or restore the service's vendor before restoring this service",
        )


@router.get("", response_model=list[ServiceOut], dependencies=[Depends(require("master-data:read"))])
def list_services(
    db: Db,
    user: Current,
    search: str | None = Query(default=None, max_length=200),
    service_category: str | None = Query(default=None, max_length=50),
    provider_type: str | None = Query(default=None, max_length=30),
    vendor_id: str | None = Query(default=None, max_length=36),
) -> list[ServiceOut]:
    statement = select(Service).where(
        Service.organization_id == user.organization_id,
        Service.is_deleted.is_(False),
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Service.service_code.ilike(like),
                Service.service_name.ilike(like),
                Service.description.ilike(like),
                Service.service_category.ilike(like),
                Service.provider_type.ilike(like),
            )
        )
    if service_category:
        statement = statement.where(Service.service_category == service_category)
    if provider_type:
        statement = statement.where(Service.provider_type == provider_type)
    if vendor_id:
        statement = statement.where(Service.vendor_id == vendor_id)
    services = db.scalars(
        statement.order_by(Service.service_code, Service.created_at.desc())
    ).all()
    return [_service_out(service) for service in services]


@router.get("/deleted", response_model=list[ServiceOut], dependencies=[Depends(require("master-data:read"))])
def list_deleted_services(db: Db, user: Current) -> list[ServiceOut]:
    services = db.scalars(
        select(Service)
        .where(Service.organization_id == user.organization_id, Service.is_deleted.is_(True))
        .order_by(Service.deleted_at.desc(), Service.service_code)
    ).all()
    return [_service_out(service) for service in services]


@router.get("/overview", response_model=ServiceOverview, dependencies=[Depends(require("master-data:read"))])
def service_overview(db: Db, user: Current) -> ServiceOverview:
    organization_id = user.organization_id
    active = Service.is_deleted.is_(False)
    deleted = Service.is_deleted.is_(True)
    active_count = db.scalar(
        select(func.count(Service.id)).where(Service.organization_id == organization_id, active)
    ) or 0
    deleted_count = db.scalar(
        select(func.count(Service.id)).where(Service.organization_id == organization_id, deleted)
    ) or 0

    category_rows = db.execute(
        select(Service.service_category, func.count(Service.id))
        .where(Service.organization_id == organization_id, active)
        .group_by(Service.service_category)
    ).all()
    provider_rows = db.execute(
        select(Service.provider_type, func.count(Service.id))
        .where(Service.organization_id == organization_id, active)
        .group_by(Service.provider_type)
    ).all()
    category_counts = dict(category_rows)
    provider_counts = dict(provider_rows)
    return ServiceOverview(
        active_count=active_count,
        deleted_count=deleted_count,
        category_counts=[
            ServiceBreakdown(key=category, label=category, count=category_counts.get(category, 0))
            for category in SERVICE_CATEGORIES
        ],
        provider_type_counts=[
            ServiceBreakdown(key=provider, label=provider, count=provider_counts.get(provider, 0))
            for provider in SERVICE_PROVIDER_TYPES
        ],
    )


@router.get("/{service_id}", response_model=ServiceOut, dependencies=[Depends(require("master-data:read"))])
def get_service(service_id: str, db: Db, user: Current) -> ServiceOut:
    service = _service_or_404(db, service_id, user.organization_id)
    return _service_out(service)


@router.post("", response_model=ServiceOut, status_code=201, dependencies=[Depends(require("master-data:create"))])
def create_service(data: ServiceCreate, request: Request, db: Db, user: Current) -> ServiceOut:
    payload = data.model_dump()
    try:
        values = _validate_service_payload(db, organization_id=user.organization_id, payload=payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if _service_code_exists(db, user.organization_id, values["service_code"]):
        raise HTTPException(status_code=409, detail="Service code already exists in this workspace")
    existing = _service_name_exists(db, user.organization_id, values["service_name"])
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Service '{values['service_name']}' already exists as {existing.service_code}; restore or permanently delete it first",
        )

    service = Service(
        organization_id=user.organization_id,
        **values,
    )
    db.add(service)
    _flush(db)
    _audit_service(
        db,
        service=service,
        user=user,
        action=ServiceAction.CREATE,
        summary=f"Created {service.service_category.lower()} service {service.service_code} — {service.service_name}",
        request=request,
    )
    _commit(db)
    db.refresh(service)
    return _service_out(service)


@router.patch("/{service_id}", response_model=ServiceOut, dependencies=[Depends(require("master-data:update"))])
def update_service(
    service_id: str,
    data: ServiceUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> ServiceOut:
    service = _service_or_404(db, service_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    merged = {
        "service_code": service.service_code,
        "service_name": service.service_name,
        "service_category": service.service_category,
        "provider_type": service.provider_type,
        "vendor_id": service.vendor_id,
        "description": service.description or "",
    }
    merged.update(supplied)
    try:
        validated = ServiceCreate.model_validate(merged).model_dump()
        values = _validate_service_payload(
            db,
            organization_id=user.organization_id,
            payload=validated,
            service=service,
        )
    except (ValidationError, ValueError) as error:
        if isinstance(error, ValidationError):
            raise HTTPException(status_code=422, detail=_validation_message(error)) from error
        raise HTTPException(status_code=422, detail=str(error)) from error

    if _service_code_exists(db, user.organization_id, values["service_code"], exclude_id=service.id):
        raise HTTPException(status_code=409, detail="Service code already exists in this workspace")
    duplicate = _service_name_exists(
        db, user.organization_id, values["service_name"], exclude_id=service.id
    )
    if duplicate:
        raise HTTPException(status_code=409, detail=f"Service name '{values['service_name']}' is already in use")

    changed = [field for field, value in values.items() if getattr(service, field) != value]
    if changed:
        for field in changed:
            setattr(service, field, values[field])
        _audit_service(
            db,
            service=service,
            user=user,
            action=ServiceAction.UPDATE,
            summary=f"Updated service {service.service_code}: {', '.join(sorted(changed))}",
            request=request,
        )
        _commit(db)
        db.refresh(service)
    return _service_out(service)


@router.delete("/{service_id}", response_model=ServiceOut, dependencies=[Depends(require("master-data:delete"))])
def soft_delete_service(service_id: str, request: Request, db: Db, user: Current) -> ServiceOut:
    service = _service_or_404(db, service_id, user.organization_id, include_deleted=False)
    service.is_deleted = True
    service.deleted_at = datetime.now(timezone.utc)
    _audit_service(
        db,
        service=service,
        user=user,
        action=ServiceAction.SOFT_DELETE,
        summary=f"Moved service {service.service_code} to deleted entries",
        request=request,
    )
    _commit(db)
    db.refresh(service)
    return _service_out(service)


@router.post("/{service_id}/restore", response_model=ServiceOut, dependencies=[Depends(require("master-data:restore"))])
def restore_service(service_id: str, request: Request, db: Db, user: Current) -> ServiceOut:
    service = _service_or_404(db, service_id, user.organization_id)
    if not service.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted service can be restored")
    _ensure_restorable_vendor(db, service, user.organization_id)
    service.is_deleted = False
    service.deleted_at = None
    _audit_service(
        db,
        service=service,
        user=user,
        action=ServiceAction.RESTORE,
        summary=f"Restored service {service.service_code}",
        request=request,
    )
    _commit(db)
    db.refresh(service)
    return _service_out(service)


@router.delete("/{service_id}/permanent", status_code=204, dependencies=[Depends(require("master-data:permanent-delete"))])
def permanently_delete_service(service_id: str, request: Request, db: Db, user: Current) -> None:
    service = _service_or_404(db, service_id, user.organization_id)
    if not service.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted service can be permanently deleted")
    _audit_service(
        db,
        service=service,
        user=user,
        action=ServiceAction.PERMANENT_DELETE,
        summary=f"Permanently deleted service {service.service_code}",
        request=request,
    )
    db.delete(service)
    _commit(db)


@router.post("/bulk-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:delete"))])
def bulk_soft_delete_services(
    data: MasterDataIDs,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataBulkActionResponse:
    services = _services_for_ids(db, data.ids, user.organization_id, deleted=False)
    deleted_at = datetime.now(timezone.utc)
    for service in services:
        service.is_deleted = True
        service.deleted_at = deleted_at
        _audit_service(
            db,
            service=service,
            user=user,
            action=ServiceAction.SOFT_DELETE,
            summary=f"Moved service {service.service_code} to deleted entries (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(services))


@router.post("/bulk-restore", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:restore"))])
def bulk_restore_services(
    data: MasterDataIDs,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataBulkActionResponse:
    services = _services_for_ids(db, data.ids, user.organization_id, deleted=True)
    for service in services:
        _ensure_restorable_vendor(db, service, user.organization_id)
    for service in services:
        service.is_deleted = False
        service.deleted_at = None
        _audit_service(
            db,
            service=service,
            user=user,
            action=ServiceAction.RESTORE,
            summary=f"Restored service {service.service_code} (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(services))


@router.post("/bulk-permanent-delete", response_model=MasterDataBulkActionResponse, dependencies=[Depends(require("master-data:permanent-delete"))])
def bulk_permanent_delete_services(
    data: MasterDataIDs,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataBulkActionResponse:
    services = _services_for_ids(db, data.ids, user.organization_id, deleted=True)
    for service in services:
        _audit_service(
            db,
            service=service,
            user=user,
            action=ServiceAction.PERMANENT_DELETE,
            summary=f"Permanently deleted service {service.service_code} (bulk action)",
            request=request,
        )
        db.delete(service)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(services))


@router.post("/import", response_model=MasterDataImportResponse, dependencies=[Depends(require("master-data:import"))])
def import_services(
    data: MasterDataImportRequest,
    request: Request,
    db: Db,
    user: Current,
) -> MasterDataImportResponse:
    """Import previewed CSV/XLSX rows with legacy aliases and row-level errors."""
    imported = 0
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_codes: set[str] = set()

    for row_number, row in enumerate(data.rows, start=1):
        try:
            normalized = _normalize_import_row(row)
            provider_type = normalize_provider_type(normalized.get("provider_type"))
            vendor_reference = normalized.get("vendor_reference")
            vendor_id = _get_vendor_reference(db, user.organization_id, vendor_reference).id

            payload = ServiceCreate.model_validate(
                {
                    "service_code": normalized.get("service_code"),
                    "service_name": normalized.get("service_name"),
                    "service_category": normalized.get("service_category"),
                    "provider_type": provider_type,
                    "vendor_id": vendor_id,
                    "description": normalized.get("description") or "",
                }
            ).model_dump()
            values = _validate_service_payload(
                db,
                organization_id=user.organization_id,
                payload=payload,
            )
            name_key = values["service_name"].casefold()
            if name_key in seen_names:
                raise ValueError("duplicate service name in this import file")
            seen_names.add(name_key)
            if values["service_code"] in seen_codes:
                raise ValueError("duplicate service code in this import file")
            seen_codes.add(values["service_code"])

            with db.begin_nested():
                service = _service_code_exists(db, user.organization_id, values["service_code"])
                if service is None:
                    service = Service(
                        organization_id=user.organization_id,
                        **values,
                    )
                    db.add(service)
                    db.flush()
                    _audit_service(
                        db,
                        service=service,
                        user=user,
                        action=ServiceAction.CREATE,
                        summary=f"Created service {service.service_code} from import",
                        request=request,
                    )
                else:
                    was_deleted = service.is_deleted
                    changed = [field for field, value in values.items() if getattr(service, field) != value]
                    for field in changed:
                        setattr(service, field, values[field])
                    service.is_deleted = False
                    service.deleted_at = None
                    if was_deleted or changed:
                        action = ServiceAction.RESTORE if was_deleted else ServiceAction.UPDATE
                        verb = "Restored and updated" if was_deleted else "Updated"
                        _audit_service(
                            db,
                            service=service,
                            user=user,
                            action=action,
                            summary=f"{verb} service {service.service_code} from import",
                            request=request,
                        )
                    db.flush()
            imported += 1
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
        except (ValueError, IntegrityError) as error:
            errors.append(f"Row {row_number}: {error}")

    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="import",
        entity_type=SERVICE_ENTITY,
        entity_label="Services",
        summary=f"Imported {imported} services with {len(errors)} validation errors",
        request=request,
    )
    _commit(db)
    return MasterDataImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )
