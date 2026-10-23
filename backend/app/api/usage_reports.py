"""Reports module: usage and cost matrix reports.

All endpoints are read-only projections of the Daily Cost ledger and reuse the
daily-cost capabilities: ``daily-cost:read`` for viewing, ``daily-cost:export``
for the export audit trail. No separate permission key is introduced.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import Current, Db, require
from app.schemas.usage_reports import (
    NptUpaReportOut,
    UsageMatrixOut,
    UsageReference,
    UsageReportExportAudit,
)
from app.services import usage_reports as service

router = APIRouter(prefix="/usage-reports", tags=["Usage Reports"])

_MATRIX_REPORTS = ("mud-chemicals", "drill-bits", "tangibles", "services", "vendors")


def _common_filters(
    block_id: str,
    rig_id: str,
    well_id: list[str],
    scope: str,
    lifecycle: str,
    currency: str,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
) -> dict:
    return {
        "block_id": block_id,
        "rig_id": rig_id,
        "well_ids": well_id,
        "scope": scope,
        "lifecycle": lifecycle,
        "currency": currency,
        "date_from": date_from,
        "date_to": date_to,
        "include_draft": include_draft,
    }


@router.get("/reference", response_model=UsageReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current) -> UsageReference:
    return service.reference_data(db, user.organization_id)


@router.get(
    "/matrix/{report}",
    response_model=UsageMatrixOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def matrix(
    report: str,
    db: Db,
    user: Current,
    block_id: str = Query(default="", max_length=36),
    rig_id: str = Query(default="", max_length=36),
    well_id: list[str] = Query(default=[]),
    scope: str = Query(default="", pattern="^(drilling|completion)?$"),
    lifecycle: str = Query(default="", pattern="^(active|final_review|completed)?$"),
    currency: str = Query(default="", max_length=10),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_draft: bool = Query(default=True),
) -> UsageMatrixOut:
    if report not in _MATRIX_REPORTS:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Unknown report '{report}'")
    return service.matrix_report(
        db, user.organization_id, report,
        **_common_filters(
            block_id, rig_id, well_id, scope, lifecycle, currency,
            date_from, date_to, include_draft,
        ),
    )


@router.get(
    "/npt-upa",
    response_model=NptUpaReportOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def npt_upa(
    db: Db,
    user: Current,
    block_id: str = Query(default="", max_length=36),
    rig_id: str = Query(default="", max_length=36),
    well_id: list[str] = Query(default=[]),
    scope: str = Query(default="", pattern="^(drilling|completion)?$"),
    lifecycle: str = Query(default="", pattern="^(active|final_review|completed)?$"),
    currency: str = Query(default="", max_length=10),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_draft: bool = Query(default=True),
) -> NptUpaReportOut:
    return service.npt_upa_report(
        db, user.organization_id,
        **_common_filters(
            block_id, rig_id, well_id, scope, lifecycle, currency,
            date_from, date_to, include_draft,
        ),
    )


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: UsageReportExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(db, user, data, request)
    return Response(status_code=204)
