"""Column-wise NDT Inspection register records for Daily Cost Management."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.rig_well import now, uid


class NdtInspection(Base):
    """One separately listed inspection line saved under a rig, well and scope."""

    __tablename__ = "ndt_inspections"
    __table_args__ = (
        CheckConstraint("scope IN ('drilling', 'completion')", name="ck_ndt_inspections_scope"),
        CheckConstraint("LENGTH(TRIM(description)) > 0", name="ck_ndt_inspections_description"),
        CheckConstraint("quantity_received >= 0", name="ck_ndt_inspections_received"),
        CheckConstraint("quantity_consumed >= 0", name="ck_ndt_inspections_consumed"),
        CheckConstraint("quantity_backloaded_good >= 0", name="ck_ndt_inspections_backloaded_good"),
        CheckConstraint("quantity_backloaded_bad >= 0", name="ck_ndt_inspections_backloaded_bad"),
        Index("ix_ndt_inspections_org_scope", "organization_id", "rig_id", "well_id", "scope"),
        Index("ix_ndt_inspections_org_deleted_created", "organization_id", "is_deleted", "created_at"),
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
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    quantity_consumed: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    quantity_backloaded_good: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    quantity_backloaded_bad: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    remarks: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    rig: Mapped["Rig"] = relationship("Rig", lazy="joined")
    well: Mapped["Well"] = relationship("Well", lazy="joined")
