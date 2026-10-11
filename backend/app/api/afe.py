"""Tenant-scoped AFE register and AFE cost estimation APIs.

Header edits and deletion are draft-only. Estimate lines are editable only while the
AFE is a draft. Status moves are controlled from the cost estimation workspace and each
move requires its own permission. Every write is audited in the same transaction.
"""

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import Current, Db, require
from app.schemas.afe import (
    AfeBulkActionResponse,
    AfeCreate,
    AfeEstimateOut,
    AfeExportAudit,
    AfeIDs,
    AfeImportRequest,
    AfeImportResponse,
    AfeOut,
    AfeOverview,
    AfeReference,
    AfeStatusIn,
    AfeUpdate,
    EstimateIn,
)
from app.services import afe as service

router = APIRouter(prefix="/afe", tags=["AFE Management"])


@router.get("/reference", response_model=AfeReference, dependencies=[Depends(require("afe:read"))])
def reference(db: Db, user: Current) -> AfeReference:
    return service.reference_data(db, user.organization_id)


@router.get("/overview", response_model=AfeOverview, dependencies=[Depends(require("afe:read"))])
def overview(db: Db, user: Current) -> AfeOverview:
    return service.overview(db, user.organization_id, user)


@router.get("/afes", response_model=list[AfeOut], dependencies=[Depends(require("afe:read"))])
def list_afes(db: Db, user: Current) -> list[AfeOut]:
    return service.list_afes(db, user.organization_id, deleted=False)


@router.get("/afes/deleted", response_model=list[AfeOut], dependencies=[Depends(require("afe:read"))])
def list_deleted(db: Db, user: Current) -> list[AfeOut]:
    return service.list_afes(db, user.organization_id, deleted=True)


@router.post("/afes", response_model=AfeOut, dependencies=[Depends(require("afe:create"))])
def create_afe(data: AfeCreate, request: Request, db: Db, user: Current) -> AfeOut:
    return service.create_afe(db, user.organization_id, data, user, request)


@router.post("/afes/import", response_model=AfeImportResponse, dependencies=[Depends(require("afe:import"))])
def import_afes(data: AfeImportRequest, request: Request, db: Db, user: Current) -> AfeImportResponse:
    imported, errors = service.import_afes(db, user.organization_id, data.rows, user, request)
    return AfeImportResponse(imported_count=imported, error_count=len(errors), errors=errors, success=not errors)


@router.post("/afes/bulk-delete", response_model=AfeBulkActionResponse, dependencies=[Depends(require("afe:delete"))])
def bulk_delete(data: AfeIDs, request: Request, db: Db, user: Current) -> AfeBulkActionResponse:
    return AfeBulkActionResponse(affected_count=service.bulk_delete(db, user.organization_id, data, user, request))


@router.post("/afes/bulk-restore", response_model=AfeBulkActionResponse, dependencies=[Depends(require("afe:restore"))])
def bulk_restore(data: AfeIDs, request: Request, db: Db, user: Current) -> AfeBulkActionResponse:
    return AfeBulkActionResponse(affected_count=service.bulk_restore(db, user.organization_id, data, user, request))


@router.post(
    "/afes/bulk-permanent-delete",
    response_model=AfeBulkActionResponse,
    dependencies=[Depends(require("afe:permanent-delete"))],
)
def bulk_permanent_delete(data: AfeIDs, request: Request, db: Db, user: Current) -> AfeBulkActionResponse:
    return AfeBulkActionResponse(
        affected_count=service.permanently_delete(db, user.organization_id, data.ids, user, request)
    )


@router.get("/afes/{afe_id}", response_model=AfeOut, dependencies=[Depends(require("afe:read"))])
def get_afe(afe_id: str, db: Db, user: Current) -> AfeOut:
    afe = service.afe_or_404(db, afe_id, user.organization_id)
    return service.afe_out_for(db, user.organization_id, afe)


@router.patch("/afes/{afe_id}", response_model=AfeOut, dependencies=[Depends(require("afe:update"))])
def update_afe(afe_id: str, data: AfeUpdate, request: Request, db: Db, user: Current) -> AfeOut:
    return service.update_afe(db, user.organization_id, afe_id, data, user, request)


@router.delete("/afes/{afe_id}", response_model=AfeOut, dependencies=[Depends(require("afe:delete"))])
def delete_afe(afe_id: str, request: Request, db: Db, user: Current) -> AfeOut:
    return service.delete_afe(db, user.organization_id, afe_id, user, request)


@router.post("/afes/{afe_id}/restore", response_model=AfeOut, dependencies=[Depends(require("afe:restore"))])
def restore_afe(afe_id: str, request: Request, db: Db, user: Current) -> AfeOut:
    return service.restore_afe(db, user.organization_id, afe_id, user, request)


@router.delete(
    "/afes/{afe_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("afe:permanent-delete"))],
)
def permanently_delete_afe(afe_id: str, request: Request, db: Db, user: Current) -> Response:
    service.permanently_delete(db, user.organization_id, [afe_id], user, request)
    return Response(status_code=204)


@router.get("/afes/{afe_id}/estimate", response_model=AfeEstimateOut, dependencies=[Depends(require("afe:read"))])
def get_estimate(afe_id: str, db: Db, user: Current) -> AfeEstimateOut:
    return service.get_estimate(db, user.organization_id, afe_id)


@router.post(
    "/afes/{afe_id}/estimate/preview",
    response_model=AfeEstimateOut,
    dependencies=[Depends(require("afe:read"))],
)
def preview_estimate(afe_id: str, data: EstimateIn, db: Db, user: Current) -> AfeEstimateOut:
    return service.preview_estimate(db, user.organization_id, afe_id, data)


@router.put("/afes/{afe_id}/estimate", response_model=AfeEstimateOut, dependencies=[Depends(require("afe:estimate"))])
def save_estimate(afe_id: str, data: EstimateIn, request: Request, db: Db, user: Current) -> AfeEstimateOut:
    return service.save_estimate(db, user.organization_id, afe_id, data, user, request)


@router.post("/afes/{afe_id}/status", response_model=AfeOut, dependencies=[Depends(require("afe:read"))])
def change_status(afe_id: str, data: AfeStatusIn, request: Request, db: Db, user: Current) -> AfeOut:
    afe = service.change_status(db, user.organization_id, afe_id, data.action, data.remarks, user, request)
    return afe


@router.post("/afes/{afe_id}/print", status_code=204, dependencies=[Depends(require("afe:export"))])
def print_afe(afe_id: str, request: Request, db: Db, user: Current) -> Response:
    service.record_print(db, user.organization_id, afe_id, user, request)
    return Response(status_code=204)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("afe:export"))])
def export_audit(data: AfeExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(
        db,
        user,
        module=data.module,
        fmt=data.format,
        record_count=data.record_count,
        include_deleted=data.include_deleted,
        request=request,
    )
    return Response(status_code=204)
