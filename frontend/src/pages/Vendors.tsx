import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, DescriptionOutlined, EditOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Chip, CircularProgress, Paper, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { VendorFormDialog } from '../components/VendorFormDialog'
import { VendorPoKpis } from '../components/VendorPoKpis'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  VENDOR_IMPORT_HEADERS,
  emptyVendorForm,
  vendorStatusLabel,
  vendorToForm,
  type Vendor,
  type VendorFormState,
  type VendorPayload,
} from '../lib/vendorMaster'

export default function Vendors() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [rows, setRows] = useState<Vendor[]>([])
  const [selectedRows, setSelectedRows] = useState<Vendor[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Vendor | null>(null)
  const [form, setFormState] = useState<VendorFormState>(emptyVendorForm)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<Vendor | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const setForm = useCallback((patch: Partial<VendorFormState>) => {
    setFormState(current => ({ ...current, ...patch }))
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<Vendor[]>('/master-data/vendors'))
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load vendors')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setFormState(emptyVendorForm)
    setFormError('')
    setFormOpen(true)
  }

  const openEdit = (vendor: Vendor) => {
    setFormRecord(vendor)
    setFormState(vendorToForm(vendor))
    setFormError('')
    setFormOpen(true)
  }

  const save = async (payload: VendorPayload) => {
    setSaving(true)
    setFormError('')
    try {
      if (formRecord) {
        await api(`/master-data/vendors/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`Vendor ${payload.vendor_code} updated.`)
      } else {
        await api('/master-data/vendors', { method: 'POST', body: body(payload) })
        setNotice(`Vendor ${payload.vendor_code} created. You can now add its PO/SO orders.`)
      }
      setFormOpen(false)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this vendor')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (vendor?: Vendor) => {
    setDeleteRecord(vendor ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const ids = deleteRecord ? [deleteRecord.id] : selectedRows.map(vendor => vendor.id)
    try {
      if (deleteRecord) {
        await api(`/master-data/vendors/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api('/master-data/vendors/bulk-delete', { method: 'POST', body: body({ ids }) })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setNotice(`${ids.length} ${ids.length === 1 ? 'vendor was' : 'vendors were'} moved to deleted entries.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these vendors to deleted entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<{ imported_count: number; error_count: number; errors: string[] }>(
      '/master-data/vendors/import',
      { method: 'POST', body: body({ rows: importedRows }) },
    )
    await load()
    if (result.imported_count) setNotice(`Imported ${result.imported_count} vendor ${result.imported_count === 1 ? 'record' : 'records'}.`)
    if (!result.error_count) return []
    return [`Imported ${result.imported_count} of ${importedRows.length} rows. Resolve the row issues below and re-import the failed rows.`, ...result.errors]
  }

  const logExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/master-data/export-audit', {
      method: 'POST',
      body: body({ module: 'vendors', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<Vendor>[]>(() => [
    { headerName: 'CODE', field: 'vendor_code', minWidth: 120, flex: .7 },
    { headerName: 'VENDOR TYPE', field: 'vendor_type', minWidth: 140 },
    { headerName: 'VENDOR NAME', field: 'vendor_name', minWidth: 200, flex: 1.3 },
    { headerName: 'CATEGORY', field: 'category', minWidth: 130, flex: .8, valueFormatter: params => params.value || '—' },
    { headerName: 'CONTACT', field: 'contact_person', minWidth: 140, flex: .9, valueFormatter: params => params.value || '—' },
    { headerName: 'EMAIL', field: 'email', minWidth: 170, flex: 1, valueFormatter: params => params.value || '—' },
    { headerName: 'PHONE', field: 'phone', minWidth: 130, flex: .8, valueFormatter: params => params.value || '—' },
    { headerName: 'COUNTRY', field: 'country', minWidth: 110, flex: .7, valueFormatter: params => params.value || '—' },
    {
      headerName: 'STATUS', field: 'status', minWidth: 105, maxWidth: 130,
      valueFormatter: params => vendorStatusLabel(params.value),
      cellRenderer: ({ value }: { value: string }) => <Chip
        size="small"
        label={vendorStatusLabel(value as Vendor['status'])}
        color={value === 'active' ? 'success' : value === 'blocked' ? 'error' : 'default'}
        variant={value === 'active' ? 'filled' : 'outlined'}
        sx={{ height: 22, fontSize: 11 }}
      />,
    },
    { headerName: 'PO/SO', field: 'order_count', minWidth: 85, maxWidth: 110 },
    { headerName: 'FILES', field: 'document_count', minWidth: 85, maxWidth: 110 },
    { headerName: 'LATEST ORDER', field: 'latest_order_date', minWidth: 125, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 125, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 250, minWidth: 250, maxWidth: 250, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Vendor }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('master-data:update') && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data.vendor_code}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        <Button size="small" color="inherit" onClick={() => navigate(`/master-data/po-so-orders?vendor=${encodeURIComponent(data.vendor_code)}`)} aria-label={`PO/SO orders of ${data.vendor_code}`} startIcon={<DescriptionOutlined sx={{ fontSize: 15 }}/>}>PO/SO</Button>
        {can('master-data:delete') && <Button size="small" color="error" onClick={() => openDelete(data)} aria-label={`Delete ${data.vendor_code}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can, navigate])

  const blockedCount = rows.filter(vendor => vendor.status === 'blocked').length

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / VENDORS"
      title="Vendors"
      subtitle="Add and maintain the suppliers first; every PO/SO order is filed against one of them."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/master-data/po-so-orders" variant="outlined" startIcon={<DescriptionOutlined/>}>PO/SO orders</Button>
        <Button component={RouterLink} to="/master-data/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('master-data:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add vendor</Button>}
      </Box>}
    />

    <VendorPoKpis active="vendors"/>

    <Paper variant="outlined" sx={{ borderRadius: 2, borderColor: 'divider', overflow: 'hidden' }}>
      <MasterDataTabs active="vendors"/>
      <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>Vendor register</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>
              {rows.length} active {rows.length === 1 ? 'vendor' : 'vendors'}{blockedCount ? ` · ${blockedCount} blocked` : ''}. Use the header checkbox to select all matching rows.
            </Typography>
          </Box>
          {can('master-data:delete') && <Button color="error" variant="outlined" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>
            Move {selectedRows.length || ''} to deleted entries
          </Button>}
        </Box>
        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
        <ErrorMessage message={error}/>
        {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
          rows={rows}
          columns={columns}
          searchPlaceholder="Search vendors by code, name, contact, country..."
          exportName="vendors"
          onImport={can('master-data:import') ? () => setImportOpen(true) : undefined}
          canExport={can('master-data:export')}
          onExport={logExport}
          selectable={can('master-data:delete')}
          onSelectionChange={setSelectedRows}
        />}
      </Box>
    </Paper>

    <VendorFormDialog
      open={formOpen}
      title={formRecord ? `Edit vendor ${formRecord.vendor_code}` : 'Add vendor'}
      subtitle="Workspace-scoped, audit-logged vendor master data."
      form={form}
      setForm={setForm}
      busy={saving}
      error={formError}
      onClose={() => { if (!saving) setFormOpen(false) }}
      onSubmit={payload => void save(payload)}
    />

    <FormDialog
      open={deleteOpen}
      title="Move vendors to deleted entries?"
      subtitle="This is a soft delete. Vendors with active PO/SO orders or active service assignments stay until those records are moved to deleted entries."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to deleted entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {deleteRecord
            ? `“${deleteRecord.vendor_code} — ${deleteRecord.vendor_name}” (${deleteRecord.order_count} PO/SO ${deleteRecord.order_count === 1 ? 'order' : 'orders'}, ${deleteRecord.document_count} files) will be moved to deleted entries.`
            : `${selectedRows.length} selected ${selectedRows.length === 1 ? 'vendor' : 'vendors'} will be moved to deleted entries.`}
        </Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import vendors"
      subtitle="Preview and validate rows before adding or updating vendors. Existing codes are updated; matching deleted entries are restored. Legacy headers (vendor_code, vendor_name, contact, description) are accepted."
      headers={VENDOR_IMPORT_HEADERS.filter(header => header !== 'vendor_type')}
      optionalHeaders={['vendor_type']}
      sample={{
        vendor_type: 'Third party', vendor_code: 'VEND-01', vendor_name: 'Acme Drilling Services', category: 'Drilling',
        contact_person: 'Ada Lovelace', email: 'ada@acme.example', phone: '+971 50 000 0000',
        website: 'acme.example', country: 'UAE', tax_registration_no: 'TRN-100200300',
        address: 'Unit 12, Industrial Area', status: 'active', credit_terms_days: '30',
        description: 'Directional drilling crews',
      }}
      templateName="vendors-template.csv"
      onRows={importRows}
    />
  </>
}
