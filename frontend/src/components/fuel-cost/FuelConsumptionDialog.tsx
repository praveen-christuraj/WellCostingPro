import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent } from 'react'
import {
  Add,
  ChevronLeft,
  ChevronRight,
  ContentCopy,
  DeleteOutline,
  ExpandLess,
  ExpandMore,
  GridViewOutlined,
  KeyboardOutlined,
  PlaylistAdd,
  Search,
  TableRowsOutlined,
} from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Collapse,
  FormControlLabel,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { api } from '../../lib/api'
import { displayDate } from '../../lib/dailyCost'
import {
  blankFuelLine,
  fuelBalancePreview,
  fuelDraftDirty,
  fuelDraftFromDay,
  fuelHasErrors,
  fuelLineKey,
  fuelLitres,
  fuelNumber,
  fuelSavePayload,
  parseFuelCompanyPaste,
  shiftIsoDate,
  validateFuelDraft,
  type FuelCompany,
  type FuelCostDay,
  type FuelCostRigOption,
  type FuelCostVendorOption,
  type FuelDraft,
  type FuelDraftLine,
} from '../../lib/fuelCost'
import { ErrorMessage, FormDialog, Tag } from '../Common'

const NEW_COMPANY_VALUE = '__new_fuel_company__'
const NEW_CATEGORY_VALUE = '__new_fuel_category__'
const GRID_PAGE_CHUNK = 90

type EntryMode = 'table' | 'grid'
type GridFilter = 'all' | 'default' | 'entered'

type Props = {
  open: boolean
  day: FuelCostDay | null
  loading: boolean
  loadError: string
  rig: FuelCostRigOption | null
  costDate: string
  companies: FuelCompany[]
  vendors: FuelCostVendorOption[]
  canEdit: boolean
  canManageCompanies: boolean
  canOverrideOpening: boolean
  saving: boolean
  saveError: string
  onClose: () => void
  onSave: (
    payload: ReturnType<typeof fuelSavePayload>,
    entryId: string | null,
    options?: { advanceToDate?: string },
  ) => void | Promise<boolean | void>
  onCompaniesChanged: (company?: FuelCompany) => Promise<void> | void
  onChangeDate?: (nextDate: string) => void
}

function BalanceTile({
  label,
  value,
  note,
  emphasize = false,
  tone = 'default',
}: {
  label: string
  value: string
  note?: string
  emphasize?: boolean
  tone?: 'default' | 'warning' | 'success'
}) {
  const borderColor = emphasize
    ? 'primary.main'
    : tone === 'warning'
      ? 'warning.main'
      : 'divider'
  return (
    <Box
      sx={{
        px: 1,
        py: 0.65,
        borderRadius: 1.25,
        border: '1px solid',
        borderColor,
        bgcolor: emphasize ? 'action.hover' : 'background.paper',
        minWidth: 0,
      }}
    >
      <Typography
        component="div"
        sx={{
          fontSize: 9.5,
          fontWeight: 800,
          letterSpacing: '0.06em',
          color: 'text.secondary',
          lineHeight: 1.2,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {label}
      </Typography>
      <Typography
        component="div"
        sx={{
          mt: 0.25,
          fontSize: 13.5,
          fontWeight: 800,
          fontVariantNumeric: 'tabular-nums',
          color: tone === 'warning' ? 'warning.main' : tone === 'success' ? 'success.main' : 'text.primary',
          lineHeight: 1.25,
        }}
      >
        {value}
      </Typography>
      {note ? (
        <Typography
          component="div"
          sx={{
            mt: 0.15,
            fontSize: 10,
            color: 'text.secondary',
            lineHeight: 1.2,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {note}
        </Typography>
      ) : null}
    </Box>
  )
}

function draftHasAnyRemarks(draft: FuelDraft): boolean {
  return Boolean(
    draft.rigEngineRemarks.trim()
    || draft.gasRemarks.trim()
    || draft.openingRemarks.trim()
    || draft.receiptRemarks.trim()
    || draft.closingRemarks.trim()
    || draft.remarks.trim(),
  )
}

export function FuelConsumptionDialog({
  open,
  day,
  loading,
  loadError,
  rig,
  costDate,
  companies,
  vendors,
  canEdit,
  canManageCompanies,
  canOverrideOpening,
  saving,
  saveError,
  onClose,
  onSave,
  onCompaniesChanged,
  onChangeDate,
}: Props) {
  const [draft, setDraft] = useState<FuelDraft>(() =>
    day ? fuelDraftFromDay(day) : {
      rigEngine: '',
      rigEngineRemarks: '',
      gas: '',
      gasRemarks: '',
      opening: '',
      openingRemarks: '',
      openingOverride: false,
      receipt: '',
      receiptRemarks: '',
      closing: '',
      closingRemarks: '',
      remarks: '',
      lines: [],
    })
  const [baseline, setBaseline] = useState<FuelDraft>(draft)
  const [attempted, setAttempted] = useState(false)
  const [pendingStepDate, setPendingStepDate] = useState<string | null>(null)
  const [showRemarks, setShowRemarks] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [entryMode, setEntryMode] = useState<EntryMode>('table')
  const [searchQuery, setSearchQuery] = useState('')
  const [gridFilter, setGridFilter] = useState<GridFilter>('all')
  const [gridRenderCap, setGridRenderCap] = useState(GRID_PAGE_CHUNK)
  const [pasteFeedback, setPasteFeedback] = useState('')

  // Inline company / category creator (placed at top of Company section — zero scrolling).
  const [newCompanyLineKey, setNewCompanyLineKey] = useState<string | null>(null)
  const [newCompanyOpen, setNewCompanyOpen] = useState(false)
  const [newCompanySource, setNewCompanySource] = useState<'vendor' | 'manual'>('vendor')
  const [newCompanyVendorId, setNewCompanyVendorId] = useState('')
  const [newCompanyName, setNewCompanyName] = useState('')
  const [newCompanyDefault, setNewCompanyDefault] = useState(true)
  const [newCategoryTarget, setNewCategoryTarget] = useState<{ lineKey: string; companyId: string } | null>(null)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [inlineBusy, setInlineBusy] = useState(false)
  const [inlineError, setInlineError] = useState('')

  const tableLitresRefs = useRef<Record<string, HTMLInputElement | null>>({})
  const gridLitresRefs = useRef<Record<string, HTMLInputElement | null>>({})
  const pendingFocusLineKey = useRef<string | null>(null)

  const dayKey = day
    ? `${day.rig_id}:${day.cost_date}:${day.entry?.id ?? 'new'}:${day.entry?.revision ?? 0}`
    : 'none'

  useEffect(() => {
    if (!day) return
    const next = fuelDraftFromDay(day)
    setDraft(next)
    setBaseline(next)
    setAttempted(false)
    setShowRemarks(draftHasAnyRemarks(next))
    setNewCompanyLineKey(null)
    setNewCompanyOpen(false)
    setNewCategoryTarget(null)
    setInlineError('')
    setPasteFeedback('')
    setGridRenderCap(GRID_PAGE_CHUNK)
  }, [dayKey, open]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setGridRenderCap(GRID_PAGE_CHUNK)
  }, [searchQuery, gridFilter, entryMode])

  useEffect(() => {
    if (!pendingFocusLineKey.current) return
    const key = pendingFocusLineKey.current
    pendingFocusLineKey.current = null
    const input = tableLitresRefs.current[key]
    if (input) {
      input.focus()
      input.select?.()
    }
  }, [draft.lines.length])

  const dirty = useMemo(() => (day ? fuelDraftDirty(draft, baseline) : false), [day, draft, baseline])
  const preview = useMemo(() => (day ? fuelBalancePreview(day, draft) : null), [day, draft])
  const errors = useMemo(
    () => (day && attempted ? validateFuelDraft(draft, day) : { lines: {}, summary: [] }),
    [day, draft, attempted],
  )

  const activeCompanies = useMemo(
    () => companies.filter(company => !company.is_deleted),
    [companies],
  )
  const companyById = useMemo(
    () => new Map(companies.map(company => [company.id, company])),
    [companies],
  )
  const availableVendors = useMemo(
    () => vendors.filter(vendor => !vendor.registered && vendor.status === 'active'),
    [vendors],
  )

  const isFirst = preview?.isFirst ?? false
  const openingEditable = isFirst || (canOverrideOpening && draft.openingOverride)
  const defaultCompanies = useMemo(
    () => activeCompanies.filter(company => company.is_default),
    [activeCompanies],
  )
  const defaultCount = defaultCompanies.length
  const previousLines = day?.previous_lines ?? []

  const remarkCount = useMemo(
    () => [
      draft.rigEngineRemarks,
      draft.gasRemarks,
      draft.openingRemarks,
      draft.receiptRemarks,
      draft.closingRemarks,
      draft.remarks,
    ].filter(text => text.trim() !== '').length,
    [draft],
  )

  const enteredCompanyIds = useMemo(() => {
    const ids = new Set<string>()
    for (const line of draft.lines) {
      if (line.company_id && fuelNumber(line.litres) > 0) ids.add(line.company_id)
    }
    return ids
  }, [draft.lines])

  const enteredLineCount = useMemo(
    () => draft.lines.filter(line => line.company_id && line.litres.trim() !== '' && fuelNumber(line.litres) > 0).length,
    [draft.lines],
  )

  const blankLineCount = useMemo(
    () => draft.lines.filter(line => !line.company_id && !line.litres.trim() && !line.remarks.trim()).length,
    [draft.lines],
  )

  const normalizedSearch = searchQuery.trim().toLowerCase()

  const visibleTableLines = useMemo(() => {
    if (!normalizedSearch) return draft.lines.map((line, idx) => ({ line, idx }))
    return draft.lines
      .map((line, idx) => ({ line, idx }))
      .filter(({ line }) => {
        if (!line.company_id) return true
        const comp = companyById.get(line.company_id)
        const cat = comp?.categories.find(item => item.id === line.category_id)
        const haystack = [
          comp?.company_name ?? '',
          comp?.vendor_code ?? '',
          cat?.category_name ?? '',
          line.remarks,
        ].join(' ').toLowerCase()
        return haystack.includes(normalizedSearch)
      })
  }, [draft.lines, normalizedSearch, companyById])

  // Build quick-fill slots: every active company shows its existing draft line(s), or 1 ready-to-type slot.
  type GridSlot = {
    slotKey: string
    company: FuelCompany
    line: FuelDraftLine | null
    extraIndex: number
  }

  const allGridSlots = useMemo<GridSlot[]>(() => {
    const byCompany = new Map<string, FuelDraftLine[]>()
    for (const line of draft.lines) {
      if (!line.company_id) continue
      const list = byCompany.get(line.company_id) ?? []
      list.push(line)
      byCompany.set(line.company_id, list)
    }
    const slots: GridSlot[] = []
    for (const company of activeCompanies) {
      const hasEntered = enteredCompanyIds.has(company.id)
      if (gridFilter === 'default' && !company.is_default && !hasEntered) continue
      if (gridFilter === 'entered' && !hasEntered) continue
      if (normalizedSearch) {
        const catNames = company.categories
          .filter(cat => !cat.is_deleted)
          .map(cat => cat.category_name)
          .join(' ')
        const haystack = `${company.company_name} ${company.vendor_code} ${catNames}`.toLowerCase()
        if (!haystack.includes(normalizedSearch)) continue
      }
      const existing = byCompany.get(company.id)
      if (existing && existing.length > 0) {
        existing.forEach((line, idx) => {
          slots.push({
            slotKey: line.key,
            company,
            line,
            extraIndex: idx,
          })
        })
      } else {
        slots.push({
          slotKey: `virtual-${company.id}`,
          company,
          line: null,
          extraIndex: 0,
        })
      }
    }
    return slots
  }, [activeCompanies, draft.lines, enteredCompanyIds, gridFilter, normalizedSearch])

  const cappedGridSlots = useMemo(
    () => allGridSlots.slice(0, gridRenderCap),
    [allGridSlots, gridRenderCap],
  )

  const setField = <K extends keyof FuelDraft>(key: K, value: FuelDraft[K]) =>
    setDraft(current => ({ ...current, [key]: value }))

  const updateLine = (lineKey: string, patch: Partial<FuelDraftLine>) =>
    setDraft(current => ({
      ...current,
      lines: current.lines.map(line => (line.key === lineKey ? { ...line, ...patch } : line)),
    }))

  const removeLine = (lineKey: string) =>
    setDraft(current => ({
      ...current,
      lines: current.lines.filter(line => line.key !== lineKey),
    }))

  const addLine = () => {
    const next = blankFuelLine()
    pendingFocusLineKey.current = next.key
    setDraft(current => ({ ...current, lines: [...current.lines, next] }))
  }

  const clearEmptyLines = () =>
    setDraft(current => ({
      ...current,
      lines: current.lines.filter(line => line.company_id || line.litres.trim() || line.remarks.trim()),
    }))

  const addDefaultSet = () => {
    setDraft(current => {
      const present = new Set(current.lines.map(line => line.company_id).filter(Boolean))
      const added = defaultCompanies
        .filter(company => !present.has(company.id))
        .map(company => ({ ...blankFuelLine(), company_id: company.id }))
      if (added.length > 0) pendingFocusLineKey.current = added[0].key
      return added.length ? { ...current, lines: [...current.lines, ...added] } : current
    })
  }

  const copyPreviousDaySet = () => {
    if (!previousLines.length) return
    setDraft(current => {
      const present = new Set(current.lines.map(line => `${line.company_id}:${line.category_id}`))
      const added: FuelDraftLine[] = []
      for (const prev of previousLines) {
        const catId = prev.category_id ?? ''
        const sig = `${prev.company_id}:${catId}`
        if (present.has(sig)) continue
        present.add(sig)
        added.push({
          key: fuelLineKey(),
          company_id: prev.company_id,
          category_id: catId,
          litres: '',
          remarks: '',
          source: 'manual',
        })
      }
      if (added.length > 0) pendingFocusLineKey.current = added[0].key
      return added.length ? { ...current, lines: [...current.lines, ...added] } : current
    })
  }

  const setGridSlotLitres = (slot: GridSlot, litresValue: string) => {
    setDraft(current => {
      if (slot.line) {
        // Keep saved lines or multi-category split lines even when cleared; drop transient empty virtual lines cleanly.
        if (litresValue.trim() === '' && !slot.line.id && !slot.line.remarks.trim() && slot.extraIndex === 0) {
          return {
            ...current,
            lines: current.lines.filter(item => item.key !== slot.line?.key),
          }
        }
        return {
          ...current,
          lines: current.lines.map(item =>
            item.key === slot.line?.key ? { ...item, litres: litresValue } : item,
          ),
        }
      }
      if (litresValue.trim() === '') return current
      const activeCats = slot.company.categories.filter(cat => !cat.is_deleted)
      const defaultCatId = activeCats.length === 1 ? activeCats[0].id : ''
      const created: FuelDraftLine = {
        key: fuelLineKey(),
        company_id: slot.company.id,
        category_id: defaultCatId,
        litres: litresValue,
        remarks: '',
        source: 'manual',
      }
      return { ...current, lines: [...current.lines, created] }
    })
  }

  const setGridSlotCategory = (slot: GridSlot, categoryId: string) => {
    if (categoryId === NEW_CATEGORY_VALUE) {
      const targetKey = slot.line?.key ?? fuelLineKey()
      if (!slot.line) {
        setDraft(current => ({
          ...current,
          lines: [
            ...current.lines,
            { key: targetKey, company_id: slot.company.id, category_id: '', litres: '', remarks: '', source: 'manual' },
          ],
        }))
      }
      setNewCategoryTarget({ lineKey: targetKey, companyId: slot.company.id })
      setNewCategoryName('')
      setInlineError('')
      return
    }
    setDraft(current => {
      if (slot.line) {
        return {
          ...current,
          lines: current.lines.map(item =>
            item.key === slot.line?.key ? { ...item, category_id: categoryId } : item,
          ),
        }
      }
      return {
        ...current,
        lines: [
          ...current.lines,
          { key: fuelLineKey(), company_id: slot.company.id, category_id: categoryId, litres: '', remarks: '', source: 'manual' },
        ],
      }
    })
  }

  const splitCompanySlot = (company: FuelCompany) => {
    setDraft(current => {
      const existing = current.lines.filter(item => item.company_id === company.id)
      const additions: FuelDraftLine[] = []
      if (existing.length === 0) {
        additions.push({
          key: fuelLineKey(),
          company_id: company.id,
          category_id: '',
          litres: '',
          remarks: '',
          source: 'manual',
        })
      }
      additions.push({
        key: fuelLineKey(),
        company_id: company.id,
        category_id: '',
        litres: '',
        remarks: '',
        source: 'manual',
      })
      return { ...current, lines: [...current.lines, ...additions] }
    })
  }

  const handleTableLitresKeyDown = (event: KeyboardEvent<HTMLDivElement>, visibleIndex: number, isLastRow: boolean) => {
    if (event.key === 'Enter' || event.key === 'ArrowDown') {
      event.preventDefault()
      const nextItem = visibleTableLines[visibleIndex + 1]
      if (nextItem) {
        const el = tableLitresRefs.current[nextItem.line.key]
        el?.focus()
        el?.select?.()
      } else if (event.key === 'Enter' && isLastRow && !normalizedSearch && canEdit) {
        const currentLine = visibleTableLines[visibleIndex]?.line
        if (currentLine && (currentLine.company_id || currentLine.litres.trim())) {
          addLine()
        }
      }
    } else if (event.key === 'ArrowUp' || (event.key === 'Enter' && event.shiftKey)) {
      event.preventDefault()
      const prevItem = visibleTableLines[visibleIndex - 1]
      if (prevItem) {
        const el = tableLitresRefs.current[prevItem.line.key]
        el?.focus()
        el?.select?.()
      }
    }
  }

  const handleGridLitresKeyDown = (event: KeyboardEvent<HTMLDivElement>, slotIndex: number) => {
    if (event.key === 'Enter' && !event.shiftKey || event.key === 'ArrowDown') {
      event.preventDefault()
      const nextSlot = cappedGridSlots[slotIndex + 1]
      if (nextSlot) {
        const el = gridLitresRefs.current[nextSlot.company.id + ':' + nextSlot.extraIndex]
        el?.focus()
        el?.select?.()
      }
    } else if (event.key === 'ArrowUp' || (event.key === 'Enter' && event.shiftKey)) {
      event.preventDefault()
      const prevSlot = cappedGridSlots[slotIndex - 1]
      if (prevSlot) {
        const el = gridLitresRefs.current[prevSlot.company.id + ':' + prevSlot.extraIndex]
        el?.focus()
        el?.select?.()
      }
    }
  }

  const handlePasteCompanyRows = (event: ClipboardEvent<HTMLDivElement>, startRowIndex?: number) => {
    if (!canEdit) return
    const text = event.clipboardData?.getData('text/plain') ?? ''
    if (!text.includes('\n') && !text.includes('\t')) return

    // Case 1: Tab-separated Excel rows (`Company \t Litres` or `Company \t Category \t Litres \t Remarks`)
    if (text.includes('\t')) {
      const { matched, unmatched } = parseFuelCompanyPaste(text, companies)
      if (!matched.length && !unmatched.length) return
      event.preventDefault()
      if (matched.length) {
        setDraft(current => {
          const updated = [...current.lines]
          for (const incoming of matched) {
            const existingIdx = updated.findIndex(
              row => row.company_id === incoming.company_id && row.category_id === incoming.category_id,
            )
            if (existingIdx >= 0) {
              updated[existingIdx] = {
                ...updated[existingIdx],
                litres: incoming.litres,
                remarks: incoming.remarks || updated[existingIdx].remarks,
              }
            } else {
              updated.push(incoming)
            }
          }
          // Drop trailing blank placeholder rows if we pasted real rows.
          const cleaned = updated.filter(row => row.company_id || row.litres.trim() || row.remarks.trim())
          return { ...current, lines: cleaned }
        })
      }
      const msgParts = [`Pasted ${matched.length} company row(s)`]
      if (unmatched.length) msgParts.push(`unmatched: ${unmatched.slice(0, 4).join(', ')}${unmatched.length > 4 ? '…' : ''}`)
      setPasteFeedback(msgParts.join(' · '))
      return
    }

    // Case 2: Vertical column of numbers pasted onto a `Litres (AGO)` cell
    if (startRowIndex !== undefined) {
      const numbers = text
        .replace(/\r\n/g, '\n')
        .split('\n')
        .map(item => item.trim().replace(/,/g, ''))
        .filter(item => item !== '')
      if (numbers.length > 1 && numbers.every(val => Number.isFinite(Number(val)))) {
        event.preventDefault()
        setDraft(current => {
          const nextLines = [...current.lines]
          numbers.forEach((num, offset) => {
            const targetIdx = startRowIndex + offset
            if (targetIdx < nextLines.length) {
              nextLines[targetIdx] = { ...nextLines[targetIdx], litres: num }
            }
          })
          return { ...current, lines: nextLines }
        })
        setPasteFeedback(`Filled litres across ${Math.min(numbers.length, draft.lines.length - startRowIndex)} row(s).`)
      }
    }
  }

  const requestStepDate = (delta: number) => {
    if (!onChangeDate || saving) return
    const target = shiftIsoDate(costDate, delta)
    if (dirty && canEdit) {
      setPendingStepDate(target)
    } else {
      onChangeDate(target)
    }
  }

  const submitInternal = (advanceToDate?: string) => {
    if (!day || !canEdit || saving) return
    setAttempted(true)
    const validation = validateFuelDraft(draft, day)
    if (fuelHasErrors(validation)) return
    const payload = fuelSavePayload({
      rigId: day.rig_id,
      costDate,
      draft,
      day,
      expectedRevision: day.entry?.revision ?? null,
    })
    onSave(payload, day.entry?.id ?? null, advanceToDate ? { advanceToDate } : undefined)
  }

  const submit = () => submitInternal()
  const submitAndNextDay = () => {
    if (!onChangeDate) return
    submitInternal(shiftIsoDate(costDate, 1))
  }

  const handleDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault()
      if (event.shiftKey && onChangeDate) submitAndNextDay()
      else submit()
    }
  }

  const openInlineNewCompany = (lineKey: string | null = null) => {
    setNewCompanyLineKey(lineKey)
    setNewCompanyOpen(true)
    setNewCompanySource(availableVendors.length ? 'vendor' : 'manual')
    setNewCompanyVendorId(availableVendors[0]?.id ?? '')
    setNewCompanyName('')
    setNewCompanyDefault(true)
    setInlineError('')
  }

  const createInlineCompany = async () => {
    setInlineBusy(true)
    setInlineError('')
    try {
      const payload = newCompanySource === 'vendor'
        ? { vendor_id: newCompanyVendorId, is_default: newCompanyDefault }
        : { company_name: newCompanyName.trim(), is_default: newCompanyDefault }
      const created = await api<FuelCompany>('/fuel-cost/companies', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      await onCompaniesChanged(created)
      if (newCompanyLineKey) {
        updateLine(newCompanyLineKey, { company_id: created.id, category_id: '' })
      } else if (entryMode === 'table') {
        const next = { ...blankFuelLine(), company_id: created.id }
        pendingFocusLineKey.current = next.key
        setDraft(current => ({ ...current, lines: [...current.lines, next] }))
      }
      setNewCompanyLineKey(null)
      setNewCompanyOpen(false)
    } catch (err) {
      setInlineError((err as Error).message)
    } finally {
      setInlineBusy(false)
    }
  }

  const createInlineCategory = async () => {
    if (!newCategoryTarget) return
    setInlineBusy(true)
    setInlineError('')
    try {
      const updated = await api<FuelCompany>(
        `/fuel-cost/companies/${newCategoryTarget.companyId}/categories`,
        { method: 'POST', body: JSON.stringify({ category_name: newCategoryName.trim() }) },
      )
      await onCompaniesChanged(updated)
      const created = updated.categories.find(
        category => !category.is_deleted
          && category.category_name.toLowerCase() === newCategoryName.trim().toLowerCase(),
      )
      if (created) updateLine(newCategoryTarget.lineKey, { category_id: created.id })
      setNewCategoryTarget(null)
      setNewCategoryName('')
    } catch (err) {
      setInlineError((err as Error).message)
    } finally {
      setInlineBusy(false)
    }
  }

  const subtitle = rig
    ? `${rig.rig_code} — ${rig.rig_name} · ${displayDate(costDate)}`
    : displayDate(costDate)

  return (
    <>
      <FormDialog
        open={open}
        title="Fuel consumption"
        subtitle={subtitle}
        maxWidth="xl"
        onClose={onClose}
        onSubmit={submit}
        submitLabel={day?.entry ? 'Save fuel day' : 'Add fuel day'}
        busy={saving}
        busyLabel="Saving..."
        submitDisabled={!canEdit || !day || Boolean(loadError)}
        dirty={dirty && canEdit}
      >
        <Box onKeyDown={handleDialogKeyDown}>
          {saveError ? <ErrorMessage message={saveError} /> : null}
          {loading ? (
            <Typography color="text.secondary" sx={{ py: 3 }}>
              Loading fuel balance and company lines…
            </Typography>
          ) : loadError ? (
            <Alert severity="error">{loadError}</Alert>
          ) : !day || !preview ? (
            <Alert severity="info">Select a rig and date to enter fuel consumption.</Alert>
          ) : (
            <Stack spacing={1.5}>
              {errors.summary.length ? (
                <Alert severity="error" sx={{ py: 0.5 }}>
                  <Stack spacing={0.25}>
                    {errors.summary.map(message => (
                      <Typography key={message} sx={{ fontSize: 13 }}>{message}</Typography>
                    ))}
                  </Stack>
                </Alert>
              ) : null}

              {/* Compact Top Context & Action Bar */}
              <Stack
                direction={{ xs: 'column', md: 'row' }}
                spacing={1}
                alignItems={{ xs: 'flex-start', md: 'center' }}
                justifyContent="space-between"
              >
                <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Tag tone="info">{rig?.rig_code ?? day.rig_code}</Tag>
                  {onChangeDate ? (
                    <Stack direction="row" spacing={0.25} alignItems="center">
                      <Tooltip title="Previous day">
                        <span>
                          <IconButton
                            size="small"
                            aria-label="Previous fuel date"
                            disabled={saving}
                            onClick={() => requestStepDate(-1)}
                          >
                            <ChevronLeft fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tag>{displayDate(costDate)}</Tag>
                      <Tooltip title="Next day">
                        <span>
                          <IconButton
                            size="small"
                            aria-label="Next fuel date"
                            disabled={saving}
                            onClick={() => requestStepDate(1)}
                          >
                            <ChevronRight fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </Stack>
                  ) : (
                    <Tag>{displayDate(costDate)}</Tag>
                  )}
                  {isFirst ? (
                    <Tag tone="warning">First fuel entry — opening stock required</Tag>
                  ) : preview.overrideActive ? (
                    <Tag tone="warning">Opening stock overridden</Tag>
                  ) : (
                    <Tag>
                      Carried from the closing stock{day.balance.previous_date ? ` (${displayDate(day.balance.previous_date)})` : ''}
                    </Tag>
                  )}
                  {!canEdit ? <Tag>Read only</Tag> : null}
                  {day.entry ? <Tag>Revision {day.entry.revision}</Tag> : <Tag tone="info">New day</Tag>}
                </Stack>

                <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Button
                    size="small"
                    variant={showRemarks ? 'outlined' : 'text'}
                    aria-expanded={showRemarks}
                    endIcon={showRemarks ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
                    onClick={() => setShowRemarks(openState => !openState)}
                  >
                    Remarks{remarkCount ? ` (${remarkCount})` : ''}
                  </Button>
                  <Button
                    size="small"
                    variant={showShortcuts ? 'outlined' : 'text'}
                    aria-expanded={showShortcuts}
                    startIcon={<KeyboardOutlined fontSize="small" />}
                    onClick={() => setShowShortcuts(openState => !openState)}
                  >
                    Shortcuts
                  </Button>
                  {canEdit && onChangeDate ? (
                    <Tooltip title="Save this day and immediately advance to the next calendar day (Ctrl/⌘+Shift+S)">
                      <span>
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={saving || Boolean(loadError)}
                          endIcon={<ChevronRight fontSize="small" />}
                          onClick={submitAndNextDay}
                        >
                          Save & next day
                        </Button>
                      </span>
                    </Tooltip>
                  ) : null}
                </Stack>
              </Stack>

              <Collapse in={showShortcuts}>
                <Alert severity="info" sx={{ py: 0.5 }}>
                  <Typography sx={{ fontSize: 12.5 }}>
                    <strong>Fast entry:</strong> Press <strong>Enter</strong> or <strong>↓ / ↑</strong> inside Litres to move down/up rows ·{' '}
                    <strong>Paste from Excel</strong> (<code>Company ⇥ Litres</code> or <code>Company ⇥ Category ⇥ Litres</code>) directly into the table ·{' '}
                    <strong>Quick-fill grid</strong> shows companies side-by-side without dropdown clicks ·{' '}
                    <strong>Ctrl/⌘ + S</strong> saves ({onChangeDate ? 'Ctrl/⌘ + Shift + S saves & opens next day' : 'instant save'}).
                  </Typography>
                </Alert>
              </Collapse>

              {/* Live Compact Material Balance Ribbon (Pinned above inputs so zero scrolling is needed) */}
              <Paper variant="outlined" sx={{ p: 1.25, borderRadius: 2 }}>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  spacing={0.75}
                  alignItems={{ xs: 'flex-start', sm: 'center' }}
                  justifyContent="space-between"
                  sx={{ mb: 0.9 }}
                >
                  <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
                    <Typography sx={{ fontWeight: 800, fontSize: 13.5 }}>Material balance</Typography>
                    <Typography color="text.secondary" sx={{ fontSize: 11.5 }}>
                      All AGO figures in litres · Rig saving recorded separately:{' '}
                      <Box component="span" sx={{ fontWeight: 700, color: 'text.primary', fontVariantNumeric: 'tabular-nums' }}>
                        {fuelLitres(preview.gas)} L
                      </Box>{' '}
                      (AGO saved via gas — not part of AGO consumption)
                    </Typography>
                  </Stack>
                  {preview.adjustments !== 0 ? (
                    <Tag tone="warning">
                      Net stock adjustment {preview.adjustments > 0 ? '+' : ''}{fuelLitres(preview.adjustments)} L
                    </Tag>
                  ) : null}
                </Stack>

                <Box
                  sx={{
                    display: 'grid',
                    gap: 0.75,
                    gridTemplateColumns: {
                      xs: 'repeat(2, minmax(0, 1fr))',
                      sm: 'repeat(3, minmax(0, 1fr))',
                      lg: 'repeat(9, minmax(0, 1fr))',
                    },
                  }}
                >
                  <BalanceTile
                    label="OPENING STOCK"
                    value={fuelLitres(preview.opening)}
                    note={isFirst ? 'First rig day' : preview.overrideActive ? `Carried ${fuelLitres(preview.carried)}` : 'Carried forward'}
                  />
                  <BalanceTile
                    label="OPENING ADJ."
                    value={fuelLitres(preview.openingAdjustment)}
                    note={preview.openingAdjustment ? 'Override delta' : 'None'}
                    tone={preview.openingAdjustment !== 0 ? 'warning' : 'default'}
                  />
                  <BalanceTile
                    label="RECEIPT"
                    value={fuelLitres(preview.receipt)}
                    note="Delivered"
                  />
                  <BalanceTile
                    label="RIG ENGINES"
                    value={fuelLitres(preview.engine)}
                    note="AGO"
                  />
                  <BalanceTile
                    label="COMPANIES"
                    value={fuelLitres(preview.company)}
                    note={`${enteredLineCount} line(s)`}
                  />
                  <BalanceTile
                    label="TOTAL AGO CONSUMPTION"
                    value={fuelLitres(preview.totalConsumption)}
                    note="Engines + companies"
                    emphasize
                  />
                  <BalanceTile
                    label="BOOK CLOSING"
                    value={fuelLitres(preview.bookClosing)}
                    note="Open + rcpt − AGO"
                  />
                  <BalanceTile
                    label="ACTUAL CLOSING"
                    value={fuelLitres(preview.actualClosing)}
                    note={draft.closing.trim() === '' ? 'Follows book' : 'Physical dip'}
                    emphasize
                  />
                  <BalanceTile
                    label="CLOSING ADJ."
                    value={fuelLitres(preview.closingAdjustment)}
                    note="Actual − book"
                    tone={preview.closingAdjustment !== 0 ? 'warning' : 'default'}
                  />
                </Box>
              </Paper>

              {/* Unified Compact Core Inputs Band: Stock, Receipts, Rig Engines & Rig Saving (Litres) */}
              <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  spacing={0.5}
                  alignItems={{ xs: 'flex-start', sm: 'center' }}
                  justifyContent="space-between"
                  sx={{ mb: 1.25 }}
                >
                  <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
                    <Typography sx={{ fontWeight: 800, fontSize: 13.5 }}>
                      Rig engines · Stock and receipts
                    </Typography>
                    <Typography color="text.secondary" sx={{ fontSize: 11.5 }}>
                      {isFirst
                        ? 'Enter initial physical opening stock; subsequent days carry closing stock forward automatically.'
                        : `Carried from the closing stock: ${fuelLitres(preview.carried)} L${canOverrideOpening ? ' (override permitted)' : ''}.`}
                    </Typography>
                  </Stack>
                  <Button
                    size="small"
                    variant={draft.openingOverride ? 'outlined' : 'text'}
                    disabled={isFirst || !canEdit || saving || !canOverrideOpening}
                    onClick={() =>
                      setDraft(current => ({
                        ...current,
                        openingOverride: !current.openingOverride,
                        opening: !current.openingOverride ? (current.opening || String(preview.carried)) : '',
                      }))
                    }
                    sx={{ minWidth: 'auto', py: 0.25 }}
                  >
                    {draft.openingOverride ? 'Use carried' : 'Override'}
                  </Button>
                </Stack>

                <Box
                  sx={{
                    display: 'grid',
                    gap: 1.25,
                    gridTemplateColumns: {
                      xs: '1fr',
                      sm: 'repeat(2, minmax(0, 1fr))',
                      lg: 'repeat(5, minmax(0, 1fr))',
                    },
                  }}
                >
                  <TextField
                    size="small"
                    type="number"
                    label="Opening stock (litres)"
                    value={openingEditable ? draft.opening : String(preview.carried)}
                    onChange={event => {
                      if (openingEditable) setField('opening', event.target.value)
                    }}
                    disabled={!canEdit || saving}
                    InputProps={{ readOnly: !openingEditable }}
                    error={Boolean(errors.opening)}
                    helperText={
                      errors.opening
                      || (isFirst
                        ? 'Mandatory day-1 dip'
                        : draft.openingOverride
                          ? `Adj: ${fuelLitres(preview.openingAdjustment)} L`
                          : !canOverrideOpening
                            ? 'Carried (override restricted)'
                            : 'Carried closing stock')
                    }
                    inputProps={{ min: 0, step: 'any' }}
                    fullWidth
                  />
                  <TextField
                    size="small"
                    type="number"
                    label="Receipt (litres)"
                    value={draft.receipt}
                    onChange={event => setField('receipt', event.target.value)}
                    disabled={!canEdit || saving}
                    error={Boolean(errors.receipt)}
                    helperText={errors.receipt || 'Delivered to rig tanks'}
                    inputProps={{ min: 0, step: 'any' }}
                    fullWidth
                  />
                  <TextField
                    size="small"
                    type="number"
                    label="Rig engine consumption (litres)"
                    value={draft.rigEngine}
                    onChange={event => setField('rigEngine', event.target.value)}
                    disabled={!canEdit || saving}
                    error={Boolean(errors.engine)}
                    helperText={errors.engine || 'Counted in AGO balance'}
                    inputProps={{ min: 0, step: 'any' }}
                    fullWidth
                  />
                  <TextField
                    size="small"
                    type="number"
                    label="Actual closing stock (litres)"
                    value={draft.closing}
                    onChange={event => setField('closing', event.target.value)}
                    placeholder={fuelLitres(preview.bookClosing)}
                    disabled={!canEdit || saving}
                    error={Boolean(errors.closing)}
                    helperText={errors.closing || `Book: ${fuelLitres(preview.bookClosing)} L`}
                    inputProps={{ min: 0, step: 'any' }}
                    fullWidth
                  />
                  <TextField
                    size="small"
                    type="number"
                    label="Rig saving (litres)"
                    value={draft.gas}
                    onChange={event => setField('gas', event.target.value)}
                    disabled={!canEdit || saving}
                    error={Boolean(errors.gas)}
                    helperText={errors.gas || 'AGO saved via gas (excluded from AGO)'}
                    inputProps={{ min: 0, step: 'any' }}
                    fullWidth
                  />
                </Box>

                <Collapse in={showRemarks}>
                  <Box
                    sx={{
                      mt: 1.5,
                      pt: 1.5,
                      borderTop: '1px solid',
                      borderColor: 'divider',
                      display: 'grid',
                      gap: 1.25,
                      gridTemplateColumns: {
                        xs: '1fr',
                        sm: 'repeat(2, minmax(0, 1fr))',
                        lg: 'repeat(3, minmax(0, 1fr))',
                      },
                    }}
                  >
                    <TextField
                      size="small"
                      label="Rig engine remarks"
                      value={draft.rigEngineRemarks}
                      onChange={event => setField('rigEngineRemarks', event.target.value)}
                      disabled={!canEdit || saving}
                      fullWidth
                    />
                    <TextField
                      size="small"
                      label="Rig saving remarks"
                      value={draft.gasRemarks}
                      onChange={event => setField('gasRemarks', event.target.value)}
                      placeholder="Generator hours on gas, dual-fuel note…"
                      disabled={!canEdit || saving}
                      fullWidth
                    />
                    <TextField
                      size="small"
                      label="Receipt remarks"
                      value={draft.receiptRemarks}
                      onChange={event => setField('receiptRemarks', event.target.value)}
                      placeholder="Waybill, supplier or meter ticket"
                      disabled={!canEdit || saving}
                      fullWidth
                    />
                    <TextField
                      size="small"
                      label="Closing stock remarks"
                      value={draft.closingRemarks}
                      onChange={event => setField('closingRemarks', event.target.value)}
                      placeholder="Evening dip note or calibration variance"
                      disabled={!canEdit || saving}
                      fullWidth
                    />
                    {openingEditable || draft.openingRemarks ? (
                      <TextField
                        size="small"
                        label="Opening stock remarks"
                        value={draft.openingRemarks}
                        onChange={event => setField('openingRemarks', event.target.value)}
                        disabled={!canEdit || saving}
                        fullWidth
                      />
                    ) : null}
                    <TextField
                      size="small"
                      label="Day remarks"
                      value={draft.remarks}
                      onChange={event => setField('remarks', event.target.value)}
                      placeholder="Handover notes, rig move or operational context"
                      disabled={!canEdit || saving}
                      fullWidth
                    />
                  </Box>
                </Collapse>
              </Paper>

              {/* Fast, Compact Company Consumption Section (Bounded height + Worksheet & 3-Column Quick-Fill Grid) */}
              <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                <Stack
                  direction={{ xs: 'column', lg: 'row' }}
                  spacing={1}
                  alignItems={{ xs: 'flex-start', lg: 'center' }}
                  justifyContent="space-between"
                  sx={{ mb: 1.1 }}
                >
                  <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
                    <Typography sx={{ fontWeight: 800, fontSize: 13.5 }}>
                      Company consumption (AGO)
                    </Typography>
                    <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                      {enteredLineCount} active line(s) · Company AGO total:{' '}
                      <Box component="span" sx={{ fontWeight: 800, color: 'text.primary', fontVariantNumeric: 'tabular-nums' }}>
                        {fuelLitres(preview.company)} L
                      </Box>
                    </Typography>
                  </Stack>

                  <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Stack
                      direction="row"
                      spacing={0.25}
                      sx={{
                        p: 0.25,
                        borderRadius: 1.25,
                        border: '1px solid',
                        borderColor: 'divider',
                      }}
                    >
                      <Button
                        size="small"
                        variant={entryMode === 'table' ? 'contained' : 'text'}
                        aria-pressed={entryMode === 'table'}
                        startIcon={<TableRowsOutlined fontSize="small" />}
                        onClick={() => setEntryMode('table')}
                        sx={{ py: 0.25, px: 1 }}
                      >
                        Worksheet
                      </Button>
                      <Button
                        size="small"
                        variant={entryMode === 'grid' ? 'contained' : 'text'}
                        aria-pressed={entryMode === 'grid'}
                        startIcon={<GridViewOutlined fontSize="small" />}
                        onClick={() => setEntryMode('grid')}
                        sx={{ py: 0.25, px: 1 }}
                      >
                        Quick-fill ({activeCompanies.length})
                      </Button>
                    </Stack>

                    {canEdit ? (
                      <>
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<PlaylistAdd fontSize="small" />}
                          disabled={saving || !defaultCount}
                          onClick={addDefaultSet}
                        >
                          Add daily set{defaultCount ? ` (${defaultCount})` : ''}
                        </Button>
                        {previousLines.length > 0 ? (
                          <Tooltip
                            title={`Load ${previousLines.length} company/category row(s) from ${day.balance.previous_date ? displayDate(day.balance.previous_date) : 'previous day'} with blank litres`}
                          >
                            <span>
                              <Button
                                size="small"
                                variant="outlined"
                                startIcon={<ContentCopy fontSize="small" />}
                                disabled={saving}
                                onClick={copyPreviousDaySet}
                              >
                                Copy previous ({previousLines.length})
                              </Button>
                            </span>
                          </Tooltip>
                        ) : null}
                        {entryMode === 'table' ? (
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<Add fontSize="small" />}
                            disabled={saving}
                            onClick={addLine}
                          >
                            Add company
                          </Button>
                        ) : null}
                        {canManageCompanies ? (
                          <Button
                            size="small"
                            variant="text"
                            startIcon={<Add fontSize="small" />}
                            disabled={saving}
                            onClick={() => openInlineNewCompany(null)}
                          >
                            Register company
                          </Button>
                        ) : null}
                        {entryMode === 'table' && blankLineCount > 0 ? (
                          <Button
                            size="small"
                            variant="text"
                            disabled={saving}
                            onClick={clearEmptyLines}
                          >
                            Clear empty ({blankLineCount})
                          </Button>
                        ) : null}
                      </>
                    ) : null}
                  </Stack>
                </Stack>

                {pasteFeedback ? (
                  <Alert
                    severity="info"
                    onClose={() => setPasteFeedback('')}
                    sx={{ mb: 1, py: 0.25 }}
                  >
                    {pasteFeedback}
                  </Alert>
                ) : null}

                {/* Top Inline New-Company Creator */}
                {newCompanyOpen ? (
                  <Paper
                    variant="outlined"
                    sx={{ p: 1.25, mb: 1.25, borderRadius: 1.5, bgcolor: 'action.hover' }}
                  >
                    <Typography sx={{ fontWeight: 700, fontSize: 12.5, mb: 1 }}>
                      Register company in Fuel Cost Register
                    </Typography>
                    {inlineError ? <Alert severity="error" sx={{ mb: 1, py: 0.25 }}>{inlineError}</Alert> : null}
                    <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} alignItems={{ md: 'center' }}>
                      <TextField
                        select
                        size="small"
                        label="Company source"
                        value={newCompanySource}
                        onChange={event => setNewCompanySource(event.target.value as 'vendor' | 'manual')}
                        sx={{ minWidth: 165 }}
                      >
                        <MenuItem value="vendor" disabled={!availableVendors.length}>From Master Data</MenuItem>
                        <MenuItem value="manual">Manual name</MenuItem>
                      </TextField>
                      {newCompanySource === 'vendor' ? (
                        <TextField
                          select
                          size="small"
                          label="Vendor"
                          value={newCompanyVendorId}
                          onChange={event => setNewCompanyVendorId(event.target.value)}
                          sx={{ flex: 1, minWidth: 220 }}
                        >
                          {availableVendors.map(vendor => (
                            <MenuItem key={vendor.id} value={vendor.id}>{vendor.display_name}</MenuItem>
                          ))}
                        </TextField>
                      ) : (
                        <TextField
                          size="small"
                          label="Company name"
                          value={newCompanyName}
                          onChange={event => setNewCompanyName(event.target.value)}
                          sx={{ flex: 1, minWidth: 220 }}
                        />
                      )}
                      <FormControlLabel
                        control={(
                          <Checkbox
                            size="small"
                            checked={newCompanyDefault}
                            onChange={event => setNewCompanyDefault(event.target.checked)}
                          />
                        )}
                        label={<Typography sx={{ fontSize: 12.5 }}>Include in daily set</Typography>}
                      />
                      <Stack direction="row" spacing={0.75}>
                        <Button
                          size="small"
                          variant="contained"
                          disabled={
                            inlineBusy
                            || (newCompanySource === 'vendor' ? !newCompanyVendorId : !newCompanyName.trim())
                          }
                          onClick={createInlineCompany}
                        >
                          {inlineBusy ? 'Adding…' : 'Add'}
                        </Button>
                        <Button
                          size="small"
                          disabled={inlineBusy}
                          onClick={() => {
                            setNewCompanyOpen(false)
                            setNewCompanyLineKey(null)
                          }}
                        >
                          Cancel
                        </Button>
                      </Stack>
                    </Stack>
                  </Paper>
                ) : null}

                {/* Top Inline New-Category Creator */}
                {newCategoryTarget ? (
                  <Paper
                    variant="outlined"
                    sx={{ p: 1.25, mb: 1.25, borderRadius: 1.5, bgcolor: 'action.hover' }}
                  >
                    <Typography sx={{ fontWeight: 700, fontSize: 12.5, mb: 0.75 }}>
                      Add category for {companyById.get(newCategoryTarget.companyId)?.company_name ?? 'company'}
                    </Typography>
                    {inlineError ? <Alert severity="error" sx={{ mb: 1, py: 0.25 }}>{inlineError}</Alert> : null}
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
                      <TextField
                        size="small"
                        label="Category name"
                        value={newCategoryName}
                        onChange={event => setNewCategoryName(event.target.value)}
                        placeholder="Crew vehicles, Camp generator, Cranes…"
                        sx={{ flex: 1, minWidth: 220 }}
                      />
                      <Stack direction="row" spacing={0.75}>
                        <Button
                          size="small"
                          variant="contained"
                          disabled={inlineBusy || !newCategoryName.trim()}
                          onClick={createInlineCategory}
                        >
                          {inlineBusy ? 'Adding…' : 'Add category'}
                        </Button>
                        <Button
                          size="small"
                          disabled={inlineBusy}
                          onClick={() => setNewCategoryTarget(null)}
                        >
                          Cancel
                        </Button>
                      </Stack>
                    </Stack>
                  </Paper>
                ) : null}

                {/* Search & Quick Filter Bar (Always visible in Grid mode, and in Worksheet mode when > 5 rows or filtered) */}
                {(entryMode === 'grid' || draft.lines.length > 5 || Boolean(searchQuery)) ? (
                  <Stack
                    direction={{ xs: 'column', sm: 'row' }}
                    spacing={1}
                    alignItems={{ sm: 'center' }}
                    justifyContent="space-between"
                    sx={{ mb: 1 }}
                  >
                    <TextField
                      size="small"
                      placeholder="Filter companies, vendor codes or categories…"
                      value={searchQuery}
                      onChange={event => setSearchQuery(event.target.value)}
                      inputProps={{ 'aria-label': 'Filter companies' }}
                      InputProps={{
                        startAdornment: (
                          <InputAdornment position="start">
                            <Search fontSize="small" color="action" />
                          </InputAdornment>
                        ),
                      }}
                      sx={{ width: { xs: '100%', sm: 320 } }}
                    />
                    {entryMode === 'grid' ? (
                      <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Button
                          size="small"
                          variant={gridFilter === 'all' ? 'contained' : 'outlined'}
                          aria-pressed={gridFilter === 'all'}
                          onClick={() => setGridFilter('all')}
                          sx={{ py: 0.25 }}
                        >
                          All ({activeCompanies.length})
                        </Button>
                        <Button
                          size="small"
                          variant={gridFilter === 'default' ? 'contained' : 'outlined'}
                          aria-pressed={gridFilter === 'default'}
                          onClick={() => setGridFilter('default')}
                          sx={{ py: 0.25 }}
                        >
                          Daily set ({defaultCount})
                        </Button>
                        <Button
                          size="small"
                          variant={gridFilter === 'entered' ? 'contained' : 'outlined'}
                          aria-pressed={gridFilter === 'entered'}
                          onClick={() => setGridFilter('entered')}
                          sx={{ py: 0.25 }}
                        >
                          Entered ({enteredCompanyIds.size})
                        </Button>
                      </Stack>
                    ) : searchQuery ? (
                      <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                        Showing {visibleTableLines.length} of {draft.lines.length} row(s)
                      </Typography>
                    ) : null}
                  </Stack>
                ) : null}

                {/* MODE 1: Dense Bounded-Scroll Worksheet Table */}
                {entryMode === 'table' ? (
                  !draft.lines.length ? (
                    <Box
                      onPaste={event => handlePasteCompanyRows(event)}
                      tabIndex={0}
                      sx={{
                        py: 2,
                        px: 1.5,
                        borderRadius: 1.5,
                        border: '1px dashed',
                        borderColor: 'divider',
                        textAlign: 'center',
                      }}
                    >
                      <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                        No company AGO lines entered yet. Click <strong>Add daily set</strong>,{' '}
                        {previousLines.length ? <><strong>Copy previous</strong>, </> : null}
                        <strong>Add company</strong>, switch to <strong>Quick-fill ({activeCompanies.length})</strong>, or paste rows from Excel.
                      </Typography>
                    </Box>
                  ) : (
                    <TableContainer
                      sx={{
                        maxHeight: 295,
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1.5,
                      }}
                    >
                      <Table size="small" stickyHeader aria-label="Company AGO consumption worksheet">
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ width: 42, py: 0.75, fontSize: 11, fontWeight: 800 }}>#</TableCell>
                            <TableCell sx={{ minWidth: 210, py: 0.75, fontSize: 11, fontWeight: 800 }}>COMPANY</TableCell>
                            <TableCell sx={{ minWidth: 165, py: 0.75, fontSize: 11, fontWeight: 800 }}>CATEGORY</TableCell>
                            <TableCell sx={{ width: 165, py: 0.75, fontSize: 11, fontWeight: 800 }}>LITRES (AGO)</TableCell>
                            <TableCell sx={{ minWidth: 170, py: 0.75, fontSize: 11, fontWeight: 800 }}>REMARKS</TableCell>
                            {canEdit ? <TableCell align="right" sx={{ width: 52, py: 0.75 }} /> : null}
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {visibleTableLines.map(({ line, idx }, visibleIdx) => {
                            const company = companyById.get(line.company_id)
                            const categories = (company?.categories ?? []).filter(
                              category => !category.is_deleted || category.id === line.category_id,
                            )
                            const rowCompanyOptions = activeCompanies.some(item => item.id === line.company_id)
                              || !company
                              ? activeCompanies
                              : [company, ...activeCompanies]
                            const lineError = errors.lines[line.key]
                            const isLastVisible = visibleIdx === visibleTableLines.length - 1

                            return (
                              <TableRow
                                key={line.key}
                                hover
                                sx={lineError ? { bgcolor: 'action.selected' } : undefined}
                              >
                                <TableCell
                                  sx={{
                                    py: 0.5,
                                    fontSize: 12,
                                    color: 'text.secondary',
                                    fontVariantNumeric: 'tabular-nums',
                                  }}
                                >
                                  {idx + 1}
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  <TextField
                                    select
                                    size="small"
                                    label="Company"
                                    value={line.company_id}
                                    onChange={event => {
                                      const value = event.target.value
                                      if (value === NEW_COMPANY_VALUE) {
                                        openInlineNewCompany(line.key)
                                        return
                                      }
                                      const nextComp = companyById.get(value)
                                      const activeCats = (nextComp?.categories ?? []).filter(cat => !cat.is_deleted)
                                      updateLine(line.key, {
                                        company_id: value,
                                        category_id: activeCats.length === 1 ? activeCats[0].id : '',
                                      })
                                    }}
                                    disabled={!canEdit || saving}
                                    error={Boolean(lineError && !line.company_id)}
                                    helperText={lineError && !line.company_id ? lineError : undefined}
                                    fullWidth
                                  >
                                    <MenuItem value="">Select company</MenuItem>
                                    {rowCompanyOptions.map(option => (
                                      <MenuItem key={option.id} value={option.id}>
                                        {option.display_name}{option.is_deleted ? ' (deleted)' : ''}
                                      </MenuItem>
                                    ))}
                                    {canManageCompanies ? (
                                      <MenuItem value={NEW_COMPANY_VALUE}>+ Add new company…</MenuItem>
                                    ) : null}
                                  </TextField>
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  <TextField
                                    select
                                    size="small"
                                    label="Category"
                                    value={line.category_id}
                                    onChange={event => {
                                      const value = event.target.value
                                      if (value === NEW_CATEGORY_VALUE && line.company_id) {
                                        setNewCategoryTarget({ lineKey: line.key, companyId: line.company_id })
                                        setNewCategoryName('')
                                        setInlineError('')
                                        return
                                      }
                                      updateLine(line.key, { category_id: value })
                                    }}
                                    disabled={!canEdit || saving || !line.company_id}
                                    fullWidth
                                  >
                                    <MenuItem value="">Uncategorised</MenuItem>
                                    {categories.map(category => (
                                      <MenuItem key={category.id} value={category.id}>
                                        {category.category_name}{category.is_deleted ? ' (deleted)' : ''}
                                      </MenuItem>
                                    ))}
                                    {canManageCompanies && line.company_id ? (
                                      <MenuItem value={NEW_CATEGORY_VALUE}>+ Add category…</MenuItem>
                                    ) : null}
                                  </TextField>
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  <TextField
                                    size="small"
                                    type="number"
                                    label="Litres (AGO)"
                                    value={line.litres}
                                    inputRef={el => {
                                      tableLitresRefs.current[line.key] = el
                                    }}
                                    onChange={event => updateLine(line.key, { litres: event.target.value })}
                                    onKeyDown={event => handleTableLitresKeyDown(event, visibleIdx, isLastVisible)}
                                    onPaste={event => handlePasteCompanyRows(event, idx)}
                                    disabled={!canEdit || saving}
                                    error={Boolean(lineError && line.company_id)}
                                    helperText={lineError && line.company_id ? lineError : undefined}
                                    inputProps={{ min: 0, step: 'any' }}
                                    sx={{ '& input': { fontVariantNumeric: 'tabular-nums' } }}
                                    fullWidth
                                  />
                                </TableCell>
                                <TableCell sx={{ py: 0.5 }}>
                                  <TextField
                                    size="small"
                                    label="Remarks"
                                    value={line.remarks}
                                    onChange={event => updateLine(line.key, { remarks: event.target.value })}
                                    onKeyDown={event => handleTableLitresKeyDown(event, visibleIdx, isLastVisible)}
                                    placeholder="Equipment, unit or ticket"
                                    disabled={!canEdit || saving}
                                    fullWidth
                                  />
                                </TableCell>
                                {canEdit ? (
                                  <TableCell align="right" sx={{ py: 0.5 }}>
                                    <IconButton
                                      size="small"
                                      aria-label="Remove company row"
                                      disabled={saving}
                                      onClick={() => removeLine(line.key)}
                                    >
                                      <DeleteOutline fontSize="small" />
                                    </IconButton>
                                  </TableCell>
                                ) : null}
                              </TableRow>
                            )
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  )
                ) : (
                  /* MODE 2: 3-Column Quick-Fill Matrix (Zero dropdown clicks, handles hundreds of companies smoothly) */
                  !activeCompanies.length ? (
                    <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                      No companies registered yet. Click <strong>Register company</strong> above to add contractors or rig support companies.
                    </Typography>
                  ) : !allGridSlots.length ? (
                    <Typography color="text.secondary" sx={{ fontSize: 13 }}>
                      No companies match the current filter.
                    </Typography>
                  ) : (
                    <Stack spacing={1}>
                      <Box
                        onPaste={event => handlePasteCompanyRows(event)}
                        sx={{
                          maxHeight: 310,
                          overflowY: 'auto',
                          pr: 0.5,
                          display: 'grid',
                          gap: 0.75,
                          gridTemplateColumns: {
                            xs: '1fr',
                            sm: 'repeat(2, minmax(0, 1fr))',
                            lg: 'repeat(3, minmax(0, 1fr))',
                          },
                        }}
                      >
                        {cappedGridSlots.map((slot, slotIdx) => {
                          const { company, line, extraIndex } = slot
                          const categories = company.categories.filter(
                            cat => !cat.is_deleted || cat.id === line?.category_id,
                          )
                          const litresVal = line?.litres ?? ''
                          const hasLitres = fuelNumber(litresVal) > 0
                          const lineError = line ? errors.lines[line.key] : undefined

                          return (
                            <Box
                              key={slot.slotKey}
                              sx={{
                                px: 1,
                                py: 0.75,
                                borderRadius: 1.25,
                                border: '1px solid',
                                borderColor: lineError
                                  ? 'error.main'
                                  : hasLitres
                                    ? 'primary.main'
                                    : 'divider',
                                bgcolor: hasLitres ? 'action.hover' : 'background.paper',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: 0.75,
                              }}
                            >
                              <Box sx={{ minWidth: 0, flex: 1 }}>
                                <Stack direction="row" spacing={0.5} alignItems="center">
                                  <Typography
                                    sx={{
                                      fontSize: 12.5,
                                      fontWeight: hasLitres ? 800 : 600,
                                      whiteSpace: 'nowrap',
                                      overflow: 'hidden',
                                      textOverflow: 'ellipsis',
                                    }}
                                    title={company.display_name}
                                  >
                                    {company.company_name}
                                  </Typography>
                                  {company.is_default && extraIndex === 0 ? (
                                    <Box
                                      component="span"
                                      sx={{
                                        fontSize: 9.5,
                                        px: 0.5,
                                        py: 0.1,
                                        borderRadius: 0.75,
                                        bgcolor: 'action.selected',
                                        color: 'text.secondary',
                                        fontWeight: 700,
                                        flexShrink: 0,
                                      }}
                                    >
                                      DAILY
                                    </Box>
                                  ) : null}
                                </Stack>

                                {categories.length > 0 || canManageCompanies ? (
                                  <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.35 }}>
                                    <TextField
                                      select
                                      variant="standard"
                                      size="small"
                                      value={line?.category_id ?? ''}
                                      onChange={event => setGridSlotCategory(slot, event.target.value)}
                                      disabled={!canEdit || saving}
                                      inputProps={{ 'aria-label': `${company.company_name} category` }}
                                      sx={{ minWidth: 110, maxWidth: 165, '& .MuiInput-input': { fontSize: 11.5, py: 0.15 } }}
                                    >
                                      <MenuItem value="">Uncategorised</MenuItem>
                                      {categories.map(cat => (
                                        <MenuItem key={cat.id} value={cat.id}>{cat.category_name}</MenuItem>
                                      ))}
                                      {canManageCompanies ? (
                                        <MenuItem value={NEW_CATEGORY_VALUE}>+ Add category…</MenuItem>
                                      ) : null}
                                    </TextField>
                                    {canEdit && categories.length > 1 && extraIndex === 0 ? (
                                      <Tooltip title="Add another category row for this company">
                                        <IconButton
                                          size="small"
                                          aria-label={`Split category row for ${company.company_name}`}
                                          onClick={() => splitCompanySlot(company)}
                                          sx={{ p: 0.2 }}
                                        >
                                          <Add sx={{ fontSize: 15 }} />
                                        </IconButton>
                                      </Tooltip>
                                    ) : null}
                                    {canEdit && extraIndex > 0 && line ? (
                                      <Tooltip title="Remove extra category row">
                                        <IconButton
                                          size="small"
                                          aria-label={`Remove split row for ${company.company_name}`}
                                          onClick={() => removeLine(line.key)}
                                          sx={{ p: 0.2 }}
                                        >
                                          <DeleteOutline sx={{ fontSize: 15 }} />
                                        </IconButton>
                                      </Tooltip>
                                    ) : null}
                                  </Stack>
                                ) : company.vendor_code ? (
                                  <Typography color="text.secondary" sx={{ fontSize: 10.5 }}>
                                    {company.vendor_code}
                                  </Typography>
                                ) : null}

                                {lineError ? (
                                  <Typography color="error" sx={{ fontSize: 10.5, mt: 0.25 }}>
                                    {lineError}
                                  </Typography>
                                ) : null}
                              </Box>

                              <TextField
                                size="small"
                                type="number"
                                placeholder="0"
                                value={litresVal}
                                inputRef={el => {
                                  gridLitresRefs.current[company.id + ':' + extraIndex] = el
                                }}
                                onChange={event => setGridSlotLitres(slot, event.target.value)}
                                onKeyDown={event => handleGridLitresKeyDown(event, slotIdx)}
                                disabled={!canEdit || saving}
                                error={Boolean(lineError)}
                                inputProps={{
                                  min: 0,
                                  step: 'any',
                                  'aria-label': `${company.company_name} litres (AGO)`,
                                }}
                                sx={{
                                  width: 108,
                                  flexShrink: 0,
                                  '& input': {
                                    textAlign: 'right',
                                    fontVariantNumeric: 'tabular-nums',
                                    py: 0.65,
                                    px: 1,
                                    fontSize: 13,
                                    fontWeight: hasLitres ? 700 : 500,
                                  },
                                }}
                              />
                            </Box>
                          )
                        })}
                      </Box>

                      {allGridSlots.length > cappedGridSlots.length ? (
                        <Stack direction="row" spacing={1} alignItems="center" justifyContent="center">
                          <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                            Showing {cappedGridSlots.length} of {allGridSlots.length} companies
                          </Typography>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={() => setGridRenderCap(cap => cap + GRID_PAGE_CHUNK)}
                          >
                            Show {Math.min(GRID_PAGE_CHUNK, allGridSlots.length - cappedGridSlots.length)} more
                          </Button>
                          <Button
                            size="small"
                            variant="text"
                            onClick={() => setGridRenderCap(allGridSlots.length)}
                          >
                            Show all ({allGridSlots.length})
                          </Button>
                        </Stack>
                      ) : null}
                    </Stack>
                  )
                )}
              </Paper>
            </Stack>
          )}
        </Box>
      </FormDialog>

      <FormDialog
        open={Boolean(pendingStepDate)}
        title="Discard unsaved fuel changes?"
        onClose={() => setPendingStepDate(null)}
        onSubmit={() => {
          const targetDate = pendingStepDate
          setPendingStepDate(null)
          if (targetDate && onChangeDate) onChangeDate(targetDate)
        }}
        submitLabel="Discard & switch day"
        danger
        dirty={false}
        maxWidth="xs"
      >
        <Typography color="text.secondary" sx={{ fontSize: 13 }}>
          Your edits on this fuel day have not been saved. Discard them and switch to{' '}
          {pendingStepDate ? displayDate(pendingStepDate) : 'the selected date'}?
        </Typography>
      </FormDialog>
    </>
  )
}
