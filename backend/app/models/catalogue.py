"""Tenant-scoped catalogue for Master Data Management: Tangibles, Consumables and
the user-managed dropdown lists they depend on.

Conventions (see ``.agent/memory/project.md``):

* Column-wise tables only; no JSON payload columns.
* Codes and part numbers are entered manually and are unique per workspace.
* Dropdown values are foreign keys to ``catalogue_options`` so renaming a
  category, manufacturer or type flows through every record that uses it.
* Every priced item keeps an append-only rate-revision history. The item row
  mirrors its latest revision so list views read a single row.
* Soft delete (``is_deleted``/``deleted_at``) with restore and purge from
  Deleted Entries, shared with the rest of Master Data Management.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
from app.models.master_data import MasterDataRecord, now, uid

# Scope is a fixed dropdown; every other dropdown is user-managed (catalogue_options).
TANGIBLE_SCOPES = ("Drilling", "Completion", "Others")

# list_key -> (display label, parent list key or None)
CATALOGUE_LISTS: dict[str, tuple[str, str | None]] = {
    "tangible_category": ("Tangible categories", None),
    "tangible_subcategory": ("Tangible subcategories", "tangible_category"),
    "manufacturer": ("Manufacturers (shared)", None),
    "drill_bit_type": ("Drill bit types", None),
    "mud_chemical_group": ("Mud chemical groups", None),
    "cement_additive_type": ("Cement additive types", None),
}

# Fixed fuel types seeded per workspace. Only their prices are maintained.
FUEL_TYPE_SEEDS: tuple[tuple[str, str], ...] = (
    ("DIESEL", "Diesel"),
    ("PETROL", "Petrol / Gasoline"),
    ("KEROSENE", "Kerosene"),
    ("JET-A1", "Aviation fuel (Jet A-1)"),
)


class CatalogueOption(MasterDataRecord):
    """One value of a user-managed dropdown list.

    ``parent_id`` links a subcategory to its category. ``parent_key`` mirrors it
    as a non-null string so the uniqueness rule also works for top-level values.
    ``value_key`` is the case-folded value, so ``Mud`` and ``mud`` cannot coexist.
    """

    __tablename__ = "catalogue_options"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "list_key", "parent_key", "value_key",
            name="uq_catalogue_options_value",
        ),
        Index("ix_catalogue_options_list", "organization_id", "list_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    list_key: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("catalogue_options.id", ondelete="CASCADE"), nullable=True, index=True
    )
    parent_key: Mapped[str] = mapped_column(String(36), default="", server_default="", nullable=False)
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    value_key: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class PricedRecord(MasterDataRecord):
    """Columns shared by every priced catalogue item (abstract).

    ``unit_rate`` is the rate as per PO for uplift-priced items (tangibles, drill
    bits) and the plain unit rate for consumables and fuel. ``cost_uplift`` and
    ``final_cost`` are only used by uplift-priced items; ``final_cost`` =
    ``unit_rate`` x ``cost_uplift`` / 100.
    """

    __abstract__ = True

    unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    cost_uplift: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    final_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    po_number: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_revision_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class RateRevision(Base):
    """Append-only price revision (abstract). Concrete tables add their item FK.

    Revisions are never edited or deleted individually; they disappear only when
    their parent item is permanently deleted from Deleted Entries.
    """

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    previous_unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False)
    cost_uplift: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    final_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    previous_final_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    po_number: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


# ---------------------------------------------------------------------------
# Tangibles
# ---------------------------------------------------------------------------


class Tangible(PricedRecord):
    __tablename__ = "tangibles"
    __table_args__ = (
        UniqueConstraint("organization_id", "tangible_code", name="uq_tangibles_org_code"),
        CheckConstraint("scope IN ('Drilling', 'Completion', 'Others')", name="ck_tangibles_scope"),
    )

    tangible_code: Mapped[str] = mapped_column(String(50), nullable=False)
    tangible_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    subcategory_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    manufacturer_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    revisions: Mapped[list["TangibleRevision"]] = relationship(
        back_populates="tangible", cascade="all, delete-orphan", order_by="desc(TangibleRevision.revision_number)"
    )


class TangibleRevision(RateRevision):
    __tablename__ = "tangible_rate_revisions"
    __table_args__ = (UniqueConstraint("tangible_id", "revision_number", name="uq_tangible_rate_revisions_number"),)

    tangible_id: Mapped[str] = mapped_column(ForeignKey("tangibles.id", ondelete="CASCADE"), nullable=False, index=True)
    tangible: Mapped[Tangible] = relationship(back_populates="revisions")


# ---------------------------------------------------------------------------
# Consumables: drill bits (tangible-style pricing), mud chemicals, cement additives, fuel
# ---------------------------------------------------------------------------


class DrillBit(PricedRecord):
    __tablename__ = "drill_bits"
    __table_args__ = (UniqueConstraint("organization_id", "bit_code", name="uq_drill_bits_org_code"),)

    bit_code: Mapped[str] = mapped_column(String(50), nullable=False)
    bit_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    bit_type_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    manufacturer_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_no: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[str] = mapped_column(String(60), nullable=False)
    iadc_code: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)
    serial_number: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False, index=True)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    revisions: Mapped[list["DrillBitRevision"]] = relationship(
        back_populates="drill_bit", cascade="all, delete-orphan", order_by="desc(DrillBitRevision.revision_number)"
    )


class DrillBitRevision(RateRevision):
    __tablename__ = "drill_bit_rate_revisions"
    __table_args__ = (UniqueConstraint("drill_bit_id", "revision_number", name="uq_drill_bit_rate_revisions_number"),)

    drill_bit_id: Mapped[str] = mapped_column(ForeignKey("drill_bits.id", ondelete="CASCADE"), nullable=False, index=True)
    drill_bit: Mapped[DrillBit] = relationship(back_populates="revisions")


class MudChemical(PricedRecord):
    __tablename__ = "mud_chemicals"
    __table_args__ = (UniqueConstraint("organization_id", "chemical_code", name="uq_mud_chemicals_org_code"),)

    chemical_code: Mapped[str] = mapped_column(String(50), nullable=False)
    chemical_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    manufacturer_id: Mapped[str | None] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=True, index=True)
    part_number: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    revisions: Mapped[list["MudChemicalRevision"]] = relationship(
        back_populates="mud_chemical", cascade="all, delete-orphan", order_by="desc(MudChemicalRevision.revision_number)"
    )


class MudChemicalRevision(RateRevision):
    __tablename__ = "mud_chemical_rate_revisions"
    __table_args__ = (UniqueConstraint("mud_chemical_id", "revision_number", name="uq_mud_chemical_rate_revisions_number"),)

    mud_chemical_id: Mapped[str] = mapped_column(ForeignKey("mud_chemicals.id", ondelete="CASCADE"), nullable=False, index=True)
    mud_chemical: Mapped[MudChemical] = relationship(back_populates="revisions")


class CementAdditive(PricedRecord):
    __tablename__ = "cement_additives"
    __table_args__ = (UniqueConstraint("organization_id", "additive_code", name="uq_cement_additives_org_code"),)

    additive_code: Mapped[str] = mapped_column(String(50), nullable=False)
    additive_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    additive_type_id: Mapped[str] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    manufacturer_id: Mapped[str | None] = mapped_column(ForeignKey("catalogue_options.id", ondelete="RESTRICT"), nullable=True, index=True)
    part_number: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)

    revisions: Mapped[list["CementAdditiveRevision"]] = relationship(
        back_populates="cement_additive", cascade="all, delete-orphan", order_by="desc(CementAdditiveRevision.revision_number)"
    )


class CementAdditiveRevision(RateRevision):
    __tablename__ = "cement_additive_rate_revisions"
    __table_args__ = (UniqueConstraint("cement_additive_id", "revision_number", name="uq_cement_additive_rate_revisions_number"),)

    cement_additive_id: Mapped[str] = mapped_column(ForeignKey("cement_additives.id", ondelete="CASCADE"), nullable=False, index=True)
    cement_additive: Mapped[CementAdditive] = relationship(back_populates="revisions")


class FuelType(PricedRecord):
    """Fixed fuel types. Only the price (and its currency/unit) is maintained."""

    __tablename__ = "fuel_types"
    __table_args__ = (UniqueConstraint("organization_id", "fuel_code", name="uq_fuel_types_org_code"),)

    fuel_code: Mapped[str] = mapped_column(String(30), nullable=False)
    fuel_name: Mapped[str] = mapped_column(String(150), nullable=False)
    uom: Mapped[str] = mapped_column(String(50), default="L", server_default="L", nullable=False)

    revisions: Mapped[list["FuelPriceRevision"]] = relationship(
        back_populates="fuel_type", cascade="all, delete-orphan", order_by="desc(FuelPriceRevision.revision_number)"
    )


class FuelPriceRevision(RateRevision):
    __tablename__ = "fuel_price_revisions"
    __table_args__ = (UniqueConstraint("fuel_type_id", "revision_number", name="uq_fuel_price_revisions_number"),)

    fuel_type_id: Mapped[str] = mapped_column(ForeignKey("fuel_types.id", ondelete="CASCADE"), nullable=False, index=True)
    fuel_type: Mapped[FuelType] = relationship(back_populates="revisions")

