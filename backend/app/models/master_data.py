"""Tenant-scoped, column-wise master data records with soft deletion."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class MasterDataRecord(Base):
    """Common lifecycle columns shared by each typed master-data table."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class UnitOfMeasurement(MasterDataRecord):
    """Unit of measurement, e.g. metre (M) or barrel (BBL)."""

    __tablename__ = "uom"
    __table_args__ = (UniqueConstraint("organization_id", "unit_code", name="uq_uom_org_code"),)

    unit_code: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_name: Mapped[str] = mapped_column(String(150), nullable=False)
    unit_symbol: Mapped[str] = mapped_column(String(50), nullable=False)


class Currency(MasterDataRecord):
    """Currency code, name, and display symbol."""

    __tablename__ = "currencies"
    __table_args__ = (UniqueConstraint("organization_id", "currency_code", name="uq_currencies_org_code"),)

    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    currency_name: Mapped[str] = mapped_column(String(100), nullable=False)
    currency_symbol: Mapped[str] = mapped_column(String(20), nullable=False)


class Phase(MasterDataRecord):
    """Well-planning or drilling phase."""

    __tablename__ = "phases"
    __table_args__ = (UniqueConstraint("organization_id", "phase_code", name="uq_phases_org_code"),)

    phase_code: Mapped[str] = mapped_column(String(50), nullable=False)
    phase_name: Mapped[str] = mapped_column(String(150), nullable=False)


class HoleSection(MasterDataRecord):
    """Drilled hole section."""

    __tablename__ = "hole_sections"
    __table_args__ = (UniqueConstraint("organization_id", "section_code", name="uq_hole_sections_org_code"),)

    section_code: Mapped[str] = mapped_column(String(50), nullable=False)
    section_name: Mapped[str] = mapped_column(String(150), nullable=False)


class Activity(MasterDataRecord):
    """Standardized well activity."""

    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("organization_id", "activity_code", name="uq_activities_org_code"),)

    activity_code: Mapped[str] = mapped_column(String(50), nullable=False)
    activity_name: Mapped[str] = mapped_column(String(150), nullable=False)
