"""Tenant-scoped Authorization For Expenditure (AFE) register and cost estimate.

An AFE is scoped to one well under one rig. Its cost estimate is stored as
column-wise line tables (no JSON payload columns):

* ``afe_service_lines`` with rate-card children (``afe_service_rates``,
  ``afe_service_charges``, ``afe_service_section_rates``);
* ``afe_consumable_lines`` (drill bits carry a catalogue item; mud chemicals,
  cement additives and fuel are section/phase lump sums);
* ``afe_tangible_lines`` priced from the tangible catalogue.

Lines reference stable master-data ids (hole sections, phases, services, drill
bits, tangibles). They never reference well-configuration row ids, which are
regenerated whenever the well plan is saved. Rates and currencies are stored as
snapshots at save time so a saved estimate reads back exactly as it was priced.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from app.models.rig_well import now, uid

AFE_TYPES = ("Drilling", "Completion")
AFE_STATUSES = ("draft", "submitted", "review", "approval")
CHARGE_CATEGORIES = (
    "Mobilization",
    "Demobilization",
    "Operation",
    "Standby",
    "Personnel-Operation",
    "Personnel-Standby",
    "Fixed Charge",
    "Others",
)
CHARGING_BASES = ("Day Rate", "Per Service Rate", "Per Section Rate")
CONSUMABLE_CATEGORIES = ("Mud Chemicals", "Cement Additives", "Fuel", "Drill Bits")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class AfeChildRecord(Base):
    """Common columns for estimate line rows (no soft delete: they follow their AFE)."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )


class Afe(Base):
    """An Authorization For Expenditure scoped to one well (one rig, one well, one code)."""

    __tablename__ = "afes"
    __table_args__ = (
        UniqueConstraint("organization_id", "afe_code", name="uq_afes_org_code"),
        CheckConstraint("configuration_scope IN ('drilling', 'completion')", name="ck_afes_configuration_scope"),
        CheckConstraint(_in("afe_type", AFE_TYPES), name="ck_afes_type"),
        CheckConstraint(_in("status", AFE_STATUSES), name="ck_afes_status"),
        Index("ix_afes_org_deleted", "organization_id", "is_deleted"),
        Index("ix_afes_org_well", "organization_id", "well_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rig_id: Mapped[str] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=False, index=True)
    well_id: Mapped[str] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True)
    afe_code: Mapped[str] = mapped_column(String(50), nullable=False)
    afe_name: Mapped[str] = mapped_column(String(200), nullable=False)
    configuration_scope: Mapped[str] = mapped_column(String(20), default="drilling", server_default="drilling", nullable=False)
    afe_type: Mapped[str] = mapped_column(String(20), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", nullable=False)
    status_remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_changed_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    estimate_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimate_saved_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    standard_currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    service_lines: Mapped[list["AfeServiceLine"]] = relationship(
        cascade="all, delete-orphan",
        order_by="AfeServiceLine.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )
    consumable_lines: Mapped[list["AfeConsumableLine"]] = relationship(
        cascade="all, delete-orphan",
        order_by="AfeConsumableLine.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )
    tangible_lines: Mapped[list["AfeTangibleLine"]] = relationship(
        cascade="all, delete-orphan",
        order_by="AfeTangibleLine.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )
    exchange_rates: Mapped[list["AfeExchangeRate"]] = relationship(
        cascade="all, delete-orphan",
        order_by="AfeExchangeRate.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )


class AfeServiceLine(AfeChildRecord):
    __tablename__ = "afe_service_lines"
    __table_args__ = (
        CheckConstraint(_in("charging_basis", CHARGING_BASES), name="ck_afe_service_lines_basis"),
        CheckConstraint("service_amount >= 0", name="ck_afe_service_lines_amount"),
        Index("ix_afe_service_lines_afe", "afe_id"),
    )

    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True)
    charging_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    hole_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    rates: Mapped[list["AfeServiceRate"]] = relationship(
        cascade="all, delete-orphan", order_by="AfeServiceRate.sort_order", lazy="selectin", passive_deletes=True
    )
    charges: Mapped[list["AfeServiceCharge"]] = relationship(
        cascade="all, delete-orphan", order_by="AfeServiceCharge.sort_order", lazy="selectin", passive_deletes=True
    )
    section_rates: Mapped[list["AfeServiceSectionRate"]] = relationship(
        cascade="all, delete-orphan", order_by="AfeServiceSectionRate.sort_order", lazy="selectin", passive_deletes=True
    )


class AfeServiceRate(AfeChildRecord):
    """One unit rate per charge category for a Day Rate service line."""

    __tablename__ = "afe_service_rates"
    __table_args__ = (
        UniqueConstraint("line_id", "charge_category", name="uq_afe_service_rates_category"),
        CheckConstraint(_in("charge_category", CHARGE_CATEGORIES), name="ck_afe_service_rates_category"),
        CheckConstraint("unit_rate >= 0", name="ck_afe_service_rates_rate"),
    )

    line_id: Mapped[str] = mapped_column(ForeignKey("afe_service_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_category: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)


class AfeServiceCharge(AfeChildRecord):
    """A quantity of days (or hours) charged in a day-based category."""

    __tablename__ = "afe_service_charges"
    __table_args__ = (
        CheckConstraint(_in("charge_category", CHARGE_CATEGORIES), name="ck_afe_service_charges_category"),
        CheckConstraint(_in("quantity_unit", ("days", "hours")), name="ck_afe_service_charges_unit"),
        CheckConstraint("quantity >= 0", name="ck_afe_service_charges_qty"),
    )

    line_id: Mapped[str] = mapped_column(ForeignKey("afe_service_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_category: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    quantity_unit: Mapped[str] = mapped_column(String(10), default="days", server_default="days", nullable=False)


class AfeServiceSectionRate(AfeChildRecord):
    """A Per Section Rate amount for one section, optionally narrowed to one phase."""

    __tablename__ = "afe_service_section_rates"
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_afe_service_section_rates_amount"),)

    line_id: Mapped[str] = mapped_column(ForeignKey("afe_service_lines.id", ondelete="CASCADE"), nullable=False, index=True)
    hole_section_id: Mapped[str] = mapped_column(ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)


class AfeConsumableLine(AfeChildRecord):
    """A consumable estimate line.

    Drill Bits reference a drill bit and are priced as quantity x rate. Mud
    Chemicals, Cement Additives and Fuel carry an estimated lump sum only.
    """

    __tablename__ = "afe_consumable_lines"
    __table_args__ = (
        CheckConstraint(_in("category", CONSUMABLE_CATEGORIES), name="ck_afe_consumable_lines_category"),
        CheckConstraint(
            "(category = 'Drill Bits' AND drill_bit_id IS NOT NULL AND estimated_amount IS NULL) OR "
            "(category <> 'Drill Bits' AND drill_bit_id IS NULL AND estimated_amount IS NOT NULL)",
            name="ck_afe_consumable_lines_kind",
        ),
        CheckConstraint("quantity >= 0", name="ck_afe_consumable_lines_qty"),
        Index("ix_afe_consumable_lines_afe", "afe_id"),
    )

    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    hole_section_id: Mapped[str] = mapped_column(ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True)
    phase_id: Mapped[str | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True, index=True)
    drill_bit_id: Mapped[str | None] = mapped_column(ForeignKey("drill_bits.id", ondelete="RESTRICT"), nullable=True, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("1"), server_default="1", nullable=False)
    captured_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    override_rate: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    estimated_amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)


class AfeTangibleLine(AfeChildRecord):
    __tablename__ = "afe_tangible_lines"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_afe_tangible_lines_qty"),
        Index("ix_afe_tangible_lines_afe", "afe_id"),
    )

    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="CASCADE"), nullable=False)
    tangible_id: Mapped[str] = mapped_column(ForeignKey("tangibles.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("1"), server_default="1", nullable=False)
    captured_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    override_rate: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)


class AfeExchangeRate(AfeChildRecord):
    """Conversion rate used for one foreign currency of an estimate.

    ``rate`` is units of the AFE's standard currency per one unit of ``currency_code``.
    Rows exist only for currencies that need converting (multi-currency estimates).
    """

    __tablename__ = "afe_exchange_rates"
    __table_args__ = (
        UniqueConstraint("afe_id", "currency_code", name="uq_afe_exchange_rates_currency"),
        CheckConstraint("rate > 0", name="ck_afe_exchange_rates_rate"),
        Index("ix_afe_exchange_rates_afe", "afe_id"),
    )

    afe_id: Mapped[str] = mapped_column(ForeignKey("afes.id", ondelete="CASCADE"), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
