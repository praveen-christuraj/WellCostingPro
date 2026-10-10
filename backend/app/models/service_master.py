"""Tenant-scoped Services register for Master Data Management."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.master_data import MasterDataRecord

SERVICE_CATEGORIES = ("Drilling Services", "Completion Services")
SERVICE_PROVIDER_TYPES = ("In House Services", "Third Party Services")


class Service(MasterDataRecord):
    """A reusable drilling or completion service and its delivery provider."""

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("organization_id", "service_code", name="uq_services_org_code"),
        CheckConstraint(
            "service_category IN ('Drilling Services', 'Completion Services')",
            name="ck_services_category",
        ),
        CheckConstraint(
            "provider_type IN ('In House Services', 'Third Party Services')",
            name="ck_services_provider_type",
        ),
        CheckConstraint(
            "(provider_type = 'Third Party Services' AND vendor_id IS NOT NULL) OR "
            "provider_type = 'In House Services'",
            name="ck_services_provider_vendor",
        ),
        # Service names are unique per workspace regardless of letter case, including
        # soft-deleted records, so restoring a record can never create a collision.
        Index(
            "uq_services_org_name_ci",
            "organization_id",
            text("lower(service_name)"),
            unique=True,
        ),
    )

    service_code: Mapped[str] = mapped_column(String(50), nullable=False)
    service_name: Mapped[str] = mapped_column(String(200), nullable=False)
    service_category: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    vendor: Mapped["Vendor | None"] = relationship("Vendor", lazy="joined")
