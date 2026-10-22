"""Fuel Cost Register persistence models (Daily Cost Management).

The Fuel Cost Register is a **rig-scoped** daily AGO (Automotive Gas Oil)
ledger. It is deliberately independent of wells, AFEs and the daily cost sheet:
a rig consumes fuel whether or not a well is being drilled, and the same rig can
serve several wells over its life.

A *fuel day* is one rig and one date (unique per workspace). It records:

* the rig engines' AGO consumption,
* gas consumption — recorded in litres for information and never mixed into AGO,
* the physical opening and actual closing stock,
* daily receipts,
* the company-wise AGO consumption lines. Every line belongs to a registered
  company (usually a vendor from Master Data) and, optionally, to one of that
  company's own categories, so consumption is classified by company and by
  category as well as in total.

The material balance is derived, not stored:

    opening stock
  + opening adjustment (only when a day's opening was overridden)
  + receipts
  - AGO consumption (rig engines + company lines)
  = book closing stock
  actual closing stock (the physical count)
  - book closing stock
  = closing adjustment

Opening stock is captured once on the rig's first day. Every later day carries
the preceding day's actual closing stock forward; the Override opening stock
action is the only way to break that chain, and the difference is reported as an
opening adjustment. The actual closing stock becomes the next day's opening.

Everything is column-wise: companies, categories and consumption lines are typed
tables and no JSON payload is persisted.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.rig_well import now, uid

FUEL_MAX_COMPANY_NAME = 200
FUEL_MAX_CATEGORY_NAME = 120
FUEL_MAX_REMARKS = 500
FUEL_MAX_DAY_REMARKS = 1000
FUEL_COMPANY_SOURCES = ("vendor", "manual", "import")
FUEL_LINE_SOURCES = ("manual", "import")


class FuelCompany(Base):
    """A company that consumes fuel from a rig (usually linked to a vendor).

    ``is_default`` marks the companies that use fuel every day. The consumption
    dialog pre-lists them so a daily entry needs only the litres, while all other
    companies are still selectable one by one.

    The row is soft-deleted and restorable; historical consumption lines keep
    their own company-name snapshot so a removed company never rewrites history.
    """

    __tablename__ = "fuel_companies"
    __table_args__ = (
        UniqueConstraint("organization_id", "company_name", name="uq_fuel_companies_org_name"),
        CheckConstraint(
            "source IN ('vendor', 'manual', 'import')", name="ck_fuel_companies_source"
        ),
        Index("ix_fuel_companies_org_deleted", "organization_id", "is_deleted"),
        Index("ix_fuel_companies_org_default", "organization_id", "is_default"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(FUEL_MAX_COMPANY_NAME), nullable=False)
    # Master Data vendor behind the company; the code is snapshotted so an
    # archived vendor never erases who burnt the fuel.
    vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    vendor_code_snapshot: Mapped[str] = mapped_column(
        String(50), default="", server_default="", nullable=False
    )
    # Part of the user's saved daily set: listed in one click when a day opens.
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual", nullable=False
    )
    remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    categories: Mapped[list["FuelCompanyCategory"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="FuelCompanyCategory.category_name",
        lazy="selectin",
        passive_deletes=True,
    )


class FuelCompanyCategory(Base):
    """One sub-category under a fuel company, created from the register itself.

    Consumption is accounted per category as well as per company, so a company
    with two rig crews or two cost centres can be split without a second company.
    """

    __tablename__ = "fuel_company_categories"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "category_name", name="uq_fuel_company_categories_company_name"
        ),
        Index("ix_fuel_company_categories_org", "organization_id", "company_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("fuel_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_name: Mapped[str] = mapped_column(String(FUEL_MAX_CATEGORY_NAME), nullable=False)
    remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    company: Mapped["FuelCompany"] = relationship(back_populates="categories", lazy="select")


class FuelCostEntry(Base):
    """One rig's fuel day: AGO, gas, stock, receipts and company consumption."""

    __tablename__ = "fuel_cost_entries"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "rig_id", "cost_date", name="uq_fuel_cost_entries_org_rig_date"
        ),
        CheckConstraint("rig_engine_consumption >= 0", name="ck_fuel_cost_entries_engine"),
        CheckConstraint("gas_consumption >= 0", name="ck_fuel_cost_entries_gas"),
        CheckConstraint(
            "opening_stock IS NULL OR opening_stock >= 0", name="ck_fuel_cost_entries_opening"
        ),
        CheckConstraint("receipt_quantity >= 0", name="ck_fuel_cost_entries_receipt"),
        CheckConstraint(
            "closing_stock IS NULL OR closing_stock >= 0", name="ck_fuel_cost_entries_closing"
        ),
        CheckConstraint("revision >= 0", name="ck_fuel_cost_entries_revision"),
        Index("ix_fuel_cost_entries_org_date", "organization_id", "cost_date"),
        Index(
            "ix_fuel_cost_entries_org_deleted_date", "organization_id", "is_deleted", "cost_date"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rig_id: Mapped[str] = mapped_column(
        ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rig_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    rig_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    cost_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # AGO burnt by the rig engines themselves.
    rig_engine_consumption: Mapped[Decimal] = mapped_column(
        Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False
    )
    rig_engine_remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )
    # Gas is recorded in litres for information; it never joins the AGO balance.
    gas_consumption: Mapped[Decimal] = mapped_column(
        Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False
    )
    gas_remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )

    # Physical anchor: set on the rig's first day or through an authorised
    # override; otherwise the previous day's actual closing carries in.
    opening_stock: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    opening_overridden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    opening_remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )

    receipt_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False
    )
    receipt_remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )

    # Physical count at the end of the day; empty accepts the book closing.
    closing_stock: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    closing_remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )

    remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_DAY_REMARKS), default="", server_default="", nullable=False
    )
    revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    rig: Mapped["Rig"] = relationship(lazy="joined")
    lines: Mapped[list["FuelCostCompanyLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="FuelCostCompanyLine.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )


class FuelCostCompanyLine(Base):
    """One company's (and optionally category's) AGO consumption on a fuel day."""

    __tablename__ = "fuel_cost_company_lines"
    __table_args__ = (
        UniqueConstraint(
            "entry_id",
            "company_id",
            "category_id",
            name="uq_fuel_cost_company_lines_entry_company_category",
        ),
        CheckConstraint("litres >= 0", name="ck_fuel_cost_company_lines_litres"),
        CheckConstraint(
            "source IN ('manual', 'import')", name="ck_fuel_cost_company_lines_source"
        ),
        Index("ix_fuel_cost_company_lines_entry_order", "entry_id", "sort_order"),
        Index(
            "ix_fuel_cost_company_lines_org_company_date",
            "organization_id",
            "company_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("fuel_cost_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("fuel_companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    company_name_snapshot: Mapped[str] = mapped_column(String(FUEL_MAX_COMPANY_NAME), nullable=False)
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("fuel_company_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_name_snapshot: Mapped[str] = mapped_column(
        String(FUEL_MAX_CATEGORY_NAME), default="", server_default="", nullable=False
    )
    litres: Mapped[Decimal] = mapped_column(
        Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False
    )
    remarks: Mapped[str] = mapped_column(
        String(FUEL_MAX_REMARKS), default="", server_default="", nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    entry: Mapped["FuelCostEntry"] = relationship(back_populates="lines", lazy="select")
    company: Mapped["FuelCompany"] = relationship(lazy="joined")
    category: Mapped["FuelCompanyCategory"] = relationship(lazy="select")
