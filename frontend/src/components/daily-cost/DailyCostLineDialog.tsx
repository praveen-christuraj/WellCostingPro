import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Divider, MenuItem, TextField, Typography } from '@mui/material'
import { FormDialog } from '../Common'
import {
  DAILY_CHARGE_CATEGORIES, DAILY_CHARGING_BASES, DAILY_CLASSIFICATIONS, DAILY_CONSUMABLE_CATEGORIES,
  DAILY_ONE_TIME_CATEGORIES, dailyMoney, type ChargingBasis, type ChargeCategory, type ConsumableCategory,
  type ConsumableKind, type CostClassification, type DailyCostBaseline, type DailyCostCatalogueOption,
  type DailyCostConsumableInput, type DailyCostLineBase, type DailyCostReference, type DailyCostServiceInput,
  type DailyCostTangibleInput, type DailyQuantityUnit,
} from '../../lib/dailyCost'

export type DailyCostLineKind = 'service' | 'consumable' | 'tangible'
export type EditableDailyCostLine = DailyCostServiceInput | DailyCostConsumableInput | DailyCostTangibleInput

type Props = {
  open: boolean
  kind: DailyCostLineKind | null
  initialLine: EditableDailyCostLine | null
  baseline: DailyCostBaseline
  reference: DailyCostReference
  wellId: string
  onClose: () => void
  onSave: (line: EditableDailyCostLine) => void
}

const KIND_BY_CATEGORY: Record<ConsumableCategory, ConsumableKind> = {
  'Mud Chemicals': 'mud_chemical', 'Cement Additives': 'cement_additive', Fuel: 'fuel', 'Drill Bits': 'drill_bit',
}
const CATEGORY_BY_KIND: Record<ConsumableKind, ConsumableCategory> = {
  mud_chemical: 'Mud Chemicals', cement_additive: 'Cement Additives', fuel: 'Fuel', drill_bit: 'Drill Bits',
}
const isService = (line: EditableDailyCostLine): line is DailyCostServiceInput => 'service_id' in line
const isConsumable = (line: EditableDailyCostLine): line is DailyCostConsumableInput => 'item_kind' in line

function baseDefaults(reference: DailyCostReference, baseline: DailyCostBaseline): DailyCostLineBase {
  const section = baseline.sections[0]
  return {
    id: null,
    activity_id: reference.activities[0]?.id ?? '',
    hole_section_id: section?.hole_section_id ?? null,
    phase_id: section?.phases[0]?.phase_id ?? null,
    sub_activity_id: null,
    classification: 'Planned',
    vendor_id: null,
    party_name: '',
    quantity: '1',
    currency: baseline.standard_currency,
    override_rate: null,
    override_reason: '',
    remarks: '',
  }
}

function initialFor(
  kind: DailyCostLineKind,
  reference: DailyCostReference,
  baseline: DailyCostBaseline,
): EditableDailyCostLine {
  const base = baseDefaults(reference, baseline)
  if (kind === 'service') {
    const rate = baseline.service_rates[0]
    const service = reference.services.find(item => item.id === rate?.service_id) ?? reference.services[0]
    const basis = rate?.charging_basis ?? 'Day Rate'
    const category = (rate?.charge_category || 'Operation') as ChargeCategory
    const unit: DailyQuantityUnit = basis === 'Per Service Rate' ? 'service'
      : basis === 'Per Section Rate' ? 'section' : DAILY_ONE_TIME_CATEGORIES.includes(category) ? 'unit' : 'days'
    return {
      ...base,
      service_id: service?.id ?? rate?.service_id ?? '',
      baseline_service_rate_id: rate?.id ?? null,
      charging_basis: basis,
      charge_category: category,
      quantity_unit: unit,
      vendor_id: service?.vendor_id ?? null,
      party_name: service?.vendor_name ?? '',
      currency: rate?.currency ?? baseline.standard_currency,
      hole_section_id: rate?.hole_section_id ?? base.hole_section_id,
      phase_id: rate?.phase_id ?? base.phase_id,
    }
  }
  if (kind === 'tangible') {
    const item = reference.catalogue_items.find(option => option.item_kind === 'tangible')
    const snapshot = baseline.catalogue_rates.find(option => option.item_kind === 'tangible' && option.id === item?.id)
    return {
      ...base,
      tangible_id: item?.id ?? '',
      currency: snapshot?.currency || item?.currency || baseline.standard_currency,
    }
  }
  const category: ConsumableCategory = 'Mud Chemicals'
  const item = reference.catalogue_items.find(option => option.item_kind === KIND_BY_CATEGORY[category])
  const snapshot = baseline.catalogue_rates.find(option => option.item_kind === item?.item_kind && option.id === item?.id)
  return {
    ...base,
    category,
    item_kind: KIND_BY_CATEGORY[category],
    item_id: item?.id ?? '',
    currency: snapshot?.currency || item?.currency || baseline.standard_currency,
  }
}

function optionsForKind(
  kind: ConsumableKind | 'tangible',
  reference: DailyCostReference,
  baseline: DailyCostBaseline,
  initialId: string | null,
): DailyCostCatalogueOption[] {
  const active = reference.catalogue_items.filter(item => item.item_kind === kind)
  const snapshots = baseline.catalogue_rates.filter(item => item.item_kind === kind)
  const merged = new Map<string, DailyCostCatalogueOption>()
  for (const snapshot of snapshots) merged.set(snapshot.id, snapshot)
  for (const item of active) if (!merged.has(item.id)) merged.set(item.id, item)
  if (initialId && !merged.has(initialId)) {
    merged.set(initialId, {
      id: initialId, item_kind: kind, category: kind === 'tangible' ? 'Tangibles' : CATEGORY_BY_KIND[kind],
      item_code: 'Existing item', item_name: 'Existing saved item', description: '', uom: 'unit',
      captured_rate: '0', currency: '', revision_number: 0, effective_date: null, display_name: 'Existing saved item',
    })
  }
  return [...merged.values()].sort((a, b) => a.item_code.localeCompare(b.item_code))
}

function itemSnapshot(
  item: DailyCostCatalogueOption | undefined,
  baseline: DailyCostBaseline,
): DailyCostCatalogueOption | undefined {
  if (!item) return undefined
  return baseline.catalogue_rates.find(rate => rate.item_kind === item.item_kind && rate.id === item.id) ?? item
}

export function DailyCostLineDialog({ open, kind, initialLine, baseline, reference, wellId, onClose, onSave }: Props) {
  const [form, setForm] = useState<EditableDailyCostLine | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || !kind) return
    setForm(initialLine ?? initialFor(kind, reference, baseline))
    setError('')
    setSaving(false)
  }, [open, kind, initialLine, reference, baseline])

  const selectedRate = useMemo(() => {
    if (!form || !isService(form) || !form.baseline_service_rate_id) return undefined
    return baseline.service_rates.find(rate => rate.id === form.baseline_service_rate_id)
  }, [form, baseline.service_rates])
  const sections = baseline.sections
  const selectedSection = sections.find(section => section.hole_section_id === form?.hole_section_id)
  const eligibleSubActivities = reference.sub_activities.filter(item => item.well_id === wellId && item.activity_id === form?.activity_id)

  const catalogKind = form && isConsumable(form) ? form.item_kind : 'tangible'
  const initialCatalogId = form && isConsumable(form) ? form.item_id : form && !isService(form) ? form.tangible_id : null
  const catalogueOptions = kind === 'service' || !form
    ? [] : optionsForKind(catalogKind, reference, baseline, initialCatalogId)
  const selectedCatalog = catalogueOptions.find(item => item.id === initialCatalogId)
  const selectedSnapshot = itemSnapshot(selectedCatalog, baseline)
  const catalogHasSnapshot = Boolean(selectedSnapshot && baseline.catalogue_rates.some(
    item => item.item_kind === selectedSnapshot.item_kind && item.id === selectedSnapshot.id,
  ))

  if (!open || !kind || !form) return null

  const update = (patch: Record<string, unknown>) => {
    setForm(current => current ? { ...current, ...patch } as EditableDailyCostLine : current)
    setError('')
  }
  const updateActivity = (activityId: string) => {
    const nextSub = eligibleSubActivities.some(item => item.id === form.sub_activity_id && item.activity_id === activityId)
      ? form.sub_activity_id : null
    update({ activity_id: activityId, sub_activity_id: nextSub })
  }
  const updateService = (serviceId: string) => {
    if (!isService(form)) return
    const candidates = baseline.service_rates.filter(rate => rate.service_id === serviceId)
    const rate = candidates[0]
    const service = reference.services.find(item => item.id === serviceId)
    const basis = rate?.charging_basis ?? form.charging_basis ?? 'Day Rate'
    const category = (rate?.charge_category || form.charge_category || 'Operation') as ChargeCategory
    const quantityUnit: DailyQuantityUnit = basis === 'Per Service Rate' ? 'service'
      : basis === 'Per Section Rate' ? 'section'
        : DAILY_ONE_TIME_CATEGORIES.includes(category) ? 'unit' : 'days'
    update({
      service_id: serviceId, baseline_service_rate_id: rate?.id ?? null, charging_basis: basis,
      charge_category: category, quantity_unit: quantityUnit,
      vendor_id: service?.vendor_id ?? form.vendor_id, party_name: service?.vendor_name ?? form.party_name,
      currency: rate?.currency || form.currency || baseline.standard_currency,
      hole_section_id: rate?.hole_section_id ?? form.hole_section_id,
      phase_id: rate?.phase_id ?? form.phase_id,
    })
  }
  const updateRate = (rateId: string) => {
    if (!isService(form)) return
    if (!rateId) {
      update({ baseline_service_rate_id: null })
      return
    }
    const rate = baseline.service_rates.find(item => item.id === rateId)
    if (!rate) return
    const category = (rate.charge_category || 'Operation') as ChargeCategory
    const quantityUnit: DailyQuantityUnit = rate.charging_basis === 'Per Service Rate' ? 'service'
      : rate.charging_basis === 'Per Section Rate' ? 'section'
        : DAILY_ONE_TIME_CATEGORIES.includes(category) ? 'unit' : 'days'
    update({
      service_id: rate.service_id, baseline_service_rate_id: rate.id, charging_basis: rate.charging_basis,
      charge_category: category, quantity_unit: quantityUnit, currency: rate.currency,
      hole_section_id: rate.hole_section_id ?? form.hole_section_id,
      phase_id: rate.phase_id ?? form.phase_id,
    })
  }
  const updateClassification = (classification: CostClassification) => {
    if (!isService(form)) {
      update({ classification })
      return
    }
    if (classification === 'Planned' && !form.baseline_service_rate_id) {
      const first = baseline.service_rates.find(rate => rate.service_id === form.service_id)
      if (first) {
        const category = (first.charge_category || 'Operation') as ChargeCategory
        update({ classification, baseline_service_rate_id: first.id, charging_basis: first.charging_basis,
          charge_category: category, currency: first.currency })
        return
      }
    }
    update({ classification })
  }

  const validate = (): string => {
    if (!form.activity_id) return 'Select a Master Data Activity.'
    if (!form.quantity || Number(form.quantity) <= 0) return 'Quantity must be greater than zero.'
    if (form.classification !== 'Planned' && !form.vendor_id && !form.party_name.trim()) return 'UPA and NPT lines need a responsible vendor or party.'
    if (form.override_rate !== null && (!form.override_rate || Number(form.override_rate) < 0)) return 'Enter a valid daily override rate.'
    if (form.override_rate !== null && form.override_reason.trim().length < 3) return 'Explain the rate override (at least 3 characters).'
    if (isService(form)) {
      if (!form.service_id) return 'Select a service.'
      if (form.classification === 'Planned' && !form.baseline_service_rate_id) return 'Choose a saved AFE service rate for planned work.'
      if (form.classification !== 'Planned' && !form.baseline_service_rate_id && form.override_rate === null) return 'Enter a manual rate for an unplanned service.'
      if (!form.charging_basis) return 'Choose the service charging basis.'
      if (!form.currency) return 'The rate needs a currency included in the locked AFE currency setup.'
      if (form.quantity_unit === 'hours' && Number(form.quantity) > 24) return 'For a daily line, hours cannot exceed 24; enter days instead.'
      if (form.charging_basis !== 'Day Rate' && !form.hole_section_id) return 'Choose a hole section for this charging basis.'
    } else if (isConsumable(form)) {
      if (!form.item_id) return 'Select a consumable item.'
      if (!form.hole_section_id) return 'Choose a hole section for actual consumable use.'
      if (!form.currency) return 'The item rate needs a currency included in the locked AFE currency setup.'
      if (!catalogHasSnapshot && form.override_rate === null) return 'This item was added after tracking began. Enter and justify its daily rate.'
    } else {
      if (!form.tangible_id) return 'Select a tangible.'
      if (!form.currency) return 'The item rate needs a currency included in the locked AFE currency setup.'
      if (!catalogHasSnapshot && form.override_rate === null) return 'This item was added after tracking began. Enter and justify its daily rate.'
    }
    if (!baseline.exchange_rates[form.currency]) return `${form.currency || 'This item'} has no conversion factor in the locked AFE currency setup. Select a supported currency or ask an AFE administrator to correct the estimate before tracking.`
    return ''
  }
  const submit = () => {
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setSaving(true)
    try {
      const prepared = { ...form, id: form.id || null,
        hole_section_id: form.hole_section_id || null, phase_id: form.phase_id || null,
        sub_activity_id: form.sub_activity_id || null, vendor_id: form.vendor_id || null,
        party_name: form.party_name.trim(), override_reason: form.override_rate === null ? '' : form.override_reason.trim(),
      } as EditableDailyCostLine
      onSave(prepared)
    } finally {
      setSaving(false)
    }
  }

  const title = `${form.id ? 'Edit' : 'Add'} ${kind === 'service' ? 'service' : kind === 'consumable' ? 'consumable usage' : 'tangible'}`
  const sectionLabel = (section: typeof sections[number]) => `${section.section_code} · ${section.section_name}`

  return <FormDialog open title={title} subtitle="Daily actuals are priced from the AFE and rate snapshots locked when tracking began. Overrides are recorded with their reason." onClose={onClose} onSubmit={submit} busy={saving} submitLabel={form.id ? 'Save line' : 'Add line'} maxWidth="md">
    <Box display="grid" gap={1.8}>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField select required label="Classification" value={form.classification} onChange={event => updateClassification(event.target.value as CostClassification)}>
          {DAILY_CLASSIFICATIONS.map(value => <MenuItem key={value} value={value}>{value === 'UPA' ? 'UPA · Unplanned Activity' : value === 'NPT' ? 'NPT · Non-Productive Time' : 'Planned'}</MenuItem>)}
        </TextField>
        <TextField select required label="Master Data Activity" value={form.activity_id} onChange={event => updateActivity(event.target.value)}>
          {reference.activities.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}
        </TextField>
      </Box>

      {kind === 'service' && isService(form) && <>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.2fr .8fr' } }}>
          <TextField select required label="Service" value={form.service_id} onChange={event => updateService(event.target.value)}>
            {reference.services.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}
          </TextField>
          <TextField select label="Locked AFE rate" value={form.baseline_service_rate_id ?? ''} onChange={event => updateRate(event.target.value)}>
            {form.classification !== 'Planned' && <MenuItem value="">Manual UPA / NPT rate</MenuItem>}
            {baseline.service_rates.filter(rate => rate.service_id === form.service_id).map(rate => <MenuItem key={rate.id} value={rate.id}>{rate.display_name}</MenuItem>)}
          </TextField>
        </Box>
        {form.baseline_service_rate_id && selectedRate
          ? <Alert severity="info" sx={{ py: 0 }}>
              Locked AFE rate: {selectedRate.charging_basis}{selectedRate.charge_category ? ` · ${selectedRate.charge_category}` : ''} · {dailyMoney(selectedRate.unit_rate, selectedRate.currency)}. Later Master Data changes do not affect this value.
            </Alert>
          : form.classification !== 'Planned' && <Alert severity="warning" sx={{ py: 0 }}>Manual UPA/NPT pricing requires a daily rate and a written reason.</Alert>}
        {!form.baseline_service_rate_id && form.classification !== 'Planned' && <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
          <TextField select label="Charging basis" value={form.charging_basis ?? 'Day Rate'} onChange={event => update({ charging_basis: event.target.value as ChargingBasis })}>
            {DAILY_CHARGING_BASES.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          {form.charging_basis === 'Day Rate' && <TextField select label="Charge category" value={form.charge_category} onChange={event => {
            const category = event.target.value as ChargeCategory
            update({ charge_category: category, quantity_unit: DAILY_ONE_TIME_CATEGORIES.includes(category) ? 'unit' : 'days' })
          }}>
            {DAILY_CHARGE_CATEGORIES.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>}
        </Box>}
      </>}

      {kind === 'consumable' && isConsumable(form) && <>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
          <TextField select required label="Consumable category" value={form.category} onChange={event => {
            const category = event.target.value as ConsumableCategory
            const nextKind = KIND_BY_CATEGORY[category]
            const first = optionsForKind(nextKind, reference, baseline, null)[0]
            const snapshot = itemSnapshot(first, baseline)
            update({ category, item_kind: nextKind, item_id: first?.id ?? '', currency: snapshot?.currency || baseline.standard_currency })
          }}>
            {DAILY_CONSUMABLE_CATEGORIES.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
          </TextField>
          <TextField select required label="Catalogue item" value={form.item_id} onChange={event => {
            const item = catalogueOptions.find(option => option.id === event.target.value)
            const snapshot = itemSnapshot(item, baseline)
            update({ item_id: event.target.value, currency: snapshot?.currency || baseline.standard_currency })
          }}>
            {catalogueOptions.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name} · {item.uom || 'unit'}</MenuItem>)}
          </TextField>
        </Box>
        {selectedSnapshot && catalogHasSnapshot
          ? <Alert severity="info" sx={{ py: 0 }}>
              Locked catalogue rate: {dailyMoney(selectedSnapshot.captured_rate, selectedSnapshot.currency)} / {selectedSnapshot.uom || 'unit'} · revision {selectedSnapshot.revision_number || 'baseline'}{selectedSnapshot.effective_date ? ` · effective ${selectedSnapshot.effective_date}` : ''}. Actuals still reconcile to the {form.category} AFE allowance.
            </Alert>
          : <Alert severity="warning" sx={{ py: 0 }}>No rate was present in the well snapshot. Enter a daily override with a reason; the actual will still reconcile against any AFE category allowance.</Alert>}
      </>}

      {kind === 'tangible' && !isService(form) && !isConsumable(form) && <>
        <TextField select required label="Tangible" value={form.tangible_id} onChange={event => {
          const item = catalogueOptions.find(option => option.id === event.target.value)
          const snapshot = itemSnapshot(item, baseline)
          update({ tangible_id: event.target.value, currency: snapshot?.currency || baseline.standard_currency })
        }}>
          {catalogueOptions.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name} · {item.uom || 'unit'}</MenuItem>)}
        </TextField>
        {selectedSnapshot && catalogHasSnapshot
          ? <Alert severity="info" sx={{ py: 0 }}>Locked catalogue rate: {dailyMoney(selectedSnapshot.captured_rate, selectedSnapshot.currency)} / {selectedSnapshot.uom || 'unit'} · revision {selectedSnapshot.revision_number || 'baseline'}.</Alert>
          : <Alert severity="warning" sx={{ py: 0 }}>No rate was present in the well snapshot. Enter a daily override with a reason.</Alert>}
      </>}

      <Divider/>
      <Typography fontSize={12} fontWeight={800} letterSpacing={.5} color="text.secondary">ACTIVITY, SCOPE &amp; RESPONSIBILITY</Typography>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField select label="Hole section" value={form.hole_section_id ?? ''} disabled={Boolean(selectedRate?.hole_section_id)} onChange={event => {
          const sectionId = event.target.value || null
          const section = sections.find(item => item.hole_section_id === sectionId)
          const phaseId = section?.phases.some(phase => phase.phase_id === form.phase_id) ? form.phase_id : section?.phases[0]?.phase_id ?? null
          update({ hole_section_id: sectionId, phase_id: phaseId, sub_activity_id: null })
        }}>
          <MenuItem value="">No hole section</MenuItem>
          {sections.map(section => <MenuItem key={section.hole_section_id} value={section.hole_section_id}>{sectionLabel(section)}</MenuItem>)}
        </TextField>
        <TextField select label="Phase" value={form.phase_id ?? ''} disabled={!selectedSection || Boolean(selectedRate?.phase_id)} onChange={event => update({ phase_id: event.target.value || null })}>
          <MenuItem value="">No phase</MenuItem>
          {selectedSection?.phases.map(phase => <MenuItem key={phase.phase_id} value={phase.phase_id}>{phase.phase_code} · {phase.phase_name}</MenuItem>)}
        </TextField>
        <TextField select label="Well-configured Sub Activity" value={form.sub_activity_id ?? ''} onChange={event => {
          const sub = eligibleSubActivities.find(item => item.id === event.target.value)
          update({ sub_activity_id: event.target.value || null, party_name: !form.party_name && sub ? sub.responsible_party : form.party_name })
        }}>
          <MenuItem value="">None selected</MenuItem>
          {eligibleSubActivities.map(item => <MenuItem key={item.id} value={item.id}>{item.sub_activity_code} · {item.sub_activity_name}</MenuItem>)}
        </TextField>
        <TextField select label="Responsible vendor" value={form.vendor_id ?? ''} onChange={event => {
          const vendor = reference.vendors.find(item => item.id === event.target.value)
          update({ vendor_id: event.target.value || null, party_name: vendor?.vendor_name ?? form.party_name })
        }}>
          <MenuItem value="">No vendor selected</MenuItem>
          {reference.vendors.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}
        </TextField>
        <TextField label="Party / responsible team" value={form.party_name} onChange={event => update({ party_name: event.target.value })} inputProps={{ maxLength: 200 }} helperText={form.classification === 'Planned' ? 'Optional unless no vendor is assigned.' : 'Required for UPA/NPT if no vendor is selected.'}/>
        <TextField select required label="Currency" value={form.currency} disabled={isService(form) ? Boolean(form.baseline_service_rate_id) : catalogHasSnapshot} onChange={event => update({ currency: event.target.value })}>
          {Object.keys(baseline.exchange_rates).sort().map(currency => <MenuItem key={currency} value={currency}>{currency}{currency === baseline.standard_currency ? ' · AFE standard' : ''}</MenuItem>)}
        </TextField>
      {form.currency && !baseline.exchange_rates[form.currency] && <Alert severity="error">{form.currency} has no exchange rate in this locked AFE. The daily cost cannot be converted for comparison.</Alert>}
      </Box>

      {isService(form) && <>
        <Divider/>
        <Typography fontSize={12} fontWeight={800} letterSpacing={.5} color="text.secondary">CHARGED QUANTITY &amp; RATE</Typography>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.2fr .8fr' } }}>
          <TextField label={DAILY_ONE_TIME_CATEGORIES.includes(form.charge_category) ? 'Recorded quantity' : 'Quantity'} type="number" required value={form.quantity} onChange={event => update({ quantity: event.target.value })} inputProps={{ min: 0.0001, step: 'any' }} helperText={DAILY_ONE_TIME_CATEGORIES.includes(form.charge_category) ? 'One-time Day Rate: the locked unit rate is charged once; quantity is retained as an operational record.' : undefined}/>
          <TextField select label="Quantity unit" value={form.quantity_unit} disabled={form.charging_basis !== 'Day Rate' || DAILY_ONE_TIME_CATEGORIES.includes(form.charge_category)} onChange={event => update({ quantity_unit: event.target.value as DailyQuantityUnit })}>
            {(form.charging_basis === 'Day Rate'
              ? DAILY_ONE_TIME_CATEGORIES.includes(form.charge_category) ? ['unit'] : ['days', 'hours']
              : form.charging_basis === 'Per Service Rate' ? ['service'] : ['section']
            ).map(unit => <MenuItem key={unit} value={unit}>{unit}</MenuItem>)}
          </TextField>
          {form.baseline_service_rate_id && selectedRate && <TextField label="Captured AFE rate" value={dailyMoney(selectedRate.unit_rate, selectedRate.currency)} InputProps={{ readOnly: true }}/>}
        </Box>
      </>}
      {!isService(form) && <>
        <Divider/>
        <Typography fontSize={12} fontWeight={800} letterSpacing={.5} color="text.secondary">ACTUAL USAGE &amp; RATE</Typography>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.2fr .8fr' } }}>
          <TextField label={`Actual quantity${selectedSnapshot?.uom ? ` (${selectedSnapshot.uom})` : ''}`} type="number" required value={form.quantity} onChange={event => update({ quantity: event.target.value })} inputProps={{ min: 0.0001, step: 'any' }}/>
          <TextField label="Captured rate" value={catalogHasSnapshot && selectedSnapshot ? `${dailyMoney(selectedSnapshot.captured_rate, selectedSnapshot.currency)} / ${selectedSnapshot.uom || 'unit'}` : 'Manual rate required'} InputProps={{ readOnly: true }}/>
        </Box>
      </>}

      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
        <TextField label="Daily unit-rate override (optional)" type="number" value={form.override_rate ?? ''} onChange={event => update({ override_rate: event.target.value === '' ? null : event.target.value })} inputProps={{ min: 0, step: 'any' }} helperText="Overrides only this daily line; the locked AFE/catalogue rate remains unchanged."/>
        <TextField label="Override reason" value={form.override_reason} onChange={event => update({ override_reason: event.target.value })} disabled={form.override_rate === null} inputProps={{ maxLength: 500 }} helperText={form.override_rate === null ? 'Required when an override rate is entered.' : `${form.override_reason.trim().length}/500 characters`}/>
      </Box>
      <TextField label="Line remarks" value={form.remarks} onChange={event => update({ remarks: event.target.value })} multiline minRows={2} inputProps={{ maxLength: 500 }}/>
      {error && <Alert severity="error">{error}</Alert>}
    </Box>
  </FormDialog>
}
