import { useCallback, useEffect, useMemo, useState } from 'react'
import { AddRounded, DeleteForeverOutlined, DeleteOutlineRounded, EditOutlined, RestoreOutlined } from '@mui/icons-material'
import { Alert, Box, Button, ButtonBase, CircularProgress, MenuItem, Paper, TextField, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading } from '../components/Common'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { formatDate, type CatalogueListSummary, type CatalogueOption, type OptionListKey } from '../lib/catalogue'

const MAX_BULK = 300

// "Tangible categories" -> "tangible category"; used in prose and field labels.
const singular = (label: string) => label.replace(/ies$/, 'y').replace(/s$/, '').toLowerCase()

// Catalogue lists are the dropdown values behind Tangibles and Consumables (categories,
// subcategories, manufacturers, drill bit types, mud chemical groups, cement additive types).
// Values are added, renamed and removed here, so forms never need their own dropdown editors.
export default function CatalogueLists() {
  const { can } = useAuth()
  const [summaries, setSummaries] = useState<CatalogueListSummary[]>([])
  const [listKey, setListKey] = useState<OptionListKey>('tangible_category')
  const [view, setView] = useState<'active' | 'removed'>('active')
  const [parentId, setParentId] = useState('')
  const [parents, setParents] = useState<CatalogueOption[]>([])
  const [rows, setRows] = useState<CatalogueOption[]>([])
  const [selected, setSelected] = useState<CatalogueOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [bulkText, setBulkText] = useState('')
  const [adding, setAdding] = useState(false)
  const [skipped, setSkipped] = useState<string[]>([])

  const [renameRecord, setRenameRecord] = useState<CatalogueOption | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState('')
  const [renaming, setRenaming] = useState(false)

  const [confirm, setConfirm] = useState<{ mode: 'remove' | 'purge'; items: CatalogueOption[] } | null>(null)
  const [confirmError, setConfirmError] = useState('')
  const [confirming, setConfirming] = useState(false)

  const current = summaries.find(item => item.key === listKey)
  const parentKey = current?.parent_key ?? null
  const parentLabel = current?.parent_label ?? ''
  const base = '/master-data/catalogue-options'
  const removedView = view === 'removed'

  const loadSummaries = useCallback(async () => {
    const lists = await api<CatalogueListSummary[]>(`${base}/lists`)
    setSummaries(lists)
    return lists
  }, [])

  const loadRows = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ list_key: listKey, deleted: String(removedView) })
      if (parentId) params.set('parent_id', parentId)
      const [options] = await Promise.all([api<CatalogueOption[]>(`${base}?${params.toString()}`), loadSummaries()])
      setRows(options)
      setSelected([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load this list')
    } finally {
      setLoading(false)
    }
  }, [listKey, removedView, parentId, loadSummaries])

  useEffect(() => { void loadRows() }, [loadRows])

  // Parent values are the active values of the list above this one (category for subcategories).
  useEffect(() => {
    if (!parentKey) { setParents([]); return }
    void api<CatalogueOption[]>(`${base}?list_key=${parentKey}&deleted=false`)
      .then(setParents)
      .catch(() => setParents([]))
  }, [parentKey])

  const selectList = (key: OptionListKey) => {
    setListKey(key)
    setParentId('')
    setSkipped([])
    setNotice('')
    setBulkText('')
  }

  const selectView = (next: 'active' | 'removed') => {
    setView(next)
    setSkipped([])
    setNotice('')
  }

  const addValues = async () => {
    const values = bulkText.split('\n').map(line => line.trim()).filter(Boolean)
    if (!values.length) return
    if (values.length > MAX_BULK) {
      setError(`Add up to ${MAX_BULK} values at a time.`)
      return
    }
    if (parentKey && !parentId) {
      setError(`Choose a ${singular(parentLabel)} first. Each ${singular(current?.label ?? 'value')} belongs to one ${singular(parentLabel)}.`)
      return
    }
    setAdding(true)
    setError('')
    setSkipped([])
    try {
      const result = await api<{ created_count: number; skipped: string[] }>(`${base}/bulk`, {
        method: 'POST',
        body: body({ list_key: listKey, values, parent_id: parentId || null }),
      })
      setSkipped(result.skipped)
      setNotice(result.created_count ? `${result.created_count} ${result.created_count === 1 ? 'value' : 'values'} added to ${current?.label ?? 'the list'}.` : 'No new values were added.')
      if (result.created_count) setBulkText('')
      await loadRows()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add these values')
    } finally {
      setAdding(false)
    }
  }

  const saveRename = async () => {
    if (!renameRecord) return
    setRenaming(true)
    setRenameError('')
    try {
      await api(`${base}/${renameRecord.id}`, { method: 'PATCH', body: body({ value: renameValue.trim() }) })
      setNotice(`Renamed to "${renameValue.trim()}". Records that use it show the new name.`)
      setRenameRecord(null)
      await loadRows()
    } catch (caught) {
      setRenameError(caught instanceof Error ? caught.message : 'Could not rename this value')
    } finally {
      setRenaming(false)
    }
  }

  const restore = async (items: CatalogueOption[]) => {
    setError('')
    try {
      if (items.length === 1) await api(`${base}/${items[0].id}/restore`, { method: 'POST' })
      else await api(`${base}/bulk-restore`, { method: 'POST', body: body({ ids: items.map(item => item.id) }) })
      setNotice(`${items.length} ${items.length === 1 ? 'value was' : 'values were'} restored.`)
      await loadRows()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not restore these values')
    }
  }

  const runConfirm = async () => {
    if (!confirm) return
    setConfirming(true)
    setConfirmError('')
    const ids = confirm.items.map(item => item.id)
    try {
      if (confirm.mode === 'remove') {
        if (ids.length === 1) await api(`${base}/${ids[0]}`, { method: 'DELETE' })
        else await api(`${base}/bulk-delete`, { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} ${ids.length === 1 ? 'value was' : 'values were'} removed. Records that use them keep the value, shown as removed.`)
      } else {
        if (ids.length === 1) await api(`${base}/${ids[0]}/permanent`, { method: 'DELETE' })
        else await api(`${base}/bulk-permanent-delete`, { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} ${ids.length === 1 ? 'value was' : 'values were'} permanently deleted.`)
      }
      setConfirm(null)
      await loadRows()
    } catch (caught) {
      setConfirmError(caught instanceof Error ? caught.message : 'This action could not be completed')
    } finally {
      setConfirming(false)
    }
  }

  const columns = useMemo<ColDef<CatalogueOption>[]>(() => [
    { headerName: 'VALUE', field: 'value', minWidth: 200, flex: 1.4 },
    ...(parentKey ? [{ headerName: singular(parentLabel).toUpperCase(), field: 'parent_value' as const, minWidth: 170, flex: 1, valueFormatter: (p: { value: string | null }) => p.value || '—' } satisfies ColDef<CatalogueOption>] : []),
    { headerName: 'USED IN RECORDS', field: 'usage_count', minWidth: 150, maxWidth: 170, type: 'numericColumn' },
    { headerName: removedView ? 'REMOVED' : 'LAST UPDATED', field: (removedView ? 'deleted_at' : 'updated_at') as 'deleted_at' | 'updated_at', minWidth: 130, valueFormatter: p => formatDate(p.value) },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: CatalogueOption }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {!removedView && can('master-data:update') && <Button size="small" onClick={() => { setRenameRecord(data); setRenameValue(data.value); setRenameError('') }} aria-label={`Rename ${data.value}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Rename</Button>}
        {!removedView && can('master-data:delete') && <Button size="small" color="error" onClick={() => { setConfirm({ mode: 'remove', items: [data] }); setConfirmError('') }} aria-label={`Remove ${data.value}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Remove</Button>}
        {removedView && can('master-data:restore') && <Button size="small" onClick={() => void restore([data])} aria-label={`Restore ${data.value}`} startIcon={<RestoreOutlined sx={{ fontSize: 15 }}/>}>Restore</Button>}
        {removedView && can('master-data:permanent-delete') && <Tooltip title={data.usage_count ? `Used by ${data.usage_count} records, so it cannot be deleted permanently` : ''}>
          <span><Button size="small" color="error" disabled={data.usage_count > 0} onClick={() => { setConfirm({ mode: 'purge', items: [data] }); setConfirmError('') }} aria-label={`Permanently delete ${data.value}`} startIcon={<DeleteForeverOutlined sx={{ fontSize: 15 }}/>}>Delete</Button></span>
        </Tooltip>}
      </Box>,
    },
  ], [parentKey, parentLabel, removedView, can])

  const activeSummary = current
  const parentName = parents.find(item => item.id === parentId)?.value

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / CATALOGUE LISTS"
      title="Catalogue lists"
      subtitle="The dropdown values used by Tangibles and Consumables. Add, rename or remove values here once, and every form uses the same list."
    />
    <MasterDataTabs active="catalogue-lists"/>

    <Box display="grid" gap={2.5} mt={2.5} sx={{ gridTemplateColumns: { xs: '1fr', md: '260px minmax(0, 1fr)' }, alignItems: 'start' }}>
      <Paper variant="outlined" sx={{ p: 1, borderRadius: 2 }} component="nav" aria-label="Catalogue lists">
        {summaries.map(item => <ButtonBase
          key={item.key}
          onClick={() => selectList(item.key)}
          aria-pressed={item.key === listKey}
          sx={{
            display: 'block', width: '100%', textAlign: 'left', p: 1.4, borderRadius: 1.5,
            bgcolor: item.key === listKey ? 'action.selected' : 'transparent',
            borderLeft: '3px solid', borderLeftColor: item.key === listKey ? 'primary.main' : 'transparent',
          }}
        >
          <Typography fontSize={13} fontWeight={800}>{item.label}</Typography>
          <Typography fontSize={11.5} color="text.secondary" mt={.3}>
            {item.active_count} active{item.parent_label ? ` · under ${item.parent_label.toLowerCase()}` : ''}{item.removed_count ? ` · ${item.removed_count} removed` : ''}
          </Typography>
        </ButtonBase>)}
      </Paper>

      <Box minWidth={0}>
        {activeSummary && <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={2} flexWrap="wrap" mb={1.5}>
          <Box>
            <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>{activeSummary.label}</Typography>
            <Typography color="text.secondary" fontSize={12} mt={.35}>
              {activeSummary.parent_label
                ? `Each value belongs to one ${singular(activeSummary.parent_label)}. Choose it below to filter, or to add values under it.`
                : 'Shared values. Changing a name here updates how records display it.'}
            </Typography>
          </Box>
          <Box display="flex" gap={1} alignItems="center">
            <Button variant={view === 'active' ? 'contained' : 'outlined'} size="small" onClick={() => selectView('active')} aria-pressed={view === 'active'}>Active · {activeSummary.active_count}</Button>
            <Button variant={view === 'removed' ? 'contained' : 'outlined'} size="small" onClick={() => selectView('removed')} aria-pressed={view === 'removed'}>Removed · {activeSummary.removed_count}</Button>
          </Box>
        </Box>}

        {!removedView && can('master-data:create') && <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, mb: 2 }}>
          <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', md: parentKey ? '240px 1fr' : '1fr' } }}>
            {parentKey && <TextField
              select
              label={`${singular(parentLabel)} filter`}
              value={parentId}
              onChange={event => setParentId(event.target.value)}
              size="small"
              helperText={parents.length ? 'Filters the list and sets where new values go.' : `Add a ${singular(parentLabel)} first.`}
            >
              <MenuItem value="">All (filter off)</MenuItem>
              {parents.map(item => <MenuItem key={item.id} value={item.id}>{item.value}</MenuItem>)}
            </TextField>}
            <Box>
              <TextField
                label={`Add ${activeSummary?.label.toLowerCase() ?? 'values'}${parentName ? ` under ${parentName}` : ''}`}
                placeholder="One value per line"
                multiline minRows={2} maxRows={6} fullWidth size="small"
                value={bulkText}
                onChange={event => setBulkText(event.target.value)}
                helperText={`Duplicates are skipped and reported. Up to ${MAX_BULK} values at a time.`}
                disabled={!!parentKey && !parentId}
              />
              <Box display="flex" justifyContent="flex-end" mt={1}>
                <Button variant="contained" startIcon={<AddRounded/>} onClick={() => void addValues()} disabled={adding || !bulkText.trim() || (!!parentKey && !parentId)}>
                  {adding ? 'Adding...' : 'Add values'}
                </Button>
              </Box>
            </Box>
          </Box>
          {skipped.length > 0 && <Alert severity="warning" sx={{ mt: 1.5 }}>
            <Typography fontSize={12.5} fontWeight={700}>{skipped.length} {skipped.length === 1 ? 'value was' : 'values were'} not added:</Typography>
            <Box component="ul" sx={{ m: 0, pl: 2.2, fontSize: 12.5 }}>{skipped.slice(0, 12).map(item => <li key={item}>{item}</li>)}</Box>
          </Alert>}
        </Paper>}

        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
        <ErrorMessage message={error}/>

        <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap" mb={1.5}>
          <Typography fontSize={12} color="text.secondary">
            {rows.length} {removedView ? 'removed' : 'active'} {rows.length === 1 ? 'value' : 'values'}{parentName ? ` under ${parentName}` : ''}.
          </Typography>
          <Box display="flex" gap={1} flexWrap="wrap">
            {removedView && can('master-data:restore') && <Button variant="outlined" startIcon={<RestoreOutlined/>} disabled={!selected.length} onClick={() => void restore(selected)}>Restore {selected.length || ''} selected</Button>}
            {removedView && can('master-data:permanent-delete') && <Button color="error" variant="outlined" startIcon={<DeleteForeverOutlined/>} disabled={!selected.length || selected.some(item => item.usage_count > 0)} onClick={() => { setConfirm({ mode: 'purge', items: selected }); setConfirmError('') }}>Delete {selected.length || ''} permanently</Button>}
            {!removedView && can('master-data:delete') && <Button color="error" variant="outlined" startIcon={<DeleteOutlineRounded/>} disabled={!selected.length} onClick={() => { setConfirm({ mode: 'remove', items: selected }); setConfirmError('') }}>Remove {selected.length || ''} selected</Button>}
          </Box>
        </Box>

        {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
          rows={rows}
          columns={columns}
          searchPlaceholder="Search values..."
          exportName={`catalogue-${listKey}`}
          canExport={can('master-data:export')}
          onExport={async (format, recordCount) => {
            await api('/master-data/export-audit', { method: 'POST', body: body({ module: 'catalogue-options', format, record_count: recordCount, include_deleted: removedView }) })
          }}
          selectable={can('master-data:delete') || can('master-data:permanent-delete') || can('master-data:restore')}
          onSelectionChange={setSelected}
        />}
      </Box>
    </Box>

    <FormDialog
      open={!!renameRecord}
      title={`Rename ${renameRecord?.value ?? 'value'}`}
      subtitle="Records that use this value will show the new name. The change is recorded in the audit log."
      onClose={() => { if (!renaming) setRenameRecord(null) }}
      onSubmit={() => void saveRename()}
      busy={renaming || !renameValue.trim()}
      submitLabel="Rename"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <TextField label="Value" required fullWidth autoFocus value={renameValue} onChange={event => setRenameValue(event.target.value)} inputProps={{ maxLength: 120 }}/>
        <ErrorMessage message={renameError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={!!confirm}
      title={confirm?.mode === 'purge' ? 'Delete permanently?' : 'Remove from the list?'}
      subtitle={confirm?.mode === 'purge'
        ? 'This cannot be undone. Only removed values that no record uses can be deleted permanently.'
        : 'Removed values stay in Removed, so you can restore them later. Records that use them keep the value.'}
      onClose={() => { if (!confirming) setConfirm(null) }}
      onSubmit={() => void runConfirm()}
      busy={confirming}
      submitLabel={confirm?.mode === 'purge' ? 'Delete permanently' : 'Remove'}
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {confirm && confirm.items.length === 1
            ? `“${confirm.items[0].value}” ${confirm.mode === 'purge' ? 'will be deleted permanently.' : 'will be removed.'}`
            : `${confirm?.items.length ?? 0} selected values ${confirm?.mode === 'purge' ? 'will be deleted permanently.' : 'will be removed.'}`}
        </Typography>
        <ErrorMessage message={confirmError}/>
      </Box>
    </FormDialog>
  </>
}
