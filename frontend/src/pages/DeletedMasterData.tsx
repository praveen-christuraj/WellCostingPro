import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { DeleteForeverOutlined, EditOutlined, RestoreOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, TextField, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { VendorFormDialog } from '../components/VendorFormDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { MASTER_DATA_MODULES, type MasterDataModule, type MasterDataModuleKey, type MasterDataRecord } from '../lib/masterData'
import { vendorToForm, type PoSoOrder, type Vendor, type VendorFormState, type VendorPayload } from '../lib/vendorMaster'

const moduleFor = (key: MasterDataModuleKey): MasterDataModule =>
  MASTER_DATA_MODULES.find(module => module.key === key) ?? MASTER_DATA_MODULES[0]

// One row shape for every soft-deleted record in the module, whatever its table.
type DeletedRow = {
  id: string
  kind: 'reference' | 'vendors' | 'po-so'
  module_key: string
  module_label: string
  code: string
  name: string
  symbol: string | null
  description: string
  is_deleted: boolean
  deleted_at: string | null
  created_at: string
  updated_at: string
}

const referenceRow = (record: MasterDataRecord, module: MasterDataModule): DeletedRow => ({
  ...record, kind: 'reference', module_key: module.key, module_label: module.label,
})

const vendorRow = (vendor: Vendor): DeletedRow => ({
  id: vendor.id, kind: 'vendors', module_key: 'vendors', module_label: 'Vendors',
  code: vendor.vendor_code, name: vendor.vendor_name, symbol: null, description: vendor.description,
  is_deleted: vendor.is_deleted, deleted_at: vendor.deleted_at, created_at: vendor.created_at, updated_at: vendor.updated_at,
})

const orderRow = (order: PoSoOrder): DeletedRow => ({
  id: order.id, kind: 'po-so', module_key: 'po-so-orders', module_label: 'PO/SO Orders',
  code: `${order.order_number} · Rev ${order.revision_number}`, name: `${order.order_type} — ${order.vendor_code} ${order.vendor_name}`,
  symbol: null, description: order.description,
  is_deleted: order.is_deleted, deleted_at: order.deleted_at, created_at: order.created_at, updated_at: order.updated_at,
})

export default function DeletedMasterData() {
  const { can } = useAuth()
  const [rows, setRows] = useState<DeletedRow[]>([])
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [selectedRows, setSelectedRows] = useState<DeletedRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editRecord, setEditRecord] = useState<DeletedRow | null>(null)
  const [form, setForm] = useState({ code: '', name: '', symbol: '', description: '' })
  const [vendorForm, setVendorForm] = useState<VendorFormState | null>(null)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [permanentRecord, setPermanentRecord] = useState<DeletedRow | null>(null)
  const [permanentOpen, setPermanentOpen] = useState(false)
  const [permanentError, setPermanentError] = useState('')
  const [permanentlyDeleting, setPermanentlyDeleting] = useState(false)
  const [restoring, setRestoring] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [referenceGroups, deletedVendors, deletedOrders] = await Promise.all([
        Promise.all(MASTER_DATA_MODULES.map(async module => {
          const deleted = await api<MasterDataRecord[]>(`/master-data/${module.key}/deleted`)
          return deleted.map(record => referenceRow(record, module))
        })),
        api<Vendor[]>('/master-data/vendors/deleted'),
        api<PoSoOrder[]>('/master-data/po-so-orders/deleted'),
      ])
      setVendors(deletedVendors)
      setRows([
        ...referenceGroups.flat(),
        ...deletedVendors.map(vendorRow),
        ...deletedOrders.map(orderRow),
      ].sort((left, right) => new Date(right.deleted_at ?? 0).getTime() - new Date(left.deleted_at ?? 0).getTime()))
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load deleted entries')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openEdit = (record: DeletedRow) => {
    setEditRecord(record)
    setFormError('')
    if (record.kind === 'vendors') {
      const vendor = vendors.find(item => item.id === record.id)
      if (vendor) setVendorForm(vendorToForm(vendor))
      return
    }
    setVendorForm(null)
    setForm({ code: record.code, name: record.name, symbol: record.symbol ?? '', description: record.description ?? '' })
  }

  const saveEdit = async () => {
    if (!editRecord) return
    setSaving(true)
    setFormError('')
    try {
      if (editRecord.kind === 'vendors' && vendorForm) {
        const payload: VendorPayload = {
          vendor_code: vendorForm.vendor_code.trim(),
          vendor_name: vendorForm.vendor_name.trim(),
          category: vendorForm.category.trim(),
          contact_person: vendorForm.contact_person.trim(),
          email: vendorForm.email.trim(),
          phone: vendorForm.phone.trim(),
          website: vendorForm.website.trim(),
          country: vendorForm.country.trim(),
          tax_registration_no: vendorForm.tax_registration_no.trim(),
          address: vendorForm.address.trim(),
          status: vendorForm.status,
          credit_terms_days: vendorForm.credit_terms_days.trim() === '' ? null : Number(vendorForm.credit_terms_days),
          description: vendorForm.description.trim(),
        }
        await api(`/master-data/vendors/${editRecord.id}`, { method: 'PATCH', body: body(payload) })
      } else {
        const module = moduleFor(editRecord.module_key as MasterDataModuleKey)
        const payload = {
          code: form.code.trim(),
          name: form.name.trim(),
          ...(module.hasSymbol ? { symbol: form.symbol.trim() || form.code.trim() } : {}),
          description: form.description.trim(),
        }
        await api(`/master-data/${module.key}/${editRecord.id}`, { method: 'PATCH', body: body(payload) })
      }
      setEditRecord(null)
      setVendorForm(null)
      setNotice('Deleted entry updated. Restore it when it is ready to be used again.')
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not update this deleted entry')
    } finally {
      setSaving(false)
    }
  }

  const restoreOne = async (record: DeletedRow) => {
    if (record.kind === 'vendors') await api(`/master-data/vendors/${record.id}/restore`, { method: 'POST' })
    else if (record.kind === 'po-so') await api(`/master-data/po-so-orders/${record.id}/restore`, { method: 'POST' })
    else await api(`/master-data/${record.module_key}/${record.id}/restore`, { method: 'POST' })
  }

  const restore = async (record?: DeletedRow) => {
    const targets = record ? [record] : selectedRows
    if (!targets.length) return
    setRestoring(true)
    setError('')
    try {
      if (record) {
        await restoreOne(record)
      } else {
        // Bulk endpoints exist per table, so group the selection and send each group.
        const groups = {
          reference: targets.filter(item => item.kind === 'reference'),
          vendors: targets.filter(item => item.kind === 'vendors'),
          'po-so': targets.filter(item => item.kind === 'po-so'),
        }
        if (groups.reference.length) {
          await api('/master-data/bulk-restore', {
            method: 'POST',
            body: body({ records: groups.reference.map(item => ({ module: item.module_key, id: item.id })) }),
          })
        }
        if (groups.vendors.length) {
          await api('/master-data/vendors/bulk-restore', { method: 'POST', body: body({ ids: groups.vendors.map(item => item.id) }) })
        }
        if (groups['po-so'].length) {
          await api('/master-data/po-so-orders/bulk-restore', { method: 'POST', body: body({ ids: groups['po-so'].map(item => item.id) }) })
        }
      }
      setNotice(`${targets.length} ${targets.length === 1 ? 'entry was' : 'entries were'} restored to active master data.`)
      setSelectedRows([])
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not restore the selected entries')
    } finally {
      setRestoring(false)
    }
  }

  const openPermanentDelete = (record?: DeletedRow) => {
    setPermanentRecord(record ?? null)
    setPermanentError('')
    setPermanentOpen(true)
  }

  const confirmPermanentDelete = async () => {
    setPermanentlyDeleting(true)
    setPermanentError('')
    const targets = permanentRecord ? [permanentRecord] : selectedRows
    try {
      if (permanentRecord) {
        if (permanentRecord.kind === 'vendors') await api(`/master-data/vendors/${permanentRecord.id}/permanent`, { method: 'DELETE' })
        else if (permanentRecord.kind === 'po-so') await api(`/master-data/po-so-orders/${permanentRecord.id}/permanent`, { method: 'DELETE' })
        else await api(`/master-data/${permanentRecord.module_key}/${permanentRecord.id}/permanent`, { method: 'DELETE' })
      } else {
        const groups = {
          reference: targets.filter(item => item.kind === 'reference'),
          vendors: targets.filter(item => item.kind === 'vendors'),
          'po-so': targets.filter(item => item.kind === 'po-so'),
        }
        if (groups.reference.length) {
          await api('/master-data/bulk-permanent-delete', {
            method: 'POST',
            body: body({ records: groups.reference.map(item => ({ module: item.module_key, id: item.id })) }),
          })
        }
        if (groups.vendors.length) {
          await api('/master-data/vendors/bulk-permanent-delete', { method: 'POST', body: body({ ids: groups.vendors.map(item => item.id) }) })
        }
        if (groups['po-so'].length) {
          await api('/master-data/po-so-orders/bulk-permanent-delete', { method: 'POST', body: body({ ids: groups['po-so'].map(item => item.id) }) })
        }
      }
      setPermanentOpen(false)
      setPermanentRecord(null)
      setSelectedRows([])
      setNotice(`${targets.length} ${targets.length === 1 ? 'entry was' : 'entries were'} permanently deleted.`)
      await load()
    } catch (caught) {
      setPermanentError(caught instanceof Error ? caught.message : 'Could not permanently delete the selected entries')
    } finally {
      setPermanentlyDeleting(false)
    }
  }

  const logExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/master-data/export-audit', {
      method: 'POST',
      body: body({ module: 'all', format, record_count: recordCount, include_deleted: true }),
    })
  }

  const columns = useMemo<ColDef<DeletedRow>[]>(() => [
    { headerName: 'MODULE', field: 'module_label', minWidth: 135, flex: .8 },
    { headerName: 'CODE', field: 'code', minWidth: 140, flex: .8 },
    { headerName: 'NAME', field: 'name', minWidth: 190, flex: 1.1 },
    { headerName: 'SYMBOL', field: 'symbol', minWidth: 90, maxWidth: 110, valueFormatter: params => params.value || '—' },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 180, flex: 1.2, valueFormatter: params => params.value || '—' },
    { headerName: 'DELETED', field: 'deleted_at', minWidth: 165, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : '' },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: DeletedRow }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('master-data:update') && data.kind !== 'po-so' && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data.code}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('master-data:restore') && <Button size="small" onClick={() => void restore(data)} disabled={restoring} aria-label={`Restore ${data.code}`} startIcon={<RestoreOutlined sx={{ fontSize: 15 }}/>}>Restore</Button>}
        {can('master-data:permanent-delete') && <Tooltip title={data.kind === 'vendors' ? 'Its PO/SO orders must be permanently deleted first' : ''}>
          <span><Button size="small" color="error" onClick={() => openPermanentDelete(data)} aria-label={`Permanently delete ${data.code}`} startIcon={<DeleteForeverOutlined sx={{ fontSize: 15 }}/>}>Delete</Button></span>
        </Tooltip>}
      </Box>,
    },
  ], [can, restoring])

  const editModule = editRecord && editRecord.kind === 'reference' ? moduleFor(editRecord.module_key as MasterDataModuleKey) : null
  const dataActionAvailable = can('master-data:restore') || can('master-data:permanent-delete')

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / DELETED ENTRIES"
      title="Deleted entries"
      subtitle="Soft-deleted records are retained here. Restore them or permanently delete them when approved."
      action={<Button component={RouterLink} to="/master-data/records" variant="outlined" startIcon={<RestoreOutlined/>}>Active master data</Button>}
    />
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
      <Box>
        <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>Deleted master data</Typography>
        <Typography color="text.secondary" fontSize={12} mt={.35}>
          {rows.length} deleted {rows.length === 1 ? 'entry' : 'entries'} across the reference lists, vendors and PO/SO orders. Use row checkboxes or the header checkbox to select entries for bulk actions.
        </Typography>
      </Box>
      <Box display="flex" gap={1} flexWrap="wrap">
        {can('master-data:restore') && <Button variant="outlined" startIcon={<RestoreOutlined/>} disabled={!selectedRows.length || restoring} onClick={() => void restore()}>
          Restore {selectedRows.length || ''} selected
        </Button>}
        {can('master-data:permanent-delete') && <Button color="error" variant="outlined" startIcon={<DeleteForeverOutlined/>} disabled={!selectedRows.length} onClick={() => openPermanentDelete()}>
          Delete {selectedRows.length || ''} permanently
        </Button>}
      </Box>
    </Box>

    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      rows={rows}
      columns={columns}
      searchPlaceholder="Search deleted entries..."
      exportName="master-data-deleted"
      canExport={can('master-data:export')}
      onExport={logExport}
      selectable={dataActionAvailable}
      onSelectionChange={setSelectedRows}
    />}

    <FormDialog
      open={!!editRecord && editRecord.kind !== 'vendors'}
      title={`Edit deleted ${editModule?.label ?? 'master data'} entry`}
      subtitle="Changes are saved while the entry remains in Deleted Entries. Restore it separately when ready."
      onClose={() => { if (!saving) setEditRecord(null) }}
      onSubmit={() => void saveEdit()}
      busy={saving}
      submitLabel="Save changes"
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Code" required fullWidth value={form.code} onChange={event => setForm({ ...form, code: event.target.value })} inputProps={{ maxLength: editModule?.key === 'currencies' ? 10 : 50 }}/>
        <TextField label="Name" required fullWidth value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} inputProps={{ maxLength: editModule?.key === 'currencies' ? 100 : 150 }}/>
        {editModule?.hasSymbol && <TextField label="Symbol" required fullWidth value={form.symbol} onChange={event => setForm({ ...form, symbol: event.target.value })} inputProps={{ maxLength: editModule.key === 'currencies' ? 20 : 50 }}/>}
        <TextField label="Description" fullWidth multiline minRows={2} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 500 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    {vendorForm && <VendorFormDialog
      open={!!editRecord && editRecord.kind === 'vendors'}
      title={`Edit deleted vendor ${editRecord?.code ?? ''}`}
      subtitle="Changes are saved while the vendor remains in Deleted Entries. Restore it separately when ready."
      form={vendorForm}
      setForm={patch => setVendorForm(current => (current ? { ...current, ...patch } : current))}
      busy={saving}
      error={formError}
      onClose={() => { if (!saving) { setEditRecord(null); setVendorForm(null) } }}
      onSubmit={() => void saveEdit()}
    />}

    <FormDialog
      open={permanentOpen}
      title="Permanently delete entries?"
      subtitle="This cannot be undone. Only soft-deleted records can be permanently removed."
      onClose={() => { if (!permanentlyDeleting) { setPermanentOpen(false); setPermanentRecord(null) } }}
      onSubmit={() => void confirmPermanentDelete()}
      busy={permanentlyDeleting}
      submitLabel="Permanently delete"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {permanentRecord
            ? `“${permanentRecord.module_label}: ${permanentRecord.code} — ${permanentRecord.name}” will be removed permanently.`
            : `${selectedRows.length} selected ${selectedRows.length === 1 ? 'entry' : 'entries'} will be removed permanently.`}
        </Typography>
        <ErrorMessage message={permanentError}/>
      </Box>
    </FormDialog>
  </>
}
