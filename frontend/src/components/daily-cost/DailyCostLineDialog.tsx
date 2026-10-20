import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Collapse,
  Divider,
  MenuItem,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import { AddRounded, DeleteOutlineRounded, TuneRounded } from '@mui/icons-material'
import { FormDialog, Tag } from '../Common'
import {
  DAILY_CONSUMABLE_CATEGORIES,
  OTHER_EXPENSE_MIN_REMARKS,
  OTHER_EXPENSE_TYPES,
  dailyMoney,
  deriveClassification,
  type ChargeCategory,
  type ChargingBasis,
  type ConsumableCategory,
  type ConsumableKind,
  type DailyCostBaseline,
  type DailyCostCatalogueOption,
  type DailyCostConsumableInput,
  type DailyCostOtherExpenseInput,
  type DailyCostReference,
  type DailyCostServiceInput,
  type DailyCostTangibleInput,
  type DailyQuantityUnit,
  type OtherExpenseType,
} from '../../lib/dailyCost'
import { formatDepthMeters, normalizeDepthUnit, type DepthUnit } from '../../lib/units'

export type DailyCostLineKind = 'service' | 'consumable' | 'tangible' | 'other'
export type EditableDailyCostLine =
  | DailyCostServiceInput
  | DailyCostConsumableInput
  | DailyCostTangibleInput
  | DailyCostOtherExpenseInput

type Props = {
  open: boolean
  kind: DailyCostLineKind | null
  initialLine: EditableDailyCostLine | null
  serviceLines: DailyCostServiceInput[]
  lineIndex: number | null
  baseline: DailyCostBaseline
  reference: DailyCostReference
  wellId: string
  onClose: () => void
  onSave: (lines: EditableDailyCostLine | EditableDailyCostLine[]) => void
}

const KIND_BY_CATEGORY: Record<ConsumableCategory, ConsumableKind> = {
  'Mud Chemicals': 'mud_chemical',
  'Cement Additives': 'cement_additive',
  Fuel: 'fuel',
  'Drill Bits': 'drill_bit',
}
const CATEGORY_BY_KIND: Record<ConsumableKind, ConsumableCategory> = {
  mud_chemical: 'Mud Chemicals',
  cement_additive: 'Cement Additives',
  fuel: 'Fuel',
  drill_bit: 'Drill Bits',
}

const isService = (line: EditableDailyCostLine): line is DailyCostServiceInput => 'service_id' in line
const isConsumable = (line: EditableDailyCostLine): line is DailyCostConsumableInput => 'item_kind' in line
const isOther = (line: EditableDailyCostLine): line is DailyCostOtherExpenseInput => 'expense_type' in line

type ServiceEntryRow = {
  cost_items?: { description: string; amount: string }[]
  id: string
  service_id: string
  baseline_service_rate_id: string | null
  charging_basis: ChargingBasis | null
  charge_category: ChargeCategory | null
  currency: string
  exchange_rate: string
  override_rate: string | null
  override_reason: string
  remarks: string
  customScope: boolean
  custom_hole_section_id: string | null
  custom_phase_id: string | null
  customQuantity: boolean
  custom_quantity: string
  custom_quantity_unit: DailyQuantityUnit
}

function defaultUsdRateForCurrency(currency: string, baseline: DailyCostBaseline): string {
  const code = (currency || '').trim().toUpperCase()
  if (!code || code === 'USD') return '1'
  if (baseline.standard_currency.toUpperCase() === 'USD' && baseline.exchange_rates[code]) {
    return baseline.exchange_rates[code]
  }
  return ''
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
      id: initialId,
      item_kind: kind,
      category: kind === 'tangible' ? 'Tangibles' : CATEGORY_BY_KIND[kind],
      item_code: 'Existing item',
      item_name: 'Existing saved item',
      description: '',
      uom: 'unit',
      captured_rate: '0',
      currency: '',
      revision_number: 0,
      effective_date: null,
      display_name: 'Existing saved item',
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

export function DailyCostLineDialog({
  open,
  kind,
  initialLine,
  serviceLines,
  lineIndex,
  baseline,
  reference,
  wellId,
  onClose,
  onSave,
}: Props) {
  // Common Criteria State
  const [commonActivityId, setCommonActivityId] = useState('')
  const [commonSubActivityId, setCommonSubActivityId] = useState<string | null>(null)
  const [commonHoleSectionId, setCommonHoleSectionId] = useState<string | null>(null)
  const [commonPhaseId, setCommonPhaseId] = useState<string | null>(null)
  const [commonActualDepth, setCommonActualDepth] = useState('')
  const [commonDepthUnit, setCommonDepthUnit] = useState<DepthUnit>('m')
  const [commonQuantity, setCommonQuantity] = useState('24')
  const [commonQuantityUnit, setCommonQuantityUnit] = useState<DailyQuantityUnit>('hours')
  const [commonVendorId, setCommonVendorId] = useState<string | null>(null)
  const [commonPartyName, setCommonPartyName] = useState('')

  // Service Rows under criteria
  const [serviceRows, setServiceRows] = useState<ServiceEntryRow[]>([])

  // Non-service line state (consumables, tangibles, other expenses)
  const [queuedLines, setQueuedLines] = useState<EditableDailyCostLine[]>([])
  const [nonServiceForm, setNonServiceForm] = useState<EditableDailyCostLine | null>(null)

  const [baselineState, setBaselineState] = useState<string>('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const currencyChoices = useMemo(() => {
    const merged = new Set<string>(['USD', baseline.standard_currency?.toUpperCase() || 'USD'])
    for (const c of reference.currencies || []) if (c) merged.add(c.toUpperCase())
    for (const c of Object.keys(baseline.exchange_rates || {})) if (c) merged.add(c.toUpperCase())
    return ['USD', ...[...merged].filter(c => c !== 'USD').sort()]
  }, [reference.currencies, baseline.standard_currency, baseline.exchange_rates])

  // Initialization
  useEffect(() => {
    if (!open || !kind) return

    const defaultSection = baseline.sections[0]
    const initialActivity = initialLine?.activity_id || reference.activities[0]?.id || ''
    const initialClassification = deriveClassification(reference.activities.find(a => a.id === initialActivity))
    const eligibleSubs = reference.sub_activities.filter(
      item => item.well_id === wellId && item.activity_id === initialActivity,
    )
    const initialSubId = initialLine?.sub_activity_id || eligibleSubs[0]?.id || null
    const initialSub = reference.sub_activities.find(s => s.id === initialSubId)

    setCommonActivityId(initialActivity)
    setCommonSubActivityId(initialSubId)
    setCommonHoleSectionId(initialLine ? initialLine.hole_section_id : defaultSection?.hole_section_id ?? null)
    setCommonPhaseId(initialLine ? initialLine.phase_id : defaultSection?.phases[0]?.phase_id ?? null)
    setCommonActualDepth(
      initialLine?.actual_depth !== null && initialLine?.actual_depth !== undefined
        ? String(initialLine.actual_depth)
        : '',
    )
    setCommonDepthUnit(normalizeDepthUnit(initialLine?.actual_depth_unit || 'm'))
    setBaselineState('')
    setQueuedLines([])

    if (initialClassification === 'Planned') {
      setCommonPartyName('Not Applicable')
      setCommonVendorId(null)
    } else {
      setCommonPartyName(initialLine?.party_name || initialSub?.responsible_party || '')
      setCommonVendorId(initialLine?.vendor_id || null)
    }

    if (kind === 'service') {
      if (initialLine && isService(initialLine)) {
        setCommonQuantity(initialLine.quantity)
        setCommonQuantityUnit(initialLine.quantity_unit)
        const cur = (initialLine.currency || baseline.standard_currency || 'USD').toUpperCase()
        setServiceRows([
          {
            cost_items: initialLine.cost_items ?? [],
            id: initialLine.id || 'service-0',
            service_id: initialLine.service_id,
            baseline_service_rate_id: initialLine.baseline_service_rate_id,
            charging_basis: initialLine.charging_basis,
            charge_category: initialLine.charge_category,
            currency: cur,
            exchange_rate: initialLine.exchange_rate || defaultUsdRateForCurrency(cur, baseline),
            override_rate: initialLine.override_rate,
            override_reason: initialLine.override_reason,
            remarks: initialLine.remarks,
            customScope: false,
            custom_hole_section_id: initialLine.hole_section_id,
            custom_phase_id: initialLine.phase_id,
            customQuantity: false,
            custom_quantity: initialLine.quantity,
            custom_quantity_unit: initialLine.quantity_unit,
          },
        ])
      } else {
        setCommonQuantity('24')
        setCommonQuantityUnit('hours')
        const firstRate = baseline.service_rates[0]
        const firstService = reference.services.find(s => s.id === firstRate?.service_id) || reference.services[0]
        const basis = (firstRate?.charging_basis || 'Day Rate') as ChargingBasis
        const category = (firstRate?.charge_category || 'Operation') as ChargeCategory
        const cur = (firstRate?.currency || baseline.standard_currency || 'USD').toUpperCase()
        setServiceRows([
          {
            id: 'service-0',
            service_id: firstService?.id || '',
            baseline_service_rate_id: firstRate?.id || null,
            charging_basis: basis,
            charge_category: category,
            currency: cur,
            exchange_rate: defaultUsdRateForCurrency(cur, baseline),
            override_rate: null,
            override_reason: '',
            remarks: '',
            customScope: false,
            custom_hole_section_id: defaultSection?.hole_section_id ?? null,
            custom_phase_id: defaultSection?.phases[0]?.phase_id ?? null,
            customQuantity: false,
            custom_quantity: '24',
            custom_quantity_unit: 'hours',
          },
        ])
      }
      setNonServiceForm(null)
    } else if (initialLine) {
      const cur = (initialLine.currency || baseline.standard_currency || 'USD').toUpperCase()
      setNonServiceForm({
        ...initialLine,
        currency: cur,
        exchange_rate: initialLine.exchange_rate || defaultUsdRateForCurrency(cur, baseline),
      })
    } else if (kind === 'other') {
      const expType = (reference.other_expense_types?.[0]?.code ?? OTHER_EXPENSE_TYPES[0].code) as OtherExpenseType
      const cur = 'USD'
      setNonServiceForm({
        id: null,
        activity_id: initialActivity,
        sub_activity_id: initialSubId,
        hole_section_id: defaultSection?.hole_section_id ?? null,
        phase_id: defaultSection?.phases[0]?.phase_id ?? null,
        vendor_id: null,
        party_name: initialClassification === 'Planned' ? 'Not Applicable' : initialSub?.responsible_party || '',
        quantity: '1',
        quantity_unit: 'unit',
        unit_rate: '',
        currency: cur,
        exchange_rate: defaultUsdRateForCurrency(cur, baseline),
        override_rate: null,
        override_reason: '',
        remarks: '',
        expense_type: expType,
        expense_description: '',
      })
    } else if (kind === 'tangible') {
      const item = reference.catalogue_items.find(option => option.item_kind === 'tangible')
      const snapshot = baseline.catalogue_rates.find(option => option.item_kind === 'tangible' && option.id === item?.id)
      const cur = (snapshot?.currency || item?.currency || baseline.standard_currency || 'USD').toUpperCase()
      setNonServiceForm({
        id: null,
        activity_id: initialActivity,
        sub_activity_id: initialSubId,
        hole_section_id: defaultSection?.hole_section_id ?? null,
        phase_id: defaultSection?.phases[0]?.phase_id ?? null,
        vendor_id: null,
        party_name: initialClassification === 'Planned' ? 'Not Applicable' : initialSub?.responsible_party || '',
        quantity: '1',
        currency: cur,
        exchange_rate: defaultUsdRateForCurrency(cur, baseline),
        override_rate: null,
        override_reason: '',
        remarks: '',
        tangible_id: item?.id ?? '',
      })
    } else {
      const cat: ConsumableCategory = 'Mud Chemicals'
      const item = reference.catalogue_items.find(option => option.item_kind === KIND_BY_CATEGORY[cat])
      const snapshot = baseline.catalogue_rates.find(option => option.item_kind === item?.item_kind && option.id === item?.id)
      const cur = (snapshot?.currency || item?.currency || baseline.standard_currency || 'USD').toUpperCase()
      setNonServiceForm({
        id: null,
        activity_id: initialActivity,
        sub_activity_id: initialSubId,
        hole_section_id: defaultSection?.hole_section_id ?? null,
        phase_id: defaultSection?.phases[0]?.phase_id ?? null,
        vendor_id: null,
        party_name: initialClassification === 'Planned' ? 'Not Applicable' : initialSub?.responsible_party || '',
        quantity: '1',
        currency: cur,
        exchange_rate: defaultUsdRateForCurrency(cur, baseline),
        override_rate: null,
        override_reason: '',
        remarks: '',
        category: cat,
        item_kind: KIND_BY_CATEGORY[cat],
        item_id: item?.id ?? '',
      })
    }

    setError('')
    setSubmitted(false)
    setSaving(false)
  }, [open, kind, initialLine, reference, baseline, wellId])

  useEffect(() => {
    if (open && baselineState === '') {
      setBaselineState(
        JSON.stringify({
          commonActivityId,
          commonSubActivityId,
          commonHoleSectionId,
          commonPhaseId,
          commonActualDepth,
          commonDepthUnit,
          commonQuantity,
          commonQuantityUnit,
          commonVendorId,
          commonPartyName,
          serviceRows,
          nonServiceForm,
        }),
      )
    }
  }, [
    open,
    baselineState,
    commonActivityId,
    commonSubActivityId,
    commonHoleSectionId,
    commonPhaseId,
    commonActualDepth,
    commonDepthUnit,
    commonQuantity,
    commonQuantityUnit,
    commonVendorId,
    commonPartyName,
    serviceRows,
    nonServiceForm,
  ])

  const currentState = JSON.stringify({
    commonActivityId,
    commonSubActivityId,
    commonHoleSectionId,
    commonPhaseId,
    commonActualDepth,
    commonDepthUnit,
    commonQuantity,
    commonQuantityUnit,
    commonVendorId,
    commonPartyName,
    serviceRows,
    nonServiceForm,
  })
  const dirty = queuedLines.length > 0 || (baselineState !== '' && currentState !== baselineState)

  const sections = baseline.sections
  const selectedCommonSection = sections.find(section => section.hole_section_id === commonHoleSectionId)
  const eligibleSubActivities = useMemo(
    () => reference.sub_activities.filter(item => item.well_id === wellId && item.activity_id === commonActivityId),
    [reference.sub_activities, wellId, commonActivityId],
  )
  const derivedClassification = deriveClassification(reference.activities.find(item => item.id === commonActivityId))

  if (!open || !kind) return null

  const handleActivityChange = (activityId: string) => {
    setCommonActivityId(activityId)
    const nextClassification = deriveClassification(reference.activities.find(item => item.id === activityId))
    const eligible = reference.sub_activities.filter(
      item => item.well_id === wellId && item.activity_id === activityId,
    )
    const nextSubId = eligible.some(item => item.id === commonSubActivityId) ? commonSubActivityId : eligible[0]?.id || null
    const nextSub = reference.sub_activities.find(item => item.id === nextSubId)
    setCommonSubActivityId(nextSubId)

    if (nextClassification === 'Planned') {
      setCommonPartyName('Not Applicable')
      setCommonVendorId(null)
    } else {
      setCommonPartyName(nextSub?.responsible_party || '')
    }

    if (nonServiceForm) {
      setNonServiceForm(prev => (prev ? {
        ...prev,
        activity_id: activityId,
        sub_activity_id: nextSubId,
        party_name: nextClassification === 'Planned' ? 'Not Applicable' : nextSub?.responsible_party || '',
        vendor_id: nextClassification === 'Planned' ? null : prev.vendor_id,
      } : null))
    }
  }

  const handleSubActivityChange = (subId: string | null) => {
    setCommonSubActivityId(subId)
    const sub = reference.sub_activities.find(item => item.id === subId)
    if (derivedClassification !== 'Planned' && sub) {
      setCommonPartyName(sub.responsible_party || '')
    }
    if (nonServiceForm) {
      setNonServiceForm(prev => (prev ? {
        ...prev,
        sub_activity_id: subId,
        party_name: derivedClassification === 'Planned' ? 'Not Applicable' : sub?.responsible_party || prev.party_name,
      } : null))
    }
  }

  const addServiceRow = () => {
    const defaultSection = baseline.sections[0]
    const cur = (baseline.standard_currency || 'USD').toUpperCase()
    setServiceRows(prev => [
      ...prev,
      {
        id: `service-${Date.now()}-${prev.length}`,
        service_id: '',
        baseline_service_rate_id: null,
        charging_basis: 'Day Rate',
        charge_category: 'Operation',
        currency: cur,
        exchange_rate: defaultUsdRateForCurrency(cur, baseline),
        override_rate: null,
        override_reason: '',
        remarks: '',
        customScope: false,
        custom_hole_section_id: defaultSection?.hole_section_id ?? null,
        custom_phase_id: defaultSection?.phases[0]?.phase_id ?? null,
        customQuantity: false,
        custom_quantity: commonQuantity,
        custom_quantity_unit: commonQuantityUnit,
      },
    ])
  }

  const updateServiceRow = (rowId: string, patch: Partial<ServiceEntryRow>) => {
    setServiceRows(prev => prev.map(row => {
      if (row.id !== rowId) return row
      const updated = { ...row, ...patch }
      if (patch.service_id && patch.service_id !== row.service_id) {
        const rate = baseline.service_rates.find(r => r.service_id === patch.service_id)
        if (rate) {
          updated.baseline_service_rate_id = rate.id
          updated.charging_basis = rate.charging_basis
          updated.charge_category = (rate.charge_category || 'Operation') as ChargeCategory
          updated.currency = rate.currency.toUpperCase()
          updated.exchange_rate = defaultUsdRateForCurrency(rate.currency, baseline)
        } else {
          updated.baseline_service_rate_id = null
        }
      }
      if (patch.currency && patch.currency !== row.currency && patch.exchange_rate === undefined) {
        updated.exchange_rate = defaultUsdRateForCurrency(patch.currency, baseline)
      }
      return updated
    }))
  }

  const removeServiceRow = (rowId: string) => {
    if (serviceRows.length <= 1) return
    setServiceRows(prev => prev.filter(r => r.id !== rowId))
  }

  const validate = (): string[] => {
    const problems: string[] = []

    if (!commonActivityId) problems.push('Select a Master Data Activity.')
    if (!commonSubActivityId) problems.push('Select a well sub activity configured for this well.')
    if (commonActualDepth.trim() !== '') {
      const depthVal = Number(commonActualDepth)
      if (!Number.isFinite(depthVal) || depthVal < 0) {
        problems.push('Enter a valid non-negative actual depth.')
      }
    }

    if (derivedClassification !== 'Planned' && !commonVendorId && !commonPartyName.trim()) {
      problems.push('UPA and NPT lines require a responsible vendor or party.')
    }

    if (kind === 'service') {
      if (!serviceRows.length) problems.push('Add at least one service.')

      const commonQtyNum = Number(commonQuantity)
      if (!commonQuantity || isNaN(commonQtyNum) || commonQtyNum <= 0) {
        problems.push('Common quantity must be greater than zero.')
      }
      if (commonQuantityUnit === 'hours' && commonQtyNum > 24) {
        problems.push('Hours cannot exceed 24 for a daily line; enter days instead.')
      }

      const duplicateCheck = new Set<string>()
      serviceRows.forEach((row, idx) => {
        const rowLabel = `Service #${idx + 1}`
        if ((row.cost_items ?? []).some(item => !item.description.trim() || item.amount === '' || !Number.isFinite(Number(item.amount)) || Number(item.amount) < 0)) problems.push(`${rowLabel}: Each cost item needs a description and a non-negative amount.`)
        if (!row.service_id) {
          problems.push(`${rowLabel}: Select a service from Master Data.`)
          return
        }

        const subId = commonSubActivityId || ''
        const dupKey = `${row.service_id}:${subId}`
        if (duplicateCheck.has(dupKey)) {
          const sName = reference.services.find(s => s.id === row.service_id)?.service_code || row.service_id
          problems.push(`${rowLabel} (${sName}): Cannot add the same service twice under the same sub activity.`)
        }
        duplicateCheck.add(dupKey)

        const existingDup = serviceLines.some(
          (sLine, sIdx) => sIdx !== lineIndex && sLine.service_id === row.service_id && (sLine.sub_activity_id || '') === subId,
        )
        if (existingDup) {
          const sName = reference.services.find(s => s.id === row.service_id)?.service_code || row.service_id
          problems.push(`${rowLabel} (${sName}): This service is already entered for this sub activity on this sheet.`)
        }

        if (derivedClassification === 'Planned' && !row.baseline_service_rate_id) {
          const sName = reference.services.find(s => s.id === row.service_id)?.service_code || row.service_id
          problems.push(`${rowLabel} (${sName}): Planned work requires a saved AFE rate. Select an AFE rate or use UPA/NPT Activity.`)
        }

        if (derivedClassification !== 'Planned' && !row.baseline_service_rate_id && row.override_rate === null) {
          const sName = reference.services.find(s => s.id === row.service_id)?.service_code || row.service_id
          problems.push(`${rowLabel} (${sName}): Unplanned service requires a manual override rate and reason.`)
        }

        if (row.override_rate !== null) {
          const ovNum = Number(row.override_rate)
          if (isNaN(ovNum) || ovNum < 0) problems.push(`${rowLabel}: Enter a valid daily override rate.`)
          if (row.override_reason.trim().length < 3) problems.push(`${rowLabel}: Explain the rate override (at least 3 characters).`)
        }

        if (row.customQuantity) {
          const custQtyNum = Number(row.custom_quantity)
          if (!row.custom_quantity || isNaN(custQtyNum) || custQtyNum <= 0) {
            problems.push(`${rowLabel}: Custom quantity must be greater than zero.`)
          }
          if (row.custom_quantity_unit === 'hours' && custQtyNum > 24) {
            problems.push(`${rowLabel}: Custom hours cannot exceed 24; enter days instead.`)
          }
        }

        const cur = (row.currency || 'USD').toUpperCase()
        if (cur !== 'USD') {
          const fxVal = Number(row.exchange_rate)
          if (!row.exchange_rate || !Number.isFinite(fxVal) || fxVal <= 0) {
            problems.push(`${rowLabel}: Enter the USD conversion rate (1 ${cur} = ? USD).`)
          }
        }
      })
    } else if (nonServiceForm) {
      const cur = (nonServiceForm.currency || 'USD').toUpperCase()
      if (cur !== 'USD') {
        const fxVal = Number(nonServiceForm.exchange_rate)
        if (!nonServiceForm.exchange_rate || !Number.isFinite(fxVal) || fxVal <= 0) {
          problems.push(`Enter the USD conversion rate (1 ${cur} = ? USD) so USD totals remain standardized across all wells.`)
        }
      }
      if (nonServiceForm.override_rate !== null) {
        const ovNum = Number(nonServiceForm.override_rate)
        if (isNaN(ovNum) || ovNum < 0) problems.push('Enter a valid daily override rate.')
        if (nonServiceForm.override_reason.trim().length < 3) {
          problems.push('Explain the daily rate override (at least 3 characters).')
        }
      }
      if (isOther(nonServiceForm)) {
        if (!nonServiceForm.expense_type) problems.push('Choose the type of other expense.')
        if (!nonServiceForm.unit_rate || Number(nonServiceForm.unit_rate) <= 0) problems.push('Enter a valid unit rate.')
        if (nonServiceForm.remarks.trim().length < OTHER_EXPENSE_MIN_REMARKS) {
          problems.push(`Remarks are mandatory on other expense (at least ${OTHER_EXPENSE_MIN_REMARKS} characters).`)
        }
      } else if (isConsumable(nonServiceForm)) {
        if (!commonHoleSectionId) problems.push('Select a hole section for this consumable line.')
        if (!nonServiceForm.item_id) problems.push('Select a consumable item.')
      } else {
        if (!('tangible_id' in nonServiceForm) || !nonServiceForm.tangible_id) problems.push('Select a tangible item.')
      }
    }

    return problems
  }

  const handleSave = (queueOnly = false) => {
    if (!queueOnly && queuedLines.length && nonServiceForm && (('item_id' in nonServiceForm && !nonServiceForm.item_id) || ('tangible_id' in nonServiceForm && !nonServiceForm.tangible_id))) {
      onSave(queuedLines)
      return
    }
    setSubmitted(true)
    const problems = validate()
    if (problems.length > 0) {
      setError(problems[0])
      return
    }

    const parsedDepth = commonActualDepth.trim() === '' ? null : commonActualDepth.trim()

    setSaving(true)
    try {
      if (kind === 'service') {
        const results: DailyCostServiceInput[] = serviceRows.map(row => {
          const secId = row.customScope ? row.custom_hole_section_id : commonHoleSectionId
          const phId = row.customScope ? row.custom_phase_id : commonPhaseId
          const qty = row.customQuantity ? row.custom_quantity : commonQuantity
          const unit = row.customQuantity ? row.custom_quantity_unit : commonQuantityUnit
          const cur = (row.currency || baseline.standard_currency || 'USD').toUpperCase()
          return {
            id: initialLine && serviceRows.length === 1 ? initialLine.id : null,
            activity_id: commonActivityId,
            sub_activity_id: commonSubActivityId,
            vendor_id: derivedClassification === 'Planned' ? null : commonVendorId,
            party_name: derivedClassification === 'Planned' ? 'Not Applicable' : commonPartyName.trim(),
            hole_section_id: secId,
            phase_id: secId ? phId : null,
            actual_depth: parsedDepth,
            actual_depth_unit: commonDepthUnit,
            quantity: qty,
            quantity_unit: unit,
            cost_items: row.cost_items ?? [],
            service_id: row.service_id,
            baseline_service_rate_id: row.baseline_service_rate_id,
            charging_basis: row.charging_basis,
            charge_category: (row.charge_category || 'Operation') as ChargeCategory,
            currency: cur,
            exchange_rate: cur !== 'USD' && row.exchange_rate ? row.exchange_rate : null,
            override_rate: row.override_rate || null,
            override_reason: row.override_rate ? row.override_reason.trim() : '',
            remarks: row.remarks.trim(),
          }
        })
        onSave(results)
      } else if (nonServiceForm) {
        const cur = (nonServiceForm.currency || baseline.standard_currency || 'USD').toUpperCase()
        const prepared: EditableDailyCostLine = {
          ...nonServiceForm,
          activity_id: commonActivityId,
          sub_activity_id: commonSubActivityId,
          hole_section_id: commonHoleSectionId,
          phase_id: commonHoleSectionId ? commonPhaseId : null,
          actual_depth: parsedDepth,
          actual_depth_unit: commonDepthUnit,
          currency: cur,
          exchange_rate: cur !== 'USD' && nonServiceForm.exchange_rate ? nonServiceForm.exchange_rate : null,
          vendor_id: derivedClassification === 'Planned' ? null : commonVendorId,
          party_name: derivedClassification === 'Planned' ? 'Not Applicable' : commonPartyName.trim(),
          remarks: nonServiceForm.remarks.trim(),
          override_reason: nonServiceForm.override_rate === null ? '' : nonServiceForm.override_reason.trim(),
        }
        if (queueOnly) {
          setQueuedLines(prev => [...prev, prepared])
          setNonServiceForm(prev => prev ? { ...prev, quantity: '1', override_rate: null, override_reason: '', remarks: '', ...('item_id' in prev ? { item_id: '' } : { tangible_id: '' }) } : prev)
          setSubmitted(false)
          setError('')
        } else onSave([...queuedLines, prepared])
      }
    } finally {
      setSaving(false)
    }
  }

  const dialogTitle = initialLine
    ? `Edit ${kind === 'service' ? 'service' : kind === 'consumable' ? 'consumable' : kind === 'other' ? 'other expense' : 'tangible'} line`
    : `Add ${kind === 'service' ? 'services' : kind === 'consumable' ? 'consumable usage' : kind === 'other' ? 'other expense' : 'tangible'}`

  const submitLabel = initialLine
    ? 'Save line'
    : kind === 'service'
      ? serviceRows.length > 1
        ? `Add ${serviceRows.length} services`
        : 'Add service'
      : 'Add line'

  const sectionLabel = (sec: typeof sections[number]) =>
    `${sec.section_code} · ${sec.section_name} (${Number(sec.from_depth).toFixed(0)}–${Number(sec.to_depth).toFixed(0)} m)`

  const depthHelperText = commonActualDepth.trim()
    ? commonDepthUnit === 'ft'
      ? `Standardized depth: ${formatDepthMeters(commonActualDepth, 'ft')} (feet ÷ 3.281). Last entered value governs this date & section.`
      : `Standardized depth: ${formatDepthMeters(commonActualDepth, 'm')}. Last entered value governs this date & section.`
    : 'Actual depth reached on this date/section (last entered value in register wins; feet auto-convert via ÷ 3.281).'

  return (
    <FormDialog
      open={open}
      title={dialogTitle}
      subtitle="Dropdowns, actual depth (standardized to metres via feet ÷ 3.281), and currency conversion apply cleanly across the daily cost register."
      onClose={onClose}
      onSubmit={() => handleSave()}
      busy={saving}
      dirty={dirty}
      submitLabel={submitLabel}
      maxWidth="md"
    >
      <Box display="grid" gap={2}>
        {/* COMMON CRITERIA SECTION */}
        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, bgcolor: 'background.paper' }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={1.2}>
            <Typography fontSize={11} fontWeight={800} letterSpacing={0.6} color="text.secondary" textTransform="uppercase">
              Common Activity &amp; Operational Criteria
            </Typography>
            <Tag tone={derivedClassification === 'Planned' ? 'info' : derivedClassification === 'UPA' ? 'warning' : 'error'}>
              {derivedClassification}
            </Tag>
          </Box>

          <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            <TextField
              select
              required
              label="Master Data Activity"
              value={commonActivityId}
              onChange={e => handleActivityChange(e.target.value)}
              helperText="Drives classification (Planned / UPA / NPT) and available sub activities."
            >
              {reference.activities.map(item => (
                <MenuItem key={item.id} value={item.id}>
                  {item.display_name}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              required
              label="Well sub activity"
              value={commonSubActivityId ?? ''}
              onChange={e => handleSubActivityChange(e.target.value || null)}
              helperText="Mandatory. Links this daily cost to the well's planned or operational step."
            >
              {!eligibleSubActivities.length && <MenuItem value="">No sub activity configured</MenuItem>}
              {eligibleSubActivities.map(item => (
                <MenuItem key={item.id} value={item.id}>
                  {item.sub_activity_code} · {item.sub_activity_name}
                </MenuItem>
              ))}
            </TextField>

            {eligibleSubActivities.length === 0 && (
              <Box sx={{ gridColumn: '1 / -1' }}>
                <Alert
                  severity="warning"
                  sx={{ py: 0 }}
                  action={
                    <Button component={RouterLink} to="/rig-well/sub-activities" size="small" color="inherit" onClick={onClose}>
                      Configure sub activities
                    </Button>
                  }
                >
                  No sub activity configured for this well and Activity. Configuring sub activities in Rig &amp; Well Management is mandatory.
                </Alert>
              </Box>
            )}

            {/* Scope (Section & Phase) */}
            <TextField
              select
              label="Hole section"
              value={commonHoleSectionId ?? ''}
              onChange={e => {
                const sId = e.target.value || null
                const sec = sections.find(s => s.hole_section_id === sId)
                setCommonHoleSectionId(sId)
                setCommonPhaseId(sec?.phases[0]?.phase_id ?? null)
              }}
            >
              <MenuItem value="">No hole section</MenuItem>
              {sections.map(sec => (
                <MenuItem key={sec.hole_section_id} value={sec.hole_section_id}>
                  {sectionLabel(sec)}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              select
              label="Phase (optional)"
              value={commonPhaseId ?? ''}
              disabled={!selectedCommonSection}
              onChange={e => setCommonPhaseId(e.target.value || null)}
            >
              <MenuItem value="">No phase</MenuItem>
              {selectedCommonSection?.phases.map(p => (
                <MenuItem key={p.phase_id} value={p.phase_id}>
                  {p.phase_code} · {p.phase_name}
                </MenuItem>
              ))}
            </TextField>

            {/* Actual Depth + Standardized Unit Selector */}
            <TextField
              label="Actual depth"
              type="number"
              value={commonActualDepth}
              onChange={e => setCommonActualDepth(e.target.value)}
              inputProps={{ min: 0, step: 'any' }}
              helperText={depthHelperText}
            />

            <TextField
              select
              label="Depth unit"
              value={commonDepthUnit}
              onChange={e => setCommonDepthUnit(e.target.value as DepthUnit)}
              helperText="All depths standardize to metres (m = ft ÷ 3.281)."
            >
              <MenuItem value="m">Metres (m) — Standard</MenuItem>
              <MenuItem value="ft">Feet (ft ÷ 3.281 → m)</MenuItem>
            </TextField>

            {/* Charged Quantity & Unit (Common) */}
            {kind === 'service' && (
              <>
                <TextField
                  label="Charged quantity"
                  type="number"
                  required
                  value={commonQuantity}
                  onChange={e => setCommonQuantity(e.target.value)}
                  inputProps={{ min: 0.0001, step: 'any' }}
                  helperText="Applies to all services added below."
                />
                <TextField
                  select
                  label="Quantity unit"
                  value={commonQuantityUnit}
                  onChange={e => setCommonQuantityUnit(e.target.value as DailyQuantityUnit)}
                  helperText="Common charging unit."
                >
                  {['hours', 'days', 'unit', 'service', 'section'].map(u => (
                    <MenuItem key={u} value={u}>
                      {u}
                    </MenuItem>
                  ))}
                </TextField>
              </>
            )}

            {/* Responsibility */}
            {derivedClassification === 'Planned' ? (
              <Box sx={{ gridColumn: '1 / -1' }}>
                <TextField
                  label="Responsible vendor / party"
                  value="Not Applicable"
                  disabled
                  fullWidth
                  helperText="Planned activities do not require a responsible party/vendor."
                />
              </Box>
            ) : (
              <>
                <TextField
                  label="Responsible party / team"
                  required
                  value={commonPartyName}
                  onChange={e => setCommonPartyName(e.target.value)}
                  inputProps={{ maxLength: 200 }}
                  helperText="Captured automatically from sub activity for UPA/NPT."
                />
                <TextField
                  select
                  label="Responsible vendor (optional)"
                  value={commonVendorId ?? ''}
                  onChange={e => {
                    const v = reference.vendors.find(item => item.id === e.target.value)
                    setCommonVendorId(e.target.value || null)
                    if (v?.vendor_name) setCommonPartyName(v.vendor_name)
                  }}
                >
                  <MenuItem value="">No vendor selected</MenuItem>
                  {reference.vendors.map(v => (
                    <MenuItem key={v.id} value={v.id}>
                      {v.display_name}
                    </MenuItem>
                  ))}
                </TextField>
              </>
            )}
          </Box>
        </Paper>

        {/* SERVICES LIST */}
        {kind === 'service' && (
          <Box>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={0.5}>
                Services under this criteria ({serviceRows.length})
              </Typography>
              {!initialLine && (
                <Button size="small" startIcon={<AddRounded sx={{ fontSize: 16 }} />} onClick={addServiceRow} variant="outlined">
                  Add another service
                </Button>
              )}
            </Box>

            <Box display="grid" gap={1.8}>
              {serviceRows.map((row, index) => {
                const sObj = reference.services.find(s => s.id === row.service_id)
                const rate = baseline.service_rates.find(r => r.id === row.baseline_service_rate_id)
                const rateMatches = baseline.service_rates.filter(r => r.service_id === row.service_id)
                const rowCurrency = (row.currency || 'USD').toUpperCase()
                const canChangeCurrency = row.override_rate !== null || !rate
                return (
                  <Paper key={row.id} variant="outlined" sx={{ p: 1.8, borderRadius: 1.5 }}>
                    <Box display="flex" justifyContent="space-between" alignItems="center" mb={1.2}>
                      <Typography fontSize={12} fontWeight={800} color="primary">
                        Service line #{index + 1}
                      </Typography>
                      {!initialLine && serviceRows.length > 1 && (
                        <Button
                          size="small"
                          color="error"
                          startIcon={<DeleteOutlineRounded sx={{ fontSize: 16 }} />}
                          onClick={() => removeServiceRow(row.id)}
                        >
                          Remove
                        </Button>
                      )}
                    </Box>

                    <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                      <TextField
                        select
                        size="small"
                        label="Service"
                        required
                        value={row.service_id}
                        onChange={e => updateServiceRow(row.id, { service_id: e.target.value })}
                        error={submitted && !row.service_id}
                        helperText="From Master Data → Services."
                        sx={{ gridColumn: { sm: '1 / -1' } }}
                      >
                        <MenuItem value="">Select a service</MenuItem>
                        {reference.services.map(s => (
                          <MenuItem key={s.id} value={s.id}>
                            {s.service_code} · {s.service_name}
                          </MenuItem>
                        ))}
                      </TextField>

                      {row.service_id && (
                        <Box sx={{ gridColumn: '1 / -1' }}>
                          {rateMatches.length > 1 ? (
                            <TextField
                              select
                              size="small"
                              label="Matched AFE rate"
                              value={row.baseline_service_rate_id ?? ''}
                              onChange={e => {
                                const pickedRate = baseline.service_rates.find(r => r.id === e.target.value)
                                updateServiceRow(row.id, {
                                  baseline_service_rate_id: e.target.value || null,
                                  charging_basis: pickedRate?.charging_basis || row.charging_basis,
                                  charge_category: (pickedRate?.charge_category || row.charge_category) as ChargeCategory,
                                  currency: (pickedRate?.currency || row.currency).toUpperCase(),
                                })
                              }}
                              fullWidth
                            >
                              {rateMatches.map(r => (
                                <MenuItem key={r.id} value={r.id}>
                                  {dailyMoney(r.unit_rate, r.currency)} / {r.charging_basis} ({r.charge_category || 'Operation'})
                                  {r.section_label ? ` · ${r.section_label}` : ''}
                                </MenuItem>
                              ))}
                            </TextField>
                          ) : rate ? (
                            <Alert severity="info" sx={{ py: 0.2 }}>
                              Locked AFE rate: {dailyMoney(rate.unit_rate, rate.currency)} / {rate.charging_basis} ({rate.charge_category || 'Operation'})
                            </Alert>
                          ) : derivedClassification === 'Planned' ? (
                            <Alert severity="error" sx={{ py: 0.2 }}>
                              No locked AFE rate found for {sObj?.service_code || 'this service'} under this scope.
                            </Alert>
                          ) : (
                            <Alert severity="warning" sx={{ py: 0.2 }}>
                              No locked AFE rate for this unplanned service. Enter a daily rate override below.
                            </Alert>
                          )}
                        </Box>
                      )}

                      <Box sx={{ gridColumn: '1 / -1' }} display="grid" gap={1}>
                        <Typography fontWeight={700}>Actual cost breakdown (optional)</Typography>
                        <Typography color="text.secondary" fontSize={12}>Amounts are in {row.currency}. Their total replaces the rate-based charge; descriptions are retained for reference.</Typography>
                        {(row.cost_items ?? []).map((item, itemIndex) => <Box key={itemIndex} display="flex" gap={1}>
                          <TextField size="small" label="Description" value={item.description} onChange={e => updateServiceRow(row.id, { cost_items: row.cost_items!.map((v, i) => i === itemIndex ? { ...v, description: e.target.value } : v) })} fullWidth />
                          <TextField size="small" label="Amount" type="number" value={item.amount} onChange={e => updateServiceRow(row.id, { cost_items: row.cost_items!.map((v, i) => i === itemIndex ? { ...v, amount: e.target.value } : v) })} />
                          <Button color="error" onClick={() => updateServiceRow(row.id, { cost_items: row.cost_items!.filter((_, i) => i !== itemIndex) })}>Remove</Button>
                        </Box>)}
                        <Button onClick={() => updateServiceRow(row.id, { cost_items: [...(row.cost_items ?? []), { description: '', amount: '' }] })}>Add cost item</Button>
                        {!!row.cost_items?.length && <Typography fontWeight={700}>Actual total: {dailyMoney(row.cost_items.reduce((sum, item) => sum + Number(item.amount || 0), 0), row.currency)}</Typography>}
                      </Box>
                      <TextField
                        size="small"
                        label="Daily rate override (optional)"
                        type="number"
                        value={row.override_rate ?? ''}
                        onChange={e => {
                          const nextOv = e.target.value === '' ? null : e.target.value
                          updateServiceRow(row.id, {
                            override_rate: nextOv,
                            currency: nextOv === null && rate ? rate.currency.toUpperCase() : row.currency,
                          })
                        }}
                        inputProps={{ min: 0, step: 'any' }}
                        helperText="Service-scoped override; locked baseline rate remains unchanged."
                      />

                      <TextField
                        size="small"
                        label="Override reason"
                        value={row.override_reason}
                        onChange={e => updateServiceRow(row.id, { override_reason: e.target.value })}
                        disabled={row.override_rate === null}
                        inputProps={{ maxLength: 500 }}
                        helperText={row.override_rate !== null ? 'Required when override is entered.' : 'Leave empty if no override.'}
                      />

                      <TextField
                        select
                        size="small"
                        label="Currency (USD standard)"
                        value={rowCurrency}
                        disabled={!canChangeCurrency}
                        onChange={e => updateServiceRow(row.id, { currency: e.target.value })}
                        helperText={canChangeCurrency ? 'USD is the default & standard currency.' : 'Matches locked AFE rate currency unless overridden.'}
                      >
                        {currencyChoices.map(c => (
                          <MenuItem key={c} value={c}>
                            {c === 'USD' ? 'USD (Default Standard)' : c}
                          </MenuItem>
                        ))}
                      </TextField>

                      {rowCurrency !== 'USD' && (
                        <TextField
                          size="small"
                          type="number"
                          required
                          label={`USD conversion rate (1 ${rowCurrency} = ? USD)`}
                          value={row.exchange_rate}
                          onChange={e => updateServiceRow(row.id, { exchange_rate: e.target.value })}
                          inputProps={{ min: 0.000001, step: 'any' }}
                          helperText={`Required for non-USD currency so USD values stay standardized across all wells.`}
                        />
                      )}

                      <Box sx={{ gridColumn: '1 / -1' }}>
                        <Button
                          size="small"
                          startIcon={<TuneRounded sx={{ fontSize: 16 }} />}
                          onClick={() => updateServiceRow(row.id, { customScope: !row.customScope, customQuantity: !row.customQuantity })}
                          sx={{ textTransform: 'none' }}
                        >
                          {row.customScope || row.customQuantity ? 'Hide custom scope/quantity' : 'Customize scope or quantity for this service'}
                        </Button>

                        <Collapse in={row.customScope || row.customQuantity}>
                          <Box mt={1} p={1.5} bgcolor="action.hover" borderRadius={1} display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                            <Typography fontSize={11} fontWeight={700} color="text.secondary" sx={{ gridColumn: '1 / -1' }}>
                              Individual Scope &amp; Quantity Override
                            </Typography>
                            <TextField
                              select
                              size="small"
                              label="Custom hole section"
                              value={row.custom_hole_section_id ?? ''}
                              onChange={e => updateServiceRow(row.id, { custom_hole_section_id: e.target.value || null, custom_phase_id: null })}
                            >
                              <MenuItem value="">No hole section</MenuItem>
                              {sections.map(sec => (
                                <MenuItem key={sec.hole_section_id} value={sec.hole_section_id}>
                                  {sectionLabel(sec)}
                                </MenuItem>
                              ))}
                            </TextField>

                            <TextField
                              select
                              size="small"
                              label="Custom phase"
                              value={row.custom_phase_id ?? ''}
                              onChange={e => updateServiceRow(row.id, { custom_phase_id: e.target.value || null })}
                            >
                              <MenuItem value="">No phase</MenuItem>
                              {sections
                                .find(s => s.hole_section_id === row.custom_hole_section_id)
                                ?.phases.map(p => (
                                  <MenuItem key={p.phase_id} value={p.phase_id}>
                                    {p.phase_code} · {p.phase_name}
                                  </MenuItem>
                                ))}
                            </TextField>

                            <TextField
                              size="small"
                              label="Custom quantity"
                              type="number"
                              value={row.custom_quantity}
                              onChange={e => updateServiceRow(row.id, { custom_quantity: e.target.value })}
                            />

                            <TextField
                              select
                              size="small"
                              label="Custom quantity unit"
                              value={row.custom_quantity_unit}
                              onChange={e => updateServiceRow(row.id, { custom_quantity_unit: e.target.value as DailyQuantityUnit })}
                            >
                              {['hours', 'days', 'unit', 'service', 'section'].map(u => (
                                <MenuItem key={u} value={u}>
                                  {u}
                                </MenuItem>
                              ))}
                            </TextField>
                          </Box>
                        </Collapse>
                      </Box>

                      <TextField
                        size="small"
                        label="Remarks (optional)"
                        value={row.remarks}
                        onChange={e => updateServiceRow(row.id, { remarks: e.target.value })}
                        inputProps={{ maxLength: 500 }}
                        sx={{ gridColumn: '1 / -1' }}
                      />
                    </Box>
                  </Paper>
                )
              })}
            </Box>
          </Box>
        )}

        {/* NON-SERVICE LINE EDITOR */}
        {kind !== 'service' && nonServiceForm && (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            {kind === 'other' && isOther(nonServiceForm) && (
              <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                <TextField
                  select
                  required
                  size="small"
                  label="Type of other expense"
                  value={nonServiceForm.expense_type}
                  onChange={e => setNonServiceForm(prev => (prev && isOther(prev) ? { ...prev, expense_type: e.target.value as OtherExpenseType } : prev))}
                >
                  {(reference.other_expense_types?.length ? reference.other_expense_types : OTHER_EXPENSE_TYPES).map(opt => (
                    <MenuItem key={opt.code} value={opt.code}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </TextField>

                <TextField
                  size="small"
                  label="Description (optional)"
                  value={nonServiceForm.expense_description}
                  onChange={e => setNonServiceForm(prev => (prev && isOther(prev) ? { ...prev, expense_description: e.target.value } : prev))}
                />

                <TextField
                  size="small"
                  label="Quantity"
                  type="number"
                  required
                  value={nonServiceForm.quantity}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, quantity: e.target.value } : prev))}
                />

                <TextField
                  size="small"
                  label={`Unit rate (${(nonServiceForm.currency || 'USD').toUpperCase()})`}
                  type="number"
                  required
                  value={nonServiceForm.unit_rate}
                  onChange={e => setNonServiceForm(prev => (prev && isOther(prev) ? { ...prev, unit_rate: e.target.value } : prev))}
                />

                <TextField
                  select
                  size="small"
                  label="Currency (USD standard)"
                  value={(nonServiceForm.currency || 'USD').toUpperCase()}
                  onChange={e => {
                    const nextCur = e.target.value.toUpperCase()
                    setNonServiceForm(prev => (prev ? {
                      ...prev,
                      currency: nextCur,
                      exchange_rate: defaultUsdRateForCurrency(nextCur, baseline),
                    } : prev))
                  }}
                  helperText="USD is the default & standard currency."
                >
                  {currencyChoices.map(c => (
                    <MenuItem key={c} value={c}>
                      {c === 'USD' ? 'USD (Default Standard)' : c}
                    </MenuItem>
                  ))}
                </TextField>

                {(nonServiceForm.currency || 'USD').toUpperCase() !== 'USD' && (
                  <TextField
                    size="small"
                    type="number"
                    required
                    label={`USD conversion rate (1 ${(nonServiceForm.currency || '').toUpperCase()} = ? USD)`}
                    value={nonServiceForm.exchange_rate ?? ''}
                    onChange={e => setNonServiceForm(prev => (prev ? { ...prev, exchange_rate: e.target.value } : prev))}
                    inputProps={{ min: 0.000001, step: 'any' }}
                    helperText={
                      nonServiceForm.exchange_rate && Number(nonServiceForm.exchange_rate) > 0 && Number(nonServiceForm.unit_rate) > 0
                        ? `Converted to USD: ${dailyMoney(Number(nonServiceForm.quantity || 1) * Number(nonServiceForm.unit_rate) * Number(nonServiceForm.exchange_rate), 'USD')}`
                        : 'Enter USD conversion rate so USD values are recorded across all wells.'
                    }
                  />
                )}

                <TextField
                  size="small"
                  label="Remarks (mandatory for other expense)"
                  required
                  multiline
                  minRows={2}
                  value={nonServiceForm.remarks}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, remarks: e.target.value } : prev))}
                  sx={{ gridColumn: '1 / -1' }}
                />
              </Box>
            )}

            {kind === 'consumable' && isConsumable(nonServiceForm) && (
              <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                <TextField
                  select
                  size="small"
                  label="Consumable category"
                  value={nonServiceForm.category}
                  onChange={e => {
                    const cat = e.target.value as ConsumableCategory
                    const nextKind = KIND_BY_CATEGORY[cat]
                    const first = optionsForKind(nextKind, reference, baseline, null)[0]
                    const snap = itemSnapshot(first, baseline)
                    const cur = (snap?.currency || first?.currency || baseline.standard_currency || 'USD').toUpperCase()
                    setNonServiceForm(prev => (prev && isConsumable(prev) ? {
                      ...prev,
                      category: cat,
                      item_kind: nextKind,
                      item_id: first?.id ?? '',
                      currency: cur,
                      exchange_rate: defaultUsdRateForCurrency(cur, baseline),
                    } : prev))
                  }}
                >
                  {(reference.consumable_categories?.length ? reference.consumable_categories : DAILY_CONSUMABLE_CATEGORIES).map(cat => (
                    <MenuItem key={cat} value={cat}>
                      {cat}
                    </MenuItem>
                  ))}
                </TextField>

                <TextField
                  select
                  size="small"
                  label="Consumable item"
                  required
                  value={nonServiceForm.item_id}
                  onChange={e => {
                    const item = reference.catalogue_items.find(opt => opt.id === e.target.value)
                    const snap = itemSnapshot(item, baseline)
                    const cur = (snap?.currency || item?.currency || baseline.standard_currency || 'USD').toUpperCase()
                    setNonServiceForm(prev => (prev && isConsumable(prev) ? {
                      ...prev,
                      item_id: e.target.value,
                      currency: cur,
                      exchange_rate: defaultUsdRateForCurrency(cur, baseline),
                    } : prev))
                  }}
                >
                  {optionsForKind(nonServiceForm.item_kind, reference, baseline, nonServiceForm.item_id).map(opt => (
                    <MenuItem key={opt.id} value={opt.id}>
                      {opt.display_name} · {opt.uom || 'unit'}
                    </MenuItem>
                  ))}
                </TextField>

                <TextField
                  size="small"
                  label="Quantity"
                  type="number"
                  required
                  value={nonServiceForm.quantity}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, quantity: e.target.value } : prev))}
                />

                <TextField
                  size="small"
                  label="Daily rate override (optional)"
                  type="number"
                  value={nonServiceForm.override_rate ?? ''}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, override_rate: e.target.value === '' ? null : e.target.value } : prev))}
                />

                {nonServiceForm.override_rate !== null && (
                  <TextField
                    size="small"
                    label="Override reason"
                    required
                    value={nonServiceForm.override_reason}
                    onChange={e => setNonServiceForm(prev => (prev ? { ...prev, override_reason: e.target.value } : prev))}
                    sx={{ gridColumn: '1 / -1' }}
                  />
                )}

                <TextField
                  select
                  size="small"
                  label="Currency (USD standard)"
                  value={(nonServiceForm.currency || 'USD').toUpperCase()}
                  disabled={nonServiceForm.override_rate === null}
                  onChange={e => {
                    const nextCur = e.target.value.toUpperCase()
                    setNonServiceForm(prev => (prev ? {
                      ...prev,
                      currency: nextCur,
                      exchange_rate: defaultUsdRateForCurrency(nextCur, baseline),
                    } : prev))
                  }}
                  helperText={nonServiceForm.override_rate !== null ? 'USD is the default & standard currency.' : 'Matches locked catalogue currency unless rate is overridden.'}
                >
                  {currencyChoices.map(c => (
                    <MenuItem key={c} value={c}>
                      {c === 'USD' ? 'USD (Default Standard)' : c}
                    </MenuItem>
                  ))}
                </TextField>

                {(nonServiceForm.currency || 'USD').toUpperCase() !== 'USD' && (
                  <TextField
                    size="small"
                    type="number"
                    required
                    label={`USD conversion rate (1 ${(nonServiceForm.currency || '').toUpperCase()} = ? USD)`}
                    value={nonServiceForm.exchange_rate ?? ''}
                    onChange={e => setNonServiceForm(prev => (prev ? { ...prev, exchange_rate: e.target.value } : prev))}
                    inputProps={{ min: 0.000001, step: 'any' }}
                    helperText="Required for non-USD currency so USD values are recorded across all wells."
                  />
                )}

                <TextField
                  size="small"
                  label="Remarks"
                  value={nonServiceForm.remarks}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, remarks: e.target.value } : prev))}
                  sx={{ gridColumn: '1 / -1' }}
                />
              </Box>
            )}

            {kind === 'tangible' && (
              <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                <TextField
                  select
                  size="small"
                  label="Tangible item"
                  required
                  value={'tangible_id' in nonServiceForm ? nonServiceForm.tangible_id : ''}
                  onChange={e => {
                    const item = reference.catalogue_items.find(opt => opt.id === e.target.value)
                    const snap = itemSnapshot(item, baseline)
                    const cur = (snap?.currency || item?.currency || baseline.standard_currency || 'USD').toUpperCase()
                    setNonServiceForm(prev => (prev && 'tangible_id' in prev ? {
                      ...prev,
                      tangible_id: e.target.value,
                      currency: cur,
                      exchange_rate: defaultUsdRateForCurrency(cur, baseline),
                    } : prev))
                  }}
                  sx={{ gridColumn: '1 / -1' }}
                >
                  {optionsForKind('tangible', reference, baseline, 'tangible_id' in nonServiceForm ? nonServiceForm.tangible_id : null).map(opt => (
                    <MenuItem key={opt.id} value={opt.id}>
                      {opt.display_name} · {opt.uom || 'unit'}
                    </MenuItem>
                  ))}
                </TextField>

                <TextField
                  size="small"
                  label="Quantity"
                  type="number"
                  required
                  value={nonServiceForm.quantity}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, quantity: e.target.value } : prev))}
                />

                <TextField
                  size="small"
                  label="Daily rate override (optional)"
                  type="number"
                  value={nonServiceForm.override_rate ?? ''}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, override_rate: e.target.value === '' ? null : e.target.value } : prev))}
                />

                {nonServiceForm.override_rate !== null && (
                  <TextField
                    size="small"
                    label="Override reason"
                    required
                    value={nonServiceForm.override_reason}
                    onChange={e => setNonServiceForm(prev => (prev ? { ...prev, override_reason: e.target.value } : prev))}
                    sx={{ gridColumn: '1 / -1' }}
                  />
                )}

                <TextField
                  select
                  size="small"
                  label="Currency (USD standard)"
                  value={(nonServiceForm.currency || 'USD').toUpperCase()}
                  disabled={nonServiceForm.override_rate === null}
                  onChange={e => {
                    const nextCur = e.target.value.toUpperCase()
                    setNonServiceForm(prev => (prev ? {
                      ...prev,
                      currency: nextCur,
                      exchange_rate: defaultUsdRateForCurrency(nextCur, baseline),
                    } : prev))
                  }}
                  helperText={nonServiceForm.override_rate !== null ? 'USD is the default & standard currency.' : 'Matches locked catalogue currency unless rate is overridden.'}
                >
                  {currencyChoices.map(c => (
                    <MenuItem key={c} value={c}>
                      {c === 'USD' ? 'USD (Default Standard)' : c}
                    </MenuItem>
                  ))}
                </TextField>

                {(nonServiceForm.currency || 'USD').toUpperCase() !== 'USD' && (
                  <TextField
                    size="small"
                    type="number"
                    required
                    label={`USD conversion rate (1 ${(nonServiceForm.currency || '').toUpperCase()} = ? USD)`}
                    value={nonServiceForm.exchange_rate ?? ''}
                    onChange={e => setNonServiceForm(prev => (prev ? { ...prev, exchange_rate: e.target.value } : prev))}
                    inputProps={{ min: 0.000001, step: 'any' }}
                    helperText="Required for non-USD currency so USD values are recorded across all wells."
                  />
                )}

                <TextField
                  size="small"
                  label="Remarks"
                  value={nonServiceForm.remarks}
                  onChange={e => setNonServiceForm(prev => (prev ? { ...prev, remarks: e.target.value } : prev))}
                  sx={{ gridColumn: '1 / -1' }}
                />
              </Box>
            )}
          </Paper>
        )}

        {!initialLine && (kind === 'consumable' || kind === 'tangible') && <Box display="grid" gap={1}>
          <Typography fontWeight={700}>Items collected: {queuedLines.length}</Typography>
          {queuedLines.map((line, index) => <Box key={index} display="flex" justifyContent="space-between" alignItems="center">
            <Typography>{reference.catalogue_items.find(item => item.id === ('item_id' in line ? line.item_id : 'tangible_id' in line ? line.tangible_id : ''))?.display_name || 'Item'} · Usage: {line.quantity}</Typography>
            <Button color="error" onClick={() => setQueuedLines(prev => prev.filter((_, i) => i !== index))}>Remove</Button>
          </Box>)}
          <Button variant="outlined" onClick={() => handleSave(true)}>Collect item & add another</Button>
          {!!queuedLines.length && <Button onClick={() => { if (nonServiceForm && (('item_id' in nonServiceForm && nonServiceForm.item_id) || ('tangible_id' in nonServiceForm && nonServiceForm.tangible_id))) handleSave(); else onSave(queuedLines) }}>Add collected items to sheet</Button>}
          <Typography color="text.secondary" fontSize={12}>Each collected item is added as a separate line. Save the daily sheet to commit them.</Typography>
        </Box>}
        {submitted && error && <Alert severity="error">{error}</Alert>}

        <Divider />
        <Typography fontSize={11.5} color="text.secondary">
          All depths are standardized to metres (feet ÷ 3.281), and non-USD lines convert automatically to USD.
        </Typography>
      </Box>
    </FormDialog>
  )
}
