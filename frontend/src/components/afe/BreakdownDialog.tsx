import { Button, Table, TableBody, TableCell, TableHead, TableRow, Typography, Box } from '@mui/material'
import { PanelDialog } from '../Common'
import { amountText, type AfeComponent } from '../../lib/afe'

// Shows how a line is built up: one row per charge, and one per section share for well-wide day rates.
export function BreakdownDialog({ open, title, currency, components, warnings, onClose }: {
  open: boolean
  title: string
  currency: string
  components: AfeComponent[]
  warnings: string[]
  onClose: () => void
}) {
  return <PanelDialog
    open={open}
    title={title}
    subtitle="Each row is a priced component. Well-wide day rates are split across sections by planned days."
    onClose={onClose}
    maxWidth="lg"
    footer={<Button onClick={onClose} color="inherit">Cancel</Button>}
  >
    {warnings.length > 0 && <Box mb={1.5}>
      {warnings.map(warning => <Typography key={warning} fontSize={12.5} color="warning.main">• {warning}</Typography>)}
    </Box>}
    {components.length === 0
      ? <Typography fontSize={13} color="text.secondary">No priced components for this line yet.</Typography>
      : <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Charge</TableCell>
            <TableCell>Section</TableCell>
            <TableCell>Phase</TableCell>
            <TableCell align="right">Quantity</TableCell>
            <TableCell align="right">Rate</TableCell>
            <TableCell align="right">Amount</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {components.map((component, index) => <TableRow key={`${component.category}-${component.section_label}-${index}`}>
            <TableCell>
              <Typography fontSize={12.5} fontWeight={700}>{component.category}</Typography>
              <Typography fontSize={11.5} color="text.secondary">{component.description}</Typography>
            </TableCell>
            <TableCell>{component.section_label || '—'}</TableCell>
            <TableCell>{component.phase_label || '—'}</TableCell>
            <TableCell align="right">{component.quantity ? `${Number(component.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${component.unit}` : component.unit}</TableCell>
            <TableCell align="right">{component.rate ? amountText(component.rate) : '—'}</TableCell>
            <TableCell align="right">{amountText(component.amount, currency)}</TableCell>
          </TableRow>)}
        </TableBody>
      </Table>}
  </PanelDialog>
}
