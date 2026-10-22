"""Tenant-scoped Fuel Cost Register endpoints (Daily Cost Management).

The register is rig-scoped and manual. Capabilities come from the existing
``daily-cost:*`` set; overriding a day's opening stock needs the separately
grantable ``daily-cost:fuel-opening-stock`` capability because it breaks the
physical carry-forward chain.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import Current, Db, granted, owner, require
from app.models.entities import User
from app.schemas.fuel_cost import (
    FuelCompanyCategoryIn,
    FuelCompanyCategoryUpdate,
    FuelCompanyIn,
    FuelCompanyOut,
    FuelCompanyUpdate,
    FuelCostBulkActionOut,
    FuelCostCompanyConsumptionOut,
    FuelCostDayOut,
    FuelCostEntryOut,
    FuelCostEntrySave,
    FuelCostExportAudit,
    FuelCostIDs,
    FuelCostImportRequest,
    FuelCostImportResponse,
    FuelCostOpeningStockUpdate,
    FuelCostReference,
)
from app.services import fuel_cost as service

router = APIRouter(prefix="/fuel-cost", tags=["Fuel Cost Register"])

OPENING_STOCK_CAPABILITY = "daily-cost:fuel-opening-stock"


def _can_override_opening(user: User) -> bool:
    return owner(user) or OPENING_STOCK_CAPABILITY in granted(user)


# ---------------------------------------------------------------------------
# Reference data and the register
# ---------------------------------------------------------------------------


@router.get("/reference", response_model=FuelCostReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current) -> FuelCostReference:
    return service.reference_data(db, user.organization_id)


@router.get("/day", response_model=FuelCostDayOut, dependencies=[Depends(require("daily-cost:read"))])
def day_for_date(
    db: Db,
    user: Current,
    rig_id: str = Query(min_length=1, max_length=36),
    cost_date: date = Query(alias="date"),
) -> FuelCostDayOut:
    """One rig day, existing or previewed before the first save."""
    return service.day_for_rig_date(db, user.organization_id, rig_id, cost_date)


@router.get(
    "/rigs/{rig_id}/company-consumption",
    response_model=FuelCostCompanyConsumptionOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def company_consumption(
    rig_id: str,
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> FuelCostCompanyConsumptionOut:
    """Company and category AGO consumption for one rig over a date range."""
    return service.company_consumption(
        db, user.organization_id, rig_id, date_from=date_from, date_to=date_to
    )


@router.get(
    "/entries/deleted",
    response_model=list[FuelCostEntryOut],
    dependencies=[Depends(require("daily-cost:read"))],
)
def deleted_entries(
    db: Db,
    user: Current,
    rig_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[FuelCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, rig_id=rig_id, date_from=date_from, date_to=date_to, deleted=True
    )


@router.get("/entries", response_model=list[FuelCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def list_entries(
    db: Db,
    user: Current,
    rig_id: str = Query(default="", max_length=36),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[FuelCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, rig_id=rig_id, date_from=date_from, date_to=date_to
    )


@router.post("/entries", response_model=FuelCostDayOut, status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def create_entry(data: FuelCostEntrySave, request: Request, db: Db, user: Current) -> FuelCostDayOut:
    return service.save_entry(
        db,
        user.organization_id,
        data,
        user,
        request,
        can_override_opening=_can_override_opening(user),
    )


@router.put("/entries/{entry_id}", response_model=FuelCostDayOut)
def update_entry(
    entry_id: str, data: FuelCostEntrySave, request: Request, db: Db, user: Current
) -> FuelCostDayOut:
    """Replace one rig day. Saving needs ``daily-cost:update``."""
    if not owner(user) and "daily-cost:update" not in granted(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return service.save_entry(
        db,
        user.organization_id,
        data,
        user,
        request,
        entry_id=entry_id,
        can_override_opening=_can_override_opening(user),
    )


@router.post(
    "/entries/{entry_id}/opening-stock",
    response_model=FuelCostDayOut,
    dependencies=[Depends(require(OPENING_STOCK_CAPABILITY))],
)
def override_opening_stock(
    entry_id: str, data: FuelCostOpeningStockUpdate, request: Request, db: Db, user: Current
) -> FuelCostDayOut:
    """Override, correct or clear a day's opening stock (audited)."""
    return service.set_opening_stock(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/bulk-delete", response_model=FuelCostBulkActionOut, dependencies=[Depends(require("daily-cost:delete"))])
def bulk_delete(data: FuelCostIDs, request: Request, db: Db, user: Current) -> FuelCostBulkActionOut:
    return service.soft_delete_entries(db, user.organization_id, data.ids, user, request)


@router.post("/entries/bulk-restore", response_model=FuelCostBulkActionOut, dependencies=[Depends(require("daily-cost:restore"))])
def bulk_restore(data: FuelCostIDs, request: Request, db: Db, user: Current) -> FuelCostBulkActionOut:
    return service.restore_entries(db, user.organization_id, data.ids, user, request)


@router.post(
    "/entries/bulk-permanent-delete",
    response_model=FuelCostBulkActionOut,
    dependencies=[Depends(require("daily-cost:permanent-delete"))],
)
def bulk_permanent_delete(data: FuelCostIDs, request: Request, db: Db, user: Current) -> FuelCostBulkActionOut:
    return service.permanently_delete_entries(db, user.organization_id, data.ids, user, request)


@router.delete("/entries/{entry_id}", response_model=FuelCostBulkActionOut, dependencies=[Depends(require("daily-cost:delete"))])
def delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> FuelCostBulkActionOut:
    return service.soft_delete_entries(db, user.organization_id, [entry_id], user, request)


@router.post(
    "/entries/{entry_id}/restore",
    response_model=FuelCostBulkActionOut,
    dependencies=[Depends(require("daily-cost:restore"))],
)
def restore_entry(entry_id: str, request: Request, db: Db, user: Current) -> FuelCostBulkActionOut:
    return service.restore_entries(db, user.organization_id, [entry_id], user, request)


@router.delete(
    "/entries/{entry_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("daily-cost:permanent-delete"))],
)
def permanently_delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> Response:
    service.permanently_delete_entries(db, user.organization_id, [entry_id], user, request)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Companies and categories (the daily entry set)
# ---------------------------------------------------------------------------


@router.get(
    "/companies/deleted", response_model=list[FuelCompanyOut],
    dependencies=[Depends(require("daily-cost:read"))],
)
def deleted_companies(db: Db, user: Current) -> list[FuelCompanyOut]:
    return service.list_companies(db, user.organization_id, deleted=True)


@router.get("/companies", response_model=list[FuelCompanyOut], dependencies=[Depends(require("daily-cost:read"))])
def list_companies(db: Db, user: Current) -> list[FuelCompanyOut]:
    return service.list_companies(db, user.organization_id)


@router.post("/companies", response_model=FuelCompanyOut, status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def create_company(data: FuelCompanyIn, request: Request, db: Db, user: Current) -> FuelCompanyOut:
    return service.create_company(db, user.organization_id, data, user, request)


@router.put("/companies/{company_id}", response_model=FuelCompanyOut, dependencies=[Depends(require("daily-cost:update"))])
def update_company(
    company_id: str, data: FuelCompanyUpdate, request: Request, db: Db, user: Current
) -> FuelCompanyOut:
    return service.update_company(db, user.organization_id, company_id, data, user, request)


@router.delete("/companies/{company_id}", response_model=FuelCompanyOut, dependencies=[Depends(require("daily-cost:delete"))])
def delete_company(company_id: str, request: Request, db: Db, user: Current) -> FuelCompanyOut:
    return service.delete_company(db, user.organization_id, company_id, user, request)


@router.post(
    "/companies/{company_id}/restore", response_model=FuelCompanyOut,
    dependencies=[Depends(require("daily-cost:restore"))],
)
def restore_company(company_id: str, request: Request, db: Db, user: Current) -> FuelCompanyOut:
    return service.restore_company(db, user.organization_id, company_id, user, request)


@router.post(
    "/companies/{company_id}/categories", response_model=FuelCompanyOut, status_code=201,
    dependencies=[Depends(require("daily-cost:create"))],
)
def create_category(
    company_id: str, data: FuelCompanyCategoryIn, request: Request, db: Db, user: Current
) -> FuelCompanyOut:
    return service.create_category(db, user.organization_id, company_id, data, user, request)


@router.put(
    "/categories/{category_id}", response_model=FuelCompanyOut,
    dependencies=[Depends(require("daily-cost:update"))],
)
def update_category(
    category_id: str, data: FuelCompanyCategoryUpdate, request: Request, db: Db, user: Current
) -> FuelCompanyOut:
    return service.update_category(db, user.organization_id, category_id, data, user, request)


@router.delete(
    "/categories/{category_id}", response_model=FuelCompanyOut,
    dependencies=[Depends(require("daily-cost:delete"))],
)
def delete_category(category_id: str, request: Request, db: Db, user: Current) -> FuelCompanyOut:
    return service.delete_category(db, user.organization_id, category_id, user, request)


@router.post(
    "/categories/{category_id}/restore", response_model=FuelCompanyOut,
    dependencies=[Depends(require("daily-cost:restore"))],
)
def restore_category(category_id: str, request: Request, db: Db, user: Current) -> FuelCompanyOut:
    return service.restore_category(db, user.organization_id, category_id, user, request)


# ---------------------------------------------------------------------------
# Import and export auditing
# ---------------------------------------------------------------------------


@router.post("/import", response_model=FuelCostImportResponse, dependencies=[Depends(require("daily-cost:import"))])
def import_rows(
    data: FuelCostImportRequest, request: Request, db: Db, user: Current
) -> FuelCostImportResponse:
    """Import fuel days and company consumption rows from a spreadsheet."""
    return service.import_rows(db, user.organization_id, data, user, request)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: FuelCostExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(db, user, data, request)
    return Response(status_code=204)
