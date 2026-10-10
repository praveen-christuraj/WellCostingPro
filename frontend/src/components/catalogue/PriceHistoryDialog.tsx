import { useEffect, useState } from 'react'
import { Box, Chip, CircularProgress, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import { PanelDialog, ErrorMessage } from '../Common'
import { api } from '../../lib/api'
import { formatDate, formatMoney, formatPercent, type PricedRecord, type RateRevision, type TypeConfig } from '../../lib/catalogue'

// Read-only price history for one item: every revision with the rate it replaced and the reason.
export function PriceHistoryDialog({ config, record, onClose }: { config: TypeConfig; record: PricedRecord; onClose: () => void }) {
  const [rows, setRows] = useState<RateRevision[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setRows(null)
    api<RateRevision[]>(`/master-data/${config.key}/${record.id}/revisions`)
      .then(setRows)
      .catch(caught => setError(caught instanceof Error ? caught.message : 'Could not load the price history'))
  }, [config.key, record.id])

  const uplift = config.priced === 'uplift'
  const code = String(record[config.codeKey] ?? '')
  const name = String(record[config.nameKey] ?? '')

  return <PanelDialog open title={`Price history: ${code}`} subtitle={`${name} · ${rows?.length ?? 0} revisions. Records are never edited; each change keeps the rate it replaced.`} onClose={onClose} maxWidth="lg">
    {!rows && !error && <Box py={5} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={24}/></Box>}
    <ErrorMessage message={error}/>
    {rows && <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflow: 'auto', maxHeight: 420 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            {['REV', 'EFFECTIVE', 'RATE', 'PREVIOUS', 'CHANGE', ...(uplift ? ['UPLIFT %', 'FINAL COST'] : []), 'CCY', 'PO NUMBER', 'REASON', 'RECORDED BY'].map(head =>
              <TableCell key={head} sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper', whiteSpace: 'nowrap' }}>{head}</TableCell>)}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map(row => {
            const previous = Number(row.previous_unit_rate)
            const change = previous > 0 ? ((Number(row.unit_rate) - previous) / previous) * 100 : null
            return <TableRow key={row.id} hover>
              <TableCell><Chip size="small" label={`#${row.revision_number}`}/></TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDate(row.effective_date)}</TableCell>
              <TableCell sx={{ fontWeight: 700 }}>{formatMoney(row.unit_rate)}</TableCell>
              <TableCell>{row.revision_number === 1 ? '—' : formatMoney(row.previous_unit_rate)}</TableCell>
              <TableCell sx={{ color: change === null ? 'text.secondary' : change > 0 ? 'error.main' : change < 0 ? 'success.main' : 'text.secondary' }}>
                {change === null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}
              </TableCell>
              {uplift && <TableCell>{formatPercent(row.cost_uplift)}</TableCell>}
              {uplift && <TableCell>{formatMoney(row.final_cost)}</TableCell>}
              <TableCell>{row.currency || '—'}</TableCell>
              <TableCell>{row.po_number || '—'}</TableCell>
              <TableCell sx={{ minWidth: 220 }}>{row.reason || '—'}</TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{row.recorded_by || '—'}</TableCell>
            </TableRow>
          })}
        </TableBody>
      </Table>
      {rows.length === 0 && <Typography p={2} color="text.secondary" fontSize={13}>No revisions yet.</Typography>}
    </Box>}
  </PanelDialog>
}
