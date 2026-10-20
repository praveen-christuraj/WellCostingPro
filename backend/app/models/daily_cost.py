"""Daily Cost Management persistence models.

A daily sheet records actual costs for one workspace well and date. Starting
its first sheet locks two immutable pricing inputs: the selected AFE estimate
and the well's then-current catalogue rate book. Every line stores both its
native-currency amount and the converted amount used for AFE comparison, along
with the source rate, FX factor, activity scope and any override justification.

Services, consumables and tangibles are priced against the AFE estimate. A
fourth group, other expenses (Lost In Hole, hole problems, fishing, third-party
claims), records unexpected charges that have no AFE allowance: they carry the
same operational scope as every other line, are accounted in their own group,
and are deducted explicitly from the locked AFE total. Their remarks are
mandatory, because the remark is what explains the charge.

All business attributes are ordinary columns; no JSON payloads are persisted.
"""

from datetime import date, datetime
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.rig_well import now, uid

COST_CLASSIFICATIONS = ("Planned", "UPA", "NPT")
DAILY_COST_STATUSES = ("draft", "submitted")
DAILY_CHARGING_BASES = ("Day Rate", "Per Service Rate", "Per Section Rate")
DAILY_CHARGE_CATEGORIES = (
    "Mobilization",
    "Demobilization",
    "Operation",
    "Standby",
    "Personnel-Operation",
    "Personnel-Standby",
    "Fixed Charge",
    "Others",
)
DAILY_CONSUMABLE_CATEGORIES = ("Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits")
# Unexpected, unbudgeted charges (Lost In Hole, hole problems, claims …). They are
# recorded with the same operational scope as every other daily line, accounted in
# their own cost group, and deducted explicitly from the locked AFE total.
OTHER_EXPENSE_TYPE_LABELS: dict[str, str] = {
    "LIH": "Lost In Hole (LIH)",
    "HOLE_PROBLEM": "Hole Problem",
    "FISHING": "Fishing & Recovery",
    "SIDE_TRACK": "Side Track & Re-entry",
    "EQUIPMENT_DAMAGE": "Equipment Damage / Loss",
    "THIRD_PARTY_CLAIM": "Third Party Claim",
    "PENALTY": "Penalty / Fine",
    "MISC": "Miscellaneous Other Cost",
}
DAILY_OTHER_EXPENSE_TYPES = tuple(OTHER_EXPENSE_TYPE_LABELS)
CATALOGUE_ITEM_KINDS = ("mud_chemical", "cement_additive", "fuel", "drill_bit", "tangible")
BASELINE_RATE_KINDS = ("day_rate", "per_service", "per_section")
BUDGET_KINDS = ("service", "consumable_category", "drill_bit", "tangible")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class DailyCostWellRateBaseline(Base):
    """Immutable Master Data price book captured at the start of well tracking."""

    __tablename__ = "daily_cost_well_rate_baselines"
    __table_args__ = (
        UniqueConstraint("organization_id", "well_id", name="uq_daily_cost_rate_baselines_org_well"),
        Index("ix_daily_cost_rate_baselines_org_well", "organization_id", "well_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    locked_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    catalogue_rates: Mapped[list["DailyCostCatalogueRateSnapshot"]] = relationship(
        back_populates="rate_baseline",
        cascade="all, delete-orphan",
        order_by="DailyCostCatalogueRateSnapshot.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )


class DailyCostCatalogueRateSnapshot(Base):
    """Immutable unit price for one catalogue item at the well's rate lock.

    ``item_id`` is a typed UUID string whose target is determined by
    ``item_kind``. It intentionally has no polymorphic foreign key: these rows
    must retain their own historical identity and price after a master item is
    soft-deleted or permanently removed.
    """

    __tablename__ = "daily_cost_catalogue_rate_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "rate_baseline_id", "item_kind", "item_id", name="uq_daily_cost_catalogue_snapshot_item"
        ),
        CheckConstraint(_in("item_kind", CATALOGUE_ITEM_KINDS), name="ck_daily_cost_catalogue_snapshot_kind"),
        CheckConstraint("unit_rate >= 0", name="ck_daily_cost_catalogue_snapshot_rate"),
        Index("ix_daily_cost_catalogue_snapshot_lookup", "organization_id", "well_id", "item_kind", "item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rate_baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_well_rate_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    item_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_code: Mapped[str] = mapped_column(String(50), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    rate_baseline: Mapped[DailyCostWellRateBaseline] = relationship(back_populates="catalogue_rates", lazy="select")


class DailyCostBaseline(Base):
    """Immutable snapshot of one AFE's approved-for-tracking plan and rate card."""

    __tablename__ = "daily_cost_baselines"
    __table_args__ = (
        UniqueConstraint("organization_id", "afe_id", name="uq_daily_cost_baselines_org_afe"),
        CheckConstraint("services_total >= 0 AND consumables_total >= 0 AND tangibles_total >= 0", name="ck_daily_cost_baselines_groups"),
        Index("ix_daily_cost_baselines_org_well", "organization_id", "well_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="RESTRICT"), nullable=False, index=True)
    rate_baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_well_rate_baselines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    afe_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    afe_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    standard_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    services_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    consumables_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    tangibles_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    afe_estimate_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    locked_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    rate_baseline: Mapped[DailyCostWellRateBaseline] = relationship(lazy="joined")
    service_rates: Mapped[list["DailyCostBaselineServiceRate"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan", order_by="DailyCostBaselineServiceRate.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    budget_lines: Mapped[list["DailyCostBaselineBudgetLine"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan", order_by="DailyCostBaselineBudgetLine.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    well_sections: Mapped[list["DailyCostBaselineSection"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan", order_by="DailyCostBaselineSection.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    exchange_rates: Mapped[list["DailyCostBaselineExchangeRate"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan", order_by="DailyCostBaselineExchangeRate.sort_order",
        lazy="selectin", passive_deletes=True,
    )


class DailyCostBaselineServiceRate(Base):
    """An immutable AFE service rate, retained per charging basis and scope."""

    __tablename__ = "daily_cost_baseline_service_rates"
    __table_args__ = (
        CheckConstraint(_in("rate_kind", BASELINE_RATE_KINDS), name="ck_daily_cost_service_rate_kind"),
        CheckConstraint(_in("charging_basis", DAILY_CHARGING_BASES), name="ck_daily_cost_service_rate_basis"),
        CheckConstraint("unit_rate >= 0", name="ck_daily_cost_service_rate_value"),
        Index("ix_daily_cost_service_rate_lookup", "baseline_id", "service_id", "charging_basis", "charge_category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[str] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_afe_line_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    service_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    charging_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    rate_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    charge_category: Mapped[str] = mapped_column(String(40), default="", server_default="", nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    baseline: Mapped[DailyCostBaseline] = relationship(back_populates="service_rates", lazy="select")


class DailyCostBaselineBudgetLine(Base):
    """AFE allowance snapshot used for planned-versus-actual matching."""

    __tablename__ = "daily_cost_baseline_budget_lines"
    __table_args__ = (
        CheckConstraint(_in("cost_group", ("Services", "Consumables", "Tangibles")), name="ck_daily_cost_budget_group"),
        CheckConstraint(_in("budget_kind", BUDGET_KINDS), name="ck_daily_cost_budget_kind"),
        CheckConstraint("native_amount >= 0 AND planned_amount >= 0", name="ck_daily_cost_budget_amounts"),
        Index("ix_daily_cost_budget_lookup", "baseline_id", "budget_kind", "item_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cost_group: Mapped[str] = mapped_column(String(20), nullable=False)
    budget_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    source_afe_line_id: Mapped[str] = mapped_column(String(36), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    phase_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    native_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"), server_default="1", nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    baseline: Mapped[DailyCostBaseline] = relationship(back_populates="budget_lines", lazy="select")


class DailyCostBaselineSection(Base):
    """Well section snapshot: daily validation never follows a later plan edit."""

    __tablename__ = "daily_cost_baseline_sections"
    __table_args__ = (
        UniqueConstraint("baseline_id", "hole_section_id", name="uq_daily_cost_baseline_section"),
        Index("ix_daily_cost_baseline_sections_baseline", "baseline_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hole_section_id: Mapped[str] = mapped_column(ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False)
    section_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    section_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    from_depth: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    to_depth: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_days: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    baseline: Mapped[DailyCostBaseline] = relationship(back_populates="well_sections", lazy="select")
    phases: Mapped[list["DailyCostBaselinePhase"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="DailyCostBaselinePhase.sort_order",
        lazy="selectin", passive_deletes=True,
    )


class DailyCostBaselinePhase(Base):
    """Phase snapshot under a frozen baseline section."""

    __tablename__ = "daily_cost_baseline_phases"
    __table_args__ = (
        UniqueConstraint("section_snapshot_id", "phase_id", name="uq_daily_cost_baseline_phase"),
        Index("ix_daily_cost_baseline_phases_section", "section_snapshot_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_baseline_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[str] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False)
    phase_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    phase_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    days: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    section: Mapped[DailyCostBaselineSection] = relationship(back_populates="phases", lazy="select")


class DailyCostBaselineExchangeRate(Base):
    """FX snapshots copied from the AFE: standard currency units per 1 foreign unit."""

    __tablename__ = "daily_cost_baseline_exchange_rates"
    __table_args__ = (UniqueConstraint("baseline_id", "currency_code", name="uq_daily_cost_baseline_exchange_currency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_baselines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    baseline: Mapped[DailyCostBaseline] = relationship(back_populates="exchange_rates", lazy="select")


class DailyCostEntry(Base):
    """One editable or submitted daily sheet for a well and operating date."""

    __tablename__ = "daily_cost_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "well_id", "cost_date", "afe_id", name="uq_daily_cost_entries_org_well_date_afe"),
        UniqueConstraint("organization_id", "daily_cost_code", name="uq_daily_cost_entries_org_code"),
        CheckConstraint(_in("status", DAILY_COST_STATUSES), name="ck_daily_cost_entries_status"),
        Index("ix_daily_cost_entries_org_date", "organization_id", "cost_date"),
        Index("ix_daily_cost_entries_org_status", "organization_id", "status"),
        Index("ix_daily_cost_entries_org_deleted", "organization_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rig_id: Mapped[str] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=False, index=True)
    rig_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    rig_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    well_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    well_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="RESTRICT"), nullable=False, index=True)
    afe_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    afe_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    afe_status_at_create: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_well_rate_baselines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    baseline_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_baselines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    daily_cost_code: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    standard_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    status_remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    services_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    consumables_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    tangibles_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    # Accounted apart from the three cost groups, so the AFE reconciliation can show
    # the deduction explicitly. total_cost already includes it.
    other_expenses_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    upa_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    npt_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    usd_exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"), server_default="1", nullable=False)
    services_total_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    consumables_total_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    tangibles_total_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    other_expenses_total_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    upa_total_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    npt_total_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    rig: Mapped["Rig"] = relationship("Rig", lazy="joined")
    well: Mapped["Well"] = relationship("Well", lazy="joined")
    afe: Mapped["Afe"] = relationship("Afe", lazy="joined")
    rate_baseline: Mapped[DailyCostWellRateBaseline] = relationship(lazy="joined")
    baseline: Mapped[DailyCostBaseline] = relationship(lazy="joined")
    service_lines: Mapped[list["DailyCostServiceLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="DailyCostServiceLine.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    consumable_lines: Mapped[list["DailyCostConsumableLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="DailyCostConsumableLine.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    tangible_lines: Mapped[list["DailyCostTangibleLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="DailyCostTangibleLine.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    other_expense_lines: Mapped[list["DailyCostOtherExpenseLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="DailyCostOtherExpenseLine.sort_order",
        lazy="selectin", passive_deletes=True,
    )


class DailyCostLine(Base):
    """Column-wise fields shared by service, consumable and tangible cost lines."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("daily_cost_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    activity_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    activity_name_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    section_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    section_name_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    phase_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    phase_name_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    sub_activity_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    sub_activity_name_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    sub_activity_party_snapshot: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True)
    sub_activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("well_sub_activities.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    classification: Mapped[str] = mapped_column(String(10), default="Planned", server_default="Planned", nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=True, index=True)
    vendor_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    vendor_name_snapshot: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    party_name: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(20), default="unit", server_default="unit", nullable=False)
    captured_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    override_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"), server_default="1", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    standard_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    usd_exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("1"), server_default="1", nullable=False)
    usd_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), server_default="0", nullable=False)
    actual_depth: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    actual_depth_input: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    actual_depth_unit: Mapped[str] = mapped_column(String(5), default="m", server_default="m", nullable=False)
    depth_entry_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rate_source: Mapped[str] = mapped_column(String(30), default="", server_default="", nullable=False)
    rate_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_budget_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_cost_baseline_budget_lines.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    budget_key: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False, index=True)
    override_reason: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)


class DailyCostServiceLine(DailyCostLine):
    __tablename__ = "daily_cost_service_lines"
    __table_args__ = (
        CheckConstraint(_in("classification", COST_CLASSIFICATIONS), name="ck_daily_cost_service_classification"),
        CheckConstraint(_in("charging_basis", DAILY_CHARGING_BASES), name="ck_daily_cost_service_basis"),
        CheckConstraint(_in("charge_category", DAILY_CHARGE_CATEGORIES), name="ck_daily_cost_service_category"),
        CheckConstraint("quantity >= 0", name="ck_daily_cost_service_quantity"),
        Index("ix_daily_cost_service_line_entry_order", "entry_id", "sort_order"),
    )

    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True)
    service_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    service_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    charging_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    charge_category: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline_service_rate_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_cost_baseline_service_rates.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    entry: Mapped[DailyCostEntry] = relationship(back_populates="service_lines", lazy="select")
    service: Mapped["Service"] = relationship("Service", lazy="joined")
    activity: Mapped["Activity"] = relationship("Activity", lazy="joined")
    section: Mapped["HoleSection | None"] = relationship("HoleSection", lazy="joined")
    phase: Mapped["Phase | None"] = relationship("Phase", lazy="joined")
    sub_activity: Mapped["WellSubActivity | None"] = relationship("WellSubActivity", lazy="joined")
    vendor: Mapped["Vendor | None"] = relationship("Vendor", lazy="joined")
    baseline_service_rate: Mapped[DailyCostBaselineServiceRate | None] = relationship(lazy="joined")


class DailyCostConsumableLine(DailyCostLine):
    __tablename__ = "daily_cost_consumable_lines"
    __table_args__ = (
        CheckConstraint(_in("classification", COST_CLASSIFICATIONS), name="ck_daily_cost_consumable_classification"),
        CheckConstraint(_in("category", DAILY_CONSUMABLE_CATEGORIES), name="ck_daily_cost_consumable_category"),
        CheckConstraint(_in("item_kind", CATALOGUE_ITEM_KINDS[:-1]), name="ck_daily_cost_consumable_item_kind"),
        CheckConstraint("quantity >= 0", name="ck_daily_cost_consumable_quantity"),
        Index("ix_daily_cost_consumable_line_entry_order", "entry_id", "sort_order"),
    )

    category: Mapped[str] = mapped_column(String(40), nullable=False)
    item_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    catalogue_rate_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_cost_catalogue_rate_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    entry: Mapped[DailyCostEntry] = relationship(back_populates="consumable_lines", lazy="select")
    activity: Mapped["Activity"] = relationship("Activity", lazy="joined")
    section: Mapped["HoleSection | None"] = relationship("HoleSection", lazy="joined")
    phase: Mapped["Phase | None"] = relationship("Phase", lazy="joined")
    sub_activity: Mapped["WellSubActivity | None"] = relationship("WellSubActivity", lazy="joined")
    vendor: Mapped["Vendor | None"] = relationship("Vendor", lazy="joined")
    catalogue_rate_snapshot: Mapped[DailyCostCatalogueRateSnapshot | None] = relationship(lazy="joined")


class DailyCostTangibleLine(DailyCostLine):
    __tablename__ = "daily_cost_tangible_lines"
    __table_args__ = (
        CheckConstraint(_in("classification", COST_CLASSIFICATIONS), name="ck_daily_cost_tangible_classification"),
        CheckConstraint("quantity >= 0", name="ck_daily_cost_tangible_quantity"),
        Index("ix_daily_cost_tangible_line_entry_order", "entry_id", "sort_order"),
    )

    tangible_id: Mapped[str] = mapped_column(ForeignKey("tangibles.id", ondelete="RESTRICT"), nullable=False, index=True)
    tangible_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    tangible_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    catalogue_rate_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("daily_cost_catalogue_rate_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    entry: Mapped[DailyCostEntry] = relationship(back_populates="tangible_lines", lazy="select")
    tangible: Mapped["Tangible"] = relationship("Tangible", lazy="joined")
    activity: Mapped["Activity"] = relationship("Activity", lazy="joined")
    section: Mapped["HoleSection | None"] = relationship("HoleSection", lazy="joined")
    phase: Mapped["Phase | None"] = relationship("Phase", lazy="joined")
    sub_activity: Mapped["WellSubActivity | None"] = relationship("WellSubActivity", lazy="joined")
    vendor: Mapped["Vendor | None"] = relationship("Vendor", lazy="joined")
    catalogue_rate_snapshot: Mapped[DailyCostCatalogueRateSnapshot | None] = relationship(lazy="joined")


class DailyCostOtherExpenseLine(DailyCostLine):
    """An unexpected charge recorded outside the AFE estimate.

    Lost In Hole, hole problems, fishing and recovery, third-party claims and
    similar events are booked here instead of inside the Services, Consumables or
    Tangibles groups, so the sheet can show them as an explicit deduction from the
    locked AFE total. The line keeps every operational scope column of the shared
    daily cost line (rig-scoped well, activity, sub activity, hole section, phase,
    responsible party), the entered unit rate, the FX factor and both amounts.
    ``remarks`` is mandatory: it is the only narrative that explains the charge.
    """

    __tablename__ = "daily_cost_other_expense_lines"
    __table_args__ = (
        CheckConstraint(_in("classification", COST_CLASSIFICATIONS), name="ck_daily_cost_other_classification"),
        CheckConstraint(_in("expense_type", DAILY_OTHER_EXPENSE_TYPES), name="ck_daily_cost_other_expense_type"),
        CheckConstraint("quantity >= 0", name="ck_daily_cost_other_quantity"),
        CheckConstraint("LENGTH(TRIM(remarks)) > 0", name="ck_daily_cost_other_remarks"),
        Index("ix_daily_cost_other_line_entry_order", "entry_id", "sort_order"),
        Index("ix_daily_cost_other_line_org_type", "organization_id", "expense_type"),
    )

    expense_type: Mapped[str] = mapped_column(String(30), nullable=False)
    expense_type_label: Mapped[str] = mapped_column(String(120), nullable=False)
    expense_description: Mapped[str] = mapped_column(String(300), default="", server_default="", nullable=False)

    entry: Mapped[DailyCostEntry] = relationship(back_populates="other_expense_lines", lazy="select")
    activity: Mapped["Activity"] = relationship("Activity", lazy="joined")
    section: Mapped["HoleSection | None"] = relationship("HoleSection", lazy="joined")
    phase: Mapped["Phase | None"] = relationship("Phase", lazy="joined")
    sub_activity: Mapped["WellSubActivity | None"] = relationship("WellSubActivity", lazy="joined")
    vendor: Mapped["Vendor | None"] = relationship("Vendor", lazy="joined")
