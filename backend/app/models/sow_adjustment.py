"""Tenant-scoped AFE SOW adjustments and well plan adjustments.

An SOW (Scope of Work) adjustment records a formal revision to an approved AFE
estimate or a configured well plan without rewriting the original records:

* ``afe_sow_adjustments`` captures a revised cost estimate per AFE with a
  mandatory reason and a narrative of what was added or removed. The revision
  is entered through the same modules as the AFE estimate itself — service
  lines (with rate cards), consumable lines and tangible lines — and its
  revised totals are derived from those lines. The original estimate lines
  stay untouched; only the latest *approved* adjustment affects cost
  comparisons.
* ``well_plan_adjustments`` captures a revised well plan per well and scope
  (drilling / completion) with a mandatory reason and a narrative of added or
  removed sections and phases. The revision is entered through the same
  section/phase grid as the well configuration itself, so users rework the
  entered values, add sections or phases, and the revised planned days and
  section count are derived from that grid. The configured well sections stay
  untouched.
* ``daily_cost_amendments`` logs each reopen of a submitted daily sheet that
  is older than the amendment threshold, so late edits are tracked separately
  from ordinary draft/submit moves.

Every adjustment stores its revision as two-sided line rows: the ``before``
side snapshots the entered values being revised and the ``after`` side holds
the revised entries, linked across sides by ``pair_key`` so each revised line
can be read against the value it replaces. Lines added by the revision exist
only on the ``after`` side; lines removed by it exist only on the ``before``
side. Aggregate columns on the parent rows (planned days, section counts,
group totals) are derived snapshots for reporting and history lists.

All tables are additive: when no approved adjustment exists, every comparison
falls back to the original AFE total and the configured planned days, so
existing data and behaviour are unchanged.
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.afe import CHARGE_CATEGORIES, CHARGING_BASES, CONSUMABLE_CATEGORIES
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
    # Revised totals in the standard currency, derived server-side from the
    # revised estimate lines (after-side rows). adjusted_total is always the
    # sum of the three groups.
    adjusted_services_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    adjusted_consumables_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    adjusted_tangibles_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    adjusted_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    approved_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    service_lines: Mapped[list["AfeSowServiceLine"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="[AfeSowServiceLine.plan_side, AfeSowServiceLine.sort_order]",
        lazy="selectin",
        passive_deletes=True,
    )
    consumable_lines: Mapped[list["AfeSowConsumableLine"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="[AfeSowConsumableLine.plan_side, AfeSowConsumableLine.sort_order]",
        lazy="selectin",
        passive_deletes=True,
    )
    tangible_lines: Mapped[list["AfeSowTangibleLine"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="[AfeSowTangibleLine.plan_side, AfeSowTangibleLine.sort_order]",
        lazy="selectin",
        passive_deletes=True,
    )
    exchange_rates: Mapped[list["AfeSowExchangeRate"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="[AfeSowExchangeRate.plan_side, AfeSowExchangeRate.sort_order]",
        lazy="selectin",
        passive_deletes=True,
    )


class SowLineRecord(Base):
    """Common columns for two-sided SOW revision line rows."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 'before' snapshots the entered values being revised; 'after' holds the
    # revised entries. pair_key links a before row to the after row that
    # replaces it; after-only rows are additions, before-only rows removals.
    plan_side: Mapped[str] = mapped_column(String(10), nullable=False)
    pair_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )


class AfeSowServiceLine(SowLineRecord):
    """One revised (or snapshot) service line, mirroring ``afe_service_lines``."""

    __tablename__ = "afe_sow_service_lines"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_afe_sow_service_pair"),
        CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_service_side"),
        CheckConstraint(_in("charging_basis", CHARGING_BASES), name="ck_afe_sow_service_basis"),
        CheckConstraint("service_amount >= 0", name="ck_afe_sow_service_amount"),
        Index("ix_afe_sow_service_adjustment", "adjustment_id"),
    )

    adjustment_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True)
    charging_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    adjustment: Mapped[AfeSowAdjustment] = relationship(back_populates="service_lines", lazy="joined")
    rates: Mapped[list["AfeSowServiceRate"]] = relationship(
        back_populates="line", cascade="all, delete-orphan", order_by="AfeSowServiceRate.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    charges: Mapped[list["AfeSowServiceCharge"]] = relationship(
        back_populates="line", cascade="all, delete-orphan", order_by="AfeSowServiceCharge.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    section_rates: Mapped[list["AfeSowServiceSectionRate"]] = relationship(
        back_populates="line", cascade="all, delete-orphan", order_by="AfeSowServiceSectionRate.sort_order",
        lazy="selectin", passive_deletes=True,
    )


class AfeSowServiceRate(SowLineRecord):
    """One unit rate per charge category on a revised Day Rate service line."""

    __tablename__ = "afe_sow_service_rates"
    __table_args__ = (
        UniqueConstraint("line_id", "charge_category", name="uq_afe_sow_service_rates_category"),
        CheckConstraint(_in("charge_category", CHARGE_CATEGORIES), name="ck_afe_sow_service_rates_cat"),
        CheckConstraint("unit_rate >= 0", name="ck_afe_sow_service_rates_rate"),
    )

    line_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_service_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charge_category: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)

    line: Mapped[AfeSowServiceLine] = relationship(back_populates="rates", lazy="joined")


class AfeSowServiceCharge(SowLineRecord):
    """One quantity of days (or hours) charged in a day-based category."""

    __tablename__ = "afe_sow_service_charges"
    __table_args__ = (
        CheckConstraint(_in("charge_category", CHARGE_CATEGORIES), name="ck_afe_sow_service_charges_cat"),
        CheckConstraint(_in("quantity_unit", ("days", "hours")), name="ck_afe_sow_service_charges_unit"),
        CheckConstraint("quantity >= 0", name="ck_afe_sow_service_charges_qty"),
    )

    line_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_service_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charge_category: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="days", server_default="days", nullable=False)

    line: Mapped[AfeSowServiceLine] = relationship(back_populates="charges", lazy="joined")


class AfeSowServiceSectionRate(SowLineRecord):
    """One Per Section Rate amount on a revised service line."""

    __tablename__ = "afe_sow_service_section_rates"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_afe_sow_service_section_rates_amount"),
    )

    line_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_service_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hole_section_id: Mapped[str] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)

    line: Mapped[AfeSowServiceLine] = relationship(back_populates="section_rates", lazy="joined")


class AfeSowConsumableLine(SowLineRecord):
    """One revised (or snapshot) consumable line, mirroring ``afe_consumable_lines``."""

    __tablename__ = "afe_sow_consumable_lines"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_afe_sow_consumable_pair"),
        CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_consumable_side"),
        CheckConstraint(_in("category", CONSUMABLE_CATEGORIES), name="ck_afe_sow_consumable_category"),
        CheckConstraint(
            "(category = 'Drill Bits' AND drill_bit_id IS NOT NULL AND estimated_amount IS NULL) OR "
            "(category <> 'Drill Bits' AND drill_bit_id IS NULL AND estimated_amount IS NOT NULL)",
            name="ck_afe_sow_consumable_kind",
        ),
        CheckConstraint("quantity >= 0", name="ck_afe_sow_consumable_qty"),
        Index("ix_afe_sow_consumable_adjustment", "adjustment_id"),
    )

    adjustment_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    hole_section_id: Mapped[str] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phase_id: Mapped[str | None] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    drill_bit_id: Mapped[str | None] = mapped_column(
        ForeignKey("drill_bits.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("1"), nullable=False)
    captured_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    override_rate: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    estimated_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    adjustment: Mapped[AfeSowAdjustment] = relationship(back_populates="consumable_lines", lazy="joined")


class AfeSowTangibleLine(SowLineRecord):
    """One revised (or snapshot) tangible line, mirroring ``afe_tangible_lines``."""

    __tablename__ = "afe_sow_tangible_lines"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_afe_sow_tangible_pair"),
        CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_tangible_side"),
        CheckConstraint("quantity >= 0", name="ck_afe_sow_tangible_qty"),
        Index("ix_afe_sow_tangible_adjustment", "adjustment_id"),
    )

    adjustment_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tangible_id: Mapped[str] = mapped_column(
        ForeignKey("tangibles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("1"), nullable=False)
    captured_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), nullable=False)
    override_rate: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    adjustment: Mapped[AfeSowAdjustment] = relationship(back_populates="tangible_lines", lazy="joined")


class AfeSowExchangeRate(Base):
    """Conversion rates one side of the revision was priced with.

    ``rate`` is units of the standard currency per one unit of ``currency_code``.
    The ``before`` side snapshots the rates the saved estimate used; the
    ``after`` side holds the rates the revision is priced with. Both sides are
    kept so each side's lines reprice exactly as entered.
    """

    __tablename__ = "afe_sow_exchange_rates"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "plan_side", "currency_code", name="uq_afe_sow_rates_currency"),
        CheckConstraint("plan_side IN ('before', 'after')", name="ck_afe_sow_rates_side"),
        CheckConstraint("rate > 0", name="ck_afe_sow_rates_rate"),
        Index("ix_afe_sow_rates_adjustment", "adjustment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    adjustment_id: Mapped[str] = mapped_column(
        ForeignKey("afe_sow_adjustments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_side: Mapped[str] = mapped_column(String(10), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    adjustment: Mapped[AfeSowAdjustment] = relationship(back_populates="exchange_rates", lazy="joined")


class WellPlanAdjustment(Base):
    """A revised well plan for one well and scope, without rewriting its plan.

    Planned days and the section count are derived from the revised
    section/phase grid (the ``after`` side) at save time; the ``before``
    values snapshot the configured plan the revision was entered against.
    """

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

    sections: Mapped[list["WellPlanAdjustmentSection"]] = relationship(
        back_populates="adjustment",
        cascade="all, delete-orphan",
        order_by="[WellPlanAdjustmentSection.plan_side, WellPlanAdjustmentSection.sort_order]",
        lazy="selectin",
        passive_deletes=True,
    )


class WellPlanAdjustmentSection(SowLineRecord):
    """One section of the revised plan grid, mirroring ``well_sections``.

    ``plan_side``/``pair_key`` work exactly as on the AFE revision lines: the
    before row snapshots the configured section, the after row holds the
    revised entry (edited in place or newly added).
    """

    __tablename__ = "well_plan_adjustment_sections"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_well_plan_adj_section_pair"),
        CheckConstraint("plan_side IN ('before', 'after')", name="ck_well_plan_adj_section_side"),
        CheckConstraint("from_depth >= 0 AND to_depth >= 0", name="ck_well_plan_adj_section_depth"),
        Index("ix_well_plan_adj_section_adjustment", "adjustment_id"),
    )

    adjustment_id: Mapped[str] = mapped_column(
        ForeignKey("well_plan_adjustments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hole_section_id: Mapped[str] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_depth: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    to_depth: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)

    adjustment: Mapped[WellPlanAdjustment] = relationship(back_populates="sections", lazy="joined")
    phases: Mapped[list["WellPlanAdjustmentPhase"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="WellPlanAdjustmentPhase.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )


class WellPlanAdjustmentPhase(SowLineRecord):
    """One phase row of the revised plan grid, mirroring ``well_phases``."""

    __tablename__ = "well_plan_adjustment_phases"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "plan_side", "pair_key", name="uq_well_plan_adj_phase_pair"),
        CheckConstraint("plan_side IN ('before', 'after')", name="ck_well_plan_adj_phase_side"),
        CheckConstraint("days >= 0", name="ck_well_plan_adj_phase_days"),
        Index("ix_well_plan_adj_phase_adjustment", "adjustment_id"),
        Index("ix_well_plan_adj_phase_section", "section_id"),
    )

    adjustment_id: Mapped[str] = mapped_column(
        ForeignKey("well_plan_adjustments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[str] = mapped_column(
        ForeignKey("well_plan_adjustment_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[str] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False, index=True)
    days: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)

    section: Mapped[WellPlanAdjustmentSection] = relationship(back_populates="phases", lazy="joined")


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
