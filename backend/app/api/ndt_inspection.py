"""NDT Inspection Register API."""

from datetime import date
from fastapi import APIRouter, Depends, Query, Request, Response
from app.api.deps import Current, Db, require
from app.schemas.ndt_inspection import NdtBulkActionOut, NdtBulkCreate, NdtEntryOut, NdtExportAudit, NdtIDs, NdtImportOut, NdtImportRequest, NdtReference, NdtUpdate
from app.services import ndt_inspection as service

router = APIRouter(prefix="/ndt-inspections", tags=["NDT Inspection Register"])

@router.get("/reference", response_model=NdtReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current): return service.reference_data(db, user.organization_id)

def _list(db, user, rig_id, well_id, scope, date_from, date_to, deleted=False):
    return service.list_entries(db, user.organization_id, rig_id=rig_id, well_id=well_id, scope=scope, date_from=date_from, date_to=date_to, deleted=deleted)

@router.get("/entries/deleted", response_model=list[NdtEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def deleted_entries(db: Db, user: Current, rig_id: str = "", well_id: str = "", scope: str = "", date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to")):
    return _list(db, user, rig_id, well_id, scope, date_from, date_to, True)

@router.get("/entries", response_model=list[NdtEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def entries(db: Db, user: Current, rig_id: str = "", well_id: str = "", scope: str = "", date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to")):
    return _list(db, user, rig_id, well_id, scope, date_from, date_to)

@router.post("/entries/bulk", response_model=list[NdtEntryOut], status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def create(data: NdtBulkCreate, request: Request, db: Db, user: Current): return service.create_bulk(db, user.organization_id, data, user, request)

@router.put("/entries/{entry_id}", response_model=NdtEntryOut, dependencies=[Depends(require("daily-cost:update"))])
def update(entry_id: str, data: NdtUpdate, request: Request, db: Db, user: Current): return service.update_entry(db, user.organization_id, entry_id, data, user, request)

@router.post("/entries/bulk-delete", response_model=NdtBulkActionOut, dependencies=[Depends(require("daily-cost:delete"))])
def delete(data: NdtIDs, request: Request, db: Db, user: Current): return service.soft_delete_entries(db, user.organization_id, data.ids, user, request)

@router.post("/entries/bulk-restore", response_model=NdtBulkActionOut, dependencies=[Depends(require("daily-cost:restore"))])
def restore(data: NdtIDs, request: Request, db: Db, user: Current): return service.restore_entries(db, user.organization_id, data.ids, user, request)

@router.post("/entries/bulk-permanent-delete", response_model=NdtBulkActionOut, dependencies=[Depends(require("daily-cost:permanent-delete"))])
def permanent_delete(data: NdtIDs, request: Request, db: Db, user: Current): return service.permanently_delete_entries(db, user.organization_id, data.ids, user, request)

@router.post("/import", response_model=NdtImportOut, dependencies=[Depends(require("daily-cost:import"))])
def import_rows(data: NdtImportRequest, request: Request, db: Db, user: Current): return service.import_entries(db, user.organization_id, data, user, request)

@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: NdtExportAudit, request: Request, db: Db, user: Current):
    service.audit_export(db, user.organization_id, data, user, request)
    return Response(status_code=204)
