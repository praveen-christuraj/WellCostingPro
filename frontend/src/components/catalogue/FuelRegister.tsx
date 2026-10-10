import { useCallback, useEffect, useMemo, useState } from 'react'
import { HistoryOutlined, PriceChangeOutlined } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../DataTable'
import { ErrorMessage } from '../Common'
import { ReviseRateDialog } from './ReviseRateDialog'
import { PriceHistoryDialog } from './PriceHistoryDialog'
import { useAuth } from '../../context/AuthContext'
import { api, body } from '../../lib/api'
import { FUEL_CONFIG, cellValue, formatDate, type PricedOverview, type PricedRecord } from '../../lib/catalogue'

// Fuel is deliberately minimal: four fixed fuel types whose price is updated when it changes.
// There is no create, edit, delete or import for fuel.
export function FuelRegister() {
  const { can } = useAuth()
  const config = FUEL_CONFIG
  const [rows, setRows] = useState<PricedRecord[]>([])
  const [overview, setOverview] = useState<PricedOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reviseRecord, setReviseRecord] = useState<PricedRecord | null>(null)
  const [reviseError, setReviseError] = useState('')
  const [revising, setRevising] = useState(false)
  const [historyRecord, setHistoryRecord] = useState<PricedRecord | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [records, summary] = await Promise.all([
        api<PricedRecord[]>('/master-data/fuel-types'),
        api<PricedOverview>('/master-data/fuel-types/overview'),
      ])
      setRows(records)
      setOverview(summary)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load fuel prices')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const revise = async (payload: Record<string, unknown>) => {
    if (!reviseRecord) return
    setRevising(true)
    setReviseError('')
    try {
      await api(`/master-data/fuel-types/${reviseRecord.id}/revise`, { method: 'POST', body: body(payload) })
      setNotice(`${reviseRecord.fuel_name} price updated. The previous price is kept in its history.`)
      setReviseRecord(null)
      await load()
    } catch (caught) {
      setReviseError(caught instanceof Error ? caught.message : 'Could not save the new price')
    } finally {
      setRevising(false)
    }
  }

  const columns = useMemo<ColDef<PricedRecord>[]>(() => [
    ...config.columns.map<ColDef<PricedRecord>>(col => ({
      headerName: col.label, field: col.key, minWidth: col.width ?? 110, flex: col.flex,
      valueFormatter: params => params.data ? cellValue(col, params.data) : '',
    })),
    {
      headerName: 'ACTIONS', width: 260, minWidth: 260, maxWidth: 260, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: PricedRecord }) => <Box display="flex" alignItems="center" height="100%" gap={.2}>
        {can('master-data:update') && <Button size="small" onClick={() => { setReviseError(''); setReviseRecord(data) }} aria-label={`Update price for ${data.fuel_name}`} startIcon={<PriceChangeOutlined sx={{ fontSize: 15 }}/>}>Update price</Button>}
        <Button size="small" onClick={() => setHistoryRecord(data)} aria-label={`Price history for ${data.fuel_name}`} startIcon={<HistoryOutlined sx={{ fontSize: 15 }}/>}>History</Button>
      </Box>,
    },
  ], [config, can])

  const latest = rows.reduce<string | null>((max, row) => (row.effective_date && (!max || row.effective_date > max) ? row.effective_date : max), null)

  return <>
    {overview && <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' }, mb: 2 }}>
      <Paper className="stat-card" variant="outlined" sx={{ p: 2.2 }}>
        <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">Fuel types</Typography>
        <Typography className="stat-value" sx={{ fontSize: 27, my: 1 }}>{rows.length}</Typography>
        <Typography color="text.secondary" fontSize={11.5}>Fixed list, maintained per workspace</Typography>
      </Paper>
      <Paper className="stat-card" variant="outlined" sx={{ p: 2.2 }}>
        <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">Price updates (30 days)</Typography>
        <Typography className="stat-value" sx={{ fontSize: 27, my: 1 }}>{overview.revisions_last_30_days}</Typography>
        <Typography color="text.secondary" fontSize={11.5}>Recorded price changes</Typography>
      </Paper>
      <Paper className="stat-card" variant="outlined" sx={{ p: 2.2 }}>
        <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">Latest price date</Typography>
        <Typography className="stat-value" sx={{ fontSize: 22, my: 1.2 }}>{formatDate(latest)}</Typography>
        <Typography color="text.secondary" fontSize={11.5}>Most recent effective price</Typography>
      </Paper>
    </Box>}

    <Box mb={1.5}>
      <Typography fontFamily="Manrope" fontWeight={800} fontSize={16}>Fuel prices</Typography>
      <Typography color="text.secondary" fontSize={12} mt={.35}>Update a price only when it changes. Prices are per litre.</Typography>
    </Box>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    <ErrorMessage message={error}/>
    {loading ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box> : <DataTable
      rows={rows}
      columns={columns}
      searchPlaceholder="Search fuel types..."
      exportName={config.key}
      canExport={can('master-data:export')}
      onExport={async (format, recordCount) => {
        await api('/master-data/export-audit', { method: 'POST', body: body({ module: config.key, format, record_count: recordCount, include_deleted: false }) })
      }}
    />}

    {reviseRecord && <ReviseRateDialog config={config} record={reviseRecord} busy={revising} error={reviseError} onClose={() => { if (!revising) setReviseRecord(null) }} onSubmit={payload => void revise(payload)}/>}
    {historyRecord && <PriceHistoryDialog config={config} record={historyRecord} onClose={() => setHistoryRecord(null)}/>}
  </>
}
