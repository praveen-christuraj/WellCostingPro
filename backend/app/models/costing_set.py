"""User-scoped shortcuts for recurring costing line items.

A set stores only references to active catalogue records plus display snapshots.
The polymorphic reference is intentionally not a foreign key: purging an optional
master-data item must not be blocked by somebody's shortcut. Stale items remain
visible as unavailable and are skipped when the set is applied.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.entities import now


SET_GROUPS = ("services", "tangibles", "consumables")
SET_ITEM_KINDS = ("service", "tangible", "mud_chemical", "cement_additive", "fuel", "drill_bit")


def uid() -> str:
    return str(uuid4())


class UserCostingSet(Base):
    """A named, private-to-one-user collection of reusable catalogue items."""

    __tablename__ = "user_costing_sets"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "item_group", "name_key", name="uq_user_costing_sets_owner_name"),
        CheckConstraint("item_group IN ('services', 'tangibles', 'consumables')", name="ck_user_costing_sets_group"),
        Index("ix_user_costing_sets_org_user", "organization_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_key: Mapped[str] = mapped_column(String(100), nullable=False)
    item_group: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)

    items: Mapped[list["UserCostingSetItem"]] = relationship(
        back_populates="costing_set",
        cascade="all, delete-orphan",
        order_by="UserCostingSetItem.sort_order",
        passive_deletes=True,
    )


class UserCostingSetItem(Base):
    """One typed catalogue reference inside a named user shortcut."""

    __tablename__ = "user_costing_set_items"
    __table_args__ = (
        UniqueConstraint("set_id", "item_kind", "item_id", name="uq_user_costing_set_items_item"),
        CheckConstraint(
            "item_kind IN ('service', 'tangible', 'mud_chemical', 'cement_additive', 'fuel', 'drill_bit')",
            name="ck_user_costing_set_items_kind",
        ),
        Index("ix_user_costing_set_items_org_set", "organization_id", "set_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    set_id: Mapped[str] = mapped_column(
        ForeignKey("user_costing_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    costing_set: Mapped[UserCostingSet] = relationship(back_populates="items")
