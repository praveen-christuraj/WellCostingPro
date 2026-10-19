import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowDropDownRounded, ArrowForwardRounded, CalculateOutlined } from '@mui/icons-material'
import { Alert, Box, Button, Chip, CircularProgress, Menu, MenuItem, Paper, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../DataTable'
import { ErrorMessage } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import {
  STATUS_ACTIONS, STATUS_LABEL, afeTotalText, amountText, nextActions, toNumber,
  type Afe, type AfeStatusAction,
} from '../../lib/afe'
import { StatusDialog, StatusTag } from './AfeShared'

// Status moves and estimate access. The AFE register shows status only; it never changes it.
function EstimateActions({ afe, can, onOpen, onStatus }: {
  afe: Afe
  can: (permission: string) => boolean
  onOpen: () => void
  onStatus: (action: AfeStatusAction) => void
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const actions = nextActions(afe.status).filter(action => can(STATUS_ACTIONS[action].permission))
  const estimateReady = Boolean(afe.estimate_saved_at) && toNumber(afe.total_cost) > 0
  const close = () => setAnchor(null)

  return <Box display="flex" alignItems="center" height="100%" gap={.2}>
    <Button size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>} onClick={onOpen} aria-label={`Open estimate for ${afe.afe_code}`}>Estimate</Button>
    {actions.length > 0 && <>
      <Button size="small" color="inherit" endIcon={<ArrowDropDownRounded/>} onClick={event => setAnchor(event.currentTarget)} aria-label={`Status actions for ${afe.afe_code}`}>Status</Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}>
        {actions.map(action => {
          const needsEstimate = action === 'submit' && !estimateReady
          const item = <MenuItem key={action} disabled={needsEstimate} onClick={() => { close(); onStatus(action) }}>
            {STATUS_ACTIONS[action].label} → {STATUS_LABEL[STATUS_ACTIONS[action].to]}
          </MenuItem>
          return needsEstimate
            ? <Tooltip key={action} title="Save a cost estimate with a total above zero first." placement="left"><span>{item}</span></Tooltip>
            : item
        })}
      </Menu>
    </>}
  </Box>
}

export function AfeEstimationTab() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [rows, setRows] = useState<Afe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [statusTarget, setStatusTarget] = useState<{ afe: Afe; action: AfeStatusAction } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await api<Afe[]>('/afe/afes'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'AFE cost estimation could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const counts = useMemo(() => ({
    draft: rows.filter(row => row.status === 'draft').length,
    submitted: rows.filter(row => row.status === 'submitted').length,
    review: rows.filter(row => row.status === 'review').length,
    approval: rows.filter(row => row.status === 'approval').length,
    warnings: rows.filter(row => row.warning_count > 0).length,
  }), [rows])

  const columns = useMemo<ColDef<Afe>[]>(() => [
    { headerName: 'AFE CODE', field: 'afe_code', minWidth: 125, flex: .75 },
    { headerName: 'AFE NAME', field: 'afe_name', minWidth: 190, flex: 1.2 },
    { headerName: 'RIG · WELL', field: 'well_name', minWidth: 210, flex: 1.2, valueFormatter: params => params.data ? `${params.data.rig_code} · ${params.data.well_code}` : '' },
    { headerName: 'STATUS', field: 'status', minWidth: 125, maxWidth: 140, cellRenderer: ({ data }: { data: Afe }) => data && <Box display="flex" alignItems="center" height="100%"><StatusTag status={data.status}/></Box> },
    { headerName: 'SERVICES', field: 'services_total', minWidth: 130, valueFormatter: params => amountText(params.value, params.data?.standard_currency) },
    { headerName: 'CONSUMABLES', field: 'consumables_total', minWidth: 135, valueFormatter: params => amountText(params.value, params.data?.standard_currency) },
    { headerName: 'TANGIBLES', field: 'tangibles_total', minWidth: 130, valueFormatter: params => amountText(params.value, params.data?.standard_currency) },
    { headerName: 'TOTAL ESTIMATE', field: 'total_cost', minWidth: 175, flex: .9, valueFormatter: params => params.data ? afeTotalText(params.data) : '' },
    { headerName: 'WARNINGS', field: 'warning_count', minWidth: 115, maxWidth: 130, valueFormatter: params => Number(params.value) > 0 ? `${params.value} to review` : 'None' },
    { headerName: 'ESTIMATE SAVED', field: 'estimate_saved_at', minWidth: 150, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : 'Not saved' },
    { headerName: 'STATUS CHANGED', field: 'status_changed_at', minWidth: 150, valueFormatter: params => params.value ? new Date(params.value).toLocaleString() : '' },
    {
      headerName: 'ACTIONS', width: 260, minWidth: 260, maxWidth: 260, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: Afe }) => data && <EstimateActions
        afe={data}
        can={can}
        onOpen={() => navigate(`/afe/estimate/${data.id}`)}
        onStatus={action => setStatusTarget({ afe: data, action })}
      />,
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [navigate, can])

  const onStatusDone = async (updated: Afe, action: AfeStatusAction) => {
    setStatusTarget(null)
    setNotice(`${updated.afe_code} is now ${STATUS_LABEL[updated.status]}. ${STATUS_ACTIONS[action].label} was recorded in the audit trail.`)
    await load()
  }

  return <>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.2 }, mb: 1.8, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap">
        <Box>
          <Typography fontWeight={800} fontSize={15}>Cost estimation and approval</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.35}>
            Open an AFE to build its estimate. Status changes are made here or in the estimate, never in the register.
          </Typography>
        </Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          <Chip size="small" label={`Draft ${counts.draft}`}/>
          <Chip size="small" color="info" variant="outlined" label={`Submitted ${counts.submitted}`}/>
          <Chip size="small" color="warning" variant="outlined" label={`Review ${counts.review}`}/>
          <Chip size="small" color="success" variant="outlined" label={`Approval ${counts.approval}`}/>
          {counts.warnings > 0 && <Chip size="small" color="warning" label={`${counts.warnings} with warnings`}/>}
        </Box>
      </Box>
      {!can('afe:estimate') && <Alert severity="info" sx={{ mt: 1.5 }}>You can view estimates but not change them. Estimate editing requires the AFE estimate permission.</Alert>}
    </Paper>

    {loading
      ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : <DataTable
        fillHeight
        fillReserve={44}
        rows={rows}
        columns={columns}
        searchPlaceholder="Search estimates by AFE, rig, well or status..."
        exportName="afe-cost-estimation"
        canExport={can('afe:export')}
        onExport={async (format, recordCount) => {
          await api('/afe/export-audit', { method: 'POST', body: body({ module: 'estimates', format, record_count: recordCount, include_deleted: false }) })
        }}
      />}

    <StatusDialog
      afe={statusTarget?.afe ?? null}
      action={statusTarget?.action ?? null}
      onClose={() => setStatusTarget(null)}
      onDone={(updated, action) => void onStatusDone(updated, action)}
    />
    <Typography fontSize={11.5} color="text.secondary" mt={1.5} display="flex" alignItems="center" gap={.6}>
      <CalculateOutlined sx={{ fontSize: 14 }}/> Totals are the saved estimate. Open an AFE to see line-by-line detail.
    </Typography>
  </>
}
