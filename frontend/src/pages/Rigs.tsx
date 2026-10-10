import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, EditOutlined, OpenInNewRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  emptyRigForm,
  RIG_IMPORT_HEADERS,
  RIG_IMPORT_OPTIONAL_HEADERS,
  type ImportResult,
  type Rig,
  type RigPayload,
} from '../lib/rigWell'

export default function Rigs() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Rig[]>([])
  const [selectedRows, setSelectedRows] = useState<Rig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Rig | null>(null)
  const [form, setForm] = useState<RigPayload>(emptyRigForm)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<Rig | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<Rig[]>('/rig-well/rigs'))
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Rigs could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptyRigForm())
    setFormError('')
    setFormOpen(true)
  }

  const openEdit = (rig: Rig) => {
    setFormRecord(rig)
    setForm({ rig_code: rig.rig_code, rig_name: rig.rig_name, remarks: rig.remarks })
    setFormError('')
    setFormOpen(true)
  }

  const save = async () => {
    setSaving(true)
    setFormError('')
    const payload = { rig_code: form.rig_code.trim(), rig_name: form.rig_name.trim(), remarks: form.remarks.trim() }
    try {
      if (formRecord) {
        await api(`/rig-well/rigs/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${formRecord.rig_code} was updated.`)
      } else {
        const created = await api<Rig>('/rig-well/rigs', { method: 'POST', body: body(payload) })
        setNotice(`${created.rig_code} was created.`)
      }
      setFormOpen(false)
      setFormRecord(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this rig')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (rig?: Rig) => {
    setDeleteRecord(rig ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/rig-well/rigs/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api('/rig-well/rigs/bulk-delete', { method: 'POST', body: body({ ids: targets.map(rig => rig.id) }) })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(`${targets.length} ${targets.length === 1 ? 'rig was' : 'rigs were'} moved to Deleted Entries.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these rigs to Deleted Entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<ImportResult>('/rig-well/rigs/import', { method: 'POST', body: body({ rows: importedRows }) })
    await load()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} rigs.`)
    if (!result.error_count) return []
    return [
      `Imported or updated ${result.imported_count} of ${importedRows.length} rows. Resolve the issues below and re-import failed rows.`,
      ...result.errors,
    ]
  }

  const onExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/rig-well/export-audit', {
      method: 'POST',
      body: body({ module: 'rigs', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<Rig>[]>(() => [
    { headerName: 'RIG CODE', field: 'rig_code', minWidth: 130, flex: .8 },
    { headerName: 'RIG NAME', field: 'rig_name', minWidth: 200, flex: 1.2 },
    { headerName: 'ACTIVE WELLS', field: 'well_count', minWidth: 115, maxWidth: 140, valueFormatter: params => Number(params.value ?? 0).toLocaleString() },
    { headerName: 'REMARKS', field: 'remarks', minWidth: 200, flex: 1.2, valueFormatter: params => params.value || '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 140, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 170, minWidth: 170, maxWidth: 170, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Rig }) => data && <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('rig-well:update') && <Button size="small" aria-label={`Edit rig ${data.rig_code}`} onClick={() => openEdit(data)} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('rig-well:delete') && <Button size="small" color="error" aria-label={`Delete rig ${data.rig_code}`} onClick={() => openDelete(data)} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can])

  return <>
    <PageHeading
      eyebrow="RIG & WELL MANAGEMENT / ASSET REGISTER"
      title="Rigs"
      subtitle="Create the operational rigs that own and organize workspace wells. Rig codes are unique within the workspace."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/rig-well/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('rig-well:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add rig</Button>}
      </Box>}
    />

    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 2, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box><Typography fontWeight={800} fontSize={15}>Rig register</Typography><Typography color="text.secondary" fontSize={12} mt={.35}>{rows.length} active {rows.length === 1 ? 'rig' : 'rigs'} in this workspace.</Typography></Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          <Button component={RouterLink} to="/rig-well/wells" size="small" variant="outlined" endIcon={<OpenInNewRounded sx={{ fontSize: 16 }}/>}>View wells</Button>
          {can('rig-well:delete') && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>Move {selectedRows.length || ''} to Deleted Entries</Button>}
        </Box>
      </Box>
    </Paper>

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      rows={rows}
      columns={columns}
      searchPlaceholder="Search rigs by code, name, or remarks..."
      exportName="rig-register"
      onImport={can('rig-well:import') ? () => setImportOpen(true) : undefined}
      canExport={can('rig-well:export')}
      onExport={onExport}
      selectable={can('rig-well:delete')}
      onSelectionChange={setSelectedRows}
    />}

    <FormDialog
      open={formOpen}
      title={formRecord ? `Edit rig ${formRecord.rig_code}` : 'Add rig'}
      subtitle="Workspace-scoped rig information. Wells are assigned after a rig is created."
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={() => void save()}
      busy={saving}
      submitDisabled={!form.rig_code.trim() || !form.rig_name.trim()}
      submitLabel={formRecord ? 'Save changes' : 'Create rig'}
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Rig code" required fullWidth value={form.rig_code} onChange={event => setForm({ ...form, rig_code: event.target.value })} inputProps={{ maxLength: 50 }} helperText="A workspace-unique code, normalized to uppercase."/>
        <TextField label="Rig name" required fullWidth value={form.rig_name} onChange={event => setForm({ ...form, rig_name: event.target.value })} inputProps={{ maxLength: 200 }}/>
        <TextField label="Remarks" fullWidth multiline minRows={2} value={form.remarks} onChange={event => setForm({ ...form, remarks: event.target.value })} inputProps={{ maxLength: 1000 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={deleteOpen}
      title="Move rig to Deleted Entries?"
      subtitle="A rig can be removed only after its active wells are moved to Deleted Entries. This is a soft delete; restoration remains available."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>{deleteRecord ? `“${deleteRecord.rig_code} — ${deleteRecord.rig_name}” will be moved to Deleted Entries.` : `${selectedRows.length} selected rigs will be moved to Deleted Entries.`}</Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import rigs"
      subtitle="Preview spreadsheet rows before import. Existing rig codes are updated; a matching deleted rig is restored."
      headers={RIG_IMPORT_HEADERS}
      optionalHeaders={RIG_IMPORT_OPTIONAL_HEADERS}
      sample={{ rig_code: 'RIG-001', rig_name: 'North Field Drilling Rig', remarks: 'Primary land rig' }}
      templateName="rig-register-template.csv"
      onRows={importRows}
    />
  </>
}
