import { useCallback, useEffect, useMemo, useState } from 'react'
import { AddRounded, DeleteOutlineRounded, EditOutlined, HistoryOutlined, PriceChangeOutlined, UploadFileRounded } from '@mui/icons-material'
import { Alert, Box, Button, Chip, CircularProgress, Paper, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../DataTable'
import { ErrorMessage, FormDialog } from '../Common'
import { ImportDialog } from '../ImportDialog'
import { PricedItemFormDialog } from './PricedItemFormDialog'
import { ReviseRateDialog } from './ReviseRateDialog'
import { PriceHistoryDialog } from './PriceHistoryDialog'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import type { ImportRow } from '../../lib/export'
import {
  cellValue,
  emptyForm,
  formatDate,
  formatMoney,
  recordToForm,
  type FormState,
  type PricedOverview,
  type PricedRecord,
  type TypeConfig,
} from '../../lib/catalogue'

function StatCard({ label, value, hint }: { label: string; value: string | number; hint: string }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2 }}>
    <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
    <Typography className="stat-value" sx={{ fontSize: 27, my: 1 }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

// Register for one priced catalogue type: stats, grid, price history, and every write
// action. Pages supply the heading and tabs; the behaviour is identical for all types.
export function CatalogueItemRegister({ config }: { config: TypeConfig }) {
  const { can } = useAuth()
  const base = `/master-data/${config.key}`
  const [rows, setRows] = useState<PricedRecord[]>([])
  const [overview, setOverview] = useState<PricedOverview | null>(null)
  const [selected, setSelected] = useState<PricedRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null)
  const [formRecord, setFormRecord] = useState<PricedRecord | null>(null)
  const [form, setForm] = useState<FormState>({})
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)

  const [reviseRecord, setReviseRecord] = useState<PricedRecord | null>(null)
  const [reviseError, setReviseError] = useState('')
  const [revising, setRevising] = useState(false)
  const [historyRecord, setHistoryRecord] = useState<PricedRecord | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const [deleteRecord, setDeleteRecord] = useState<PricedRecord | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [records, summary] = await Promise.all([
        api<PricedRecord[]>(base),
        api<PricedOverview>(`${base}/overview`),
      ])
      setRows(records)
      setOverview(summary)
      setSelected([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `Could not load ${config.label}`)
    } finally {
      setLoading(false)
    }
  }, [base, config.label])

  useEffect(() => { void load() }, [load])

  const openCreate = () => {
    setFormRecord(null)
    setForm(emptyForm(config))
    setFormError('')
    setFormMode('create')
  }

  const openEdit = (record: PricedRecord) => {
    setFormRecord(record)
    setForm(recordToForm(config, record))
    setFormError('')
    setFormMode('edit')
  }

  const save = async (payload: Record<string, unknown>) => {
    setSaving(true)
    setFormError('')
    try {
      if (formRecord) {
        await api(`${base}/${formRecord.id}`, { method: 'PATCH', body: body(payload) })
        setNotice(`${formRecord[config.codeKey]} was updated.`)
      } else {
        const created = await api<PricedRecord>(base, { method: 'POST', body: body(payload) })
        setNotice(`${created[config.codeKey]} was created with its first rate (revision 1).`)
      }
      setFormMode(null)
      setFormRecord(null)
      await load()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : `Could not save this ${config.singular}`)
    } finally {
      setSaving(false)
    }
  }

  const revise = async (payload: Record<string, unknown>) => {
    if (!reviseRecord) return
    setRevising(true)
    setReviseError('')
    try {
      await api(`${base}/${reviseRecord.id}/revise`, { method: 'POST', body: body(payload) })
      setNotice(`${reviseRecord[config.codeKey]} was revised. The previous rate is kept in its price history.`)
      setReviseRecord(null)
      await load()
    } catch (caught) {
      setReviseError(caught instanceof Error ? caught.message : 'Could not save this revision')
    } finally {
      setRevising(false)
    }
  }

  const openDelete = (record?: PricedRecord) => {
    setDeleteRecord(record ?? null)
    setDeleteError('')
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setDeleteError('')
    const targets = deleteRecord ? [deleteRecord] : selected
    try {
      if (deleteRecord) await api(`${base}/${deleteRecord.id}`, { method: 'DELETE' })
      else await api(`${base}/bulk-delete`, { method: 'POST', body: body({ ids: targets.map(item => item.id) }) })
      setDeleteOpen(false)
      setDeleteRecord(null)
      setNotice(`${targets.length} ${targets.length === 1 ? config.singular : `${config.singular}s`} moved to Deleted Entries. Their price history is kept.`)
      await load()
    } catch (caught) {
      setDeleteError(caught instanceof Error ? caught.message : 'Could not move these records to Deleted Entries')
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<{ imported_count: number; error_count: number; errors: string[] }>(`${base}/import`, {
      method: 'POST',
      body: body({ rows: importedRows }),
    })
    await load()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} ${config.label.toLowerCase()}.`)
    if (!result.error_count) return []
    return [
      `Imported ${result.imported_count} of ${importedRows.length} rows. Fix the rows below and import them again.`,
      ...result.errors,
    ]
  }

  const logExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/master-data/export-audit', {
      method: 'POST',
      body: body({ module: config.key, format, record_count: recordCount, include_deleted: false }),
    })
  }

  const columns = useMemo<ColDef<PricedRecord>[]>(() => [
    ...config.columns.map<ColDef<PricedRecord>>(col => ({
      headerName: col.label,
      field: col.key,
      minWidth: col.width ?? 110,
      flex: col.flex,
      valueFormatter: params => params.data ? cellValue(col, params.data) : '',
    })),
    {
      headerName: 'ACTIONS', width: 330, minWidth: 330, maxWidth: 330, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: PricedRecord }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('master-data:update') && <Button size="small" onClick={() => openEdit(data)} aria-label={`Edit ${data[config.codeKey]}`} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}
        {can('master-data:update') && <Button size="small" onClick={() => { setReviseError(''); setReviseRecord(data) }} aria-label={`Revise rate for ${data[config.codeKey]}`} startIcon={<PriceChangeOutlined sx={{ fontSize: 15 }}/>}>Revise rate</Button>}
        <Button size="small" onClick={() => setHistoryRecord(data)} aria-label={`Price history for ${data[config.codeKey]}`} startIcon={<HistoryOutlined sx={{ fontSize: 15 }}/>}>History</Button>
        {can('master-data:delete') && <Button size="small" color="error" onClick={() => openDelete(data)} aria-label={`Delete ${data[config.codeKey]}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>}
      </Box>,
    },
  ], [config, can])

  const top = overview?.breakdown.slice().sort((a, b) => b.count - a.count)[0]
  const uplift = config.priced === 'uplift'

  return <>
    {overview && <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' }, mb: 2 }}>
      <StatCard label={`Active ${config.label.toLowerCase()}`} value={overview.active_count} hint={`${overview.deleted_count} in Deleted Entries`}/>
      <StatCard label="Rate revisions (30 days)" value={overview.revisions_last_30_days} hint="Price changes recorded in the last 30 days"/>
      <StatCard label={overview.breakdown_label ? `Top ${overview.breakdown_label.toLowerCase()}` : 'Records with a rate'} value={top ? top.count : overview.active_count} hint={top ? top.label : 'Every record keeps a price history'}/>
      <StatCard label="Price history" value={overview.recent_revisions.length} hint="Most recent changes listed below"/>
    </Box>}

    {overview && overview.breakdown.length > 0 && <Box display="flex" gap={1} flexWrap="wrap" mb={2}>
      <Typography fontSize={12} color="text.secondary" alignSelf="center" mr={.5}>By {overview.breakdown_label?.toLowerCase()}:</Typography>
      {overview.breakdown.map(item => <Chip key={item.key} size="small" label={`${item.label} · ${item.count}`} variant="outlined"/>)}
    </Box>}

    <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
      <Box>
        <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>{config.label} register</Typography>
        <Typography color="text.secondary" fontSize={12} mt={.35}>
          {rows.length} active {rows.length === 1 ? config.singular : `${config.singular}s`}. {uplift ? 'Final cost = rate as per PO × uplift ÷ 100.' : 'Rates are unit rates per the unit of measure.'} Rate changes go through Revise rate.
        </Typography>
      </Box>
      <Box display="flex" gap={1} flexWrap="wrap">
        {can('master-data:import') && <Button variant="outlined" startIcon={<UploadFileRounded/>} onClick={() => setImportOpen(true)}>Import</Button>}
        {can('master-data:delete') && <Button color="error" variant="outlined" startIcon={<DeleteOutlineRounded/>} disabled={!selected.length} onClick={() => openDelete()}>
          Move {selected.length || ''} to deleted entries
        </Button>}
        {can('master-data:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate}>Add {config.singular}</Button>}
      </Box>
    </Box>

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>

    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      rows={rows}
      columns={columns}
      searchPlaceholder={`Search ${config.label.toLowerCase()} by code, name, category, make...`}
      exportName={config.key}
      onImport={can('master-data:import') ? () => setImportOpen(true) : undefined}
      canExport={can('master-data:export')}
      onExport={logExport}
      selectable={can('master-data:delete')}
      onSelectionChange={setSelected}
    />}

    {overview && overview.recent_revisions.length > 0 && <Paper variant="outlined" sx={{ mt: 2.5, p: 2, borderRadius: 2 }}>
      <Typography fontFamily="Manrope" fontWeight={800} fontSize={14}>Recent price changes</Typography>
      <Box mt={1}>
        {overview.recent_revisions.map(revision => <Box key={revision.id} display="flex" gap={1.5} alignItems="baseline" sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1 }}>
          <Chip size="small" label={`${revision.item_code} · #${revision.revision_number}`}/>
          <Typography fontSize={12.5} fontWeight={700}>{formatMoney(revision.previous_unit_rate)} → {formatMoney(revision.unit_rate)} {revision.currency}</Typography>
          <Typography fontSize={12} color="text.secondary">effective {formatDate(revision.effective_date)} · {revision.reason || 'No reason given'} · {revision.recorded_by || 'Unknown user'}</Typography>
        </Box>)}
      </Box>
    </Paper>}

    <PricedItemFormDialog
      config={config}
      open={formMode !== null}
      mode={formMode ?? 'create'}
      title={formMode === 'edit' && formRecord ? `Edit ${formRecord[config.codeKey]}` : `Add ${config.singular}`}
      form={form}
      setForm={patch => setForm(current => ({ ...current, ...patch }))}
      record={formRecord}
      busy={saving}
      error={formError}
      onClose={() => { setFormMode(null); setFormRecord(null) }}
      onSubmit={payload => void save(payload)}
    />

    {reviseRecord && <ReviseRateDialog
      config={config}
      record={reviseRecord}
      busy={revising}
      error={reviseError}
      onClose={() => { if (!revising) setReviseRecord(null) }}
      onSubmit={payload => void revise(payload)}
    />}

    {historyRecord && <PriceHistoryDialog config={config} record={historyRecord} onClose={() => setHistoryRecord(null)}/>}

    <FormDialog
      open={deleteOpen}
      title={`Move ${deleteRecord ? config.singular : `${config.singular}s`} to Deleted Entries?`}
      subtitle="This is a soft delete. The price history is kept, and you can restore the record or delete it permanently from Deleted Entries."
      onClose={() => { if (!deleting) { setDeleteOpen(false); setDeleteRecord(null) } }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>
          {deleteRecord
            ? `“${deleteRecord[config.codeKey]} — ${deleteRecord[config.nameKey]}” will be moved to Deleted Entries.`
            : `${selected.length} selected ${selected.length === 1 ? config.singular : `${config.singular}s`} will be moved to Deleted Entries.`}
        </Typography>
        <ErrorMessage message={deleteError}/>
      </Box>
    </FormDialog>

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title={`Import ${config.label.toLowerCase()}`}
      subtitle={config.importHint}
      headers={config.importHeaders}
      optionalHeaders={config.importOptional}
      sample={config.sample}
      templateName={config.templateName}
      onRows={importRows}
    />
  </>
}
