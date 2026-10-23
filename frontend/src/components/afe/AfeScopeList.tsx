import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowForwardRounded, DeleteOutlineRounded } from '@mui/icons-material'
import { Alert, Box, Button, Menu, MenuItem, Paper, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../DataTable'
import { FormDialog, Tag } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import { afeTotalText, type Afe } from '../../lib/afe'
import { ErrorDetails, StatusTag } from './AfeShared'

function RowActions({ afe, canDelete, onEstimate, onDelete }: {
  afe: Afe
  canDelete: boolean
  onEstimate: () => void
  onDelete: () => void
}) {
  const draft = afe.status === 'draft'
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const close = () => setAnchor(null)
  return <Box display="flex" alignItems="center" height="100%" gap={.2}>
    <Button size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>} onClick={onEstimate} aria-label={`Open cost estimate for ${afe.afe_code}`}>Estimate</Button>
    {canDelete && <>
      <Button size="small" color="inherit" endIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>} onClick={event => setAnchor(event.currentTarget)} disabled={!draft} aria-label={`Delete AFE ${afe.afe_code}`}>
        Delete
      </Button>
      <Tooltip title={draft ? 'Move to Deleted Entries' : 'Only draft AFEs can be deleted. Reopen the AFE as Draft first.'}>
        <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}>
          <MenuItem key="delete" disabled={!draft} onClick={() => { close(); onDelete() }}>Move to Deleted Entries</MenuItem>
        </Menu>
      </Tooltip>
    </>}
  </Box>
}

export function AfeScopeList({ afees, exportName }: { afees: Afe[]; exportName: string }) {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [deleteTargets, setDeleteTargets] = useState<Afe[] | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)
  const [deleting, setDeleting] = useState(false)
  const [notice, setNotice] = useState('')

  const canDelete = can('afe:delete')

  const confirmDelete = useCallback(async () => {
    if (!deleteTargets?.length) return
    setDeleting(true)
    setDeleteError(null)
    try {
      if (deleteTargets.length === 1) {
        await api(`/afe/afes/${deleteTargets[0].id}`, { method: 'DELETE' })
      } else {
        await api('/afe/afes/bulk-delete', { method: 'POST', body: body({ ids: deleteTargets.map(row => row.id) }) })
      }
      setNotice(`${deleteTargets.length} AFE${deleteTargets.length === 1 ? '' : 's'} moved to Deleted Entries.`)
      setDeleteTargets(null)
    } catch (caught) {
      setDeleteError(caught)
    } finally {
      setDeleting(false)
    }
  }, [deleteTargets])

  const onExport = useCallback(async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/afe/export-audit', {
      method: 'POST',
      body: body({ module: 'afes', format, record_count: recordCount, include_deleted: false }),
    })
  }, [])

  const columns = useMemo<ColDef<Afe>[]>(() => [
    { headerName: 'AFE CODE', field: 'afe_code', minWidth: 130, flex: .8 },
    { headerName: 'AFE NAME', field: 'afe_name', minWidth: 200, flex: 1.3 },
    { headerName: 'CONFIGURATION SCOPE', field: 'configuration_scope', minWidth: 155 },
    { headerName: 'TYPE', field: 'afe_type', minWidth: 115, maxWidth: 130 },
    { headerName: 'RIG · WELL', field: 'well_name', minWidth: 210, flex: 1.2, valueFormatter: params => params.data ? `${params.data.rig_code} · ${params.data.well_code}` : '' },
    { headerName: 'STATUS', field: 'status', minWidth: 125, maxWidth: 140, cellRenderer: ({ data }: { data: Afe }) => data && <Box display="flex" alignItems="center" height="100%"><StatusTag status={data.status}/></Box> },
    { headerName: 'ESTIMATE TOTAL', field: 'total_cost', minWidth: 170, flex: .9, valueFormatter: params => params.data ? afeTotalText(params.data) : '' },
    { headerName: 'WARNINGS', field: 'warning_count', minWidth: 115, maxWidth: 130, cellRenderer: ({ value }: { value: number }) => <Box display="flex" alignItems="center" height="100%">{value > 0 ? <Tag tone="warning">{value} to review</Tag> : <Tag>None</Tag>}</Box> },
    { headerName: 'ESTIMATE SAVED', field: 'estimate_saved_at', minWidth: 150, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : 'Not saved' },
    { headerName: 'UPDATED', field: 'updated_at', minWidth: 135, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 260, minWidth: 260, maxWidth: 260, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Afe }) => data && <RowActions
        afe={data}
        canDelete={canDelete}
        onEstimate={() => navigate(`/afe/estimate/${data.id}`)}
        onDelete={() => { setDeleteError(null); setDeleteTargets([data]) }}
      />,
    },
  ], [canDelete, navigate])

  return <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.8, borderRadius: 2 }}>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <DataTable
      fillHeight
      rows={afees}
      columns={columns}
      searchPlaceholder="Search AFEs by code, name, rig, well, type or status..."
      exportName={exportName}
      canExport={can('afe:export')}
      onExport={onExport}
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
      {deleteError ? <Box mt={1.5}><ErrorDetails error={deleteError} /></Box> : null}
    </FormDialog>
  </Paper>
}
