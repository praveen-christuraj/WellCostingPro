import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, OpenInNew, Search } from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  InputAdornment,
  Menu,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { api } from '../../lib/api'
import { displayDate } from '../../lib/dailyCost'
import { exportCsv, exportPdf, exportXlsx, type ExportColumn } from '../../lib/export'
import {
  fuelLitres,
  fuelQuery,
  type FuelCostLedgerLine,
  type FuelCostPaginatedLines,
} from '../../lib/fuelCost'
import { Tag } from '../Common'

type Props = {
  rigId: string
  rigCode: string
  dateFrom: string
  dateTo: string
  companyId?: string
  categoryKey?: string
  canExport: boolean
  title: string
  onOpenDate: (costDate: string) => void
}

function splitCategoryKey(categoryKey?: string): { category_id?: string; category_name?: string } {
  if (!categoryKey) return {}
  if (categoryKey === '__none__') return { category_id: '__none__' }
  if (categoryKey.startsWith('cat:')) return { category_name: categoryKey.slice(4) }
  return { category_id: categoryKey }
}

export function FuelLinesLedger({
  rigId,
  rigCode,
  dateFrom,
  dateTo,
  companyId = '',
  categoryKey = '',
  canExport,
  title,
  onOpenDate,
}: Props) {
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<20 | 50 | 100>(20)
  const [data, setData] = useState<FuelCostPaginatedLines | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [exportAnchor, setExportAnchor] = useState<HTMLElement | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 220)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [rigId, dateFrom, dateTo, companyId, categoryKey, debouncedSearch, pageSize])

  const catParams = useMemo(() => splitCategoryKey(categoryKey), [categoryKey])

  const loadPage = useCallback(async () => {
    if (!rigId) return
    setLoading(true)
    setError('')
    try {
      const query = fuelQuery({
        from: dateFrom || undefined,
        to: dateTo || undefined,
        company_id: companyId || undefined,
        category_id: catParams.category_id,
        category_name: catParams.category_name,
        search: debouncedSearch || undefined,
        page,
        page_size: pageSize,
      })
      const res = await api<FuelCostPaginatedLines>(`/fuel-cost/rigs/${rigId}/lines${query}`)
      setData(res)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [rigId, dateFrom, dateTo, companyId, catParams, debouncedSearch, page, pageSize])

  useEffect(() => {
    loadPage()
  }, [loadPage])

  const totalCount = data?.total_count ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))

  const exportCols: ExportColumn<FuelCostLedgerLine>[] = useMemo(() => [
    { header: 'DATE', value: row => displayDate(row.cost_date) },
    { header: 'RIG', value: row => row.rig_code },
    { header: 'COMPANY', value: row => row.company_name },
    { header: 'VENDOR CODE', value: row => row.vendor_code || '—' },
    { header: 'CATEGORY', value: row => row.category_name || 'Uncategorised' },
    { header: 'AGO CONSUMED (LITRES)', value: row => fuelLitres(row.litres) },
    { header: 'SOURCE', value: row => row.source },
    { header: 'REMARKS', value: row => row.remarks || '' },
  ], [])

  const runExport = async (format: 'csv' | 'xlsx' | 'pdf') => {
    setExportAnchor(null)
    if (!rigId) return
    setExporting(true)
    try {
      const query = fuelQuery({
        from: dateFrom || undefined,
        to: dateTo || undefined,
        company_id: companyId || undefined,
        category_id: catParams.category_id,
        category_name: catParams.category_name,
        search: debouncedSearch || undefined,
        page: 1,
        page_size: 5000,
      })
      const full = await api<FuelCostPaginatedLines>(`/fuel-cost/rigs/${rigId}/lines${query}`)
      const base = `fuel-lines-${rigCode || 'rig'}`
      if (format === 'csv') exportCsv(`${base}.csv`, full.rows, exportCols)
      else if (format === 'xlsx') await exportXlsx(`${base}.xlsx`, full.rows, exportCols)
      else await exportPdf(`${base}.pdf`, `${title} — ${rigCode}`, full.rows, exportCols)
      await api('/fuel-cost/export-audit', {
        method: 'POST',
        body: JSON.stringify({
          module: 'company-lines',
          format,
          record_count: full.rows.length,
          rig_id: rigId,
        }),
      }).catch(() => undefined)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1}
        alignItems={{ xs: 'flex-start', md: 'center' }}
        justifyContent="space-between"
        sx={{ mb: 1.25 }}
      >
        <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
          <Typography sx={{ fontWeight: 800, fontSize: 14 }}>{title}</Typography>
          <Typography
            color="text.secondary"
            sx={{ fontSize: 12.5 }}
            aria-live="polite"
          >
            {loading
              ? 'Loading ledger…'
              : `${totalCount.toLocaleString()} line(s) · Total AGO ${fuelLitres(data?.total_litres ?? 0)} L`}
          </Typography>
        </Stack>

        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField
            size="small"
            placeholder="Search company, category or remarks…"
            value={search}
            onChange={event => setSearch(event.target.value)}
            inputProps={{ 'aria-label': `Search ${title}` }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search fontSize="small" color="action" />
                </InputAdornment>
              ),
            }}
            sx={{ width: { xs: '100%', sm: 270 } }}
          />
          {canExport ? (
            <>
              <Button
                size="small"
                variant="outlined"
                startIcon={<Download fontSize="small" />}
                disabled={exporting || !totalCount}
                onClick={event => setExportAnchor(event.currentTarget)}
              >
                {exporting ? 'Exporting…' : 'Export'}
              </Button>
              <Menu
                anchorEl={exportAnchor}
                open={Boolean(exportAnchor)}
                onClose={() => setExportAnchor(null)}
              >
                <MenuItem onClick={() => runExport('csv')}>Export CSV</MenuItem>
                <MenuItem onClick={() => runExport('xlsx')}>Export Excel (.xlsx)</MenuItem>
                <MenuItem onClick={() => runExport('pdf')}>Export PDF</MenuItem>
              </Menu>
            </>
          ) : null}
        </Stack>
      </Stack>

      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}

      {!loading && !data?.rows.length ? (
        <Typography color="text.secondary" sx={{ py: 2, fontSize: 13 }}>
          No daily company consumption lines match the selected filters.
        </Typography>
      ) : (
        <TableContainer
          sx={{
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1.5,
          }}
        >
          <Table size="small" aria-label={title}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>DATE</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>COMPANY</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>CATEGORY</TableCell>
                <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>AGO (LITRES)</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>SOURCE</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>REMARKS</TableCell>
                <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>ACTIONS</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(data?.rows ?? []).map(row => (
                <TableRow key={row.id} hover>
                  <TableCell sx={{ fontSize: 12.5, whiteSpace: 'nowrap' }}>
                    {displayDate(row.cost_date)}
                  </TableCell>
                  <TableCell sx={{ fontSize: 12.5, fontWeight: 600 }}>
                    {row.company_name}
                    {row.vendor_code ? (
                      <Box component="span" sx={{ ml: 0.75, color: 'text.secondary', fontSize: 11, fontWeight: 500 }}>
                        ({row.vendor_code})
                      </Box>
                    ) : null}
                  </TableCell>
                  <TableCell sx={{ fontSize: 12.5 }}>
                    {row.category_name || 'Uncategorised'}
                  </TableCell>
                  <TableCell
                    align="right"
                    sx={{ fontSize: 12.5, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}
                  >
                    {fuelLitres(row.litres)}
                  </TableCell>
                  <TableCell>
                    <Tag tone={row.source === 'import' ? 'info' : 'neutral'}>{row.source}</Tag>
                  </TableCell>
                  <TableCell sx={{ fontSize: 12.5, color: 'text.secondary', maxWidth: 260 }}>
                    {row.remarks || '—'}
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                    <Button
                      size="small"
                      endIcon={<OpenInNew sx={{ fontSize: 14 }} />}
                      onClick={() => onOpenDate(row.cost_date)}
                    >
                      Open day
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        alignItems={{ sm: 'center' }}
        justifyContent="space-between"
        sx={{ mt: 1.25 }}
      >
        <Typography color="text.secondary" sx={{ fontSize: 12 }}>
          {totalCount
            ? `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, totalCount)} of ${totalCount.toLocaleString()}`
            : '0 records'}
        </Typography>
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            select
            size="small"
            label="Rows"
            value={pageSize}
            onChange={event => setPageSize(Number(event.target.value) as 20 | 50 | 100)}
            sx={{ width: 92 }}
          >
            <MenuItem value={20}>20</MenuItem>
            <MenuItem value={50}>50</MenuItem>
            <MenuItem value={100}>100</MenuItem>
          </TextField>
          <Button
            size="small"
            variant="outlined"
            disabled={loading || page <= 1}
            onClick={() => setPage(current => Math.max(1, current - 1))}
          >
            Previous
          </Button>
          <Typography sx={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
            Page {Math.min(page, totalPages)} of {totalPages}
          </Typography>
          <Button
            size="small"
            variant="outlined"
            disabled={loading || page >= totalPages}
            onClick={() => setPage(current => Math.min(totalPages, current + 1))}
          >
            Next
          </Button>
        </Stack>
      </Stack>
    </Paper>
  )
}
