"""Tenant-scoped Mud Cost Analysis records.

A daily entry is locked to one rig, well, section snapshot and date. The well/date
unique key enforces the one-entry-per-well-per-day rule, even for soft-deleted
records. Section configuration rows are rebuilt when a well plan is edited, so
``section_id`` is retained as a typed snapshot key (without a cascading FK); the
master Hole Section remains protected by a restrictive FK and all section labels
and depth bounds are snapshotted for historical reconciliation.

Every named quantity is a row in ``mud_cost_entry_lines`` with typed columns.
No serialized or JSON payload is persisted.
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
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.mud_cost import MUD_COST_DB_CATEGORY_KEYS, MUD_COST_LINE_CODES
from app.models.rig_well import now, uid


def _in_values(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class MudCostEntry(Base):
    """One daily material-balance capture for a well and its mud section."""

    __tablename__ = "mud_cost_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "well_id", "entry_date", name="uq_mud_cost_entries_org_well_date"),
        CheckConstraint("section_scope IN ('drilling', 'completion')", name="ck_mud_cost_entries_section_scope"),
        CheckConstraint("section_from_depth >= 0 AND section_to_depth >= section_from_depth", name="ck_mud_cost_entries_section_depth"),
        Index("ix_mud_cost_entries_org_rig_date", "organization_id", "rig_id", "entry_date"),
        Index("ix_mud_cost_entries_org_section_date", "organization_id", "section_id", "entry_date"),
        Index("ix_mud_cost_entries_org_deleted_date", "organization_id", "is_deleted", "entry_date"),
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
    # Snapshot key only: Rig & Well Management replaces well_sections rows on a saved draft.
    section_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    hole_section_id: Mapped[str] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    section_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    section_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    section_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    section_from_depth: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    section_to_depth: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    rig: Mapped["Rig"] = relationship("Rig", lazy="joined")
    well: Mapped["Well"] = relationship("Well", lazy="joined")
    hole_section: Mapped["HoleSection"] = relationship("HoleSection", lazy="joined")
    lines: Mapped[list["MudCostEntryLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="MudCostEntryLine.sort_order",
        lazy="selectin",
        passive_deletes=True,
    )


class MudCostEntryLine(Base):
    """One configured stock, receipt, addition, loss or other quantity + remark."""

    __tablename__ = "mud_cost_entry_lines"
    __table_args__ = (
        UniqueConstraint("entry_id", "line_code", name="uq_mud_cost_entry_lines_entry_code"),
        CheckConstraint(_in_values("line_code", MUD_COST_LINE_CODES), name="ck_mud_cost_entry_lines_code"),
        CheckConstraint(_in_values("category", MUD_COST_DB_CATEGORY_KEYS), name="ck_mud_cost_entry_lines_category"),
        CheckConstraint("amount >= 0", name="ck_mud_cost_entry_lines_amount"),
        CheckConstraint("amount = 0 OR LENGTH(TRIM(remarks)) >= 3", name="ck_mud_cost_entry_lines_remarks"),
        Index("ix_mud_cost_entry_line_entry_order", "entry_id", "sort_order"),
        Index("ix_mud_cost_entry_line_org_category", "organization_id", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("mud_cost_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_code: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    line_label: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"), server_default="0", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    entry: Mapped[MudCostEntry] = relationship(back_populates="lines", lazy="select")
