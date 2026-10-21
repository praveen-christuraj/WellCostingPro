"""Tenant-scoped Mud Cost Analysis endpoints."""
from datetime import date
from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import Current, Db, require
from app.schemas.mud_cost import (
    MudCostBalanceView,
    MudCostBulkActionOut,
    MudCostEntryCreate,
    MudCostEntryOut,
    MudCostEntryUpdate,
    MudCostOpeningStockIn,
    MudCostExportAudit,
    MudCostIDs,
    MudCostImportRequest,
    MudCostImportResponse,
    MudCostMaterialBalanceOut,
    MudCostReconciliationOut,
    MudCostReference,
    MudCostSectionSettingIn,
    MudCostSectionSettingOut,
)
from app.services import mud_cost as service

router = APIRouter(prefix="/mud-cost", tags=["Mud Cost Analysis"])


@router.get("/reference", response_model=MudCostReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current) -> MudCostReference:
    return service.reference_data(db, user.organization_id)


@router.get("/entries/deleted", response_model=list[MudCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def deleted_entries(
    db: Db,
    user: Current,
    rig_id: str = Query(default="", max_length=36),
    well_id: str = Query(default="", max_length=36),
    section_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[MudCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, rig_id=rig_id, well_id=well_id, section_id=section_id,
        date_from=date_from, date_to=date_to, deleted=True,
    )


@router.get("/entries", response_model=list[MudCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def list_entries(
    db: Db,
    user: Current,
    rig_id: str = Query(default="", max_length=36),
    well_id: str = Query(default="", max_length=36),
    section_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[MudCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, rig_id=rig_id, well_id=well_id, section_id=section_id,
        date_from=date_from, date_to=date_to,
    )


@router.get(
    "/material-balance",
    response_model=MudCostMaterialBalanceOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def material_balance(
    db: Db,
    user: Current,
    rig_id: str = Query(min_length=1, max_length=36),
    well_id: str = Query(min_length=1, max_length=36),
    section_id: str = Query(default="", max_length=36),
    view: MudCostBalanceView = Query(default="daily"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> MudCostMaterialBalanceOut:
    return service.material_balance(
        db, user.organization_id, rig_id=rig_id, well_id=well_id, section_id=section_id,
        view=view, date_from=date_from, date_to=date_to,
    )


@router.get(
    "/section-settings",
    response_model=list[MudCostSectionSettingOut],
    dependencies=[Depends(require("daily-cost:read"))],
)
def section_settings(
    db: Db,
    user: Current,
    rig_id: str = Query(min_length=1, max_length=36),
    well_id: str = Query(min_length=1, max_length=36),
) -> list[MudCostSectionSettingOut]:
    return service.section_settings(db, user.organization_id, rig_id, well_id)


@router.put(
    "/section-settings",
    response_model=MudCostSectionSettingOut,
    dependencies=[Depends(require("daily-cost:update"))],
)
def save_section_setting(
    data: MudCostSectionSettingIn,
    request: Request,
    db: Db,
    user: Current,
) -> MudCostSectionSettingOut:
    return service.upsert_section_setting(db, user.organization_id, data, user, request)


@router.get(
    "/reconciliation",
    response_model=MudCostReconciliationOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def reconciliation(
    db: Db,
    user: Current,
    rig_id: str = Query(min_length=1, max_length=36),
    well_id: str = Query(min_length=1, max_length=36),
    section_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_draft: bool = Query(default=True),
) -> MudCostReconciliationOut:
    return service.mud_cost_reconciliation(
        db, user.organization_id, rig_id=rig_id, well_id=well_id, section_id=section_id,
        date_from=date_from, date_to=date_to, include_draft=include_draft,
    )


@router.post(
    "/entries",
    response_model=MudCostEntryOut,
    status_code=201,
    dependencies=[Depends(require("daily-cost:create"))],
)
def create_entry(data: MudCostEntryCreate, request: Request, db: Db, user: Current) -> MudCostEntryOut:
    return service.create_entry(db, user.organization_id, data, user, request)


@router.put(
    "/entries/{entry_id}",
    response_model=MudCostEntryOut,
    dependencies=[Depends(require("daily-cost:update"))],
)
def update_entry(
    entry_id: str,
    data: MudCostEntryUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> MudCostEntryOut:
    return service.update_entry(db, user.organization_id, entry_id, data, user, request)


@router.put(
    "/entries/{entry_id}/opening-stock",
    response_model=MudCostEntryOut,
    dependencies=[Depends(require("mud-cost:opening-stock-update"))],
)
def update_opening_stock(
    entry_id: str, data: MudCostOpeningStockIn, request: Request, db: Db, user: Current,
) -> MudCostEntryOut:
    return service.update_opening_stock(db, user.organization_id, entry_id, data, user, request)


@router.get(
    "/entries/{entry_id}",
    response_model=MudCostEntryOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def get_entry(entry_id: str, db: Db, user: Current) -> MudCostEntryOut:
    return service.get_entry(db, user.organization_id, entry_id)


@router.post(
    "/entries/import",
    response_model=MudCostImportResponse,
    dependencies=[Depends(require("daily-cost:import"))],
)
def import_entries(
    data: MudCostImportRequest,
    request: Request,
    db: Db,
    user: Current,
) -> MudCostImportResponse:
    return service.import_entries(db, user.organization_id, data, user, request)


@router.post(
    "/entries/bulk-delete",
    response_model=MudCostBulkActionOut,
    dependencies=[Depends(require("daily-cost:delete"))],
)
def bulk_delete(data: MudCostIDs, request: Request, db: Db, user: Current) -> MudCostBulkActionOut:
    return MudCostBulkActionOut(affected_count=service.soft_delete_entries(
        db, user.organization_id, data.ids, user, request,
    ))


@router.post(
    "/entries/bulk-restore",
    response_model=MudCostBulkActionOut,
    dependencies=[Depends(require("daily-cost:restore"))],
)
def bulk_restore(data: MudCostIDs, request: Request, db: Db, user: Current) -> MudCostBulkActionOut:
    return MudCostBulkActionOut(affected_count=service.restore_entries(
        db, user.organization_id, data.ids, user, request,
    ))


@router.post(
    "/entries/bulk-permanent-delete",
    response_model=MudCostBulkActionOut,
    dependencies=[Depends(require("daily-cost:permanent-delete"))],
)
def bulk_permanent_delete(
    data: MudCostIDs,
    request: Request,
    db: Db,
    user: Current,
) -> MudCostBulkActionOut:
    return MudCostBulkActionOut(affected_count=service.permanently_delete_entries(
        db, user.organization_id, data.ids, user, request,
    ))


@router.delete(
    "/entries/{entry_id}",
    response_model=MudCostEntryOut,
    dependencies=[Depends(require("daily-cost:delete"))],
)
def delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> MudCostEntryOut:
    service.soft_delete_entries(db, user.organization_id, [entry_id], user, request)
    return service.get_deleted_entry(db, user.organization_id, entry_id)


@router.post(
    "/entries/{entry_id}/restore",
    response_model=MudCostEntryOut,
    dependencies=[Depends(require("daily-cost:restore"))],
)
def restore_entry(entry_id: str, request: Request, db: Db, user: Current) -> MudCostEntryOut:
    service.restore_entries(db, user.organization_id, [entry_id], user, request)
    return service.get_entry(db, user.organization_id, entry_id)


@router.delete(
    "/entries/{entry_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("daily-cost:permanent-delete"))],
)
def permanently_delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> Response:
    service.permanently_delete_entries(db, user.organization_id, [entry_id], user, request)
    return Response(status_code=204)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: MudCostExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(db, user, data, request)
    return Response(status_code=204)
