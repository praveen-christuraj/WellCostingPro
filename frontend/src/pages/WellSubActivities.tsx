import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { AddRounded, DeleteOutlineRounded, EditOutlined, FactCheckOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, MenuItem, Paper, TextField, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, useFormDirty, Tag } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import {
  activeWellScopes,
  emptySubActivityForm,
  scopeLabel,
  SUB_ACTIVITY_IMPORT_HEADERS as SUB_ACTIVITY_HEADERS,
  SUB_ACTIVITY_IMPORT_OPTIONAL_HEADERS,
  type ImportResult,
  type MasterActivity,
  type RigOption,
  type SubActivity,
  type SubActivityPayload,
  type Well,
  type WellConfigurationScope,
} from '../lib/rigWell'

function isPlannedActivity(activity?: MasterActivity | null): boolean {
  if (!activity) return true
  const text = `${activity.code} ${activity.name}`.toLowerCase()
  if (/\bnpt\b/.test(text) || /non[ -]?productive/.test(text)) return false
  if (/\bupa\b/.test(text) || text.includes('unplanned')) return false
  return true
}

export default function WellSubActivities() {
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [rigs, setRigs] = useState<RigOption[]>([])
  const [wells, setWells] = useState<Well[]>([])
  const [activities, setActivities] = useState<MasterActivity[]>([])
  const [selectedRigId, setSelectedRigId] = useState('')
  const [selectedWellId, setSelectedWellId] = useState('')
  const [selectedScope, setSelectedScope] = useState<WellConfigurationScope | ''>('')
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
  const formDirty = useFormDirty(form, formOpen)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<SubActivity | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const activeWell = wells.find(well => well.id === selectedWellId) ?? null
  const availableScopes = useMemo(() => activeWellScopes(activeWell), [activeWell])
  const wellOptions = useMemo(
    () => wells.filter(well => well.rig_id === selectedRigId && activeWellScopes(well).length > 0),
    [wells, selectedRigId],
  )

  const activeScopeStatus = activeWell && selectedScope
    ? (selectedScope === 'completion'
        ? { status: activeWell.completion_status, config_status: activeWell.completion_config_status }
        : { status: activeWell.status, config_status: activeWell.config_status })
    : null

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
      const queryScope = searchParams.get('scope') ?? ''
      if (queryWell && wellList.some(well => well.id === queryWell)) {
        const well = wellList.find(item => item.id === queryWell)!
        const scopes = activeWellScopes(well)
        setSelectedWellId(queryWell)
        setSelectedRigId(well.rig_id)
        if ((queryScope === 'drilling' || queryScope === 'completion') && scopes.includes(queryScope)) {
          setSelectedScope(queryScope)
        } else {
          setSelectedScope(scopes[0] ?? '')
        }
      } else if (queryRig && rigList.some(rig => rig.id === queryRig)) {
        setSelectedRigId(queryRig)
      } else {
        setSelectedRigId(current => rigList.some(rig => rig.id === current) ? current : '')
        setSelectedWellId(current => wellList.some(well => well.id === current) ? current : '')
        setSelectedScope(current => {
          if (!current) return ''
          return current
        })
      }
    } catch (caught) {
      setLookupError(caught instanceof Error ? caught.message : 'Rigs, wells or Activities could not be loaded')
    } finally {
      setLoadingLookups(false)
    }
  }, [searchParams])

  const loadRows = useCallback(async () => {
    if (!selectedWellId || !selectedScope) {
      setRows([])
      setSelectedRows([])
      return
    }
    setLoadingRows(true)
    setError('')
    try {
      const query = new URLSearchParams({ well_id: selectedWellId, scope: selectedScope })
      const records = await api<SubActivity[]>(`/rig-well/sub-activities?${query.toString()}`)
      setRows(records)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Well sub activities could not be loaded')
    } finally {
      setLoadingRows(false)
    }
  }, [selectedWellId, selectedScope])

  useEffect(() => { void loadLookups() }, [loadLookups])
  useEffect(() => { void loadRows() }, [loadRows])

  const onRigChange = (value: string) => {
    setSelectedRigId(value)
    setSelectedWellId('')
    setSelectedScope('')
    setRows([])
    setSelectedRows([])
    setNotice('')
    const params = new URLSearchParams(searchParams)
    if (value) params.set('rig_id', value)
    else params.delete('rig_id')
    params.delete('well_id')
    params.delete('scope')
    setSearchParams(params, { replace: true })
  }
  const onWellChange = (value: string) => {
    setSelectedWellId(value)
    setSelectedRows([])
    const well = wells.find(item => item.id === value)
    const scopes = activeWellScopes(well)
    const nextScope: WellConfigurationScope | '' = value
      ? (selectedScope && scopes.includes(selectedScope) ? selectedScope : (scopes.length === 1 ? scopes[0] : ''))
      : ''
    setSelectedScope(nextScope)
    const params = new URLSearchParams(searchParams)
    if (selectedRigId) params.set('rig_id', selectedRigId)
    if (value) params.set('well_id', value)
    else params.delete('well_id')
    if (nextScope) params.set('scope', nextScope)
    else params.delete('scope')
    setSearchParams(params, { replace: true })
  }
  const onScopeChange = (value: string) => {
    const nextScope = value === 'drilling' || value === 'completion' ? value : ''
    setSelectedScope(nextScope)
    setSelectedRows([])
    const params = new URLSearchParams(searchParams)
    if (selectedRigId) params.set('rig_id', selectedRigId)
    if (selectedWellId) params.set('well_id', selectedWellId)
    if (nextScope) params.set('scope', nextScope)
    else params.delete('scope')
    setSearchParams(params, { replace: true })
  }

  const selectedActivity = activities.find(a => a.id === form.activity_id) ?? null
  const isPlanned = selectedActivity ? isPlannedActivity(selectedActivity) : true

  const openCreate = () => {
    if (!selectedScope) return
    setFormRecord(null)
    const initial = emptySubActivityForm(selectedWellId, selectedScope)
    const firstAct = activities[0]
    if (firstAct) {
      initial.activity_id = firstAct.id
      initial.responsible_party = isPlannedActivity(firstAct) ? 'Not Applicable' : ''
    }
    setForm(initial)
    setFormError('')
    setFormOpen(true)
  }
  const openEdit = (record: SubActivity) => {
    setFormRecord(record)
    const act = activities.find(a => a.id === record.activity_id)
    const planned = isPlannedActivity(act)
    setForm({
      well_id: selectedWellId,
      scope: record.scope,
      sub_activity_code: record.sub_activity_code,
      sub_activity_name: record.sub_activity_name,
      activity_id: record.activity_id,
      responsible_party: planned ? 'Not Applicable' : record.responsible_party,
      description: record.description,
    })
    setFormError('')
    setFormOpen(true)
  }

  const onActivityChange = (activityId: string) => {
    const act = activities.find(a => a.id === activityId)
    const planned = isPlannedActivity(act)
    setForm(prev => ({
      ...prev,
      activity_id: activityId,
      responsible_party: planned ? 'Not Applicable' : (prev.responsible_party === 'Not Applicable' ? '' : prev.responsible_party),
    }))
  }

  const save = async () => {
    if (!selectedWellId || !selectedScope) return
    setSaving(true)
    setFormError('')
    const payload = {
      well_id: selectedWellId,
      scope: selectedScope,
      sub_activity_code: form.sub_activity_code.trim(),
      sub_activity_name: form.sub_activity_name.trim(),
      activity_id: form.activity_id,
      responsible_party: isPlanned ? 'Not Applicable' : form.responsible_party.trim(),
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
        setNotice(`${created.sub_activity_code} was added to ${created.well_code} (${scopeLabel(created.scope)}).`)
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
    if (!selectedWellId || !selectedScope) return
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/rig-well/sub-activities/${deleteRecord.id}?well_id=${encodeURIComponent(selectedWellId)}`, { method: 'DELETE' })
      } else {
        const query = new URLSearchParams({ well_id: selectedWellId, scope: selectedScope })
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
    if (!selectedWellId || !selectedScope) return ['Select a rig, well and scope before importing sub activities.']
    const query = new URLSearchParams({ well_id: selectedWellId, scope: selectedScope })
    const result = await api<ImportResult>(`/rig-well/sub-activities/import?${query.toString()}`, {
      method: 'POST', body: body({ rows: importedRows }),
    })
    await loadRows()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} sub activities for ${activeWell?.well_code} (${scopeLabel(selectedScope)}).`)
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
    {
      headerName: 'SCOPE', field: 'scope', minWidth: 115, maxWidth: 130,
      cellRenderer: ({ data }: { data: SubActivity }) => data && <Box display="flex" alignItems="center" height="100%"><Tag tone="info">{scopeLabel(data.scope)}</Tag></Box>,
    },
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
      subtitle="Break a well's Activities into concrete work steps per configuration scope. Select the rig, well and scope (Drilling or Completion) first; every entry remains scoped to that well plan and one Activity from Master Data."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/rig-well/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
        {can('rig-well:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!selectedWellId || !selectedScope || !activities.length}>Add sub activity</Button>}
      </Box>}
    />

    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, borderRadius: 2, mb: 2 }}>
      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.25fr 0.95fr auto' }} gap={1.5} alignItems="end">
        <TextField select label="Rig" value={selectedRigId} disabled={loadingLookups} onChange={event => onRigChange(event.target.value)}>
          <MenuItem value="">Select a rig</MenuItem>
          {rigs.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
        </TextField>
        <TextField select label="Well" value={selectedWellId} disabled={!selectedRigId || loadingLookups} onChange={event => onWellChange(event.target.value)}>
          <MenuItem value="">Select a well</MenuItem>
          {wellOptions.map(well => <MenuItem key={well.id} value={well.id}>{well.well_code} — {well.well_name}</MenuItem>)}
        </TextField>
        <TextField select label="Well scope" value={selectedScope} disabled={!selectedWellId || loadingLookups} onChange={event => onScopeChange(event.target.value)}>
          <MenuItem value="">Select a scope</MenuItem>
          {availableScopes.map(scope => <MenuItem key={scope} value={scope}>{scopeLabel(scope)}</MenuItem>)}
        </TextField>
        <Box display="flex" gap={1}>
          {can('rig-well:delete') && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>Move {selectedRows.length || ''} to Deleted Entries</Button>}
        </Box>
      </Box>
      {activeWell && selectedScope && activeScopeStatus && <Box mt={1.5} display="flex" gap={1} flexWrap="wrap" alignItems="center">
        <Typography fontSize={12} color="text.secondary">Selected well scope:</Typography>
        <Typography fontSize={12} fontWeight={800}>{activeWell.well_code} — {activeWell.well_name}</Typography>
        <Tag tone="info">{scopeLabel(selectedScope)}</Tag>
        <Tag tone="info">{activeWell.rig_code} — {activeWell.rig_name}</Tag>
        <Tag tone={activeScopeStatus.status === 'active' ? 'success' : 'neutral'}>{activeScopeStatus.status}</Tag>
        <Tag tone={activeScopeStatus.config_status === 'configured' ? 'info' : 'warning'}>Plan {activeScopeStatus.config_status}</Tag>
      </Box>}
    </Paper>

    {lookupError && <Alert severity="error" sx={{ mb: 1.5 }}>{lookupError}</Alert>}
    {!loadingLookups && !rigs.length && <Alert severity="info" sx={{ mb: 1.5 }} action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/rigs" size="small">Add a rig</Button> : undefined}>Create a rig and a well before entering well sub activities.</Alert>}
    {!loadingLookups && rigs.length > 0 && (!selectedWellId || !selectedScope) && <Alert severity="info" sx={{ mb: 1.5 }}>Choose a rig, well and scope (Drilling or Completion) to open its sub activity register. Codes are unique within each well scope, so Drilling and Completion maintain independent sub activity lists.</Alert>}
    {!loadingLookups && selectedWellId && selectedScope && !activities.length && <Alert severity="warning" sx={{ mb: 1.5 }} icon={<FactCheckOutlined/>} action={can('master-data:read') ? <Button component={RouterLink} to="/master-data/records?module=activities" size="small">Manage Activities</Button> : undefined}>No active Master Data Activities are available. An Activity must be configured before a sub activity can be created.</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    {loadingLookups ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : selectedWellId && selectedScope ? loadingRows ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      fillHeight
      key={`${selectedWellId}:${selectedScope}`}
      rows={rows}
      columns={columns}
      searchPlaceholder={`Search ${scopeLabel(selectedScope).toLowerCase()} sub activities...`}
      exportName={`sub-activities-${activeWell?.well_code ?? 'well'}-${selectedScope}`}
      onImport={can('rig-well:import') ? () => setImportOpen(true) : undefined}
      canExport={can('rig-well:export')}
      onExport={onExport}
      selectable={can('rig-well:delete')}
      onSelectionChange={setSelectedRows}
    /> : null}

    <FormDialog
      open={formOpen}
      title={formRecord ? `Edit sub activity ${formRecord.sub_activity_code}` : `Add sub activity${activeWell && selectedScope ? ` · ${activeWell.well_code} (${scopeLabel(selectedScope)})` : ''}`}
      subtitle="The well and configuration scope are fixed for this entry. Select a controlling Activity from the workspace Master Data register."
      onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
      onSubmit={() => void save()}
      busy={saving}
      dirty={formDirty}
      submitDisabled={!selectedWellId || !selectedScope || !activities.length || !form.sub_activity_code.trim() || !form.sub_activity_name.trim() || !form.activity_id || (!isPlanned && (!form.responsible_party.trim() || form.responsible_party.trim() === 'Not Applicable')) || !form.description.trim()}
      submitLabel={formRecord ? 'Save changes' : 'Create sub activity'}
    >
      <Box display="grid" gap={2} pt={.5}>
        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.5, py: 1.1, bgcolor: 'action.hover' }}>
          <Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">Well &amp; scope</Typography>
          <Typography fontSize={13} fontWeight={800} mt={.25}>{activeWell && selectedScope ? `${activeWell.rig_code} / ${activeWell.well_code} — ${activeWell.well_name} · ${scopeLabel(selectedScope)}` : 'Select a rig, well and scope first'}</Typography>
        </Box>
        <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.4fr' }} gap={1.5}>
          <TextField label="Sub activity code" required fullWidth value={form.sub_activity_code} onChange={event => setForm({ ...form, sub_activity_code: event.target.value })} inputProps={{ maxLength: 50 }} helperText="Unique within this well scope; normalized to uppercase."/>
          <TextField label="Sub activity name" required fullWidth value={form.sub_activity_name} onChange={event => setForm({ ...form, sub_activity_name: event.target.value })} inputProps={{ maxLength: 150 }}/>
        </Box>
        <TextField select label="Activity" required fullWidth value={form.activity_id} onChange={event => onActivityChange(event.target.value)}>
          {activities.map(activity => <MenuItem key={activity.id} value={activity.id}>{activity.code} — {activity.name}</MenuItem>)}
        </TextField>
        <TextField
          label="Responsible party / company"
          required={!isPlanned}
          disabled={isPlanned}
          fullWidth
          value={isPlanned ? 'Not Applicable' : form.responsible_party}
          onChange={event => setForm({ ...form, responsible_party: event.target.value })}
          inputProps={{ maxLength: 200 }}
          helperText={isPlanned ? 'Not applicable for planned activities.' : 'Who performs or is responsible for this work step? (Mandatory for UPA/NPT)'}
        />
        <TextField label="Description / remarks" required fullWidth multiline minRows={3} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} inputProps={{ maxLength: 4000 }}/>
        <ErrorMessage message={formError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={deleteOpen}
      title="Move sub activity to Deleted Entries?"
      subtitle="This is a soft delete. A deleted child entry remains attached to its well scope and can be restored from the module's Deleted Entries view."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>{deleteRecord ? `“${deleteRecord.sub_activity_code} — ${deleteRecord.sub_activity_name}” will be moved from ${activeWell?.well_code} (${scopeLabel(deleteRecord.scope)}) to Deleted Entries.` : `${selectedRows.length} selected sub activities from ${activeWell?.well_code} (${selectedScope ? scopeLabel(selectedScope) : ''}) will be moved to Deleted Entries.`}</Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title={`Import sub activities${activeWell && selectedScope ? ` · ${activeWell.well_code} (${scopeLabel(selectedScope)})` : ''}`}
      subtitle="Rows are imported into the selected well scope (unless an optional scope column overrides a row to drilling or completion). The Activity column accepts an exact Master Data Activity code or name; the sub activity code is unique within each well scope."
      headers={SUB_ACTIVITY_HEADERS}
      optionalHeaders={SUB_ACTIVITY_IMPORT_OPTIONAL_HEADERS}
      sample={{ sub_activity_code: 'RIH-01', sub_activity_name: 'Run in hole with tubing', activity: 'DRILL', responsible_party: 'Operations team', description: 'Run completion tubing to planned depth.' }}
      templateName={`well-sub-activities-${selectedScope || 'drilling'}-template.csv`}
      onRows={importRows}
    />
  </>
}
