import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, EditOutlined, FactCheckOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, MenuItem, Paper, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  emptySubActivityForm,
  SUB_ACTIVITY_IMPORT_HEADERS as SUB_ACTIVITY_HEADERS,
  type ImportResult,
  type MasterActivity,
  type RigOption,
  type SubActivity,
  type SubActivityPayload,
  type Well,
} from '../lib/rigWell'

export default function WellSubActivities() {
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [rigs, setRigs] = useState<RigOption[]>([])
  const [wells, setWells] = useState<Well[]>([])
  const [activities, setActivities] = useState<MasterActivity[]>([])
  const [selectedRigId, setSelectedRigId] = useState('')
  const [selectedWellId, setSelectedWellId] = useState('')
  const [rows, setRows] = useState<SubActivity[]>([])
  const [selectedRows, setSelectedRows] = useState<SubActivity[]>([])
  const [loadingLookups, setLoadingLookups] = useState(true)
  const [loadingRows, setLoadingRows] = useState(false)
  const [lookupError, setLookupError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<SubActivity | null>(null)
  const [form, setForm] = useState<SubActivityPayload>(emptySubActivityForm())
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<SubActivity | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const activeWell = wells.find(well => well.id === selectedWellId) ?? null
  const wellOptions = useMemo(
    () => wells.filter(well => well.rig_id === selectedRigId),
    [wells, selectedRigId],
  )
  const loadLookups = useCallback(async () => {
    setLoadingLookups(true)
    setLookupError('')
    try {
      const [rigList, wellList, activityList] = await Promise.all([
        api<RigOption[]>('/rig-well/rigs/dropdown'),
        api<Well[]>('/rig-well/wells'),
        api<MasterActivity[]>('/rig-well/sub-activities/activity-options'),
      ])
      setRigs(rigList)
      setWells(wellList)
      setActivities(activityList)
      const queryRig = searchParams.get('rig_id') ?? ''
      const queryWell = searchParams.get('well_id') ?? ''
      if (queryWell && wellList.some(well => well.id === queryWell)) {
        const well = wellList.find(item => item.id === queryWell)
        setSelectedWellId(queryWell)
        setSelectedRigId(well?.rig_id ?? '')
      } else if (queryRig && rigList.some(rig => rig.id === queryRig)) {
        setSelectedRigId(queryRig)
      } else {
        setSelectedRigId(current => rigList.some(rig => rig.id === current) ? current : '')
        setSelectedWellId(current => wellList.some(well => well.id === current) ? current : '')
      }
    } catch (caught) {
      setLookupError(caught instanceof Error ? caught.message : 'Rigs, wells or Activities could not be loaded')
    } finally {
      setLoadingLookups(false)
    }
  }, [searchParams])

  const loadRows = useCallback(async () => {
    if (!selectedWellId) {
      setRows([])
      setSelectedRows([])
      return
    }
    setLoadingRows(true)
    setError('')
    try {
      const query = new URLSearchParams({ well_id: selectedWellId })
      const records = await api<SubActivity[]>(`/rig-well/sub-activities?${query.toString()}`)
      setRows(records)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Well sub activities could not be loaded')
    } finally {
      setLoadingRows(false)
    }
  }, [selectedWellId])

  useEffect(() => { void loadLookups() }, [loadLookups])
  useEffect(() => { void loadRows() }, [loadRows])

  const onRigChange = (value: string) => {
    setSelectedRigId(value)
    setSelectedWellId('')
    setRows([])
    setSelectedRows([])
    setNotice('')
    const params = new URLSearchParams(searchParams)
    if (value) params.set('rig_id', value)
    else params.delete('rig_id')
    params.delete('well_id')
    setSearchParams(params, { replace: true })
  }
  const onWellChange = (value: string) => {
    setSelectedWellId(value)
    setSelectedRows([])
    const params = new URLSearchParams(searchParams)
    if (selectedRigId) params.set('rig_id', selectedRigId)
    if (value) params.set('well_id', value)
    else params.delete('well_id')
    setSearchParams(params, { replace: true })
  }

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptySubActivityForm(selectedWellId))
    setFormError('')
    setFormOpen(true)
  }
  const openEdit = (record: SubActivity) => {
    setFormRecord(record)
    setForm({
      well_id: selectedWellId,
      sub_activity_code: record.sub_activity_code,
      sub_activity_name: record.sub_activity_name,
      activity_id: record.activity_id,
      responsible_party: record.responsible_party,
      description: record.description,
    })
    setFormError('')
    setFormOpen(true)
  }

  const save = async () => {
    if (!selectedWellId) return
    setSaving(true)
    setFormError('')
    const payload = {
      well_id: selectedWellId,
      sub_activity_code: form.sub_activity_code.trim(),
      sub_activity_name: form.sub_activity_name.trim(),
      activity_id: form.activity_id,
      responsible_party: form.responsible_party.trim(),
      description: form.description.trim(),
    }
    try {
      if (formRecord) {
        await api(`/rig-well/sub-activities/${formRecord.id}?well_id=${encodeURIComponent(selectedWellId)}`, {
          method: 'PATCH', body: body({
            sub_activity_code: payload.sub_activity_code,
            sub_activity_name: payload.sub_activity_name,
            activity_id: payload.activity_id,
            responsible_party: payload.responsible_party,
            description: payload.description,
          }),
        })
        setNotice(`${formRecord.sub_activity_code} was updated.`)
      } else {
        const created = await api<SubActivity>('/rig-well/sub-activities', { method: 'POST', body: body(payload) })
        setNotice(`${created.sub_activity_code} was added to ${created.well_code}.`)
      }
      setFormOpen(false)
      setFormRecord(null)
      await loadRows()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this sub activity')
    } finally {
      setSaving(false)
    }
  }

  const openDelete = (record?: SubActivity) => {
    setDeleteRecord(record ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }
  const confirmDelete = async () => {
    if (!selectedWellId) return
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/rig-well/sub-activities/${deleteRecord.id}?well_id=${encodeURIComponent(selectedWellId)}`, { method: 'DELETE' })
      } else {
        const query = new URLSearchParams({ well_id: selectedWellId })
        await api(`/rig-well/sub-activities/bulk-delete?${query.toString()}`, {
          method: 'POST', body: body({ ids: targets.map(item => item.id) }),
        })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(`${targets.length} ${targets.length === 1 ? 'sub activity was' : 'sub activities were'} moved to Deleted Entries.`)
      await loadRows()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these sub activities to Deleted Entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    if (!selectedWellId) return ['Select a well before importing sub activities.']
    const query = new URLSearchParams({ well_id: selectedWellId })
    const result = await api<ImportResult>(`/rig-well/sub-activities/import?${query.toString()}`, {
      method: 'POST', body: body({ rows: importedRows }),
    })
    await loadRows()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} sub activities for ${activeWell?.well_code}.`)
    if (!result.error_count) return []
    return [`Imported or updated ${result.imported_count} of ${importedRows.length} rows. Resolve the issues below and re-import failed rows.`, ...result.errors]
  }

  const onExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/rig-well/export-audit', {
      method: 'POST',
      body: body({ module: 'well-sub-activities', format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<SubActivity>[]>(() => [
    { headerName: 'CODE', field: 'sub_activity_code', minWidth: 120, flex: .7 },
    { headerName: 'SUB ACTIVITY', field: 'sub_activity_name', minWidth: 195, flex: 1.2 },
    { headerName: 'ACTIVITY', field: 'activity_display', minWidth: 180, flex: 1 },
    { headerName: 'RESPONSIBLE PARTY / COMPANY', field: 'responsible_party', minWidth: 195, flex: 1 },
    { headerName: 'DESCRIPTION / REMARKS', field: 'description', minWidth: 230, flex: 1.4, valueFormatter: params => params.value || '—' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 135, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 170, minWidth: 170, maxWidth: 170, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: SubActivity }) => data && <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('rig-well:update') && <Button size="small" aria-label={`Edit sub activity ${data.sub_activity_code}`} onClick={() => openEdit(data)} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('rig-well:delete') && <Button size="small" color="error" aria-label={`Delete sub activity ${data.sub_activity_code}`} onClick={() => openDelete(data)} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can])

  return <>
    <PageHeading
      eyebrow="RIG & WELL MANAGEMENT / WELL-SCOPED OPERATIONS"
      title="Well sub activities"
      subtitle="Break a well's Activities into concrete work steps. Select the rig and well first; every entry remains scoped to that well and one Activity from Master Data."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/rig-well/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('rig-well:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!selectedWellId || !activities.length}>Add sub activity</Button>}
      </Box>}
    />

    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, borderRadius: 2, mb: 2 }}>
      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.35fr auto' }} gap={1.5} alignItems="end">
        <TextField select label="Rig" value={selectedRigId} disabled={loadingLookups} onChange={event => onRigChange(event.target.value)}>
          <MenuItem value="">Select a rig</MenuItem>
          {rigs.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select label="Well" value={selectedWellId} disabled={!selectedRigId || loadingLookups} onChange={event => onWellChange(event.target.value)}>
          <MenuItem value="">Select a well</MenuItem>
          {wellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.well_code} — {well.well_name}</MenuItem>)}
        </TextField>
        <Box display="flex" gap={1}>
          {can('rig-well:delete') && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>Move {selectedRows.length || ''} to Deleted Entries</Button>}
        </Box>
      </Box>
      {activeWell && <Box mt={1.5} display="flex" gap={1} flexWrap="wrap" alignItems="center">
        <Typography fontSize={12} color="text.secondary">Selected well:</Typography><Typography fontSize={12} fontWeight={800}>{activeWell.well_code} — {activeWell.well_name}</Typography>
        <Tag tone="info">{activeWell.rig_code} — {activeWell.rig_name}</Tag>
        <Tag tone={activeWell.status === 'active' ? 'success' : 'neutral'}>{activeWell.status}</Tag>
        <Tag tone={activeWell.config_status === 'configured' ? 'info' : 'warning'}>Plan {activeWell.config_status}</Tag>
      </Box>}
    </Paper>

    {lookupError && <Alert severity="error" sx={{ mb: 1.5 }}>{lookupError}</Alert>}
    {!loadingLookups && !rigs.length && <Alert severity="info" sx={{ mb: 1.5 }} action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/rigs" size="small">Add a rig</Button> : undefined}>Create a rig and a well before entering well sub activities.</Alert>}
    {!loadingLookups && rigs.length > 0 && !selectedWellId && <Alert severity="info" sx={{ mb: 1.5 }}>Choose a rig and its well to open the scoped sub activity register. Codes may repeat on another well, but are unique within the selected well.</Alert>}
    {!loadingLookups && selectedWellId && !activities.length && <Alert severity="warning" sx={{ mb: 1.5 }} icon={<FactCheckOutlined/>} action={can('master-data:read') ? <Button component={RouterLink} to="/master-data/records?module=activities" size="small">Manage Activities</Button> : undefined}>No active Master Data Activities are available. An Activity must be configured before a sub activity can be created.</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    {loadingLookups ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : selectedWellId ? loadingRows ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      key={selectedWellId}
      rows={rows}
      columns={columns}
      searchPlaceholder="Search this well's sub activities..."
      exportName={`sub-activities-${activeWell?.well_code ?? 'well'}`}
      onImport={can('rig-well:import') ? () => setImportOpen(true) : undefined}
      canExport={can('rig-well:export')}
      onExport={onExport}
      selectable={can('rig-well:delete')}
      onSelectionChange={setSelectedRows}
    /> : null}

    <FormDialog
      open={formOpen}
      title={formRecord ? `Edit sub activity ${formRecord.sub_activity_code}` : `Add sub activity${activeWell ? ` · ${activeWell.well_code}` : ''}`}
      subtitle="The well scope is fixed for this entry. Select a controlling Activity from the workspace Master Data register."
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={() => void save()}
      busy={saving}
      submitDisabled={!selectedWellId || !activities.length || !form.sub_activity_code.trim() || !form.sub_activity_name.trim() || !form.activity_id || !form.responsible_party.trim() || !form.description.trim()}
      submitLabel={formRecord ? 'Save changes' : 'Create sub activity'}
    >
      <Box display="grid" gap={2} pt={.5}>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1.1, bgcolor: 'action.hover' }}>
          <Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Well scope</Typography>
          <Typography fontSize={13} fontWeight={800} mt={.25}>{activeWell ? `${activeWell.rig_code} / ${activeWell.well_code} — ${activeWell.well_name}` : 'Select a rig and well first'}</Typography>
        </Box>
        <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.4fr' }} gap={1.5}>
          <TextField label="Sub activity code" required fullWidth value={form.sub_activity_code} onChange={event => setForm({ ...form, sub_activity_code: event.target.value })} inputProps={{ maxLength: 50 }} helperText="Unique within this well; normalized to uppercase."/>
          <TextField label="Sub activity name" required fullWidth value={form.sub_activity_name} onChange={event => setForm({ ...form, sub_activity_name: event.target.value })} inputProps={{ maxLength: 150 }}/>
        </Box>
        <TextField select label="Activity" required fullWidth value={form.activity_id} onChange={event => setForm({ ...form, activity_id: event.target.value })}>
          {activities.map(activity => <MenuItem key={activity.id} value={activity.id}>{activity.code} — {activity.name}</MenuItem>)}
        </TextField>
        <TextField label="Responsible party / company" required fullWidth value={form.responsible_party} onChange={event => setForm({ ...form, responsible_party: event.target.value })} inputProps={{ maxLength: 200 }} helperText="Who performs or owns this work step?"/>
        <TextField label="Description / remarks" required fullWidth multiline minRows={3} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 4000 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={deleteOpen}
      title="Move sub activity to Deleted Entries?"
      subtitle="This is a soft delete. A deleted child entry remains attached to its well and can be restored from the module's Deleted Entries view."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>{deleteRecord ? `“${deleteRecord.sub_activity_code} — ${deleteRecord.sub_activity_name}” will be moved from ${activeWell?.well_code} to Deleted Entries.` : `${selectedRows.length} selected sub activities from ${activeWell?.well_code} will be moved to Deleted Entries.`}</Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title={`Import sub activities${activeWell ? ` · ${activeWell.well_code}` : ''}`}
      subtitle="Rows are imported only into the selected well. The Activity column accepts an exact Master Data Activity code or name; the sub activity code is unique within this well."
      headers={SUB_ACTIVITY_HEADERS}
      sample={{ sub_activity_code: 'RIH-01', sub_activity_name: 'Run in hole with tubing', activity: 'DRILL', responsible_party: 'Operations team', description: 'Run completion tubing to planned depth.' }}
      templateName="well-sub-activities-template.csv"
      onRows={importRows}
    />
  </>
}
