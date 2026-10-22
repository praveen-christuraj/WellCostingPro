"""Tenant-scoped LIH Cost Register endpoints (Daily Cost Management)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import Current, Db, granted, owner, require
from app.schemas.lih_cost import (
    LihCostBulkActionOut,
    LihCostDayOut,
    LihCostDaySave,
    LihCostEntryCreate,
    LihCostEntryOut,
    LihCostEntryUpdate,
    LihCostExportAudit,
    LihCostIDs,
    LihCostImportRequest,
    LihCostImportResponse,
    LihCostLineIDs,
    LihCostLineIn,
    LihCostReference,
    LihCostReportOut,
)
from app.services import lih_cost as service

router = APIRouter(prefix="/lih-cost", tags=["LIH Cost Register"])


@router.get("/reference", response_model=LihCostReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current) -> LihCostReference:
    return service.reference_data(db, user.organization_id)


@router.get("/day", response_model=LihCostDayOut | None, dependencies=[Depends(require("daily-cost:read"))])
def day_for_date(
    db: Db,
    user: Current,
    well_id: str = Query(min_length=1, max_length=36),
    cost_date: date = Query(alias="date"),
) -> LihCostDayOut | None:
    """The register for one well and date, or null when that date has none yet."""
    return service.day_for_well_date(db, user.organization_id, well_id, cost_date)


@router.get("/entries/deleted", response_model=list[LihCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def deleted_entries(
    db: Db,
    user: Current,
    rig_id: str = Query(default="", max_length=36),
    well_id: str = Query(default="", max_length=36),
    afe_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[LihCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, rig_id=rig_id, well_id=well_id, afe_id=afe_id,
        date_from=date_from, date_to=date_to, deleted=True,
    )


@router.get("/entries", response_model=list[LihCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def list_entries(
    db: Db,
    user: Current,
    rig_id: str = Query(default="", max_length=36),
    well_id: str = Query(default="", max_length=36),
    afe_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[LihCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, rig_id=rig_id, well_id=well_id, afe_id=afe_id,
        date_from=date_from, date_to=date_to,
    )


@router.get(
    "/wells/{well_id}/report", response_model=LihCostReportOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def well_report(
    well_id: str,
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> LihCostReportOut:
    """Cumulative LIH cost and items for one well, used by the printed cost reports."""
    return service.well_report(db, user.organization_id, well_id, date_from=date_from, date_to=date_to)


@router.post("/entries", response_model=LihCostDayOut, status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def create_entry(data: LihCostEntryCreate, request: Request, db: Db, user: Current) -> LihCostDayOut:
    return service.create_entry(db, user.organization_id, data, user, request)


@router.put("/day", response_model=LihCostDayOut)
def save_day(data: LihCostDaySave, request: Request, db: Db, user: Current) -> LihCostDayOut:
    """Save a whole worksheet (header plus every item) in one transaction.

    Creating a new day needs ``daily-cost:create``; saving an existing day needs
    ``daily-cost:update``, so the two capabilities stay separate even though the
    worksheet uses a single endpoint.
    """
    needed = (
        "daily-cost:update"
        if service.day_exists(db, user.organization_id, data.well_id, data.cost_date)
        else "daily-cost:create"
    )
    if not owner(user) and needed not in granted(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return service.save_day(db, user.organization_id, data, user, request)


@router.post(
    "/import", response_model=LihCostImportResponse,
    dependencies=[Depends(require("daily-cost:import"))],
)
def import_lines(data: LihCostImportRequest, request: Request, db: Db, user: Current) -> LihCostImportResponse:
    """Import many LIH items from a spreadsheet, grouped by date."""
    return service.import_lines(db, user.organization_id, data, user, request)


@router.post("/entries/bulk-delete", response_model=LihCostBulkActionOut, dependencies=[Depends(require("daily-cost:delete"))])
def bulk_delete(data: LihCostIDs, request: Request, db: Db, user: Current) -> LihCostBulkActionOut:
    return service.soft_delete_entries(db, user.organization_id, data.ids, user, request)


@router.post("/entries/bulk-restore", response_model=LihCostBulkActionOut, dependencies=[Depends(require("daily-cost:restore"))])
def bulk_restore(data: LihCostIDs, request: Request, db: Db, user: Current) -> LihCostBulkActionOut:
    return service.restore_entries(db, user.organization_id, data.ids, user, request)


@router.post(
    "/entries/bulk-permanent-delete", response_model=LihCostBulkActionOut,
    dependencies=[Depends(require("daily-cost:permanent-delete"))],
)
def bulk_permanent_delete(data: LihCostIDs, request: Request, db: Db, user: Current) -> LihCostBulkActionOut:
    return service.permanently_delete_entries(db, user.organization_id, data.ids, user, request)


@router.get("/entries/{entry_id}", response_model=LihCostDayOut, dependencies=[Depends(require("daily-cost:read"))])
def get_entry(entry_id: str, db: Db, user: Current) -> LihCostDayOut:
    return service.get_entry(db, user.organization_id, entry_id)


@router.put("/entries/{entry_id}", response_model=LihCostDayOut, dependencies=[Depends(require("daily-cost:update"))])
def update_entry(entry_id: str, data: LihCostEntryUpdate, request: Request, db: Db, user: Current) -> LihCostDayOut:
    return service.update_entry(db, user.organization_id, entry_id, data, user, request)


@router.delete("/entries/{entry_id}", response_model=LihCostEntryOut, dependencies=[Depends(require("daily-cost:delete"))])
def delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> LihCostEntryOut:
    service.soft_delete_entries(db, user.organization_id, [entry_id], user, request)
    return service.get_deleted_entry(db, user.organization_id, entry_id)


@router.post("/entries/{entry_id}/restore", response_model=LihCostEntryOut, dependencies=[Depends(require("daily-cost:restore"))])
def restore_entry(entry_id: str, request: Request, db: Db, user: Current) -> LihCostEntryOut:
    service.restore_entries(db, user.organization_id, [entry_id], user, request)
    return service.get_entry(db, user.organization_id, entry_id).entry


@router.delete(
    "/entries/{entry_id}/permanent", status_code=204,
    dependencies=[Depends(require("daily-cost:permanent-delete"))],
)
def permanently_delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> Response:
    service.permanently_delete_entries(db, user.organization_id, [entry_id], user, request)
    return Response(status_code=204)


@router.post("/entries/{entry_id}/lines", response_model=LihCostDayOut, status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def add_line(entry_id: str, data: LihCostLineIn, request: Request, db: Db, user: Current) -> LihCostDayOut:
    return service.add_line(db, user.organization_id, entry_id, data, user, request)


@router.put(
    "/entries/{entry_id}/lines/{line_id}", response_model=LihCostDayOut,
    dependencies=[Depends(require("daily-cost:update"))],
)
def update_line(
    entry_id: str, line_id: str, data: LihCostLineIn, request: Request, db: Db, user: Current,
) -> LihCostDayOut:
    return service.update_line(db, user.organization_id, entry_id, line_id, data, user, request)


@router.delete(
    "/entries/{entry_id}/lines/{line_id}", response_model=LihCostDayOut,
    dependencies=[Depends(require("daily-cost:delete"))],
)
def delete_line(entry_id: str, line_id: str, request: Request, db: Db, user: Current) -> LihCostDayOut:
    return service.delete_line(db, user.organization_id, entry_id, line_id, user, request)


@router.post(
    "/entries/{entry_id}/lines/bulk-delete", response_model=LihCostDayOut,
    dependencies=[Depends(require("daily-cost:delete"))],
)
def bulk_delete_lines(
    entry_id: str, data: LihCostLineIDs, request: Request, db: Db, user: Current,
) -> LihCostDayOut:
    """Remove several items from one day in a single call."""
    return service.delete_lines(db, user.organization_id, entry_id, data.line_ids, user, request)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: LihCostExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(db, user, data, request)
    return Response(status_code=204)
