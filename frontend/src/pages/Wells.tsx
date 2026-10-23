import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { AddRounded, ArrowDropDownRounded, DeleteOutlineRounded, EditOutlined, ListAltRounded, TuneRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, IconButton, Menu, MenuItem, Paper, Tab, Tabs, TextField, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag, useFormDirty } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import { PlanAdjustmentDialog } from '../components/PlanAdjustmentDialog'
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
  type BlockOption,
  type ImportResult,
  type RigOption,
  type Well,
  type WellConfigurationScope,
  type WellPayload,
} from '../lib/rigWell'

type WellTab = 'configured' | 'final_review' | 'completed'

const TABS: { key: WellTab; label: string }[] = [
  { key: 'configured', label: 'Configured wells' },
  { key: 'final_review', label: 'Wells for final review' },
  { key: 'completed', label: 'Completed wells' },
]

type TransitionAction = 'configure' | 'draft' | 'final_review' | 'complete' | 'activate'

type ScopeRow = { well: Well; scope: WellConfigurationScope }

function scopeState(well: Well, scope: WellConfigurationScope) {
  return scope === 'completion'
    ? {
        status: well.completion_status,
        config_status: well.completion_config_status,
        section_count: well.completion_section_count,
        sub_activity_count: well.completion_sub_activity_count ?? 0,
        total_depth: well.completion_total_depth,
        total_depth_m: well.completion_total_depth_m,
        total_days: well.completion_total_days,
        depth_unit: well.completion_depth_unit,
      }
    : {
        status: well.status,
        config_status: well.config_status,
        section_count: well.section_count,
        sub_activity_count: well.drilling_sub_activity_count ?? 0,
        total_depth: well.total_depth,
        total_depth_m: well.total_depth_m,
        total_days: well.total_days,
        depth_unit: well.depth_unit,
      }
}

function scopeName(scope: WellConfigurationScope) {
  return scope === 'drilling' ? 'Drilling' : 'Completion'
}

function planTone(config_status: string) {
  if (config_status === 'configured') return 'success'
  if (config_status === 'final_review') return 'warning'
  return 'warning'
}

function statusTone(status: string) {
  return status === 'completed' ? 'neutral' : 'success'
}

function WellActions({
  well,
  scope,
  canEdit,
  canDelete,
  canAdjustPlan,
  onEdit,
  onConfigure,
  onDelete,
  onTransition,
  onAdjustPlan,
  onActivateOtherScope,
}: {
  well: Well
  scope: WellConfigurationScope
  canEdit: boolean
  canDelete: boolean
  canAdjustPlan: boolean
  onEdit: () => void
  onConfigure: () => void
  onDelete: () => void
  onTransition: (action: TransitionAction) => void
  onAdjustPlan: () => void
  onActivateOtherScope: (otherScope: WellConfigurationScope) => void
}) {
  const plan = scopeState(well, scope)
  const label = scopeName(scope)
  const otherScope: WellConfigurationScope = scope === 'drilling' ? 'completion' : 'drilling'
  const otherIsMissing = otherScope === 'completion' ? well.completion_purged : well.drilling_purged
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const menuOpen = Boolean(anchor)
  const close = () => setAnchor(null)
  const action = (next: TransitionAction) => { close(); onTransition(next) }
  return (
    <Box display="flex" alignItems="center" height="100%" gap={.1}>
      {canEdit && <Button size="small" aria-label={`Edit well ${well.well_code}`} onClick={onEdit} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
      <Tooltip title={`View or edit ${label.toLowerCase()} well plan`}>
        <IconButton size="small" aria-label={`${canEdit ? 'Configure' : 'View'} ${label} plan ${well.well_code}`} onClick={onConfigure}><TuneRounded fontSize="small"/></IconButton>
      </Tooltip>
      <Tooltip title={`Open ${label.toLowerCase()} sub activities`}>
        <IconButton
          component={RouterLink}
          to={`/rig-well/sub-activities?rig_id=${encodeURIComponent(well.rig_id)}&well_id=${encodeURIComponent(well.id)}&scope=${scope}`}
          size="small"
          aria-label={`Open ${label} sub activities for ${well.well_code}`}
        >
          <ListAltRounded fontSize="small"/>
        </IconButton>
      </Tooltip>
      {canAdjustPlan && plan.config_status === 'configured' && <Tooltip title={`SOW plan adjustments (${label.toLowerCase()} planned days)`}>
        <Button size="small" onClick={onAdjustPlan}>Plan adj.</Button>
      </Tooltip>}
      {(canEdit || canDelete) && <>
        <Button size="small" color="inherit" endIcon={<ArrowDropDownRounded/>} onClick={event => setAnchor(event.currentTarget)}>Status</Button>
        <Menu anchorEl={anchor} open={menuOpen} onClose={close}>
          {canEdit && plan.status === 'completed' && <MenuItem onClick={() => action('activate')}>Reactivate {label} scope</MenuItem>}
          {canEdit && plan.status === 'active' && plan.config_status === 'draft' && plan.section_count > 0 && <MenuItem onClick={() => action('configure')}>Mark {label} configured</MenuItem>}
          {canEdit && plan.status === 'active' && plan.config_status === 'draft' && plan.section_count === 0 && <MenuItem disabled>Save a {label.toLowerCase()} plan before configuring</MenuItem>}
          {canEdit && plan.status === 'active' && plan.config_status === 'configured' && <MenuItem onClick={() => action('draft')}>Reopen {label} as Draft</MenuItem>}
          {canEdit && plan.status === 'active' && plan.config_status === 'configured' && <MenuItem onClick={() => action('final_review')}>Mark {label} for final review</MenuItem>}
          {canEdit && plan.status === 'active' && plan.config_status === 'final_review' && <MenuItem onClick={() => action('complete')}>Mark {label} completed</MenuItem>}
          {canEdit && otherIsMissing && <MenuItem onClick={() => { close(); onActivateOtherScope(otherScope) }}>Add {scopeName(otherScope)} scope</MenuItem>}
          {canDelete && <MenuItem sx={{ color: 'error.main' }} onClick={() => { close(); onDelete() }}>Move {label} scope to Deleted Entries</MenuItem>}
        </Menu>
      </>}
    </Box>
  )
}

const transitionCopy: Record<TransitionAction, { title: (scope: string) => string; label: (scope: string) => string; description: string }> = {
  configure: {
    title: scope => `Mark ${scope} plan as configured?`,
    label: scope => `Mark ${scope} configured`,
    description: 'The saved plan becomes a configured well baseline. Reopen it as Draft before editing.',
  },
  draft: {
    title: scope => `Reopen ${scope} plan as Draft?`,
    label: scope => `Reopen ${scope} as Draft`,
    description: 'This unlocks the well plan for edits. The change is recorded in the audit trail.',
  },
  final_review: {
    title: scope => `Mark ${scope} scope for final review?`,
    label: scope => `Mark ${scope} for final review`,
    description: 'The configured plan moves to final review. From there the scope can be marked completed.',
  },
  complete: {
    title: scope => `Mark ${scope} scope completed?`,
    label: scope => `Complete ${scope} scope`,
    description: 'Only this scope is marked complete. Its plan stays read-only until this scope is reactivated.',
  },
  activate: {
    title: scope => `Reactivate ${scope} scope?`,
    label: scope => `Reactivate ${scope} scope`,
    description: 'The scope returns to Active with its plan marked Configured.',
  },
}

const SCOPE_PRESETS: { value: string; label: string; scopes: WellConfigurationScope[] }[] = [
  { value: 'both', label: 'Drilling & Completion', scopes: ['drilling', 'completion'] },
  { value: 'drilling', label: 'Drilling only (no completion planned)', scopes: ['drilling'] },
  { value: 'completion', label: 'Completion only', scopes: ['completion'] },
]

function scopePresetValue(scopes: WellConfigurationScope[]): string {
  if (scopes.includes('drilling') && scopes.includes('completion')) return 'both'
  if (scopes.includes('completion')) return 'completion'
  return 'drilling'
}

export default function Wells() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const active: WellTab = TABS.some(tab => tab.key === requested) ? (requested as WellTab) : 'configured'
  const [rows, setRows] = useState<Well[]>([])
  const [rigs, setRigs] = useState<RigOption[]>([])
  const [blocks, setBlocks] = useState<BlockOption[]>([])
  const [blockFilter, setBlockFilter] = useState('')
  const [selectedRows, setSelectedRows] = useState<ScopeRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Well | null>(null)
  const [form, setForm] = useState<WellPayload>(emptyWellForm)
  const formDirty = useFormDirty(form, formOpen)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteRecord, setDeleteRecord] = useState<ScopeRow | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [configurationTarget, setConfigurationTarget] = useState<ScopeRow | null>(null)
  const [adjustTarget, setAdjustTarget] = useState<ScopeRow | null>(null)
  const [transitionTarget, setTransitionTarget] = useState<ScopeRow | null>(null)
  const [transitionAction, setTransitionAction] = useState<TransitionAction>('configure')
  const [transitionRemarks, setTransitionRemarks] = useState('')
  const [transitionError, setTransitionError] = useState('')
  const [transitioning, setTransitioning] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const query = blockFilter ? `?block_id=${encodeURIComponent(blockFilter)}` : ''
      const [wellRows, rigOptions, blockOptions] = await Promise.all([
        api<Well[]>(`/rig-well/wells${query}`),
        api<RigOption[]>('/rig-well/rigs/dropdown'),
        api<BlockOption[]>('/rig-well/blocks/dropdown'),
      ])
      setRows(wellRows)
      setRigs(rigOptions)
      setBlocks(blockOptions)
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Wells could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [blockFilter])

  useEffect(() => { void load() }, [load])

  const scopeRows = useMemo<ScopeRow[]>(() => rows.flatMap(well => {
    const out: ScopeRow[] = []
    if (!well.drilling_is_deleted) out.push({ well, scope: 'drilling' })
    if (!well.completion_is_deleted) out.push({ well, scope: 'completion' })
    return out
  }), [rows])

  const tabRows = useMemo<ScopeRow[]>(() => scopeRows.filter(row => {
    const { status, config_status } = scopeState(row.well, row.scope)
    if (active === 'configured') return status === 'active' && (config_status === 'configured' || config_status === 'draft')
    if (active === 'final_review') return status === 'active' && config_status === 'final_review'
    return status === 'completed'
  }), [scopeRows, active])

  const counts = useMemo(() => {
    const tally = { configured: 0, draft: 0, final_review: 0, completed: 0 }
    scopeRows.forEach(row => {
      const { status, config_status } = scopeState(row.well, row.scope)
      if (status === 'completed') tally.completed += 1
      else if (config_status === 'final_review') tally.final_review += 1
      else if (config_status === 'configured') tally.configured += 1
      else tally.draft += 1
    })
    return tally
  }, [scopeRows])

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
      block_id: well.block_id,
      well_code: well.well_code,
      well_name: well.well_name,
      well_location: well.well_location,
      objective: well.objective,
      remarks: well.remarks,
      scopes: ['drilling', 'completion'],
    })
    setFormError('')
    setFormOpen(true)
  }

  const activateScope = async (well: Well, scope: WellConfigurationScope) => {
    setError('')
    try {
      await api(`/rig-well/wells/${well.id}/scopes/${scope}/activate`, { method: 'POST' })
      setNotice(`${scopeName(scope)} scope added to ${well.well_code}.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Well scope could not be added')
    }
  }

  const save = async () => {
    setSaving(true)
    setFormError('')
    const basePayload = {
      rig_id: form.rig_id,
      block_id: form.block_id,
      well_code: form.well_code.trim(),
      well_name: form.well_name.trim(),
      well_location: form.well_location.trim(),
      objective: form.objective.trim(),
      remarks: form.remarks.trim(),
    }
    try {
      if (formRecord) {
        await api(`/rig-well/wells/${formRecord.id}`, { method: 'PATCH', body: body(basePayload) })
        setNotice(`${formRecord.well_code} was updated.`)
      } else {
        const created = await api<Well>('/rig-well/wells', {
          method: 'POST',
          body: body({ ...basePayload, scopes: form.scopes }),
        })
        setNotice(`${created.well_code} was created under ${created.rig_code} in block ${created.block_code}.`)
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

  const openDelete = (target?: ScopeRow) => {
    setDeleteRecord(target ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }
  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selectedRows
    try {
      if (deleteRecord) {
        await api(`/rig-well/wells/${deleteRecord.well.id}?scope=${deleteRecord.scope}`, { method: 'DELETE' })
      } else {
        await api('/rig-well/wells/bulk-delete', {
          method: 'POST',
          body: body({ items: targets.map(item => ({ id: item.well.id, scope: item.scope })) }),
        })
      }
      setDeleteOpen(false)
      setDeleteRecord(null)
      setSelectedRows([])
      setNotice(
        targets.length === 1
          ? `${targets[0].well.well_code} (${scopeName(targets[0].scope)}) was moved to Deleted Entries.`
          : `${targets.length} well scopes were moved to Deleted Entries.`,
      )
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these well scopes to Deleted Entries')
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

  const openTransition = (row: ScopeRow, action: TransitionAction) => {
    setTransitionTarget(row)
    setTransitionAction(action)
    setTransitionRemarks('')
    setTransitionError('')
  }
  const confirmTransition = async () => {
    if (!transitionTarget) return
    setTransitioning(true)
    setTransitionError('')
    try {
      await api(`/rig-well/wells/${transitionTarget.well.id}/transition`, {
        method: 'POST',
        body: body({ action: transitionAction, scope: transitionTarget.scope, remarks: transitionRemarks.trim() }),
      })
      setNotice(`${transitionTarget.well.well_code} · ${scopeName(transitionTarget.scope)}: ${transitionCopy[transitionAction].label(scopeName(transitionTarget.scope)).toLowerCase()} was recorded.`)
      setTransitionTarget(null)
      await load()
    } catch (caught) {
      setTransitionError(caught instanceof Error ? caught.message : 'Well scope status could not be updated')
    } finally {
      setTransitioning(false)
    }
  }

  const columns = useMemo<ColDef<ScopeRow>[]>(() => [
    { headerName: 'WELL CODE', field: 'well.well_code', minWidth: 125, flex: .75 },
    { headerName: 'WELL NAME', field: 'well.well_name', minWidth: 180, flex: 1.1 },
    { headerName: 'RIG', field: 'well.rig_display', minWidth: 170, flex: 1 },
    { headerName: 'BLOCK', field: 'well.block_code', minWidth: 190, flex: 1, valueFormatter: params => params.data ? `${params.data.well.block_code} \u2014 ${params.data.well.block_name}` : '' },
    { headerName: 'SCOPE', field: 'scope', minWidth: 115, maxWidth: 130, cellRenderer: ({ data }: { data: ScopeRow }) => <Box display="flex" alignItems="center" height="100%"><Tag tone="info">{scopeName(data.scope)}</Tag></Box> },
    {
      headerName: 'SCOPE STATUS', minWidth: 135, maxWidth: 155,
      valueGetter: params => params.data ? scopeState(params.data.well, params.data.scope).status : '',
      cellRenderer: ({ data }: { data: ScopeRow }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={statusTone(scopeState(data.well, data.scope).status)}>{scopeState(data.well, data.scope).status}</Tag></Box>,
    },
    {
      headerName: 'PLAN', minWidth: 135, maxWidth: 155,
      valueGetter: params => params.data ? scopeState(params.data.well, params.data.scope).config_status : '',
      cellRenderer: ({ data }: { data: ScopeRow }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={planTone(scopeState(data.well, data.scope).config_status)}>{scopeState(data.well, data.scope).config_status}</Tag></Box>,
    },
    {
      headerName: 'PLANNED DEPTH (m)', minWidth: 165,
      valueGetter: params => {
        if (!params.data) return null
        const plan = scopeState(params.data.well, params.data.scope)
        return formatDepth(plan.total_depth, plan.depth_unit, plan.total_depth_m)
      },
    },
    {
      headerName: 'PLANNED DAYS', minWidth: 125,
      valueGetter: params => params.data ? formatDays(scopeState(params.data.well, params.data.scope).total_days) : '',
    },
    {
      headerName: 'ADJ PLANNED DAYS', field: 'well.adjusted_total_days', minWidth: 150,
      headerTooltip: 'Adjusted planned days from the approved plan adjustment (drilling scope)',
      valueGetter: params => {
        if (!params.data || params.data.scope !== 'drilling') return '\u2014'
        return params.data.well.adjusted_total_days == null ? '\u2014' : formatDays(params.data.well.adjusted_total_days)
      },
    },
    {
      headerName: 'SUB ACTIVITIES', minWidth: 125, maxWidth: 145,
      valueGetter: params => params.data ? scopeState(params.data.well, params.data.scope).sub_activity_count : 0,
      valueFormatter: params => Number(params.value ?? 0).toLocaleString(),
    },
    { headerName: 'UPDATED', field: 'well.updated_at', minWidth: 135, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: ScopeRow }) => data && <WellActions
        well={data.well}
        scope={data.scope}
        canEdit={can('rig-well:update')}
        canDelete={can('rig-well:delete')}
        canAdjustPlan={can('rig-well:plan-adjust')}
        onEdit={() => openEdit(data.well)}
        onConfigure={() => setConfigurationTarget(data)}
        onDelete={() => openDelete(data)}
        onTransition={action => openTransition(data, action)}
        onAdjustPlan={() => setAdjustTarget(data)}
        onActivateOtherScope={otherScope => void activateScope(data.well, otherScope)}
      />,
    },
  ], [can])

  const transition = transitionTarget ? transitionCopy[transitionAction] : null
  const transitionScope = transitionTarget ? scopeName(transitionTarget.scope) : ''

  return (
    <>
      <PageHeading
        eyebrow="RIG & WELL MANAGEMENT / WELL REGISTER"
        title="Wells"
        subtitle="Every well belongs to one active rig. Each well tracks its Drilling and Completion scopes separately, with its own plan, sub activities, AFEs and cost registers. Unused scopes can be moved to Deleted Entries independently."
        action={<Box display="flex" gap={1} flexWrap="wrap">
          <Button component={RouterLink} to="/rig-well/deleted" variant="outlined" startIcon={<DeleteOutlineRounded/>}>Deleted entries</Button>
          {can('rig-well:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!rigs.length || !blocks.length}>Add well</Button>}
        </Box>}
      />

      {!rigs.length && <Alert severity="warning" sx={{ mb: 1.8 }} action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/rigs" size="small">Create a rig</Button> : undefined}>Create at least one active rig before adding wells. Rigs are maintained in the Rig register.</Alert>}
      {!blocks.length && <Alert severity="warning" sx={{ mb: 1.8 }} action={can('rig-well:create') ? <Button component={RouterLink} to="/rig-well/blocks" size="small">Create a block</Button> : undefined}>Create at least one active block before adding wells. Every well takes its block from the Block register, and the well register is segregated by block.</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
      <ErrorMessage message={error} />

      <Box borderBottom={1} borderColor="divider" mb={2}>
        <Tabs value={active} onChange={(_event, value: WellTab) => setParams(value === 'configured' ? {} : { tab: value })} aria-label="Well register tabs">
          {TABS.map(tab => <Tab key={tab.key} value={tab.key} label={tab.label} id={`wells-tab-${tab.key}`} aria-controls={`wells-panel-${tab.key}`} />)}
        </Tabs>
      </Box>
      <Box role="tabpanel" id={`wells-panel-${active}`} aria-labelledby={`wells-tab-${active}`}>
        <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.8, borderRadius: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
            <Box>
              <Typography fontWeight={800} fontSize={15}>{TABS.find(tab => tab.key === active)?.label}</Typography>
              <Typography color="text.secondary" fontSize={12} mt={.35}>
                {counts.configured} configured · {counts.draft} in draft · {counts.final_review} for final review · {counts.completed} completed
                {blockFilter ? ` · segregated to ${blocks.find(block => block.id === blockFilter)?.display_name ?? 'the selected block'}` : '.'}
              </Typography>
            </Box>
            <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
              <TextField
                select
                size="small"
                label="Segregate by block"
                value={blockFilter}
                onChange={event => setBlockFilter(event.target.value)}
                sx={{ minWidth: 245 }}
              >
                <MenuItem value="">All blocks ({blocks.reduce((total, block) => total + block.well_count, 0)} wells)</MenuItem>
                {blocks.map(block => <MenuItem key={block.id} value={block.id}>{block.display_name} ({block.well_count})</MenuItem>)}
              </TextField>
              {blockFilter && <Button size="small" variant="outlined" onClick={() => setBlockFilter('')}>Clear</Button>}
              {can('rig-well:delete') && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openDelete()}>Move {selectedRows.length || ''} to Deleted Entries</Button>}
            </Box>
          </Box>
          {selectedRows.length > 0 && <Alert severity="info" sx={{ mt: 1.5 }}>
            {selectedRows.length} scope row{selectedRows.length === 1 ? '' : 's'} selected. Only the selected scope{selectedRows.length === 1 ? '' : 's'} will be moved to Deleted Entries; any active sibling scope remains untouched.
          </Alert>}
        </Paper>
        {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26} /></Box> : <DataTable
          fillHeight
          rows={tabRows}
          columns={columns}
          rowKey={row => `${row.well.id}|${row.scope}`}
          searchPlaceholder="Search wells by code, rig, block, location, objective..."
          exportName={`wells-${active}`}
          onImport={can('rig-well:import') ? () => setImportOpen(true) : undefined}
          canExport={can('rig-well:export')}
          onExport={onExport}
          selectable={can('rig-well:delete')}
          onSelectionChange={setSelectedRows}
        />}
      </Box>

      <FormDialog
        open={formOpen}
        title={formRecord ? `Edit well ${formRecord.well_code}` : 'Add well'}
        subtitle="Assign the well to an active rig and block. Well codes are unique across the workspace."
        onClose={() => { if (!saving) { setFormOpen(false); setFormRecord(null) } }}
        onSubmit={() => void save()}
        busy={saving}
        dirty={formDirty}
        submitDisabled={!rigs.length || !blocks.length || !form.rig_id || !form.block_id || !form.well_code.trim() || !form.well_name.trim() || !form.well_location.trim() || !form.objective.trim()}
        submitLabel={formRecord ? 'Save changes' : 'Create well'}
      >
        <Box display="grid" gap={2} pt={.5}>
          <TextField select label="Rig" required fullWidth value={form.rig_id} onChange={event => setForm({ ...form, rig_id: event.target.value })}>
            {rigs.map(rig => <MenuItem key={rig.id} value={rig.id}>{rig.display_name}</MenuItem>)}
          </TextField>
          <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.4fr' }} gap={1.5}>
            <TextField label="Well code" required fullWidth value={form.well_code} onChange={event => setForm({ ...form, well_code: event.target.value })} inputProps={{ maxLength: 50 }} helperText="Workspace-unique; normalized to uppercase." />
            <TextField label="Well name" required fullWidth value={form.well_name} onChange={event => setForm({ ...form, well_name: event.target.value })} inputProps={{ maxLength: 200 }} />
          </Box>
          <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1.4fr 1fr' }} gap={1.5}>
            <TextField label="Well location" required fullWidth value={form.well_location} onChange={event => setForm({ ...form, well_location: event.target.value })} inputProps={{ maxLength: 300 }} />
            <TextField select label="Block" required fullWidth value={form.block_id} onChange={event => setForm({ ...form, block_id: event.target.value })} helperText={blocks.length ? 'Blocks are maintained in the Block register.' : 'Create a block first.'}>
              {blocks.map(block => <MenuItem key={block.id} value={block.id}>{block.display_name}</MenuItem>)}
            </TextField>
          </Box>
          {!formRecord && (
            <TextField
              select
              label="Planned scopes"
              required
              fullWidth
              value={scopePresetValue(form.scopes)}
              onChange={event => {
                const preset = SCOPE_PRESETS.find(item => item.value === event.target.value)
                setForm({ ...form, scopes: preset ? [...preset.scopes] : ['drilling', 'completion'] })
              }}
              helperText="Choose both scopes or start with only Drilling / Completion. You can add or remove scopes independently later."
            >
              {SCOPE_PRESETS.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
            </TextField>
          )}
          <TextField label="Objective" required fullWidth multiline minRows={2} value={form.objective} onChange={event => setForm({ ...form, objective: event.target.value })} inputProps={{ maxLength: 500 }} />
          <TextField label="Remarks" fullWidth multiline minRows={2} value={form.remarks} onChange={event => setForm({ ...form, remarks: event.target.value })} inputProps={{ maxLength: 1000 }} />
          <ErrorMessage message={formError} />
        </Box>
      </FormDialog>

      <FormDialog
        open={deleteOpen}
        title={deleteRecord ? `Move ${scopeName(deleteRecord.scope)} scope to Deleted Entries?` : 'Move selected well scopes to Deleted Entries?'}
        subtitle="Only dependencies belonging to the selected scope (its sub activities, AFEs and cost entries) are checked. Sibling active scopes remain untouched."
        onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
        onSubmit={() => void confirmDelete()}
        busy={deleting}
        submitLabel="Move to Deleted Entries"
      >
        <Box display="grid" gap={1.5} pt={.5}>
          <Typography fontSize={13}>
            {deleteRecord
              ? `The ${scopeName(deleteRecord.scope)} scope of “${deleteRecord.well.well_code} — ${deleteRecord.well.well_name}” under ${deleteRecord.well.rig_code} will be moved to Deleted Entries.`
              : `${selectedRows.length} selected well scope${selectedRows.length === 1 ? '' : 's'} will be moved to Deleted Entries.`}
          </Typography>
          <ErrorMessage message={deleteError} />
        </Box>
      </FormDialog>

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="Import wells"
        subtitle="Preview before import. Rig and block codes must resolve to active records in this workspace. Existing well codes are updated and deleted matches are restored."
        headers={WELL_IMPORT_HEADERS}
        optionalHeaders={WELL_IMPORT_OPTIONAL_HEADERS}
        sample={{ rig_code: 'RIG-001', block_code: 'BLOCK-A', well_code: 'WELL-001', well_name: 'North appraisal well', well_location: 'North field', objective: 'Appraisal', remarks: 'Sample row' }}
        templateName="well-register-template.csv"
        onRows={importRows}
      />

      <WellConfigurationDialog
        open={!!configurationTarget}
        well={configurationTarget?.well ?? null}
        initialScope={configurationTarget?.scope}
        onClose={() => setConfigurationTarget(null)}
        onSaved={() => { setNotice('Scoped well configuration updated.'); void load() }}
      />

      {adjustTarget && <PlanAdjustmentDialog
        open={!!adjustTarget}
        well={adjustTarget.well}
        initialScope={adjustTarget.scope}
        onClose={() => setAdjustTarget(null)}
        onChanged={() => { setNotice('Plan adjustment recorded.'); void load() }}
      />}

      <FormDialog
        open={!!transitionTarget}
        title={transition ? transition.title(transitionScope) : 'Update well scope'}
        subtitle={transition ? transition.description : ''}
        onClose={() => { if (!transitioning) { setTransitionTarget(null); setTransitionError('') } }}
        onSubmit={() => void confirmTransition()}
        busy={transitioning}
        submitDisabled={transitionRemarks.trim().length < 3}
        submitLabel={transition ? transition.label(transitionScope) : 'Confirm'}
      >
        <Box display="grid" gap={1.7} pt={.5}>
          {transitionTarget && <Typography fontSize={13}>{transitionTarget.well.well_code} — {transitionTarget.well.well_name} ({transitionTarget.well.rig_code}) · {transitionScope}</Typography>}
          <TextField label="Reason / audit note" required fullWidth multiline minRows={3} value={transitionRemarks} onChange={event => setTransitionRemarks(event.target.value)} inputProps={{ maxLength: 500 }} helperText="At least 3 characters. This note is stored in the audit trail." />
          <ErrorMessage message={transitionError} />
        </Box>
      </FormDialog>
    </>
  )
}
