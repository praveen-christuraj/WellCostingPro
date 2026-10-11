"""Tenant-scoped well sub activities.

A sub activity belongs to one well and references an active Activity from the
workspace's Master Data register. Its code is unique within that well only.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.master_data import Activity
from app.models.rig_well import Well


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class WellSubActivity(Base):
    """A well-scoped task classified under a Master Data Activity."""

    __tablename__ = "well_sub_activities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "well_id", "sub_activity_code",
            name="uq_well_sub_activities_org_well_code",
        ),
        Index("ix_well_sub_activities_org_deleted", "organization_id", "is_deleted"),
        Index("ix_well_sub_activities_org_activity", "organization_id", "activity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[str] = mapped_column(
        ForeignKey("wells.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sub_activity_code: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_activity_name: Mapped[str] = mapped_column(String(150), nullable=False)
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    responsible_party: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    well: Mapped[Well] = relationship(back_populates="sub_activities", lazy="joined")
    activity: Mapped[Activity] = relationship(lazy="joined")
