import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { DeleteForeverOutlined, EditOutlined, RestoreOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { MASTER_DATA_MODULES, type DeletedMasterDataRecord, type MasterDataModule, type MasterDataModuleKey, type MasterDataRecord } from '../lib/masterData'

const moduleFor = (key: MasterDataModuleKey): MasterDataModule =>
  MASTER_DATA_MODULES.find(module => module.key === key) ?? MASTER_DATA_MODULES[0]

export default function DeletedMasterData() {
  const { can } = useAuth()
  const [rows, setRows] = useState<DeletedMasterDataRecord[]>([])
  const [selectedRows, setSelectedRows] = useState<DeletedMasterDataRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editRecord, setEditRecord] = useState<DeletedMasterDataRecord | null>(null)
  const [form, setForm] = useState({ code: '', name: '', symbol: '', description: '' })
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [permanentRecord, setPermanentRecord] = useState<DeletedMasterDataRecord | null>(null)
  const [permanentOpen, setPermanentOpen] = useState(false)
  const [permanentError, setPermanentError] = useState('')
  const [permanentlyDeleting, setPermanentlyDeleting] = useState(false)
  const [restoring, setRestoring] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const groups = await Promise.all(MASTER_DATA_MODULES.map(async module => {
        const deleted = await api<MasterDataRecord[]>(`/master-data/${module.key}/deleted`)
        return deleted.map(record => ({
          ...record,
          module_key: module.key,
          module_label: module.label,
        }))
      }))
      setRows(groups.flat().sort((left, right) => new Date(right.deleted_at ?? 0).getTime() - new Date(left.deleted_at ?? 0).getTime()))
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load deleted entries')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openEdit = (record: DeletedMasterDataRecord) => {
    setEditRecord(record)
    setForm({ code: record.code, name: record.name, symbol: record.symbol ?? '', description: record.description ?? '' })
    setFormError('')
  }

  const saveEdit = async () => {
    if (!editRecord) return
    const module = moduleFor(editRecord.module_key)
    setSaving(true)
    setFormError('')
    const payload = {
      code: form.code.trim(),
      name: form.name.trim(),
      ...(module.hasSymbol ? { symbol: form.symbol.trim() || form.code.trim() } : {}),
      description: form.description.trim(),
    }
    try {
      await api(`/master-data/${module.key}/${editRecord.id}`, { method: 'PATCH', body: body(payload) })
      setEditRecord(null)
      setNotice(`${module.label} deleted entry updated.`)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not update this deleted entry')
    } finally {
      setSaving(false)
    }
  }

  const restore = async (record?: DeletedMasterDataRecord) => {
    const targets = record ? [record] : selectedRows
    if (!targets.length) return
    setRestoring(true)
    setError('')
    try {
      if (record) {
        await api(`/master-data/${record.module_key}/${record.id}/restore`, { method: 'POST' })
      } else {
        await api('/master-data/bulk-restore', {
          method: 'POST',
          body: body({ records: targets.map(item => ({ module: item.module_key, id: item.id })) }),
        })
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

  const openPermanentDelete = (record?: DeletedMasterDataRecord) => {
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
        await api(`/master-data/${permanentRecord.module_key}/${permanentRecord.id}/permanent`, { method: 'DELETE' })
      } else {
        await api('/master-data/bulk-permanent-delete', {
          method: 'POST',
          body: body({ records: targets.map(item => ({ module: item.module_key, id: item.id })) }),
        })
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

  const columns = useMemo<ColDef<DeletedMasterDataRecord>[]>(() => [
    { headerName: 'MODULE', field: 'module_label', minWidth: 135, flex: .8 },
    { headerName: 'CODE', field: 'code', minWidth: 125, flex: .8 },
    { headerName: 'NAME', field: 'name', minWidth: 175, flex: 1.1 },
    { headerName: 'SYMBOL', field: 'symbol', minWidth: 90, maxWidth: 110, valueFormatter: params => params.value || '—' },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 180, flex: 1.2, valueFormatter: params => params.value || '—' },
    { headerName: 'DELETED', field: 'deleted_at', minWidth: 165, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : '' },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: DeletedMasterDataRecord }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('master-data:update') && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data.code}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('master-data:restore') && <Button size="small" onClick={() => restore(data)} disabled={restoring} aria-label={`Restore ${data.code}`} startIcon={<RestoreOutlined sx={{ fontSize: 15 }}/>}>Restore</Button>}
        {can('master-data:permanent-delete') && <Button size="small" color="error" onClick={() => openPermanentDelete(data)} aria-label={`Permanently delete ${data.code}`} startIcon={<DeleteForeverOutlined sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can, restore, restoring])

  const moduleForEdit = editRecord ? moduleFor(editRecord.module_key) : null
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
          {rows.length} deleted {rows.length === 1 ? 'entry' : 'entries'} across the five reference lists. Use row checkboxes or the header checkbox to select entries for bulk actions.
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
      open={!!editRecord}
      title={`Edit deleted ${moduleForEdit?.label ?? 'master data'} entry`}
      subtitle="Changes are saved while the entry remains in Deleted Entries. Restore it separately when ready."
      onClose={() => { if (!saving) setEditRecord(null) }}
      onSubmit={saveEdit}
      busy={saving}
      submitLabel="Save changes"
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Code" required fullWidth value={form.code} onChange={event => setForm({ ...form, code: event.target.value })} inputProps={{ maxLength: moduleForEdit?.key === 'currencies' ? 10 : 50 }}/>
        <TextField label="Name" required fullWidth value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} inputProps={{ maxLength: moduleForEdit?.key === 'currencies' ? 100 : 150 }}/>
        {moduleForEdit?.hasSymbol && <TextField label="Symbol" required fullWidth value={form.symbol} onChange={event => setForm({ ...form, symbol: event.target.value })} inputProps={{ maxLength: moduleForEdit.key === 'currencies' ? 20 : 50 }}/>}
        <TextField label="Description" fullWidth multiline minRows={2} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 500 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={permanentOpen}
      title="Permanently delete entries?"
      subtitle="This cannot be undone. Only soft-deleted records can be permanently removed."
      onClose={() => { if (!permanentlyDeleting) { setPermanentOpen(false); setPermanentRecord(null) } }}
      onSubmit={confirmPermanentDelete}
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
