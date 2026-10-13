import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import {
  PrintOutlined, AddRounded, ArrowBackRounded, CloudUploadOutlined, ContentCopyOutlined, DeleteOutlineRounded,
  DownloadOutlined, EditOutlined, LockOutlined, RefreshRounded, SaveOutlined, SendRounded, UndoRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, LinearProgress, Paper, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import type { ColDef, ICellRendererParams } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import { DailyCostLineDialog, type DailyCostLineKind, type EditableDailyCostLine } from '../components/daily-cost/DailyCostLineDialog'
import { useCostPrint } from '../components/daily-cost/DailyCostPrintSheet'
import { WellCostPrintDialog } from '../components/daily-cost/WellCostPrintDialog'
import { useAuth } from '../context/AuthContext'
import { api, body } from '../lib/api'
import { downloadTemplate, parseImportFile, type ImportRow } from '../lib/export'
import {
  DAILY_COST_STATUSES, DAILY_ONE_TIME_CATEGORIES, dailyMoney, displayDate, entryQuery, otherExpenseLabel, saveFromDay,
  type DailyCostBaseline, type DailyCostComparisonLine, type DailyCostDay, type DailyCostGroup,
  type AnyDailyCostLine, type DailyCostImportResult, type DailyCostPreview, type DailyCostReference,
  type DailyCostSavePayload,
} from '../lib/dailyCost'

/** Where each dialog kind lives inside the save payload. */
type LineGroupKey = 'services' | 'consumables' | 'tangibles' | 'other_expenses'
const GROUP_KEY: Record<DailyCostLineKind, LineGroupKey> = {
  service: 'services', consumable: 'consumables', tangible: 'tangibles', other: 'other_expenses',
}

type GridLine = {
  id: string; lineIndex: number; item: string; activity: string; section: string; subActivity: string
  vendor: string; quantity: string; quantityUnit: string; rate: string; currency: string
  amount: string; standardAmount: string; source: string; budget: string; overrideReason: string; remarks: string
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
  const [printOpen, setPrintOpen] = useState(false)
  const [printBusy, setPrintBusy] = useState(false)
  const [printError, setPrintError] = useState('')
  const { entryId = '' } = useParams()
  const { can } = useAuth()
  const [day, setDay] = useState<DailyCostDay | null>(null)
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
  const fileInput = useRef<HTMLInputElement>(null)

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
      setPayload(saveFromDay(dayData))
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
  // close first offer to save this sheet. The beforeunload handler above stays
  // for the raw reload case.
  const leaveGuard = useUnsavedChangesGuard({
    when: dirty,
    onSave: () => save(),
    title: 'Leave without saving?',
    message: 'This daily cost sheet has changes that are not saved yet. Save them before leaving, or discard them deliberately.',
  })

  const addOrEditLine = (line: EditableDailyCostLine) => {
    if (!lineEditor) return
    const group = GROUP_KEY[lineEditor.kind]
    const index = lineEditor.index
    setPayload(current => {
      const rows = [...current[group]] as EditableDailyCostLine[]
      if (index === null) rows.push(line)
      else rows[index] = line
      return { ...current, [group]: rows }
    })
    setPreview(null)
    setLineEditor(null)
    setNotice(group === 'other_expenses'
      ? 'Other expense updated. The AFE remaining balance is being recalculated with the deduction; save to commit the change.'
      : 'Line updated. Preview and AFE remaining balance are recalculating; save to commit the change.')
  }

  const removeLine = () => {
    if (!lineDelete) return
    const group = GROUP_KEY[lineDelete.kind]
    const { index } = lineDelete
    setPayload(current => ({ ...current, [group]: current[group].filter((_row, rowIndex) => rowIndex !== index) }))
    setPreview(null)
    setLineDelete(null)
    setNotice('Line removed from the draft. Save to commit the change.')
  }

  const save = async (): Promise<boolean> => {
    if (!day) return false
    setSaving(true)
    setSaveError('')
    setNotice('')
    try {
      const updated = await api<DailyCostDay>(`/daily-cost/entries/${entryId}`, { method: 'PUT', body: body(payload) })
      setDay(updated)
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
  const vendorName = (vendorId: string | null, party: string) => {
    const vendor = reference.vendors.find(item => item.id === vendorId)
    return vendor?.vendor_name || party || '—'
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
      const vendor = vendorName(line.vendor_id, line.party_name)
      const sub = priced
        ? (priced.sub_activity_code ? `${priced.sub_activity_code} · ${priced.sub_activity_name}` : priced.sub_activity_name || '—')
        : reference.sub_activities.find(item => item.id === line.sub_activity_id)?.display_name ?? '—'
      return {
        id: line.id || `${kind}-${index}`, lineIndex: index, item, activity,
        section: scopeName(line.hole_section_id, line.phase_id), subActivity: sub,
        vendor, quantity: line.quantity, quantityUnit: 'quantity_unit' in line ? line.quantity_unit : '',
        rate: `${dailyMoney(priced?.effective_rate ?? sourceRate, priced?.currency ?? sourceCurrency)}${sourceLabel ? ` · ${sourceLabel}` : ''}`,
        currency: priced?.currency ?? sourceCurrency,
        amount: dailyMoney(localAmount, priced?.currency ?? sourceCurrency),
        standardAmount: priced ? dailyMoney(priced.standard_amount, standard) : 'Preview pending',
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
      { headerName: 'RESPONSIBLE PARTY', field: 'vendor', minWidth: 150 },
      { headerName: 'QUANTITY', field: 'quantity', minWidth: 115, valueGetter: params => params.data ? `${params.data.quantity} ${params.data.quantityUnit}`.trim() : '' },
      { headerName: 'RATE / SOURCE', field: 'rate', minWidth: 190, tooltipField: 'overrideReason' },
      { headerName: 'NATIVE AMOUNT', field: 'amount', minWidth: 145 },
      { headerName: `AFE AMOUNT (${standard})`, field: 'standardAmount', minWidth: 155 },
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
    'vendor_code', 'party_name', 'service_code', 'baseline_service_rate_id', 'charging_basis', 'charge_category',
    'quantity_unit', 'category', 'item_kind', 'item_code', 'quantity', 'currency', 'override_rate', 'override_reason',
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
        vendor_code: '', service_code: rate?.service_code ?? 'SERVICE-001',
        baseline_service_rate_id: rate?.id ?? '', charging_basis: rate?.charging_basis ?? 'Day Rate',
        charge_category: category, quantity_unit: unit, quantity: '1', currency: rate?.currency ?? standard,
        override_rate: '', override_reason: '', remarks: '',
      },
      {
        // An unexpected charge: no AFE allowance, mandatory remark, own unit rate.
        line_type: 'Other', activity_code: reference.activities.find(item => /npt|non.?productive/i.test(`${item.activity_code} ${item.activity_name}`))?.activity_code ?? activityCode,
        section_code: section?.section_code ?? '', phase_code: phase?.phase_code ?? '',
        sub_activity_code: subActivityCode, vendor_code: '', party_name: 'Operator',
        expense_type: 'LIH', expense_description: '6 5/8 in BHA left in hole', unit_rate: '250000',
        quantity: '1', quantity_unit: 'unit', currency: standard, remarks: 'Tools lost in hole during tripping',
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
      await api('/daily-cost/export-audit', { method: 'POST', body: body({
        module: 'day-sheet', format: 'pdf', record_count: 1, entry_id: entry.id,
        well_id: entry.well_id, include_deleted: entry.is_deleted,
      }) })
      print({ title: `Daily cost sheet · ${entry.daily_cost_code}`, period: displayDate(entry.cost_date), days: [saved] })
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
          <Tooltip title={dirty ? 'Save or discard changes before printing the saved daily sheet.' : 'Print the full saved daily sheet or save as PDF.'}><span><Button variant="outlined" startIcon={<PrintOutlined/>} disabled={dirty || saving || printBusy} onClick={() => void printDay()}>{printBusy ? 'Preparing print…' : 'Print daily sheet'}</Button></span></Tooltip>
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

    {notice && <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setNotice('')}>{notice}</Alert>}
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

    <Box display="grid" gap={1.2} mb={1.6} sx={{ gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(6, 1fr)' } }}>
      <StatCard label="AFE planned" value={dailyMoney(day.comparison.planned_total, standard)} hint="Locked standard-currency budget"/>
      <StatCard label="Actual to date" value={dailyMoney(actualToDate, standard)} hint={hasPreviewForEdits ? 'Includes the current unsaved preview' : 'All four cost groups through this day'}/>
      <StatCard label="Other expenses deducted" value={dailyMoney(otherToDate, standard)} hint={otherItemSummary || 'LIH, hole problems and similar charges'} tone={otherToDate ? 'bad' : undefined}/>
      <StatCard label="Remaining balance" value={dailyMoney(remaining, standard)} hint={remaining < 0 ? 'AFE budget is exceeded' : 'Planned less actual, other expenses included'} tone={remaining < 0 ? 'bad' : 'good'}/>
      <StatCard label="UPA to date" value={dailyMoney(upaToDate, standard)} hint="Unplanned Activity charges" tone={upaToDate ? 'bad' : undefined}/>
      <StatCard label="NPT to date" value={dailyMoney(nptToDate, standard)} hint="Non-Productive Time charges" tone={nptToDate ? 'bad' : undefined}/>
    </Box>

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
      <LineGroup title="Services" subtitle="AFE Day Rate, Per Service Rate and Per Section Rate charges. Hours convert to a portion of the locked day rate." count={payload.services.length} rows={services} columns={makeColumns('service')} editable={editable} canExport={canExport} onExport={recordExport} onAdd={() => setLineEditor({ kind: 'service', index: null })} onImport={openImport}/>
      <LineGroup title="Consumables" subtitle="Itemized chemical, additive, fuel and drill-bit usage, reconciled to either item or category-level AFE allowances." count={payload.consumables.length} rows={consumables} columns={makeColumns('consumable')} editable={editable} canExport={canExport} onExport={recordExport} onAdd={() => setLineEditor({ kind: 'consumable', index: null })} onImport={openImport}/>
      <LineGroup title="Tangibles" subtitle="Actual tangible usage priced from the locked catalogue or a justified daily override." count={payload.tangibles.length} rows={tangibles} columns={makeColumns('tangible')} editable={editable} canExport={canExport} onExport={recordExport} onAdd={() => setLineEditor({ kind: 'tangible', index: null })} onImport={openImport}/>
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
    <WellCostPrintDialog open={printOpen} onClose={() => setPrintOpen(false)} wells={reference?.wells ?? []} initialWellId={entry.well_id}/>

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

function LineGroup({ title, subtitle, count, rows, columns, editable, canExport, onExport, onAdd, onImport, addLabel }: {
  title: string; subtitle: string; count: number; rows: GridLine[]; columns: ColDef<GridLine>[]; editable: boolean
  canExport: boolean; onExport: (format: 'csv' | 'xlsx' | 'pdf', count: number) => Promise<void>
  onAdd: () => void; onImport: () => void; addLabel?: string
}) {
  return <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" gap={1.5} flexWrap="wrap" p={1.8}>
      <Box><Typography fontWeight={800} fontSize={14}>{title} <Typography component="span" fontSize={12} color="text.secondary" fontWeight={600}>({count})</Typography></Typography><Typography color="text.secondary" fontSize={11.2} mt={.25}>{subtitle}</Typography></Box>
      {editable && <Box display="flex" gap={.7}>
        <Button size="small" onClick={onImport} startIcon={<CloudUploadOutlined sx={{ fontSize: 17 }}/>}>Import</Button>
        <Button size="small" variant="contained" onClick={onAdd} startIcon={<AddRounded sx={{ fontSize: 17 }}/>}>Add {addLabel ?? (title === 'Services' ? 'service' : title === 'Consumables' ? 'usage' : 'tangible')}</Button>
      </Box>}
    </Box>
    <DataTable rows={rows} columns={columns} rowKey="id" searchPlaceholder={`Search ${title.toLowerCase()} by item, activity, vendor or status…`} exportName={`daily-cost-${title.toLowerCase()}`} canExport={canExport} onExport={canExport ? onExport : undefined}/>
    {count === 0 && <Typography color="text.secondary" fontSize={11.5} textAlign="center" py={1.2}>No {title.toLowerCase()} recorded for this day yet.</Typography>}
  </Paper>
}
