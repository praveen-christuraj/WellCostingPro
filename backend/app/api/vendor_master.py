"""Tenant-scoped Vendors and PO/SO Orders APIs (Master Data Management).

Vendors are maintained first; each PO/SO order belongs to one vendor, keeps an
amendment chain (revision 0 is the original, later revisions are amendments) and
holds the scanned copies the user attaches. No monetary values are stored — the
attached document is the source of truth, so document custody (upload, download,
replace, remove, restore) is audited like any other change.

Attachments are kept in the workspace database (``po_so_documents.content``)
because the deployed API filesystem is ephemeral; metadata stays column-wise.
"""

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Current, Db, require
from app.core.config import get_settings
from app.models import AuditLog
from app.models.vendor_master import (
    DOCUMENT_KINDS,
    ORDER_STATUSES,
    ORDER_TYPES,
    VENDOR_STATUSES,
    OrderDocument,
    PurchaseOrder,
    Vendor,
)
from app.schemas.master_data import (
    MasterDataActivity,
    MasterDataBulkActionResponse,
    MasterDataIDs,
    MasterDataImportRequest,
    MasterDataImportResponse,
)
from app.schemas.vendor_master import (
    DocumentOut,
    DocumentUpdate,
    DocumentUploadItem,
    DocumentUploadResult,
    OrderAmendmentCreate,
    OrderCreate,
    OrderOut,
    OrderRevisionOut,
    OrderUpdate,
    VendorCreate,
    VendorOption,
    VendorOut,
    VendorPoCount,
    VendorPoOverview,
    VendorPoTopVendor,
    VendorUpdate,
)
from app.services import audit

router = APIRouter(prefix="/master-data", tags=["Vendors & PO/SO Orders"])

VENDOR_LABEL = "Vendors"
ORDER_LABEL = "PO/SO Orders"
DOCUMENT_LABEL = "PO/SO Documents"

VENDOR_ENTITY = "vendor"
ORDER_ENTITY = "po_so_order"
DOCUMENT_ENTITY = "po_so_document"
AUDIT_ENTITY_TYPES = (VENDOR_ENTITY, ORDER_ENTITY, DOCUMENT_ENTITY)

# Documents are the payload of this module, so the accepted families are explicit.
ALLOWED_DOCUMENT_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf",
    ".png", ".jpg", ".jpeg", ".msg", ".eml",
)
DOCUMENT_KIND_LABELS = {
    "po_copy": "PO/SO copy",
    "signed_copy": "Signed copy",
    "amendment_copy": "Amendment copy",
    "specification": "Specification",
    "correspondence": "Correspondence",
    "other": "Other",
}

VENDOR_IMPORT_ALIASES = {
    "vendor_code": ("vendor_code", "code", "vendor code", "supplier_code"),
    "vendor_name": ("vendor_name", "name", "vendor name", "supplier_name"),
    "category": ("category", "vendor_category", "type"),
    "contact_person": ("contact_person", "contact", "contact person", "contact_name"),
    "email": ("email", "e_mail", "email_id"),
    "phone": ("phone", "mobile", "telephone", "contact_number"),
    "website": ("website", "web", "url"),
    "country": ("country",),
    "tax_registration_no": ("tax_registration_no", "tax_id", "tax_no", "gst_no", "vat_no", "registration_no"),
    "address": ("address", "location"),
    "status": ("status", "vendor_status"),
    "credit_terms_days": ("credit_terms_days", "credit_days", "payment_terms_days"),
    "description": ("description", "remarks", "notes", "desc"),
}

ORDER_IMPORT_ALIASES = {
    "order_number": ("order_number", "po_so_number", "po_number", "so_number", "number"),
    "order_type": ("order_type", "type", "po_type"),
    "vendor_code": ("vendor_code", "vendor", "supplier_code", "supplier"),
    "issue_date": ("issue_date", "effective_date", "po_date", "order_date", "date"),
    "expiry_date": ("expiry_date", "valid_until", "validity_date", "end_date"),
    "status": ("status", "order_status"),
    "description": ("description", "remarks", "notes", "scope", "desc"),
}

# Spreadsheet-friendly aliases, so an ERP dump imports without hand editing.
VENDOR_STATUS_ALIASES = {
    "active": "active", "a": "active", "enabled": "active", "approved": "active",
    "inactive": "inactive", "i": "inactive", "disabled": "inactive", "dormant": "inactive",
    "blocked": "blocked", "b": "blocked", "hold": "blocked", "on hold": "blocked",
    "on-hold": "blocked", "blacklisted": "blocked", "suspended": "blocked",
}
ORDER_TYPE_ALIASES = {
    "po": "PO", "purchase order": "PO", "purchase": "PO",
    "so": "SO", "service order": "SO", "service": "SO",
    "callout": "Callout", "call out": "Callout", "call-out": "Callout",
    "others": "Others", "other": "Others",
}
ORDER_STATUS_ALIASES = {
    "open": "open", "issued": "open", "active": "open", "in progress": "open",
    "closed": "closed", "complete": "closed", "completed": "closed", "done": "closed",
    "cancelled": "cancelled", "canceled": "cancelled", "void": "cancelled",
}

DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%d-%b-%Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M",
)
# `<ORDER NUMBER>_Rev3`, `<ORDER NUMBER>__3`, `<ORDER NUMBER> Rev 3`, `<ORDER NUMBER>_3`
REVISION_SUFFIX = re.compile(r"(?P<number>.+?)[\s_\-]*(?:rev(?:ision)?[\s_\-.]*)?(?P<revision>\d{1,3})$", re.IGNORECASE)


class MasterDataAction:
    """Action labels are centralized so audit summaries stay consistent."""

    CREATE = "create"
    UPDATE = "update"
    AMEND = "amend"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
    PERMANENT_DELETE = "permanent_delete"
    IMPORT = "import"
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_DOWNLOAD = "document_download"
    DOCUMENT_DELETE = "document_delete"
    DOCUMENT_RESTORE = "document_restore"
    DOCUMENT_PERMANENT_DELETE = "document_permanent_delete"


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This record conflicts with an existing workspace record") from error


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )


def _check_email(value: str) -> str:
    if not value:
        return ""
    try:
        return str(TypeAdapter(EmailStr).validate_python(value)).lower()
    except Exception as error:
        raise ValueError(f"'{value}' is not a valid e-mail address") from error


def _check_website(value: str) -> str:
    if not value:
        return ""
    candidate = value if re.match(r"^https?://", value, re.IGNORECASE) else f"https://{value}"
    if not re.match(r"^https?://[^\s/]+\.[^\s/]{2,}", candidate, re.IGNORECASE):
        raise ValueError(f"'{value}' is not a valid website address")
    return candidate


def _parse_import_date(value: Any) -> date | None:
    """Accept the date shapes people actually export from Excel and ERP lists."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d+(\.\d+)?", text):
        serial = float(text)
        if 1 < serial < 200000:  # Excel/Sheets day serial
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    parts = re.split(r"[-/. ]", text.split()[0])
    if len(parts) == 3:
        year, month, day = parts if len(parts[0]) == 4 else (parts[2], parts[1], parts[0])
        if len(year) == 2:
            year = f"20{year}" if int(year) < 50 else f"19{year}"
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date '{text}' (use YYYY-MM-DD or DD/MM/YYYY)")


def _normalize_import_row(row: dict[str, Any], aliases: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Map a spreadsheet header row onto this module's field names."""
    lowered = {str(key).strip().lower().replace(" ", "_").replace("-", "_"): value for key, value in row.items()}
    normalized: dict[str, Any] = {}
    for field, candidates in aliases.items():
        for candidate in candidates:
            value = lowered.get(candidate.replace(" ", "_"))
            if value not in (None, ""):
                normalized[field] = value
                break
    return normalized


# --------------------------------------------------------------------------- #
# Record lookups and output shaping
# --------------------------------------------------------------------------- #


def _vendor_or_404(db: Session, vendor_id: str, organization_id: str, *, include_deleted: bool = True) -> Vendor:
    statement = select(Vendor).where(Vendor.id == vendor_id, Vendor.organization_id == organization_id)
    if not include_deleted:
        statement = statement.where(Vendor.is_deleted.is_(False))
    vendor = db.scalar(statement)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found in this workspace")
    return vendor


def _order_or_404(db: Session, order_id: str, organization_id: str, *, include_deleted: bool = True) -> PurchaseOrder:
    statement = select(PurchaseOrder).where(
        PurchaseOrder.id == order_id, PurchaseOrder.organization_id == organization_id
    )
    if not include_deleted:
        statement = statement.where(PurchaseOrder.is_deleted.is_(False))
    order = db.scalar(statement)
    if order is None:
        raise HTTPException(status_code=404, detail="PO/SO order not found in this workspace")
    return order


def _document_or_404(db: Session, document_id: str, organization_id: str) -> OrderDocument:
    document = db.scalar(
        select(OrderDocument).where(
            OrderDocument.id == document_id, OrderDocument.organization_id == organization_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found in this workspace")
    return document


def _document_counts(db: Session, organization_id: str, order_ids: Iterable[str]) -> dict[str, int]:
    ids = [order_id for order_id in order_ids]
    if not ids:
        return {}
    rows = db.execute(
        select(OrderDocument.order_id, func.count(OrderDocument.id))
        .where(
            OrderDocument.organization_id == organization_id,
            OrderDocument.is_deleted.is_(False),
            OrderDocument.order_id.in_(ids),
        )
        .group_by(OrderDocument.order_id)
    ).all()
    return {order_id: count for order_id, count in rows}


def _revision_counts(db: Session, organization_id: str, order_numbers: Iterable[str]) -> dict[str, int]:
    numbers = list({number for number in order_numbers if number})
    if not numbers:
        return {}
    rows = db.execute(
        select(PurchaseOrder.order_number, func.count(PurchaseOrder.id))
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.order_number.in_(numbers),
        )
        .group_by(PurchaseOrder.order_number)
    ).all()
    return {number: count for number, count in rows}


def _vendor_stats(db: Session, organization_id: str) -> tuple[dict[str, int], dict[str, int], dict[str, date | None]]:
    """Orders, documents and the latest order date per vendor (active orders only)."""
    order_rows = db.execute(
        select(
            PurchaseOrder.vendor_id,
            func.count(PurchaseOrder.id),
            func.max(PurchaseOrder.issue_date),
        )
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.vendor_id)
    ).all()
    document_rows = db.execute(
        select(PurchaseOrder.vendor_id, func.count(OrderDocument.id))
        .join(OrderDocument, OrderDocument.order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            OrderDocument.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.vendor_id)
    ).all()
    return (
        {vendor_id: count for vendor_id, count, _ in order_rows},
        {vendor_id: count for vendor_id, count in document_rows},
        {vendor_id: latest for vendor_id, _, latest in order_rows},
    )


def _vendor_out(
    vendor: Vendor,
    *,
    order_count: int = 0,
    document_count: int = 0,
    latest_order_date: date | None = None,
) -> VendorOut:
    return VendorOut(
        id=vendor.id,
        vendor_code=vendor.vendor_code,
        vendor_name=vendor.vendor_name,
        category=vendor.category or "",
        contact_person=vendor.contact_person or "",
        email=vendor.email or "",
        phone=vendor.phone or "",
        website=vendor.website or "",
        country=vendor.country or "",
        tax_registration_no=vendor.tax_registration_no or "",
        address=vendor.address or "",
        status=vendor.status,
        credit_terms_days=vendor.credit_terms_days,
        description=vendor.description or "",
        order_count=order_count,
        document_count=document_count,
        latest_order_date=latest_order_date,
        is_deleted=vendor.is_deleted,
        deleted_at=vendor.deleted_at,
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
    )


def _order_out(
    order: PurchaseOrder,
    *,
    document_count: int = 0,
    revision_count: int = 1,
) -> OrderOut:
    expiry = order.expiry_date
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        order_type=order.order_type,
        vendor_id=order.vendor_id,
        vendor_code=order.vendor.vendor_code if order.vendor else "",
        vendor_name=order.vendor.vendor_name if order.vendor else "",
        vendor_status=order.vendor.status if order.vendor else "inactive",
        revision_number=order.revision_number,
        is_current=order.is_current,
        revision_note=order.revision_note or "",
        parent_order_id=order.parent_order_id,
        issue_date=order.issue_date,
        expiry_date=expiry,
        status=order.status,
        description=order.description or "",
        document_count=document_count,
        revision_count=revision_count,
        is_expired=bool(expiry and expiry < _today()),
        is_deleted=order.is_deleted,
        deleted_at=order.deleted_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _document_out(document: OrderDocument, order: PurchaseOrder | None = None) -> DocumentOut:
    order = order or document.order
    return DocumentOut(
        id=document.id,
        order_id=document.order_id,
        order_number=order.order_number if order else "",
        file_name=document.file_name,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        checksum_sha256=document.checksum_sha256,
        document_kind=document.document_kind,
        label=document.label or "",
        notes=document.description or "",
        revision_number=document.revision_number,
        uploaded_by_name=document.uploaded_by_name or "",
        is_deleted=document.is_deleted,
        deleted_at=document.deleted_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _audit(
    db: Session,
    *,
    user: Any,
    action: str,
    entity_type: str,
    entity_label: str,
    summary: str,
    request: Request,
    entity_id: str | None = None,
) -> None:
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label[:255],
        summary=summary,
        request=request,
    )


def _order_label(order: PurchaseOrder) -> str:
    return f"{ORDER_LABEL} · {order.order_number} (Rev {order.revision_number})"


# --------------------------------------------------------------------------- #
# Documents (file payload handling)
# --------------------------------------------------------------------------- #


def _max_document_bytes() -> int:
    return max(1, get_settings().document_max_size_mb) * 1024 * 1024


def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """Validate extension, size and content before anything is persisted."""
    filename = (upload.filename or "").strip()
    if not filename:
        raise ValueError("The file has no name")
    extension = ("." + filename.rsplit(".", 1)[1].lower()) if "." in filename else ""
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError(
            f"'{extension or filename}' is not an accepted file type. Allowed: {', '.join(ALLOWED_DOCUMENT_EXTENSIONS)}"
        )
    content = upload.file.read()
    if not content:
        raise ValueError("The file is empty")
    limit = _max_document_bytes()
    if len(content) > limit:
        raise ValueError(
            f"The file is {len(content) / 1024 / 1024:.1f} MB; the limit is {limit / 1024 / 1024:.0f} MB"
        )
    return content, filename


def _human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{max(1, size // 1024)} KB"


def _content_disposition(disposition: str, filename: str) -> str:
    ascii_name = re.sub(r"[\"\\\r\n]", "_", filename.encode("ascii", "ignore").decode()) or "attachment"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _store_document(
    db: Session,
    *,
    order: PurchaseOrder,
    user: Any,
    content: bytes,
    filename: str,
    content_type: str,
    document_kind: str,
    label: str,
    notes: str,
) -> OrderDocument:
    """Persist one attachment, refusing an exact duplicate inside the same order."""
    checksum = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(OrderDocument).where(
            OrderDocument.order_id == order.id,
            OrderDocument.organization_id == order.organization_id,
            OrderDocument.checksum_sha256 == checksum,
            OrderDocument.is_deleted.is_(False),
        )
    )
    if duplicate is not None:
        raise ValueError(f"An identical file is already attached as '{duplicate.file_name}'")
    document = OrderDocument(
        organization_id=order.organization_id,
        order_id=order.id,
        file_name=filename[:300],
        content_type=(content_type or "application/octet-stream")[:120],
        size_bytes=len(content),
        checksum_sha256=checksum,
        document_kind=document_kind,
        label=label[:200],
        description=notes[:500],
        revision_number=order.revision_number,
        content=content,
        uploaded_by_user_id=user.id,
        uploaded_by_name=user.full_name,
    )
    db.add(document)
    return document


def _split_revision_hint(filename: str) -> tuple[str, int | None]:
    """Read an optional revision suffix such as ``PO-100_Rev2`` or ``PO-100__2``."""
    stem = filename.rsplit(".", 1)[0].strip()
    match = REVISION_SUFFIX.match(stem)
    if match:
        number = match.group("number").strip(" _-.")
        revision = int(match.group("revision"))
        if number and revision <= 200:
            return number, revision
    return stem, None


# --------------------------------------------------------------------------- #
# Module dashboard
# --------------------------------------------------------------------------- #


@router.get(
    "/vendor-po/overview",
    response_model=VendorPoOverview,
    dependencies=[Depends(require("master-data:read"))],
)
def vendor_po_overview(db: Db, user: Current) -> VendorPoOverview:
    """KPIs for the Vendors and PO/SO Orders tabs of Master Data Management."""
    organization_id = user.organization_id

    def vendor_count(status: str | None = None, *, deleted: bool = False) -> int:
        statement = select(func.count(Vendor.id)).where(
            Vendor.organization_id == organization_id, Vendor.is_deleted.is_(deleted)
        )
        if status:
            statement = statement.where(Vendor.status == status)
        return db.scalar(statement) or 0

    def order_count(*, deleted: bool = False, amendments: bool = False, status: str | None = None) -> int:
        statement = select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.organization_id == organization_id, PurchaseOrder.is_deleted.is_(deleted)
        )
        if amendments:
            statement = statement.where(PurchaseOrder.revision_number > 0)
        if status:
            statement = statement.where(PurchaseOrder.status == status)
        return db.scalar(statement) or 0

    type_rows = db.execute(
        select(PurchaseOrder.order_type, func.count(PurchaseOrder.id))
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.order_type)
    ).all()
    types = {order_type: count for order_type, count in type_rows}

    top_rows = db.execute(
        select(
            Vendor.id,
            Vendor.vendor_code,
            Vendor.vendor_name,
            func.count(PurchaseOrder.id),
        )
        .join(PurchaseOrder, PurchaseOrder.vendor_id == Vendor.id)
        .where(
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
            PurchaseOrder.is_deleted.is_(False),
        )
        .group_by(Vendor.id, Vendor.vendor_code, Vendor.vendor_name)
        .order_by(func.count(PurchaseOrder.id).desc(), Vendor.vendor_code)
        .limit(5)
    ).all()
    document_rows = db.execute(
        select(PurchaseOrder.vendor_id, func.count(OrderDocument.id))
        .join(OrderDocument, OrderDocument.order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            OrderDocument.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.vendor_id)
    ).all()
    documents_by_vendor = {vendor_id: count for vendor_id, count in document_rows}

    return VendorPoOverview(
        vendors_active=vendor_count("active"),
        vendors_inactive=vendor_count("inactive"),
        vendors_blocked=vendor_count("blocked"),
        vendors_deleted=vendor_count(deleted=True),
        orders_active=order_count(),
        orders_amendments=order_count(amendments=True),
        orders_deleted=order_count(deleted=True),
        orders_by_type=[
            VendorPoCount(key=order_type, label=order_type, count=types.get(order_type, 0))
            for order_type in ORDER_TYPES
        ],
        orders_by_status=[
            VendorPoCount(key=status, label=status.title(), count=order_count(status=status))
            for status in ORDER_STATUSES
        ],
        documents_active=db.scalar(
            select(func.count(OrderDocument.id)).where(
                OrderDocument.organization_id == organization_id,
                OrderDocument.is_deleted.is_(False),
            )
        ) or 0,
        documents_deleted=db.scalar(
            select(func.count(OrderDocument.id)).where(
                OrderDocument.organization_id == organization_id,
                OrderDocument.is_deleted.is_(True),
            )
        ) or 0,
        storage_bytes=db.scalar(
            select(func.coalesce(func.sum(OrderDocument.size_bytes), 0)).where(
                OrderDocument.organization_id == organization_id,
                OrderDocument.is_deleted.is_(False),
            )
        ) or 0,
        top_vendors=[
            VendorPoTopVendor(
                vendor_id=vendor_id,
                vendor_code=vendor_code,
                vendor_name=vendor_name,
                order_count=order_total,
                document_count=documents_by_vendor.get(vendor_id, 0),
            )
            for vendor_id, vendor_code, vendor_name, order_total in top_rows
        ],
    )


@router.get(
    "/vendor-po/activity",
    response_model=list[MasterDataActivity],
    dependencies=[Depends(require("master-data:read"))],
)
def vendor_po_activity(db: Db, user: Current) -> list[MasterDataActivity]:
    """Recent vendor, order and document activity for the module dashboard."""
    entries = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == user.organization_id,
            AuditLog.entity_type.in_(AUDIT_ENTITY_TYPES),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(8)
    ).all()
    return [
        MasterDataActivity(
            id=entry.id,
            action=entry.action,
            entity_label=entry.entity_label,
            summary=entry.summary,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


# --------------------------------------------------------------------------- #
# Vendors
# --------------------------------------------------------------------------- #


@router.get(
    "/vendors/options",
    response_model=list[VendorOption],
    dependencies=[Depends(require("master-data:read"))],
)
def vendor_options(db: Db, user: Current) -> list[VendorOption]:
    """Lightweight vendor list for PO/SO forms and filters (active vendors only)."""
    vendors = db.scalars(
        select(Vendor)
        .where(
            Vendor.organization_id == user.organization_id,
            Vendor.is_deleted.is_(False),
        )
        .order_by(Vendor.vendor_code)
    ).all()
    orders, _, _ = _vendor_stats(db, user.organization_id)
    return [
        VendorOption(
            id=vendor.id,
            vendor_code=vendor.vendor_code,
            vendor_name=vendor.vendor_name,
            status=vendor.status,
            order_count=orders.get(vendor.id, 0),
            label=f"{vendor.vendor_code} — {vendor.vendor_name}",
        )
        for vendor in vendors
    ]


@router.get(
    "/vendors/deleted",
    response_model=list[VendorOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_deleted_vendors(db: Db, user: Current) -> list[VendorOut]:
    vendors = db.scalars(
        select(Vendor)
        .where(Vendor.organization_id == user.organization_id, Vendor.is_deleted.is_(True))
        .order_by(Vendor.deleted_at.desc(), Vendor.vendor_code)
    ).all()
    return [_vendor_out(vendor) for vendor in vendors]


@router.get("/vendors", response_model=list[VendorOut], dependencies=[Depends(require("master-data:read"))])
def list_vendors(db: Db, user: Current) -> list[VendorOut]:
    """Active vendors with their PO/SO and attached-document counts."""
    vendors = db.scalars(
        select(Vendor)
        .where(Vendor.organization_id == user.organization_id, Vendor.is_deleted.is_(False))
        .order_by(Vendor.vendor_code)
    ).all()
    orders, documents, latest = _vendor_stats(db, user.organization_id)
    return [
        _vendor_out(
            vendor,
            order_count=orders.get(vendor.id, 0),
            document_count=documents.get(vendor.id, 0),
            latest_order_date=latest.get(vendor.id),
        )
        for vendor in vendors
    ]


@router.get(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:read"))],
)
def get_vendor(vendor_id: str, db: Db, user: Current) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    orders, documents, latest = _vendor_stats(db, user.organization_id)
    return _vendor_out(
        vendor,
        order_count=orders.get(vendor.id, 0),
        document_count=documents.get(vendor.id, 0),
        latest_order_date=latest.get(vendor.id),
    )


# Every editable vendor column; partial updates are validated against the whole record.
VENDOR_FIELDS = (
    "vendor_code", "vendor_name", "category", "contact_person", "email", "phone",
    "website", "country", "tax_registration_no", "address", "status",
    "credit_terms_days", "description",
)


def _vendor_values(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the free-text business fields and map them onto model columns."""
    values = dict(payload)
    code = str(values.get("vendor_code") or "").strip().upper()
    if not code:
        raise ValueError("Vendor code is required")
    values["vendor_code"] = code
    name = str(values.get("vendor_name") or "").strip()
    if not name:
        raise ValueError("Vendor name is required")
    values["vendor_name"] = name
    values["email"] = _check_email(str(values.get("email") or "").strip())
    values["website"] = _check_website(str(values.get("website") or "").strip())
    status = values.get("status") or "active"
    if status not in VENDOR_STATUSES:
        raise ValueError(f"Status must be one of {', '.join(VENDOR_STATUSES)}")
    values["status"] = status
    for field in ("category", "contact_person", "phone", "country", "tax_registration_no", "address", "description"):
        values[field] = str(values.get(field) or "").strip()
    terms = values.get("credit_terms_days")
    values["credit_terms_days"] = int(terms) if terms not in (None, "") else None
    return values


def _duplicate_vendor(db: Session, organization_id: str, code: str, *, exclude_id: str | None = None) -> Vendor | None:
    statement = select(Vendor).where(
        Vendor.organization_id == organization_id,
        func.upper(Vendor.vendor_code) == code,
    )
    if exclude_id:
        statement = statement.where(Vendor.id != exclude_id)
    return db.scalar(statement)


@router.post(
    "/vendors",
    response_model=VendorOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_vendor(data: VendorCreate, request: Request, db: Db, user: Current) -> VendorOut:
    try:
        payload = _vendor_values(data.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if _duplicate_vendor(db, user.organization_id, payload["vendor_code"]):
        raise HTTPException(
            status_code=409,
            detail=f"Vendor code '{payload['vendor_code']}' already exists; restore or permanently remove its deleted entry first",
        )
    vendor = Vendor(organization_id=user.organization_id, **payload)
    db.add(vendor)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Vendor code already exists in this workspace") from error
    _audit(
        db,
        user=user,
        action=MasterDataAction.CREATE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Created vendor {vendor.vendor_code} ({vendor.vendor_name})",
        request=request,
    )
    _commit(db)
    db.refresh(vendor)
    return _vendor_out(vendor)


@router.patch(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_vendor(
    vendor_id: str,
    data: VendorUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    # Validate against the whole record so a partial update still satisfies the
    # required fields, then write back only what the caller supplied.
    merged = {field: getattr(vendor, field) for field in VENDOR_FIELDS}
    merged.update(supplied)
    try:
        payload = _vendor_values(merged)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if _duplicate_vendor(db, user.organization_id, payload["vendor_code"], exclude_id=vendor.id):
        raise HTTPException(
            status_code=409, detail=f"Vendor code '{payload['vendor_code']}' already exists in this workspace"
        )

    changed = [field for field in supplied if getattr(vendor, field) != payload[field]]
    for field in supplied:
        setattr(vendor, field, payload[field])
    if changed:
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Updated vendor {vendor.vendor_code}: {', '.join(sorted(changed))}",
            request=request,
        )
        _commit(db)
        db.refresh(vendor)
    return _vendor_out(vendor)


@router.delete(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:delete"))],
)
def soft_delete_vendor(vendor_id: str, request: Request, db: Db, user: Current) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id, include_deleted=False)
    live_orders = db.scalar(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.vendor_id == vendor.id,
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
    ) or 0
    if live_orders:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Vendor {vendor.vendor_code} still has {live_orders} active PO/SO "
                f"{'order' if live_orders == 1 else 'orders'}. Move them to deleted entries first."
            ),
        )
    vendor.is_deleted = True
    vendor.deleted_at = datetime.now(timezone.utc)
    _audit(
        db,
        user=user,
        action=MasterDataAction.SOFT_DELETE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Moved vendor {vendor.vendor_code} to deleted entries",
        request=request,
    )
    _commit(db)
    db.refresh(vendor)
    return _vendor_out(vendor)


@router.post(
    "/vendors/{vendor_id}/restore",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_vendor(vendor_id: str, request: Request, db: Db, user: Current) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    if not vendor.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted vendor can be restored")
    vendor.is_deleted = False
    vendor.deleted_at = None
    _audit(
        db,
        user=user,
        action=MasterDataAction.RESTORE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Restored vendor {vendor.vendor_code}",
        request=request,
    )
    _commit(db)
    db.refresh(vendor)
    return _vendor_out(vendor)


@router.delete(
    "/vendors/{vendor_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_vendor(vendor_id: str, request: Request, db: Db, user: Current) -> None:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    if not vendor.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted vendor can be permanently deleted")
    remaining = db.scalar(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.vendor_id == vendor.id,
            PurchaseOrder.organization_id == user.organization_id,
        )
    ) or 0
    if remaining:
        raise HTTPException(
            status_code=409,
            detail=f"Vendor {vendor.vendor_code} still holds {remaining} PO/SO order rows. Permanently delete those first.",
        )
    _audit(
        db,
        user=user,
        action=MasterDataAction.PERMANENT_DELETE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Permanently deleted vendor {vendor.vendor_code}",
        request=request,
    )
    db.delete(vendor)
    _commit(db)
    return None


def _vendors_for_ids(db: Session, ids: list[str], organization_id: str, *, deleted: bool) -> list[Vendor]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate vendor IDs are not allowed")
    vendors = list(
        db.scalars(
            select(Vendor).where(Vendor.organization_id == organization_id, Vendor.id.in_(ids))
        ).all()
    )
    if len(vendors) != len(ids):
        raise HTTPException(status_code=404, detail="One or more vendors were not found in this workspace")
    if any(vendor.is_deleted is not deleted for vendor in vendors):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"Bulk action requires only {expected} vendors")
    return vendors


@router.post(
    "/vendors/bulk-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:delete"))],
)
def bulk_soft_delete_vendors(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    vendors = _vendors_for_ids(db, data.ids, user.organization_id, deleted=False)
    blocked = [
        vendor.vendor_code
        for vendor in vendors
        if (
            db.scalar(
                select(func.count(PurchaseOrder.id)).where(
                    PurchaseOrder.vendor_id == vendor.id,
                    PurchaseOrder.is_deleted.is_(False),
                )
            )
            or 0
        )
    ]
    if blocked:
        raise HTTPException(
            status_code=409,
            detail=f"These vendors still have active PO/SO orders: {', '.join(sorted(blocked))}",
        )
    deleted_at = datetime.now(timezone.utc)
    for vendor in vendors:
        vendor.is_deleted = True
        vendor.deleted_at = deleted_at
        _audit(
            db,
            user=user,
            action=MasterDataAction.SOFT_DELETE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Moved vendor {vendor.vendor_code} to deleted entries (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(vendors))


@router.post(
    "/vendors/bulk-restore",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:restore"))],
)
def bulk_restore_vendors(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    vendors = _vendors_for_ids(db, data.ids, user.organization_id, deleted=True)
    for vendor in vendors:
        vendor.is_deleted = False
        vendor.deleted_at = None
        _audit(
            db,
            user=user,
            action=MasterDataAction.RESTORE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Restored vendor {vendor.vendor_code} (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(vendors))


@router.post(
    "/vendors/bulk-permanent-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def bulk_permanent_delete_vendors(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    vendors = _vendors_for_ids(db, data.ids, user.organization_id, deleted=True)
    for vendor in vendors:
        remaining = db.scalar(
            select(func.count(PurchaseOrder.id)).where(PurchaseOrder.vendor_id == vendor.id)
        ) or 0
        if remaining:
            raise HTTPException(
                status_code=409,
                detail=f"Vendor {vendor.vendor_code} still holds {remaining} PO/SO order rows",
            )
    for vendor in vendors:
        _audit(
            db,
            user=user,
            action=MasterDataAction.PERMANENT_DELETE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Permanently deleted vendor {vendor.vendor_code} (bulk action)",
            request=request,
        )
        db.delete(vendor)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(vendors))


@router.post(
    "/vendors/import",
    response_model=MasterDataImportResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def import_vendors(
    data: MasterDataImportRequest, request: Request, db: Db, user: Current
) -> MasterDataImportResponse:
    """Upsert vendors from a previewed spreadsheet, reporting per-row problems."""
    imported = 0
    errors: list[str] = []
    seen: set[str] = set()

    for row_number, row in enumerate(data.rows, start=1):
        normalized = _normalize_import_row(row, VENDOR_IMPORT_ALIASES)
        status_text = str(normalized.get("status") or "").strip().lower()
        if status_text:
            if status_text not in VENDOR_STATUS_ALIASES:
                errors.append(
                    f"Row {row_number}: status '{status_text}' is not recognized (use active, inactive or blocked)"
                )
                continue
            normalized["status"] = VENDOR_STATUS_ALIASES[status_text]
        terms_text = str(normalized.get("credit_terms_days") or "").strip()
        if terms_text:
            digits = re.sub(r"[^0-9]", "", terms_text)
            if not digits:
                errors.append(f"Row {row_number}: credit terms '{terms_text}' is not a number of days")
                continue
            normalized["credit_terms_days"] = int(digits)
        try:
            payload = _vendor_values(VendorCreate.model_validate(normalized).model_dump())
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        code = payload["vendor_code"]
        if code in seen:
            errors.append(f"Row {row_number} ({code}): duplicate vendor code in this import file")
            continue
        seen.add(code)

        vendor = _duplicate_vendor(db, user.organization_id, code)
        if vendor is None:
            vendor = Vendor(organization_id=user.organization_id, **payload)
            db.add(vendor)
            try:
                db.flush()
            except IntegrityError as error:
                db.rollback()
                errors.append(f"Row {row_number} ({code}): vendor code already exists")
                continue
            action = MasterDataAction.CREATE
            summary = f"Created vendor {code} from import"
        else:
            for field, value in payload.items():
                setattr(vendor, field, value)
            if vendor.is_deleted:
                vendor.is_deleted = False
                vendor.deleted_at = None
                action = MasterDataAction.RESTORE
                summary = f"Restored and updated vendor {code} from import"
            else:
                action = MasterDataAction.UPDATE
                summary = f"Updated vendor {code} from import"
        _audit(
            db,
            user=user,
            action=action,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {code}",
            summary=summary,
            request=request,
        )
        imported += 1

    _audit(
        db,
        user=user,
        action=MasterDataAction.IMPORT,
        entity_type=VENDOR_ENTITY,
        entity_label=VENDOR_LABEL,
        summary=f"Imported {imported} vendors with {len(errors)} validation errors",
        request=request,
    )
    _commit(db)
    return MasterDataImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


# --------------------------------------------------------------------------- #
# PO/SO Orders
# --------------------------------------------------------------------------- #


@router.get(
    "/po-so-orders/deleted",
    response_model=list[OrderOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_deleted_orders(db: Db, user: Current) -> list[OrderOut]:
    orders = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(True),
        )
        .order_by(PurchaseOrder.deleted_at.desc(), PurchaseOrder.order_number)
    ).all()
    documents = _document_counts(db, user.organization_id, [order.id for order in orders])
    revisions = _revision_counts(db, user.organization_id, [order.order_number for order in orders])
    return [
        _order_out(
            order,
            document_count=documents.get(order.id, 0),
            revision_count=revisions.get(order.order_number, 0),
        )
        for order in orders
    ]


@router.get(
    "/po-so-orders",
    response_model=list[OrderOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_orders(db: Db, user: Current) -> list[OrderOut]:
    """Every active PO/SO revision in the workspace, with vendor and file counts."""
    orders = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
        .order_by(PurchaseOrder.order_number, PurchaseOrder.revision_number)
    ).all()
    documents = _document_counts(db, user.organization_id, [order.id for order in orders])
    revisions = _revision_counts(db, user.organization_id, [order.order_number for order in orders])
    return [
        _order_out(
            order,
            document_count=documents.get(order.id, 0),
            revision_count=revisions.get(order.order_number, 1),
        )
        for order in orders
    ]


@router.get(
    "/po-so-orders/{order_id}/revisions",
    response_model=list[OrderRevisionOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_order_revisions(order_id: str, db: Db, user: Current) -> list[OrderRevisionOut]:
    """The amendment history of one order number, oldest first."""
    order = _order_or_404(db, order_id, user.organization_id)
    family = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == order.order_number,
        )
        .order_by(PurchaseOrder.revision_number)
    ).all()
    documents = _document_counts(db, user.organization_id, [row.id for row in family])
    return [
        OrderRevisionOut(
            id=row.id,
            revision_number=row.revision_number,
            is_current=row.is_current,
            revision_note=row.revision_note or "",
            issue_date=row.issue_date,
            status=row.status,
            document_count=documents.get(row.id, 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
            is_deleted=row.is_deleted,
        )
        for row in family
    ]


def _order_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = dict(payload)
    number = str(values.get("order_number") or "").strip().upper()
    if not number:
        raise ValueError("PO/SO number is required")
    values["order_number"] = number
    order_type = values.get("order_type") or "PO"
    if order_type not in ORDER_TYPES:
        raise ValueError(f"Order type must be one of {', '.join(ORDER_TYPES)}")
    values["order_type"] = order_type
    status = values.get("status") or "open"
    if status not in ORDER_STATUSES:
        raise ValueError(f"Status must be one of {', '.join(ORDER_STATUSES)}")
    values["status"] = status
    values["description"] = str(values.get("description") or "").strip()
    issue, expiry = values.get("issue_date"), values.get("expiry_date")
    if issue and expiry and expiry < issue:
        raise ValueError("Expiry date cannot be earlier than the issue date")
    return values


def _active_vendor(db: Session, vendor_id: str, organization_id: str) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if vendor is None:
        raise ValueError("Select a vendor that exists in this workspace")
    return vendor


@router.post(
    "/po-so-orders",
    response_model=OrderOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_order(data: OrderCreate, request: Request, db: Db, user: Current) -> OrderOut:
    """Create the original (revision 0) of a PO/SO order."""
    try:
        payload = _order_values(data.model_dump())
        vendor = _active_vendor(db, payload["vendor_id"], user.organization_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if vendor.status == "blocked":
        raise HTTPException(
            status_code=409,
            detail=f"Vendor {vendor.vendor_code} is blocked. Unblock it before adding new PO/SO orders.",
        )
    number = payload["order_number"]
    existing = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == number,
            PurchaseOrder.revision_number == 0,
        )
    )
    if existing is not None:
        detail = (
            f"'{number}' already exists in this workspace. Use Create amendment to add a revision."
            if not existing.is_deleted
            else f"A deleted original of '{number}' exists. Restore it from Deleted Entries first."
        )
        raise HTTPException(status_code=409, detail=detail)

    order = PurchaseOrder(
        organization_id=user.organization_id,
        revision_number=0,
        is_current=True,
        **payload,
    )
    db.add(order)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This PO/SO number and revision already exists") from error
    _audit(
        db,
        user=user,
        action=MasterDataAction.CREATE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=f"Created {order.order_type} {order.order_number} for vendor {vendor.vendor_code}",
        request=request,
    )
    _commit(db)
    db.refresh(order)
    return _order_out(order, revision_count=1)


@router.post(
    "/po-so-orders/import",
    response_model=MasterDataImportResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def import_orders(
    data: MasterDataImportRequest, request: Request, db: Db, user: Current
) -> MasterDataImportResponse:
    """Upsert original PO/SO revisions from a previewed spreadsheet.

    Amendments are never created by import — they need an explicit revision note
    and lineage, so they are raised with Create amendment in the UI.
    """
    imported = 0
    errors: list[str] = []
    seen: set[str] = set()
    vendors = {
        vendor.vendor_code.upper(): vendor
        for vendor in db.scalars(
            select(Vendor).where(
                Vendor.organization_id == user.organization_id, Vendor.is_deleted.is_(False)
            )
        ).all()
    }

    for row_number, row in enumerate(data.rows, start=1):
        normalized = _normalize_import_row(row, ORDER_IMPORT_ALIASES)
        vendor_code = str(normalized.get("vendor_code") or "").strip().upper()
        vendor = vendors.get(vendor_code)
        if vendor is None:
            errors.append(f"Row {row_number}: vendor '{vendor_code or '(blank)'}' is not an active vendor in this workspace")
            continue
        if vendor.status == "blocked":
            errors.append(f"Row {row_number}: vendor '{vendor_code}' is blocked; unblock it before importing orders")
            continue
        type_text = str(normalized.get("order_type") or "").strip().lower()
        if type_text and type_text not in ORDER_TYPE_ALIASES:
            errors.append(f"Row {row_number}: order type '{type_text}' is not recognized (use PO, SO, Callout or Others)")
            continue
        status_text = str(normalized.get("status") or "").strip().lower()
        if status_text and status_text not in ORDER_STATUS_ALIASES:
            errors.append(f"Row {row_number}: status '{status_text}' is not recognized (use open, closed or cancelled)")
            continue
        try:
            payload = _order_values(
                OrderCreate.model_validate(
                    {
                        "order_number": normalized.get("order_number"),
                        "order_type": ORDER_TYPE_ALIASES.get(type_text, "PO"),
                        "vendor_id": vendor.id,
                        "status": ORDER_STATUS_ALIASES.get(status_text, "open"),
                        "description": normalized.get("description") or "",
                    }
                ).model_dump()
            )
            payload["issue_date"] = _parse_import_date(normalized.get("issue_date"))
            payload["expiry_date"] = _parse_import_date(normalized.get("expiry_date"))
            payload = _order_values(payload)
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        number = payload["order_number"]
        if number in seen:
            errors.append(f"Row {row_number} ({number}): duplicate PO/SO number in this import file")
            continue
        seen.add(number)

        order = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == user.organization_id,
                PurchaseOrder.order_number == number,
                PurchaseOrder.revision_number == 0,
            )
        )
        if order is None:
            order = PurchaseOrder(
                organization_id=user.organization_id, revision_number=0, is_current=True, **payload
            )
            db.add(order)
            try:
                db.flush()
            except IntegrityError as error:
                db.rollback()
                errors.append(f"Row {row_number} ({number}): PO/SO number already exists")
                continue
            action = MasterDataAction.CREATE
            summary = f"Created {order.order_type} {number} from import"
        else:
            for field, value in payload.items():
                setattr(order, field, value)
            if order.is_deleted:
                order.is_deleted = False
                order.deleted_at = None
                action = MasterDataAction.RESTORE
                summary = f"Restored and updated {order.order_type} {number} from import"
            else:
                action = MasterDataAction.UPDATE
                summary = f"Updated {order.order_type} {number} from import"
        _audit(
            db,
            user=user,
            action=action,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=summary,
            request=request,
        )
        imported += 1

    _audit(
        db,
        user=user,
        action=MasterDataAction.IMPORT,
        entity_type=ORDER_ENTITY,
        entity_label=ORDER_LABEL,
        summary=f"Imported {imported} PO/SO orders with {len(errors)} validation errors",
        request=request,
    )
    _commit(db)
    return MasterDataImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


@router.post(
    "/po-so-orders/{order_id}/amendment",
    response_model=OrderOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_amendment(
    order_id: str,
    data: OrderAmendmentCreate,
    request: Request,
    db: Db,
    user: Current,
) -> OrderOut:
    """Raise the next revision of an order, optionally carrying its files forward."""
    source = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    highest = db.scalar(
        select(func.max(PurchaseOrder.revision_number)).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == source.order_number,
        )
    ) or 0
    next_revision = highest + 1
    if next_revision > 200:
        raise HTTPException(status_code=409, detail="This order already has 200 revisions; close it instead")

    payload = {
        "order_number": source.order_number,
        "order_type": data.order_type or source.order_type,
        "vendor_id": source.vendor_id,
        "issue_date": data.issue_date if data.issue_date is not None else source.issue_date,
        "expiry_date": data.expiry_date if data.expiry_date is not None else source.expiry_date,
        "status": data.status or source.status,
        "description": source.description if data.description is None else data.description,
        "revision_note": data.revision_note,
    }
    try:
        payload = _order_values(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    payload["revision_note"] = data.revision_note

    amendment = PurchaseOrder(
        organization_id=user.organization_id,
        parent_order_id=source.id,
        revision_number=next_revision,
        is_current=True,
        **payload,
    )
    db.add(amendment)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This PO/SO number and revision already exists") from error

    siblings = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == source.order_number,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.id != amendment.id,
        )
    ).all()
    for sibling in siblings:
        sibling.is_current = False

    copied = 0
    if data.copy_documents:
        for document in db.scalars(
            select(OrderDocument).where(
                OrderDocument.order_id == source.id,
                OrderDocument.organization_id == user.organization_id,
                OrderDocument.is_deleted.is_(False),
            )
        ).all():
            db.add(
                OrderDocument(
                    organization_id=user.organization_id,
                    order_id=amendment.id,
                    file_name=document.file_name,
                    content_type=document.content_type,
                    size_bytes=document.size_bytes,
                    checksum_sha256=document.checksum_sha256,
                    document_kind="amendment_copy" if document.document_kind == "po_copy" else document.document_kind,
                    label=document.label,
                    description=document.description,
                    revision_number=amendment.revision_number,
                    content=bytes(document.content),
                    uploaded_by_user_id=user.id,
                    uploaded_by_name=user.full_name,
                )
            )
            copied += 1

    _audit(
        db,
        user=user,
        action=MasterDataAction.AMEND,
        entity_type=ORDER_ENTITY,
        entity_id=amendment.id,
        entity_label=_order_label(amendment),
        summary=(
            f"Created revision {amendment.revision_number} of {amendment.order_type} "
            f"{amendment.order_number}: {amendment.revision_note}"
        ),
        request=request,
    )
    if copied:
        _audit(
            db,
            user=user,
            action=MasterDataAction.DOCUMENT_UPLOAD,
            entity_type=DOCUMENT_ENTITY,
            entity_id=amendment.id,
            entity_label=_order_label(amendment),
            summary=f"Carried {copied} file(s) forward from revision {source.revision_number} of {amendment.order_number}",
            request=request,
        )
    _commit(db)
    db.refresh(amendment)
    documents = _document_counts(db, user.organization_id, [amendment.id])
    return _order_out(
        amendment,
        document_count=documents.get(amendment.id, 0),
        revision_count=next_revision + 1,
    )


@router.patch(
    "/po-so-orders/{order_id}",
    response_model=OrderOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_order(
    order_id: str,
    data: OrderUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> OrderOut:
    order = _order_or_404(db, order_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    merged = {
        field: getattr(order, field)
        for field in ("order_number", "order_type", "vendor_id", "issue_date", "expiry_date", "status", "description")
    }
    merged.update(supplied)
    try:
        payload = _order_values(merged)
        # The vendor is only re-checked when it actually changes, so editing the
        # description of an order keeps working whatever the vendor's state is.
        if "vendor_id" in supplied:
            _active_vendor(db, payload["vendor_id"], user.organization_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    family = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == order.order_number,
            PurchaseOrder.is_deleted.is_(False),
        )
    ).all()
    if payload["vendor_id"] != order.vendor_id and len(family) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"This order has {len(family)} revisions; the vendor of an amendment chain cannot change",
        )
    if payload["vendor_id"] != order.vendor_id:
        new_vendor = db.get(Vendor, payload["vendor_id"])
        if new_vendor is not None and new_vendor.status == "blocked":
            raise HTTPException(
                status_code=409,
                detail=f"Vendor {new_vendor.vendor_code} is blocked. Unblock it before moving orders to this vendor.",
            )

    # Work out what changed before the chain rename touches this row.
    changed = [field for field in supplied if getattr(order, field) != payload[field]]
    renamed_to = payload["order_number"] if payload["order_number"] != order.order_number else None
    if renamed_to:
        clash = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == user.organization_id,
                PurchaseOrder.order_number == renamed_to,
                PurchaseOrder.id != order.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"'{renamed_to}' already exists in this workspace (revision {clash.revision_number})",
            )
        # Renaming keeps the whole amendment chain together.
        for member in family:
            member.order_number = renamed_to

    for field in supplied:
        setattr(order, field, payload[field])
    if changed:
        summary = f"Updated {order.order_type} {order.order_number} (Rev {order.revision_number}): {', '.join(sorted(changed))}"
        if renamed_to:
            summary += f" (renamed across {len(family)} revisions)"
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=summary,
            request=request,
        )
        _commit(db)
        db.refresh(order)
    documents = _document_counts(db, user.organization_id, [order.id])
    revisions = _revision_counts(db, user.organization_id, [order.order_number])
    return _order_out(
        order,
        document_count=documents.get(order.id, 0),
        revision_count=revisions.get(order.order_number, 1),
    )


@router.delete(
    "/po-so-orders/{order_id}",
    response_model=OrderOut,
    dependencies=[Depends(require("master-data:delete"))],
)
def soft_delete_order(order_id: str, request: Request, db: Db, user: Current) -> OrderOut:
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    order.is_deleted = True
    order.deleted_at = datetime.now(timezone.utc)
    order.is_current = False
    _audit(
        db,
        user=user,
        action=MasterDataAction.SOFT_DELETE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=f"Moved {order.order_type} {order.order_number} (Rev {order.revision_number}) to deleted entries",
        request=request,
    )
    _commit(db)
    db.refresh(order)
    return _order_out(order)


@router.post(
    "/po-so-orders/{order_id}/restore",
    response_model=OrderOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_order(order_id: str, request: Request, db: Db, user: Current) -> OrderOut:
    order = _order_or_404(db, order_id, user.organization_id)
    if not order.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted PO/SO order can be restored")
    order.is_deleted = False
    order.deleted_at = None
    # Only the highest live revision of a number is the one to quote.
    highest = db.scalar(
        select(func.max(PurchaseOrder.revision_number)).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == order.order_number,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.id != order.id,
        )
    )
    order.is_current = highest is None or order.revision_number > highest
    if order.is_current:
        for sibling in db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == user.organization_id,
                PurchaseOrder.order_number == order.order_number,
                PurchaseOrder.is_deleted.is_(False),
                PurchaseOrder.id != order.id,
            )
        ).all():
            sibling.is_current = False
    _audit(
        db,
        user=user,
        action=MasterDataAction.RESTORE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=f"Restored {order.order_type} {order.order_number} (Rev {order.revision_number})",
        request=request,
    )
    _commit(db)
    db.refresh(order)
    documents = _document_counts(db, user.organization_id, [order.id])
    revisions = _revision_counts(db, user.organization_id, [order.order_number])
    return _order_out(
        order,
        document_count=documents.get(order.id, 0),
        revision_count=revisions.get(order.order_number, 1),
    )


@router.delete(
    "/po-so-orders/{order_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_order(order_id: str, request: Request, db: Db, user: Current) -> None:
    order = _order_or_404(db, order_id, user.organization_id)
    if not order.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted PO/SO order can be permanently deleted")
    document_total = db.scalar(
        select(func.count(OrderDocument.id)).where(OrderDocument.order_id == order.id)
    ) or 0
    _audit(
        db,
        user=user,
        action=MasterDataAction.PERMANENT_DELETE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=(
            f"Permanently deleted {order.order_type} {order.order_number} (Rev {order.revision_number})"
            + (f" with {document_total} attached file(s)" if document_total else "")
        ),
        request=request,
    )
    db.delete(order)
    _commit(db)
    return None


def _orders_for_ids(db: Session, ids: list[str], organization_id: str, *, deleted: bool) -> list[PurchaseOrder]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate order IDs are not allowed")
    orders = list(
        db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == organization_id, PurchaseOrder.id.in_(ids)
            )
        ).all()
    )
    if len(orders) != len(ids):
        raise HTTPException(status_code=404, detail="One or more PO/SO orders were not found in this workspace")
    if any(order.is_deleted is not deleted for order in orders):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"Bulk action requires only {expected} PO/SO orders")
    return orders


@router.post(
    "/po-so-orders/bulk-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:delete"))],
)
def bulk_soft_delete_orders(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    orders = _orders_for_ids(db, data.ids, user.organization_id, deleted=False)
    deleted_at = datetime.now(timezone.utc)
    for order in orders:
        order.is_deleted = True
        order.deleted_at = deleted_at
        order.is_current = False
        _audit(
            db,
            user=user,
            action=MasterDataAction.SOFT_DELETE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=(
                f"Moved {order.order_type} {order.order_number} (Rev {order.revision_number}) "
                "to deleted entries (bulk action)"
            ),
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(orders))


@router.post(
    "/po-so-orders/bulk-restore",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:restore"))],
)
def bulk_restore_orders(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    orders = _orders_for_ids(db, data.ids, user.organization_id, deleted=True)
    for order in orders:
        order.is_deleted = False
        order.deleted_at = None
        _audit(
            db,
            user=user,
            action=MasterDataAction.RESTORE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=f"Restored {order.order_type} {order.order_number} (Rev {order.revision_number}) (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(orders))


@router.post(
    "/po-so-orders/bulk-permanent-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def bulk_permanent_delete_orders(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    orders = _orders_for_ids(db, data.ids, user.organization_id, deleted=True)
    for order in orders:
        _audit(
            db,
            user=user,
            action=MasterDataAction.PERMANENT_DELETE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=f"Permanently deleted {order.order_type} {order.order_number} (Rev {order.revision_number}) (bulk action)",
            request=request,
        )
        db.delete(order)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(orders))


# --------------------------------------------------------------------------- #
# Documents attached to a PO/SO revision
# --------------------------------------------------------------------------- #


@router.post(
    "/po-so-orders/documents/bulk",
    response_model=DocumentUploadResult,
    dependencies=[Depends(require("master-data:document-upload"))],
)
async def bulk_upload_documents(
    request: Request,
    db: Db,
    user: Current,
    files: list[UploadFile] = File(...),
    document_kind: str = Form("po_copy"),
) -> DocumentUploadResult:
    """Attach many files at once, matching each file name to an order number.

    File names are read as ``<ORDER NUMBER>`` or ``<ORDER NUMBER>_Rev2``
    (``_2`` and ``__2`` also work); an unmatched file is reported, never guessed.
    """
    if document_kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=422, detail=f"Document kind must be one of {', '.join(DOCUMENT_KINDS)}")
    orders = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
    ).all()
    by_number: dict[str, list[PurchaseOrder]] = {}
    for order in orders:
        by_number.setdefault(order.order_number.upper(), []).append(order)

    items: list[DocumentUploadItem] = []
    uploaded = 0
    for upload in files:
        filename = (upload.filename or "").strip()
        try:
            content, filename = _read_upload(upload)
        except ValueError as error:
            items.append(DocumentUploadItem(file_name=filename or "(unnamed)", accepted=False, message=str(error)))
            continue

        hint, revision_hint = _split_revision_hint(filename)
        family = by_number.get(hint.upper())
        matched_revision = revision_hint
        if family is None:
            # Fall back to the longest order number that appears in the file name.
            candidates = [
                number for number in by_number if number and number.upper() in filename.upper()
            ]
            if not candidates:
                items.append(
                    DocumentUploadItem(
                        file_name=filename,
                        accepted=False,
                        message="No active PO/SO number matches this file name",
                    )
                )
                continue
            family = by_number[max(candidates, key=len)]
            matched_revision = None

        target = None
        if matched_revision is not None:
            target = next((row for row in family if row.revision_number == matched_revision), None)
        if target is None:
            target = next((row for row in family if row.is_current), None) or family[-1]
        try:
            document = _store_document(
                db,
                order=target,
                user=user,
                content=content,
                filename=filename,
                content_type=upload.content_type or "application/octet-stream",
                document_kind=document_kind,
                label="",
                notes="Attached by bulk upload",
            )
            db.flush()
        except ValueError as error:
            items.append(
                DocumentUploadItem(
                    file_name=filename,
                    order_number=target.order_number,
                    revision_number=target.revision_number,
                    accepted=False,
                    message=str(error),
                )
            )
            continue

        _audit(
            db,
            user=user,
            action=MasterDataAction.DOCUMENT_UPLOAD,
            entity_type=DOCUMENT_ENTITY,
            entity_id=document.id,
            entity_label=f"{DOCUMENT_LABEL} · {filename}",
            summary=(
                f"Attached {filename} ({_human_size(len(content))}) to {target.order_type} "
                f"{target.order_number} (Rev {target.revision_number}) by bulk upload"
            ),
            request=request,
        )
        uploaded += 1
        items.append(
            DocumentUploadItem(
                file_name=filename,
                order_number=target.order_number,
                revision_number=target.revision_number,
                document_id=document.id,
                accepted=True,
                message=f"Attached to {target.order_number} (Rev {target.revision_number})",
            )
        )

    _commit(db)
    return DocumentUploadResult(
        uploaded_count=uploaded,
        rejected_count=len(items) - uploaded,
        items=items,
    )


@router.get(
    "/po-so-orders/{order_id}/documents",
    response_model=list[DocumentOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_documents(order_id: str, db: Db, user: Current, include_deleted: bool = False) -> list[DocumentOut]:
    order = _order_or_404(db, order_id, user.organization_id)
    statement = select(OrderDocument).where(
        OrderDocument.order_id == order.id, OrderDocument.organization_id == user.organization_id
    )
    if not include_deleted:
        statement = statement.where(OrderDocument.is_deleted.is_(False))
    documents = db.scalars(statement.order_by(OrderDocument.created_at, OrderDocument.id)).all()
    return [_document_out(document, order) for document in documents]


@router.post(
    "/po-so-orders/{order_id}/documents",
    response_model=DocumentUploadResult,
    status_code=201,
    dependencies=[Depends(require("master-data:document-upload"))],
)
async def upload_documents(
    order_id: str,
    request: Request,
    db: Db,
    user: Current,
    files: list[UploadFile] = File(...),
    document_kind: str = Form("po_copy"),
    label: str = Form(""),
    notes: str = Form(""),
) -> DocumentUploadResult:
    """Attach one or more scanned copies to a PO/SO revision.

    Each file is reported on its own, so one rejected file (wrong type, empty,
    duplicate) never hides behind the files that were accepted.
    """
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    if document_kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=422, detail=f"Document kind must be one of {', '.join(DOCUMENT_KINDS)}")

    items: list[DocumentUploadItem] = []
    uploaded = 0
    for upload in files:
        filename = (upload.filename or "").strip()
        try:
            content, filename = _read_upload(upload)
            document = _store_document(
                db,
                order=order,
                user=user,
                content=content,
                filename=filename,
                content_type=upload.content_type or "application/octet-stream",
                document_kind=document_kind,
                label=label.strip(),
                notes=notes.strip(),
            )
            db.flush()
            _audit(
                db,
                user=user,
                action=MasterDataAction.DOCUMENT_UPLOAD,
                entity_type=DOCUMENT_ENTITY,
                entity_id=document.id,
                entity_label=f"{DOCUMENT_LABEL} · {filename}",
                summary=(
                    f"Attached {filename} ({_human_size(len(content))}) to {order.order_type} "
                    f"{order.order_number} (Rev {order.revision_number})"
                ),
                request=request,
            )
        except ValueError as error:
            items.append(
                DocumentUploadItem(
                    file_name=filename or "(unnamed)",
                    order_number=order.order_number,
                    revision_number=order.revision_number,
                    accepted=False,
                    message=str(error),
                )
            )
            continue

        uploaded += 1
        items.append(
            DocumentUploadItem(
                file_name=filename,
                order_number=order.order_number,
                revision_number=order.revision_number,
                document_id=document.id,
                accepted=True,
                message=f"Attached to {order.order_number} (Rev {order.revision_number})",
            )
        )

    if not uploaded:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="; ".join(f"{item.file_name}: {item.message}" for item in items) or "No file was attached",
        )
    _commit(db)
    # Per-file results, so one rejected file never hides behind the successful ones.
    return DocumentUploadResult(uploaded_count=uploaded, rejected_count=len(items) - uploaded, items=items)


@router.get(
    "/po-so-orders/documents/{document_id}",
    dependencies=[Depends(require("master-data:document-download"))],
)
def download_document(document_id: str, db: Db, user: Current, request: Request, inline: bool = False) -> Response:
    """Serve the stored bytes; ``inline=1`` previews PDFs and images in the browser."""
    document = _document_or_404(db, document_id, user.organization_id)
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_DOWNLOAD,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=(
            f"Downloaded {document.file_name} from {order.order_type} {order.order_number} "
            f"(Rev {document.revision_number})"
        ),
        request=request,
    )
    _commit(db)
    return Response(
        content=bytes(document.content),
        media_type=document.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition(
                "inline" if inline else "attachment", document.file_name
            ),
            "Content-Length": str(document.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch(
    "/po-so-orders/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_document(
    document_id: str,
    data: DocumentUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> DocumentOut:
    document = _document_or_404(db, document_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    mapping = {"document_kind": "document_kind", "label": "label", "notes": "description"}
    changed: list[str] = []
    for field, value in supplied.items():
        column = mapping[field]
        clean = "" if value is None else str(value).strip()
        if getattr(document, column) != clean:
            setattr(document, column, clean)
            changed.append(field)
    if changed:
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=DOCUMENT_ENTITY,
            entity_id=document.id,
            entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
            summary=f"Updated document details for {document.file_name}: {', '.join(sorted(changed))}",
            request=request,
        )
        _commit(db)
        db.refresh(document)
    return _document_out(document)


@router.delete(
    "/po-so-orders/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require("master-data:document-delete"))],
)
def soft_delete_document(document_id: str, request: Request, db: Db, user: Current) -> DocumentOut:
    document = _document_or_404(db, document_id, user.organization_id)
    if document.is_deleted:
        raise HTTPException(status_code=409, detail="This document is already in removed files")
    document.is_deleted = True
    document.deleted_at = datetime.now(timezone.utc)
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_DELETE,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=(
            f"Removed {document.file_name} from {order.order_type} {order.order_number} "
            f"(Rev {document.revision_number}); it stays recoverable"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(document)
    return _document_out(document)


@router.post(
    "/po-so-orders/documents/{document_id}/restore",
    response_model=DocumentOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_document(document_id: str, request: Request, db: Db, user: Current) -> DocumentOut:
    document = _document_or_404(db, document_id, user.organization_id)
    if not document.is_deleted:
        raise HTTPException(status_code=409, detail="Only a removed document can be restored")
    document.is_deleted = False
    document.deleted_at = None
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_RESTORE,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=f"Restored {document.file_name} to {order.order_type} {order.order_number}",
        request=request,
    )
    _commit(db)
    db.refresh(document)
    return _document_out(document)


@router.delete(
    "/po-so-orders/documents/{document_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_document(document_id: str, request: Request, db: Db, user: Current) -> None:
    document = _document_or_404(db, document_id, user.organization_id)
    if not document.is_deleted:
        raise HTTPException(status_code=409, detail="Only a removed document can be permanently deleted")
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_PERMANENT_DELETE,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=(
            f"Permanently deleted {document.file_name} ({_human_size(document.size_bytes)}) "
            f"from {order.order_type} {order.order_number}"
        ),
        request=request,
    )
    db.delete(document)
    _commit(db)
    return None
