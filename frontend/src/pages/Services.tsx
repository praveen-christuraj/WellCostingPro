import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, EditOutlined, StorefrontOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { ServiceFormDialog } from '../components/ServiceFormDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  SERVICE_IMPORT_HEADERS,
  SERVICE_OPTIONAL_IMPORT_HEADERS,
  emptyServiceForm,
  serviceToForm,
  type Service,
  type ServiceFormState,
  type ServiceOverview,
  type ServicePayload,
} from '../lib/serviceMaster'
import type { VendorOption } from '../lib/vendorMaster'

function StatCard({ label, value, hint }: { label: string; value: number; hint: string }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 27, my: 1 }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

export default function Services() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Service[]>([])
  const [vendors, setVendors] = useState<VendorOption[]>([])
  const [overview, setOverview] = useState<ServiceOverview | null>(null)
  const [selectedRows, setSelectedRows] = useState<Service[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Service | null>(null)
  const [form, setForm] = useState<ServiceFormState>(emptyServiceForm)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<Service | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [services, vendorOptions, summary] = await Promise.all([
        api<Service[]>('/master-data/services'),
        api<VendorOption[]>('/master-data/vendors/options'),
        api<ServiceOverview>('/master-data/services/overview'),
      ])
      setRows(services)
      setVendors(vendorOptions)
      setOverview(summary)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load Services')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptyServiceForm)
    setFormError('')
    setFormOpen(true)
  }

  const openEdit = (service: Service) => {
    setFormRecord(service)
    setForm(serviceToForm(service))
    setFormError('')
    setFormOpen(true)
  }

  const save = async (payload: ServicePayload) => {
    setSaving(true)
    setFormError('')
    try {
      if (formRecord) {
        await api(`/master-data/services/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${formRecord.service_code} was updated.`)
      } else {
        const created = await api<Service>('/master-data/services', { method: 'POST', body: body(payload) })
        setNotice(`${created.service_code} was created.`)
      }
      setFormOpen(false)
      setFormRecord(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this service')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (service?: Service) => {
    setDeleteRecord(service ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/master-data/services/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api('/master-data/services/bulk-delete', {
          method: 'POST',
          body: body({ ids: targets.map(service => service.id) }),
        })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(`${targets.length} ${targets.length === 1 ? 'service was' : 'services were'} moved to Deleted Entries.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these services to Deleted Entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<{ imported_count: number; error_count: number; errors: string[] }>(
      '/master-data/services/import',
      { method: 'POST', body: body({ rows: importedRows }) },
    )
    await load()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} services.`)
    if (!result.error_count) return []
    return [
      `Imported ${result.imported_count} of ${importedRows.length} rows. Resolve the row issues below and re-import the failed rows.`,
      ...result.errors,
    ]
  }

  const logExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/master-data/export-audit', {
      method: 'POST',
      body: body({ module: 'services', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<Service>[]>(() => [
    { headerName: 'SERVICE CODE', field: 'service_code', minWidth: 125, flex: .7 },
    { headerName: 'SERVICE NAME', field: 'service_name', minWidth: 190, flex: 1.2 },
    { headerName: 'SERVICE CATEGORY', field: 'service_category', minWidth: 165, flex: .95 },
    { headerName: 'PROVIDER TYPE', field: 'provider_type', minWidth: 125, flex: .8 },
    {
      headerName: 'VENDOR / PROVIDER', field: 'vendor_name', minWidth: 190, flex: 1,
      valueFormatter: params => params.data?.vendor_name
        ? `${params.data.vendor_code ? `${params.data.vendor_code} — ` : ''}${params.data.vendor_name}`
        : 'Vendor assignment required',
    },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 190, flex: 1.2, valueFormatter: params => params.value || '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 135, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 185, minWidth: 185, maxWidth: 185, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Service }) => <Box display="flex" alignItems="center" height="100%" gap={.3}>
        {can('master-data:update') && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data.service_code}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('master-data:delete') && <Button size="small" color="error" onClick={() => openDelete(data)} aria-label={`Delete ${data.service_code}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can])

  const categoryCount = (label: string) => overview?.category_counts.find(item => item.label === label)?.count ?? 0
  const providerCount = (label: string) => overview?.provider_type_counts.find(item => item.label === label)?.count ?? 0

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / SERVICE REGISTER"
      title="Services"
      subtitle="Maintain the drilling and completion services available to your workspace, with clear in-house and third-party ownership."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/master-data/vendors" variant="outlined" startIcon={<StorefrontOutlined/>}>Vendors</Button>
        <Button component={RouterLink} to="/master-data/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('master-data:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add service</Button>}
      </Box>}
    />

    {overview && <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(3, 1fr)', lg: 'repeat(5, 1fr)' }, mb: 2.5 }}>
      <StatCard label="Active services" value={overview.active_count} hint={`${overview.deleted_count} retained in Deleted Entries`}/>
      <StatCard label="Drilling services" value={categoryCount('Drilling Services')} hint="Active drilling service records"/>
      <StatCard label="Completion services" value={categoryCount('Completion Services')} hint="Active completion service records"/>
      <StatCard label="In House Services" value={providerCount('In House Services')} hint="Delivered by internal teams"/>
      <StatCard label="Third Party Services" value={providerCount('Third Party Services')} hint="Linked to workspace vendors"/>
    </Box>}

    <Paper variant="outlined" sx={{ borderRadius: 2, borderColor: 'divider', overflow: 'hidden' }}>
      <MasterDataTabs active="services"/>
      <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>Service register</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>
              {rows.length} active {rows.length === 1 ? 'service' : 'services'}. Enter service codes manually and select a vendor for both provider types.
            </Typography>
          </Box>
          {can('master-data:delete') && <Button
            color="error"
            variant="outlined"
            startIcon={<DeleteOutlineRounded/>}
            disabled={!selectedRows.length}
            onClick={() => openDelete()}
          >Move {selectedRows.length || ''} to deleted entries</Button>}
        </Box>
        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
        <ErrorMessage message={error}/>
        {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
          rows={rows}
          columns={columns}
          searchPlaceholder="Search services by code, name, category, provider, or vendor..."
          exportName="services"
          onImport={can('master-data:import') ? () => setImportOpen(true) : undefined}
          canExport={can('master-data:export')}
          onExport={logExport}
          selectable={can('master-data:delete')}
          onSelectionChange={setSelectedRows}
        />}
      </Box>
    </Paper>

    <ServiceFormDialog
      open={formOpen}
      title={formRecord ? `Edit service ${formRecord.service_code}` : 'Add service'}
      subtitle="Workspace-scoped, auditable service master data."
      form={form}
      setForm={patch => setForm(current => ({ ...current, ...patch }))}
      vendors={vendors}
      busy={saving}
      error={formError}
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={payload => void save(payload)}
    />

    <FormDialog
      open={deleteOpen}
      title="Move services to Deleted Entries?"
      subtitle="This is a soft delete. Restore the service or permanently remove it from Deleted Entries."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {deleteRecord
            ? `“${deleteRecord.service_code} — ${deleteRecord.service_name}” will be moved to Deleted Entries.`
            : `${selectedRows.length} selected ${selectedRows.length === 1 ? 'service' : 'services'} will be moved to Deleted Entries.`}
        </Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import services"
      subtitle="Preview rows before import. Service codes and vendors are required. Existing codes are updated and deleted matches are restored. The category column is optional for legacy spreadsheets and defaults to Drilling Services; legacy Inhouse and 3rd Party labels are accepted."
      headers={SERVICE_IMPORT_HEADERS}
      optionalHeaders={SERVICE_OPTIONAL_IMPORT_HEADERS}
      sample={{
        service_code: 'MUD-LOG',
        service_name: 'Mud Logging',
        service_category: 'Drilling Services',
        provider_type: 'Third Party Services',
        vendor_code: 'VEND-01',
        description: 'Mud logging while drilling',
      }}
      templateName="services-template.csv"
      onRows={importRows}
    />
  </>
}
