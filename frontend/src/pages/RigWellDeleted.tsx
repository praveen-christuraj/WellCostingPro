import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { DeleteForeverOutlined, DeleteOutlineRounded, RestoreRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { entityLabel, type DeletedRigWellRecord } from '../lib/rigWell'

export default function RigWellDeleted() {
  const { can } = useAuth()
  const [rows, setRows] = useState<DeletedRigWellRecord[]>([])
  const [selectedRows, setSelectedRows] = useState<DeletedRigWellRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [purgeOpen, setPurgeOpen] = useState(false)
  const [purgeRecord, setPurgeRecord] = useState<DeletedRigWellRecord | null>(null)
  const [purgeError, setPurgeError] = useState('')
  const [purging, setPurging] = useState(false)
  const [restoring, setRestoring] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<DeletedRigWellRecord[]>('/rig-well/deleted'))
      setSelectedRows([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Deleted Rig & Well records could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { void load() }, [load])

  const restoreRows = async (targets: DeletedRigWellRecord[]) => {
    setRestoring(true)
    setError('')
    try {
      if (targets.length === 1) {
        const target = targets[0]
        await api(`/rig-well/${target.entity_type === 'well_sub_activity' ? 'sub-activities' : `${target.entity_type}s`}/${target.id}/restore`, { method: 'POST' })
      } else {
        await api('/rig-well/deleted/bulk-restore', {
          method: 'POST', body: body({ records: targets.map(target => ({ entity_type: target.entity_type, id: target.id })) }),
        })
      }
      setNotice(`${targets.length} ${targets.length === 1 ? 'record was' : 'records were'} restored.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Selected records could not be restored')
    } finally {
      setRestoring(false)
    }
  }

  const openPurge = (record?: DeletedRigWellRecord) => {
    setPurgeRecord(record ?? null)
    setPurgeError('')
    setPurgeOpen(true)
  }

  const confirmPurge = async () => {
    setPurging(true)
    setPurgeError('')
    const targets = purgeRecord ? [purgeRecord] : selectedRows
    try {
      if (purgeRecord) {
        const collection = purgeRecord.entity_type === 'well_sub_activity' ? 'sub-activities' : `${purgeRecord.entity_type}s`
        await api(`/rig-well/${collection}/${purgeRecord.id}/permanent`, { method: 'DELETE' })
      } else {
        await api('/rig-well/deleted/bulk-permanent-delete', {
          method: 'POST', body: body({ records: targets.map(target => ({ entity_type: target.entity_type, id: target.id })) }),
        })
      }
      setPurgeOpen(false)
      setPurgeRecord(null)
      setNotice(`${targets.length} ${targets.length === 1 ? 'record was' : 'records were'} permanently deleted.`)
      await load()
    } catch (caught) {
      setPurgeError(caught instanceof Error ? caught.message : 'Selected records could not be permanently deleted')
    } finally {
      setPurging(false)
    }
  }

  const onExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/rig-well/export-audit', {
      method: 'POST', body: body({ module: 'deleted', format, record_count: recordCount, include_deleted: true }),
    })
  }

  const columns = useMemo<ColDef<DeletedRigWellRecord>[]>(() => [
    { headerName: 'TYPE', field: 'entity_type', minWidth: 145, maxWidth: 175, cellRenderer: ({ value }: { value: DeletedRigWellRecord['entity_type'] }) => <Box display="flex" alignItems="center" height="100%"><Tag tone="warning">{entityLabel(value)}</Tag></Box> },
    { headerName: 'CODE', field: 'code', minWidth: 130, flex: .8 },
    { headerName: 'NAME', field: 'name', minWidth: 190, flex: 1.2 },
    { headerName: 'PARENT / SCOPE', field: 'parent_label', minWidth: 190, flex: 1.2 },
    { headerName: 'DELETED', field: 'deleted_at', minWidth: 165, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : '' },
    { headerName: 'CREATED', field: 'created_at', minWidth: 145, valueFormatter: params => params.value ? new Date(params.value).toLocaleDateString() : '' },
    {
      headerName: 'ACTIONS', width: 240, minWidth: 240, maxWidth: 240, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: DeletedRigWellRecord }) => data && <Box display="flex" alignItems="center" height="100%" gap={.5}>
        {can('rig-well:restore') && <Button size="small" disabled={restoring} onClick={() => void restoreRows([data])} aria-label={`Restore ${data.code}`} startIcon={<RestoreRounded sx={{ fontSize: 16 }}/>}>Restore</Button>}
        {can('rig-well:permanent-delete') && <Button size="small" color="error" onClick={() => openPurge(data)} aria-label={`Permanently delete ${data.code}`} startIcon={<DeleteForeverOutlined sx={{ fontSize: 16 }}/>}>Permanently delete</Button>}
      </Box>,
    },
  ], [can, restoring])

  return <>
    <PageHeading
      eyebrow="RIG & WELL MANAGEMENT / RETENTION"
      title="Deleted entries"
      subtitle="Restore removed records or permanently purge them after reviewing their parent-child dependencies."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/rig-well" variant="outlined">Module overview</Button>
        {can('rig-well:restore') && <Button variant="outlined" startIcon={<RestoreRounded/>} disabled={!selectedRows.length || restoring} onClick={() => void restoreRows(selectedRows)}>Restore {selectedRows.length || ''} selected</Button>}
        {can('rig-well:permanent-delete') && <Button color="error" variant="contained" startIcon={<DeleteOutlineRounded/>} disabled={!selectedRows.length} onClick={() => openPurge()}>Permanently delete {selectedRows.length || ''} selected</Button>}
      </Box>}
    />

    <Alert severity="warning" sx={{ mb: 1.8 }} action={can('master-data:read') ? <Button component={RouterLink} to="/master-data/deleted" size="small">Master Data deleted entries</Button> : undefined}>
      Permanent deletion is irreversible. Restore parent records first; before purging a rig or well, permanently delete its child wells or sub activities. Configuration sections and phases are removed with their well. Restore an Activity from Master Data before restoring sub activities assigned to it.
    </Alert>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.5, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap">
        <Box><Typography fontWeight={800} fontSize={15}>Deleted Rig & Well records</Typography><Typography color="text.secondary" fontSize={12} mt={.35}>{rows.length} retained {rows.length === 1 ? 'record' : 'records'} across rigs, wells and well sub activities.</Typography></Box>
      </Box>
    </Paper>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      rows={rows}
      columns={columns}
      searchPlaceholder="Search deleted codes, names, parent scope..."
      exportName="rig-well-deleted-entries"
      canExport={can('rig-well:export')}
      onExport={onExport}
      selectable={can('rig-well:restore') || can('rig-well:permanent-delete')}
      onSelectionChange={setSelectedRows}
    />}

    <FormDialog
      open={purgeOpen}
      title="Permanently delete these records?"
      subtitle="This action cannot be undone. The API checks that required child entries are included or already removed."
      onClose={() => { if (!purging) { setPurgeOpen(false); setPurgeRecord(null) } }}
      onSubmit={() => void confirmPurge()}
      busy={purging}
      submitLabel="Permanently delete"
    >
      <Box display="grid" gap={1.5} pt={.5}>
        {purgeRecord
          ? <Typography fontSize={13}>Permanently delete <b>{entityLabel(purgeRecord.entity_type)} · {purgeRecord.code} — {purgeRecord.name}</b>? This cannot be reversed.</Typography>
          : <Typography fontSize={13}>Permanently delete {selectedRows.length} selected records? Child records must be selected alongside a deleted parent or permanently removed first.</Typography>}
        <ErrorMessage message={purgeError}/>
      </Box>
    </FormDialog>
  </>
}
