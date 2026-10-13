import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ColDef } from 'ag-grid-community'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  MenuItem,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import { AddRounded, DeleteOutlineRounded, EditOutlined, PlaylistAddCheckRounded } from '@mui/icons-material'
import { api, body } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { DataTable } from '../components/DataTable'
import { FormDialog, PageHeading, useFormDirty } from '../components/Common'
import { ImportDialog } from '../components/ImportDialog'
import type { ImportRow } from '../lib/export'
import {
  COSTING_SET_GROUPS,
  COSTING_SET_ITEM_KIND_LABEL,
  type CostingSet,
  type CostingSetGroup,
  type CostingSetImportResult,
  type CostingSetInput,
  type CostingSetOption,
} from '../lib/costingSets'

type SetForm = {
  name: string
  item_group: CostingSetGroup
  description: string
  selected_items: string[]
}

type SetGridRow = {
  membership_id: string
  set_id: string
  set_name: string
  item_group: CostingSetGroup
  item_kind: string
  item_code: string
  item_name: string
  description: string
  updated_at: string
  is_available: boolean
}

const IMPORT_HEADERS = ['Set name', 'Item group', 'Item kind', 'Item code']
const EMPTY_FORM: SetForm = { name: '', item_group: 'services', description: '', selected_items: [] }
const keyOf = (kind: string, id: string) => `${kind}:${id}`

function StatCard({ label, value, hint }: { label: string; value: string | number; hint: string }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 27, my: 1 }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

function labelGroup(group: string) {
  return COSTING_SET_GROUPS.find(option => option.value === group)?.label ?? group
}

function labelDate(value: string) {
  return value ? new Date(value).toLocaleDateString() : ''
}

function normalizeGroup(value: string): CostingSetGroup | null {
  const normalized = value.trim().toLowerCase()
  if (normalized === 'service' || normalized === 'services') return 'services'
  if (normalized === 'tangible' || normalized === 'tangibles') return 'tangibles'
  if (normalized === 'consumable' || normalized === 'consumables') return 'consumables'
  return null
}

function normalizeKind(value: string): CostingSetInput['items'][number]['item_kind'] | null {
  const normalized = value.trim().toLowerCase().replace(/[\s-]+/g, '_')
  const aliases: Record<string, CostingSetInput['items'][number]['item_kind']> = {
    service: 'service',
    tangible: 'tangible',
    mud_chemical: 'mud_chemical',
    mud_chemicals: 'mud_chemical',
    cement_additive: 'cement_additive',
    cement_additives: 'cement_additive',
    fuel: 'fuel',
    drill_bit: 'drill_bit',
    drill_bits: 'drill_bit',
  }
  return aliases[normalized] ?? null
}

export default function CostingSets() {
  const { can } = useAuth()
  const [sets, setSets] = useState<CostingSet[]>([])
  const [options, setOptions] = useState<CostingSetOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<CostingSet | null>(null)
  const [form, setForm] = useState<SetForm>(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<CostingSet | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [setRows, itemOptions] = await Promise.all([
        api<CostingSet[]>('/costing-sets'),
        api<CostingSetOption[]>('/costing-sets/options'),
      ])
      setSets(setRows)
      setOptions(itemOptions)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load your costing sets')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setEditorOpen(true)
  }

  const openEdit = (set: CostingSet) => {
    setEditing(set)
    setForm({
      name: set.name,
      item_group: set.item_group,
      description: set.description,
      selected_items: set.items.map(item => keyOf(item.item_kind, item.item_id)),
    })
    setFormError('')
    setEditorOpen(true)
  }

  const closeEditor = () => {
    if (saving) return
    setEditorOpen(false)
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError('')
  }

  const dirty = useFormDirty(form, editorOpen)
  const activeOptions = useMemo(
    () => options.filter(option => option.item_group === form.item_group),
    [options, form.item_group],
  )
  const staleOptions = useMemo(() => {
    if (!editing || editing.item_group !== form.item_group) return []
    const known = new Set(activeOptions.map(option => keyOf(option.item_kind, option.item_id)))
    return editing.items
      .filter(item => !item.is_available && !known.has(keyOf(item.item_kind, item.item_id)))
      .map(item => ({
        item_group: editing.item_group,
        item_kind: item.item_kind,
        item_id: item.item_id,
        item_code: item.item_code,
        item_name: item.item_name,
        display_name: item.display_name,
        is_available: false,
      } satisfies CostingSetOption))
  }, [activeOptions, editing, form.item_group])
  const editorOptions = useMemo(() => [...activeOptions, ...staleOptions], [activeOptions, staleOptions])
  const selectedOptions = editorOptions.filter(option => form.selected_items.includes(keyOf(option.item_kind, option.item_id)))
  const staleSelectedCount = selectedOptions.filter(option => option.is_available === false).length

  const save = async () => {
    setFormError('')
    if (!form.name.trim()) {
      setFormError('Enter a name for this costing set.')
      return
    }
    if (!form.selected_items.length) {
      setFormError('Choose at least one active catalogue item.')
      return
    }
    const payload: CostingSetInput = {
      name: form.name.trim(),
      item_group: form.item_group,
      description: form.description.trim(),
      items: form.selected_items.map(value => {
        const separator = value.indexOf(':')
        return {
          item_kind: value.slice(0, separator) as CostingSetInput['items'][number]['item_kind'],
          item_id: value.slice(separator + 1),
        }
      }),
    }
    setSaving(true)
    try {
      if (editing) {
        await api(`/costing-sets/${editing.id}`, { method: 'PUT', body: body(payload) })
        setNotice(`${payload.name} was updated.`)
      } else {
        await api('/costing-sets', { method: 'POST', body: body(payload) })
        setNotice(`${payload.name} was created for your ${labelGroup(payload.item_group).toLowerCase()}.`)
      }
      setEditorOpen(false)
      setEditing(null)
      setForm(EMPTY_FORM)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not save this costing set')
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    setDeleteError('')
    try {
      await api(`/costing-sets/${deleteTarget.id}`, { method: 'DELETE' })
      setNotice(`${deleteTarget.name} was deleted.`)
      setDeleteTarget(null)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not delete this costing set')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (rows: ImportRow[]): Promise<string[]> => {
    const payload = rows.map(row => ({
      set_name: row['Set name'] ?? row.set_name ?? '',
      item_group: normalizeGroup(row['Item group'] ?? row.item_group ?? '') ?? (row['Item group'] ?? row.item_group ?? '').toLowerCase(),
      item_kind: normalizeKind(row['Item kind'] ?? row.item_kind ?? '') ?? (row['Item kind'] ?? row.item_kind ?? '').toLowerCase(),
      item_code: row['Item code'] ?? row.item_code ?? '',
      description: row.Description ?? row.description ?? '',
    }))
    const result = await api<CostingSetImportResult>('/costing-sets/import', {
      method: 'POST',
      body: body({ rows: payload }),
    })
    await load()
    if (result.created_sets || result.updated_sets || result.imported_items) {
      setNotice(`Import added ${result.imported_items} item(s) to ${result.created_sets} new and ${result.updated_sets} existing set(s).`)
    }
    if (!result.errors.length) return []
    return [
      `Imported ${result.imported_items} item(s). Correct the rows below and re-import; matching existing sets are merged safely.`,
      ...result.errors.map(problem => `Row ${problem.row} (${problem.set_name || 'unnamed set'} · ${problem.item_code || 'no item code'}): ${problem.message}`),
    ]
  }

  const rows = useMemo<SetGridRow[]>(() => sets.flatMap(set => set.items.map(item => ({
    membership_id: item.id,
    set_id: set.id,
    set_name: set.name,
    item_group: set.item_group,
    item_kind: item.item_kind,
    item_code: item.item_code,
    item_name: item.item_name,
    description: set.description,
    updated_at: set.updated_at,
    is_available: item.is_available,
  }))), [sets])

  const columns = useMemo<ColDef<SetGridRow>[]>(() => [
    { headerName: 'Set name', field: 'set_name', minWidth: 170, flex: 1 },
    { headerName: 'Item group', field: 'item_group', minWidth: 115, valueFormatter: params => labelGroup(params.value ?? '') },
    { headerName: 'Item kind', field: 'item_kind', minWidth: 135, valueFormatter: params => COSTING_SET_ITEM_KIND_LABEL[params.value as keyof typeof COSTING_SET_ITEM_KIND_LABEL] ?? params.value ?? '' },
    { headerName: 'Item code', field: 'item_code', minWidth: 120 },
    { headerName: 'Item name', field: 'item_name', minWidth: 170, flex: 1 },
    { headerName: 'Description', field: 'description', minWidth: 180, flex: 1, valueFormatter: params => params.value || '—' },
    { headerName: 'Available', field: 'is_available', minWidth: 105, valueFormatter: params => params.value ? 'Active' : 'Unavailable' },
    { headerName: 'Updated', field: 'updated_at', minWidth: 130, valueFormatter: params => labelDate(params.value ?? '') },
    {
      headerName: 'ACTIONS', width: 155, minWidth: 155, maxWidth: 155, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: SetGridRow }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('costing-sets:update') && <Button size="small" onClick={() => {
          const target = sets.find(set => set.id === data.set_id)
          if (target) openEdit(target)
        }} aria-label={`Edit ${data.set_name}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('costing-sets:delete') && <Button size="small" color="error" onClick={() => {
          const target = sets.find(set => set.id === data.set_id)
          if (target) { setDeleteError(''); setDeleteTarget(target) }
        }} aria-label={`Delete ${data.set_name}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [can, openEdit, sets])

  const groupCounts = useMemo(() => Object.fromEntries(COSTING_SET_GROUPS.map(group => [
    group.value,
    sets.filter(set => set.item_group === group.value).length,
  ])) as Record<CostingSetGroup, number>, [sets])
  const itemCount = sets.reduce((total, set) => total + set.item_count, 0)
  const submitDisabled = !form.name.trim() || !form.selected_items.length

  return <>
    <PageHeading
      eyebrow="COSTING WORKSPACE / PERSONAL SHORTCUTS"
      title="Reusable costing sets"
      subtitle="Save private lists of frequently used services, tangibles and consumables. Apply them as editable bulk-add shortcuts in an AFE estimate or daily cost sheet."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {can('costing-sets:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Create set</Button>}
      </Box>}
    />

    <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(4, 1fr)' }, mb: 2.5 }}>
      <StatCard label="Private sets" value={sets.length} hint="Visible only to your account"/>
      <StatCard label="Saved item links" value={itemCount} hint="Current and retained catalogue references"/>
      <StatCard label="Service sets" value={groupCounts.services} hint="For AFE and daily cost"/>
      <StatCard label="Catalogue sets" value={groupCounts.tangibles + groupCounts.consumables} hint="Tangibles and consumables"/>
    </Box>

    <Paper variant="outlined" sx={{ borderRadius: 2, borderColor: 'divider', overflow: 'hidden' }}>
      <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
        <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>Your saved set items</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>
              {sets.length} named set(s), {rows.length} item link(s). Export/import works one catalogue membership per row.
            </Typography>
          </Box>
          <Box display="flex" gap={1} flexWrap="wrap">
            {can('costing-sets:import') && <Button variant="outlined" startIcon={<PlaylistAddCheckRounded/>} onClick={() => setImportOpen(true)}>Import</Button>}
            {can('costing-sets:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Create set</Button>}
          </Box>
        </Box>
        <Alert severity="info" sx={{ mb: 1.5 }}>
          Sets store catalogue references only—not prices, currencies, section assignments or quantities. AFE and daily-cost sheets keep using their existing preview, validation and save workflow. Other users in this workspace cannot see your sets.
        </Alert>
        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
        {error && <Alert severity="error" onClose={() => setError('')} sx={{ mb: 1.5 }}>{error}</Alert>}
        {loading
          ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
          : <DataTable
            rows={rows}
            columns={columns}
            rowKey="membership_id"
            searchPlaceholder="Search set names, item type, code or item name..."
            exportName="my-costing-set-items"
            canExport={can('costing-sets:export')}
            onExport={async (format, recordCount) => {
              await api('/costing-sets/export-audit', {
                method: 'POST',
                body: body({ format, record_count: recordCount }),
              })
            }}
            onImport={can('costing-sets:import') ? () => setImportOpen(true) : undefined}
          />}
      </Box>
    </Paper>

    <FormDialog
      open={editorOpen}
      title={editing ? `Edit costing set · ${editing.name}` : 'Create reusable costing set'}
      subtitle="Choose one item group per set. Sets are private to your user account and store references—not rate or estimate data."
      onClose={closeEditor}
      onSubmit={() => void save()}
      dirty={dirty}
      busy={saving}
      busyLabel={editing ? 'Saving set...' : 'Creating set...'}
      submitLabel={editing ? 'Save set' : 'Create set'}
      submitDisabled={submitDisabled}
      maxWidth="md"
    >
      <Box display="grid" gap={1.7}>
        {formError && <Alert severity="error">{formError}</Alert>}
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
          <TextField label="Set name" required value={form.name} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} inputProps={{ maxLength: 100 }}/>
          <TextField select label="Item group" value={form.item_group} onChange={event => setForm(current => ({
            ...current,
            item_group: event.target.value as CostingSetGroup,
            selected_items: event.target.value === current.item_group ? current.selected_items : [],
          }))}>
            {COSTING_SET_GROUPS.map(group => <MenuItem key={group.value} value={group.value}>{group.label}</MenuItem>)}
          </TextField>
        </Box>
        <TextField label="Description (optional)" value={form.description} onChange={event => setForm(current => ({ ...current, description: event.target.value }))} inputProps={{ maxLength: 500 }}/>
        <Autocomplete
          multiple
          options={editorOptions}
          value={selectedOptions}
          onChange={(_event, selected) => setForm(current => ({
            ...current,
            selected_items: selected.map(option => keyOf(option.item_kind, option.item_id)),
          }))}
          isOptionEqualToValue={(option, value) => option.item_kind === value.item_kind && option.item_id === value.item_id}
          getOptionLabel={option => `${COSTING_SET_ITEM_KIND_LABEL[option.item_kind]} · ${option.display_name}`}
          filterSelectedOptions
          renderOption={(props, option) => <li {...props} key={keyOf(option.item_kind, option.item_id)}>
            <Box display="flex" justifyContent="space-between" width="100%" gap={2}>
              <Typography fontSize={12.5}>{COSTING_SET_ITEM_KIND_LABEL[option.item_kind]} · {option.display_name}</Typography>
              <Typography fontSize={11} color={option.is_available === false ? 'warning.main' : 'text.secondary'}>
                {option.is_available === false ? 'Unavailable' : 'Active'}
              </Typography>
            </Box>
          </li>}
          renderInput={params => <TextField
            {...params}
            label={`Catalogue items · ${labelGroup(form.item_group)}`}
            placeholder="Search by code or name"
            helperText="Choose one or more active catalogue items. Unavailable existing references can be removed or retained."
          />}
        />
        {staleSelectedCount > 0 && <Alert severity="warning">
          This set has {staleSelectedCount} retained catalogue reference(s) that are no longer active. You may keep them in the set (they will be skipped when applied) or remove them here.
        </Alert>}
        {!editorOptions.length && <Alert severity="info">There are no active {labelGroup(form.item_group).toLowerCase()} to add yet. Create or restore catalogue items in Master Data first.</Alert>}
      </Box>
    </FormDialog>

    <FormDialog
      open={Boolean(deleteTarget)}
      title={`Delete ${deleteTarget?.name ?? 'costing set'}?`}
      subtitle="This removes only your reusable shortcut. Existing estimates and daily cost sheets are not changed."
      onClose={() => { if (!deleting) { setDeleteTarget(null); setDeleteError('') } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      busyLabel="Deleting set..."
      submitLabel="Delete set"
      submitDisabled={!can('costing-sets:delete')}
      danger
    >
      <Box display="grid" gap={1}>
        {deleteError && <Alert severity="error">{deleteError}</Alert>}
        <Typography fontSize={13}>{deleteTarget?.item_count ?? 0} catalogue item(s) will be removed from this set only.</Typography>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import reusable costing sets"
      subtitle="Use one row per set item. Codes are resolved against active catalogue records in this workspace; matching same-name sets are merged."
      headers={IMPORT_HEADERS}
      optionalHeaders={['Description', 'Item name', 'Updated', 'Available']}
      sample={{
        'Set name': 'Drilling start-up',
        'Item group': 'services',
        'Item kind': 'service',
        'Item code': 'SVC-001',
        Description: 'Common drilling services',
      }}
      templateName="costing-sets-template.csv"
      onRows={importRows}
    />
  </>
}
