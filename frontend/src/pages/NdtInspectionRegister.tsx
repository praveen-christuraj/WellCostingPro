import { useCallback, useEffect, useMemo, useState } from 'react'
import { Add, DeleteForever, DeleteOutline, EditOutlined, Refresh, RestoreFromTrash, Upload } from '@mui/icons-material'
import { Alert, Box, Button, IconButton, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { FormDialog, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'
import { ImportDialog } from '../components/ImportDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import type { ImportRow } from '../lib/export'
import { NDT_IMPORT_HEADERS, NDT_IMPORT_OPTIONAL, NDT_IMPORT_SAMPLE, importNdtRow, newNdtLine, quantity, type NdtEntry, type NdtLine, type NdtReference, type NdtScope } from '../lib/ndtInspection'

const numericFields = ['quantity_received', 'quantity_consumed', 'quantity_backloaded_good', 'quantity_backloaded_bad'] as const
const dateText = (value: string) => new Date(value).toLocaleString()

export default function NdtInspectionRegister() {
  const { can } = useAuth()
  const [rows, setRows] = useState<NdtEntry[]>([])
  const [reference, setReference] = useState<NdtReference>({ rigs: [], wells: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [rigFilter, setRigFilter] = useState('')
  const [wellFilter, setWellFilter] = useState('')
  const [scopeFilter, setScopeFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<NdtEntry[]>([])
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<NdtEntry | null>(null)
  const [rigId, setRigId] = useState('')
  const [wellId, setWellId] = useState('')
  const [scope, setScope] = useState<NdtScope>('drilling')
  const [lines, setLines] = useState<NdtLine[]>([newNdtLine()])
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [confirm, setConfirm] = useState<{ kind: 'delete' | 'restore' | 'purge'; ids: string[] } | null>(null)

  const query = useMemo(() => {
    const q = new URLSearchParams()
    if (rigFilter) q.set('rig_id', rigFilter); if (wellFilter) q.set('well_id', wellFilter); if (scopeFilter) q.set('scope', scopeFilter)
    if (dateFrom) q.set('from', dateFrom); if (dateTo) q.set('to', dateTo)
    return q.size ? `?${q}` : ''
  }, [rigFilter, wellFilter, scopeFilter, dateFrom, dateTo])

  const load = useCallback(async () => {
    setLoading(true); setError(''); setSelected([])
    try {
      const [entries, ref] = await Promise.all([
        api<NdtEntry[]>(`/ndt-inspections/entries${showDeleted ? '/deleted' : ''}${query}`),
        api<NdtReference>('/ndt-inspections/reference'),
      ])
      setRows(entries); setReference(ref)
    } catch (caught) { setError((caught as Error).message) } finally { setLoading(false) }
  }, [query, showDeleted])
  useEffect(() => { void load() }, [load])

  const filterWells = reference.wells.filter(w => !rigFilter || w.rig_id === rigFilter)
  const editorWells = reference.wells.filter(w => w.rig_id === rigId && (scope === 'completion' ? w.completion_available : w.drilling_available))
  useEffect(() => { if (wellFilter && !filterWells.some(w => w.id === wellFilter)) setWellFilter('') }, [rigFilter]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (wellId && !editorWells.some(w => w.id === wellId)) setWellId('') }, [rigId, scope]) // eslint-disable-line react-hooks/exhaustive-deps

  const openAdd = () => {
    const firstRig = reference.rigs[0]?.id ?? ''
    const firstWell = reference.wells.find(w => w.rig_id === firstRig && w.drilling_available)?.id ?? ''
    setEditing(null); setRigId(firstRig); setWellId(firstWell); setScope('drilling'); setLines([newNdtLine()]); setFormError(''); setEditorOpen(true)
  }
  const openEdit = (row: NdtEntry) => {
    setEditing(row); setRigId(row.rig_id); setWellId(row.well_id); setScope(row.scope)
    setLines([{ key: row.id, description: row.description, quantity_received: row.quantity_received, quantity_consumed: row.quantity_consumed, quantity_backloaded_good: row.quantity_backloaded_good, quantity_backloaded_bad: row.quantity_backloaded_bad, remarks: row.remarks }])
    setFormError(''); setEditorOpen(true)
  }
  const valid = Boolean(rigId && wellId && lines.length && lines.every(line => line.description.trim() && numericFields.every(field => line[field] !== '' && Number.isFinite(Number(line[field])) && Number(line[field]) >= 0)))
  const updateLine = (key: string, field: keyof NdtLine, value: string) => setLines(current => current.map(line => line.key === key ? { ...line, [field]: value } : line))
  const save = async () => {
    if (!valid) { setFormError('Choose the rig, well and scope, then enter a description and non-negative quantities for every line.'); return }
    setSaving(true); setFormError('')
    try {
      const clean = lines.map(({ key: _key, ...line }) => line)
      if (editing) await api(`/ndt-inspections/entries/${editing.id}`, { method: 'PUT', body: body({ rig_id: rigId, well_id: wellId, scope, ...clean[0] }) })
      else await api('/ndt-inspections/entries/bulk', { method: 'POST', body: body({ rig_id: rigId, well_id: wellId, scope, lines: clean }) })
      setEditorOpen(false); setNotice(editing ? 'NDT inspection line updated.' : `${lines.length} NDT inspection line${lines.length === 1 ? '' : 's'} added.`); await load()
    } catch (caught) { setFormError((caught as Error).message) } finally { setSaving(false) }
  }
  const runLifecycle = async () => {
    if (!confirm) return
    setSaving(true); setError('')
    const endpoint = confirm.kind === 'delete' ? 'bulk-delete' : confirm.kind === 'restore' ? 'bulk-restore' : 'bulk-permanent-delete'
    try { await api(`/ndt-inspections/entries/${endpoint}`, { method: 'POST', body: body({ ids: confirm.ids }) }); setConfirm(null); await load() }
    catch (caught) { setError((caught as Error).message) } finally { setSaving(false) }
  }
  const importRows = async (source: ImportRow[]) => {
    const result = await api<{ created_count: number; errors: string[] }>('/ndt-inspections/import', { method: 'POST', body: body({ rows: source.map(importNdtRow) }) })
    if (!result.errors.length) { setNotice(`${result.created_count} NDT inspection line(s) imported.`); await load() }
    return result.errors
  }

  const columns = useMemo<ColDef<NdtEntry>[]>(() => [
    { headerName: 'RIG', field: 'rig_code', minWidth: 110 }, { headerName: 'WELL', field: 'well_code', minWidth: 120 },
    { headerName: 'SCOPE', field: 'scope', minWidth: 115, cellRenderer: (p: ICellRendererParams<NdtEntry>) => <Box display="flex" height="100%" alignItems="center"><Tag tone="info">{p.value === 'completion' ? 'Completion' : 'Drilling'}</Tag></Box> },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 220, flex: 1 },
    { headerName: 'RECEIVED', field: 'quantity_received', minWidth: 120, type: 'rightAligned', valueFormatter: p => quantity(p.value) },
    { headerName: 'CONSUMED', field: 'quantity_consumed', minWidth: 120, type: 'rightAligned', valueFormatter: p => quantity(p.value) },
    { headerName: 'BACKLOADED GOOD', field: 'quantity_backloaded_good', minWidth: 155, type: 'rightAligned', valueFormatter: p => quantity(p.value) },
    { headerName: 'BACKLOADED BAD', field: 'quantity_backloaded_bad', minWidth: 150, type: 'rightAligned', valueFormatter: p => quantity(p.value) },
    { headerName: 'REMARKS', field: 'remarks', minWidth: 180 }, { headerName: 'CREATED', field: 'created_at', minWidth: 170, valueFormatter: p => dateText(p.value) },
    { headerName: 'ACTIONS', field: 'id', minWidth: 105, maxWidth: 120, sortable: false, filter: false, cellRenderer: (p: ICellRendererParams<NdtEntry>) => p.data ? <Stack direction="row" alignItems="center" height="100%">
      {!showDeleted && can('daily-cost:update') && <Tooltip title="Edit"><IconButton size="small" onClick={() => openEdit(p.data!)}><EditOutlined fontSize="small"/></IconButton></Tooltip>}
      {!showDeleted && can('daily-cost:delete') && <Tooltip title="Delete"><IconButton size="small" onClick={() => setConfirm({ kind: 'delete', ids: [p.data!.id] })}><DeleteOutline fontSize="small"/></IconButton></Tooltip>}
      {showDeleted && can('daily-cost:restore') && <Tooltip title="Restore"><IconButton size="small" onClick={() => setConfirm({ kind: 'restore', ids: [p.data!.id] })}><RestoreFromTrash fontSize="small"/></IconButton></Tooltip>}
      {showDeleted && can('daily-cost:permanent-delete') && <Tooltip title="Delete permanently"><IconButton size="small" color="error" onClick={() => setConfirm({ kind: 'purge', ids: [p.data!.id] })}><DeleteForever fontSize="small"/></IconButton></Tooltip>}
    </Stack> : null },
  ], [can, showDeleted]) // eslint-disable-line react-hooks/exhaustive-deps

  return <Box display="grid" gap={2} minHeight={0}>
    <PageHeading eyebrow="Daily Cost Management" title="NDT Inspection Register" subtitle="Record inspection quantities by rig, well, and drilling or completion scope." action={<Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {can('daily-cost:create') && <Button variant="contained" startIcon={<Add/>} onClick={openAdd}>Add NDT Inspection</Button>}
      {can('daily-cost:import') && <Button variant="outlined" startIcon={<Upload/>} onClick={() => setImportOpen(true)}>Import</Button>}
      <Button variant="outlined" color={showDeleted ? 'primary' : 'inherit'} startIcon={showDeleted ? <RestoreFromTrash/> : <DeleteOutline/>} onClick={() => setShowDeleted(v => !v)}>{showDeleted ? 'Active entries' : 'Deleted entries'}</Button>
      <Button variant="outlined" color="inherit" startIcon={<Refresh/>} onClick={() => void load()}>Refresh</Button>
    </Stack>}/>
    {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}{notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    <Paper variant="outlined" sx={{ p: 1.5 }}><Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2}>
      <TextField select size="small" label="Rig" value={rigFilter} onChange={e => setRigFilter(e.target.value)} sx={{ minWidth: 190 }}><MenuItem value="">All rigs</MenuItem>{reference.rigs.map(r => <MenuItem key={r.id} value={r.id}>{r.display_name}</MenuItem>)}</TextField>
      <TextField select size="small" label="Well" value={wellFilter} onChange={e => setWellFilter(e.target.value)} sx={{ minWidth: 210 }}><MenuItem value="">All wells</MenuItem>{filterWells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}</TextField>
      <TextField select size="small" label="Scope" value={scopeFilter} onChange={e => setScopeFilter(e.target.value)} sx={{ minWidth: 145 }}><MenuItem value="">All scopes</MenuItem><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem></TextField>
      <TextField size="small" type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} InputLabelProps={{ shrink: true }}/><TextField size="small" type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} InputLabelProps={{ shrink: true }}/>
      {(rigFilter || wellFilter || scopeFilter || dateFrom || dateTo) && <Button onClick={() => { setRigFilter(''); setWellFilter(''); setScopeFilter(''); setDateFrom(''); setDateTo('') }}>Clear</Button>}
    </Stack></Paper>
    {selected.length > 0 && <Paper variant="outlined" sx={{ px: 1.5, py: 1 }}><Stack direction="row" alignItems="center" gap={1}><Typography variant="body2" fontWeight={700}>{selected.length} selected</Typography>{!showDeleted && can('daily-cost:delete') && <Button color="error" size="small" onClick={() => setConfirm({ kind: 'delete', ids: selected.map(row => row.id) })}>Delete</Button>}{showDeleted && can('daily-cost:restore') && <Button size="small" onClick={() => setConfirm({ kind: 'restore', ids: selected.map(row => row.id) })}>Restore</Button>}{showDeleted && can('daily-cost:permanent-delete') && <Button color="error" size="small" onClick={() => setConfirm({ kind: 'purge', ids: selected.map(row => row.id) })}>Delete permanently</Button>}</Stack></Paper>}
    <DataTable rows={rows} columns={columns} selectable onSelectionChange={setSelected} selectionResetKey={`${showDeleted}-${query}`} fillHeight exportName={showDeleted ? 'deleted-ndt-inspections' : 'ndt-inspection-register'} canExport={can('daily-cost:export')} onExport={(format, record_count) => api('/ndt-inspections/export-audit', { method: 'POST', body: body({ format, record_count, include_deleted: showDeleted }) })} searchPlaceholder="Search inspections..."/>
    {loading && <Typography color="text.secondary">Loading NDT inspections…</Typography>}

    <FormDialog open={editorOpen} onClose={() => setEditorOpen(false)} onSubmit={save} busy={saving} dirty title={editing ? 'Edit NDT Inspection' : 'Add NDT Inspection'} subtitle={editing ? 'Update this separately listed inspection line.' : 'Choose the shared scope, add line items, then save them together.'} submitLabel={editing ? 'Save changes' : `Save ${lines.length} line${lines.length === 1 ? '' : 's'}`} submitDisabled={!valid} maxWidth="xl">
      <Box display="grid" gap={2}>
        {formError && <Alert severity="error">{formError}</Alert>}
        <Paper variant="outlined" sx={{ p: 1.5 }}><Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
          <TextField select required fullWidth label="Rig" value={rigId} onChange={e => setRigId(e.target.value)}>{reference.rigs.map(r => <MenuItem key={r.id} value={r.id}>{r.display_name}</MenuItem>)}</TextField>
          <TextField select required fullWidth label="Well" value={wellId} onChange={e => setWellId(e.target.value)}>{editorWells.map(w => <MenuItem key={w.id} value={w.id}>{w.display_name}</MenuItem>)}</TextField>
          <TextField select required fullWidth label="Scope" value={scope} onChange={e => setScope(e.target.value as NdtScope)}><MenuItem value="drilling">Drilling</MenuItem><MenuItem value="completion">Completion</MenuItem></TextField>
        </Stack></Paper>
        <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Description</TableCell><TableCell align="right">Quantity received</TableCell><TableCell align="right">Quantity consumed</TableCell><TableCell align="right">Backloaded good</TableCell><TableCell align="right">Backloaded bad</TableCell><TableCell>Remarks</TableCell>{!editing && <TableCell width={48}/>}</TableRow></TableHead><TableBody>{lines.map((line, index) => <TableRow key={line.key}>
          <TableCell sx={{ minWidth: 220 }}><TextField required size="small" fullWidth value={line.description} inputProps={{ maxLength: 300 }} onChange={e => updateLine(line.key, 'description', e.target.value)} placeholder={`Line ${index + 1} description`}/></TableCell>
          {numericFields.map(field => <TableCell key={field} sx={{ minWidth: 145 }}><TextField required size="small" type="number" fullWidth value={line[field]} inputProps={{ min: 0, step: 'any' }} onChange={e => updateLine(line.key, field, e.target.value)}/></TableCell>)}
          <TableCell sx={{ minWidth: 200 }}><TextField size="small" fullWidth value={line.remarks} inputProps={{ maxLength: 500 }} onChange={e => updateLine(line.key, 'remarks', e.target.value)}/></TableCell>
          {!editing && <TableCell><IconButton aria-label="Remove line" disabled={lines.length === 1} onClick={() => setLines(current => current.filter(item => item.key !== line.key))}><DeleteOutline/></IconButton></TableCell>}
        </TableRow>)}</TableBody></Table></TableContainer>
        {!editing && <Box><Button startIcon={<Add/>} onClick={() => setLines(current => [...current, newNdtLine()])}>Add line item</Button></Box>}
      </Box>
    </FormDialog>
    <ImportDialog open={importOpen} onClose={() => setImportOpen(false)} title="Import NDT inspections" subtitle="Each spreadsheet row becomes a separate register line." headers={NDT_IMPORT_HEADERS} optionalHeaders={NDT_IMPORT_OPTIONAL} sample={NDT_IMPORT_SAMPLE} templateName="ndt-inspection-import" onRows={importRows}/>
    <FormDialog open={Boolean(confirm)} onClose={() => setConfirm(null)} onSubmit={runLifecycle} busy={saving} danger={confirm?.kind !== 'restore'} title={confirm?.kind === 'restore' ? 'Restore NDT inspections?' : confirm?.kind === 'purge' ? 'Permanently delete NDT inspections?' : 'Delete NDT inspections?'} subtitle={confirm?.kind === 'purge' ? 'This cannot be undone.' : confirm?.kind === 'restore' ? 'The selected lines will return to the active register.' : 'The selected lines can be restored from Deleted entries.'} submitLabel={confirm?.kind === 'restore' ? 'Restore' : confirm?.kind === 'purge' ? 'Delete permanently' : 'Delete'}><Typography>{confirm?.ids.length ?? 0} line(s) selected.</Typography></FormDialog>
  </Box>
}
