import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { ArrowForwardRounded, RefreshRounded, StorageOutlined, TableChartOutlined, TableRowsOutlined, VpnKeyOutlined } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body } from '../lib/api'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'
import { useAuth } from '../context/AuthContext'
import { numberComparator, yesNo, type CatalogueItem, type TableCatalogue } from '../lib/databaseBrowser'

type CatalogueRow = CatalogueItem & { key_text: string; timestamped: string }

function StatCard({ label, value, hint, icon }: { label: string; value: number | undefined; hint: string; icon: ReactNode }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2.2, borderRadius: 2 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={11} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon" sx={{ bgcolor: 'primary.light', color: 'text.secondary' }}>{icon}</Box>
    </Box>
    <Typography className="stat-value" sx={{ fontSize: 28, my: 1 }}>{value === undefined ? '…' : value.toLocaleString()}</Typography>
    <Typography color="text.secondary" fontSize={11.5}>{hint}</Typography>
  </Paper>
}

// Module dashboard entry point: every table of the workspace database, read-only.
export default function DatabaseBrowser() {
  const { can } = useAuth()
  const canExport = can('database-browser:export')
  const [catalogue, setCatalogue] = useState<TableCatalogue | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setCatalogue(await api<TableCatalogue>('/database-browser/tables'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The table catalogue could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const rows = useMemo<CatalogueRow[]>(() => (catalogue?.items ?? []).map(item => ({
    ...item,
    key_text: item.primary_key.length ? item.primary_key.join(', ') : '—',
    timestamped: yesNo(item.has_timestamps),
  })), [catalogue])

  const columns = useMemo<ColDef<CatalogueRow>[]>(() => [
    {
      headerName: 'TABLE', field: 'name', minWidth: 230,
      cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%">
        <Typography component={RouterLink} to={`/other-management/database/${encodeURIComponent(value)}`} fontFamily="monospace" fontWeight={700} fontSize={12.5} color="primary.main" sx={{ textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}>{value}</Typography>
      </Box>,
    },
    { headerName: 'MODULE', field: 'group', minWidth: 190 },
    { headerName: 'COLUMNS', field: 'column_count', width: 120, flex: 0, type: 'rightAligned', comparator: numberComparator },
    { headerName: 'ROWS', field: 'row_count', width: 120, flex: 0, type: 'rightAligned', comparator: numberComparator },
    { headerName: 'PRIMARY KEY', field: 'key_text', minWidth: 170 },
    { headerName: 'TIMESTAMPED', field: 'timestamped', width: 165, flex: 0 },
    { headerName: 'TENANT SCOPE', field: 'scope', minWidth: 190, cellRenderer: ({ value }: { value: string }) => <Tag tone="info">{value}</Tag> },
    {
      headerName: 'OPEN', width: 110, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data?: CatalogueRow }) => data ? <Box display="flex" alignItems="center" height="100%">
        <Button component={RouterLink} to={`/other-management/database/${encodeURIComponent(data.name)}`} size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 16 }}/>}>Open</Button>
      </Box> : null,
    },
  ], [])

  return <>
    <PageHeading
      eyebrow="OTHER MANAGEMENTS / DATABASE BROWSER"
      title="Database Browser"
      subtitle="Every table in this workspace database, with its structure and rows. Read-only, so you can check data and prepare Power BI extracts without opening the database."
      action={<Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={busy}>{busy ? 'Refreshing...' : 'Refresh'}</Button>}
    />
    <ErrorMessage message={error}/>
    {busy && !catalogue ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : <>
      <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(4, minmax(0, 1fr))' }, mb: 2.5 }}>
        <StatCard label="Tables" value={catalogue?.total_tables} hint="Tables that belong to this workspace" icon={<StorageOutlined sx={{ fontSize: 18 }}/>}/>
        <StatCard label="Records" value={catalogue?.total_rows} hint="Rows across all tables in this workspace" icon={<TableRowsOutlined sx={{ fontSize: 18 }}/>}/>
        <StatCard label="Columns" value={catalogue?.items.reduce((sum, item) => sum + item.column_count, 0)} hint="Columns visible in the browser" icon={<TableChartOutlined sx={{ fontSize: 18 }}/>}/>
        <StatCard label="Protected columns" value={catalogue?.hidden_columns} hint="Credentials and session secrets, never shown" icon={<VpnKeyOutlined sx={{ fontSize: 18 }}/>}/>
      </Box>
      <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2, borderColor: 'divider' }}>
        <Typography fontSize={12.5} color="text.secondary" lineHeight={1.6}>
          Open a table to see its rows (newest first, up to 5,000 on screen) and its structure. Use <b>Download full table</b> on a table page to export every row as CSV for Power BI.
          {catalogue && catalogue.excluded_tables > 0 ? ` ${catalogue.excluded_tables} internal table${catalogue.excluded_tables === 1 ? ' is' : 's are'} hidden (migration bookkeeping and session storage).` : ''}
        </Typography>
      </Paper>
      <DataTable<CatalogueRow>
        rows={rows}
        columns={columns}
        rowKey="name"
        searchPlaceholder="Search tables, modules, keys..."
        exportName="database-catalogue"
        canExport={canExport}
        onExport={async (format, recordCount) => {
          await api('/database-browser/export-audit', { method: 'POST', body: body({ scope: 'catalogue', format, record_count: recordCount }) })
        }}
      />
    </>}
  </>
}
