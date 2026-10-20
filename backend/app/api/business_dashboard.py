"""Business Dashboard endpoints.

One read-only page for the whole costing workflow. Access is the union of the
source modules (``rig-well:read``, ``afe:read``, ``daily-cost:read``), and the
response carries capability flags so each section is only rendered when its
own permission is granted. The API never returns AFE or actual cost figures to
a caller without that module's read permission.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import Current, Db
from app.schemas.business_dashboard import (
    BusinessDashboardOut,
    DashboardExportAudit,
    DashboardWellDetail,
)
from app.services import business_dashboard as service

router = APIRouter(prefix="/dashboard/business", tags=["Business Dashboard"])


def _dashboard_user(user: Current) -> None:
    """The dashboard itself is open to any source-module reader."""
    if not service.access_allowed(user):
        raise HTTPException(
            status_code=403,
            detail="The business dashboard requires read access to rigs and wells, AFEs or daily costs",
        )
    return user


@router.get("", response_model=BusinessDashboardOut)
def dashboard(
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    rig_id: str = Query(default="", max_length=36),
    well_id: str = Query(default="", max_length=36),
    afe_id: str = Query(default="", max_length=36),
    afe_type: str = Query(default="", max_length=20),
    well_status: str = Query(default="", max_length=20),
    currency: str = Query(default="", max_length=10),
    include_draft: bool = Query(default=True),
) -> BusinessDashboardOut:
    """KPIs, charts, tables and alerts for the filtered wells.

    The date range applies to the cost register (actuals, actual days, NPT/UPA
    and the trend). Planned days and AFE amounts are plan-level figures and are
    not date-bound, which the response repeats in its alerts.
    """
    _dashboard_user(user)
    return service.dashboard(
        db, user.organization_id, user,
        date_from=date_from, date_to=date_to, rig_id=rig_id, well_id=well_id, afe_id=afe_id,
        afe_type=afe_type, well_status=well_status, currency=currency, include_draft=include_draft,
    )


@router.get("/wells/{well_id}", response_model=DashboardWellDetail)
def well_detail(
    well_id: str,
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    currency: str = Query(default="", max_length=10),
    include_draft: bool = Query(default=True),
) -> DashboardWellDetail:
    """Drill-through: one well's AFEs, daily trend, activities and sections."""
    _dashboard_user(user)
    return service.well_detail(
        db, user.organization_id, user, well_id,
        date_from=date_from, date_to=date_to, currency=currency, include_draft=include_draft,
    )


@router.post("/export-audit", status_code=204)
def export_audit(
    data: DashboardExportAudit, request: Request, db: Db, user: Current,
) -> None:
    """Audit a CSV/XLSX/PDF download of the dashboard tables.

    Exports are built in the browser from the rows already on screen; this
    records who exported what, like every other module's export audit.
    """
    _dashboard_user(user)
    service.record_export(
        db, user, fmt=data.format, record_count=data.record_count, request=request,
    )
