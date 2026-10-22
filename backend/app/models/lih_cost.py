"""LIH Cost Register persistence models.

The Lost In Hole (LIH) register is a manual, well-scoped register inside Daily
Cost Management. A *LIH day* is one rig / well / AFE / date record. The day is
an aggregate: its items are edited as one worksheet and saved together in a
single atomic request, so a user never has to add them one call at a time.
Every item carries its own equipment dimensions (OD, ID, fish-neck OD and
length, connection, serial number and total length) as ordinary typed columns.

Two columns keep the aggregate honest:

* ``revision`` on the day is bumped on every save, so a worksheet opened in one
  browser cannot silently overwrite items saved from another,
* ``source`` on the item records how the row was created (manual entry,
  duplicated from another item, or imported), which keeps bulk imports and
  duplicated rows distinguishable in the register and the audit trail.

LIH cost is deliberately accounted outside the AFE estimate:

* ``total_cost`` on the day is the sum of its item totals,
* the day is reported separately from Services / Consumables / Tangibles and
  Other Expenses,
* cost analysis, the daily cost report and the well cost report add it to the
  actual cost **and** deduct it explicitly from the AFE amount.

An LIH day may be filed against one AFE so a multi-AFE well can deduct the cost
from the right budget. The AFE is resolved from the well when the client does
not send one, and the day's currency is the AFE's standard currency (or the
workspace default currency for a well without an AFE), so LIH values join the
AFE comparison without any conversion.

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.rig_well import now, uid

LIH_MAX_ITEM_DESCRIPTION = 300
LIH_MAX_SERIAL_NUMBER = 100
LIH_MAX_CONNECTION = 100
LIH_MAX_REMARKS = 500
LIH_LINE_SOURCES = ("manual", "duplicate", "import")


class LihCostEntry(Base):
    """One date's LIH register for a rig and well (and its AFE, when known)."""

    __tablename__ = "lih_cost_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "well_id", "cost_date", name="uq_lih_cost_entries_org_well_date"),
        CheckConstraint("total_cost >= 0", name="ck_lih_cost_entries_total"),
        CheckConstraint("line_count >= 0", name="ck_lih_cost_entries_line_count"),
        CheckConstraint("revision >= 0", name="ck_lih_cost_entries_revision"),
        Index("ix_lih_cost_entries_org_rig", "organization_id", "rig_id"),
        Index("ix_lih_cost_entries_org_afe_date", "organization_id", "afe_id", "cost_date"),
        Index("ix_lih_cost_entries_org_deleted_date", "organization_id", "is_deleted", "cost_date"),
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
    # Optional only for a well whose AFE is not created yet. Once an AFE is
    # assigned it is the budget this LIH cost is deducted from.
    afe_id: Mapped[str | None] = mapped_column(
        ForeignKey("afes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    afe_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    afe_name_snapshot: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    cost_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The AFE standard currency (workspace default when the well has no AFE),
    # so LIH totals join the AFE comparison without conversion.
    currency: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    # Bumped on every worksheet save; a stale client is rejected instead of
    # overwriting items somebody else has saved in the meantime.
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    rig: Mapped["Rig"] = relationship("Rig", lazy="joined")
    well: Mapped["Well"] = relationship("Well", lazy="joined")
    afe: Mapped["Afe | None"] = relationship("Afe", lazy="joined")
    lines: Mapped[list["LihCostLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="LihCostLine.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )


class LihCostLine(Base):
    """One LIH item under a LIH day.

    ``item_description``, ``no_of_units`` and ``unit_cost`` are mandatory; the
    server computes ``total_cost`` as units × unit cost. The remaining columns
    are optional equipment details kept as typed measurements and text.
    ``source`` is how the row entered the register (manual, duplicate, import)
    and ``sort_order`` is its position on the day's worksheet.
    """

    __tablename__ = "lih_cost_lines"
    __table_args__ = (
        CheckConstraint("LENGTH(TRIM(item_description)) > 0", name="ck_lih_cost_lines_description"),
        CheckConstraint("no_of_units >= 0", name="ck_lih_cost_lines_units"),
        CheckConstraint("unit_cost >= 0", name="ck_lih_cost_lines_unit_cost"),
        CheckConstraint("total_cost >= 0", name="ck_lih_cost_lines_total"),
        CheckConstraint(
            "od_size IS NULL OR od_size >= 0", name="ck_lih_cost_lines_od"
        ),
        CheckConstraint(
            "id_size IS NULL OR id_size >= 0", name="ck_lih_cost_lines_id"
        ),
        CheckConstraint(
            "fish_neck_od IS NULL OR fish_neck_od >= 0", name="ck_lih_cost_lines_fish_neck_od"
        ),
        CheckConstraint(
            "fish_neck_length IS NULL OR fish_neck_length >= 0", name="ck_lih_cost_lines_fish_neck_length"
        ),
        CheckConstraint("length IS NULL OR length >= 0", name="ck_lih_cost_lines_length"),
        CheckConstraint(
            "source IN ('manual', 'duplicate', 'import')", name="ck_lih_cost_lines_source"
        ),
        Index("ix_lih_cost_lines_entry_order", "entry_id", "sort_order"),
        Index("ix_lih_cost_lines_org_description", "organization_id", "item_description"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("lih_cost_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_description: Mapped[str] = mapped_column(String(LIH_MAX_ITEM_DESCRIPTION), nullable=False)
    od_size: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    id_size: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    fish_neck_od: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    fish_neck_length: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    serial_number: Mapped[str] = mapped_column(String(LIH_MAX_SERIAL_NUMBER), default="", server_default="", nullable=False)
    connection: Mapped[str] = mapped_column(String(LIH_MAX_CONNECTION), default="", server_default="", nullable=False)
    length: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    no_of_units: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    unit: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    remarks: Mapped[str] = mapped_column(String(LIH_MAX_REMARKS), default="", server_default="", nullable=False)
    # manual | duplicate | import — how this row was captured.
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    entry: Mapped[LihCostEntry] = relationship(back_populates="lines", lazy="select")
