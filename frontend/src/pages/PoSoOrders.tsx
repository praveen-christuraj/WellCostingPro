import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { AddRounded, AttachFileRounded, DeleteOutlineRounded, EditOutlined, HistoryOutlined, StorefrontOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Checkbox, Chip, CircularProgress, FormControlLabel, MenuItem, Paper, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { OrderDocumentsDialog } from '../components/OrderDocumentsDialog'
import { OrderFormDialog } from '../components/OrderFormDialog'
import { VendorPoKpis } from '../components/VendorPoKpis'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  ORDER_IMPORT_HEADERS,
  ORDER_STATUSES,
  ORDER_TYPES,
  emptyOrderForm,
  orderStatusLabel,
  orderToForm,
  revisionLabel,
  type AmendmentPayload,
  type OrderFormState,
  type OrderPayload,
  type PoSoOrder,
  type VendorOption,
} from '../lib/vendorMaster'

export default function PoSoOrders() {
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [rows, setRows] = useState<PoSoOrder[]>([])
  const [vendors, setVendors] = useState<VendorOption[]>([])
  const [selectedRows, setSelectedRows] = useState<PoSoOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [vendorFilter, setVendorFilter] = useState(searchParams.get('vendor') ?? '')
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [currentOnly, setCurrentOnly] = useState(false)
  const [formMode, setFormMode] = useState<'create' | 'edit' | 'amend' | null>(null)
  const [formRecord, setFormRecord] = useState<PoSoOrder | null>(null)
  const [form, setFormState] = useState<OrderFormState>(emptyOrderForm)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [documentsFor, setDocumentsFor] = useState<PoSoOrder | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<PoSoOrder | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const setForm = useCallback((patch: Partial<OrderFormState>) => {
    setFormState(current => ({ ...current, ...patch }))
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [orders, options] = await Promise.all([
        api<PoSoOrder[]>('/master-data/po-so-orders'),
        api<VendorOption[]>('/master-data/vendors/options'),
      ])
      setRows(orders)
      setVendors(options)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load PO/SO orders')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const filtered = useMemo(() => rows.filter(order => {
    if (vendorFilter && order.vendor_code !== vendorFilter) return false
    if (typeFilter && order.order_type !== typeFilter) return false
    if (statusFilter && order.status !== statusFilter) return false
    if (currentOnly && !order.is_current) return false
    return true
  }), [rows, vendorFilter, typeFilter, statusFilter, currentOnly])

  const openCreate = () => {
    const preferred = vendors.find(vendor => vendor.vendor_code === vendorFilter)
    setFormRecord(null)
    setFormState({ ...emptyOrderForm, vendor_id: preferred?.id ?? '' })
    setFormError('')
    setFormMode('create')
  }

  const openEdit = (order: PoSoOrder) => {
    setFormRecord(order)
    setFormState(orderToForm(order))
    setFormError('')
    setFormMode('edit')
  }

  const openAmend = (order: PoSoOrder) => {
    setFormRecord(order)
    setFormState({ ...orderToForm(order), revision_note: '', copy_documents: true })
    setFormError('')
    setFormMode('amend')
  }

  const save = async (payload: OrderPayload | AmendmentPayload) => {
    setSaving(true)
    setFormError('')
    try {
      if (formMode === 'amend' && formRecord) {
        const created = await api<PoSoOrder>(`/master-data/po-so-orders/${formRecord.id}/amendment`, { method: 'POST', body: body(payload) })
        setNotice(`Revision ${created.revision_number} of ${created.order_number} created${'copy_documents' in payload && payload.copy_documents ? ' with the previous files carried over' : ''}.`)
      } else if (formMode === 'edit' && formRecord) {
        await api(`/master-data/po-so-orders/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${formRecord.order_number} (Rev ${formRecord.revision_number}) updated.`)
      } else if (formMode === 'create') {
        const created = await api<PoSoOrder>('/master-data/po-so-orders', { method: 'POST', body: body(payload) })
        setNotice(`${created.order_type} ${created.order_number} created. Attach the scanned copy from the Files action.`)
      }
      setFormMode(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this order')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (order?: PoSoOrder) => {
    setDeleteRecord(order ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const ids = deleteRecord ? [deleteRecord.id] : selectedRows.map(order => order.id)
    try {
      if (deleteRecord) {
        await api(`/master-data/po-so-orders/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api('/master-data/po-so-orders/bulk-delete', { method: 'POST', body: body({ ids }) })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setNotice(`${ids.length} ${ids.length === 1 ? 'order was' : 'orders were'} moved to deleted entries. Attached files stay recoverable.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these orders to deleted entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<{ imported_count: number; error_count: number; errors: string[] }>(
      '/master-data/po-so-orders/import',
      { method: 'POST', body: body({ rows: importedRows }) },
    )
    await load()
    if (result.imported_count) setNotice(`Imported ${result.imported_count} PO/SO ${result.imported_count === 1 ? 'order' : 'orders'}.`)
    if (!result.error_count) return []
    return [`Imported ${result.imported_count} of ${importedRows.length} rows. Resolve the row issues below and re-import the failed rows.`, ...result.errors]
  }

  const logExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/master-data/export-audit', {
      method: 'POST',
      body: body({ module: 'po-so-orders', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<PoSoOrder>[]>(() => [
    { headerName: 'ORDER NUMBER', field: 'order_number', minWidth: 150, flex: .9 },
    { headerName: 'TYPE', field: 'order_type', minWidth: 85, maxWidth: 110 },
    { headerName: 'VENDOR', field: 'vendor_code', minWidth: 115, flex: .7 },
    { headerName: 'VENDOR NAME', field: 'vendor_name', minWidth: 170, flex: 1 },
    { headerName: 'REVISION', field: 'revision_number', minWidth: 150, valueFormatter: params => (params.data ? revisionLabel(params.data) : ''), cellRenderer: ({ data }: { data: PoSoOrder }) => <Chip size="small" label={revisionLabel(data)} color={data.is_current ? 'primary' : 'default'} variant={data.is_current ? 'filled' : 'outlined'} sx={{ height: 22, fontSize: 11 }}/> },
    { headerName: 'ISSUE DATE', field: 'issue_date', minWidth: 120, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '—' },
    { headerName: 'VALID UNTIL', field: 'expiry_date', minWidth: 130, valueFormatter: params => params.value ? `${new Date(params.value).toLocaleDateString()}${params.data?.is_expired ? ' (expired)' : ''}` : '—' },
    { headerName: 'STATUS', field: 'status', minWidth: 105, maxWidth: 130, valueFormatter: params => orderStatusLabel(params.value) },
    { headerName: 'FILES', field: 'document_count', minWidth: 80, maxWidth: 105 },
    { headerName: 'SCOPE', field: 'description', minWidth: 180, flex: 1.1, valueFormatter: params => params.value || '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 120, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: PoSoOrder }) => <Box display="flex" alignItems="center" height="100%" gap={.1}>
        <Button size="small" onClick={() => setDocumentsFor(data)} aria-label={`Files of ${data.order_number}`} startIcon={<AttachFileRounded sx={{ fontSize: 15 }}/>}>Files</Button>
        {can('master-data:create') && <Button size="small" color="inherit" onClick={() => openAmend(data)} aria-label={`Amend ${data.order_number}`} startIcon={<HistoryOutlined sx={{ fontSize: 15 }}/>}>Amend</Button>}
        {can('master-data:update') && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data.order_number}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('master-data:delete') && <Button size="small" color="error" onClick={() => openDelete(data)} aria-label={`Delete ${data.order_number}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can])

  const clearVendorFilter = () => {
    setVendorFilter('')
    const next = new URLSearchParams(searchParams)
    next.delete('vendor')
    setSearchParams(next, { replace: true })
  }

  const amendments = rows.filter(order => order.revision_number > 0).length

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / PO-SO ORDERS"
      title="PO/SO Orders"
      subtitle="File every purchase and service order against its vendor, keep each amendment as a revision, and attach the scanned copies for reference."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/master-data/vendors" variant="outlined" startIcon={<StorefrontOutlined/>}>Vendors</Button>
        <Button component={RouterLink} to="/master-data/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('master-data:create') && <Button variant="contained" startIcon={<AddRounded/>} disabled={!vendors.length} onClick={openCreate}>Add PO/SO order</Button>}
      </Box>}
    />

    <VendorPoKpis active="orders"/>

    <Paper variant="outlined" sx={{ borderRadius: 2, borderColor: 'divider', overflow: 'hidden' }}>
      <MasterDataTabs active="po-so-orders"/>
      <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
        <Box display="flex" gap={1.2} flexWrap="wrap" alignItems="center" mb={1.5}>
          <TextField select size="small" label="Vendor" value={vendorFilter} onChange={event => setVendorFilter(event.target.value)} sx={{ minWidth: 220 }}>
            <MenuItem value="">All vendors</MenuItem>
            {vendors.map(vendor => <MenuItem key={vendor.id} value={vendor.vendor_code}>{vendor.label}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Type" value={typeFilter} onChange={event => setTypeFilter(event.target.value)} sx={{ minWidth: 130 }}>
            <MenuItem value="">All types</MenuItem>
            {ORDER_TYPES.map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}
          </TextField>
          <TextField select size="small" label="Status" value={statusFilter} onChange={event => setStatusFilter(event.target.value)} sx={{ minWidth: 140 }}>
            <MenuItem value="">Any status</MenuItem>
            {ORDER_STATUSES.map(status => <MenuItem key={status.value} value={status.value}>{status.label}</MenuItem>)}
          </TextField>
          <FormControlLabel
            control={<Checkbox checked={currentOnly} onChange={event => setCurrentOnly(event.target.checked)}/>}
            label={<Typography fontSize={12.5}>Current revisions only</Typography>}
          />
          {(vendorFilter || typeFilter || statusFilter || currentOnly) && <Button size="small" color="inherit" onClick={() => { clearVendorFilter(); setTypeFilter(''); setStatusFilter(''); setCurrentOnly(false) }}>Clear</Button>}
        </Box>

        <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>Order register</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>
              {filtered.length} of {rows.length} {rows.length === 1 ? 'revision' : 'revisions'}{amendments ? ` · ${amendments} amendments` : ''}. Use the header checkbox to select all matching rows.
            </Typography>
          </Box>
          {can('master-data:delete') && <Button color="error" variant="outlined" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>
            Move {selectedRows.length || ''} to deleted entries
          </Button>}
        </Box>
        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
        <ErrorMessage message={error}/>
        {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
          rows={filtered}
          columns={columns}
          searchPlaceholder="Search by order number, vendor, scope..."
          exportName="po-so-orders"
          onImport={can('master-data:import') ? () => setImportOpen(true) : undefined}
          canExport={can('master-data:export')}
          onExport={logExport}
          selectable={can('master-data:delete')}
          onSelectionChange={setSelectedRows}
        />}
      </Box>
    </Paper>

    <OrderFormDialog
      open={formMode !== null}
      mode={formMode ?? 'create'}
      order={formRecord}
      vendors={vendors}
      form={form}
      setForm={setForm}
      busy={saving}
      error={formError}
      onClose={() => { if (!saving) setFormMode(null) }}
      onSubmit={payload => void save(payload)}
    />

    <OrderDocumentsDialog
      open={!!documentsFor}
      order={documentsFor}
      onClose={() => setDocumentsFor(null)}
      onChanged={() => { void load() }}
    />

    <FormDialog
      open={deleteOpen}
      title="Move orders to deleted entries?"
      subtitle="This is a soft delete. Attached files stay with the order and can be restored from Deleted Entries."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to deleted entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {deleteRecord
            ? `“${deleteRecord.order_type} ${deleteRecord.order_number} — revision ${deleteRecord.revision_number}” (${deleteRecord.vendor_code}, ${deleteRecord.document_count} files) will be moved to deleted entries.`
            : `${selectedRows.length} selected ${selectedRows.length === 1 ? 'revision' : 'revisions'} will be moved to deleted entries.`}
        </Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import PO/SO orders"
      subtitle="Creates or updates the original (revision 0) of each order. Amendments are raised with Create amendment so their reason is recorded. Dates accept YYYY-MM-DD, DD/MM/YYYY and Excel serials."
      headers={ORDER_IMPORT_HEADERS}
      sample={{
        order_number: 'PO-2026-001', order_type: 'PO', vendor_code: 'VEND-01',
        issue_date: '2026-01-15', expiry_date: '2026-12-31', status: 'open',
        description: 'Rig move and 3 wells',
      }}
      templateName="po-so-orders-template.csv"
      onRows={importRows}
    />
  </>
}
