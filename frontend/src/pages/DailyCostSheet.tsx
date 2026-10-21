import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import {
  PrintOutlined, AddRounded, ArrowBackRounded, CloudUploadOutlined, ContentCopyOutlined, DeleteOutlineRounded,
  DownloadOutlined, EditOutlined, LockOutlined, PlaylistAddRounded, RefreshRounded, SaveOutlined, SendRounded, UndoRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, LinearProgress, Paper, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import { DailyCostLineDialog, type DailyCostLineKind, type EditableDailyCostLine } from '../components/daily-cost/DailyCostLineDialog'
import { DailyCostBulkScopeDialog } from '../components/daily-cost/DailyCostBulkScopeDialog'
import { WellProgressPanel } from '../components/daily-cost/WellProgressPanel'
import { CostingSetPickerDialog } from '../components/CostingSetPickerDialog'
import { useCostPrint } from '../components/daily-cost/DailyCostPrintSheet'
import { WellCostPrintDialog } from '../components/daily-cost/WellCostPrintDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { listEntryAmendments, type DailyCostAmendment } from '../lib/sowAdjustment'
import { downloadTemplate, parseImportFile, type ImportRow } from '../lib/export'
import {
  DAILY_COST_STATUSES, DAILY_ONE_TIME_CATEGORIES, costReportTitle, dailyMoney, deriveClassification, displayDate,
  entryQuery, otherExpenseLabel, saveFromDay,
  type DailyCostBaseline, type DailyCostComparisonLine, type DailyCostDay, type DailyCostGroup,
  type AnyDailyCostLine, type DailyCostImportResult, type DailyCostPreview, type DailyCostReference,
  type DailyCostSavePayload, type DailyCostServiceInput, type DailyQuantityUnit, type WellProgressScope,
  type ConsumableCategory, type ConsumableKind, type DailyCostWellSummary,
} from '../lib/dailyCost'
import type { MudCostMaterialBalance, MudCostReconciliation } from '../lib/mudCost'
import { formatDepthMeters } from '../lib/units'
import type { CostingSet, CostingSetGroup } from '../lib/costingSets'

/** Where each dialog kind lives inside the save payload. */
type LineGroupKey = 'services' | 'consumables' | 'tangibles' | 'other_expenses'
const GROUP_KEY: Record<DailyCostLineKind, LineGroupKey> = {
  service: 'services', consumable: 'consumables', tangible: 'tangibles', other: 'other_expenses',
}

type GridLine = {
  id: string; lineIndex: number; item: string; activity: string; section: string; actualDepth: string; subActivity: string
  vendor: string; quantity: string; quantityUnit: string; rate: string; currency: string
  amount: string; standardAmount: string; usdAmount: string; source: string; budget: string; overrideReason: string; remarks: string
}
type StatusAction = 'submit' | 'reopen'
type LineDelete = { kind: DailyCostLineKind; index: number; label: string } | null

function StatCard({ label, value, hint, tone }: { label: string; value: string; hint: string; tone?: 'good' | 'bad' }) {
  return <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, minWidth: 0 }}>
    <Typography color="text.secondary" fontSize={10} fontWeight={800} letterSpacing={.7} textTransform="uppercase">{label}</Typography>
    <Typography fontWeight={800} fontSize={21} mt={.6} sx={{ color: tone === 'good' ? 'success.main' : tone === 'bad' ? 'error.main' : 'text.primary', overflowWrap: 'anywhere' }}>{value}</Typography>
    <Typography color="text.secondary" fontSize={10.8} mt={.3}>{hint}</Typography>
  </Paper>
}

function amountForRate(rate: string, quantity: string, unit: string, basis?: string, category?: string): string {
  const billableQuantity = basis === 'Day Rate' && category && DAILY_ONE_TIME_CATEGORIES.includes(category as typeof DAILY_ONE_TIME_CATEGORIES[number])
    ? 1
    : Number(quantity) / (basis === 'Day Rate' && unit === 'hours' ? 24 : 1)
  const amount = Number(rate) * billableQuantity
  return Number.isFinite(amount) ? amount.toFixed(2) : '—'
}

export default function DailyCostSheet() {
  const { print, printSheet } = useCostPrint()
  const [dailyPrintOpen, setDailyPrintOpen] = useState(false)
  const [milestoneLabel, setMilestoneLabel] = useState('Spud date & time')
  const [printOpen, setPrintOpen] = useState(false)
  const [printBusy, setPrintBusy] = useState(false)
  const [printError, setPrintError] = useState('')
  const { entryId = '' } = useParams()
  const { can } = useAuth()
  const canReadCostingSets = can('costing-sets:read')
  const [day, setDay] = useState<DailyCostDay | null>(null)
  // Well progress milestones (spud / progress completion) for this sheet's AFE scope.
  const [progress, setProgress] = useState<WellProgressScope | null>(null)
  const [progressDirty, setProgressDirty] = useState(false)
  const progressSaveRef = useRef<(() => Promise<boolean>) | null>(null)
  const [baseline, setBaseline] = useState<DailyCostBaseline | null>(null)
  const [reference, setReference] = useState<DailyCostReference | null>(null)
  const [payload, setPayload] = useState<DailyCostSavePayload>({ remarks: '', services: [], consumables: [], tangibles: [], other_expenses: [] })
  const [preview, setPreview] = useState<DailyCostPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [previewRetry, setPreviewRetry] = useState(0)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [notice, setNotice] = useState('')
  const [lineEditor, setLineEditor] = useState<{ kind: DailyCostLineKind; index: number | null } | null>(null)
  const [lineDelete, setLineDelete] = useState<LineDelete>(null)
  const [statusAction, setStatusAction] = useState<StatusAction | null>(null)
  const [statusRemarks, setStatusRemarks] = useState('')
  const [statusBusy, setStatusBusy] = useState(false)
  const [statusError, setStatusError] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [importBusy, setImportBusy] = useState(false)
  const [importRows, setImportRows] = useState<ImportRow[]>([])
  const [importFileName, setImportFileName] = useState('')
  const [importErrors, setImportErrors] = useState<string[]>([])
  const [importError, setImportError] = useState('')
  const [previousDay, setPreviousDay] = useState<DailyCostDay | null>(null)
  const [previousBusy, setPreviousBusy] = useState(false)
  const [previousError, setPreviousError] = useState('')
  const [copyBusy, setCopyBusy] = useState(false)
  const [costingSets, setCostingSets] = useState<CostingSet[]>([])
  const [costingSetError, setCostingSetError] = useState('')
  const [setPickerGroup, setSetPickerGroup] = useState<CostingSetGroup | null>(null)
  const [selectedServiceIndices, setSelectedServiceIndices] = useState<number[]>([])
  const [serviceSelectionResetKey, setServiceSelectionResetKey] = useState(0)
  const [bulkScopeOpen, setBulkScopeOpen] = useState(false)
  const [amendments, setAmendments] = useState<DailyCostAmendment[]>([])
  const fileInput = useRef<HTMLInputElement>(null)
  const clearServiceSelection = () => {
    setSelectedServiceIndices([])
    setServiceSelectionResetKey(value => value + 1)
  }

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [dayData, baselineData, referenceData] = await Promise.all([
        api<DailyCostDay>(`/daily-cost/entries/${entryId}`),
        api<DailyCostBaseline>(`/daily-cost/entries/${entryId}/baseline`),
        api<DailyCostReference>('/daily-cost/reference'),
      ])
      setDay(dayData)
      setBaseline(baselineData)
      setReference(referenceData)
      setProgress(dayData.progress)
      setPayload(saveFromDay(dayData))
      setSelectedServiceIndices([])
      setServiceSelectionResetKey(value => value + 1)
      setPreview(null)
      setPreviewError('')
      setSaveError('')
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'The daily cost sheet could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [entryId])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    let active = true
    listEntryAmendments(entryId)
      .then(rows => { if (active) setAmendments(rows) })
      .catch(() => { if (active) setAmendments([]) })
    return () => { active = false }
  }, [entryId, day?.entry.status])

  useEffect(() => {
    if (!canReadCostingSets) {
      setCostingSets([])
      setCostingSetError('')
      return
    }
    let active = true
    setCostingSetError('')
    api<CostingSet[]>('/costing-sets')
      .then(records => { if (active) setCostingSets(records) })
      .catch(caught => {
        if (active) {
          setCostingSets([])
          setCostingSetError(caught instanceof Error ? caught.message : 'Costing sets could not be loaded')
        }
      })
    return () => { active = false }
  }, [canReadCostingSets])

  const selectedServiceLines = useMemo(
    () => selectedServiceIndices.flatMap(index => {
      const line = payload.services[index]
      return line ? [{ index, line }] : []
    }),
    [selectedServiceIndices, payload.services],
  )
  const originalPayload = useMemo(() => day ? saveFromDay(day) : null, [day])
  const dirty = Boolean(originalPayload && JSON.stringify(payload) !== JSON.stringify(originalPayload))
  const editable = Boolean(day && day.entry.status === 'draft' && can('daily-cost:update'))
  const hasPreviewForEdits = Boolean(preview && dirty)
  const canExport = can('daily-cost:export')
  const saveDisabled = !dirty || saving || previewing || Boolean(previewError)

  useEffect(() => {
    if (!day || !dirty || !editable || loading) {
      setPreview(null)
      setPreviewError('')
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setPreviewing(true)
      setPreviewError('')
      try {
        const priced = await api<DailyCostPreview>(`/daily-cost/entries/${entryId}/preview`, {
          method: 'PUT', body: body(payload), signal: controller.signal,
        })
        setPreview(priced)
      } catch (caught) {
        if (controller.signal.aborted) return
        setPreview(null)
        setPreviewError(caught instanceof Error ? caught.message : 'Daily cost preview could not be calculated')
      } finally {
        if (!controller.signal.aborted) setPreviewing(false)
      }
    }, 400)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [day, dirty, editable, entryId, loading, payload, previewRetry])

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  // Page-level unsaved-changes guard (convention 15): navigation, back and tab
  // close first offer to save this sheet — including unsaved progress dates.
  // The beforeunload handler above stays for the raw reload case.
  const leaveGuard = useUnsavedChangesGuard({
    when: dirty || progressDirty,
    onSave: async () => {
      if (progressDirty && !(await (progressSaveRef.current?.() ?? true))) return false
      if (dirty) return save()
      return true
    },
    title: 'Leave without saving?',
    message: 'This daily cost sheet has changes that are not saved yet — cost lines or the well progress dates. Save them before leaving, or discard them deliberately.',
  })

  const addOrEditLine = (lineOrLines: EditableDailyCostLine | EditableDailyCostLine[]) => {
    if (!lineEditor) return
    const group = GROUP_KEY[lineEditor.kind]
    const index = lineEditor.index
    const linesToAdd = Array.isArray(lineOrLines) ? lineOrLines : [lineOrLines]
    setPayload(current => {
      const rows = [...current[group]] as EditableDailyCostLine[]
      if (index === null) {
        rows.push(...linesToAdd)
      } else {
        rows[index] = linesToAdd[0]
      }
      return { ...current, [group]: rows }
    })
    if (group === 'services') clearServiceSelection()
    setPreview(null)
    setLineEditor(null)
    setNotice(group === 'other_expenses'
      ? 'Other expense updated. The AFE remaining balance is being recalculated with the deduction; save to commit the change.'
      : `${linesToAdd.length > 1 ? `${linesToAdd.length} lines` : 'Line'} updated. Preview and AFE remaining balance are recalculating; save to commit the change.`)
  }

  const removeLine = () => {
    if (!lineDelete) return
    const group = GROUP_KEY[lineDelete.kind]
    const { index } = lineDelete
    setPayload(current => ({ ...current, [group]: current[group].filter((_row, rowIndex) => rowIndex !== index) }))
    if (group === 'services') clearServiceSelection()
    setPreview(null)
    setLineDelete(null)
    setNotice('Line removed from the draft. Save to commit the change.')
  }

  const applyBulkServiceScope = (updates: { index: number; line: DailyCostServiceInput }[]) => {
    const updateByIndex = new Map(updates.map(item => [item.index, item.line]))
    setPayload(current => ({
      ...current,
      services: current.services.map((line, index) => updateByIndex.get(index) ?? line),
    }))
    clearServiceSelection()
    setBulkScopeOpen(false)
    setPreview(null)
    setPreviewError('')
    setNotice(`${updates.length} service line${updates.length === 1 ? '' : 's'} updated in the draft. Preview will validate the changes; save to commit them.`)
  }

  const save = async (): Promise<boolean> => {
    if (!day) return false
    setSaving(true)
    setSaveError('')
    setNotice('')
    try {
      const updated = await api<DailyCostDay>(`/daily-cost/entries/${entryId}`, { method: 'PUT', body: body(payload) })
      setDay(updated)
      setProgress(current => updated.progress ?? current)
      setPayload(saveFromDay(updated))
      setPreview(null)
      setNotice('Daily cost sheet saved. Actual-to-date and remaining AFE balance have been refreshed.')
      return true
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : 'The daily cost sheet could not be saved')
      return false
    } finally {
      setSaving(false)
    }
  }

  // Drill days repeat the same crew, service and consumable pattern, so the
  // previous well-day sheet is offered as a starting point for today's entry.
  const loadPreviousDay = useCallback(async () => {
    if (!day) return
    setPreviousBusy(true)
    setPreviousError('')
    try {
      const candidates = await api<{ id: string; cost_date: string; daily_cost_code: string }[]>(
        `/daily-cost/entries${entryQuery({ afe_id: day.entry.afe_id, to: day.entry.cost_date })}`,
      )
      const previous = candidates
        .filter(item => item.cost_date < day.entry.cost_date)
        .sort((left, right) => right.cost_date.localeCompare(left.cost_date))[0]
      if (!previous) {
        setPreviousDay(null)
        setPreviousError('No earlier daily sheet exists for this AFE yet. Enter today\u2019s actuals from scratch.')
        return
      }
      setPreviousDay(await api<DailyCostDay>(`/daily-cost/entries/${previous.id}`))
    } catch (caught) {
      setPreviousDay(null)
      setPreviousError(caught instanceof Error ? caught.message : 'The previous daily sheet could not be loaded')
    } finally {
      setPreviousBusy(false)
    }
  }, [day])

  useEffect(() => { void loadPreviousDay() }, [loadPreviousDay])

  const copyPreviousDay = async (mode: 'replace' | 'append') => {
    if (!previousDay) return
    setCopyBusy(true)
    setNotice('')
    try {
      const source = saveFromDay(previousDay)
      const copyList = <T extends { id?: string | null }>(rows: T[]) => rows.map(line => ({ ...line, id: null }))
      const copied = {
        services: copyList(source.services), consumables: copyList(source.consumables),
        tangibles: copyList(source.tangibles), other_expenses: copyList(source.other_expenses),
      }
      setPayload(current => ({
        remarks: current.remarks,
        services: mode === 'replace' ? copied.services : [...current.services, ...copied.services],
        consumables: mode === 'replace' ? copied.consumables : [...current.consumables, ...copied.consumables],
        tangibles: mode === 'replace' ? copied.tangibles : [...current.tangibles, ...copied.tangibles],
        other_expenses: mode === 'replace' ? copied.other_expenses : [...current.other_expenses, ...copied.other_expenses],
      }))
      setPreview(null)
      const count = source.services.length + source.consumables.length + source.tangibles.length
        + source.other_expenses.length
      setNotice(count
        ? `${count} line${count === 1 ? '' : 's'} copied from ${previousDay.entry.daily_cost_code} (${displayDate(previousDay.entry.cost_date)}). Review quantities, dates and rates before saving.`
        : `${previousDay.entry.daily_cost_code} has no lines to copy.`)
    } finally {
      setCopyBusy(false)
    }
  }

  const completeStatusAction = async () => {
    if (!day || !statusAction) return
    if (statusAction === 'reopen' && statusRemarks.trim().length < 3) {
      setStatusError('Give a reason of at least 3 characters for reopening this sheet.')
      return
    }
    setStatusBusy(true)
    setStatusError('')
    try {
      const updated = await api<DailyCostDay>(`/daily-cost/entries/${entryId}/${statusAction}`, {
        method: 'POST', body: body({ remarks: statusRemarks.trim() }),
      })
      setDay(updated)
      setPayload(saveFromDay(updated))
      setPreview(null)
      setStatusAction(null)
      setStatusRemarks('')
      setNotice(statusAction === 'submit' ? 'Daily cost sheet submitted and locked for editing.' : 'Daily cost sheet reopened as Draft.')
    } catch (caught) {
      setStatusError(caught instanceof Error ? caught.message : `Could not ${statusAction} this sheet`)
    } finally {
      setStatusBusy(false)
    }
  }

  const readImportFile = async (file?: File) => {
    if (!file) return
    setImportError('')
    setImportErrors([])
    try {
      const parsed = await parseImportFile(file)
      if (!parsed.rows.length) throw new Error('This file contains no data rows.')
      setImportFileName(file.name)
      setImportRows(parsed.rows)
    } catch (caught) {
      setImportRows([])
      setImportFileName('')
      setImportError(caught instanceof Error ? caught.message : 'This file could not be read')
    }
  }

  const importDailyCosts = async () => {
    if (!importRows.length) return
    setImportBusy(true)
    setImportError('')
    setImportErrors([])
    try {
      const result = await api<DailyCostImportResult>(`/daily-cost/entries/${entryId}/import`, {
        method: 'POST', body: body({ rows: importRows }),
      })
      if (!result.success) {
        setImportErrors(result.errors)
        return
      }
      setImportOpen(false)
      setImportRows([])
      setImportFileName('')
      await load()
      setNotice(`${result.imported_count} line${result.imported_count === 1 ? '' : 's'} imported and validated. Existing lines were retained.`)
    } catch (caught) {
      setImportError(caught instanceof Error ? caught.message : 'Import could not be completed')
    } finally {
      setImportBusy(false)
    }
  }

  const recordExport = async (format: 'csv' | 'xlsx' | 'pdf', recordCount: number) => {
    await api('/daily-cost/export-audit', { method: 'POST', body: body({
      module: 'day-sheet', format, record_count: recordCount, include_deleted: false,
    }) })
  }

  const applyCostingSet = (costingSet: CostingSet) => {
    if (!day || !baseline || !reference) return
    const available = costingSet.items.filter(item => item.is_available)
    let skipped = costingSet.items.length - available.length
    let addedCount = 0
    const nextServices = payload.services.slice()
    const nextConsumables = payload.consumables.slice()
    const nextTangibles = payload.tangibles.slice()
    const preferredActivityId = payload.services[0]?.activity_id
      ?? reference.activities.find(item => deriveClassification(item) === 'Planned')?.id
      ?? reference.activities[0]?.id
      ?? ''
    const activity = reference.activities.find(item => item.id === preferredActivityId)
    const subActivity = reference.sub_activities.find(item =>
      item.well_id === day.entry.well_id && item.activity_id === preferredActivityId,
    )
    const defaultSection = baseline.sections[0]
    const defaultPhase = defaultSection?.phases[0]
    const duplicateServices = new Set(nextServices.map(line => `${line.service_id}:${line.sub_activity_id ?? ''}`))
    const duplicateCatalogueItems = new Set([
      ...nextConsumables.map(line => `${line.item_kind}:${line.item_id}:${line.activity_id}:${line.sub_activity_id ?? ''}`),
      ...nextTangibles.map(line => `tangible:${line.tangible_id}:${line.activity_id}:${line.sub_activity_id ?? ''}`),
    ])

    if (!activity || !subActivity) {
      skipped += available.length
    } else if (deriveClassification(activity) !== 'Planned' && !subActivity.responsible_party.trim() && costingSet.item_group !== 'services') {
      skipped += available.length
    } else if (costingSet.item_group === 'services') {
      for (const item of available) {
        const service = reference.services.find(option => option.id === item.item_id)
        const rate = baseline.service_rates.find(option => option.service_id === item.item_id)
        if (!service || !rate) { skipped += 1; continue }
        const sectionId = rate.hole_section_id ?? defaultSection?.hole_section_id ?? null
        const phaseId = rate.phase_id ?? (sectionId === defaultSection?.hole_section_id ? defaultPhase?.phase_id : null) ?? null
        const duplicateKey = `${service.id}:${subActivity.id}`
        const vendor = service.vendor_id ? reference.vendors.find(option => option.id === service.vendor_id) : null
        const category = (rate.charge_category || 'Operation') as DailyCostServiceInput['charge_category']
        const quantityUnit: DailyQuantityUnit = rate.charging_basis === 'Per Service Rate' ? 'service'
          : rate.charging_basis === 'Per Section Rate' ? 'section'
            : DAILY_ONE_TIME_CATEGORIES.includes(category) ? 'unit' : 'days'
        if (duplicateServices.has(duplicateKey)
          || (!baseline.exchange_rates[rate.currency] && rate.currency !== 'USD')
          || (rate.charging_basis !== 'Day Rate' && !sectionId)
          || (deriveClassification(activity) !== 'Planned' && !vendor && !service.vendor_name && !subActivity.responsible_party)) {
          skipped += 1
          continue
        }
        const isPlanned = deriveClassification(activity) === 'Planned'
        nextServices.push({
          id: null,
          activity_id: activity.id,
          hole_section_id: sectionId,
          phase_id: sectionId ? phaseId : null,
          sub_activity_id: subActivity.id,
          vendor_id: isPlanned ? null : vendor?.id ?? null,
          party_name: isPlanned ? 'Not Applicable' : subActivity.responsible_party || vendor?.vendor_name || service.vendor_name || '',
          quantity: '1',
          currency: rate.currency,
          override_rate: null,
          override_reason: '',
          remarks: `Added from costing set ${costingSet.name}`,
          service_id: service.id,
          baseline_service_rate_id: rate.id,
          charging_basis: rate.charging_basis,
          charge_category: category,
          quantity_unit: quantityUnit,
        })
        duplicateServices.add(duplicateKey)
        addedCount += 1
      }
    } else if (costingSet.item_group === 'tangibles') {
      for (const item of available) {
        const catalogueItem = reference.catalogue_items.find(option => option.item_kind === 'tangible' && option.id === item.item_id)
        const snapshot = baseline.catalogue_rates.find(option => option.item_kind === 'tangible' && option.id === item.item_id)
        const duplicateKey = `tangible:${item.item_id}:${activity.id}:${subActivity.id}`
        if (!catalogueItem || !snapshot || duplicateCatalogueItems.has(duplicateKey) || (!baseline.exchange_rates[snapshot.currency] && snapshot.currency !== 'USD')) {
          skipped += 1
          continue
        }
        nextTangibles.push({
          id: null,
          activity_id: activity.id,
          hole_section_id: defaultSection?.hole_section_id ?? null,
          phase_id: defaultPhase?.phase_id ?? null,
          sub_activity_id: subActivity.id,
          vendor_id: null,
          party_name: subActivity.responsible_party || '',
          quantity: '1',
          currency: snapshot.currency,
          override_rate: null,
          override_reason: '',
          remarks: `Added from costing set ${costingSet.name}`,
          tangible_id: catalogueItem.id,
        })
        duplicateCatalogueItems.add(duplicateKey)
        addedCount += 1
      }
    } else {
      const categoryByKind: Record<ConsumableKind, ConsumableCategory> = {
        mud_chemical: 'Mud Chemicals', cement_additive: 'Cement Additives', fuel: 'Fuel', drill_bit: 'Drill Bits',
      }
      for (const item of available) {
        if (item.item_kind === 'service' || item.item_kind === 'tangible') { skipped += 1; continue }
        const kind = item.item_kind as ConsumableKind
        const catalogueItem = reference.catalogue_items.find(option => option.item_kind === kind && option.id === item.item_id)
        const snapshot = baseline.catalogue_rates.find(option => option.item_kind === kind && option.id === item.item_id)
        const duplicateKey = `${kind}:${item.item_id}:${activity.id}:${subActivity.id}`
        if (!catalogueItem || !snapshot || duplicateCatalogueItems.has(duplicateKey)
          || !defaultSection || (!baseline.exchange_rates[snapshot.currency] && snapshot.currency !== 'USD')) {
          skipped += 1
          continue
        }
        nextConsumables.push({
          id: null,
          activity_id: activity.id,
          hole_section_id: defaultSection.hole_section_id,
          phase_id: defaultPhase?.phase_id ?? null,
          sub_activity_id: subActivity.id,
          vendor_id: null,
          party_name: subActivity.responsible_party || '',
          quantity: '1',
          currency: snapshot.currency,
          override_rate: null,
          override_reason: '',
          remarks: `Added from costing set ${costingSet.name}`,
          category: categoryByKind[kind],
          item_kind: kind,
          item_id: catalogueItem.id,
        })
        duplicateCatalogueItems.add(duplicateKey)
        addedCount += 1
      }
    }

    if (addedCount) {
      if (costingSet.item_group === 'services') clearServiceSelection()
      setPayload(current => ({
        ...current,
        services: nextServices,
        consumables: nextConsumables,
        tangibles: nextTangibles,
      }))
      setPreview(null)
      setPreviewError('')
      setNotice(`${addedCount} line${addedCount === 1 ? '' : 's'} added from “${costingSet.name}”.${skipped ? ` ${skipped} unavailable, duplicate or unpriced item(s) skipped.` : ''} Review the draft, then save.`)
    } else {
      setNotice(`No lines were added from “${costingSet.name}”. ${skipped} item(s) were unavailable, duplicated, missing a locked AFE rate or unsupported by the current well setup.`)
    }
    setSetPickerGroup(null)
  }

  if (loading && !day) return <Box py={12} display="grid" sx={{ placeItems: 'center' }}><CircularProgress/></Box>
  if (loadError || !day || !baseline || !reference) return <>
    <PageHeading eyebrow="DAILY COST MANAGEMENT / DAILY SHEET" title="Daily cost sheet" subtitle="The daily sheet could not be opened." action={<Button component={RouterLink} to="/daily-cost" startIcon={<ArrowBackRounded/>}>Back to register</Button>}/>
    <ErrorMessage message={loadError || 'This daily sheet is not available in the workspace.'}/>
  </>

  const entry = day.entry
  const standard = entry.standard_currency
  const allPreview = preview
    ? [...preview.services, ...preview.consumables, ...preview.tangibles, ...preview.other_expenses] : []
  const allSaved = [...day.services, ...day.consumables, ...day.tangibles, ...day.other_expenses]
  const savedAmount = Number(entry.total_cost)
  const workingAmount = hasPreviewForEdits ? Number(preview?.total_cost ?? savedAmount) : savedAmount
  const actualToDate = Number(day.comparison.actual_to_date) + (hasPreviewForEdits ? workingAmount - savedAmount : 0)
  const remaining = Number(day.comparison.planned_total) - actualToDate
  const upaToDate = Number(day.comparison.upa_to_date) + (hasPreviewForEdits
    ? Number(preview?.upa_total ?? 0) - Number(entry.upa_total) : 0)
  const nptToDate = Number(day.comparison.npt_to_date) + (hasPreviewForEdits
    ? Number(preview?.npt_total ?? 0) - Number(entry.npt_total) : 0)
  const savedActualByBudget = new Map<string, number>()
  for (const line of allSaved) savedActualByBudget.set(line.budget_key, (savedActualByBudget.get(line.budget_key) ?? 0) + Number(line.standard_amount))
  const previewActualByBudget = new Map<string, number>()
  for (const line of allPreview) previewActualByBudget.set(line.budget_key, (previewActualByBudget.get(line.budget_key) ?? 0) + Number(line.standard_amount))
  const comparisonRows: DailyCostComparisonLine[] = day.comparison.budget_lines.map(line => {
    const delta = hasPreviewForEdits
      ? (previewActualByBudget.get(line.budget_key) ?? 0) - (savedActualByBudget.get(line.budget_key) ?? 0) : 0
    const actual = Number(line.actual_to_date) + delta
    return { ...line, actual_to_date: actual.toFixed(2), balance: (Number(line.planned) - actual).toFixed(2) }
  })
  if (hasPreviewForEdits && preview) {
    const knownKeys = new Set(comparisonRows.map(line => line.budget_key))
    for (const [group, lines] of [
      ['Services', preview.services], ['Consumables', preview.consumables], ['Tangibles', preview.tangibles],
      ['Other Expenses', preview.other_expenses],
    ] as const) {
      const added = new Map<string, { code: string; name: string; amount: number }>()
      for (const line of lines) {
        if (knownKeys.has(line.budget_key)) continue
        const previous = added.get(line.budget_key) ?? { code: '', name: '', amount: 0 }
        if ('service_code' in line) { previous.code = line.service_code; previous.name = line.service_name }
        else if ('item_code' in line) { previous.code = line.item_code; previous.name = line.item_name }
        else if ('expense_type' in line) { previous.code = line.expense_type; previous.name = line.expense_type_label }
        else { previous.code = line.tangible_code; previous.name = line.tangible_name }
        previous.amount += Number(line.standard_amount)
        added.set(line.budget_key, previous)
      }
      for (const [budgetKey, item] of added) {
        knownKeys.add(budgetKey)
        comparisonRows.push({
          budget_key: budgetKey, cost_group: group, budget_kind: budgetKey.split(':')[0],
          item_code: item.code, item_name: item.name, planned: '0.00',
          actual_to_date: item.amount.toFixed(2), balance: (-item.amount).toFixed(2), is_planned: false,
        })
      }
    }
  }

  // Other expenses are their own group: they are part of the day's cost and are
  // simultaneously deducted from the AFE amount, so both halves stay visible.
  const savedOther = Number(entry.other_expenses_total)
  const workingOther = hasPreviewForEdits ? Number(preview?.other_expenses_total ?? savedOther) : savedOther
  const otherDelta = workingOther - savedOther
  const trackedActualToDate = Number(day.comparison.tracked_actual_to_date)
    + (hasPreviewForEdits ? workingAmount - savedAmount - otherDelta : 0)
  const otherToDate = Number(day.comparison.other_expenses_to_date) + otherDelta
  const otherItems = (hasPreviewForEdits ? preview?.other_expenses : day.other_expenses) ?? []
  const otherItemSummary = otherItems.length
    ? [...new Set(otherItems.map(line => line.expense_type_label))].join(', ')
    : [...new Set(day.other_expenses.map(line => line.expense_type_label))].join(', ')

  const scopeName = (sectionId: string | null, phaseId: string | null) => {
    if (!sectionId) return 'No hole section'
    const section = baseline.sections.find(item => item.hole_section_id === sectionId)
    if (!section) return 'Section outside baseline'
    const phase = section.phases.find(item => item.phase_id === phaseId)
    return `${section.section_code}${phase ? ` · ${phase.phase_code}` : ''}`
  }
  const activityName = (id: string) => {
    const activity = reference.activities.find(item => item.id === id)
    return activity ? `${activity.activity_code} · ${activity.activity_name}` : 'Activity unavailable'
  }
  const vendorName = (vendorId: string | null, party: string, activityId?: string) => {
    const act = activityId ? reference.activities.find(item => item.id === activityId) : null
    if (act && deriveClassification(act) === 'Planned') {
      return 'Not Applicable'
    }
    const vendor = reference.vendors.find(item => item.id === vendorId)
    return vendor?.vendor_name || party || (party === 'Not Applicable' ? 'Not Applicable' : '—')
  }
  const getGridRows = (kind: DailyCostLineKind): GridLine[] => {
    const group = GROUP_KEY[kind]
    const inputs = payload[group] as EditableDailyCostLine[]
    // Priced rows come from the preview while the sheet is dirty, otherwise from the
    // saved sheet; either way they line up with `inputs` in order.
    const outputs = (preview ? preview[group] : !dirty ? day[group] : []) as unknown as AnyDailyCostLine[]
    return inputs.map((line, index) => {
      const priced = outputs[index]
      let item = '—'
      let sourceRate = ''
      let sourceCurrency = line.currency
      let sourceLabel = ''
      if (kind === 'service' && 'service_id' in line) {
        const service = reference.services.find(option => option.id === line.service_id)
        const rate = baseline.service_rates.find(option => option.id === line.baseline_service_rate_id)
        const savedLine = day.services.find(option => option.id === line.id && option.service_id === line.service_id)
        item = rate?.display_name || (savedLine ? `${savedLine.service_code} · ${savedLine.service_name}` : service?.display_name) || 'Service unavailable'
        sourceRate = line.override_rate ?? rate?.unit_rate ?? '0'
        sourceCurrency = line.currency || rate?.currency || standard
        sourceLabel = line.override_rate !== null ? 'Daily override' : rate ? 'Locked AFE' : 'Manual UPA/NPT'
      } else if (kind === 'consumable' && 'item_kind' in line) {
        const snapshot = baseline.catalogue_rates.find(option => option.id === line.item_id && option.item_kind === line.item_kind)
        const itemOption = reference.catalogue_items.find(option => option.id === line.item_id)
        const savedLine = day.consumables.find(option => option.id === line.id && option.item_id === line.item_id)
        item = snapshot?.display_name || savedLine?.item_name || itemOption?.display_name || 'Catalogue item unavailable'
        sourceRate = line.override_rate ?? snapshot?.captured_rate ?? '0'
        sourceCurrency = line.currency || snapshot?.currency || standard
        sourceLabel = line.override_rate !== null ? 'Daily override' : snapshot ? `Rate rev ${snapshot.revision_number || 'baseline'}` : 'Manual rate'
      } else if (kind === 'other' && 'expense_type' in line) {
        const pricedOther = priced && 'expense_type' in priced ? priced : undefined
        const label = pricedOther?.expense_type_label
          ?? otherExpenseLabel(line.expense_type, reference.other_expense_types ?? [])
        const detail = (pricedOther?.expense_description ?? line.expense_description).trim()
        item = detail ? `${label} · ${detail}` : label
        sourceRate = line.unit_rate || '0'
        sourceCurrency = line.currency || standard
        sourceLabel = 'No AFE allowance'
      } else if (kind === 'tangible' && 'tangible_id' in line) {
        const snapshot = baseline.catalogue_rates.find(option => option.id === line.tangible_id && option.item_kind === 'tangible')
        const itemOption = reference.catalogue_items.find(option => option.id === line.tangible_id)
        const savedLine = day.tangibles.find(option => option.id === line.id && option.tangible_id === line.tangible_id)
        item = snapshot?.display_name || savedLine?.tangible_name || itemOption?.display_name || 'Tangible unavailable'
        sourceRate = line.override_rate ?? snapshot?.captured_rate ?? '0'
        sourceCurrency = line.currency || snapshot?.currency || standard
        sourceLabel = line.override_rate !== null ? 'Daily override' : snapshot ? `Rate rev ${snapshot.revision_number || 'baseline'}` : 'Manual rate'
      }
      let localAmount = '—'
      if (priced) localAmount = priced.amount
      else if ('cost_items' in line && line.cost_items?.length) localAmount = String(line.cost_items.reduce((sum, item) => sum + Number(item.amount), 0))
      else if (line.override_rate !== null) localAmount = amountForRate(
        line.override_rate, line.quantity, 'quantity_unit' in line ? line.quantity_unit : 'unit',
        'charging_basis' in line ? line.charging_basis ?? undefined : undefined,
        'charge_category' in line ? line.charge_category : undefined,
      )
      else if (kind === 'service' && 'quantity_unit' in line) localAmount = amountForRate(
        sourceRate, line.quantity, line.quantity_unit,
        'charging_basis' in line ? line.charging_basis ?? undefined : undefined,
        'charge_category' in line ? line.charge_category : undefined,
      )
      else if (sourceRate !== '0') localAmount = amountForRate(sourceRate, line.quantity, 'unit')
      const activity = activityName(line.activity_id)
      const vendor = vendorName(line.vendor_id, line.party_name, line.activity_id)
      const sub = priced
        ? (priced.sub_activity_code ? `${priced.sub_activity_code} · ${priced.sub_activity_name}` : priced.sub_activity_name || '—')
        : reference.sub_activities.find(item => item.id === line.sub_activity_id)?.display_name ?? '—'
      const resolvedDepth = priced?.actual_depth != null
        ? formatDepthMeters(priced.actual_depth, 'm')
        : formatDepthMeters(line.actual_depth, line.actual_depth_unit ?? 'm')
      return {
        id: line.id || `${kind}-${index}`, lineIndex: index, item, activity,
        section: scopeName(line.hole_section_id, line.phase_id),
        actualDepth: resolvedDepth,
        subActivity: sub,
        vendor, quantity: line.quantity, quantityUnit: 'quantity_unit' in line ? line.quantity_unit : '',
        rate: `${dailyMoney(priced?.effective_rate ?? sourceRate, priced?.currency ?? sourceCurrency)}${sourceLabel ? ` · ${sourceLabel}` : ''}`,
        currency: priced?.currency ?? sourceCurrency,
        amount: dailyMoney(localAmount, priced?.currency ?? sourceCurrency),
        standardAmount: priced ? dailyMoney(priced.standard_amount, standard) : 'Preview pending',
        usdAmount: priced ? dailyMoney(priced.usd_amount ?? priced.standard_amount, 'USD') : 'Preview pending',
        source: priced?.rate_source ?? sourceLabel,
        budget: priced?.budget_name ?? 'AFE comparison pending',
        overrideReason: line.override_reason,
        remarks: line.remarks,
      }
    })
  }

  const makeColumns = (kind: DailyCostLineKind): ColDef<GridLine>[] => {
    const columns: ColDef<GridLine>[] = [
      { headerName: 'ITEM', field: 'item', minWidth: 190, flex: 1.2 },
      { headerName: 'ACTIVITY', field: 'activity', minWidth: 140 },
      { headerName: 'SUB ACTIVITY', field: 'subActivity', minWidth: 140 },
      { headerName: 'SECTION / PHASE', field: 'section', minWidth: 140 },
      { headerName: 'ACTUAL DEPTH (m)', field: 'actualDepth', minWidth: 135 },
      { headerName: 'RESPONSIBLE PARTY', field: 'vendor', minWidth: 150 },
      { headerName: 'QUANTITY', field: 'quantity', minWidth: 115, valueGetter: params => params.data ? `${params.data.quantity} ${params.data.quantityUnit}`.trim() : '' },
      { headerName: 'RATE / SOURCE', field: 'rate', minWidth: 190, tooltipField: 'overrideReason' },
      { headerName: 'NATIVE AMOUNT', field: 'amount', minWidth: 145 },
      { headerName: `AFE AMOUNT (${standard})`, field: 'standardAmount', minWidth: 155 },
      ...(standard.toUpperCase() !== 'USD' ? [{ headerName: 'USD AMOUNT (STD)', field: 'usdAmount' as const, minWidth: 150 }] : []),
      { headerName: 'AFE BUDGET MATCH', field: 'budget', minWidth: 185 },
    ]
    // The remark is what explains an unbudgeted charge, so it gets a column here.
    if (kind === 'other') columns.splice(1, 0, { headerName: 'REMARKS', field: 'remarks', minWidth: 240, flex: 1 })
    if (editable) columns.push({
      headerName: 'ACTIONS', field: 'id', minWidth: 118, width: 118, sortable: false,
      cellRenderer: (params: ICellRendererParams<GridLine>) => params.data ? <Box display="flex" alignItems="center" height="100%" gap={.2}>
        <Tooltip title="Edit line"><Button size="small" aria-label={`Edit ${params.data.item}`} onClick={() => setLineEditor({ kind, index: params.data!.lineIndex })}><EditOutlined sx={{ fontSize: 16 }}/></Button></Tooltip>
        <Tooltip title="Remove line"><Button size="small" color="error" aria-label={`Remove ${params.data.item}`} onClick={() => setLineDelete({ kind, index: params.data!.lineIndex, label: params.data!.item })}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button></Tooltip>
      </Box> : null,
    })
    return columns
  }

  const services = getGridRows('service')
  const consumables = getGridRows('consumable')
  const tangibles = getGridRows('tangible')
  const otherExpenses = getGridRows('other')
  const lineCount = payload.services.length + payload.consumables.length + payload.tangibles.length
    + payload.other_expenses.length
  const otherLineCount = payload.other_expenses.length
  const canSubmit = can('daily-cost:submit') && entry.status === 'draft'
  const canReopen = can('daily-cost:reopen') && entry.status === 'submitted'

  const openImport = () => {
    setImportRows([])
    setImportFileName('')
    setImportErrors([])
    setImportError('')
    setImportOpen(true)
  }
  const importHeaders = [
    'line_type', 'activity_code', 'section_code', 'phase_code', 'sub_activity_code',
    'actual_depth', 'actual_depth_unit',
    'vendor_code', 'party_name', 'service_code', 'baseline_service_rate_id', 'charging_basis', 'charge_category',
    'quantity_unit', 'category', 'item_kind', 'item_code', 'quantity', 'currency', 'exchange_rate',
    'override_rate', 'override_reason',
    'expense_type', 'expense_description', 'unit_rate', 'remarks',
  ]
  const exportTemplate = () => {
    const rate = baseline.service_rates[0]
    const section = baseline.sections.find(item => item.hole_section_id === rate?.hole_section_id)
    const phase = section?.phases.find(item => item.phase_id === rate?.phase_id)
    const category = rate?.charge_category || 'Operation'
    const unit = rate?.charging_basis === 'Per Service Rate' ? 'service'
      : rate?.charging_basis === 'Per Section Rate' ? 'section'
        : ['Mobilization', 'Demobilization', 'Fixed Charge'].includes(category) ? 'unit' : 'days'
    const activityCode = reference.activities[0]?.activity_code || 'DRILL'
    const subActivityCode = reference.sub_activities.find(item => item.well_id === entry.well_id)?.sub_activity_code ?? ''
    downloadTemplate('daily-cost-import-template.csv', importHeaders, [
      {
        line_type: 'Service', activity_code: activityCode,
        section_code: section?.section_code ?? '', phase_code: phase?.phase_code ?? '',
        sub_activity_code: subActivityCode,
        actual_depth: section?.to_depth ?? '', actual_depth_unit: 'm',
        vendor_code: '', service_code: rate?.service_code ?? 'SERVICE-001',
        baseline_service_rate_id: rate?.id ?? '', charging_basis: rate?.charging_basis ?? 'Day Rate',
        charge_category: category, quantity_unit: unit, quantity: '1', currency: rate?.currency ?? standard,
        exchange_rate: '',
        override_rate: '', override_reason: '', remarks: '',
      },
      {
        // An unexpected charge: no AFE allowance, mandatory remark, own unit rate.
        line_type: 'Other', activity_code: reference.activities.find(item => /npt|non.?productive/i.test(`${item.activity_code} ${item.activity_name}`))?.activity_code ?? activityCode,
        section_code: section?.section_code ?? '', phase_code: phase?.phase_code ?? '',
        sub_activity_code: subActivityCode,
        actual_depth: '', actual_depth_unit: 'm',
        vendor_code: '', party_name: 'Operator',
        expense_type: 'LIH', expense_description: '6 5/8 in BHA left in hole', unit_rate: '250000',
        quantity: '1', quantity_unit: 'unit', currency: 'USD', exchange_rate: '', remarks: 'Tools lost in hole during tripping',
      },
    ])
  }
  const openStatus = (action: StatusAction) => {
    setStatusRemarks('')
    setStatusError('')
    setStatusAction(action)
  }

  const currentGroupActual = (group: DailyCostGroup) => {
    const lineGroup = group === 'Services' ? preview?.services
      : group === 'Consumables' ? preview?.consumables
        : group === 'Tangibles' ? preview?.tangibles : preview?.other_expenses
    if (!hasPreviewForEdits || !lineGroup) {
      return day.comparison.groups.find(item => item.cost_group === group)?.actual_to_date ?? '0'
    }
    const savedGroup = group === 'Services' ? day.services : group === 'Consumables' ? day.consumables
      : group === 'Tangibles' ? day.tangibles : day.other_expenses
    const previous = savedGroup.reduce((sum, line) => sum + Number(line.standard_amount), 0)
    const current = lineGroup.reduce((sum, line) => sum + Number(line.standard_amount), 0)
    const initial = Number(day.comparison.groups.find(item => item.cost_group === group)?.actual_to_date ?? 0)
    return (initial + current - previous).toFixed(2)
  }

  const printDay = async () => {
    if (dirty || !day) return
    setPrintBusy(true)
    setPrintError('')
    try {
      // Re-fetch the saved record, never print an unsaved preview.
      const saved = await api<DailyCostDay>(`/daily-cost/entries/${entry.id}`)
      const params = new URLSearchParams({ to: entry.cost_date, include_draft: 'true' })
      const mudParams = new URLSearchParams({
        rig_id: entry.rig_id, well_id: entry.well_id, to: entry.cost_date, include_draft: 'true',
      })
      const mudBalanceParams = new URLSearchParams({
        rig_id: entry.rig_id, well_id: entry.well_id, view: 'section', to: entry.cost_date,
      })
      const [overviewDays, summary, mudReconciliation, mudBalance] = await Promise.all([
        api<DailyCostDay[]>(`/daily-cost/wells/${entry.well_id}/cost-report?${params}`).catch(() => [saved]),
        api<DailyCostWellSummary>(`/daily-cost/wells/${entry.well_id}/cost-summary?${params}`).catch(() => null),
        api<MudCostReconciliation>(`/mud-cost/reconciliation?${mudParams}`).catch(() => null),
        api<MudCostMaterialBalance>(`/mud-cost/material-balance?${mudBalanceParams}`).catch(() => null),
      ])
      await api('/daily-cost/export-audit', { method: 'POST', body: body({
        module: 'day-sheet', format: 'pdf', record_count: 1, entry_id: entry.id,
        well_id: entry.well_id, include_deleted: entry.is_deleted,
      }) })
      const well = reference?.wells.find(item => item.id === entry.well_id)
      print({
        // The report title names the well scope the sheet costs.
        title: costReportTitle('daily', [saved.progress?.scope ?? progress?.scope], entry.well_name),
        period: displayDate(entry.cost_date), days: [saved],
        overviewDays, summary, mudReconciliation, mudBalance, sections: well?.sections ?? baseline?.sections,
        reportKind: 'daily', milestoneLabel: milestoneLabel.trim() || 'Spud date & time',
      })
      setDailyPrintOpen(false)
    } catch (caught) {
      setPrintError(caught instanceof Error ? caught.message : 'The daily sheet could not be printed')
    } finally { setPrintBusy(false) }
  }

  const statusTitle = statusAction === 'submit' ? 'Submit daily cost sheet?' : 'Reopen this daily cost sheet?'
  const statusSubtitle = statusAction === 'submit'
    ? 'Submission freezes editing and records the current daily actuals in the review workflow.'
    : 'Reopening returns this sheet to Draft so an authorized user can correct it. The reason is written to the audit trail.'

  return <>
    <PageHeading
      eyebrow="DAILY COST MANAGEMENT / DAILY SHEET"
      title={entry.daily_cost_code}
      subtitle={`${entry.well_code} · ${entry.well_name} · ${entry.rig_code} · ${entry.afe_code} ${entry.afe_name} · ${displayDate(entry.cost_date)}`}
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {canExport && <>
          <Tooltip title={dirty ? 'Save or discard changes before printing the saved daily sheet.' : 'Prepare the saved daily report and edit its milestone label.'}><span><Button variant="outlined" startIcon={<PrintOutlined/>} disabled={dirty || saving || printBusy} onClick={() => { setMilestoneLabel('Spud date & time'); setDailyPrintOpen(true) }}>{printBusy ? 'Preparing print…' : 'Print daily sheet'}</Button></span></Tooltip>
          <Button variant="outlined" startIcon={<PrintOutlined/>} onClick={() => setPrintOpen(true)}>Print well costing sheet</Button>
        </>}
        <Button component={RouterLink} to="/daily-cost" variant="outlined" startIcon={<ArrowBackRounded/>}>Register</Button>
        <Button variant="outlined" startIcon={<RefreshRounded/>} onClick={() => void load()} disabled={loading || dirty}>{loading ? 'Refreshing…' : 'Refresh'}</Button>
        {entry.status === 'draft' && editable && <>
          <Tooltip title={previousDay
            ? `Start from ${previousDay.entry.daily_cost_code} · ${displayDate(previousDay.entry.cost_date)}`
            : 'No earlier daily sheet for this AFE'}>
            <span><Button variant="outlined" startIcon={<ContentCopyOutlined/>} disabled={!previousDay || copyBusy} onClick={() => void copyPreviousDay('replace')}>Copy previous day</Button></span>
          </Tooltip>
          <Button variant="outlined" startIcon={<CloudUploadOutlined/>} onClick={openImport}>Import lines</Button>
          {can('daily-cost:update') && <Button variant="contained" startIcon={<SaveOutlined/>} onClick={() => void save()} disabled={saveDisabled}>{saving ? 'Saving…' : 'Save sheet'}</Button>}
        </>}
        {canSubmit && <Tooltip title={dirty ? 'Save changes before submitting.' : 'Submit this daily sheet for review.'}><span><Button variant="contained" color="success" startIcon={<SendRounded/>} onClick={() => openStatus('submit')} disabled={dirty || saving}>Submit</Button></span></Tooltip>}
        {canReopen && <Button variant="outlined" startIcon={<UndoRounded/>} onClick={() => openStatus('reopen')}>Reopen</Button>}
      </Box>}
    />

    {progress && <WellProgressPanel
      wellId={entry.well_id} scopes={[progress]} canEdit={can('daily-cost:update')}
      asOfLabel={`the sheet date (${displayDate(entry.cost_date)})`}
      asOfDate={entry.cost_date}
      onSaved={report => setProgress(report.scopes.find(scope => scope.scope === progress.scope) ?? progress)}
      onDirtyChange={setProgressDirty} saveRef={progressSaveRef}
    />}

    {notice && <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setNotice('')}>{notice}</Alert>}
    {costingSetError && <Alert severity="warning" sx={{ mb: 1.5 }} onClose={() => setCostingSetError('')}>{costingSetError}</Alert>}
    <ErrorMessage message={saveError}/>
    {previewError && <Alert severity="error" sx={{ mb: 1.5 }} action={can('daily-cost:update') ? <Button color="inherit" size="small" onClick={() => { setPreviewError(''); setPreview(null); setPreviewRetry(value => value + 1) }}>Retry preview</Button> : undefined}>{previewError}</Alert>}
    {entry.status === 'submitted' && <Alert severity="info" icon={<LockOutlined/>} sx={{ mb: 1.5 }}>
      Submitted by {entry.submitted_by || 'workspace user'}{entry.submitted_at ? ` on ${new Date(entry.submitted_at).toLocaleString()}` : ''}. The daily sheet is read-only{entry.status_remarks ? ` · ${entry.status_remarks}` : ''}.
    </Alert>}
    {!editable && entry.status === 'draft' && <Alert severity="info" sx={{ mb: 1.5 }}>You can view this Draft. Editing requires the Daily Cost update permission.</Alert>}
    {entry.status === 'draft' && editable && previousDay && <Alert severity="info" icon={<ContentCopyOutlined/>} sx={{ mb: 1.5 }}
      action={<Box display="flex" gap={.6}>
        <Button color="inherit" size="small" disabled={copyBusy} onClick={() => void copyPreviousDay('replace')}>Replace lines</Button>
        <Button color="inherit" size="small" disabled={copyBusy} onClick={() => void copyPreviousDay('append')}>Add to current</Button>
      </Box>}>
      {previousDay.entry.daily_cost_code} · {displayDate(previousDay.entry.cost_date)} carried {previousDay.services.length} service,{' '}
      {previousDay.consumables.length} consumable, {previousDay.tangibles.length} tangible and{' '}
      {previousDay.other_expenses.length} other-expense line(s) totalling{' '}
      {dailyMoney(previousDay.entry.total_cost, standard)}. Copied lines keep the activity, section, vendor and locked AFE rate, and are saved as new lines on this sheet.
    </Alert>}
    {entry.status === 'draft' && editable && previousError && <Alert severity="info" sx={{ mb: 1.5 }}>{previousError}</Alert>}
    {previousBusy && <LinearProgress sx={{ mb: 1.5 }}/>}
    {dirty && <Alert severity="warning" sx={{ mb: 1.5 }} action={can('daily-cost:update') ? <Button color="inherit" size="small" onClick={() => { setPayload(originalPayload ?? payload); setPreview(null); setPreviewError('') }}>Discard changes</Button> : undefined}>
      Unsaved changes{previewing ? ' · recalculating against the locked AFE baseline…' : hasPreviewForEdits ? ' · preview is current' : ' · save to update the register'}.
    </Alert>}

    {standard.toUpperCase() !== 'USD' && (
      <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, mb: 1.5, display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Box flex={1} minWidth={240}>
          <Typography fontSize={12} fontWeight={800}>Standardized USD Conversion Rate ({standard.toUpperCase()} → USD)</Typography>
          <Typography fontSize={11} color="text.secondary">
            USD is the standard currency across all wells. Enter the conversion rate (1 {standard.toUpperCase()} = ? USD) so this sheet’s USD totals remain accurate.
          </Typography>
        </Box>
        <TextField
          size="small"
          type="number"
          required
          disabled={!editable}
          label={`1 ${standard.toUpperCase()} = ? USD`}
          value={payload.usd_exchange_rate ?? entry.usd_exchange_rate ?? '1'}
          onChange={event => setPayload(current => ({ ...current, usd_exchange_rate: event.target.value }))}
          inputProps={{ min: 0.000001, step: 'any' }}
          sx={{ width: 210 }}
        />
        <Typography fontSize={12} fontWeight={800} color="primary">
          Today in USD: {dailyMoney(hasPreviewForEdits ? preview?.total_cost_usd : entry.total_cost_usd, 'USD')}
        </Typography>
      </Paper>
    )}

    <Box display="grid" gap={1.2} mb={1.6} sx={{ gridTemplateColumns: { xs: '1fr 1fr', md: day.comparison.has_adjustment ? 'repeat(9, 1fr)' : 'repeat(7, 1fr)' } }}>
      <StatCard label="AFE planned" value={dailyMoney(day.comparison.planned_total, standard)} hint="Locked standard-currency budget"/>
      {day.comparison.has_adjustment && day.comparison.adjusted_planned_total != null && <>
        <StatCard label="Adjusted AFE" value={dailyMoney(day.comparison.adjusted_planned_total, standard)} hint="Latest approved SOW revision"/>
        <StatCard
          label="Adjusted balance"
          value={dailyMoney(Number(day.comparison.adjusted_planned_total) - actualToDate, standard)}
          hint={Number(day.comparison.adjusted_planned_total) - actualToDate < 0 ? 'Adjusted budget is exceeded' : 'Adjusted less actual to date'}
          tone={Number(day.comparison.adjusted_planned_total) - actualToDate < 0 ? 'bad' : 'good'}
        />
      </>}
      <StatCard label="Actual to date" value={dailyMoney(actualToDate, standard)} hint={hasPreviewForEdits ? 'Includes the current unsaved preview' : 'All four cost groups through this day'}/>
      <StatCard
        label="Actual depth"
        value={formatDepthMeters(hasPreviewForEdits ? preview?.actual_depth : entry.actual_depth, 'm')}
        hint="Last entered depth (ft ÷ 3.281 → m)"
      />
      <StatCard label="Other expenses deducted" value={dailyMoney(otherToDate, standard)} hint={otherItemSummary || 'LIH, hole problems and similar charges'} tone={otherToDate ? 'bad' : undefined}/>
      <StatCard label="Remaining balance" value={dailyMoney(remaining, standard)} hint={remaining < 0 ? 'AFE budget is exceeded' : 'Planned less actual, other expenses included'} tone={remaining < 0 ? 'bad' : 'good'}/>
      <StatCard label="UPA to date" value={dailyMoney(upaToDate, standard)} hint="Unplanned Activity charges" tone={upaToDate ? 'bad' : undefined}/>
      <StatCard label="NPT to date" value={dailyMoney(nptToDate, standard)} hint="Non-Productive Time charges" tone={nptToDate ? 'bad' : undefined}/>
    </Box>
    {amendments.length > 0 && <Alert severity="info" sx={{ mb: 1.5 }}>
      Amended {amendments.length} time{amendments.length === 1 ? '' : 's'} after its cost date
      {amendments[amendments.length - 1] ? ` — latest by ${amendments[amendments.length - 1].reopened_by || 'workspace user'} on ${new Date(amendments[amendments.length - 1].reopened_at).toLocaleString()}: ${amendments[amendments.length - 1].reason}` : ''}.
    </Alert>}

    <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, mb: 1.7 }}>
      <Box display="flex" justifyContent="space-between" gap={1.5} flexWrap="wrap" alignItems="center">
        <Box>
          <Typography fontWeight={800} fontSize={14}>Immutable daily cost baseline</Typography>
          <Typography color="text.secondary" fontSize={11.5} mt={.3}>
            AFE budget and exchange rates locked {new Date(baseline.locked_at).toLocaleString()} · Well catalogue prices locked {new Date(entry.rate_baseline_locked_at).toLocaleString()} · AFE status when started: {entry.afe_status}.
          </Typography>
        </Box>
        <Box display="flex" gap={1} flexWrap="wrap">
          <Tag tone={entry.status === 'submitted' ? 'success' : 'info'}>{DAILY_COST_STATUSES[entry.status]}</Tag>
          <Tag>{`${lineCount} line${lineCount === 1 ? '' : 's'}`}</Tag>
          {previewing && <Tag tone="warning">Repricing…</Tag>}
        </Box>
      </Box>
      <Box display="grid" gap={1.1} mt={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
        {day.comparison.groups.map(group => {
          const actual = currentGroupActual(group.cost_group)
          const balance = Number(group.planned) - Number(actual)
          const isOtherGroup = group.cost_group === 'Other Expenses'
          return <Box key={group.cost_group} sx={{ p: 1.15, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
            <Typography fontSize={11} fontWeight={800}>{group.cost_group}</Typography>
            <Typography fontSize={10.5} color="text.secondary" mt={.3}>
              {isOtherGroup ? 'No AFE allowance' : `Planned ${dailyMoney(group.planned, standard)}`} · Actual to date {dailyMoney(actual, standard)}
            </Typography>
            <Typography fontSize={11.5} fontWeight={700} color={balance < 0 ? 'error.main' : 'success.main'} mt={.3}>
              {isOtherGroup ? `Deducted from AFE ${dailyMoney(Number(actual), standard)}` : `Remaining ${dailyMoney(balance, standard)}`}
            </Typography>
          </Box>
        })}
      </Box>
    </Paper>

    <Box display="grid" gap={1.8}>
      <LineGroup
        title="Services" subtitle="AFE Day Rate, Per Service Rate and Per Section Rate charges. Hours convert to a portion of the locked day rate."
        count={payload.services.length} rows={services} columns={makeColumns('service')} editable={editable} canExport={canExport}
        onExport={recordExport} onAdd={() => setLineEditor({ kind: 'service', index: null })} onImport={openImport}
        selectable selectedCount={selectedServiceLines.length} selectionResetKey={serviceSelectionResetKey}
        onSelectionChange={rows => setSelectedServiceIndices(rows.map(row => row.lineIndex))}
        onBulkEdit={() => setBulkScopeOpen(true)} bulkEditLabel="Assign scope / depth / quantity"
        onAddFromSet={canReadCostingSets ? () => setSetPickerGroup('services') : undefined}
      />
      <LineGroup
        title="Consumables" subtitle="Itemized chemical, additive, fuel and drill-bit usage, reconciled to either item or category-level AFE allowances."
        count={payload.consumables.length} rows={consumables} columns={makeColumns('consumable')} editable={editable} canExport={canExport}
        onExport={recordExport} onAdd={() => setLineEditor({ kind: 'consumable', index: null })} onImport={openImport}
        onAddFromSet={canReadCostingSets ? () => setSetPickerGroup('consumables') : undefined}
      />
      <LineGroup
        title="Tangibles" subtitle="Actual tangible usage priced from the locked catalogue or a justified daily override."
        count={payload.tangibles.length} rows={tangibles} columns={makeColumns('tangible')} editable={editable} canExport={canExport}
        onExport={recordExport} onAdd={() => setLineEditor({ kind: 'tangible', index: null })} onImport={openImport}
        onAddFromSet={canReadCostingSets ? () => setSetPickerGroup('tangibles') : undefined}
      />
      <LineGroup
        title="Other Expenses"
        subtitle="Unexpected charges — Lost In Hole, hole problems, fishing, claims. No AFE allowance: the amount is deducted from the AFE total and every line needs a remark."
        count={otherLineCount} rows={otherExpenses} columns={makeColumns('other')} addLabel="other expense"
        editable={editable} canExport={canExport} onExport={recordExport}
        onAdd={() => setLineEditor({ kind: 'other', index: null })} onImport={openImport}
      />
    </Box>

    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, mt: 1.8 }}>
      <Box display="flex" justifyContent="space-between" alignItems="start" gap={2} flexWrap="wrap" mb={1.3}>
        <Box><Typography fontWeight={800} fontSize={15}>AFE budget reconciliation</Typography><Typography color="text.secondary" fontSize={11.5} mt={.3}>Category-level bulk allowances are intentionally matched against itemized actuals; balances update as the cost date advances.</Typography></Box>
        {editable && <Button size="small" startIcon={<DownloadOutlined/>} onClick={exportTemplate}>Import template</Button>}
      </Box>
      <Box display="grid" gap={1} mb={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(4, auto)' }, justifyContent: { sm: 'flex-end' }, alignItems: 'center' }}>
        <Typography fontSize={11.5} color="text.secondary">Total AFE {dailyMoney(day.comparison.planned_total, standard)}</Typography>
        <Typography fontSize={11.5} color="text.secondary">Less services, consumables &amp; tangibles {dailyMoney(trackedActualToDate, standard)}</Typography>
        <Typography fontSize={11.5} fontWeight={700} color={otherToDate ? 'error.main' : 'text.secondary'}>Less other expenses {dailyMoney(otherToDate, standard)}</Typography>
        <Typography fontSize={12} fontWeight={800} color={remaining < 0 ? 'error.main' : 'success.main'}>AFE available {dailyMoney(remaining, standard)}</Typography>
      </Box>
      {Boolean(otherLineCount || day.other_expenses.length) && <Alert severity="warning" sx={{ mb: 1.4 }}>
        Other expenses on this sheet: {otherLineCount} line(s) totalling {dailyMoney(workingOther, standard)}
        {otherItemSummary ? ` (${otherItemSummary})` : ''}. They are not part of the AFE estimate, so the amount is
        deducted from the AFE total rather than reconciled against a budget line.
      </Alert>}
      <Box sx={{ overflowX: 'auto' }}>
        <Table size="small" sx={{ minWidth: 700 }}>
          <TableHead><TableRow><TableCell>AFE budget line</TableCell><TableCell>Group</TableCell><TableCell align="right">Planned</TableCell><TableCell align="right">Actual to date</TableCell><TableCell align="right">Balance</TableCell></TableRow></TableHead>
          <TableBody>{comparisonRows.map((line, index) => <TableRow key={`${line.budget_key}-${index}`}>
            <TableCell><Typography fontSize={12} fontWeight={700}>{line.item_code || line.item_name || 'Unbudgeted actual'}</Typography><Typography fontSize={10.5} color="text.secondary">{line.item_name}{!line.is_planned ? ' · unplanned' : ''}</Typography></TableCell>
            <TableCell><Tag>{line.cost_group}</Tag></TableCell>
            <TableCell align="right">{dailyMoney(line.planned, standard)}</TableCell>
            <TableCell align="right">{dailyMoney(line.actual_to_date, standard)}</TableCell>
            <TableCell align="right"><Typography fontSize={12} fontWeight={700} color={Number(line.balance) < 0 ? 'error.main' : 'success.main'}>{dailyMoney(line.balance, standard)}</Typography></TableCell>
          </TableRow>)}
            {!comparisonRows.length && <TableRow><TableCell colSpan={5} align="center"><Typography color="text.secondary" fontSize={12} py={2}>The AFE has no cost lines in its saved estimate.</Typography></TableCell></TableRow>}
          </TableBody>
        </Table>
      </Box>
      {payload.remarks !== entry.remarks && <Typography fontSize={11} color="warning.dark" mt={1}>Daily remarks are not saved yet.</Typography>}
      <TextField
        fullWidth label="Daily sheet / shift remarks" value={payload.remarks} disabled={!editable}
        onChange={event => setPayload(current => ({ ...current, remarks: event.target.value }))}
        multiline minRows={2} inputProps={{ maxLength: 1000 }} sx={{ mt: 1.7 }}
      />
    </Paper>

    {editable && <Box display="flex" justifyContent="flex-end" gap={1} mt={1.6}>
      <Button variant="outlined" onClick={() => setPayload(originalPayload ?? payload)} disabled={!dirty || saving}>Discard changes</Button>
      <Button variant="contained" startIcon={<SaveOutlined/>} onClick={() => void save()} disabled={saveDisabled}>{saving ? 'Saving…' : 'Save daily sheet'}</Button>
    </Box>}

    <ErrorMessage message={printError}/>
    {printSheet}
    <FormDialog
      open={dailyPrintOpen}
      title="Print daily cost report"
      subtitle="The report uses saved data and cumulative schedules. Edit only the milestone label when this report represents a side track or another operational milestone."
      onClose={() => setDailyPrintOpen(false)}
      onSubmit={() => void printDay()}
      submitLabel="Print daily report"
      busy={printBusy}
    >
      <TextField fullWidth label="Milestone label in report" value={milestoneLabel} onChange={event => setMilestoneLabel(event.target.value)} inputProps={{ maxLength: 80 }} helperText="For example: Side track on date / time. The recorded date and time are not changed."/>
      <ErrorMessage message={printError}/>
    </FormDialog>
    <WellCostPrintDialog open={printOpen} onClose={() => setPrintOpen(false)} wells={reference?.wells ?? []} initialWellId={entry.well_id}/>

    <DailyCostBulkScopeDialog
      open={bulkScopeOpen && editable}
      selections={selectedServiceLines}
      allLines={payload.services}
      baseline={baseline}
      reference={reference}
      wellId={entry.well_id}
      onClose={() => setBulkScopeOpen(false)}
      onApply={applyBulkServiceScope}
    />
    <CostingSetPickerDialog
      open={setPickerGroup !== null && editable && canReadCostingSets}
      group={setPickerGroup ?? 'services'}
      destination="daily-cost"
      sets={costingSets}
      onClose={() => setSetPickerGroup(null)}
      onApply={applyCostingSet}
    />

    <DailyCostLineDialog
      open={Boolean(lineEditor)} kind={lineEditor?.kind ?? null}
      initialLine={(() => {
        if (!lineEditor || lineEditor.index === null) return null
        return payload[GROUP_KEY[lineEditor.kind]][lineEditor.index] as EditableDailyCostLine | undefined ?? null
      })()}
      serviceLines={payload.services}
      lineIndex={lineEditor?.kind === 'service' ? lineEditor.index : null}
      baseline={baseline} reference={reference} wellId={entry.well_id}
      onClose={() => setLineEditor(null)} onSave={addOrEditLine}
    />

    <FormDialog open={Boolean(lineDelete)} title={`Remove ${lineDelete?.label ?? 'line'}?`} subtitle="This removes the line from this unsaved daily sheet. A saved line is deleted only after you save the sheet." onClose={() => setLineDelete(null)} onSubmit={removeLine} submitLabel="Remove line">
      <Alert severity="warning">This change will affect the AFE actual-to-date and remaining balance after you save.</Alert>
    </FormDialog>

    {/* Intercepts navigation, the back button and tab close while the sheet has unsaved edits. */}
    {leaveGuard}

    <FormDialog open={Boolean(statusAction)} title={statusTitle} subtitle={statusSubtitle} onClose={() => { if (!statusBusy) setStatusAction(null) }} onSubmit={() => void completeStatusAction()} busy={statusBusy} submitLabel={statusAction === 'submit' ? 'Submit daily sheet' : 'Reopen as Draft'} submitDisabled={statusAction === 'reopen' && statusRemarks.trim().length < 3}>
      <Box display="grid" gap={1.5}>
        {statusAction === 'reopen' && Math.floor((Date.now() - Date.parse(`${entry.cost_date}T00:00:00Z`)) / 86_400_000) > 30 && <Alert severity="warning">
          This sheet is more than 30 days old, so reopening it is recorded as an amendment and needs the daily-cost amendment permission.
        </Alert>}
        <TextField label={statusAction === 'reopen' ? 'Reopen reason (required)' : 'Submission remarks (optional)'} value={statusRemarks} onChange={event => setStatusRemarks(event.target.value)} multiline minRows={2} inputProps={{ maxLength: 500 }} helperText={statusAction === 'reopen' ? 'At least 3 characters; recorded in the audit trail.' : 'Optional note recorded with the submission.'}/>
        {statusError && <Alert severity="error">{statusError}</Alert>}
      </Box>
    </FormDialog>

    <FormDialog open={importOpen} title="Import daily actuals" subtitle="Upload one CSV or Excel file. Rows are validated as a batch; invalid files make no changes and existing lines are retained." onClose={() => { if (!importBusy) setImportOpen(false) }} onSubmit={() => void importDailyCosts()} busy={importBusy} submitLabel={`Validate and import${importRows.length ? ` (${importRows.length})` : ''}`} submitDisabled={!importRows.length || !editable} maxWidth="md">
      <Box display="grid" gap={1.4}>
        <Alert severity="info">Use the template for line_type (Service, Consumable, Tangible or Other), activity_code, sub_activity_code and the item/service code. The Activity classifies the line (Planned / UPA / NPT); planned services must include their baseline_service_rate_id, while UPA/NPT manual rates require an override reason. An Other row also needs expense_type, unit_rate and a remark, and is deducted from the AFE total. The same service can appear again only under a different sub_activity_code.</Alert>
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
          <Button variant="outlined" startIcon={<CloudUploadOutlined/>} onClick={() => fileInput.current?.click()}>Choose CSV / XLSX</Button>
          <Button variant="text" startIcon={<DownloadOutlined/>} onClick={exportTemplate}>Download CSV template</Button>
          {importFileName && <Typography fontSize={12} color="text.secondary">{importFileName} · {importRows.length} data rows</Typography>}
          <input ref={fileInput} hidden type="file" accept=".csv,.xlsx,.xls" onChange={event => { void readImportFile(event.target.files?.[0]); event.target.value = '' }}/>
        </Box>
        {importRows.length > 0 && <Paper variant="outlined" sx={{ p: 1.3, borderRadius: 1.5 }}>
          <Typography fontSize={12} fontWeight={700}>Import preview</Typography>
          <Typography color="text.secondary" fontSize={11} mt={.35}>First row: {Object.entries(importRows[0]).filter(([, value]) => value).slice(0, 6).map(([key, value]) => `${key}: ${value}`).join(' · ')}</Typography>
          <Typography color="text.secondary" fontSize={10.5} mt={.4}>The import is all-or-nothing. Validate errors below before retrying.</Typography>
        </Paper>}
        {importErrors.length > 0 && <Alert severity="error"><Typography fontSize={12} fontWeight={700}>Import validation found {importErrors.length} issue{importErrors.length === 1 ? '' : 's'}:</Typography><Box component="ul" sx={{ mb: 0, mt: .6, pl: 2.2 }}>{importErrors.map((error, index) => <li key={`${index}-${error}`}><Typography fontSize={11.5}>{error}</Typography></li>)}</Box></Alert>}
        {importError && <Alert severity="error">{importError}</Alert>}
      </Box>
    </FormDialog>
  </>
}

function LineGroup({
  title, subtitle, count, rows, columns, editable, canExport, onExport, onAdd, onImport, addLabel,
  onAddFromSet, selectable = false, selectedCount = 0, onSelectionChange, onBulkEdit, bulkEditLabel,
  selectionResetKey,
}: {
  title: string; subtitle: string; count: number; rows: GridLine[]; columns: ColDef<GridLine>[]; editable: boolean
  canExport: boolean; onExport: (format: 'csv' | 'xlsx' | 'pdf', count: number) => Promise<void>
  onAdd: () => void; onImport: () => void; addLabel?: string; onAddFromSet?: () => void
  selectable?: boolean; selectedCount?: number; onSelectionChange?: (rows: GridLine[]) => void
  onBulkEdit?: () => void; bulkEditLabel?: string; selectionResetKey?: number
}) {
  return <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap" p={1.8}>
      <Box><Typography fontWeight={800} fontSize={14}>{title} <Typography component="span" fontSize={12} color="text.secondary" fontWeight={600}>({count})</Typography></Typography><Typography color="text.secondary" fontSize={11.2} mt={.25}>{subtitle}</Typography></Box>
      {editable && <Box display="flex" gap={.7} flexWrap="wrap">
        <Button size="small" onClick={onImport} startIcon={<CloudUploadOutlined sx={{ fontSize: 17 }}/>}>Import</Button>
        {onAddFromSet && <Button size="small" variant="outlined" onClick={onAddFromSet} startIcon={<PlaylistAddRounded sx={{ fontSize: 17 }}/>}>Add from set</Button>}
        {onBulkEdit && selectedCount > 0 && <Button size="small" variant="outlined" onClick={onBulkEdit} startIcon={<EditOutlined sx={{ fontSize: 16 }}/>}>{bulkEditLabel ?? 'Bulk edit'} ({selectedCount})</Button>}
        <Button size="small" variant="contained" onClick={onAdd} startIcon={<AddRounded sx={{ fontSize: 17 }}/>}>Add {addLabel ?? (title === 'Services' ? 'service' : title === 'Consumables' ? 'usage' : 'tangible')}</Button>
      </Box>}
    </Box>
    <DataTable
      rows={rows} columns={columns} rowKey="id"
      searchPlaceholder={`Search ${title.toLowerCase()} by item, activity, vendor or status…`}
      exportName={`daily-cost-${title.toLowerCase()}`} canExport={canExport} onExport={canExport ? onExport : undefined}
      selectable={editable && selectable} onSelectionChange={onSelectionChange} selectionResetKey={selectionResetKey}
    />
    {count === 0 && <Typography color="text.secondary" fontSize={11.5} textAlign="center" py={1.2}>No {title.toLowerCase()} recorded for this day yet.</Typography>}
  </Paper>
}
