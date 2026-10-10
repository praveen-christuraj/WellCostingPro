"""Tenant-scoped Vendors, PO/SO orders and the documents attached to them.

This is the commercial side of Master Data Management: vendors are added
first, every PO/SO order belongs to one vendor, and each order keeps its own
amendment chain plus the scanned copies the user attaches for later reference.
No prices or values are stored — the attached document *is* the record.

Everything follows the module conventions: column-wise tables (never a JSON
payload column), the shared ``MasterDataRecord`` lifecycle columns, per
workspace uniqueness, and soft deletion with restore/purge.
"""

from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.master_data import MasterDataRecord

VENDOR_STATUSES = ("active", "inactive", "blocked")
ORDER_TYPES = ("PO", "SO", "Callout", "Others")
ORDER_STATUSES = ("open", "closed", "cancelled")
DOCUMENT_KINDS = (
    "po_copy",
    "signed_copy",
    "amendment_copy",
    "specification",
    "correspondence",
    "other",
)
VENDOR_CATEGORIES = (
    "Drilling",
    "Completions",
    "Well Services",
    "Cementing",
    "Mud & Chemicals",
    "Casing & Tubulars",
    "Bits & Tools",
    "Logistics & Transport",
    "Equipment Rental",
    "Catering & Camps",
    "Inspection & Testing",
    "Engineering Services",
    "Other",
)


class Vendor(MasterDataRecord):
    """A supplier the workspace buys from. Parents every PO/SO order."""

    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("organization_id", "vendor_code", name="uq_vendors_org_code"),)

    vendor_code: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="", server_default="")
    contact_person: Mapped[str] = mapped_column(String(150), default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(60), default="", server_default="")
    website: Mapped[str] = mapped_column(String(255), default="", server_default="")
    country: Mapped[str] = mapped_column(String(100), default="", server_default="")
    tax_registration_no: Mapped[str] = mapped_column(String(60), default="", server_default="")
    address: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    credit_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )


class PurchaseOrder(MasterDataRecord):
    """One PO/SO issue: revision 0 is the original, later rows are amendments.

    ``parent_order_id`` keeps the lineage of an amendment chain, ``is_current``
    marks the revision a user should quote today, and the pair
    (order_number, revision_number) is unique per workspace.
    """

    __tablename__ = "po_so_orders"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "order_number",
            "revision_number",
            name="uq_po_so_orders_org_number_revision",
        ),
    )

    order_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    order_type: Mapped[str] = mapped_column(String(20), default="PO", server_default="PO", index=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("po_so_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    revision_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)

    vendor: Mapped[Vendor] = relationship(back_populates="orders", lazy="joined")
    documents: Mapped[list["OrderDocument"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderDocument(MasterDataRecord):
    """A file attached to a PO/SO revision, stored with its bytes in-database.

    The workspace database is the durable store (Render/Compose filesystems are
    ephemeral), so the payload lives in a deferred ``content`` column and the
    metadata stays in ordinary typed columns. ``description`` is the note the
    user writes about the file.
    """

    __tablename__ = "po_so_documents"

    order_id: Mapped[str] = mapped_column(
        ForeignKey("po_so_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120), default="application/octet-stream", server_default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", server_default="")
    document_kind: Mapped[str] = mapped_column(String(30), default="po_copy", server_default="po_copy")
    label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    revision_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by_name: Mapped[str] = mapped_column(String(160), default="", server_default="")

    order: Mapped[PurchaseOrder] = relationship(back_populates="documents")
