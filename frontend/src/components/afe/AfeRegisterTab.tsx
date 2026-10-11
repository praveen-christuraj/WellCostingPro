import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AddRounded, ArrowForwardRounded, DeleteOutlineRounded, EditOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../DataTable'
import { ErrorMessage, FormDialog, Tag } from '../Common'
import { ImportDialog } from '../ImportDialog'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import type { ImportRow } from '../../lib/export'
import { amountText, totalsText, type Afe, type AfeReference, type ImportResponse } from '../../lib/afe'
import { AfeFormDialog } from './AfeFormDialog'
import { ErrorDetails, StatusTag } from './AfeShared'

export const AFE_IMPORT_HEADERS = ['rig_code', 'well_code', 'afe_code', 'afe_name', 'afe_type']
export const AFE_IMPORT_OPTIONAL_HEADERS = ['remarks']

function RowActions({ afe, canEdit, canDelete, onEstimate, onEdit, onDelete }: {
  afe: Afe
  canEdit: boolean
  canDelete: boolean
  onEstimate: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const draft = afe.status === 'draft'
  return <Box display="flex" alignItems="center" height="100%" gap={.2}>
    <Button size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>} onClick={onEstimate} aria-label={`Open cost estimate for ${afe.afe_code}`}>Estimate</Button>
    {canEdit && draft && <Button size="small" startIcon={<EditOutlined sx={{ fontSize: 15 }}/>} onClick={onEdit} aria-label={`Edit AFE ${afe.afe_code}`}>Edit</Button>}
    {canDelete && <Tooltip title={draft ? 'Move to Deleted Entries' : 'Only draft AFEs can be deleted. Reopen the AFE as Draft first.'}>
      <span>
        <Button size="small" color="error" disabled={!draft} onClick={onDelete} aria-label={`Delete AFE ${afe.afe_code}`} startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>}>Delete</Button>
      </span>
    </Tooltip>}
  </Box>
}

export function AfeRegisterTab({ reference, onReferenceChanged }: {
  reference: AfeReference | null
  onReferenceChanged: () => void
}) {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [rows, setRows] = useState<Afe[]>([])
  const [selected, setSelected] = useState<Afe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formRecord, setFormRecord] = useState<Afe | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [deleteTargets, setDeleteTargets] = useState<Afe[] | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<Afe[]>('/afe/afes'))
      setSelected([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AFE register could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const canCreate = can('afe:create')
  const canUpdate = can('afe:update')
  const canDelete = can('afe:delete')
  const draftCount = rows.filter(row => row.status === 'draft').length
  const selectedBlocked = selected.filter(row => row.status !== 'draft')

  const openCreate = () => { setFormRecord(null); setFormOpen(true) }
  const openEdit = (afe: Afe) => { setFormRecord(afe); setFormOpen(true) }

  const onSaved = async (saved: Afe, created: boolean) => {
    setFormOpen(false)
    setFormRecord(null)
    setNotice(created ? `${saved.afe_code} was created for ${saved.well_code}. Open its estimate to price it.` : `${saved.afe_code} was updated.`)
    await load()
  }

  const confirmDelete = async () => {
    if (!deleteTargets?.length) return
    setDeleting(true)
    setDeleteError(null)
    try {
      if (deleteTargets.length === 1) {
        await api(`/afe/afes/${deleteTargets[0].id}`, { method: 'DELETE' })
      } else {
        await api('/afe/afes/bulk-delete', { method: 'POST', body: body({ ids: deleteTargets.map(row => row.id) }) })
      }
      setNotice(`${deleteTargets.length} ${deleteTargets.length === 1 ? 'AFE was' : 'AFEs were'} moved to Deleted Entries.`)
      setDeleteTargets(null)
      await load()
    } catch (caught) {
      setDeleteError(caught)
    } finally {
      setDeleting(false)
    }
  }

  const importRows = async (importedRows: ImportRow[]): Promise<string[]> => {
    const result = await api<ImportResponse>('/afe/afes/import', { method: 'POST', body: body({ rows: importedRows }) })
    await load()
    onReferenceChanged()
    if (result.imported_count) setNotice(`Imported or updated ${result.imported_count} AFE${result.imported_count === 1 ? '' : 's'}.`)
    if (!result.error_count) return []
    return [
      `Imported or updated ${result.imported_count} of ${importedRows.length} rows. Resolve the issues below and re-import the failed rows.`,
      ...result.errors,
    ]
  }

  const onExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/afe/export-audit', { method: 'POST', body: body({ module: 'afes', format, record_count: recordCount, include_deleted: false }) })
  }

  const columns = useMemo<ColDef<Afe>[]>(() => [
    { headerName: 'AFE CODE', field: 'afe_code', minWidth: 130, flex: .8 },
    { headerName: 'AFE NAME', field: 'afe_name', minWidth: 200, flex: 1.3 },
    { headerName: 'TYPE', field: 'afe_type', minWidth: 115, maxWidth: 130 },
    { headerName: 'RIG', field: 'rig_name', minWidth: 150, flex: 1, valueFormatter: params => params.data ? `${params.data.rig_code} · ${params.data.rig_name}` : '' },
    { headerName: 'WELL', field: 'well_name', minWidth: 180, flex: 1.1, valueFormatter: params => params.data ? `${params.data.well_code} · ${params.data.well_name}` : '' },
    { headerName: 'STATUS', field: 'status', minWidth: 125, maxWidth: 140, cellRenderer: ({ data }: { data: Afe }) => data && <Box display="flex" alignItems="center" height="100%"><StatusTag status={data.status}/></Box> },
    { headerName: 'ITEMS', field: 'service_count', minWidth: 120, maxWidth: 150, valueFormatter: params => params.data ? `${params.data.service_count} svc · ${params.data.consumable_count} cons · ${params.data.tangible_count} tang` : '' },
    { headerName: 'ESTIMATE TOTAL', field: 'total_cost', minWidth: 170, flex: .9, valueFormatter: params => params.data ? (params.data.totals_by_currency.length ? totalsText(params.data.totals_by_currency) : amountText(params.value)) : '' },
    { headerName: 'WARNINGS', field: 'warning_count', minWidth: 115, maxWidth: 130, cellRenderer: ({ value }: { value: number }) => <Box display="flex" alignItems="center" height="100%">{value > 0 ? <Tag tone="warning">{value} to review</Tag> : <Tag>None</Tag>}</Box> },
    { headerName: 'ESTIMATE SAVED', field: 'estimate_saved_at', minWidth: 150, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : 'Not saved' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 135, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 300, minWidth: 300, maxWidth: 300, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Afe }) => data && <RowActions
        afe={data}
        canEdit={canUpdate}
        canDelete={canDelete}
        onEstimate={() => navigate(`/afe/estimate/${data.id}`)}
        onEdit={() => openEdit(data)}
        onDelete={() => { setDeleteError(null); setDeleteTargets([data]) }}
      />,
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [canUpdate, canDelete, navigate])

  return <>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    {!reference?.rigs.length && reference && <Alert severity="warning" sx={{ mb: 1.5 }}>Create an active rig and well with a saved plan in Rig & Well Management before creating AFEs.</Alert>}
    <ErrorMessage message={error}/>

    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.8, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box>
          <Typography fontWeight={800} fontSize={15}>AFE register</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35}>
            {rows.length} active AFE{rows.length === 1 ? '' : 's'} · {rows.filter(row => row.afe_type === 'Drilling').length} drilling · {rows.filter(row => row.afe_type === 'Completion').length} completion · {draftCount} draft. Status is changed from AFE cost estimation.
          </Typography>
        </Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          {canDelete && <Button color="error" variant="outlined" size="small" startIcon={<DeleteOutlineRounded/>} disabled={!selected.length || selectedBlocked.length > 0} onClick={() => { setDeleteError(null); setDeleteTargets(selected) }}>
            Move {selected.length || ''} to Deleted Entries
          </Button>}
          {canCreate && <Button variant="contained" startIcon={<AddRounded/>} onClick={openCreate} disabled={!reference?.rigs.length}>Create AFE</Button>}
        </Box>
      </Box>
      {selectedBlocked.length > 0 && <Alert severity="warning" sx={{ mt: 1.5 }}>
        {selectedBlocked.length} selected AFE{selectedBlocked.length === 1 ? ' is' : 's are'} not draft. Only draft AFEs can be moved to Deleted Entries. Deselect them to continue.
      </Alert>}
    </Paper>

    {loading
      ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <DataTable
        rows={rows}
        columns={columns}
        searchPlaceholder="Search AFEs by code, name, rig, well, type or status..."
        exportName="afe-register"
        onImport={can('afe:import') ? () => setImportOpen(true) : undefined}
        canExport={can('afe:export')}
        onExport={onExport}
        selectable={canDelete}
        onSelectionChange={setSelected}
      />}

    <AfeFormDialog
      open={formOpen}
      record={formRecord}
      reference={reference}
      onClose={() => { setFormOpen(false); setFormRecord(null) }}
      onSaved={(saved, created) => void onSaved(saved, created)}
    />

    <ImportDialog
      open={importOpen}
      onClose={() => setImportOpen(false)}
      title="Import AFEs"
      subtitle="Each row names an active rig and well by code. Existing AFE codes are updated only while they are draft."
      headers={AFE_IMPORT_HEADERS}
      optionalHeaders={AFE_IMPORT_OPTIONAL_HEADERS}
      sample={{ rig_code: 'RIG-01', well_code: 'WELL-01', afe_code: 'AFE-DR-001', afe_name: 'Surface and intermediate hole', afe_type: 'Drilling', remarks: '' }}
      templateName="afe-register-template"
      onRows={importRows}
    />

    <FormDialog
      open={Boolean(deleteTargets)}
      title={deleteTargets && deleteTargets.length === 1 ? `Move ${deleteTargets[0].afe_code} to Deleted Entries?` : `Move ${deleteTargets?.length ?? 0} AFEs to Deleted Entries?`}
      subtitle="Deleted AFEs leave the register and their estimates stop counting in totals. You can restore them from Deleted Entries."
      onClose={() => { if (!deleting) setDeleteTargets(null) }}
      onSubmit={() => void confirmDelete()}
      busy={deleting}
      submitLabel="Move to Deleted Entries"
    >
      <Typography fontSize={13}>The change is recorded in the audit trail.</Typography>
      {deleteError ? <Box mt={1.5}><ErrorDetails error={deleteError}/></Box> : null}
    </FormDialog>
  </>
}
