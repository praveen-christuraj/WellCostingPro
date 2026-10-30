import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Box, Button, CircularProgress, Paper, Stack, Typography } from '@mui/material'
import {
  AddRounded, ArrowForwardRounded, ContentCopyRounded, DeleteOutlineRounded, EditOutlined,
  PlayArrowRounded, PublishOutlined, RefreshRounded, UnpublishedOutlined, VisibilityOutlined,
} from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body } from '../lib/api'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import {
  reportTypeLabel, visibilityLabel, type ReportDefinition, type ReportDefinitionList, type ReportVersion, type Starter,
} from '../lib/reportBuilder'

function when(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(undefined, { month: 'short', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function ReportBuilder() {
  const navigate = useNavigate()
  const { can } = useAuth()
  const canCreate = can('report-builder:create')
  const canPublish = can('report-builder:publish')

  const [definitions, setDefinitions] = useState<ReportDefinitionList | null>(null)
  const [starters, setStarters] = useState<Starter[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [scope, setScope] = useState<'all' | 'mine' | 'shared'>('all')
  const [versions, setVersions] = useState<{ report: ReportDefinition; items: ReportVersion[] } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ReportDefinition | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [creating, setCreating] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const [list, starterList] = await Promise.all([
        api<ReportDefinitionList>(`/report-builder/definitions?scope=${scope}`),
        api<{ items: Starter[] }>('/report-builder/starters'),
      ])
      setDefinitions(list)
      setStarters(starterList.items)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Reports could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [scope])

  useEffect(() => { void load() }, [load])

  const useStarter = async (starter: Starter) => {
    setCreating(starter.key)
    setError('')
    try {
      const record = await api<ReportDefinition>('/report-builder/definitions/from-starter', {
        method: 'POST', body: body({ key: starter.key }),
      })
      navigate(`/reports/builder/${record.id}`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The starter report could not be copied')
    } finally {
      setCreating('')
    }
  }

  const togglePublish = async (record: ReportDefinition) => {
    setError('')
    try {
      const updated = await api<ReportDefinition>(`/report-builder/definitions/${record.id}/publish`, {
        method: 'POST', body: body({ published: record.status !== 'published' }),
      })
      setNotice(`${updated.name} is now ${updated.status}.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The report could not be published')
    }
  }

  const duplicate = async (record: ReportDefinition) => {
    try {
      const copy = await api<ReportDefinition>(`/report-builder/definitions/${record.id}/duplicate`, { method: 'POST' })
      setNotice(`Copied into “${copy.name}”.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The report could not be copied')
    }
  }

  const remove = async () => {
    if (!deleteTarget) return
    setDeleteBusy(true)
    try {
      await api<void>(`/report-builder/definitions/${deleteTarget.id}`, { method: 'DELETE', action: `Deleting “${deleteTarget.name}”` })
      setNotice(`“${deleteTarget.name}” was deleted.`)
      setDeleteTarget(null)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The report could not be deleted')
    } finally {
      setDeleteBusy(false)
    }
  }

  const showVersions = async (record: ReportDefinition) => {
    try {
      setVersions({ report: record, items: await api<ReportVersion[]>(`/report-builder/definitions/${record.id}/versions`) })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The version history could not be loaded')
    }
  }

  const columns = useMemo<ColDef<ReportDefinition>[]>(() => [
    {
      headerName: 'REPORT', field: 'name', minWidth: 250,
      cellRenderer: ({ data }: { data?: ReportDefinition }) => data ? <Box display="flex" flexDirection="column" justifyContent="center" height="100%">
        <Typography fontWeight={700} fontSize={12.8}>{data.name}</Typography>
        <Typography color="text.secondary" fontSize={11}>{data.description || `${data.design.columns.length} columns`} · v{data.version}</Typography>
      </Box> : null,
    },
    { headerName: 'SOURCE', field: 'source_table', minWidth: 165 },
    { headerName: 'LAYOUT', field: 'report_type', width: 165, flex: 0, valueFormatter: ({ value }) => reportTypeLabel(String(value)) },
    {
      headerName: 'STATUS', field: 'status', width: 130, flex: 0,
      cellRenderer: ({ data }: { data?: ReportDefinition }) => data ? <Box display="flex" alignItems="center" height="100%">
        <Tag tone={data.status === 'published' ? 'success' : 'neutral'}>{data.status === 'published' ? 'Published' : 'Draft'}</Tag>
      </Box> : null,
    },
    {
      headerName: 'SHARED WITH', field: 'visibility', width: 175, flex: 0,
      valueFormatter: ({ data }) => data ? (data.grants.length ? `${data.grants.length} grant${data.grants.length === 1 ? '' : 's'}` : visibilityLabel(data.visibility)) : '',
    },
    { headerName: 'RUNS', field: 'run_count', width: 90, flex: 0, type: 'rightAligned' },
    { headerName: 'LAST RUN', field: 'last_run_at', width: 165, flex: 0, valueFormatter: ({ value }) => when(value as string | null) },
    { headerName: 'OWNER', field: 'created_by_display', minWidth: 135 },
    {
      headerName: 'ACTIONS', width: 430, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data?: ReportDefinition }) => {
        if (!data) return null
        return <Box display="flex" alignItems="center" height="100%" gap={.3} flexWrap="wrap">
          {data.can_run && <Button size="small" startIcon={<PlayArrowRounded sx={{ fontSize: 15 }}/>}
            onClick={() => navigate(data.status === 'published' ? `/reports/custom/${data.id}` : `/reports/builder/${data.id}?preview=1`)}>Run</Button>}
          {data.can_edit && <Button size="small" startIcon={<EditOutlined sx={{ fontSize: 15 }}/>} onClick={() => navigate(`/reports/builder/${data.id}`)}>Design</Button>}
          <Button size="small" startIcon={<VisibilityOutlined sx={{ fontSize: 15 }}/>} onClick={() => void showVersions(data)}>Versions</Button>
          {canCreate && <Button size="small" startIcon={<ContentCopyRounded sx={{ fontSize: 15 }}/>} onClick={() => void duplicate(data)}>Copy</Button>}
          {canPublish && data.can_publish && <Button size="small"
            startIcon={data.status === 'published' ? <UnpublishedOutlined sx={{ fontSize: 15 }}/> : <PublishOutlined sx={{ fontSize: 15 }}/>}
            onClick={() => void togglePublish(data)}>{data.status === 'published' ? 'Unpublish' : 'Publish'}</Button>}
          {data.can_delete && <Button size="small" color="error" onClick={() => setDeleteTarget(data)}><DeleteOutlineRounded sx={{ fontSize: 16 }}/></Button>}
        </Box>
      },
    },
  ], [canCreate, canPublish, load]) // eslint-disable-line react-hooks/exhaustive-deps

  const counts = definitions?.counts ?? {}

  return <>
    <PageHeading
      eyebrow="REPORTS / REPORT BUILDER"
      title="Report Builder"
      subtitle="Design a report once — source, columns, layout, questions and sharing — then publish it into Custom Reports for everybody you name."
      action={<>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={busy}>Refresh</Button>
        {canCreate && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => navigate('/reports/builder/new')}>New report</Button>}
      </>}
    />
    <ErrorMessage message={error}/>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}

    <Paper variant="outlined" sx={{ p: 1.5, mb: 2, borderRadius: 2, display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
      <Typography color="text.secondary" fontSize={12}>Show</Typography>
      <Box display="flex" gap={.5} flexWrap="wrap">
        {([['all', `All (${counts.all ?? 0})`], ['mine', `Mine (${counts.mine ?? 0})`], ['shared', `Shared with me (${counts.shared ?? 0})`]] as const).map(([value, label]) =>
          <Button key={value} size="small" variant={scope === value ? 'contained' : 'outlined'} onClick={() => setScope(value)}>{label}</Button>)}
      </Box>
      <Box flex={1}/>
      <Typography color="text.secondary" fontSize={12}>{counts.published ?? 0} published · {counts.draft ?? 0} draft</Typography>
    </Paper>

    {busy && !definitions ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <DataTable<ReportDefinition>
        rows={definitions?.items ?? []}
        columns={columns}
        rowKey="id"
        searchPlaceholder="Filter the visible reports..."
        exportName="report-definitions"
      />}

    <Box mt={4} mb={1.5}>
      <Typography variant="h6">Start from a proven design</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mt: .4 }}>
        These are complete designs over this workspace's own tables. Copy one and adjust it — nothing is shared until you publish it.
      </Typography>
    </Box>
    <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' } }}>
      {starters.map(starter => <Paper key={starter.key} variant="outlined" sx={{ p: 2, borderRadius: 2, display: 'flex', flexDirection: 'column' }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={.8}>
          <Typography fontWeight={800} fontSize={13.5}>{starter.name}</Typography>
          <Tag tone="info">{reportTypeLabel(starter.report_type)}</Tag>
        </Box>
        <Typography color="text.secondary" fontSize={12} sx={{ flex: 1 }}>{starter.description}</Typography>
        <Typography color="text.secondary" fontSize={11.2} sx={{ mt: 1 }}>{starter.source_label} · {starter.column_count} columns</Typography>
        <Button size="small" variant="outlined" endIcon={<ArrowForwardRounded sx={{ fontSize: 16 }}/>} sx={{ mt: 1.5, alignSelf: 'flex-start' }}
          disabled={!canCreate || !starter.available || creating === starter.key} onClick={() => void useStarter(starter)}>
          {creating === starter.key ? 'Copying...' : starter.available ? 'Use this starter' : 'Table not in this workspace'}
        </Button>
      </Paper>)}
    </Box>

    <FormDialog open={Boolean(deleteTarget)} title="Delete this report?" maxWidth="sm" danger
      subtitle={deleteTarget ? `“${deleteTarget.name}” and its ${deleteTarget.status === 'published' ? 'published listing' : 'design'} are removed for everybody it was shared with. The audit trail keeps the record.` : ''}
      onClose={() => setDeleteTarget(null)} onSubmit={() => void remove()} busy={deleteBusy} submitLabel="Delete report">
      <Typography fontSize={13} color="text.secondary">This cannot be undone from the screen. If you only want to stop people running it, unpublish it instead.</Typography>
    </FormDialog>

    <PanelDialog open={Boolean(versions)} title="Version history"
      subtitle={versions ? `${versions.report.name} · currently version ${versions.report.version}` : ''}
      onClose={() => setVersions(null)}>
      {versions && (versions.items.length === 0
        ? <Typography color="text.secondary" fontSize={12.5}>No versions recorded yet.</Typography>
        : <Stack spacing={1.2}>
          {versions.items.map(item => <Paper key={item.id} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap">
              <Typography fontWeight={800} fontSize={13}>Version {item.version} · {item.report_name}</Typography>
              <Tag tone={item.status === 'published' ? 'success' : 'neutral'}>{item.status}</Tag>
            </Box>
            <Typography color="text.secondary" fontSize={11.5} sx={{ mt: .4 }}>
              {when(item.created_at)} · {item.changed_by_display} · {item.column_count} columns · {item.filter_count} filters ·
              {' '}{item.grouping_count} groupings · {item.grant_count} grants
            </Typography>
            {item.change_note && <Typography fontSize={12} sx={{ mt: .5 }}>{item.change_note}</Typography>}
          </Paper>)}
        </Stack>)}
    </PanelDialog>
  </>
}
