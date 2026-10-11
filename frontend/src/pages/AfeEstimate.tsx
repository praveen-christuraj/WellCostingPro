import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link as RouterLink, useNavigate, useParams } from 'react-router-dom'
import { AddRounded, ArrowBackRounded, DeleteOutlineRounded, EditOutlined, PrintOutlined, SaveOutlined, TableRowsOutlined, UndoRounded } from '@mui/icons-material'
import { Alert, Box, Button, CircularProgress, Paper, Table, TableBody, TableCell, TableHead, TableRow, Tooltip, Typography } from '@mui/material'
import type { ColDef } from 'ag-grid-community'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { AfePrintSheet } from '../components/afe/AfePrintSheet'
import { BreakdownDialog } from '../components/afe/BreakdownDialog'
import { BulkEstimateDialog, type BulkResult } from '../components/afe/BulkEstimateDialog'
import { ConsumableLineDialog } from '../components/afe/ConsumableLineDialog'
import { ErrorDetails, StatusDialog, StatusTag } from '../components/afe/AfeShared'
import { ServiceLineDialog } from '../components/afe/ServiceLineDialog'
import { TangibleLineDialog } from '../components/afe/TangibleLineDialog'
import { useAuth } from '../context/AuthContext'
import { ApiError, api, body } from '../lib/api'
import {
  STATUS_ACTIONS, amountText, consumableProblems, daysText, estimateToInput, nextActions, serviceProblems, stableJson, tangibleProblems, toNumber, totalsText,
  type Afe, type AfeComponent, type AfeEstimate, type AfeReference, type AfeStatusAction, type ConsumableLineInput, type ConsumableLineOut,
  type EstimateInput, type ServiceLineInput, type ServiceLineOut, type TangibleLineInput, type TangibleLineOut, type WellScope,
} from '../lib/afe'

type LineKind = 'service' | 'consumable' | 'tangible'
type Editor = { kind: LineKind; key: string | null } | null

// Flattened rows for the grids. Fields are top-level so search, filters and export work on them.
type ServiceRow = {
  key: string; service: string; basis: string; scope: string; currency: string; basis_detail: string
  amount: number | null; amount_text: string; status: string; warnings: number; problems: string[]
  line: ServiceLineInput; out: ServiceLineOut | null
}
type ConsumableRow = {
  key: string; category: string; item: string; scope: string; quantity: string; rate: string; currency: string
  amount: number | null; amount_text: string; status: string; warnings: number; problems: string[]
  line: ConsumableLineInput; out: ConsumableLineOut | null
}
type TangibleRow = {
  key: string; code: string; name: string; manufacturer: string; uom: string; quantity: string; rate: string; currency: string
  amount: number | null; amount_text: string; status: string; warnings: number; problems: string[]
  line: TangibleLineInput; out: TangibleLineOut | null
}

function sectionLabel(scope: WellScope, sectionId: string | null): string {
  if (!sectionId) return 'All sections'
  const section = scope.sections.find(item => item.hole_section_id === sectionId)
  return section ? `${section.section_code} · ${section.section_name}` : 'Not in well plan'
}
function phaseLabel(scope: WellScope, sectionId: string | null, phaseId: string | null): string {
  if (!sectionId || !phaseId) return ''
  const phase = scope.sections.find(item => item.hole_section_id === sectionId)?.phases.find(item => item.phase_id === phaseId)
  return phase ? `${phase.phase_code} · ${phase.phase_name}` : 'Not in well plan'
}

function statusFor(problems: string[], out: unknown, warnings: number): string {
  if (problems.length) return 'Incomplete'
  if (!out) return 'Pricing…'
  return warnings > 0 ? 'Priced · review' : 'Priced'
}

function RowButtons({ canEdit, onEdit, onDelete, onBreakdown, disabledHint }: {
  canEdit: boolean
  onEdit: () => void
  onDelete: () => void
  onBreakdown: () => void
  disabledHint?: string
}) {
  return <Box display="flex" alignItems="center" height="100%" gap={.2}>
    <Button size="small" onClick={onBreakdown}>Breakdown</Button>
    {canEdit && <Button size="small" startIcon={<EditOutlined sx={{ fontSize: 15 }}/>} onClick={onEdit}>Edit</Button>}
    {canEdit && <Tooltip title={disabledHint ?? 'Remove this line from the estimate'}><span>
      <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 15 }}/>} onClick={onDelete}>Delete</Button>
    </span></Tooltip>}
  </Box>
}

function Card({ title, subtitle, count, actions, children }: { title: string; subtitle: string; count: number; actions: ReactNode; children: ReactNode }) {
  return <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2 }, mb: 2, borderRadius: 2 }}>
    <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mb={1.5}>
      <Box>
        <Typography fontWeight={800} fontSize={15}>{title} <Typography component="span" color="text.secondary" fontSize={13} fontWeight={600}>({count})</Typography></Typography>
        <Typography color="text.secondary" fontSize={12} mt={.3}>{subtitle}</Typography>
      </Box>
      <Box display="flex" gap={1} flexWrap="wrap">{actions}</Box>
    </Box>
    {children}
  </Paper>
}

export default function AfeEstimate() {
  const { afeId = '' } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()

  const [afe, setAfe] = useState<Afe | null>(null)
  const [saved, setSaved] = useState<AfeEstimate | null>(null)
  const [reference, setReference] = useState<AfeReference | null>(null)
  const [inputs, setInputs] = useState<EstimateInput>({ services: [], consumables: [], tangibles: [] })
  const [preview, setPreview] = useState<AfeEstimate | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [previewError, setPreviewError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [editor, setEditor] = useState<Editor>(null)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [breakdown, setBreakdown] = useState<{ title: string; currency: string; components: AfeComponent[]; warnings: string[] } | null>(null)
  const [statusTarget, setStatusTarget] = useState<AfeStatusAction | null>(null)
  const [leaveOpen, setLeaveOpen] = useState(false)
  const [discardOpen, setDiscardOpen] = useState(false)
  const [printing, setPrinting] = useState(false)
  const [selected, setSelected] = useState<Record<LineKind, string[]>>({ service: [], consumable: [], tangible: [] })
  const [bulkDelete, setBulkDelete] = useState<LineKind | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [estimate, refData] = await Promise.all([
        api<AfeEstimate>(`/afe/afes/${afeId}/estimate`),
        api<AfeReference>('/afe/reference'),
      ])
      setSaved(estimate)
      setAfe(estimate.afe)
      setReference(refData)
      setInputs(estimateToInput(estimate))
      setPreview(null)
      setPreviewError(null)
      setSaveError(null)
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'The AFE estimate could not be loaded')
    } finally {
      setLoading(false)
    }
  }, [afeId])

  useEffect(() => { void load() }, [load])

  const editable = Boolean(afe && afe.status === 'draft' && can('afe:estimate'))
  const canPrint = can('afe:export')

  // Preview only valid lines, so one incomplete row never blocks the numbers for the rest.
  const validInputs = useMemo<EstimateInput>(() => ({
    services: inputs.services.filter(line => serviceProblems(line).length === 0),
    consumables: inputs.consumables.filter(line => consumableProblems(line).length === 0),
    tangibles: inputs.tangibles.filter(line => tangibleProblems(line).length === 0),
  }), [inputs])
  const previewSignature = useMemo(() => stableJson(validInputs), [validInputs])
  const savedSignature = useMemo(() => (saved ? stableJson(estimateToInput(saved)) : ''), [saved])
  const dirty = Boolean(saved) && stableJson(inputs) !== savedSignature
  const incompleteCount = [
    ...inputs.services.filter(line => serviceProblems(line).length > 0),
    ...inputs.consumables.filter(line => consumableProblems(line).length > 0),
    ...inputs.tangibles.filter(line => tangibleProblems(line).length > 0),
  ].length

  // Debounced preview. The effect re-runs only when the valid payload actually changes.
  useEffect(() => {
    if (!afe || !editable || loading) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setPreviewing(true)
      try {
        const result = await api<AfeEstimate>(`/afe/afes/${afe.id}/estimate/preview`, {
          method: 'POST', body: body(validInputs), signal: controller.signal,
        })
        setPreview(result)
        setPreviewError(null)
      } catch (caught) {
        if (controller.signal.aborted) return
        setPreview(null)
        setPreviewError(caught)
      } finally {
        if (!controller.signal.aborted) setPreviewing(false)
      }
    }, 450)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewSignature, editable, afe?.id, loading])

  // Warn before the browser closes or reloads the page with unsaved changes.
  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const shown: AfeEstimate | null = editable && preview ? preview : saved
  const showingPreview = Boolean(editable && preview && shown === preview)

  const serviceRows = useMemo<ServiceRow[]>(() => {
    if (!reference || !saved) return []
    return inputs.services.map(line => {
      const problems = serviceProblems(line)
      const out = shown?.services.find(item => item.client_key === line.client_key) ?? null
      const service = reference.services.find(item => item.id === line.service_id)
      const warnings = out?.warnings.length ?? 0
      const basisDetail = line.charging_basis === 'Day Rate'
        ? `${line.rates.length} unit rate${line.rates.length === 1 ? '' : 's'}${line.charges.length ? ` · ${line.charges.length} day entr${line.charges.length === 1 ? 'y' : 'ies'}` : ''}`
        : line.charging_basis === 'Per Service Rate' ? amountText(line.service_amount, line.currency)
          : `${line.section_rates.filter(rate => toNumber(rate.amount) > 0).length} section rate(s)`
      return {
        key: line.client_key,
        service: service ? `${service.service_code} · ${service.service_name}` : 'Service removed from master data',
        basis: line.charging_basis,
        basis_detail: basisDetail,
        scope: line.charging_basis === 'Per Section Rate' ? 'Per section' : [sectionLabel(saved.well, line.hole_section_id), phaseLabel(saved.well, line.hole_section_id, line.phase_id)].filter(Boolean).join(' · '),
        currency: line.currency,
        amount: out ? toNumber(out.amount) : null,
        amount_text: out ? amountText(out.amount, line.currency) : problems.length ? 'Incomplete' : 'Pricing…',
        status: statusFor(problems, out, warnings),
        warnings,
        problems,
        line,
        out,
      }
    })
  }, [inputs.services, shown, reference, saved])

  const consumableRows = useMemo<ConsumableRow[]>(() => {
    if (!reference || !saved) return []
    return inputs.consumables.map(line => {
      const problems = consumableProblems(line)
      const out = shown?.consumables.find(item => item.client_key === line.client_key) ?? null
      const bit = reference.drill_bits.find(item => item.id === line.drill_bit_id)
      const warnings = out?.warnings.length ?? 0
      return {
        key: line.client_key,
        category: line.category,
        item: line.category === 'Drill Bits' ? (bit ? `${bit.bit_code} · ${bit.bit_name}` : 'Select a drill bit') : 'Lump sum estimate',
        scope: [sectionLabel(saved.well, line.hole_section_id), phaseLabel(saved.well, line.hole_section_id, line.phase_id)].filter(Boolean).join(' · '),
        quantity: line.category === 'Drill Bits' ? line.quantity : '—',
        rate: out?.effective_rate ? amountText(out.effective_rate) : line.category === 'Drill Bits' ? 'Master rate' : '—',
        currency: line.category === 'Drill Bits' ? (bit?.currency ?? line.currency) : line.currency,
        amount: out ? toNumber(out.amount) : null,
        amount_text: out ? amountText(out.amount, out.currency) : problems.length ? 'Incomplete' : 'Pricing…',
        status: statusFor(problems, out, warnings),
        warnings,
        problems,
        line,
        out,
      }
    })
  }, [inputs.consumables, shown, reference, saved])

  const tangibleRows = useMemo<TangibleRow[]>(() => {
    if (!reference) return []
    return inputs.tangibles.map(line => {
      const problems = tangibleProblems(line)
      const out = shown?.tangibles.find(item => item.client_key === line.client_key) ?? null
      const item = reference.tangibles.find(entry => entry.id === line.tangible_id)
      const warnings = out?.warnings.length ?? 0
      return {
        key: line.client_key,
        code: item ? item.tangible_code : '—',
        name: item ? item.tangible_name : 'Tangible removed from master data',
        manufacturer: item?.manufacturer_name ?? '',
        uom: item?.uom ?? '',
        quantity: line.quantity,
        rate: out ? `${amountText(out.effective_rate)}${out.override_rate ? ' (override)' : ''}` : line.override_rate ? `${line.override_rate} (override)` : 'Master rate',
        currency: out?.currency ?? item?.currency ?? '',
        amount: out ? toNumber(out.amount) : null,
        amount_text: out ? amountText(out.amount, out.currency) : problems.length ? 'Incomplete' : 'Pricing…',
        status: statusFor(problems, out, warnings),
        warnings,
        problems,
        line,
        out,
      }
    })
  }, [inputs.tangibles, shown, reference])

  // Grid columns read the editable state through props captured here; handlers only use stable setters.
  const openBreakdown = useCallback((title: string, currency: string, out: { components: AfeComponent[]; warnings: string[] } | null) => {
    setBreakdown({ title, currency, components: out?.components ?? [], warnings: out?.warnings ?? [] })
  }, [])

  const removeLines = (kind: LineKind, keys: string[]) => {
    const drop = new Set(keys)
    setInputs(current => ({
      ...current,
      services: kind === 'service' ? current.services.filter(line => !drop.has(line.client_key)) : current.services,
      consumables: kind === 'consumable' ? current.consumables.filter(line => !drop.has(line.client_key)) : current.consumables,
      tangibles: kind === 'tangible' ? current.tangibles.filter(line => !drop.has(line.client_key)) : current.tangibles,
    }))
    setSelected(current => ({ ...current, [kind]: [] }))
  }

  const upsertService = (line: ServiceLineInput) => setInputs(current => ({
    ...current,
    services: current.services.some(item => item.client_key === line.client_key)
      ? current.services.map(item => (item.client_key === line.client_key ? line : item))
      : [...current.services, line],
  }))
  const upsertConsumable = (line: ConsumableLineInput) => setInputs(current => ({
    ...current,
    consumables: current.consumables.some(item => item.client_key === line.client_key)
      ? current.consumables.map(item => (item.client_key === line.client_key ? line : item))
      : [...current.consumables, line],
  }))
  const upsertTangible = (line: TangibleLineInput) => setInputs(current => ({
    ...current,
    tangibles: current.tangibles.some(item => item.client_key === line.client_key)
      ? current.tangibles.map(item => (item.client_key === line.client_key ? line : item))
      : [...current.tangibles, line],
  }))

  const applyBulk = (result: BulkResult) => {
    setInputs(current => ({
      ...current,
      services: [...current.services, ...result.services],
      consumables: [...current.consumables, ...result.consumables],
    }))
    setBulkOpen(false)
    setNotice(`${result.consumables.length + result.services.length} line${result.consumables.length + result.services.length === 1 ? '' : 's'} added from the bulk estimate. Review them, then save.`)
  }

  const save = async () => {
    if (!afe) return
    if (incompleteCount) {
      setSaveError(new ApiError(`Fix ${incompleteCount} incomplete line${incompleteCount === 1 ? '' : 's'} before saving.`, 422, []))
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const result = await api<AfeEstimate>(`/afe/afes/${afe.id}/estimate`, { method: 'PUT', body: body(inputs) })
      setSaved(result)
      setAfe(result.afe)
      setInputs(estimateToInput(result))
      setPreview(null)
      setNotice(`Estimate saved for ${result.afe.afe_code}. Total ${totalsText(result.summary.totals_by_currency)}.`)
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSaving(false)
    }
  }

  const discardChanges = () => {
    if (!saved) return
    setInputs(estimateToInput(saved))
    setPreview(null)
    setSaveError(null)
    setPreviewError(null)
    setDiscardOpen(false)
    setNotice('Unsaved changes were discarded.')
  }

  const refreshAfter = async (message: string) => {
    setNotice(message)
    await load()
  }

  const print = async () => {
    if (!afe) return
    setPrinting(true)
    try {
      await api(`/afe/afes/${afe.id}/print`, { method: 'POST' })
      window.setTimeout(() => {
        window.print()
        setPrinting(false)
      }, 60)
    } catch (caught) {
      setPrinting(false)
      setSaveError(caught)
    }
  }

  const goBack = () => {
    if (dirty) setLeaveOpen(true)
    else navigate('/afe/register?tab=estimation')
  }

  const estimateReady = Boolean(saved?.persisted) && toNumber(saved?.summary.total) > 0

  const serviceColumns = useMemo<ColDef<ServiceRow>[]>(() => [
    { headerName: 'SERVICE', field: 'service', minWidth: 230, flex: 1.4 },
    { headerName: 'BASIS', field: 'basis', minWidth: 150, flex: .9, valueFormatter: params => params.data ? `${params.data.basis} · ${params.data.basis_detail}` : '' },
    { headerName: 'SCOPE', field: 'scope', minWidth: 190, flex: 1.1 },
    { headerName: 'CURRENCY', field: 'currency', minWidth: 105, maxWidth: 120 },
    { headerName: 'AMOUNT', field: 'amount', minWidth: 150, flex: .8, valueFormatter: params => params.data ? params.data.amount_text : '' },
    { headerName: 'STATUS', field: 'status', minWidth: 130, maxWidth: 160, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={value === 'Incomplete' ? 'warning' : value.startsWith('Priced') ? 'success' : 'neutral'}>{value}</Tag></Box> },
    {
      headerName: 'ACTIONS', width: 270, minWidth: 270, maxWidth: 270, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: ServiceRow }) => data && <RowButtons
        canEdit={editable}
        onBreakdown={() => openBreakdown(data.service, data.currency, data.out)}
        onEdit={() => setEditor({ kind: 'service', key: data.key })}
        onDelete={() => removeLines('service', [data.key])}
      />,
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [editable, openBreakdown])

  const consumableColumns = useMemo<ColDef<ConsumableRow>[]>(() => [
    { headerName: 'CATEGORY', field: 'category', minWidth: 140, maxWidth: 170 },
    { headerName: 'ITEM', field: 'item', minWidth: 210, flex: 1.2 },
    { headerName: 'SCOPE', field: 'scope', minWidth: 190, flex: 1.1 },
    { headerName: 'QUANTITY', field: 'quantity', minWidth: 110, maxWidth: 130 },
    { headerName: 'RATE', field: 'rate', minWidth: 140, flex: .7 },
    { headerName: 'CURRENCY', field: 'currency', minWidth: 105, maxWidth: 120 },
    { headerName: 'AMOUNT', field: 'amount', minWidth: 150, flex: .8, valueFormatter: params => params.data ? params.data.amount_text : '' },
    { headerName: 'STATUS', field: 'status', minWidth: 130, maxWidth: 160, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={value === 'Incomplete' ? 'warning' : value.startsWith('Priced') ? 'success' : 'neutral'}>{value}</Tag></Box> },
    {
      headerName: 'ACTIONS', width: 270, minWidth: 270, maxWidth: 270, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: ConsumableRow }) => data && <RowButtons
        canEdit={editable}
        onBreakdown={() => openBreakdown(`${data.category} · ${data.item}`, data.currency, data.out)}
        onEdit={() => setEditor({ kind: 'consumable', key: data.key })}
        onDelete={() => removeLines('consumable', [data.key])}
      />,
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [editable, openBreakdown])

  const tangibleColumns = useMemo<ColDef<TangibleRow>[]>(() => [
    { headerName: 'CODE', field: 'code', minWidth: 110, maxWidth: 140 },
    { headerName: 'TANGIBLE', field: 'name', minWidth: 220, flex: 1.2 },
    { headerName: 'MANUFACTURER', field: 'manufacturer', minWidth: 160, flex: .9 },
    { headerName: 'UOM', field: 'uom', minWidth: 80, maxWidth: 100 },
    { headerName: 'QUANTITY', field: 'quantity', minWidth: 110, maxWidth: 130 },
    { headerName: 'RATE', field: 'rate', minWidth: 170, flex: .8 },
    { headerName: 'CURRENCY', field: 'currency', minWidth: 105, maxWidth: 120 },
    { headerName: 'AMOUNT', field: 'amount', minWidth: 150, flex: .8, valueFormatter: params => params.data ? params.data.amount_text : '' },
    { headerName: 'STATUS', field: 'status', minWidth: 130, maxWidth: 160, cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={value === 'Incomplete' ? 'warning' : value.startsWith('Priced') ? 'success' : 'neutral'}>{value}</Tag></Box> },
    {
      headerName: 'ACTIONS', width: 270, minWidth: 270, maxWidth: 270, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data: TangibleRow }) => data && <RowButtons
        canEdit={editable}
        onBreakdown={() => openBreakdown(data.name, data.currency, data.out)}
        onEdit={() => setEditor({ kind: 'tangible', key: data.key })}
        onDelete={() => removeLines('tangible', [data.key])}
      />,
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [editable, openBreakdown])

  if (loading) return <Box py={10} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
  if (loadError || !afe || !saved || !reference) return <>
    <PageHeading eyebrow="AFE MANAGEMENT / COST ESTIMATE" title="AFE cost estimate" subtitle="The estimate could not be opened."/>
    <ErrorMessage message={loadError || 'This AFE is not available in this workspace.'}/>
    <Button component={RouterLink} to="/afe/register?tab=estimation" startIcon={<ArrowBackRounded/>} sx={{ mt: 2 }}>Back to AFE cost estimation</Button>
  </>

  const statusActions = nextActions(afe.status).filter(action => can(STATUS_ACTIONS[action].permission))
  const warningList = shown?.summary.warnings ?? []
  const wellSections = saved.well.sections
  const rollup = shown?.summary.by_section ?? []

  return <>
    <PageHeading
      eyebrow="AFE MANAGEMENT / COST ESTIMATE"
      title={`${afe.afe_code} · ${afe.afe_name}`}
      subtitle={`${afe.rig_code} · ${afe.well_code} ${afe.well_name} · ${afe.afe_type} AFE. Sections and phases come from the well plan.`}
      action={<Box display="flex" gap={1} flexWrap="wrap" justifyContent="flex-end">
        <Button variant="outlined" startIcon={<ArrowBackRounded/>} onClick={goBack}>AFE cost estimation</Button>
        {canPrint && <Tooltip title={dirty ? 'Save the estimate before printing.' : estimateReady ? 'Print the complete AFE' : 'Save an estimate before printing.'}><span>
          <Button variant="outlined" startIcon={<PrintOutlined/>} onClick={() => void print()} disabled={!estimateReady || dirty || printing}>{printing ? 'Preparing...' : 'Print AFE'}</Button>
        </span></Tooltip>}
        {editable && <Tooltip title={incompleteCount ? `Fix ${incompleteCount} incomplete line${incompleteCount === 1 ? '' : 's'} first.` : !dirty ? 'No changes to save.' : 'Save the estimate'}><span>
          <Button variant="contained" startIcon={<SaveOutlined/>} onClick={() => void save()} disabled={saving || !dirty || incompleteCount > 0}>{saving ? 'Saving...' : 'Save estimate'}</Button>
        </span></Tooltip>}
        {editable && dirty && <Button color="inherit" startIcon={<UndoRounded/>} onClick={() => setDiscardOpen(true)}>Discard changes</Button>}
        {statusActions.map(action => {
          const blocked = dirty || (action === 'submit' && !estimateReady)
          const reason = dirty ? 'Save or discard the estimate changes first.' : 'Save a cost estimate with a total above zero first.'
          return <Tooltip key={action} title={blocked ? reason : STATUS_ACTIONS[action].description}><span>
            <Button variant={action === 'approve' ? 'contained' : 'outlined'} color={action === 'reopen' ? 'warning' : 'primary'} disabled={blocked} onClick={() => setStatusTarget(action)}>{STATUS_ACTIONS[action].label}</Button>
          </span></Tooltip>
        })}
      </Box>}
    />

    <Box display="flex" alignItems="center" gap={1} flexWrap="wrap" mb={1.5}>
      <StatusTag status={afe.status}/>
      {!editable && afe.status !== 'draft' && <Tag tone="info">Read-only · {afe.status === 'approval' ? 'approved' : 'under review'}</Tag>}
      {editable && dirty && !previewing && <Tag tone="warning">Unsaved changes</Tag>}
      {editable && previewing && <Tag tone="info">Recalculating preview…</Tag>}
      {editable && !dirty && saved.persisted && <Tag tone="success">Saved {saved.saved_at ? new Date(saved.saved_at).toLocaleString() : ''}{saved.saved_by ? ` by ${saved.saved_by}` : ''}</Tag>}
      {!saved.persisted && <Tag>No estimate saved yet</Tag>}
      {showingPreview && <Typography fontSize={12} color="text.secondary">Totals below are a live preview. Save to keep them.</Typography>}
    </Box>

    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>{notice}</Alert>}
    {!editable && afe.status === 'draft' && !can('afe:estimate') && <Alert severity="info" sx={{ mb: 1.5 }}>You can view this estimate. Changing it requires the AFE estimate permission.</Alert>}
    {editable && incompleteCount > 0 && <Alert severity="warning" sx={{ mb: 1.5 }}>
      {incompleteCount} line{incompleteCount === 1 ? ' is' : 's are'} incomplete. Incomplete lines are left out of the preview and block saving. Use Edit on the flagged line to complete it.
    </Alert>}
    {previewError ? <ErrorDetails error={previewError} title="The preview could not be calculated. Fix these issues:"/> : null}
    {saveError ? <ErrorDetails error={saveError} title="The estimate was not saved. Fix these issues:"/> : null}
    {warningList.length > 0 && <Alert severity="warning" sx={{ mb: 1.5 }}>
      <Typography fontWeight={700} fontSize={13} mb={.4}>{warningList.length} estimate warning{warningList.length === 1 ? '' : 's'}</Typography>
      {warningList.slice(0, 6).map(warning => <Typography key={warning} fontSize={12.5}>• {warning}</Typography>)}
      {warningList.length > 6 && <Typography fontSize={12.5}>…and {warningList.length - 6} more. Open the line breakdown for details.</Typography>}
    </Alert>}

    {/* Well configuration: the only source of sections, phases, depths and planned days. */}
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2 }, mb: 2, borderRadius: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={2} flexWrap="wrap" mb={1.2}>
        <Box>
          <Typography fontWeight={800} fontSize={15}>Well configuration</Typography>
          <Typography color="text.secondary" fontSize={12} mt={.3}>{saved.well.well_code} · {saved.well.well_name} · {saved.well.well_location} · Block {saved.well.block}</Typography>
        </Box>
        <Box display="flex" gap={1} alignItems="center" flexWrap="wrap">
          <Tag tone={saved.well.config_status === 'configured' ? 'info' : 'warning'}>Plan {saved.well.config_status}</Tag>
          <Tag>{saved.well.status}</Tag>
          <Typography fontSize={12} color="text.secondary">Planned {daysText(saved.well.total_days)}{saved.well.total_depth ? ` · ${Number(saved.well.total_depth).toLocaleString()} ${saved.well.depth_unit}` : ''}</Typography>
          <Button component={RouterLink} to="/rig-well/wells" size="small">Edit plan</Button>
        </Box>
      </Box>
      {wellSections.length === 0
        ? <Alert severity="warning">This well has no sections yet. Save its plan in Rig & Well Management before estimating.</Alert>
        : <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Section</TableCell>
                <TableCell>Depth</TableCell>
                <TableCell align="right">Planned days</TableCell>
                <TableCell>Phases (planned days)</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {wellSections.map(section => <TableRow key={section.hole_section_id}>
                <TableCell><Typography fontSize={13} fontWeight={700}>{section.section_code} · {section.section_name}</Typography></TableCell>
                <TableCell>{section.from_depth} → {section.to_depth}</TableCell>
                <TableCell align="right">{daysText(section.total_days)}</TableCell>
                <TableCell>{section.phases.length ? section.phases.map(phase => `${phase.phase_name} (${daysText(phase.days)})`).join(' · ') : 'No phases'}</TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        </Box>}
    </Paper>

    {/* Totals strip */}
    <Box display="grid" gap={1.5} mb={2} sx={{ gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, 1fr)' } }}>
      {[
        { label: 'Services', value: shown?.summary.services_total ?? '0' },
        { label: 'Consumables', value: shown?.summary.consumables_total ?? '0' },
        { label: 'Tangibles', value: shown?.summary.tangibles_total ?? '0' },
      ].map(item => <Paper key={item.label} variant="outlined" sx={{ p: 1.8, borderRadius: 2 }}>
        <Typography fontSize={11} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.7}>{item.label}</Typography>
        <Typography fontSize={18} fontWeight={800} mt={.4}>{shown?.summary.totals_by_currency.length ? amountText(item.value) : '—'}</Typography>
      </Paper>)}
      <Paper variant="outlined" sx={{ p: 1.8, borderRadius: 2, borderColor: 'primary.main', borderWidth: 1.5 }}>
        <Typography fontSize={11} fontWeight={800} color="primary.main" textTransform="uppercase" letterSpacing={.7}>Total estimate</Typography>
        <Typography fontSize={18} fontWeight={800} mt={.4}>{totalsText(shown?.summary.totals_by_currency ?? [])}</Typography>
        <Typography fontSize={11.5} color="text.secondary">{showingPreview ? 'Live preview' : 'Saved estimate'}</Typography>
      </Paper>
    </Box>

    {/* By-section rollup. Daily-rate lines are split per section, never shown well-wide. */}
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2 }, mb: 2, borderRadius: 2 }}>
      <Typography fontWeight={800} fontSize={15}>By hole section and phase</Typography>
      <Typography color="text.secondary" fontSize={12} mt={.3} mb={1.2}>Well-wide day rates are split by each section’s planned days. Lines not tied to a section appear under Well-level.</Typography>
      {rollup.length === 0
        ? <Typography fontSize={13} color="text.secondary">Add lines to see the section split.</Typography>
        : <Box sx={{ overflowX: 'auto' }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Section / phase</TableCell>
                <TableCell align="right">Planned days</TableCell>
                <TableCell align="right">Services</TableCell>
                <TableCell align="right">Consumables</TableCell>
                <TableCell align="right">Tangibles</TableCell>
                <TableCell align="right">Total</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rollup.map(row => <TableRow key={`${row.hole_section_id ?? 'well'}-${row.label}`}>
                <TableCell>{row.label}</TableCell>
                <TableCell align="right">{daysText(row.planned_days)}</TableCell>
                <TableCell align="right">{amountText(row.services)}</TableCell>
                <TableCell align="right">{amountText(row.consumables)}</TableCell>
                <TableCell align="right">{amountText(row.tangibles)}</TableCell>
                <TableCell align="right"><strong>{amountText(row.total)}</strong></TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        </Box>}
    </Paper>

    <Card
      title="Services"
      subtitle="Day-rate, per-service and per-section charges from Master Data. Well-wide day rates are split by planned days."
      count={serviceRows.length}
      actions={<>
        {editable && selected.service.length > 0 && <Button color="error" variant="outlined" size="small" onClick={() => setBulkDelete('service')}>Delete {selected.service.length} selected</Button>}
        {editable && <Button variant="contained" size="small" startIcon={<AddRounded/>} onClick={() => setEditor({ kind: 'service', key: null })}>Add service</Button>}
      </>}
    >
      <DataTable
        rows={serviceRows}
        columns={serviceColumns}
        searchPlaceholder="Search services by code, name, basis or section..."
        exportName={`afe-${afe.afe_code}-services`}
        canExport={can('afe:export')}
        selectable={editable}
        onSelectionChange={rows => setSelected(current => ({ ...current, service: rows.map(row => row.key) }))}
        onExport={async (format, recordCount) => {
          await api('/afe/export-audit', { method: 'POST', body: body({ module: 'estimates', format, record_count: recordCount, include_deleted: false }) })
        }}
      />
    </Card>

    <Card
      title="Consumables"
      subtitle="Mud chemicals, cement additives and fuel are estimated per section as lump sums. Drill bits are priced per bit."
      count={consumableRows.length}
      actions={<>
        {editable && selected.consumable.length > 0 && <Button color="error" variant="outlined" size="small" onClick={() => setBulkDelete('consumable')}>Delete {selected.consumable.length} selected</Button>}
        {editable && <Button variant="outlined" size="small" startIcon={<TableRowsOutlined/>} onClick={() => setBulkOpen(true)}>Bulk by section</Button>}
        {editable && <Button variant="contained" size="small" startIcon={<AddRounded/>} onClick={() => setEditor({ kind: 'consumable', key: null })}>Add consumable</Button>}
      </>}
    >
      <DataTable
        rows={consumableRows}
        columns={consumableColumns}
        searchPlaceholder="Search consumables by category, drill bit, section or status..."
        exportName={`afe-${afe.afe_code}-consumables`}
        canExport={can('afe:export')}
        selectable={editable}
        onSelectionChange={rows => setSelected(current => ({ ...current, consumable: rows.map(row => row.key) }))}
        onExport={async (format, recordCount) => {
          await api('/afe/export-audit', { method: 'POST', body: body({ module: 'estimates', format, record_count: recordCount, include_deleted: false }) })
        }}
      />
    </Card>

    <Card
      title="Tangibles"
      subtitle="Items from Master Data at their captured rate. Enter an override rate only when the quoted price differs."
      count={tangibleRows.length}
      actions={<>
        {editable && selected.tangible.length > 0 && <Button color="error" variant="outlined" size="small" onClick={() => setBulkDelete('tangible')}>Delete {selected.tangible.length} selected</Button>}
        {editable && <Button variant="contained" size="small" startIcon={<AddRounded/>} onClick={() => setEditor({ kind: 'tangible', key: null })}>Add tangible</Button>}
      </>}
    >
      <DataTable
        rows={tangibleRows}
        columns={tangibleColumns}
        searchPlaceholder="Search tangibles by code, name, manufacturer or description..."
        exportName={`afe-${afe.afe_code}-tangibles`}
        canExport={can('afe:export')}
        selectable={editable}
        onSelectionChange={rows => setSelected(current => ({ ...current, tangible: rows.map(row => row.key) }))}
        onExport={async (format, recordCount) => {
          await api('/afe/export-audit', { method: 'POST', body: body({ module: 'estimates', format, record_count: recordCount, include_deleted: false }) })
        }}
      />
    </Card>

    {/* Editors. Each returns a draft line; nothing is saved until the estimate is saved. */}
    {editor?.kind === 'service' && <ServiceLineDialog
      open
      initial={editor.key ? inputs.services.find(line => line.client_key === editor.key) ?? null : null}
      scope={saved.well}
      reference={reference}
      onClose={() => setEditor(null)}
      onSave={line => { upsertService(line); setEditor(null) }}
    />}
    {editor?.kind === 'consumable' && <ConsumableLineDialog
      open
      initial={editor.key ? inputs.consumables.find(line => line.client_key === editor.key) ?? null : null}
      scope={saved.well}
      reference={reference}
      onClose={() => setEditor(null)}
      onSave={line => { upsertConsumable(line); setEditor(null) }}
    />}
    {editor?.kind === 'tangible' && <TangibleLineDialog
      open
      initial={editor.key ? inputs.tangibles.find(line => line.client_key === editor.key) ?? null : null}
      reference={reference}
      onClose={() => setEditor(null)}
      onSave={line => { upsertTangible(line); setEditor(null) }}
    />}
    <BulkEstimateDialog open={bulkOpen} scope={saved.well} reference={reference} onClose={() => setBulkOpen(false)} onApply={applyBulk}/>

    <BreakdownDialog
      open={Boolean(breakdown)}
      title={breakdown?.title ?? ''}
      currency={breakdown?.currency ?? ''}
      components={breakdown?.components ?? []}
      warnings={breakdown?.warnings ?? []}
      onClose={() => setBreakdown(null)}
    />

    <StatusDialog
      afe={statusTarget ? afe : null}
      action={statusTarget}
      onClose={() => setStatusTarget(null)}
      onDone={(updated, action) => {
        setStatusTarget(null)
        void refreshAfter(`${updated.afe_code} is now ${updated.status}. ${STATUS_ACTIONS[action].label} was recorded in the audit trail.`)
      }}
    />

    <FormDialog
      open={bulkDelete !== null}
      title={`Delete ${bulkDelete ? selected[bulkDelete].length : 0} selected line${bulkDelete && selected[bulkDelete].length === 1 ? '' : 's'}?`}
      subtitle="The lines leave this estimate. Nothing is saved until you save the estimate."
      onClose={() => setBulkDelete(null)}
      onSubmit={() => { if (bulkDelete) removeLines(bulkDelete, selected[bulkDelete]); setBulkDelete(null) }}
      submitLabel="Remove lines"
    >
      <Typography fontSize={13}>You can still discard the change until you save.</Typography>
    </FormDialog>

    <FormDialog
      open={leaveOpen}
      title="Leave without saving?"
      subtitle="This estimate has changes that are not saved yet."
      onClose={() => setLeaveOpen(false)}
      onSubmit={() => navigate('/afe/register?tab=estimation')}
      submitLabel="Discard and leave"
    >
      <Typography fontSize={13}>Save the estimate to keep these changes, or discard them and leave.</Typography>
    </FormDialog>

    <FormDialog
      open={discardOpen}
      title="Discard unsaved changes?"
      subtitle="The estimate returns to the last saved version."
      onClose={() => setDiscardOpen(false)}
      onSubmit={discardChanges}
      submitLabel="Discard changes"
    >
      <Typography fontSize={13}>Lines you added or edited since the last save will be lost.</Typography>
    </FormDialog>

    {/* Print sheet is hidden on screen and printed in full (all sections, all lines). */}
    {saved.persisted && <AfePrintSheet estimate={saved}/>}
  </>
}
