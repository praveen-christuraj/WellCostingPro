"""Typed API contracts for Vendors and PO/SO Orders (Master Data Management)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VendorStatus = Literal["active", "inactive", "blocked"]
OrderType = Literal["PO", "SO", "Callout", "Others"]
OrderStatus = Literal["open", "closed", "cancelled"]
DocumentKind = Literal[
    "po_copy", "signed_copy", "amendment_copy", "specification", "correspondence", "other"
]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class VendorCreate(BaseModel):
    vendor_code: str = Field(min_length=1, max_length=50)
    vendor_name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=80)
    contact_person: str = Field(default="", max_length=150)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=60)
    website: str = Field(default="", max_length=255)
    country: str = Field(default="", max_length=100)
    tax_registration_no: str = Field(default="", max_length=60)
    address: str = Field(default="", max_length=500)
    status: VendorStatus = "active"
    credit_terms_days: int | None = Field(default=None, ge=0, le=365)
    description: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "vendor_code", "vendor_name", "category", "contact_person", "email", "phone",
        "website", "country", "tax_registration_no", "address", "description",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class VendorUpdate(BaseModel):
    vendor_code: str | None = Field(default=None, min_length=1, max_length=50)
    vendor_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    contact_person: str | None = Field(default=None, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=60)
    website: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=100)
    tax_registration_no: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=500)
    status: VendorStatus | None = None
    credit_terms_days: int | None = Field(default=None, ge=0, le=365)
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "vendor_code", "vendor_name", "category", "contact_person", "email", "phone",
        "website", "country", "tax_registration_no", "address", "description",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class VendorOut(BaseModel):
    id: str
    vendor_code: str
    vendor_name: str
    category: str
    contact_person: str
    email: str
    phone: str
    website: str
    country: str
    tax_registration_no: str
    address: str
    status: VendorStatus
    credit_terms_days: int | None = None
    description: str
    order_count: int = 0
    document_count: int = 0
    latest_order_date: date | None = None
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class VendorOption(BaseModel):
    id: str
    vendor_code: str
    vendor_name: str
    status: VendorStatus
    order_count: int = 0
    label: str


class OrderCreate(BaseModel):
    order_number: str = Field(min_length=1, max_length=100)
    order_type: OrderType = "PO"
    vendor_id: str = Field(min_length=1, max_length=36)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus = "open"
    description: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_number", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderUpdate(BaseModel):
    order_number: str | None = Field(default=None, min_length=1, max_length=100)
    order_type: OrderType | None = None
    vendor_id: str | None = Field(default=None, min_length=1, max_length=36)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus | None = None
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_number", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderAmendmentCreate(BaseModel):
    """A new revision of an existing order. The server assigns the revision number."""

    revision_note: str = Field(min_length=1, max_length=500)
    order_type: OrderType | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus | None = None
    description: str | None = Field(default=None, max_length=500)
    copy_documents: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("revision_note", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderOut(BaseModel):
    id: str
    order_number: str
    order_type: OrderType
    vendor_id: str
    vendor_code: str
    vendor_name: str
    vendor_status: VendorStatus
    revision_number: int
    is_current: bool
    revision_note: str
    parent_order_id: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus
    description: str
    document_count: int = 0
    revision_count: int = 1
    is_expired: bool = False
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrderRevisionOut(BaseModel):
    id: str
    revision_number: int
    is_current: bool
    revision_note: str
    issue_date: date | None = None
    status: OrderStatus
    document_count: int = 0
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class DocumentUpdate(BaseModel):
    document_kind: DocumentKind | None = None
    label: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("label", "notes", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class DocumentOut(BaseModel):
    id: str
    order_id: str
    order_number: str
    file_name: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    document_kind: DocumentKind
    label: str
    notes: str
    revision_number: int
    uploaded_by_name: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadItem(BaseModel):
    file_name: str
    order_number: str = ""
    revision_number: int | None = None
    document_id: str | None = None
    accepted: bool
    message: str


class DocumentUploadResult(BaseModel):
    uploaded_count: int
    rejected_count: int
    items: list[DocumentUploadItem]


class VendorPoCount(BaseModel):
    key: str
    label: str
    count: int


class VendorPoTopVendor(BaseModel):
    vendor_id: str
    vendor_code: str
    vendor_name: str
    order_count: int
    document_count: int


class VendorPoOverview(BaseModel):
    vendors_active: int
    vendors_inactive: int
    vendors_blocked: int
    vendors_deleted: int
    orders_active: int
    orders_amendments: int
    orders_deleted: int
    orders_by_type: list[VendorPoCount]
    orders_by_status: list[VendorPoCount]
    documents_active: int
    documents_deleted: int
    storage_bytes: int
    top_vendors: list[VendorPoTopVendor]
