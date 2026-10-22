"""Retention rules shared by the Deleted Entries purge flows.

Daily-cost baselines are immutable audit snapshots, but they *belong to* the
record they snapshot: an AFE baseline exists only to price that AFE's daily
sheets, and a well rate baseline exists only to price that well's sheets. The
same is true of the AFE's SOW revision history and the well's plan revisions.
They are retained exactly as long as their owner is retained. Once the owning
AFE or well is permanently deleted - after the sheets that price from those
snapshots are gone - the snapshots are purged with it.

That ownership rule keeps the audit trail honest without turning the snapshots
into tombstones: a record could otherwise never be purged after its last sheet
was purged, because the orphaned baseline kept failing the foreign key.

This module also gives the Rig & Well and AFE purge endpoints one metadata
driven safety net. Every RESTRICT reference to the record being purged is
counted up front, so a user always receives an actionable 409 naming the module
that still holds the record instead of an opaque integrity error (HTTP 500).
"""

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.daily_cost import DailyCostBaseline, DailyCostEntry, DailyCostWellRateBaseline
from app.models.mud_cost import MudCostSectionSetting
from app.models.sow_adjustment import AfeSowAdjustment, WellPlanAdjustment
from app.services.dependencies import REFERENCE_LABELS, dependency_counts

# Tables whose rows are owned by the AFE/well being purged. They are retained
# with their owner and removed by the purge, so they must not block it. Labels
# are read from the single reference-label map instead of being re-typed here.
OWNED_SNAPSHOT_TABLES = (
    "daily_cost_baselines",
    "daily_cost_well_rate_baselines",
    "daily_cost_catalogue_rate_snapshots",
    "afe_sow_adjustments",
    "well_plan_adjustments",
    "mud_cost_section_settings",
)
OWNED_SNAPSHOT_LABELS = tuple(REFERENCE_LABELS[table] for table in OWNED_SNAPSHOT_TABLES)

# Convenience labels for callers that purge child records in the same transaction.
WELL_LABEL = REFERENCE_LABELS["wells"]
AFE_LABEL = REFERENCE_LABELS["afes"]
SUB_ACTIVITY_LABEL = REFERENCE_LABELS["well_sub_activities"]
DAILY_SHEET_LABEL = REFERENCE_LABELS["daily_cost_entries"]
MUD_COST_LABEL = REFERENCE_LABELS["mud_cost_entries"]


def _counts_by(
    db: Session,
    model: Any,
    parent_column: Any,
    organization_id: str,
    parent_ids: Iterable[str],
    *,
    active_only: bool = False,
) -> dict[str, int]:
    """Rows per parent id, optionally limited to records not in Deleted Entries."""

    ids = list(dict.fromkeys(parent_ids))
    if not ids:
        return {}
    statement = select(parent_column, func.count(model.id)).where(
        model.organization_id == organization_id,
        parent_column.in_(ids),
    )
    if active_only:
        statement = statement.where(model.is_deleted.is_(False))
    return {str(parent_id): int(count) for parent_id, count in db.execute(statement.group_by(parent_column)).all()}


def daily_sheet_counts_by_afe(
    db: Session, organization_id: str, afe_ids: Iterable[str], *, active_only: bool = False
) -> dict[str, int]:
    return _counts_by(db, DailyCostEntry, DailyCostEntry.afe_id, organization_id, afe_ids, active_only=active_only)


def purge_owned_snapshots(
    db: Session,
    organization_id: str,
    *,
    afe_ids: Iterable[str] = (),
    well_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Delete the immutable snapshots owned by the AFEs/wells being purged.

    AFE baselines are removed before well rate baselines so the RESTRICT
    reference between them is never left dangling, and AFE SOW revisions are
    removed before the well they belong to. Callers must first confirm that
    every daily sheet pricing from these snapshots has been purged.

    Returns the number of rows removed per snapshot kind, for the audit summary.
    """

    afe_id_list = list(dict.fromkeys(afe_ids))
    well_id_list = list(dict.fromkeys(well_ids))
    removed = {
        "afe_baseline": 0,
        "rate_baseline": 0,
        "sow_adjustment": 0,
        "plan_adjustment": 0,
        "mud_setting": 0,
    }

    sow_revisions: dict[str, AfeSowAdjustment] = {}
    if afe_id_list:
        for row in db.scalars(
            select(AfeSowAdjustment).where(
                AfeSowAdjustment.organization_id == organization_id,
                AfeSowAdjustment.afe_id.in_(afe_id_list),
            )
        ).all():
            sow_revisions[row.id] = row
    if well_id_list:
        for row in db.scalars(
            select(AfeSowAdjustment).where(
                AfeSowAdjustment.organization_id == organization_id,
                AfeSowAdjustment.well_id.in_(well_id_list),
            )
        ).all():
            sow_revisions[row.id] = row
        for row in db.scalars(
            select(WellPlanAdjustment).where(
                WellPlanAdjustment.organization_id == organization_id,
                WellPlanAdjustment.well_id.in_(well_id_list),
            )
        ).all():
            db.delete(row)
            removed["plan_adjustment"] += 1
        # Per-well mud section settings are configuration for the well, like its
        # sections and phases; the well cannot exist without them, so they are
        # removed with it once its Mud Cost entries have been purged.
        for row in db.scalars(
            select(MudCostSectionSetting).where(
                MudCostSectionSetting.organization_id == organization_id,
                MudCostSectionSetting.well_id.in_(well_id_list),
            )
        ).all():
            db.delete(row)
            removed["mud_setting"] += 1
    for row in sow_revisions.values():
        db.delete(row)
        removed["sow_adjustment"] += 1
    if removed["sow_adjustment"] or removed["plan_adjustment"] or removed["mud_setting"]:
        db.flush()

    afe_baselines: dict[str, DailyCostBaseline] = {}
    if afe_id_list or well_id_list:
        conditions = []
        if afe_id_list:
            conditions.append(DailyCostBaseline.afe_id.in_(afe_id_list))
        if well_id_list:
            conditions.append(DailyCostBaseline.well_id.in_(well_id_list))
        rows = db.scalars(
            select(DailyCostBaseline).where(
                DailyCostBaseline.organization_id == organization_id,
                *conditions,
            )
        ).all()
        afe_baselines = {baseline.id: baseline for baseline in rows}
    for baseline in afe_baselines.values():
        db.delete(baseline)
        removed["afe_baseline"] += 1
    if afe_baselines:
        db.flush()

    if well_id_list:
        rate_baselines = list(
            db.scalars(
                select(DailyCostWellRateBaseline).where(
                    DailyCostWellRateBaseline.organization_id == organization_id,
                    DailyCostWellRateBaseline.well_id.in_(well_id_list),
                )
            ).all()
        )
        for baseline in rate_baselines:
            db.delete(baseline)
            removed["rate_baseline"] += 1
        if rate_baselines:
            db.flush()
    return removed


def snapshot_summary(removed: dict[str, int]) -> str:
    """Human summary of purged snapshots, used in audit rows."""

    parts = []
    if removed.get("afe_baseline"):
        parts.append(f"{removed['afe_baseline']} locked AFE baseline(s)")
    if removed.get("rate_baseline"):
        parts.append(f"{removed['rate_baseline']} well rate baseline(s)")
    if removed.get("sow_adjustment"):
        parts.append(f"{removed['sow_adjustment']} SOW revision(s)")
    if removed.get("plan_adjustment"):
        parts.append(f"{removed['plan_adjustment']} well plan revision(s)")
    if removed.get("mud_setting"):
        parts.append(f"{removed['mud_setting']} Mud Cost section setting(s)")
    return ", ".join(parts)


def retained_references(
    db: Session, organization_id: str, record: Any, *, ignore: Iterable[str] = ()
) -> dict[str, int]:
    """Blocking references to ``record``, excluding the snapshots the purge owns.

    ``ignore`` names references that the caller is purging in the same
    transaction (for example the sub activities selected alongside their well).
    """

    counts = dependency_counts(db, record, organization_id)
    for label in (*OWNED_SNAPSHOT_LABELS, *ignore):
        counts.pop(label, None)
    return counts


def assert_purgeable(
    db: Session,
    organization_id: str,
    record: Any,
    *,
    entity_label: str,
    next_step: str,
    ignore: Iterable[str] = (),
) -> None:
    """Raise an actionable 409 when another module still holds the record."""

    references = retained_references(db, organization_id, record, ignore=ignore)
    if not references:
        return
    summary = ", ".join(f"{count} {label}" for label, count in references.items())
    raise HTTPException(
        status_code=409,
        detail=f"Cannot permanently delete {entity_label}: it is still referenced by {summary}. {next_step}",
    )
