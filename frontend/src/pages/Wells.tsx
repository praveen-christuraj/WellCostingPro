import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AddRounded, ArrowDropDownRounded, DeleteOutlineRounded, EditOutlined, ListAltRounded, TuneRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, IconButton, Menu, MenuItem, Paper, TextField, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { WellConfigurationDialog } from '../components/WellConfigurationDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  emptyWellForm,
  formatDays,
  formatDepth,
  WELL_IMPORT_HEADERS,
  WELL_IMPORT_OPTIONAL_HEADERS,
  type ImportResult,
  type RigOption,
  type Well,
  type WellPayload,
} from '../lib/rigWell'

 type TransitionAction = 'configure' | 'draft' | 'complete' | 'activate'

function WellActions({
  well, canEdit, canDelete, onEdit, onConfigure, onDelete, onTransition,
}: {
  well: Well
  canEdit: boolean
  canDelete: boolean
  onEdit: () => void
  onConfigure: () => void
  onDelete: () => void
  onTransition: (action: TransitionAction) => void
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const menuOpen = Boolean(anchor)
  const close = () => setAnchor(null)
  const action = (next: TransitionAction) => { close(); onTransition(next) }
  return <Box display="flex" alignItems="center" height="100%" gap={.1}>
    {canEdit && <Button size="small" aria-label={`Edit well ${well.well_code}`} onClick={onEdit} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
    <Tooltip title="View or edit well plan">
      <IconButton size="small" aria-label={`${canEdit ? 'Configure' : 'View'} well plan ${well.well_code}`} onClick={onConfigure}><TuneRounded fontSize="small"/></IconButton>
    </Tooltip>
    <Tooltip title="Open this well's sub activities">
      <IconButton component={RouterLink} to={`/rig-well/sub-activities?rig_id=${encodeURIComponent(well.rig_id)}&well_id=${encodeURIComponent(well.id)}`} size="small" aria-label={`Open sub activities for ${well.well_code}`}><ListAltRounded fontSize="small"/></IconButton>
    </Tooltip>
    {(canEdit || canDelete) && <>
      <Button size="small" color="inherit" endIcon={<ArrowDropDownRounded/>} onClick={event => setAnchor(event.currentTarget)}>Status</Button>
      <Menu anchorEl={anchor} open={menuOpen} onClose={close}>
        {canEdit && well.status === 'completed' && <MenuItem onClick={() => action('activate')}>Reactivate well</MenuItem>}
        {canEdit && well.status === 'active' && well.config_status === 'configured' && <MenuItem onClick={() => action('draft')}>Reopen plan as Draft</MenuItem>}
        {canEdit && well.status === 'active' && well.config_status === 'configured' && <MenuItem onClick={() => action('complete')}>Mark well completed</MenuItem>}
        {canEdit && well.status === 'active' && well.config_status === 'draft' && well.section_count > 0 && <MenuItem onClick={() => action('configure')}>Mark plan configured</MenuItem>}
        {canEdit && well.status === 'active' && well.config_status === 'draft' && well.section_count === 0 && <MenuItem disabled>Save a plan before configuring</MenuItem>}
        {canDelete && <MenuItem sx={{ color: 'error.main' }} onClick={() => { close(); onDelete() }}>Move to Deleted Entries</MenuItem>}
      </Menu>
    </>}
  </Box>
}

const transitionCopy: Record<TransitionAction, { title: string; label: string; description: string }> = {
  configure: { title: 'Mark well plan as configured?', label: 'Mark configured', description: 'The saved plan becomes a configured well baseline. Reopen it as Draft before editing.' },
  draft: { title: 'Reopen well plan as Draft?', label: 'Reopen as Draft', description: 'This unlocks the well plan for edits. The change is recorded in the audit trail.' },
  complete: { title: 'Mark well as completed?', label: 'Complete well', description: 'The well is marked complete. Its plan stays read-only until the well is reactivated.' },
  activate: { title: 'Reactivate this well?', label: 'Reactivate well', description: 'The well will return to Active. Its configuration status remains unchanged.' },
}

export default function Wells() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Well[]>([])
  const [rigs, setRigs] = useState<RigOption[]>([])
  const [selectedRows, setSelectedRows] = useState<Well[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Well | null>(null)
  const [form, setForm] = useState<WellPayload>(emptyWellForm)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<Well | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [configurationTarget, setConfigurationTarget] = useState<Well | null>(null)
  const [transitionTarget, setTransitionTarget] = useState<Well | null>(null)
  const [transitionAction, setTransitionAction] = useState<TransitionAction>('configure')
  const [transitionRemarks, setTransitionRemarks] = useState('')
  const [transitionError, setTransitionError] = useState('')
  const [transitioning, setTransitioning] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [wellRows, rigOptions] = await Promise.all([
        api<Well[]>('/rig-well/wells'),
        api<RigOption[]>('/rig-well/rigs/dropdown'),
      ])
      setRows(wellRows)
      setRigs(rigOptions)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Wells could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptyWellForm())
    setFormError('')
    setFormOpen(true)
  }
  const openEdit = (well: Well) => {
    setFormRecord(well)
    setForm({
      rig_id: well.rig_id,
      well_code: well.well_code,
      well_name: well.well_name,
      well_location: well.well_location,
      block: well.block,
      objective: well.objective,
      remarks: well.remarks,
    })
    setFormError('')
    setFormOpen(true)
  }

  const save = async () => {
    setSaving(true)
    setFormError('')
    const payload = {
      rig_id: form.rig_id,
      well_code: form.well_code.trim(),
      well_name: form.well_name.trim(),
      well_location: form.well_location.trim(),
      block: form.block.trim(),
      objective: form.objective.trim(),
      remarks: form.remarks.trim(),
    }
    try {
      if (formRecord) {
        await api(`/rig-well/wells/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${formRecord.well_code} was updated.`)
      } else {
        const created = await api<Well>('/rig-well/wells', { method: 'POST', body: body(payload) })
        setNotice(`${created.well_code} was created under ${created.rig_code}.`)
      }
      setFormOpen(false)
      setFormRecord(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this well')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (well?: Well) => {
    setDeleteRecord(well ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }
  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/rig-well/wells/${deleteRecord.id}`, { method: 'DELETE' })
      } else {
        await api('/rig-well/wells/bulk-delete', { method: 'POST', body: body({ ids: targets.map(well => well.id) }) })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(`${targets.length} ${targets.length === 1 ? 'well was' : 'wells were'} moved to Deleted Entries.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these wells to Deleted Entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<ImportResult>('/rig-well/wells/import', { method: 'POST', body: body({ rows: importedRows }) })
    await load()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} wells.`)
    if (!result.error_count) return []
    return [
      `Imported or updated ${result.imported_count} of ${importedRows.length} rows. Resolve the issues below and re-import failed rows.`,
      ...result.errors,
    ]
  }

  const onExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/rig-well/export-audit', {
      method: 'POST',
      body: body({ module: 'wells', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const openTransition = (well: Well, action: TransitionAction) => {
    setTransitionTarget(well)
    setTransitionAction(action)
    setTransitionRemarks('')
    setTransitionError('')
  }
  const confirmTransition = async () => {
    if (!transitionTarget) return
    setTransitioning(true)
    setTransitionError('')
    try {
      await api(`/rig-well/wells/${transitionTarget.id}/transition`, {
        method: 'POST', body: body({ action: transitionAction, remarks: transitionRemarks.trim() }),
      })
      setNotice(`${transitionTarget.well_code}: ${transitionCopy[transitionAction].label.toLowerCase()} was recorded.`)
      setTransitionTarget(null)
      await load()
    } catch (caught) {
      setTransitionError(caught instanceof Error ? caught.message : 'Well status could not be updated')
    } finally {
      setTransitioning(false)
    }
  }

  const columns = useMemo<ColDef<Well>[]>(() => [
    { headerName: 'WELL CODE', field: 'well_code', minWidth: 125, flex: .75 },
    { headerName: 'WELL NAME', field: 'well_name', minWidth: 180, flex: 1.1 },
    { headerName: 'RIG', field: 'rig_display', minWidth: 170, flex: 1 },
    { headerName: 'LOCATION / BLOCK', field: 'well_location', minWidth: 170, valueFormatter: params => params.data ? `${params.data.well_location} / ${params.data.block}` : '' },
    { headerName: 'OBJECTIVE', field: 'objective', minWidth: 145, flex: .9 },
    { headerName: 'WELL STATUS', field: 'status', minWidth: 115, maxWidth: 130, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={value === 'completed' ? 'neutral' : 'success'}>{value}</Tag></Box> },
    { headerName: 'PLAN STATUS', field: 'config_status', minWidth: 120, maxWidth: 145, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={value === 'configured' ? 'info' : 'warning'}>{value}</Tag></Box> },
    { headerName: 'PLANNED DEPTH', field: 'total_depth', minWidth: 140, valueFormatter: params => formatDepth(params.value, params.data?.depth_unit ?? 'm') },
    { headerName: 'PLANNED DAYS', field: 'total_days', minWidth: 125, valueFormatter: params => formatDays(params.value) },
    { headerName: 'SUB ACTIVITIES', field: 'sub_activity_count', minWidth: 125, maxWidth: 145, valueFormatter: params => Number(params.value ?? 0).toLocaleString() },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 135, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 275, minWidth: 275, maxWidth: 275, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Well }) => data && <WellActions
        well={data}
        canEdit={can('rig-well:update')}
        canDelete={can('rig-well:delete')}
        onEdit={() => openEdit(data)}
        onConfigure={() => setConfigurationTarget(data)}
        onDelete={() => openDelete(data)}
        onTransition={action => openTransition(data, action)}
      />,
    },
  ], [can, rigs])

  const transition = transitionTarget ? transitionCopy[transitionAction] : null

  return <>
    <PageHeading
      eyebrow="RIG & WELL MANAGEMENT / WELL REGISTER"
      title="Wells"
      subtitle="Every well belongs to one active rig. Configure its hole-section depth intervals and planned phases, then manage its lifecycle."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/rig-well/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('rig-well:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!rigs.length}>Add well</Button>}
      </Box>}
    />

    {!rigs.length && <Alert severity="warning" sx={{ mb: 1.8 }} action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/rigs" size="small">Create a rig</Button> : undefined}>Create at least one active rig before adding wells. Rigs are maintained in the Rig register.</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.8, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box><Typography fontWeight={800} fontSize={15}>Well register</Typography><Typography color="text.secondary" fontSize={12} mt={.35}>{rows.filter(row => row.status === 'active').length} active wells · {rows.filter(row => row.status === 'active' && row.config_status === 'configured').length} configured · {rows.filter(row => row.status === 'completed').length} completed.</Typography></Box>
        {can('rig-well:delete') && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>Move {selectedRows.length || ''} to Deleted Entries</Button>}
      </Box>
    </Paper>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      rows={rows}
      columns={columns}
      searchPlaceholder="Search wells by code, rig, location, block, objective..."
      exportName="well-register"
      onImport={can('rig-well:import') ? () => setImportOpen(true) : undefined}
      canExport={can('rig-well:export')}
      onExport={onExport}
      selectable={can('rig-well:delete')}
      onSelectionChange={setSelectedRows}
    />}

    <FormDialog
      open={formOpen}
      title={formRecord ? `Edit well ${formRecord.well_code}` : 'Add well'}
      subtitle="Assign the well to an active rig. Well codes are unique across the workspace."
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={() => void save()}
      busy={saving}
      submitDisabled={!rigs.length || !form.rig_id || !form.well_code.trim() || !form.well_name.trim() || !form.well_location.trim() || !form.block.trim() || !form.objective.trim()}
      submitLabel={formRecord ? 'Save changes' : 'Create well'}
    >
      <Box display="grid" gap={2} pt={.5}>
        <TextField select label="Rig" required fullWidth value={form.rig_id} onChange={event => setForm({ ...form, rig_id: event.target.value })}>
          {rigs.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.4fr' }} gap={1.5}>
          <TextField label="Well code" required fullWidth value={form.well_code} onChange={event => setForm({ ...form, well_code: event.target.value })} inputProps={{ maxLength: 50 }} helperText="Workspace-unique; normalized to uppercase."/>
          <TextField label="Well name" required fullWidth value={form.well_name} onChange={event => setForm({ ...form, well_name: event.target.value })} inputProps={{ maxLength: 200 }}/>
        </Box>
        <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1.4fr 1fr' }} gap={1.5}>
          <TextField label="Well location" required fullWidth value={form.well_location} onChange={event => setForm({ ...form, well_location: event.target.value })} inputProps={{ maxLength: 300 }}/>
          <TextField label="Block" required fullWidth value={form.block} onChange={event => setForm({ ...form, block: event.target.value })} inputProps={{ maxLength: 200 }}/>
        </Box>
        <TextField label="Objective" required fullWidth multiline minRows={2} value={form.objective} onChange={event => setForm({ ...form, objective: event.target.value })} inputProps={{ maxLength: 500 }}/>
        <TextField label="Remarks" fullWidth multiline minRows={2} value={form.remarks} onChange={event => setForm({ ...form, remarks: event.target.value })} inputProps={{ maxLength: 1000 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={deleteOpen}
      title="Move well to Deleted Entries?"
      subtitle="A well with active sub activities cannot be deleted. Move its sub activities to Deleted Entries first."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>{deleteRecord ? `“${deleteRecord.well_code} — ${deleteRecord.well_name}” under ${deleteRecord.rig_code} will be moved to Deleted Entries.` : `${selectedRows.length} selected wells will be moved to Deleted Entries.`}</Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import wells"
      subtitle="Preview before import. Rig codes must resolve to active rigs in this workspace. Existing well codes are updated and deleted matches are restored."
      headers={WELL_IMPORT_HEADERS}
      optionalHeaders={WELL_IMPORT_OPTIONAL_HEADERS}
      sample={{ rig_code: 'RIG-001', well_code: 'WELL-001', well_name: 'North appraisal well', well_location: 'North field', block: 'Block A', objective: 'Appraisal', remarks: 'Sample row' }}
      templateName="well-register-template.csv"
      onRows={importRows}
    />

    <WellConfigurationDialog
      open={!!configurationTarget}
      well={configurationTarget}
      onClose={() => setConfigurationTarget(null)}
      onSaved={() => { setNotice('Well plan saved as Draft.'); void load() }}
    />

    <FormDialog
      open={!!transitionTarget}
      title={transition?.title ?? 'Update well lifecycle'}
      subtitle={transition?.description}
      onClose={() => { if (!transitioning) { setTransitionTarget(null); setTransitionError('') } }}
      onSubmit={() => void confirmTransition()}
      busy={transitioning}
      submitDisabled={transitionRemarks.trim().length < 3}
      submitLabel={transition?.label ?? 'Confirm'}
    >
      <Box display="grid" gap={1.7} pt={.5}>
        {transitionTarget && <Typography fontSize={13}>{transitionTarget.well_code} — {transitionTarget.well_name} ({transitionTarget.rig_code})</Typography>}
        <TextField label="Reason / audit note" required fullWidth multiline minRows={3} value={transitionRemarks} onChange={event => setTransitionRemarks(event.target.value)} inputProps={{ maxLength: 500 }} helperText="At least 3 characters. This note is stored in the audit trail."/>
        <ErrorMessage message={transitionError}/>
      </Box>
    </FormDialog>
  </>
}
