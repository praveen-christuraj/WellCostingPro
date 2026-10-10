import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, EditOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import { MASTER_DATA_MODULES, type MasterDataModule, type MasterDataModuleKey, type MasterDataRecord } from '../lib/masterData'

const moduleFor = (key: string | null): MasterDataModule =>
  MASTER_DATA_MODULES.find(module => module.key === key) ?? MASTER_DATA_MODULES[0]

export default function MasterDataRecords() {
  const { can } = useAuth()
  const [searchParams] = useSearchParams()
  const currentModule = moduleFor(searchParams.get('module'))
  const moduleKey: MasterDataModuleKey = currentModule.key
  const [rows, setRows] = useState<MasterDataRecord[]>([])
  const [selectedRows, setSelectedRows] = useState<MasterDataRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null)
  const [formRecord, setFormRecord] = useState<MasterDataRecord | null>(null)
  const [form, setForm] = useState({ code: '', name: '', symbol: '', description: '' })
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<MasterDataRecord | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const records = await api<MasterDataRecord[]>(`/master-data/${moduleKey}`)
      setRows(records)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load master data')
    } finally {
      setLoading(false)
    }
  }, [moduleKey])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setForm({ code: '', name: '', symbol: '', description: '' })
    setFormError('')
    setFormMode('create')
  }

  const openEdit = (record: MasterDataRecord) => {
    setFormRecord(record)
    setForm({ code: record.code, name: record.name, symbol: record.symbol ?? '', description: record.description ?? '' })
    setFormError('')
    setFormMode('edit')
  }

  const save = async () => {
    setSaving(true)
    setFormError('')
    const payload = {
      code: form.code.trim(),
      name: form.name.trim(),
      ...(currentModule.hasSymbol ? { symbol: form.symbol.trim() || form.code.trim() } : {}),
      description: form.description.trim(),
    }
    try {
      if (formMode === 'create') {
        await api(`/master-data/${moduleKey}`, { method: 'POST', body: body(payload) })
        setNotice(`${currentModule.label} record created.`)
      } else if (formMode === 'edit' && formRecord) {
        await api(`/master-data/${moduleKey}/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${currentModule.label} record updated.`)
      }
      setFormMode(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this record')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (record?: MasterDataRecord) => {
    setDeleteRecord(record ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const ids = deleteRecord ? [deleteRecord.id] : selectedRows.map(record => record.id)
    try {
      if (deleteRecord) {
        await api(`/master-data/${moduleKey}/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api(`/master-data/${moduleKey}/bulk-delete`, { method: 'POST', body: body({ ids }) })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(`${ids.length} ${ids.length === 1 ? 'record was' : 'records were'} moved to deleted entries.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these records to deleted entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<{ imported_count: number; error_count: number; errors: string[] }>(
      `/master-data/${moduleKey}/import`,
      { method: 'POST', body: body({ rows: importedRows }) },
    )
    await load()
    if (result.imported_count) {
      setNotice(`Imported ${result.imported_count} ${currentModule.label.toLowerCase()} ${result.imported_count === 1 ? 'record' : 'records'}.`)
    }
    if (!result.error_count) return []
    return [`Imported ${result.imported_count} of ${importedRows.length} rows. Resolve the row issues below and re-import the failed rows.`, ...result.errors]
  }

  const logExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api(`/master-data/export-audit`, {
      method: 'POST',
      body: body({ module: moduleKey, format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<MasterDataRecord>[]>(() => [
    { headerName: 'CODE', field: 'code', minWidth: 130, flex: .8 },
    { headerName: 'NAME', field: 'name', minWidth: 190, flex: 1.2 },
    ...(currentModule.hasSymbol ? [{ headerName: 'SYMBOL', field: 'symbol', minWidth: 100, flex: .6 } as ColDef<MasterDataRecord>] : []),
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 200, flex: 1.4, valueFormatter: params => params.value || '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 140, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 180, minWidth: 180, maxWidth: 180, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: MasterDataRecord }) => <Box display="flex" alignItems="center" height="100%" gap={.3}>
        {can('master-data:update') && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data.code}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('master-data:delete') && <Button size="small" color="error" onClick={() => openDelete(data)} aria-label={`Delete ${data.code}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can, currentModule])

  const importHeaders = ['code', 'name', ...(currentModule.hasSymbol ? ['symbol'] : []), 'description']
  const importSample: ImportRow = {
    code: currentModule.hasSymbol ? 'SAMPLE' : 'PHASE1',
    name: currentModule.hasSymbol ? `Sample ${currentModule.label}` : 'Sample record',
    ...(currentModule.hasSymbol ? { symbol: 'SMP' } : {}),
    description: 'Optional description',
  }

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / REFERENCE DATA"
      title="Master data"
      subtitle="Maintain the workspace reference lists used across well-costing workflows."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/master-data/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('master-data:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add {currentModule.label}</Button>}
      </Box>}
    />

    <Paper variant="outlined" sx={{ borderRadius: 2, borderColor: 'divider', overflow: 'hidden' }}>
      <MasterDataTabs active={moduleKey}/>

      <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>{currentModule.title}</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>
              {rows.length} active {rows.length === 1 ? 'record' : 'records'}. Use the header checkbox to select all matching rows.
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
          key={moduleKey}
          rows={rows}
          columns={columns}
          searchPlaceholder={`Search ${currentModule.label.toLowerCase()}...`}
          exportName={`master-data-${moduleKey}`}
          onImport={can('master-data:import') ? () => setImportOpen(true) : undefined}
          canExport={can('master-data:export')}
          onExport={logExport}
          selectable={can('master-data:delete')}
          onSelectionChange={setSelectedRows}
        />}
      </Box>
    </Paper>

    <FormDialog
      open={formMode !== null}
      title={formMode === 'create' ? `Add ${currentModule.label}` : `Edit ${currentModule.label}`}
      subtitle={`Workspace-scoped, audit-logged ${currentModule.title.toLowerCase()} reference data.`}
      onClose={() => { if (!saving) setFormMode(null) }}
      onSubmit={save}
      busy={saving}
      submitLabel={formMode === 'create' ? 'Create record' : 'Save changes'}
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Code" required fullWidth value={form.code} onChange={event => setForm({ ...form, code: event.target.value })} inputProps={{ maxLength: currentModule.key === 'currencies' ? 10 : 50 }}/>
        <TextField label="Name" required fullWidth value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} inputProps={{ maxLength: currentModule.key === 'currencies' ? 100 : 150 }}/>
        {currentModule.hasSymbol && <TextField label="Symbol" required fullWidth helperText="If left blank, the code is used as the symbol." value={form.symbol} onChange={event => setForm({ ...form, symbol: event.target.value })} inputProps={{ maxLength: currentModule.key === 'currencies' ? 20 : 50 }}/>}
        <TextField label="Description" fullWidth multiline minRows={2} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 500 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={deleteOpen}
      title="Move to deleted entries?"
      subtitle="This is a soft delete. You can restore the record or permanently delete it from Deleted Entries."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={confirmDelete}
      busy={deleting}
      submitLabel="Move to deleted entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {deleteRecord
            ? `“${deleteRecord.code} — ${deleteRecord.name}” will be moved to deleted entries.`
            : `${selectedRows.length} selected ${selectedRows.length === 1 ? 'record' : 'records'} will be moved to deleted entries.`}
        </Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title={`Import ${currentModule.label}`}
      subtitle="Preview and validate rows before adding or updating workspace master data. Existing codes are updated; matching deleted entries are restored."
      headers={importHeaders}
      sample={importSample}
      templateName={`master-data-${moduleKey}-template.csv`}
      onRows={importRows}
    />
  </>
}
