"""Typed API contract for the cross-module Business Dashboard.

The dashboard is a read-only projection of the Rig & Well, AFE and Daily Cost
modules. Every figure keeps its own currency: amounts are only summed when the
AFE standard currency (or the daily sheet standard currency) matches the
currency selected on the dashboard, and the response reports what was left out.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class DashboardCapabilities(BaseModel):
    """Which module sections the caller may read.

    The API is the authorization authority: a section that is not permitted is
    returned empty/null instead of being merely hidden in the interface.
    """

    plan: bool          # rig-well:read — rig/well details, planned days, configuration, depth
    budget: bool        # afe:read — AFE amount, SOW adjusted amount, AFE positions
    actuals: bool       # daily-cost:read — actual amount, actual days, NPT/UPA, cost trends


class DashboardRigOption(BaseModel):
    id: str
    code: str
    name: str


class DashboardWellOption(BaseModel):
    id: str
    code: str
    name: str
    rig_id: str
    rig_code: str
    status: str


class DashboardAfeOption(BaseModel):
    id: str
    code: str
    name: str
    well_id: str
    rig_id: str
    afe_type: str
    status: str
    currency: str


class DashboardFilterOptions(BaseModel):
    """Unfiltered workspace options, so the filter bar never loses its choices."""

    rigs: list[DashboardRigOption]
    wells: list[DashboardWellOption]
    afes: list[DashboardAfeOption]
    currencies: list[str]
    default_currency: str
    afe_types: list[str]


class DashboardKpis(BaseModel):
    # Scope
    rigs: int | None = None
    wells: int | None = None
    active_wells: int | None = None
    completed_wells: int | None = None
    configured_wells: int | None = None
    draft_wells: int | None = None
    afes: int | None = None
    wells_with_actuals: int | None = None
    # Days
    planned_days: Decimal | None = None
    actual_days: int | None = None
    recorded_days: int | None = None
    npt_days: int | None = None
    upa_days: int | None = None
    day_variance: Decimal | None = None
    # Money, all in `currency`
    afe_amount: Decimal | None = None
    sow_adjusted_amount: Decimal | None = None
    effective_afe_amount: Decimal | None = None
    actual_amount: Decimal | None = None
    afe_balance: Decimal | None = None
    utilisation_percent: Decimal | None = None
    npt_amount: Decimal | None = None
    upa_amount: Decimal | None = None
    other_expenses_amount: Decimal | None = None
    # Depth
    planned_depth: Decimal | None = None
    actual_depth: Decimal | None = None
    depth_progress_percent: Decimal | None = None
    depth_unit: str = ""
    # Exceptions
    over_budget_wells: int = 0
    over_budget_afes: int = 0
    conversion_pending_afes: int = 0


class DashboardWellRow(BaseModel):
    well_id: str
    well_code: str
    well_name: str
    well_location: str = ""
    block: str = ""
    status: str = ""
    config_status: str = ""
    depth_unit: str = ""
    rig_id: str
    rig_code: str
    rig_name: str
    # Plan (Well Configuration), drilling and configured completion kept apart
    drilling_planned_days: Decimal | None = None
    completion_planned_days: Decimal | None = None
    planned_days: Decimal | None = None
    drilling_plan_adjusted: bool = False
    completion_plan_adjusted: bool = False
    section_count: int | None = None
    planned_depth: Decimal | None = None
    actual_depth: Decimal | None = None
    depth_progress_percent: Decimal | None = None
    # Budget (AFE)
    afe_count: int | None = None
    drilling_afe_count: int | None = None
    completion_afe_count: int | None = None
    afe_amount: Decimal | None = None
    sow_adjusted_amount: Decimal | None = None
    has_sow_adjustment: bool = False
    effective_afe_amount: Decimal | None = None
    afe_balance: Decimal | None = None
    utilisation_percent: Decimal | None = None
    over_budget: bool = False
    # Actuals (Daily Cost register)
    actual_amount: Decimal | None = None
    services_amount: Decimal | None = None
    consumables_amount: Decimal | None = None
    tangibles_amount: Decimal | None = None
    other_expenses_amount: Decimal | None = None
    npt_amount: Decimal | None = None
    upa_amount: Decimal | None = None
    first_cost_date: date | None = None
    last_cost_date: date | None = None
    actual_days: int | None = None
    recorded_days: int | None = None
    sheets: int | None = None
    draft_sheets: int | None = None
    npt_days: int | None = None
    upa_days: int | None = None
    currency: str = ""


class DashboardAfeRow(BaseModel):
    afe_id: str
    afe_code: str
    afe_name: str
    afe_type: str
    configuration_scope: str
    status: str
    well_id: str
    well_code: str
    well_name: str
    rig_id: str
    rig_code: str
    rig_name: str
    currency: str = ""
    afe_amount: Decimal | None = None
    sow_adjusted_amount: Decimal | None = None
    has_sow_adjustment: bool = False
    sow_revision: int | None = None
    effective_afe_amount: Decimal | None = None
    actual_amount: Decimal | None = None
    afe_balance: Decimal | None = None
    utilisation_percent: Decimal | None = None
    over_budget: bool = False
    conversion_pending: bool = False
    first_cost_date: date | None = None
    last_cost_date: date | None = None
    actual_days: int | None = None
    recorded_days: int | None = None
    sheets: int | None = None
    npt_days: int | None = None
    upa_days: int | None = None
    npt_amount: Decimal | None = None
    upa_amount: Decimal | None = None


class DashboardRigRow(BaseModel):
    rig_id: str
    rig_code: str
    rig_name: str
    wells: int
    active_wells: int = 0
    completed_wells: int = 0
    planned_days: Decimal | None = None
    actual_days: int | None = None
    recorded_days: int | None = None
    npt_days: int | None = None
    upa_days: int | None = None
    afe_amount: Decimal | None = None
    effective_afe_amount: Decimal | None = None
    actual_amount: Decimal | None = None
    afe_balance: Decimal | None = None
    planned_depth: Decimal | None = None
    actual_depth: Decimal | None = None
    draft_sheets: int | None = None


class DashboardDailyPoint(BaseModel):
    cost_date: date
    actual: Decimal
    cumulative: Decimal
    npt: Decimal = Decimal("0")
    upa: Decimal = Decimal("0")
    sheets: int = 0


class DashboardSlice(BaseModel):
    """One cut of the ledger (cost group, Planned/UPA/NPT, status, …)."""

    key: str
    label: str
    count: int | None = None
    days: int | None = None
    planned: Decimal | None = None
    actual: Decimal | None = None
    balance: Decimal | None = None
    share: Decimal | None = None


class DashboardSectionRow(BaseModel):
    hole_section_id: str | None = None
    section_code: str
    section_name: str
    scope: str = "drilling"
    from_depth: Decimal | None = None
    to_depth: Decimal | None = None
    planned_days: Decimal | None = None
    active_days: int | None = None
    amount: Decimal | None = None
    share: Decimal | None = None
    reached: bool = False
    planned_phase_count: int | None = None


class DashboardActivityRow(BaseModel):
    activity_id: str | None = None
    activity_code: str
    activity_name: str
    classification: str = "Planned"
    active_days: int | None = None
    amount: Decimal | None = None
    share: Decimal | None = None
    sub_activity_count: int | None = None


class DashboardAlert(BaseModel):
    kind: str
    severity: Literal["info", "warning", "error"]
    title: str
    detail: str
    well_id: str | None = None


class DashboardDaySheet(BaseModel):
    """One daily cost sheet behind a point on the trend, so the panel can open it."""

    entry_id: str
    cost_date: date
    afe_code: str = ""
    status: str
    total: Decimal = Decimal("0")
    npt: Decimal = Decimal("0")
    upa: Decimal = Decimal("0")
    warning_count: int = 0


class DashboardWellDetail(BaseModel):
    well: DashboardWellRow
    afes: list[DashboardAfeRow]
    daily: list[DashboardDailyPoint]
    sheets: list[DashboardDaySheet] = []
    classification: list[DashboardSlice]
    cost_groups: list[DashboardSlice]
    activities: list[DashboardActivityRow]
    sections: list[DashboardSectionRow]
    notes: list[str]


class DashboardExportAudit(BaseModel):
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = 0


class BusinessDashboardOut(BaseModel):
    generated_at: datetime
    date_from: date | None = None
    date_to: date | None = None
    include_draft: bool = True
    currency: str = ""
    available_currencies: list[str] = []
    default_currency: str = ""
    capabilities: DashboardCapabilities
    filters: DashboardFilterOptions
    kpis: DashboardKpis
    alerts: list[DashboardAlert] = []
    well_statuses: list[DashboardSlice] = []
    afe_statuses: list[DashboardSlice] = []
    cost_groups: list[DashboardSlice] = []
    classification: list[DashboardSlice] = []
    daily: list[DashboardDailyPoint] = []
    rigs: list[DashboardRigRow] = []
    wells: list[DashboardWellRow] = []
    afes: list[DashboardAfeRow] = []
    excluded_afe_count: int = 0
    excluded_entry_count: int = 0
    conversion_pending_afes: int = 0
