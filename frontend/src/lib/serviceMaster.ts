// Typed contracts for the Services register in Master Data Management.

export type ServiceCategory = 'Drilling Services' | 'Completion Services'
export type ServiceProviderType = 'In House Services' | 'Third Party Services'

export type Service = {
  id: string
  service_code: string
  service_name: string
  service_category: ServiceCategory
  provider_type: ServiceProviderType
  vendor_id: string | null
  vendor_code: string | null
  vendor_name: string | null
  description: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export type ServiceBreakdown = { key: string; label: string; count: number }

export type ServiceOverview = {
  active_count: number
  deleted_count: number
  category_counts: ServiceBreakdown[]
  provider_type_counts: ServiceBreakdown[]
}

export const SERVICE_CATEGORIES: ServiceCategory[] = ['Drilling Services', 'Completion Services']
export const SERVICE_PROVIDER_TYPES: ServiceProviderType[] = ['In House Services', 'Third Party Services']

// The service_category column is optional so spreadsheets from the legacy
// register still import; blank/missing categories default to Drilling Services.
export const SERVICE_IMPORT_HEADERS = [
  'service_code', 'service_name', 'provider_type', 'vendor_code', 'description',
]
export const SERVICE_OPTIONAL_IMPORT_HEADERS = ['service_category']

export const emptyServiceForm = {
  service_code: '',
  service_name: '',
  service_category: 'Drilling Services' as ServiceCategory,
  provider_type: 'In House Services' as ServiceProviderType,
  vendor_id: '',
  description: '',
}

export type ServiceFormState = typeof emptyServiceForm

export const serviceToForm = (service: Service): ServiceFormState => ({
  service_code: service.service_code,
  service_name: service.service_name,
  service_category: service.service_category,
  provider_type: service.provider_type,
  vendor_id: service.vendor_id ?? '',
  description: service.description,
})

export const serviceFormToPayload = (form: ServiceFormState) => ({
  service_code: form.service_code.trim(),
  service_name: form.service_name.trim(),
  service_category: form.service_category,
  provider_type: form.provider_type,
  vendor_id: form.vendor_id || null,
  description: form.description.trim(),
})

export type ServicePayload = ReturnType<typeof serviceFormToPayload>
