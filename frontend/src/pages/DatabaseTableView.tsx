import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Box, Button, CircularProgress, Paper, Tab, Tabs, Typography } from '@mui/material'
import { ArrowBackRounded, DownloadRounded, RefreshRounded } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body, downloadFile } from '../lib/api'
import { ErrorMessage, PageHeading } from '../components/Common'
import { DataTable } from '../components/DataTable'
import { useAuth } from '../context/AuthContext'
import {
  ROW_KEY,
  rowColumnDefs,
  tableApi,
  withRowKeys,
  yesNo,
  type GridRow,
  type IndexInfo,
  type TableRows,
  type TableStructure,
} from '../lib/databaseBrowser'

type StructureRow = {
  position: number
  name: string
  data_type: string
  kind: string
  nullable: string
  primary_key: string
  unique: string
  indexed: string
  foreign_key: string
  default: string
  max_length: number | string
}

type IndexRow = IndexInfo & { position: number }

const STRUCTURE_COLUMNS: ColDef<StructureRow>[] = [
  { headerName: 'POSITION', field: 'position', width: 110, flex: 0, type: 'rightAligned' },
  { headerName: 'COLUMN', field: 'name', minWidth: 180 },
  { headerName: 'DATA TYPE', field: 'data_type', minWidth: 150 },
  { headerName: 'KIND', field: 'kind', width: 110, flex: 0 },
  { headerName: 'NULLABLE', field: 'nullable', width: 110, flex: 0 },
  { headerName: 'PRIMARY KEY', field: 'primary_key', width: 130, flex: 0 },
  { headerName: 'UNIQUE', field: 'unique', width: 105, flex: 0 },
  { headerName: 'INDEXED', field: 'indexed', width: 105, flex: 0 },
  { headerName: 'FOREIGN KEY', field: 'foreign_key', minWidth: 170 },
  { headerName: 'DEFAULT', field: 'default', minWidth: 140 },
  { headerName: 'MAX LENGTH', field: 'max_length', width: 125, flex: 0, type: 'rightAligned' },
]

const INDEX_COLUMNS: ColDef<IndexRow>[] = [
  { headerName: 'POSITION', field: 'position', width: 110, flex: 0, type: 'rightAligned' },
  { headerName: 'INDEX', field: 'name', minWidth: 230 },
  { headerName: 'COLUMNS', field: 'columns', minWidth: 220 },
  { headerName: 'UNIQUE', field: 'unique', width: 110, flex: 0, valueFormatter: p => (p.value ? 'Yes' : 'No') },
]

// One table in the workspace database: its rows (Data) and its definition (Structure).
export default function DatabaseTableView() {
  const { tableName = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'structure' ? 'structure' : 'data'
  const { can } = useAuth()
  const canExport = can('database-browser:export')
  const [rows, setRows] = useState<TableRows | null>(null)
  const [structure, setStructure] = useState<TableStructure | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const [definition, data] = await Promise.all([
        api<TableStructure>(`${tableApi(tableName)}/structure`),
        api<TableRows>(`${tableApi(tableName)}/rows`),
      ])
      setStructure(definition)
      setRows(data)
    } catch (caught) {
      setStructure(null)
      setRows(null)
      setError(caught instanceof Error ? caught.message : 'The table could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [tableName])

  useEffect(() => { void load() }, [load])

  const gridRows = useMemo<GridRow[]>(() => withRowKeys(rows?.items ?? []), [rows])
  const gridColumns = useMemo(() => rowColumnDefs(structure?.columns ?? []), [structure])
  const structureRows = useMemo<StructureRow[]>(() => (structure?.columns ?? []).map(column => ({
    position: column.position,
    name: column.name,
    data_type: column.data_type,
    kind: column.kind,
    nullable: yesNo(column.nullable),
    primary_key: yesNo(column.primary_key),
    unique: yesNo(column.unique),
    indexed: yesNo(column.indexed),
    foreign_key: column.foreign_key || '—',
    default: column.default || '—',
    max_length: column.max_length ?? '—',
  })), [structure])
  const indexRows = useMemo<IndexRow[]>(() => (structure?.indexes ?? []).map((index, offset) => ({ ...index, position: offset + 1 })), [structure])

  const download = async () => {
    setDownloading(true)
    setDownloadError('')
    try {
      await downloadFile(`${tableApi(tableName)}/download.csv`, `${tableName}.csv`)
    } catch (caught) {
      setDownloadError(caught instanceof Error ? caught.message : 'The download could not be completed')
    } finally {
      setDownloading(false)
    }
  }

  const audit = (scope: 'rows' | 'structure') => async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/database-browser/export-audit', { method: 'POST', body: body({ scope, format, record_count: recordCount, table: tableName }) })
  }

  const subtitle = structure
    ? `${structure.group} · ${structure.row_count.toLocaleString()} ${structure.row_count === 1 ? 'row' : 'rows'} in this workspace · ${structure.columns.length} columns · tenant scope ${structure.scope}`
    : busy ? 'Loading table...' : 'Table unavailable'

  return <>
    <PageHeading
      eyebrow="OTHER MANAGEMENTS / DATABASE BROWSER"
      title={tableName}
      subtitle={subtitle}
      action={<Box display="flex" gap={1} flexWrap="wrap">
        <Button component={RouterLink} to="/other-management/database" variant="outlined" startIcon={<ArrowBackRounded/>}>All tables</Button>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={busy}>{busy ? 'Refreshing...' : 'Refresh'}</Button>
        {canExport && <Button variant="contained" startIcon={downloading ? <CircularProgress size={14} color="inherit"/> : <DownloadRounded/>} onClick={() => void download()} disabled={downloading || !structure}>{downloading ? 'Preparing CSV...' : 'Download full table (CSV)'}</Button>}
      </Box>}
    />
    <ErrorMessage message={error}/>
    <ErrorMessage message={downloadError}/>
    {busy && !structure ? <Box py={8} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : structure && rows && <>
      <Paper variant="outlined" sx={{ borderColor: 'divider', borderRadius: 2, overflow: 'hidden' }}>
        <Tabs
          value={view}
          onChange={(_event, next: 'data' | 'structure') => setParams(next === 'structure' ? { view: 'structure' } : {}, { replace: true })}
          aria-label="Table views"
          sx={{ px: 2.5, borderBottom: '1px solid', borderColor: 'divider' }}
        >
          <Tab value="data" label={`Data (${rows.total.toLocaleString()})`} id="table-tab-data" aria-controls="table-panel-data"/>
          <Tab value="structure" label={`Structure (${structure.columns.length})`} id="table-tab-structure" aria-controls="table-panel-structure"/>
        </Tabs>

        {view === 'data' && <Box id="table-panel-data" role="tabpanel" aria-labelledby="table-tab-data" sx={{ p: { xs: 1.5, sm: 2 } }}>
          {rows.truncated && <Alert severity="info" sx={{ mb: 1.5 }}>
            Showing the newest {rows.shown.toLocaleString()} of {rows.total.toLocaleString()} rows. Filters and exports below apply to the rows on screen; use Download full table (CSV) for every row.
          </Alert>}
          {rows.total === 0 && <Typography color="text.secondary" fontSize={12.5} mb={1.5}>This table has no rows in this workspace yet.</Typography>}
          <DataTable<GridRow>
            fillHeight
            rows={gridRows}
            columns={gridColumns}
            rowKey={ROW_KEY}
            searchPlaceholder="Search loaded rows..."
            exportName={tableName}
            canExport={canExport}
            onExport={audit('rows')}
          />
        </Box>}

        {view === 'structure' && <Box id="table-panel-structure" role="tabpanel" aria-labelledby="table-tab-structure" sx={{ p: { xs: 1.5, sm: 2 } }}>
          {structure.hidden_columns > 0 && <Alert severity="info" sx={{ mb: 2 }}>
            {structure.hidden_columns} credential or session {structure.hidden_columns === 1 ? 'column is' : 'columns are'} not listed here and cannot be exported.
          </Alert>}
          <Typography fontWeight={800} fontSize={14} mb={1}>Columns</Typography>
          <DataTable<StructureRow>
            rows={structureRows}
            columns={STRUCTURE_COLUMNS}
            rowKey="position"
            searchPlaceholder="Search columns..."
            exportName={`${tableName}-columns`}
            canExport={canExport}
            onExport={audit('structure')}
          />
          <Typography fontWeight={800} fontSize={14} mt={3} mb={1}>Indexes and unique constraints</Typography>
          <DataTable<IndexRow>
            rows={indexRows}
            columns={INDEX_COLUMNS}
            rowKey="position"
            searchPlaceholder="Search indexes..."
            exportName={`${tableName}-indexes`}
            canExport={canExport}
            onExport={audit('structure')}
          />
        </Box>}
      </Paper>
    </>}
  </>
}
