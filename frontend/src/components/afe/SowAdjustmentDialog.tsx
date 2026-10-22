import { useEffect, useMemo, useRef, useState } from 'react'
import { AddRounded, DeleteOutlineRounded, EditOutlined } from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Divider, MenuItem, Paper, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { ErrorMessage, FormDialog, PanelDialog, Tag } from '../Common'
import { useAuth } from '../../context/AuthContext'
import { api } from '../../lib/api'
import {
  amountText, estimateToInput,
  type Afe, type AfeEstimate, type AfeReference, type ConsumableLineInput, type ConsumableLineOut,
  type ServiceLineInput, type ServiceLineOut, type TangibleLineInput, type TangibleLineOut,
} from '../../lib/afe'
import { ConsumableLineDialog } from './ConsumableLineDialog'
import { ServiceLineDialog } from './ServiceLineDialog'
import { TangibleLineDialog } from './TangibleLineDialog'
import {
  SOW_CHANGE_LABEL, SOW_CHANGE_TONE, SOW_STATUS_LABEL, SOW_STATUS_TONE, adjustmentDeltaText,
  approveAfeAdjustment, createAfeAdjustment, listAfeAdjustments, pairSowLines, previewAfeAdjustment,
  updateAfeAdjustment, voidAfeAdjustment,
  type AfeSowAdjustment, type AfeSowAdjustmentInput, type AfeSowAdjustmentPreview,
  type LineChange, type PairedSowLine, type SowConsumableLineInput, type SowServiceLineInput,
  type SowTangibleLineInput,
} from '../../lib/sowAdjustment'

type EditorState = { kind: 'service' | 'consumable' | 'tangible'; key: string | null } | null
type Decision = { adjustment: AfeSowAdjustment; action: 'approve' | 'void' } | null

type ModuleLines = {
  services: SowServiceLineInput[]
  consumables: SowConsumableLineInput[]
  tangibles: SowTangibleLineInput[]
}

// The revised entry keeps `pair_key` on every line so the saved revision links
// each entry to the entered value it replaces. Seeded lines carry the before
// keys (`sv0`, `cs0`, …); lines the user adds get a fresh unique key.
function toSowLines(estimate: AfeEstimate): ModuleLines {
  const base = estimateToInput(estimate)
  return {
    services: base.services.map((line, index) => ({ ...line, pair_key: `sv${index}` })),
    consumables: base.consumables.map((line, index) => ({ ...line, pair_key: `cs${index}` })),
    tangibles: base.tangibles.map((line, index) => ({ ...line, pair_key: `tg${index}` })),
  }
}

function serviceOutToInput(line: ServiceLineOut): SowServiceLineInput {
  return {
    pair_key: line.client_key ?? null,
    client_key: line.client_key ?? '',
    service_id: line.service_id,
    charging_basis: line.charging_basis,
    hole_section_id: line.hole_section_id,
    phase_id: line.phase_id,
    currency: line.currency,
    service_amount: line.service_amount,
    remarks: line.remarks,
    rates: line.rates.map(rate => ({ category: rate.category, unit_rate: rate.unit_rate })),
    charges: line.charges.map(charge => ({ category: charge.category, quantity: charge.quantity, quantity_unit: charge.quantity_unit })),
    section_rates: line.section_rates.map(rate => ({ hole_section_id: rate.hole_section_id, phase_id: rate.phase_id, amount: rate.amount })),
  }
}

function consumableOutToInput(line: ConsumableLineOut): SowConsumableLineInput {
  return {
    pair_key: line.client_key ?? null,
    client_key: line.client_key ?? '',
    category: line.category,
    hole_section_id: line.hole_section_id,
    phase_id: line.phase_id,
    drill_bit_id: line.drill_bit_id,
    quantity: line.quantity,
    override_rate: line.override_rate,
    estimated_amount: line.estimated_amount,
    currency: line.currency,
    remarks: line.remarks,
  }
}

function tangibleOutToInput(line: TangibleLineOut): SowTangibleLineInput {
  return {
    pair_key: line.client_key ?? null,
    client_key: line.client_key ?? '',
    tangible_id: line.tangible_id,
    quantity: line.quantity,
    override_rate: line.override_rate,
    remarks: line.remarks,
  }
}

// Baseline of the entered values, keyed by pair key: every edited row reads
// against what it replaces ('new value against the entered value').
type BaselineEntry = { amount: string; remarks: string }
type BaselineMaps = {
  services: Map<string, BaselineEntry>
  consumables: Map<string, BaselineEntry>
  tangibles: Map<string, BaselineEntry>
}

function baselineFromEstimate(estimate: AfeEstimate): BaselineMaps {
  const entry = (line: { amount: string | number; remarks: string }): BaselineEntry =>
    ({ amount: String(line.amount ?? '0'), remarks: line.remarks ?? '' })
  return {
    services: new Map(estimate.services.map(line => [line.client_key ?? '', entry(line)])),
    consumables: new Map(estimate.consumables.map(line => [line.client_key ?? '', entry(line)])),
    tangibles: new Map(estimate.tangibles.map(line => [line.client_key ?? '', entry(line)])),
  }
}

function baselineFromBundle(adjustment: AfeSowAdjustment): BaselineMaps {
  const entry = (line: { amount: string | number; remarks: string }): BaselineEntry =>
    ({ amount: String(line.amount ?? '0'), remarks: line.remarks ?? '' })
  return {
    services: new Map((adjustment.before?.services ?? []).map(line => [line.client_key ?? '', entry(line)])),
    consumables: new Map((adjustment.before?.consumables ?? []).map(line => [line.client_key ?? '', entry(line)])),
    tangibles: new Map((adjustment.before?.tangibles ?? []).map(line => [line.client_key ?? '', entry(line)])),
  }
}

const emptyBaseline = (): BaselineMaps => ({
  services: new Map(), consumables: new Map(), tangibles: new Map(),
})

export function SowAdjustmentDialog({ open, afe, onClose, onChanged }: {
  open: boolean
  afe: Afe
  onClose: () => void
  onChanged: (updated: Afe) => void
}) {
  const { can } = useAuth()
  const canAdjust = can('afe:sow-adjust')
  const canDecide = can('afe:sow-approve')
  const keyCounter = useRef(0)
  const nextPairKey = () => `new-${Date.now().toString(36)}-${++keyCounter.current}`

  const [adjustments, setAdjustments] = useState<AfeSowAdjustment[]>([])
  const [estimate, setEstimate] = useState<AfeEstimate | null>(null)
  const [reference, setReference] = useState<AfeReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [lines, setLines] = useState<ModuleLines>(emptyAll())
  const [baseline, setBaseline] = useState<BaselineMaps>(emptyBaseline())
  const [standardCurrency, setStandardCurrency] = useState('')
  const [exchangeRates, setExchangeRates] = useState<{ currency_code: string; rate: string }[]>([])
  const [reason, setReason] = useState('')
  const [sowSummary, setSowSummary] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [editor, setEditor] = useState<EditorState>(null)

  const [preview, setPreview] = useState<AfeSowAdjustmentPreview | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const [decision, setDecision] = useState<Decision>(null)
  const [remarks, setRemarks] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [deciding, setDeciding] = useState(false)

  const estimateReady = afe.estimate_saved_at != null && !afe.conversion_pending && afe.total_cost != null
  const openDraft = adjustments.find(item => item.status === 'draft' && item.id !== editingId) ?? null

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [estimateResult, referenceResult, rows] = await Promise.all([
        api<AfeEstimate>(`/afe/afes/${afe.id}/estimate`),
        api<AfeReference>('/afe/reference'),
        listAfeAdjustments(afe.id),
      ])
      setEstimate(estimateResult)
      setReference(referenceResult)
      setAdjustments(rows)
      if (!editingId) seedFromEstimate(estimateResult)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'SOW adjustments could not be loaded')
    } finally {
      setLoading(false)
    }
  }

  const seedFromEstimate = (estimateResult: AfeEstimate) => {
    setLines(toSowLines(estimateResult))
    setBaseline(baselineFromEstimate(estimateResult))
    setStandardCurrency(estimateResult.summary.currency.standard_currency)
    setExchangeRates(estimateResult.summary.currency.exchange_rates.map(rate => ({ currency_code: rate.currency_code, rate: rate.rate })))
  }

  const seedFromDraft = (adjustment: AfeSowAdjustment) => {
    if (!adjustment.after) return
    setLines({
      services: adjustment.after.services.map(serviceOutToInput),
      consumables: adjustment.after.consumables.map(consumableOutToInput),
      tangibles: adjustment.after.tangibles.map(tangibleOutToInput),
    })
    setBaseline(baselineFromBundle(adjustment))
    setStandardCurrency(adjustment.standard_currency)
    setExchangeRates(adjustment.after.summary.currency.exchange_rates.map(rate => ({ currency_code: rate.currency_code, rate: rate.rate })))
    setReason(adjustment.reason)
    setSowSummary(adjustment.sow_summary)
    setEditingId(adjustment.id)
    setFormError('')
  }

  useEffect(() => {
    if (!open) return
    setReason('')
    setSowSummary('')
    setEditingId(null)
    setFormError('')
    setPreview(null)
    setPreviewError('')
    setExpanded(null)
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, afe.id])

  const refreshAfe = async () => {
    try {
      onChanged(await api<Afe>(`/afe/afes/${afe.id}`))
    } catch {
      // The list already shows the new revision; the header refresh is best-effort.
    }
  }

  // ---- line CRUD through the same entry dialogs as the AFE estimate ----

  const upsertService = (line: ServiceLineInput) => setLines(current => {
    const existing = current.services.find(row => row.client_key === line.client_key)
    const incomingPair = (line as Partial<SowServiceLineInput>).pair_key
    const tagged: SowServiceLineInput = {
      ...line,
      pair_key: existing?.pair_key ?? incomingPair ?? nextPairKey(),
    }
    return existing
      ? { ...current, services: current.services.map(row => row.client_key === line.client_key ? tagged : row) }
      : { ...current, services: [...current.services, tagged] }
  })

  const upsertConsumables = (incoming: ConsumableLineInput[]) => setLines(current => {
    let rowsOut = current.consumables
    for (const line of incoming) {
      const existing = rowsOut.find(row => row.client_key === line.client_key)
      const incomingPair = (line as Partial<SowConsumableLineInput>).pair_key
      const tagged: SowConsumableLineInput = {
        ...line,
        pair_key: existing?.pair_key ?? incomingPair ?? nextPairKey(),
      }
      rowsOut = existing
        ? rowsOut.map(row => row.client_key === line.client_key ? tagged : row)
        : [...rowsOut, tagged]
    }
    return { ...current, consumables: rowsOut }
  })

  const upsertTangibles = (incoming: TangibleLineInput[]) => setLines(current => {
    let rowsOut = current.tangibles
    for (const line of incoming) {
      const existing = rowsOut.find(row => row.client_key === line.client_key)
      const incomingPair = (line as Partial<SowTangibleLineInput>).pair_key
      const tagged: SowTangibleLineInput = {
        ...line,
        pair_key: existing?.pair_key ?? incomingPair ?? nextPairKey(),
      }
      rowsOut = existing
        ? rowsOut.map(row => row.client_key === line.client_key ? tagged : row)
        : [...rowsOut, tagged]
    }
    return { ...current, tangibles: rowsOut }
  })

  const removeLine = (kind: 'services' | 'consumables' | 'tangibles', clientKey: string) =>
    setLines(current => ({ ...current, [kind]: current[kind].filter(row => row.client_key !== clientKey) }))

  // ---- derived totals: price the revised entry exactly like the save ----

  const previewSignature = useMemo(() => JSON.stringify({
    lines, standardCurrency, exchangeRates,
  }), [lines, standardCurrency, exchangeRates])

  useEffect(() => {
    if (!open || !estimateReady) return
    let current = true
    const timer = window.setTimeout(() => {
      previewAfeAdjustment(afe.id, {
        reason: 'preview',
        services: lines.services,
        consumables: lines.consumables,
        tangibles: lines.tangibles,
        standard_currency: standardCurrency,
        exchange_rates: exchangeRates,
      }).then(result => {
        if (!current) return
        setPreview(result)
        setPreviewError('')
      }).catch(caught => {
        if (!current) return
        setPreview(null)
        setPreviewError(caught instanceof Error ? caught.message : 'The revised estimate could not be priced')
      })
    }, 700)
    return () => { current = false; window.clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewSignature, open, afe.id])

  const previewLine = (kind: 'services' | 'consumables' | 'tangibles', clientKey: string) => {
    const rows = preview?.[kind] as (ServiceLineOut | ConsumableLineOut | TangibleLineOut)[] | undefined
    return rows?.find(row => (row.client_key ?? row.id) === clientKey) ?? null
  }

  const changeFor = (kind: keyof BaselineMaps, pairKey: string | null, previewAmount: string | null): LineChange => {
    const before = baseline[kind].get(pairKey ?? '')
    if (!before) return 'added'
    const afterAmount = previewAmount ?? before.amount
    return Number(before.amount) !== Number(afterAmount) ? 'modified' : 'kept'
  }

  const submitForm = async () => {
    setSaving(true)
    setFormError('')
    try {
      const payload: AfeSowAdjustmentInput = {
        reason: reason.trim(),
        sow_summary: sowSummary.trim(),
        standard_currency: standardCurrency,
        exchange_rates: exchangeRates,
        services: lines.services,
        consumables: lines.consumables,
        tangibles: lines.tangibles,
      }
      if (editingId) await updateAfeAdjustment(editingId, payload)
      else await createAfeAdjustment(afe.id, payload)
      setEditingId(null)
      setReason('')
      setSowSummary('')
      setPreview(null)
      await load()
      await refreshAfe()
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'The adjustment could not be saved')
    } finally {
      setSaving(false)
    }
  }

  const submitDecision = async () => {
    if (!decision) return
    setDeciding(true)
    setDecisionError('')
    try {
      if (decision.action === 'approve') await approveAfeAdjustment(decision.adjustment.id, remarks.trim())
      else await voidAfeAdjustment(decision.adjustment.id, remarks.trim())
      setDecision(null)
      setRemarks('')
      await load()
      await refreshAfe()
    } catch (caught) {
      setDecisionError(caught instanceof Error ? caught.message : 'The decision could not be recorded')
    } finally {
      setDeciding(false)
    }
  }

  const multiCurrency = Boolean(estimate?.summary.currency.multi_currency)
  const currencyBlocked = multiCurrency && (!standardCurrency || exchangeRates.some(rate => !rate.currency_code.trim() || !(Number(rate.rate) > 0)))

  const changeTag = (change: LineChange) => <Tag tone={SOW_CHANGE_TONE[change]}>{SOW_CHANGE_LABEL[change]}</Tag>

  const wasChip = (before: BaselineEntry | undefined, previewAmount: string | null, currency: string) => {
    if (!before) return <Typography component="span" fontSize={11} color="success.main" fontWeight={700}>New</Typography>
    const afterAmount = previewAmount ?? before.amount
    if (Number(before.amount) === Number(afterAmount)) return null
    return <Typography component="span" fontSize={11} color="warning.main" fontWeight={700}>was {amountText(before.amount, currency)}</Typography>
  }

  const revisionLineSummary = (adjustment: AfeSowAdjustment): string => {
    if (!adjustment.before || !adjustment.after) return 'Line detail unavailable'
    const parts: string[] = []
    for (const [kind, label] of [['service', 'service'], ['consumable', 'consumable'], ['tangible', 'tangible']] as const) {
      const before = kind === 'service' ? adjustment.before.services : kind === 'consumable' ? adjustment.before.consumables : adjustment.before.tangibles
      const after = kind === 'service' ? adjustment.after.services : kind === 'consumable' ? adjustment.after.consumables : adjustment.after.tangibles
      const paired = pairSowLines(kind, before, after)
      const added = paired.filter(row => row.change === 'added').length
      const removed = paired.filter(row => row.change === 'removed').length
      const modified = paired.filter(row => row.change === 'modified').length
      const text = [added ? `${added} new` : '', modified ? `${modified} modified` : '', removed ? `${removed} removed` : ''].filter(Boolean).join(', ')
      if (text) parts.push(`${text} ${label}${added + modified + removed === 1 ? '' : 's'}`)
    }
    return parts.join(' · ') || 'No line changes'
  }

  const revisionDiff = (adjustment: AfeSowAdjustment): PairedSowLine[] => {
    if (!adjustment.before || !adjustment.after) return []
    return [
      ...pairSowLines('service', adjustment.before.services, adjustment.after.services),
      ...pairSowLines('consumable', adjustment.before.consumables, adjustment.after.consumables),
      ...pairSowLines('tangible', adjustment.before.tangibles, adjustment.after.tangibles),
    ].filter(row => row.change !== 'kept')
  }

  const currency = standardCurrency || afe.standard_currency

  return <>
    <PanelDialog
      open={open && decision == null}
      title={`SOW adjustments · ${afe.afe_code}`}
      subtitle="Revisions are entered through the same modules as the AFE estimate — services with rate cards, consumables and tangibles. Every value works against the entered one, new lines can be added and the adjusted totals derive from the revised lines. The saved estimate itself never changes."
      onClose={onClose}
      maxWidth="lg"
      footer={<Button variant="outlined" onClick={onClose}>Close</Button>}
    >
      <Box display="grid" gap={2}>
        <Alert severity="info">
          Original approved total {amountText(afe.total_cost, afe.standard_currency)}
          {' '}· Services {amountText(afe.services_total)} · Consumables {amountText(afe.consumables_total)} · Tangibles {amountText(afe.tangibles_total)}
          {afe.has_sow_adjustment && afe.adjusted_total != null && <> · Effective (Rev {afe.sow_revision}) {amountText(afe.adjusted_total, afe.standard_currency)}</>}
        </Alert>
        <ErrorMessage message={error}/>
        {loading
          ? <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
          : <>
            {!estimateReady && <Alert severity="warning">Save the estimate with all conversion rates before recording an adjustment — the original totals must be convertible.</Alert>}
            {canAdjust && estimateReady && <Box sx={{ p: 1.8, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
              <Typography fontWeight={800} fontSize={14} mb={.3}>{editingId ? 'Edit draft revision' : 'New adjustment draft'}</Typography>
              <Typography color="text.secondary" fontSize={12} mb={1.5}>
                {editingId
                  ? 'Only draft revisions can be edited. Approving a revision locks it.'
                  : openDraft
                    ? `Revision ${openDraft.revision_number} is still a draft. Approve or void it before starting another.`
                    : 'Prefilled with the saved estimate — change the values the scope change affects and add or remove lines.'}
              </Typography>
              <Box display="grid" gap={1.5}>
                <TextField label="Reason" required fullWidth value={reason} onChange={event => setReason(event.target.value)} inputProps={{ maxLength: 500 }} helperText="Why the scope changed — recorded permanently with the revision."/>
                <TextField label="Scope summary" fullWidth multiline minRows={2} value={sowSummary} onChange={event => setSowSummary(event.target.value)} inputProps={{ maxLength: 2000 }} helperText="Narrative of what was added or removed: services, consumables, tangibles, days."/>

                {multiCurrency && <Box sx={{ p: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
                  <Typography fontWeight={800} fontSize={12} mb={1}>Currency setup</Typography>
                  <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={1.2}>
                    <TextField select label="Standard currency" fullWidth size="small" value={standardCurrency} onChange={event => setStandardCurrency(event.target.value)}>
                      {reference?.currencies.map(option => <MenuItem key={option.code} value={option.code}>{option.code} — {option.name}</MenuItem>)}
                    </TextField>
                    <Box display="grid" gap={.8}>
                      {exchangeRates.map((rate, index) => <Box key={`${rate.currency_code}-${index}`} display="grid" gridTemplateColumns="1fr 1fr auto" gap={.8} alignItems="center">
                        <TextField size="small" label="Currency" value={rate.currency_code} slotProps={{ htmlInput: { maxLength: 10 } }}
                          onChange={event => setExchangeRates(rows => rows.map((row, i) => i === index ? { ...row, currency_code: event.target.value.toUpperCase() } : row))}/>
                        <TextField size="small" label={`Rate to ${standardCurrency}`} value={rate.rate} inputProps={{ inputMode: 'decimal' }}
                          onChange={event => setExchangeRates(rows => rows.map((row, i) => i === index ? { ...row, rate: event.target.value } : row))}/>
                        <Button color="error" size="small" aria-label="Remove rate" onClick={() => setExchangeRates(rows => rows.filter((_, i) => i !== index))}><DeleteOutlineRounded fontSize="small"/></Button>
                      </Box>)}
                    </Box>
                  </Box>
                </Box>}

                <ModuleTable
                  title="Services"
                  hint="Same entry module as the AFE estimate: charging basis, per-category rates, day/hour quantities and per-section rates."
                  count={lines.services.length}
                  onAdd={() => setEditor({ kind: 'service', key: null })}
                  addLabel="Add service"
                >
                  {lines.services.map(line => {
                    const priced = previewLine('services', line.client_key) as ServiceLineOut | null
                    const change = changeFor('services', line.pair_key, priced ? String(priced.amount) : null)
                    const service = reference?.services.find(item => item.id === line.service_id)
                    return <TableRow key={line.client_key}>
                      <TableCell>
                        <Typography fontSize={12.5} fontWeight={700}>{service ? `${service.service_code} · ${service.service_name}` : 'Service'}</Typography>
                        <Box display="flex" gap={.8} alignItems="center" flexWrap="wrap" mt={.3}>
                          <Typography fontSize={11} color="text.secondary">{line.charging_basis}</Typography>
                          {change !== 'kept' && changeTag(change)}
                          {wasChip(baseline.services.get(line.pair_key ?? ''), priced ? String(priced.amount) : null, line.currency || currency)}
                        </Box>
                      </TableCell>
                      <TableCell align="right">
                        <Typography fontSize={12.5} fontWeight={700}>{priced ? amountText(priced.amount, line.currency || currency) : '—'}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Button size="small" startIcon={<EditOutlined fontSize="small"/>} onClick={() => setEditor({ kind: 'service', key: line.client_key })}>Edit</Button>
                        <Button size="small" color="error" aria-label="Remove service" onClick={() => removeLine('services', line.client_key)}><DeleteOutlineRounded fontSize="small"/></Button>
                      </TableCell>
                    </TableRow>
                  })}
                </ModuleTable>

                <ModuleTable
                  title="Consumables"
                  hint="Same entry module as the AFE estimate: drill bits priced at quantity × rate, mud chemicals, cement additives and fuel as lump sums per section/phase."
                  count={lines.consumables.length}
                  onAdd={() => setEditor({ kind: 'consumable', key: null })}
                  addLabel="Add consumable"
                >
                  {lines.consumables.map(line => {
                    const priced = previewLine('consumables', line.client_key) as ConsumableLineOut | null
                    const change = changeFor('consumables', line.pair_key, priced ? String(priced.amount) : null)
                    const bit = reference?.drill_bits.find(item => item.id === line.drill_bit_id)
                    return <TableRow key={line.client_key}>
                      <TableCell>
                        <Typography fontSize={12.5} fontWeight={700}>{line.category === 'Drill Bits' && bit ? `${bit.bit_code} · ${bit.bit_name}` : line.category}</Typography>
                        <Box display="flex" gap={.8} alignItems="center" flexWrap="wrap" mt={.3}>
                          <Typography fontSize={11} color="text.secondary">Qty {line.quantity}{priced?.effective_rate ? ` × ${amountText(priced.effective_rate, line.currency || currency)}` : ''}</Typography>
                          {change !== 'kept' && changeTag(change)}
                          {wasChip(baseline.consumables.get(line.pair_key ?? ''), priced ? String(priced.amount) : null, line.currency || currency)}
                        </Box>
                      </TableCell>
                      <TableCell align="right">
                        <Typography fontSize={12.5} fontWeight={700}>{priced ? amountText(priced.amount, line.currency || currency) : '—'}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Button size="small" startIcon={<EditOutlined fontSize="small"/>} onClick={() => setEditor({ kind: 'consumable', key: line.client_key })}>Edit</Button>
                        <Button size="small" color="error" aria-label="Remove consumable" onClick={() => removeLine('consumables', line.client_key)}><DeleteOutlineRounded fontSize="small"/></Button>
                      </TableCell>
                    </TableRow>
                  })}
                </ModuleTable>

                <ModuleTable
                  title="Tangibles"
                  hint="Same entry module as the AFE estimate: quantity × captured catalogue rate, with an optional rate override."
                  count={lines.tangibles.length}
                  onAdd={() => setEditor({ kind: 'tangible', key: null })}
                  addLabel="Add tangible"
                >
                  {lines.tangibles.map(line => {
                    const priced = previewLine('tangibles', line.client_key) as TangibleLineOut | null
                    const change = changeFor('tangibles', line.pair_key, priced ? String(priced.amount) : null)
                    const item = reference?.tangibles.find(entry => entry.id === line.tangible_id)
                    return <TableRow key={line.client_key}>
                      <TableCell>
                        <Typography fontSize={12.5} fontWeight={700}>{item ? `${item.tangible_code} · ${item.tangible_name}` : 'Tangible'}</Typography>
                        <Box display="flex" gap={.8} alignItems="center" flexWrap="wrap" mt={.3}>
                          <Typography fontSize={11} color="text.secondary">Qty {line.quantity}{priced?.effective_rate ? ` × ${amountText(priced.effective_rate, priced.currency || currency)}` : ''}</Typography>
                          {change !== 'kept' && changeTag(change)}
                          {wasChip(baseline.tangibles.get(line.pair_key ?? ''), priced ? String(priced.amount) : null, priced?.currency || currency)}
                        </Box>
                      </TableCell>
                      <TableCell align="right">
                        <Typography fontSize={12.5} fontWeight={700}>{priced ? amountText(priced.amount, priced.currency || currency) : '—'}</Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Button size="small" startIcon={<EditOutlined fontSize="small"/>} onClick={() => setEditor({ kind: 'tangible', key: line.client_key })}>Edit</Button>
                        <Button size="small" color="error" aria-label="Remove tangible" onClick={() => removeLine('tangibles', line.client_key)}><DeleteOutlineRounded fontSize="small"/></Button>
                      </TableCell>
                    </TableRow>
                  })}
                </ModuleTable>

                <Box sx={{ p: 1.3, border: '1px solid', borderColor: 'divider', borderRadius: 1.5, bgcolor: 'action.hover' }}>
                  <Typography fontWeight={800} fontSize={12.5} mb={.8}>Derived revised totals (server-priced, {currency})</Typography>
                  {previewError
                    ? <ErrorMessage message={previewError}/>
                    : <Box display="grid" gridTemplateColumns={{ xs: '1fr 1fr', sm: 'repeat(4, 1fr)' }} gap={1.2}>
                      <DerivedCell label="Services" value={preview ? amountText(preview.adjusted_services_total, preview.standard_currency) : '…'} was={amountText(afe.services_total, afe.standard_currency)}/>
                      <DerivedCell label="Consumables" value={preview ? amountText(preview.adjusted_consumables_total, preview.standard_currency) : '…'} was={amountText(afe.consumables_total, afe.standard_currency)}/>
                      <DerivedCell label="Tangibles" value={preview ? amountText(preview.adjusted_tangibles_total, preview.standard_currency) : '…'} was={amountText(afe.tangibles_total, afe.standard_currency)}/>
                      <DerivedCell label="Total" value={preview ? amountText(preview.adjusted_total, preview.standard_currency) : '…'} was={amountText(afe.total_cost, afe.standard_currency)}/>
                    </Box>}
                </Box>

                <ErrorMessage message={formError}/>
                <Box display="flex" gap={1} flexWrap="wrap">
                  <Button variant="contained" disabled={saving || reason.trim().length < 3 || currencyBlocked || (openDraft != null && editingId == null)} onClick={() => void submitForm()}>
                    {saving ? 'Saving…' : editingId ? 'Save draft' : 'Save draft revision'}
                  </Button>
                  {editingId && <Button color="inherit" disabled={saving} onClick={() => {
                    setEditingId(null)
                    setReason('')
                    setSowSummary('')
                    setFormError('')
                    if (estimate) seedFromEstimate(estimate)
                  }}>Cancel edit</Button>}
                </Box>
              </Box>
            </Box>}
            {adjustments.length === 0
              ? <Typography color="text.secondary" fontSize={13}>No adjustments recorded yet.</Typography>
              : adjustments.map(adjustment => <Box key={adjustment.id} sx={{ p: 1.8, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap">
                  <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                    <Typography fontWeight={800} fontSize={14}>Revision {adjustment.revision_number}</Typography>
                    <Tag tone={SOW_STATUS_TONE[adjustment.status]}>{SOW_STATUS_LABEL[adjustment.status]}</Tag>
                    <Typography fontSize={12} color="text.secondary">
                      {new Date(adjustment.created_at).toLocaleString()} by {adjustment.created_by || 'workspace user'}
                    </Typography>
                  </Box>
                  <Typography fontWeight={800} fontSize={14}>
                    {amountText(adjustment.adjusted_total, adjustment.standard_currency)}{' '}
                    <Typography component="span" fontSize={12.5} color={Number(adjustment.delta_total) < 0 ? 'success.main' : 'text.secondary'}>
                      ({adjustmentDeltaText(adjustment.delta_total, adjustment.standard_currency)})
                    </Typography>
                  </Typography>
                </Box>
                <Typography fontSize={12.5} mt={1}><strong>Reason:</strong> {adjustment.reason}</Typography>
                {adjustment.sow_summary && <Typography fontSize={12.5} mt={.4} color="text.secondary">{adjustment.sow_summary}</Typography>}
                <Typography fontSize={12} color="text.secondary" mt={.8}>
                  Services {amountText(adjustment.adjusted_services_total)} · Consumables {amountText(adjustment.adjusted_consumables_total)} · Tangibles {amountText(adjustment.adjusted_tangibles_total)}
                  {adjustment.original_total != null && <> · Original {amountText(adjustment.original_total, adjustment.standard_currency)}</>}
                  {' · '}{revisionLineSummary(adjustment)}
                </Typography>
                <Button size="small" sx={{ mt: .8 }} onClick={() => setExpanded(expanded === adjustment.id ? null : adjustment.id)}>
                  {expanded === adjustment.id ? 'Hide line changes' : 'Show line changes'}
                </Button>
                {expanded === adjustment.id && <Box mt={1.2} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, p: 1.2 }}>
                  {revisionDiff(adjustment).length === 0
                    ? <Typography fontSize={12} color="text.secondary">No line-level changes: only the narrative was recorded.</Typography>
                    : revisionDiff(adjustment).map(row => <Box key={`${adjustment.id}-${row.pair_key}`} display="flex" gap={1} alignItems="center" flexWrap="wrap" mb={.6}>
                      <Typography fontSize={12} fontWeight={700}>{row.label}</Typography>
                      {changeTag(row.change)}
                      <Typography fontSize={11.5} color="text.secondary">
                        {row.before_amount !== null && <>was {amountText(row.before_amount, adjustment.standard_currency)}</>}
                        {row.before_amount !== null && row.after_amount !== null && ' → '}
                        {row.after_amount !== null && <>{amountText(row.after_amount, adjustment.standard_currency)}</>}
                      </Typography>
                    </Box>)}
                </Box>}
                {adjustment.status !== 'draft' && <Typography fontSize={12} color="text.secondary" mt={.4}>
                  {adjustment.status === 'approved' ? 'Approved' : 'Voided'} by {adjustment.approved_by || 'workspace user'}
                  {adjustment.approved_at ? ` on ${new Date(adjustment.approved_at).toLocaleString()}` : ''}
                </Typography>}
                <Box display="flex" gap={1} mt={1.2} flexWrap="wrap">
                  {canAdjust && adjustment.status === 'draft' && <Button size="small" variant="outlined" onClick={() => seedFromDraft(adjustment)}>Edit draft</Button>}
                  {canDecide && adjustment.status === 'draft' && <Button size="small" variant="contained" onClick={() => { setDecision({ adjustment, action: 'approve' }); setRemarks(''); setDecisionError('') }}>Approve</Button>}
                  {canDecide && adjustment.status !== 'void' && <Button size="small" variant="outlined" color="error" onClick={() => { setDecision({ adjustment, action: 'void' }); setRemarks(''); setDecisionError('') }}>Void</Button>}
                </Box>
              </Box>)}
          </>}
      </Box>
    </PanelDialog>

    {estimate && reference && <>
      {editor?.kind === 'service' && <ServiceLineDialog
        open
        initial={editor.key ? lines.services.find(line => line.client_key === editor.key) ?? null : null}
        scope={estimate.well}
        reference={reference}
        onClose={() => setEditor(null)}
        onSave={line => { upsertService(line); setEditor(null) }}
      />}
      {editor?.kind === 'consumable' && <ConsumableLineDialog
        open
        initial={editor.key ? lines.consumables.find(line => line.client_key === editor.key) ?? null : null}
        scope={estimate.well}
        reference={reference}
        onClose={() => setEditor(null)}
        onSave={rows => { upsertConsumables(rows); setEditor(null) }}
      />}
      {editor?.kind === 'tangible' && <TangibleLineDialog
        open
        initial={editor.key ? lines.tangibles.find(line => line.client_key === editor.key) ?? null : null}
        reference={reference}
        onClose={() => setEditor(null)}
        onSave={rows => { upsertTangibles(rows); setEditor(null) }}
      />}
    </>}

    <FormDialog
      open={decision != null}
      title={decision?.action === 'approve' ? `Approve revision ${decision.adjustment.revision_number}?` : `Void revision ${decision?.adjustment.revision_number}?`}
      subtitle={decision?.action === 'approve'
        ? 'The revised totals become the effective AFE budget for cost comparisons. Earlier approved revisions are superseded.'
        : 'Voiding removes this revision from cost comparisons. The previously approved revision (if any) becomes effective again.'}
      onClose={() => { if (!deciding) setDecision(null) }}
      onSubmit={() => void submitDecision()}
      busy={deciding}
      submitDisabled={remarks.trim().length < 3}
      submitLabel={decision?.action === 'approve' ? 'Approve revision' : 'Void revision'}
      danger={decision?.action === 'void'}
    >
      <Box display="grid" gap={1.7} pt={.5}>
        <TextField label="Approval remarks" required fullWidth multiline minRows={3} value={remarks} onChange={event => setRemarks(event.target.value)} inputProps={{ maxLength: 1000 }} helperText="At least 3 characters. Recorded permanently with the revision."/>
        <ErrorMessage message={decisionError}/>
      </Box>
    </FormDialog>
  </>
}

function emptyAll(): ModuleLines {
  return { services: [], consumables: [], tangibles: [] }
}

function ModuleTable({ title, hint, count, onAdd, addLabel, children }: {
  title: string
  hint: string
  count: number
  onAdd: () => void
  addLabel: string
  children: React.ReactNode
}) {
  return <Paper variant="outlined" sx={{ borderRadius: 1.5, overflow: 'hidden' }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap" sx={{ px: 1.5, py: 1.1, bgcolor: 'action.hover' }}>
      <Box>
        <Typography fontWeight={800} fontSize={12.5}>{title} ({count})</Typography>
        <Typography fontSize={11} color="text.secondary" mt={.15}>{hint}</Typography>
      </Box>
      <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={onAdd}>{addLabel}</Button>
    </Box>
    <Divider/>
    {count === 0
      ? <Typography color="text.secondary" fontSize={12} sx={{ px: 1.5, py: 1.6, textAlign: 'center' }}>No lines — add one to revise this module.</Typography>
      : <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: 800, fontSize: 11 }}>LINE · AGAINST ENTERED VALUE</TableCell>
            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>REVISED AMOUNT</TableCell>
            <TableCell align="right" sx={{ fontWeight: 800, fontSize: 11 }}>ACTIONS</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>{children}</TableBody>
      </Table>}
  </Paper>
}

function DerivedCell({ label, value, was }: { label: string; value: string; was: string }) {
  return <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, px: 1.2, py: .9, bgcolor: 'background.paper' }}>
    <Typography fontSize={10} fontWeight={800} color="text.secondary" textTransform="uppercase">{label}</Typography>
    <Typography fontSize={14} fontWeight={800} mt={.2}>{value}</Typography>
    <Typography fontSize={10.5} color="text.secondary" mt={.15}>entered {was}</Typography>
  </Box>
}
