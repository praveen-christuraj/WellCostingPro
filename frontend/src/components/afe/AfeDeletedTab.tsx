import { useCallback, useEffect, useMemo, useState } from 'react'
import { DeleteForeverOutlined, RestoreRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../DataTable'
import { ErrorMessage, FormDialog } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import { afeTotalText, type Afe } from '../../lib/afe'
import { ErrorDetails, StatusTag } from './AfeShared'

type PendingAction = { kind: 'restore' | 'purge'; targets: Afe[] }

export function AfeDeletedTab() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Afe[]>([])
  const [selected, setSelected] = useState<Afe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<Afe[]>('/afe/afes/deleted'))
      setSelected([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Deleted AFEs could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const confirm = async () => {
    if (!pending) return
    setBusy(true)
    setActionError(null)
    const ids = pending.targets.map(row => row.id)
    try {
      if (pending.kind === 'restore') {
        if (ids.length === 1) await api(`/afe/afes/${ids[0]}/restore`, { method: 'POST' })
        else await api('/afe/afes/bulk-restore', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} ${ids.length === 1 ? 'AFE was' : 'AFEs were'} restored to the register.`)
      } else {
        if (ids.length === 1) await api(`/afe/afes/${ids[0]}/permanent`, { method: 'DELETE' })
        else await api('/afe/afes/bulk-permanent-delete', { method: 'POST', body: body({ ids }) })
        setNotice(`${ids.length} ${ids.length === 1 ? 'AFE was' : 'AFEs were'} permanently deleted with their estimates.`)
      }
      setPending(null)
      await load()
    } catch (caught) {
      setActionError(caught)
    } finally {
      setBusy(false)
    }
  }

  const columns = useMemo<ColDef<Afe>[]>(() => [
    { headerName: 'AFE CODE', field: 'afe_code', minWidth: 125, flex: .75 },
    { headerName: 'AFE NAME', field: 'afe_name', minWidth: 190, flex: 1.2 },
    { headerName: 'TYPE', field: 'afe_type', minWidth: 110, maxWidth: 125 },
    { headerName: 'RIG · WELL', field: 'well_name', minWidth: 210, flex: 1.2, valueFormatter: params => params.data ? `${params.data.rig_code} · ${params.data.well_code}` : '' },
    { headerName: 'STATUS AT DELETION', field: 'status', minWidth: 150, cellRenderer: ({ data }: { data: Afe }) => data && <Box display="flex" alignItems="center" height="100%"><StatusTag status={data.status}/></Box> },
    { headerName: 'ESTIMATE', field: 'total_cost', minWidth: 170, valueFormatter: params => params.data ? afeTotalText(params.data) : '' },
    { headerName: 'DELETED AT', field: 'deleted_at', minWidth: 160, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : '' },
    {
      headerName: 'ACTIONS', width: 230, minWidth: 230, maxWidth: 230, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Afe }) => data && <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('afe:restore') && <Button size="small" startIcon={<RestoreRounded sx={{ fontSize: 15 }}/>} onClick={() => { setActionError(null); setPending({ kind: 'restore', targets: [data] }) }} aria-label={`Restore AFE ${data.afe_code}`}>Restore</Button>}
        {can('afe:permanent-delete') && <Button size="small" color="error" startIcon={<DeleteForeverOutlined sx={{ fontSize: 15 }}/>} onClick={() => { setActionError(null); setPending({ kind: 'purge', targets: [data] }) }} aria-label={`Delete AFE ${data.afe_code} permanently`}>Delete forever</Button>}
      </Box>,
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [can])

  const canRestore = can('afe:restore')
  const canPurge = can('afe:permanent-delete')
  const count = selected.length
  const pendingCount = pending?.targets.length ?? 0

  return <>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.8, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box>
          <Typography fontWeight={800} fontSize={15}>Deleted entries</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35}>
            {rows.length} deleted AFE{rows.length === 1 ? '' : 's'}. Restore returns them to the register; permanent delete removes the AFE, its estimate and the locked baseline snapshots that belong to it.
          </Typography>
        </Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          {canRestore && <Button variant="outlined" startIcon={<RestoreRounded/>} disabled={!count} onClick={() => setPending({ kind: 'restore', targets: selected })}>Restore {count || ''}</Button>}
          {canPurge && <Button color="error" variant="outlined" startIcon={<DeleteForeverOutlined/>} disabled={!count} onClick={() => setPending({ kind: 'purge', targets: selected })}>Delete {count || ''} forever</Button>}
        </Box>
      </Box>
    </Paper>

    {loading
      ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <DataTable
        fillHeight
        rows={rows}
        columns={columns}
        searchPlaceholder="Search deleted AFEs by code, name, rig or well..."
        exportName="afe-deleted"
        canExport={can('afe:export')}
        onExport={async (format, recordCount) => {
          await api('/afe/export-audit', { method: 'POST', body: body({ module: 'deleted', format, record_count: recordCount, include_deleted: true }) })
        }}
        selectable={canRestore || canPurge}
        onSelectionChange={setSelected}
      />}

    <FormDialog
      open={Boolean(pending)}
      title={pending?.kind === 'purge'
        ? `Permanently delete ${pendingCount === 1 ? pending.targets[0].afe_code : `${pendingCount} AFEs`}?`
        : `Restore ${pendingCount === 1 ? pending?.targets[0].afe_code : `${pendingCount} AFEs`}?`}
      subtitle={pending?.kind === 'purge'
        ? 'Permanent delete removes the AFE, its estimate lines, its locked daily-cost baseline and its SOW revisions. Any daily-cost sheet that still references the AFE must be permanently deleted from Daily Cost Management first. This cannot be undone.'
        : 'Restored AFEs return to the register as they were. A restore is refused while the rig or well is inactive or deleted.'}
      onClose={() => { if (!busy) setPending(null) }}
      onSubmit={() => void confirm()}
      busy={busy}
      submitLabel={pending?.kind === 'purge' ? 'Delete permanently' : 'Restore'}
      danger={pending?.kind === 'purge'}
    >
      {pending?.kind === 'purge' && <Alert severity="warning" sx={{ mb: 1.5 }}>Only permanently delete AFEs you no longer need for audit. The action is refused, with the blocking records named, while an active or deleted daily-cost sheet or another module still references this AFE.</Alert>}
      {actionError ? <ErrorDetails error={actionError}/> : null}
    </FormDialog>
  </>
}
