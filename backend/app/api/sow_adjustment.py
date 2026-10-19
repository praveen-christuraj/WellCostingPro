"""Tenant-scoped AFE SOW adjustments and well plan adjustments.

Adjustments are recorded separately from the approved AFE estimates and the
configured well plans they revise. Only the latest *approved* revision per
AFE (or per well and scope) affects cost comparisons; drafts and voided
revisions are visible history only.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import Current, Db, require
from app.schemas.sow_adjustment import (
    AfeSowAdjustmentCreate,
    AfeSowAdjustmentOut,
    AfeSowAdjustmentUpdate,
    DailyCostAmendmentOut,
    SowApprovalIn,
    WellAdjustedSummary,
    WellPlanAdjustmentCreate,
    WellPlanAdjustmentOut,
    WellPlanAdjustmentUpdate,
)
from app.services import sow_adjustment as service

router = APIRouter(tags=["SOW Adjustments"])


# ---------------------------------------------------------------------------
# AFE SOW adjustments
# ---------------------------------------------------------------------------


@router.get(
    "/afe/afes/{afe_id}/sow-adjustments",
    response_model=list[AfeSowAdjustmentOut],
    dependencies=[Depends(require("afe:read"))],
)
def list_afe_adjustments(afe_id: str, db: Db, user: Current) -> list[AfeSowAdjustmentOut]:
    return service.list_afe_adjustments(db, user.organization_id, afe_id)


@router.post(
    "/afe/afes/{afe_id}/sow-adjustments",
    response_model=AfeSowAdjustmentOut,
    status_code=201,
    dependencies=[Depends(require("afe:sow-adjust"))],
)
def create_afe_adjustment(
    afe_id: str, data: AfeSowAdjustmentCreate, request: Request, db: Db, user: Current
) -> AfeSowAdjustmentOut:
    return service.create_afe_adjustment(db, user.organization_id, afe_id, data, user, request)


@router.patch(
    "/afe/sow-adjustments/{adjustment_id}",
    response_model=AfeSowAdjustmentOut,
    dependencies=[Depends(require("afe:sow-adjust"))],
)
def update_afe_adjustment(
    adjustment_id: str, data: AfeSowAdjustmentUpdate, request: Request, db: Db, user: Current
) -> AfeSowAdjustmentOut:
    return service.update_afe_adjustment(db, user.organization_id, adjustment_id, data, user, request)


@router.post(
    "/afe/sow-adjustments/{adjustment_id}/approve",
    response_model=AfeSowAdjustmentOut,
    dependencies=[Depends(require("afe:sow-approve"))],
)
def approve_afe_adjustment(
    adjustment_id: str, data: SowApprovalIn, request: Request, db: Db, user: Current
) -> AfeSowAdjustmentOut:
    return service.approve_afe_adjustment(db, user.organization_id, adjustment_id, user, request, data.remarks)


@router.post(
    "/afe/sow-adjustments/{adjustment_id}/void",
    response_model=AfeSowAdjustmentOut,
    dependencies=[Depends(require("afe:sow-approve"))],
)
def void_afe_adjustment(
    adjustment_id: str, data: SowApprovalIn, request: Request, db: Db, user: Current
) -> AfeSowAdjustmentOut:
    return service.void_afe_adjustment(db, user.organization_id, adjustment_id, user, request, data.remarks)


# ---------------------------------------------------------------------------
# Well plan adjustments
# ---------------------------------------------------------------------------


@router.get(
    "/rig-well/wells/{well_id}/plan-adjustments",
    response_model=list[WellPlanAdjustmentOut],
    dependencies=[Depends(require("rig-well:read"))],
)
def list_well_plan_adjustments(
    well_id: str,
    db: Db,
    user: Current,
    scope: Literal["drilling", "completion"] | None = Query(default=None),
) -> list[WellPlanAdjustmentOut]:
    return service.list_well_plan_adjustments(db, user.organization_id, well_id, scope)


@router.post(
    "/rig-well/wells/{well_id}/plan-adjustments",
    response_model=WellPlanAdjustmentOut,
    status_code=201,
    dependencies=[Depends(require("rig-well:plan-adjust"))],
)
def create_well_plan_adjustment(
    well_id: str, data: WellPlanAdjustmentCreate, request: Request, db: Db, user: Current
) -> WellPlanAdjustmentOut:
    return service.create_well_plan_adjustment(db, user.organization_id, well_id, data, user, request)


@router.patch(
    "/rig-well/plan-adjustments/{adjustment_id}",
    response_model=WellPlanAdjustmentOut,
    dependencies=[Depends(require("rig-well:plan-adjust"))],
)
def update_well_plan_adjustment(
    adjustment_id: str, data: WellPlanAdjustmentUpdate, request: Request, db: Db, user: Current
) -> WellPlanAdjustmentOut:
    return service.update_well_plan_adjustment(db, user.organization_id, adjustment_id, data, user, request)


@router.post(
    "/rig-well/plan-adjustments/{adjustment_id}/approve",
    response_model=WellPlanAdjustmentOut,
    dependencies=[Depends(require("rig-well:plan-adjust"))],
)
def approve_well_plan_adjustment(
    adjustment_id: str, data: SowApprovalIn, request: Request, db: Db, user: Current
) -> WellPlanAdjustmentOut:
    return service.approve_well_plan_adjustment(db, user.organization_id, adjustment_id, user, request, data.remarks)


@router.post(
    "/rig-well/plan-adjustments/{adjustment_id}/void",
    response_model=WellPlanAdjustmentOut,
    dependencies=[Depends(require("rig-well:plan-adjust"))],
)
def void_well_plan_adjustment(
    adjustment_id: str, data: SowApprovalIn, request: Request, db: Db, user: Current
) -> WellPlanAdjustmentOut:
    return service.void_well_plan_adjustment(db, user.organization_id, adjustment_id, user, request, data.remarks)


@router.get(
    "/rig-well/wells/{well_id}/adjusted-summary",
    response_model=WellAdjustedSummary,
    dependencies=[Depends(require("rig-well:read"))],
)
def well_adjusted_summary(
    well_id: str,
    db: Db,
    user: Current,
    scope: Literal["drilling", "completion"] = Query(default="drilling"),
) -> WellAdjustedSummary:
    return service.well_adjusted_summary(db, user.organization_id, well_id, scope)


# ---------------------------------------------------------------------------
# Daily cost amendments (late reopens listed separately from the audit trail)
# ---------------------------------------------------------------------------


@router.get(
    "/daily-cost/entries/{entry_id}/amendments",
    response_model=list[DailyCostAmendmentOut],
    dependencies=[Depends(require("daily-cost:read"))],
)
def list_amendments(entry_id: str, db: Db, user: Current) -> list[DailyCostAmendmentOut]:
    return service.list_amendments(db, user.organization_id, entry_id)
