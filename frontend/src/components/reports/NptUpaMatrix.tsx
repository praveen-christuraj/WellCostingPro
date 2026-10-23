import { Alert, Box, Paper, Typography } from '@mui/material'
import { formatMoney, type NptUpaReport } from '../../lib/usageReports'

const cellSx = {
  border: '1px solid',
  borderColor: 'divider',
  px: 1,
  py: 0.75,
  fontSize: 11.5,
  whiteSpace: 'nowrap',
} as const

type Measure = {
  key: string
  label: string
  kind: 'days' | 'money'
  field: 'planned_days' | 'upa_days' | 'npt_days' | 'planned_amount' | 'upa_amount' | 'npt_amount'
  total: boolean
}

const MEASURES: Measure[] = [
  { key: 'npt-days', label: 'NPT days', kind: 'days', field: 'npt_days', total: true },
  { key: 'npt-cost', label: `NPT cost`, kind: 'money', field: 'npt_amount', total: true },
  { key: 'upa-days', label: 'UPA days', kind: 'days', field: 'upa_days', total: true },
  { key: 'upa-cost', label: `UPA cost`, kind: 'money', field: 'upa_amount', total: true },
  { key: 'planned-days', label: 'Planned days (reference)', kind: 'days', field: 'planned_days', total: false },
  { key: 'planned-cost', label: 'Planned cost (reference)', kind: 'money', field: 'planned_amount', total: false },
]

/** NPT/UPA measure matrix: classification measures down the rows, wells across. */
export default function NptUpaMatrix({ report, currency }: { report: NptUpaReport; currency: string }) {
  const wellById = new Map(report.wells.map(well => [well.well_id, well]))
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, mb: 1.7, overflowX: 'auto' }}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={1.1}>
        <Box>
          <Typography fontWeight={800} fontSize={14}>NPT / UPA matrix</Typography>
          <Typography color="text.secondary" fontSize={11.2}>
            Days are distinct cost dates carrying that classification; costs are in {currency}.
          </Typography>
        </Box>
        <Typography color="text.secondary" fontSize={11.2} className="tnum">
          {report.wells.length} well{report.wells.length === 1 ? '' : 's'}
        </Typography>
      </Box>
      {report.wells.length === 0 ? (
        <Alert severity="info">No NPT/UPA records match the selected filters.</Alert>
      ) : (
        <Box
          component="table"
          sx={{
            borderCollapse: 'collapse', width: '100%',
            minWidth: Math.max(720, report.wells.length * 200 + 300),
            '& th, & td': cellSx,
            '& thead th': { bgcolor: 'action.hover', textAlign: 'center', fontWeight: 800 },
            '& tbody th': { textAlign: 'left', position: 'sticky', left: 0, bgcolor: 'background.paper', zIndex: 1 },
            '& thead th.sticky-head': { position: 'sticky', left: 0, zIndex: 2, textAlign: 'left' },
            '& td': { textAlign: 'right', fontVariantNumeric: 'tabular-nums' },
            '& tr[data-total="true"]': { bgcolor: 'action.hover', fontWeight: 800 },
            '& tr[data-reference="true"]': { color: 'text.secondary' },
          }}
        >
          <thead>
            <tr>
              <th className="sticky-head">Measure</th>
              {report.wells.map(well => (
                <th key={well.well_id}>
                  {well.well_code} — {well.well_name}
                  <Typography component="span" display="block" color="text.secondary" fontSize={10.5} fontWeight={600}>
                    {well.block_code} · {well.rig_code}
                  </Typography>
                </th>
              ))}
              <th>All wells</th>
            </tr>
          </thead>
          <tbody>
            {MEASURES.map(measure => (
              <tr key={measure.key} data-total={measure.total || null} data-reference={!measure.total || null}>
                <th>{measure.label}{measure.kind === 'money' ? ` (${currency})` : ''}</th>
                {report.wells.map(well => {
                  const value = well[measure.field]
                  return <td key={well.well_id}>{measure.kind === 'money' ? formatMoney(value, currency) : value}</td>
                })}
                <td>{measure.kind === 'money'
                  ? formatMoney(report.totals[measure.field], currency)
                  : report.totals[measure.field]}</td>
              </tr>
            ))}
            <tr data-total="true">
              <th>Total cost ({currency})</th>
              {report.wells.map(well => <td key={well.well_id}>{formatMoney(well.total_amount, currency)}</td>)}
              <td>{formatMoney(report.totals.total_amount, currency)}</td>
            </tr>
          </tbody>
        </Box>
      )}
      {wellById.size === 0 ? null : (
        <Typography color="text.secondary" fontSize={11} mt={1}>
          A cost date can count for more than one classification when the sheet carries both NPT and UPA lines.
        </Typography>
      )}
    </Paper>
  )
}
