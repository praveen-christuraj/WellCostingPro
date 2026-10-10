// Typed contracts and labels for the Vendors and PO/SO Orders tabs.
// Shapes mirror backend/app/schemas/vendor_master.py.

export type VendorType = 'Inhouse' | 'Third party'
export const VENDOR_TYPES: VendorType[] = ['Inhouse', 'Third party']

export type VendorStatus = 'active' | 'inactive' | 'blocked'
export type OrderType = 'PO' | 'SO' | 'Callout' | 'Others'
export type OrderStatus = 'open' | 'closed' | 'cancelled'
export type DocumentKind = 'po_copy' | 'signed_copy' | 'amendment_copy' | 'specification' | 'correspondence' | 'other'

export type Vendor = {
  vendor_type: VendorType
  id: string
  vendor_code: string
  vendor_name: string
  category: string
  contact_person: string
  email: string
  phone: string
  website: string
  country: string
  tax_registration_no: string
  address: string
  status: VendorStatus
  credit_terms_days: number | null
  description: string
  order_count: number
  document_count: number
  latest_order_date: string | null
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type VendorOption = {
  vendor_type: VendorType
  id: string
  vendor_code: string
  vendor_name: string
  status: VendorStatus
  order_count: number
  label: string
}

export type PoSoOrder = {
  id: string
  order_number: string
  order_type: OrderType
  vendor_id: string
  vendor_code: string
  vendor_name: string
  vendor_status: VendorStatus
  revision_number: number
  is_current: boolean
  revision_note: string
  parent_order_id: string | null
  issue_date: string | null
  expiry_date: string | null
  status: OrderStatus
  description: string
  document_count: number
  revision_count: number
  is_expired: boolean
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type OrderRevision = {
  id: string
  revision_number: number
  is_current: boolean
  revision_note: string
  issue_date: string | null
  status: OrderStatus
  document_count: number
  created_at: string
  updated_at: string
  is_deleted: boolean
}

export type OrderDocument = {
  id: string
  order_id: string
  order_number: string
  file_name: string
  content_type: string
  size_bytes: number
  checksum_sha256: string
  document_kind: DocumentKind
  label: string
  notes: string
  revision_number: number
  uploaded_by_name: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type DocumentUploadItem = {
  file_name: string
  order_number: string
  revision_number: number | null
  document_id: string | null
  accepted: boolean
  message: string
}

export type DocumentUploadResult = {
  uploaded_count: number
  rejected_count: number
  items: DocumentUploadItem[]
}

export type VendorPoCount = { key: string; label: string; count: number }

export type VendorPoOverview = {
  vendors_active: number
  vendors_inactive: number
  vendors_blocked: number
  vendors_deleted: number
  orders_active: number
  orders_amendments: number
  orders_deleted: number
  orders_by_type: VendorPoCount[]
  orders_by_status: VendorPoCount[]
  documents_active: number
  documents_deleted: number
  storage_bytes: number
  top_vendors: { vendor_id: string; vendor_code: string; vendor_name: string; order_count: number; document_count: number }[]
}

export const VENDOR_STATUSES: { value: VendorStatus; label: string; hint: string }[] = [
  { value: 'active', label: 'Active', hint: 'Can receive new PO/SO orders' },
  { value: 'inactive', label: 'Inactive', hint: 'Kept for reference; still selectable' },
  { value: 'blocked', label: 'Blocked', hint: 'New PO/SO orders are refused' },
]

export const VENDOR_CATEGORIES = [
  'Drilling', 'Completions', 'Well Services', 'Cementing', 'Mud & Chemicals', 'Casing & Tubulars', 'Bits & Tools',
  'Logistics & Transport', 'Equipment Rental', 'Catering & Camps', 'Inspection & Testing',
  'Engineering Services', 'Other',
]

export const ORDER_TYPES: OrderType[] = ['PO', 'SO', 'Callout', 'Others']

export const ORDER_STATUSES: { value: OrderStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
  { value: 'cancelled', label: 'Cancelled' },
]

export const DOCUMENT_KINDS: { value: DocumentKind; label: string }[] = [
  { value: 'po_copy', label: 'PO/SO copy' },
  { value: 'signed_copy', label: 'Signed copy' },
  { value: 'amendment_copy', label: 'Amendment copy' },
  { value: 'specification', label: 'Specification' },
  { value: 'correspondence', label: 'Correspondence' },
  { value: 'other', label: 'Other' },
]

// Mirrors the backend guard in app/api/vendor_master.py.
export const ACCEPTED_DOCUMENT_EXTENSIONS = '.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.rtf,.png,.jpg,.jpeg,.msg,.eml'
export const MAX_DOCUMENT_MB = 15

export const VENDOR_IMPORT_HEADERS = [
  'vendor_code', 'vendor_name', 'vendor_type', 'category', 'contact_person', 'email', 'phone',
  'website', 'country', 'tax_registration_no', 'address', 'status', 'credit_terms_days', 'description',
]

export const ORDER_IMPORT_HEADERS = [
  'order_number', 'order_type', 'vendor_code', 'issue_date', 'expiry_date', 'status', 'description',
]

export const vendorStatusLabel = (status: VendorStatus) =>
  VENDOR_STATUSES.find(item => item.value === status)?.label ?? status

export const orderStatusLabel = (status: OrderStatus) =>
  ORDER_STATUSES.find(item => item.value === status)?.label ?? status

export const documentKindLabel = (kind: DocumentKind) =>
  DOCUMENT_KINDS.find(item => item.value === kind)?.label ?? kind

export const revisionLabel = (order: Pick<PoSoOrder, 'revision_number' | 'is_current' | 'revision_count'>) =>
  order.revision_number === 0
    ? order.revision_count > 1 ? 'Original' : 'Original (no amendments)'
    : order.is_current ? `Revision ${order.revision_number} · current` : `Revision ${order.revision_number} · superseded`

export const formatBytes = (size: number) => {
  if (!size) return '0 KB'
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

export const canPreview = (contentType: string, fileName: string) =>
  contentType === 'application/pdf' || contentType.startsWith('image/') || /\.(png|jpe?g|pdf)$/i.test(fileName)

export const emptyVendorForm = {
  vendor_type: 'Third party' as VendorType,
  vendor_code: '', vendor_name: '', category: '', contact_person: '', email: '', phone: '',
  website: '', country: '', tax_registration_no: '', address: '', status: 'active' as VendorStatus,
  credit_terms_days: '', description: '',
}

export type VendorFormState = typeof emptyVendorForm

export const vendorToForm = (vendor: Vendor): VendorFormState => ({
  vendor_type: vendor.vendor_type,
  vendor_code: vendor.vendor_code,
  vendor_name: vendor.vendor_name,
  category: vendor.category,
  contact_person: vendor.contact_person,
  email: vendor.email,
  phone: vendor.phone,
  website: vendor.website,
  country: vendor.country,
  tax_registration_no: vendor.tax_registration_no,
  address: vendor.address,
  status: vendor.status,
  credit_terms_days: vendor.credit_terms_days === null ? '' : String(vendor.credit_terms_days),
  description: vendor.description,
})

export const vendorFormToPayload = (form: VendorFormState) => ({
  vendor_type: form.vendor_type,
  vendor_code: form.vendor_code.trim(),
  vendor_name: form.vendor_name.trim(),
  category: form.category.trim(),
  contact_person: form.contact_person.trim(),
  email: form.email.trim(),
  phone: form.phone.trim(),
  website: form.website.trim(),
  country: form.country.trim(),
  tax_registration_no: form.tax_registration_no.trim(),
  address: form.address.trim(),
  status: form.status,
  credit_terms_days: form.credit_terms_days.trim() === '' ? null : Number(form.credit_terms_days),
  description: form.description.trim(),
})

export type VendorPayload = ReturnType<typeof vendorFormToPayload>

export const emptyOrderForm = {
  order_number: '',
  order_type: 'PO' as OrderType,
  vendor_id: '',
  issue_date: '',
  expiry_date: '',
  status: 'open' as OrderStatus,
  description: '',
  revision_note: '',
  copy_documents: true,
}

export type OrderFormState = typeof emptyOrderForm

export const orderToForm = (order: PoSoOrder): OrderFormState => ({
  order_number: order.order_number,
  order_type: order.order_type,
  vendor_id: order.vendor_id,
  issue_date: order.issue_date ?? '',
  expiry_date: order.expiry_date ?? '',
  status: order.status,
  description: order.description,
  revision_note: '',
  copy_documents: true,
})

export type OrderPayload = {
  order_number: string
  order_type: OrderType
  vendor_id: string
  issue_date: string | null
  expiry_date: string | null
  status: OrderStatus
  description: string
}

export const orderFormToPayload = (form: OrderFormState): OrderPayload => ({
  order_number: form.order_number.trim(),
  order_type: form.order_type,
  vendor_id: form.vendor_id,
  issue_date: form.issue_date || null,
  expiry_date: form.expiry_date || null,
  status: form.status,
  description: form.description.trim(),
})

export type AmendmentPayload = {
  revision_note: string
  order_type: OrderType
  issue_date: string | null
  expiry_date: string | null
  status: OrderStatus
  description: string
  copy_documents: boolean
}

export const orderFormToAmendment = (form: OrderFormState): AmendmentPayload => ({
  revision_note: form.revision_note.trim(),
  order_type: form.order_type,
  issue_date: form.issue_date || null,
  expiry_date: form.expiry_date || null,
  status: form.status,
  description: form.description.trim(),
  copy_documents: form.copy_documents,
})
