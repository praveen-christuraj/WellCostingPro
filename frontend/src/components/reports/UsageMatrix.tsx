import { Fragment } from 'react'
import { Alert, Box, Paper, Typography } from '@mui/material'
import { formatMoney, formatQuantity, type UsageMatrix as Matrix } from '../../lib/usageReports'

const cellSx = {
  border: '1px solid',
  borderColor: 'divider',
  px: 1,
  py: 0.75,
  fontSize: 11.5,
  whiteSpace: 'nowrap',
} as const

/**
 * Shared matrix surface for every usage/cost report: item rows, well columns,
 * hole-section sub headers with usage/cost cells, and well + grand totals.
 * Tangible rows carry category band headers; cost-only reports hide quantities.
 */
export default function UsageMatrix({ report, title, hint }: { report: Matrix; title: string; hint: string }) {
  const costOnly = report.mode === 'cost'
  const cellMap = (rowId: string) => {
    const row = report.rows.find(item => item.item_id === rowId)
    const byWell = new Map(row?.cells.map(cell => [cell.well_id, cell]) ?? [])
    return (wellId: string, sectionKey?: string) => {
      const wellCell = byWell.get(wellId)
      if (!wellCell) return { quantity: '', amount: '' }
      if (!sectionKey) return { quantity: wellCell.quantity, amount: wellCell.amount }
      return wellCell.sections.find(section => section.section_key === sectionKey) ?? { quantity: '', amount: '' }
    }
  }
  const totalFor = (wellId: string) => report.well_totals.find(total => total.well_id === wellId)

  // Category band rows for the well-structured tangible categorization.
  const bands: { label: string; start: number }[] = []
  if (report.report === 'tangibles') {
    report.rows.forEach((row, index) => {
      const label = row.category || 'Uncategorised'
      if (index === 0 || bands[bands.length - 1].label !== label) bands.push({ label, start: index })
    })
  }
  const bandAt = (index: number) => {
    if (report.report !== 'tangibles') return null
    let current: string | null = null
    for (const band of bands) if (index >= band.start) current = band.label
    return current
  }

  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, mb: 1.7, overflowX: 'auto' }}>
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={1.1}>
        <Box>
          <Typography fontWeight={800} fontSize={14}>{title}</Typography>
          <Typography color="text.secondary" fontSize={11.2}>{hint}</Typography>
        </Box>
        <Typography color="text.secondary" fontSize={11.2} className="tnum">
          {report.rows.length} item{report.rows.length === 1 ? '' : 's'} · {report.wells.length} well{report.wells.length === 1 ? '' : 's'}
        </Typography>
      </Box>
      {report.wells.length === 0 || report.rows.length === 0 ? (
        <Alert severity="info" sx={{ mb: 1 }}>No usage or cost records match the selected filters.</Alert>
      ) : (
        <Box
          component="table"
          sx={{
            borderCollapse: 'collapse', width: '100%',
            minWidth: Math.max(760, report.wells.length * (costOnly ? 220 : 300) + 320),
            '& th, & td': cellSx,
            '& thead th': { bgcolor: 'action.hover', textAlign: 'center', fontWeight: 800 },
            '& tbody th': { textAlign: 'left', position: 'sticky', left: 0, bgcolor: 'background.paper', zIndex: 1 },
            '& thead th.sticky-head': { position: 'sticky', left: 0, zIndex: 2, textAlign: 'left' },
            '& th.sticky-total, & td.sticky-total': { position: 'sticky', right: 0, bgcolor: 'background.paper', zIndex: 1 },
            '& thead th.sticky-total': { zIndex: 2 },
            '& td': { textAlign: 'right', fontVariantNumeric: 'tabular-nums' },
            '& tr[data-total="true"]': { bgcolor: 'action.hover', fontWeight: 800 },
            '& tr[data-band="true"] th': { bgcolor: 'action.hover', textTransform: 'uppercase', letterSpacing: 0.6, fontSize: 10.8 },
          }}
        >
          <thead>
            <tr>
              <th className="sticky-head" rowSpan={2}>Cost item</th>
              {report.wells.map(well => (
                <th key={well.well_id} colSpan={costOnly ? well.sections.length + 1 : well.sections.length * 2 + 2}>
                  {well.well_code} — {well.well_name}
                  <Typography component="span" display="block" color="text.secondary" fontSize={10.5} fontWeight={600}>
                    {well.block_code} · {well.rig_code}
                  </Typography>
                </th>
              ))}
              <th className="sticky-total" rowSpan={2}>
                Grand total
                <Typography component="span" display="block" color="text.secondary" fontSize={9.8} fontWeight={700}>
                  {costOnly ? report.currency : `QTY · COST (${report.currency})`}
                </Typography>
              </th>
            </tr>
            <tr>
              {report.wells.map(well => (
                <Fragment key={`sub-${well.well_id}`}>
                  {well.sections.map(section => (
                    <th key={section.section_key} colSpan={costOnly ? 1 : 2}>
                      {section.section_code || 'WL'}
                      <Typography component="span" display="block" color="text.secondary" fontSize={10.2} fontWeight={600}>
                        {section.section_name} · {section.scope}
                      </Typography>
                      {!costOnly && (
                        <Typography component="span" display="block" color="text.secondary" fontSize={9.8} fontWeight={700}>
                          QTY · COST ({report.currency})
                        </Typography>
                      )}
                    </th>
                  ))}
                  <th colSpan={costOnly ? 1 : 2}>
                    Well total
                    {!costOnly && (
                      <Typography component="span" display="block" color="text.secondary" fontSize={9.8} fontWeight={700}>
                        QTY · COST
                      </Typography>
                    )}
                  </th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.rows.map((row, index) => {
              const lookup = cellMap(row.item_id)
              const band = bandAt(index)
              const previousBand = index === 0 ? null : bandAt(index - 1)
              return (
                <Fragment key={row.item_id}>
                  {band && band !== previousBand && (
                    <tr data-band="true">
                      <th colSpan={999}>{band}</th>
                    </tr>
                  )}
                  <tr>
                    <th>
                      <Typography fontWeight={800} fontSize={12}>{row.item_name}</Typography>
                      <Typography color="text.secondary" fontSize={10.8} fontWeight={600}>
                        {row.item_code}{row.uom ? ` · ${row.uom}` : ''}{row.manufacturer ? ` · ${row.manufacturer}` : ''}
                      </Typography>
                      {row.subcategory && <Typography color="text.secondary" fontSize={10.5}>{row.subcategory}{row.detail ? ` · ${row.detail}` : ''}</Typography>}
                      {!row.subcategory && row.detail && <Typography color="text.secondary" fontSize={10.5}>{row.detail}</Typography>}
                    </th>
                    {report.wells.map(well => (
                      <Fragment key={`${row.item_id}-${well.well_id}`}>
                        {well.sections.map(section => {
                          const cell = lookup(well.well_id, section.section_key)
                          return (
                            <Fragment key={section.section_key}>
                              {!costOnly && <td>{formatQuantity(cell.quantity)}</td>}
                              <td>{formatMoney(cell.amount, report.currency)}</td>
                            </Fragment>
                          )
                        })}
                        {(() => {
                          const total = lookup(well.well_id)
                          return (
                            <Fragment>
                              {!costOnly && <td data-total>{formatQuantity(total.quantity)}</td>}
                              <td data-total>{formatMoney(total.amount, report.currency)}</td>
                            </Fragment>
                          )
                        })()}
                      </Fragment>
                    ))}
                    {!costOnly && <td className="sticky-total" data-total>{formatQuantity(row.quantity_total)}</td>}
                    <td className="sticky-total" data-total>{formatMoney(row.amount_total, report.currency)}</td>
                  </tr>
                </Fragment>
              )
            })}
            <tr data-total="true">
              <th>Grand total{costOnly ? '' : ` (${report.currency})`}</th>
              {report.wells.map(well => {
                const total = totalFor(well.well_id)
                return (
                  <Fragment key={`grand-${well.well_id}`}>
                    {well.sections.map(section => <td key={section.section_key} colSpan={costOnly ? 1 : 2} />)}
                    {!costOnly && <td>{formatQuantity(total?.quantity)}</td>}
                    <td>{formatMoney(total?.amount, report.currency)}</td>
                  </Fragment>
                )
              })}
              {!costOnly && <td className="sticky-total">{formatQuantity(report.grand_quantity)}</td>}
              <td className="sticky-total">{formatMoney(report.grand_amount, report.currency)}</td>
            </tr>
          </tbody>
        </Box>
      )}
      {!costOnly && (
        <Typography color="text.secondary" fontSize={11} mt={1}>
          Quantities use each item's own unit of measure (shown in the row header); costs are in {report.currency}.
        </Typography>
      )}
    </Paper>
  )
}
