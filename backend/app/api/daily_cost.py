"""Tenant-scoped Daily Cost Management endpoints."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import Current, Db, require
from app.schemas.daily_cost import (
    DailyCostBaselineOut,
    DailyCostDayOut,
    DailyCostEntryCreate,
    DailyCostEntryOut,
    DailyCostExportAudit,
    DailyCostIDs,
    DailyCostImportRequest,
    DailyCostImportResponse,
    DailyCostOverview,
    DailyCostPreviewOut,
    DailyCostReference,
    DailyCostReopenIn,
    DailyCostSaveIn,
    DailyCostStatusIn,
)
from app.services import daily_cost as service

router = APIRouter(prefix="/daily-cost", tags=["Daily Cost Management"])


@router.get("/reference", response_model=DailyCostReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current) -> DailyCostReference:
    return service.reference_data(db, user.organization_id)


@router.get("/overview", response_model=DailyCostOverview, dependencies=[Depends(require("daily-cost:read"))])
def overview(db: Db, user: Current) -> DailyCostOverview:
    return service.overview(db, user.organization_id, user)


@router.get("/entries/deleted", response_model=list[DailyCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def deleted_entries(db: Db, user: Current) -> list[DailyCostEntryOut]:
    return service.list_entries(db, user.organization_id, deleted=True)


@router.get("/entries", response_model=list[DailyCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def list_entries(db: Db, user: Current) -> list[DailyCostEntryOut]:
    return service.list_entries(db, user.organization_id, deleted=False)


@router.post("/entries", response_model=DailyCostDayOut, status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def create_entry(data: DailyCostEntryCreate, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.create_entry(db, user.organization_id, data, user, request)


@router.post("/entries/bulk-delete", dependencies=[Depends(require("daily-cost:delete"))])
def bulk_delete(data: DailyCostIDs, request: Request, db: Db, user: Current) -> dict[str, int]:
    return {"affected_count": service.bulk_soft_delete(db, user.organization_id, data, user, request)}


@router.post("/entries/bulk-restore", dependencies=[Depends(require("daily-cost:restore"))])
def bulk_restore(data: DailyCostIDs, request: Request, db: Db, user: Current) -> dict[str, int]:
    return {"affected_count": service.bulk_restore(db, user.organization_id, data, user, request)}


@router.post("/entries/bulk-permanent-delete", dependencies=[Depends(require("daily-cost:permanent-delete"))])
def bulk_permanent_delete(data: DailyCostIDs, request: Request, db: Db, user: Current) -> dict[str, int]:
    return {"affected_count": service.permanently_delete(db, user.organization_id, data.ids, user, request)}


@router.get("/entries/{entry_id}/baseline", response_model=DailyCostBaselineOut, dependencies=[Depends(require("daily-cost:read"))])
def baseline(entry_id: str, db: Db, user: Current) -> DailyCostBaselineOut:
    return service.context_for_entry(db, user.organization_id, entry_id)


@router.get("/entries/{entry_id}/previous", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:read"))])
def previous_entry(entry_id: str, db: Db, user: Current) -> DailyCostDayOut:
    return service.previous_day(db, user.organization_id, entry_id)


@router.get("/entries/{entry_id}", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:read"))])
def get_entry(entry_id: str, db: Db, user: Current) -> DailyCostDayOut:
    return service.get_day(db, user.organization_id, entry_id)


@router.put("/entries/{entry_id}/preview", response_model=DailyCostPreviewOut, dependencies=[Depends(require("daily-cost:read"))])
def preview_entry(entry_id: str, data: DailyCostSaveIn, db: Db, user: Current) -> DailyCostPreviewOut:
    return service.preview_day(db, user.organization_id, entry_id, data)


@router.put("/entries/{entry_id}", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:update"))])
def save_entry(entry_id: str, data: DailyCostSaveIn, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.save_day(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/{entry_id}/import", response_model=DailyCostImportResponse, dependencies=[Depends(require("daily-cost:import"))])
def import_entry(entry_id: str, data: DailyCostImportRequest, request: Request, db: Db, user: Current) -> DailyCostImportResponse:
    return service.import_daily_cost(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/{entry_id}/submit", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:submit"))])
def submit_entry(entry_id: str, data: DailyCostStatusIn, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.submit_entry(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/{entry_id}/reopen", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:reopen"))])
def reopen_entry(entry_id: str, data: DailyCostReopenIn, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.reopen_entry(db, user.organization_id, entry_id, data, user, request)


@router.delete("/entries/{entry_id}", response_model=DailyCostEntryOut, dependencies=[Depends(require("daily-cost:delete"))])
def delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> DailyCostEntryOut:
    return service.soft_delete_entry(db, user.organization_id, entry_id, user, request)


@router.post("/entries/{entry_id}/restore", response_model=DailyCostEntryOut, dependencies=[Depends(require("daily-cost:restore"))])
def restore_entry(entry_id: str, request: Request, db: Db, user: Current) -> DailyCostEntryOut:
    return service.restore_entry(db, user.organization_id, entry_id, user, request)


@router.delete("/entries/{entry_id}/permanent", status_code=204, dependencies=[Depends(require("daily-cost:permanent-delete"))])
def permanently_delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> Response:
    service.permanently_delete(db, user.organization_id, [entry_id], user, request)
    return Response(status_code=204)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: DailyCostExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(db, user, data, request)
    return Response(status_code=204)
