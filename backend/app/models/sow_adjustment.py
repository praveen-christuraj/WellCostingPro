"""Tenant-scoped AFE SOW adjustments and well plan adjustments.

An SOW (Scope of Work) adjustment records a formal revision to an approved AFE
estimate or a configured well plan without rewriting the original records:

* ``afe_sow_adjustments`` captures revised cost totals per AFE (services,
  consumables, tangibles) with a mandatory reason and a narrative of what was
  added or removed. The original estimate lines stay untouched; only the
  latest *approved* adjustment affects cost comparisons.
* ``well_plan_adjustments`` captures revised planned days per well and scope
  (drilling / completion) with section counts and a narrative of added or
  removed sections and phases. The configured well sections stay untouched.
* ``daily_cost_amendments`` logs each reopen of a submitted daily sheet that
  is older than the amendment threshold, so late edits are tracked separately
  from ordinary draft/submit moves.

All three tables are additive: when no approved adjustment exists, every
comparison falls back to the original AFE total and the configured planned
days, so existing data and behaviour are unchanged.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.rig_well import now, uid

SOW_STATUSES = ("draft", "approved", "void")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class AfeSowAdjustment(Base):
    """A revised cost total for one AFE, tracked separately from its estimate."""

    __tablename__ = "afe_sow_adjustments"
    __table_args__ = (
        UniqueConstraint("organization_id", "afe_id", "revision_number", name="uq_afe_sow_org_afe_revision"),
        CheckConstraint("configuration_scope IN ('drilling', 'completion')", name="ck_afe_sow_scope"),
        CheckConstraint(_in("status", SOW_STATUSES), name="ck_afe_sow_status"),
        CheckConstraint("revision_number >= 1", name="ck_afe_sow_revision"),
        CheckConstraint(
            "adjusted_services_total >= 0 AND adjusted_consumables_total >= 0 AND adjusted_tangibles_total >= 0",
            name="ck_afe_sow_adjusted_groups",
        ),
        Index("ix_afe_sow_org_afe", "organization_id", "afe_id"),
        Index("ix_afe_sow_org_well", "organization_id", "well_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="RESTRICT"), nullable=False, index=True)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    rig_id: Mapped[str] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=False, index=True)
    configuration_scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    sow_summary: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    standard_currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    # Snapshots of the saved estimate at creation time, for audit. Null while
    # the AFE has no converted total (pending conversion).
    original_services_total: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    original_consumables_total: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    original_tangibles_total: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    original_total: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    # Revised totals in the standard currency. adjusted_total is always the sum
    # of the three groups and is computed by the service layer.
    adjusted_services_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    adjusted_consumables_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    adjusted_tangibles_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    adjusted_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class WellPlanAdjustment(Base):
    """Revised planned days for one well and scope, without rewriting its plan."""

    __tablename__ = "well_plan_adjustments"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "well_id", "configuration_scope", "revision_number",
            name="uq_well_plan_org_well_scope_revision",
        ),
        CheckConstraint("configuration_scope IN ('drilling', 'completion')", name="ck_well_plan_scope"),
        CheckConstraint(_in("status", SOW_STATUSES), name="ck_well_plan_status"),
        CheckConstraint("revision_number >= 1", name="ck_well_plan_revision"),
        CheckConstraint(
            "planned_days_before >= 0 AND planned_days_after >= 0",
            name="ck_well_plan_days",
        ),
        Index("ix_well_plan_org_well", "organization_id", "well_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    configuration_scope: Mapped[str] = mapped_column(String(20), default="drilling", nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    sow_summary: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    planned_days_before: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    planned_days_after: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    section_count_before: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    section_count_after: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class DailyCostAmendment(Base):
    """One tracked reopen of an older submitted daily sheet.

    Ordinary reopens are already audited; this table exists so late edits
    (sheets reopened well after their cost date) can be listed separately from
    the general audit trail and counted per sheet.
    """

    __tablename__ = "daily_cost_amendments"
    __table_args__ = (
        UniqueConstraint("organization_id", "entry_id", "amendment_number", name="uq_daily_amend_org_entry_number"),
        Index("ix_daily_amend_org_entry", "organization_id", "entry_id"),
        Index("ix_daily_amend_org_well", "organization_id", "well_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="RESTRICT"), nullable=False, index=True)
    amendment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    days_after_cost_date: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    reopened_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    reopened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
