import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, EditOutlined, OpenInNewRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, useFormDirty } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  BLOCK_IMPORT_HEADERS,
  BLOCK_IMPORT_OPTIONAL_HEADERS,
  emptyBlockForm,
  type Block,
  type BlockPayload,
  type ImportResult,
} from '../lib/rigWell'

export default function Blocks() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Block[]>([])
  const [selectedRows, setSelectedRows] = useState<Block[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Block | null>(null)
  const [form, setForm] = useState<BlockPayload>(emptyBlockForm)
  const formDirty = useFormDirty(form, formOpen)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<Block | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<Block[]>('/rig-well/blocks'))
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Blocks could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptyBlockForm())
    setFormError('')
    setFormOpen(true)
  }

  const openEdit = (block: Block) => {
    setFormRecord(block)
    setForm({ block_code: block.block_code, block_name: block.block_name, description: block.description })
    setFormError('')
    setFormOpen(true)
  }

  const save = async () => {
    setSaving(true)
    setFormError('')
    const payload = {
      block_code: form.block_code.trim(),
      block_name: form.block_name.trim(),
      description: form.description.trim(),
    }
    try {
      if (formRecord) {
        await api(`/rig-well/blocks/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${formRecord.block_code} was updated.`)
      } else {
        const created = await api<Block>('/rig-well/blocks', { method: 'POST', body: body(payload) })
        setNotice(`${created.block_code} was created.`)
      }
      setFormOpen(false)
      setFormRecord(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this block')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (block?: Block) => {
    setDeleteRecord(block ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/rig-well/blocks/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api('/rig-well/blocks/bulk-delete', { method: 'POST', body: body({ ids: targets.map(block => block.id) }) })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(`${targets.length} ${targets.length === 1 ? 'block was' : 'blocks were'} moved to Deleted Entries.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these blocks to Deleted Entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<ImportResult>('/rig-well/blocks/import', { method: 'POST', body: body({ rows: importedRows }) })
    await load()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} blocks.`)
    if (!result.error_count) return []
    return [
      `Imported or updated ${result.imported_count} of ${importedRows.length} rows. Resolve the issues below and re-import failed rows.`,
      ...result.errors,
    ]
  }

  const onExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/rig-well/export-audit', {
      method: 'POST',
      body: body({ module: 'blocks', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<Block>[]>(() => [
    { headerName: 'BLOCK CODE', field: 'block_code', minWidth: 130, flex: .8 },
    { headerName: 'BLOCK NAME', field: 'block_name', minWidth: 210, flex: 1.2 },
    { headerName: 'WELLS', field: 'well_count', minWidth: 100, maxWidth: 120, valueFormatter: params => Number(params.value ?? 0).toLocaleString() },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 240, flex: 1.4, valueFormatter: params => params.value || '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 140, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 170, minWidth: 170, maxWidth: 170, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Block }) => data && <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('rig-well:update') && <Button size="small" aria-label={`Edit block ${data.block_code}`} onClick={() => openEdit(data)} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('rig-well:delete') && <Button size="small" color="error" aria-label={`Delete block ${data.block_code}`} onClick={() => openDelete(data)} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can])

  return <>
    <PageHeading
      eyebrow="RIG & WELL MANAGEMENT / ASSET REGISTER"
      title="Blocks"
      subtitle="Create the concession / field blocks that group workspace wells. Well records choose their block from this register, and the well register is segregated by block."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/rig-well/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('rig-well:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add block</Button>}
      </Box>}
    />

    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 2, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box><Typography fontWeight={800} fontSize={15}>Block register</Typography><Typography color="text.secondary" fontSize={12} mt={.35}>{rows.length} active {rows.length === 1 ? 'block' : 'blocks'} · {rows.reduce((total, block) => total + Number(block.well_count ?? 0), 0)} active wells assigned.</Typography></Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          <Button component={RouterLink} to="/rig-well/wells" size="small" variant="outlined" endIcon={<OpenInNewRounded sx={{ fontSize: 16 }}/>}>View wells by block</Button>
          {can('rig-well:delete') && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>Move {selectedRows.length || ''} to Deleted Entries</Button>}
        </Box>
      </Box>
    </Paper>

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      fillHeight
      rows={rows}
      columns={columns}
      searchPlaceholder="Search blocks by code, name, or description..."
      exportName="block-register"
      onImport={can('rig-well:import') ? () => setImportOpen(true) : undefined}
      canExport={can('rig-well:export')}
      onExport={onExport}
      selectable={can('rig-well:delete')}
      onSelectionChange={setSelectedRows}
    />}

    <FormDialog
      open={formOpen}
      title={formRecord ? `Edit block ${formRecord.block_code}` : 'Add block'}
      subtitle="Workspace-scoped block information. Wells are assigned to a block after it is created."
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={() => void save()}
      busy={saving}
      dirty={formDirty}
      submitDisabled={!form.block_code.trim() || !form.block_name.trim()}
      submitLabel={formRecord ? 'Save changes' : 'Create block'}
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Block code" required fullWidth value={form.block_code} onChange={event => setForm({ ...form, block_code: event.target.value })} inputProps={{ maxLength: 50 }} helperText="A workspace-unique code, normalized to uppercase."/>
        <TextField label="Block name" required fullWidth value={form.block_name} onChange={event => setForm({ ...form, block_name: event.target.value })} inputProps={{ maxLength: 200 }}/>
        <TextField label="Description" fullWidth multiline minRows={2} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 1000 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={deleteOpen}
      title="Move block to Deleted Entries?"
      subtitle="A block can be removed only after its wells are moved to Deleted Entries or reassigned to another block. This is a soft delete; restoration remains available."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>{deleteRecord ? `“${deleteRecord.block_code} — ${deleteRecord.block_name}” will be moved to Deleted Entries.` : `${selectedRows.length} selected blocks will be moved to Deleted Entries.`}</Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import blocks"
      subtitle="Preview spreadsheet rows before import. Existing block codes are updated; a matching deleted block is restored."
      headers={BLOCK_IMPORT_HEADERS}
      optionalHeaders={BLOCK_IMPORT_OPTIONAL_HEADERS}
      sample={{ block_code: 'OMB-1', block_name: 'OML Block 1', description: 'Shallow water acreage' }}
      templateName="block-register-template.csv"
      onRows={importRows}
    />
  </>
}
