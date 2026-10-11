"""Tenant-scoped rigs, wells, and well configuration.

A rig owns wells; each well may carry a depth/phase configuration.  The
configuration rows are replaced as a single audited draft, while rigs and
wells use the common soft-delete lifecycle.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
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
from app.models.master_data import HoleSection, Phase


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class RigWellRecord(Base):
    """Typed common lifecycle columns for business records in this module."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )


class Rig(RigWellRecord):
    """A workspace rig. Rig codes are unique within the workspace."""

    __tablename__ = "rigs"
    __table_args__ = (
        UniqueConstraint("organization_id", "rig_code", name="uq_rigs_org_code"),
        Index("ix_rigs_org_deleted", "organization_id", "is_deleted"),
    )

    rig_code: Mapped[str] = mapped_column(String(50), nullable=False)
    rig_name: Mapped[str] = mapped_column(String(200), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)

    wells: Mapped[list["Well"]] = relationship(
        back_populates="rig", lazy="noload", passive_deletes=True
    )


class Well(RigWellRecord):
    """A well assigned to exactly one rig."""

    __tablename__ = "wells"
    __table_args__ = (
        UniqueConstraint("organization_id", "well_code", name="uq_wells_org_code"),
        CheckConstraint("status IN ('active', 'completed')", name="ck_wells_status"),
        CheckConstraint("config_status IN ('draft', 'configured')", name="ck_wells_config_status"),
        CheckConstraint("depth_unit IN ('m', 'ft')", name="ck_wells_depth_unit"),
        Index("ix_wells_org_rig", "organization_id", "rig_id"),
        Index("ix_wells_org_deleted", "organization_id", "is_deleted"),
    )

    rig_id: Mapped[str] = mapped_column(
        ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    well_code: Mapped[str] = mapped_column(String(50), nullable=False)
    well_name: Mapped[str] = mapped_column(String(200), nullable=False)
    well_location: Mapped[str] = mapped_column(String(300), nullable=False)
    block: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(String(500), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)
    config_status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False
    )
    depth_unit: Mapped[str] = mapped_column(String(10), default="m", server_default="m", nullable=False)

    rig: Mapped[Rig] = relationship(back_populates="wells", lazy="joined")
    sections: Mapped[list["WellSection"]] = relationship(
        back_populates="well",
        lazy="selectin",
        order_by="WellSection.sort_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sub_activities: Mapped[list["WellSubActivity"]] = relationship(
        "WellSubActivity", back_populates="well", lazy="noload", passive_deletes=True
    )


class WellSection(Base):
    """A hole-section interval in a well's configuration."""

    __tablename__ = "well_sections"
    __table_args__ = (
        Index("ix_well_sections_org_well", "organization_id", "well_id"),
        UniqueConstraint("well_id", "sort_order", name="uq_well_sections_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hole_section_id: Mapped[str] = mapped_column(
        ForeignKey("hole_sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_depth: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    to_depth: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    well: Mapped[Well] = relationship(back_populates="sections", lazy="joined")
    hole_section: Mapped[HoleSection] = relationship(lazy="joined")
    phases: Mapped[list["WellPhase"]] = relationship(
        back_populates="section",
        lazy="selectin",
        order_by="WellPhase.sort_order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class WellPhase(Base):
    """A master-data phase and planned day count within one hole section."""

    __tablename__ = "well_phases"
    __table_args__ = (
        Index("ix_well_phases_org_section", "organization_id", "section_id"),
        UniqueConstraint("section_id", "sort_order", name="uq_well_phases_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[str] = mapped_column(
        ForeignKey("well_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase_id: Mapped[str] = mapped_column(
        ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    days: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    section: Mapped[WellSection] = relationship(back_populates="phases", lazy="joined")
    phase: Mapped[Phase] = relationship(lazy="joined")
