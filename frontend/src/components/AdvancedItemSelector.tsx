import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { FilterAltOffRounded, FilterAltRounded } from '@mui/icons-material'
import { FormDialog, Tag } from './Common'

/** One selectable row in the advanced selector (a mud chemical, a tangible, …). */
export type AdvancedSelectorItem = {
  id: string
  code: string
  name: string
  description?: string
  /** Secondary line under the item name (manufacturer, category, …). */
  details?: string
  uom?: string
  /** Unit rate as a numeric string; already formatted for display by `rateText`. */
  rate: string
  currency?: string
}

export type AdvancedSelectorSelection = { item: AdvancedSelectorItem; quantity: string }

type Props = {
  open: boolean
  title: string
  subtitle?: string
  /** Singular noun used in messages: "mud chemical", "tangible". */
  itemNoun: string
  items: AdvancedSelectorItem[]
  onClose: () => void
  /** Return an error message to keep the selector open, or null when the rows were accepted. */
  onAdd: (rows: AdvancedSelectorSelection[]) => string | null
  /** Formats one unit rate (for example with the currency code). */
  rateText?: (item: AdvancedSelectorItem) => string
  /** Items already on the sheet; shown as a tag so they are not added twice by mistake. */
  existingIds?: string[]
  /** Tangible estimates accept a zero quantity; usage quantities must be greater than zero. */
  allowZeroQuantity?: boolean
  footerNote?: string
  quantityLabel?: string
  /** Select catalogue references without asking for a quantity (costing-set editor). */
  selectionOnly?: boolean
  /** Show every supplied item and add only rows whose optional quantity was entered. */
  quantityEntryOnly?: boolean
  initialSelectedIds?: string[]
}

const QUANTITY_PATTERN = /^\d+(?:\.\d{1,10})?$/

/**
 * Multi-item picker used by the daily cost register and the AFE cost estimate.
 *
 * Every selected item becomes its own line. Selections survive filtering, so the
 * "Show selected only" toggle is a review tool: it hides everything that is not
 * already ticked while search stays available on top of it.
 */
export function AdvancedSelectorDialog({
  open,
  title,
  subtitle,
  itemNoun,
  items,
  onClose,
  onAdd,
  rateText,
  existingIds = [],
  allowZeroQuantity = false,
  footerNote,
  quantityLabel = 'Usage quantity',
  selectionOnly = false,
  quantityEntryOnly = false,
  initialSelectedIds = [],
}: Props) {
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [search, setSearch] = useState('')
  const [showSelectedOnly, setShowSelectedOnly] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setSelected(Object.fromEntries(initialSelectedIds.map(id => [id, true])))
    setQuantities({})
    setSearch('')
    setShowSelectedOnly(false)
    setSubmitted(false)
    setError('')
  }, [open, title]) // initial selection is intentionally captured when the dialog opens

  const existing = useMemo(() => new Set(existingIds), [existingIds])
  const validQuantity = (value: string) => {
    if (!QUANTITY_PATTERN.test(value.trim())) return false
    return allowZeroQuantity ? Number(value) >= 0 : Number(value) > 0
  }

  const matching = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return items
    return items.filter(item =>
      `${item.code} ${item.name} ${item.description ?? ''} ${item.details ?? ''}`.toLowerCase().includes(query),
    )
  }, [items, search])
  const visible = showSelectedOnly && !quantityEntryOnly ? matching.filter(item => selected[item.id]) : matching
  const enteredCount = items.filter(item => (quantities[item.id] ?? '').trim()).length
  const selectedCount = quantityEntryOnly ? enteredCount : items.filter(item => selected[item.id]).length
  const allVisibleSelected = visible.length > 0 && visible.every(item => selected[item.id])
  const someVisibleSelected = visible.some(item => selected[item.id]) && !allVisibleSelected
  const quantityHelper = allowZeroQuantity ? 'Zero or greater.' : 'Required, greater than zero.'

  const toggle = (id: string, checked: boolean) => {
    setSelected(current => ({ ...current, [id]: checked }))
    if (!checked) setQuantities(current => ({ ...current, [id]: '' }))
    setError('')
  }

  const submit = () => {
    setSubmitted(true)
    const rows = quantityEntryOnly
      ? items.filter(item => (quantities[item.id] ?? '').trim()).map(item => ({ item, quantity: quantities[item.id] }))
      : items.filter(item => selected[item.id]).map(item => ({ item, quantity: quantities[item.id] ?? '' }))
    if (!rows.length) {
      setError(`Select at least one ${itemNoun}.`)
      return
    }
    const missing = selectionOnly ? undefined : rows.find(row => !validQuantity(row.quantity))
    if (missing) {
      setShowSelectedOnly(true)
      setError(`Enter the ${quantityLabel.toLowerCase()} for ${missing.item.code} · ${missing.item.name}.`)
      return
    }
    const addError = onAdd(rows)
    if (addError) {
      setError(addError)
      return
    }
    setError('')
    onClose()
  }

  return <FormDialog
    open={open}
    title={title}
    subtitle={subtitle}
    onClose={onClose}
    onSubmit={submit}
    submitLabel={selectionOnly ? `Use selected items (${selectedCount})` : quantityEntryOnly ? `Add entered items (${enteredCount})` : `Add selected items (${selectedCount})`}
    submitDisabled={selectedCount === 0}
    maxWidth="lg"
  >
    <Box display="grid" gap={1.5}>
      <Box display="flex" gap={1} flexWrap="wrap" alignItems="flex-start">
        <TextField
          size="small"
          label="Search items"
          value={search}
          onChange={event => setSearch(event.target.value)}
          sx={{ flex: '1 1 260px' }}
          helperText={`${items.length} available · ${quantityEntryOnly ? `${enteredCount} with quantity` : `${selectedCount} selected`} · ${visible.length} shown`}
        />
        {!quantityEntryOnly && <Button
          variant={showSelectedOnly ? 'contained' : 'outlined'}
          size="small"
          startIcon={showSelectedOnly ? <FilterAltOffRounded/> : <FilterAltRounded/>}
          aria-pressed={showSelectedOnly}
          onClick={() => setShowSelectedOnly(current => !current)}
          sx={{ mt: .5 }}
        >
          {showSelectedOnly ? 'Show all items' : `Show selected only${selectedCount ? ` (${selectedCount})` : ''}`}
        </Button>}
      </Box>

      <Box sx={{ overflowX: 'auto', border: '1px solid', borderColor: 'divider' }}>
        <Table size="small" aria-label={`${title} item list`} sx={{ minWidth: selectionOnly ? 520 : 720 }}>
          <TableHead><TableRow>
            {!quantityEntryOnly && <TableCell padding="checkbox">
              <Checkbox
                checked={allVisibleSelected}
                indeterminate={someVisibleSelected}
                disabled={!visible.length}
                inputProps={{ 'aria-label': showSelectedOnly ? 'Clear every shown selection' : 'Select all shown items' }}
                onChange={event => {
                  const checked = event.target.checked
                  setSelected(current => ({ ...current, ...Object.fromEntries(visible.map(item => [item.id, checked])) }))
                  if (!checked) {
                    setQuantities(current => ({
                      ...current,
                      ...Object.fromEntries(visible.map(item => [item.id, ''])),
                    }))
                  }
                  setError('')
                }}
              />
            </TableCell>}
            <TableCell>Item</TableCell>
            {!selectionOnly && <TableCell>UOM</TableCell>}
            {!selectionOnly && <TableCell align="right">Unit price</TableCell>}
            {!selectionOnly && <TableCell>{quantityLabel}</TableCell>}
          </TableRow></TableHead>
          <TableBody>
            {visible.map(item => {
              const checked = quantityEntryOnly ? Boolean((quantities[item.id] ?? '').trim()) : Boolean(selected[item.id])
              const invalid = submitted && checked && !selectionOnly && !validQuantity(quantities[item.id] ?? '')
              return <TableRow key={item.id} selected={checked}>
                {!quantityEntryOnly && <TableCell padding="checkbox">
                  <Checkbox
                    checked={checked}
                    inputProps={{ 'aria-label': `Select ${item.code} · ${item.name}` }}
                    onChange={event => toggle(item.id, event.target.checked)}
                  />
                </TableCell>}
                <TableCell>
                  <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                    <Typography fontSize={12.5} fontWeight={700}>{item.name}</Typography>
                    {existing.has(item.id) && <Tag tone="info">Already added</Tag>}
                  </Box>
                  <Typography fontSize={11} color="text.secondary">{item.code}</Typography>
                  {item.details && <Typography fontSize={11} color="text.secondary">{item.details}</Typography>}
                </TableCell>
                {!selectionOnly && <TableCell>{item.uom || 'unit'}</TableCell>}
                {!selectionOnly && <TableCell align="right" className="tnum">
                  {rateText ? rateText(item) : item.rate}
                </TableCell>}
                {!selectionOnly && <TableCell>
                  <TextField
                    size="small"
                    type="number"
                    label={`${quantityLabel} for ${item.name}`}
                    value={quantities[item.id] ?? ''}
                    disabled={!quantityEntryOnly && !checked}
                    required={!quantityEntryOnly && checked}
                    error={invalid}
                    onChange={event => {
                      setQuantities(current => ({ ...current, [item.id]: event.target.value }))
                      setError('')
                    }}
                    inputProps={{ min: allowZeroQuantity ? 0 : 0.0000000001, step: '0.0000000001' }}
                    helperText={invalid ? quantityHelper : quantityEntryOnly ? 'Leave empty to skip.' : ' '}
                  />
                </TableCell>}
              </TableRow>
            })}
            {!visible.length && <TableRow><TableCell colSpan={selectionOnly ? 2 : quantityEntryOnly ? 4 : 5}>
              <Typography color="text.secondary" textAlign="center" py={2}>
                {showSelectedOnly
                  ? (selectedCount
                    ? 'None of the selected items match the search.'
                    : 'No items selected yet. Choose “Show all items” to pick some.')
                  : 'No matching items.'}
              </Typography>
            </TableCell></TableRow>}
          </TableBody>
        </Table>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      {footerNote && <Typography color="text.secondary" fontSize={11.5}>{footerNote}</Typography>}
    </Box>
  </FormDialog>
}
