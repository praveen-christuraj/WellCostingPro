import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, Chip, CircularProgress,
  Divider, FormControlLabel, IconButton, MenuItem, Paper, Stack, Step, StepLabel, Stepper, TextField,
  Typography,
} from '@mui/material'
import {
  AddRounded, ArrowBackRounded, ArrowForwardRounded, CloseRounded, ContentCopyRounded, DeleteOutlineRounded,
  ExpandMoreRounded, FunctionsRounded, PlayArrowRounded, PublishOutlined, SaveOutlined, VisibilityOutlined,
} from '@mui/icons-material'
import { api, body, ApiError } from '../lib/api'
import { ErrorMessage, PageHeading, Tag, useUnsavedChangesGuard } from '../components/Common'
import {
  aggregateLabel, BUCKETS, emptyColumn, emptyDesign, EMPTY_RUN, keyFromLabel, OPERATORS, reportTypeLabel,
  visibilityLabel, type Aggregate, type Catalog, type CatalogDetail, type ColumnKind, type Lookups,
  type ReportColumn, type ReportCondition, type ReportDefinition, type ReportDesign, type ReportFilter,
  type ReportGrant, type ReportRun, type ReportRuntimeFilter,
} from '../lib/reportBuilder'

const STEPS = ['Data & dates', 'Columns', 'Layout', 'Filters & questions', 'Sharing', 'Preview & save']

const AGGREGATES: Aggregate[] = ['NONE', 'SUM', 'AVG', 'COUNT', 'COUNT_DISTINCT', 'MIN', 'MAX', 'PRODUCT', 'FIRST', 'LAST']
const TEXT_AGGREGATES: Aggregate[] = ['NONE', 'COUNT', 'COUNT_DISTINCT', 'FIRST', 'LAST']

type FieldOption = { value: string; label: string; group: string; dataType: string }

/** Encodes a catalogue field as one selectable value: DATA::column or RELATED::key::table::column. */
function fieldOptions(detail: CatalogDetail | null): FieldOption[] {
  if (!detail) return []
  const options: FieldOption[] = detail.columns.map(column => ({
    value: `DATA::::${column.column}`, label: column.label, group: `${detail.label} (this table)`, dataType: column.data_type,
  }))
  detail.relations.forEach(relation => relation.columns.forEach(column => options.push({
    value: `RELATED::${relation.key_column}::${relation.table}::${column.column}`,
    label: column.label, group: relation.label, dataType: column.data_type,
  })))
  return options
}

function decodeField(value: string): { source_kind: string; related_key_column: string; related_table: string; column_name: string } {
  const [kind, key, table, column] = value.split('::')
  return { source_kind: kind || 'DATA', related_key_column: key || '', related_table: table || '', column_name: column || '' }
}

function encodeField(source: { source_kind?: string; related_key_column?: string; related_table?: string; column_name?: string }): string {
  const kind = source.source_kind || 'DATA'
  return `${kind}::${source.related_key_column || ''}::${source.related_table || ''}::${source.column_name || ''}`
}

function payloadOf(design: ReportDesign): ReportDesign {
  return {
    ...design,
    name: design.name.trim(),
    description: design.description.trim(),
    columns: design.columns.map((column, index) => ({
      ...column,
      key: column.key || `column_${index + 1}`,
      label: column.label.trim() || column.column_name || `Column ${index + 1}`,
      conditions: column.conditions.map(condition => ({ ...condition })),
    })),
  }
}

export default function ReportDesigner() {
  const { reportId } = useParams()
  const isNew = !reportId || reportId === 'new'
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const previewRequested = params.get('preview') === '1'

  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [detail, setDetail] = useState<CatalogDetail | null>(null)
  const [lookups, setLookups] = useState<Lookups>({ users: [], roles: [] })
  const [design, setDesign] = useState<ReportDesign>(emptyDesign())
  const [record, setRecord] = useState<ReportDefinition | null>(null)
  const [baseline, setBaseline] = useState(JSON.stringify(emptyDesign()))
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const [run, setRun] = useState<ReportRun>(EMPTY_RUN)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [notice, setNotice] = useState('')

  const dirty = JSON.stringify(design) !== baseline

  const save = useCallback(async (publish = false): Promise<boolean> => {
    setSaving(true)
    setError('')
    setProblems([])
    try {
      const payload = payloadOf(design)
      if (!payload.name.trim()) { setProblems(['Give the report a name on the first step.']); setStep(0); return false }
      if (!payload.source_table) { setProblems(['Choose the table this report reads from.']); setStep(0); return false }
      if (!payload.columns.length) { setProblems(['Add at least one column on the Columns step.']); setStep(1); return false }
      const saved = isNew || !record
        ? await api<ReportDefinition>('/report-builder/definitions', { method: 'POST', body: body(payload), action: 'Saving the report' })
        : await api<ReportDefinition>(`/report-builder/definitions/${record.id}`, { method: 'PUT', body: body(payload), action: 'Saving the report' })
      let final = saved
      const shouldPublish = publish || record?.status === 'published'
      if (shouldPublish && saved.status !== 'published' && saved.can_publish) {
        setPublishing(true)
        final = await api<ReportDefinition>(`/report-builder/definitions/${saved.id}/publish`, {
          method: 'POST', body: body({ published: true }), action: 'Publishing the report',
        })
      }
      setRecord(final)
      setDesign(final.design)
      setBaseline(JSON.stringify(final.design))
      setNotice(publish
        ? `“${final.name}” is saved and published as version ${final.version}. It now appears in Custom Reports.`
        : `“${final.name}” is saved as version ${final.version}${final.status === 'published' ? ' and stays published' : ' as a draft'}.`)
      if (isNew) navigate(`/reports/builder/${final.id}`, { replace: true })
      return true
    } catch (caught) {
      const apiError = caught as ApiError
      setError(apiError.message || 'The report could not be saved')
      if (apiError.details?.length) setProblems(apiError.details)
      return false
    } finally {
      setSaving(false)
      setPublishing(false)
    }
  }, [design, isNew, navigate, record])

  const guard = useUnsavedChangesGuard({ when: dirty, onSave: () => save(false) })

  const loadDetail = useCallback(async (table: string) => {
    if (!table) { setDetail(null); return }
    try {
      setDetail(await api<CatalogDetail>(`/report-builder/catalog/${encodeURIComponent(table)}`))
    } catch {
      setDetail(null)
    }
  }, [])

  useEffect(() => {
    let live = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const [catalogue, lookup] = await Promise.all([
          api<Catalog>('/report-builder/catalog'),
          api<Lookups>('/report-builder/lookups'),
        ])
        if (!live) return
        setCatalog(catalogue)
        setLookups(lookup)
        if (!isNew && reportId) {
          const definition = await api<ReportDefinition>(`/report-builder/definitions/${reportId}`)
          if (!live) return
          setRecord(definition)
          setDesign(definition.design)
          setBaseline(JSON.stringify(definition.design))
          setStep(previewRequested ? 5 : 0)
          await loadDetail(definition.design.source_table)
        } else if (catalogue.tables.length) {
          const first = catalogue.tables.find(item => item.table === 'wells') ?? catalogue.tables[0]
          const start = { ...emptyDesign(), source_table: first.table, name: '' }
          setDesign(start)
          setBaseline(JSON.stringify(start))
          await loadDetail(first.table)
        }
      } catch (caught) {
        if (live) setError(caught instanceof Error ? caught.message : 'The designer could not be loaded')
      } finally {
        if (live) setLoading(false)
      }
    }
    void load()
    return () => { live = false }
  }, [isNew, reportId, loadDetail, previewRequested])

  const options = useMemo(() => fieldOptions(detail), [detail])
  const numericColumns = useMemo(
    () => design.columns.filter(column => column.data_type === 'number' || column.aggregate === 'COUNT' || column.aggregate === 'COUNT_DISTINCT'),
    [design.columns],
  )

  const update = (patch: Partial<ReportDesign>) => setDesign(current => ({ ...current, ...patch }))

  const changeSource = async (table: string) => {
    setDesign(current => ({
      ...current, source_table: table, date_column: '', columns: [], filters: [], runtime_filters: [],
      groupings: [], sorts: [], matrix_value_key: '',
    }))
    await loadDetail(table)
  }

  const updateColumn = (index: number, patch: Partial<ReportColumn>) => setDesign(current => ({
    ...current,
    columns: current.columns.map((column, position) => position === index ? { ...column, ...patch } : column),
  }))

  const addColumn = (kind: ColumnKind) => setDesign(current => {
    const index = current.columns.length
    const column = emptyColumn(index)
    const first = detail?.columns.find(item => item.data_type === (kind === 'CALCULATED' ? 'number' : 'text')) ?? detail?.columns[0]
    return {
      ...current,
      columns: [...current.columns, {
        ...column, kind,
        column_name: kind === 'CALCULATED' ? '' : (first?.column ?? ''),
        data_type: kind === 'CALCULATED' ? 'number' : (first?.data_type === 'boolean' ? 'text' : first?.data_type as ReportColumn['data_type'] ?? 'text'),
        label: kind === 'CALCULATED' ? '' : (first?.label ?? ''),
        aggregate: kind === 'CALCULATED' ? 'NONE' : column.aggregate,
      }],
    }
  })

  const removeColumn = (index: number) => setDesign(current => {
    const removed = current.columns[index]
    return {
      ...current,
      columns: current.columns.filter((_, position) => position !== index),
      groupings: current.groupings.filter(item => item.column_key !== removed.key),
      sorts: current.sorts.filter(item => item.column_key !== removed.key),
      matrix_value_key: current.matrix_value_key === removed.key ? '' : current.matrix_value_key,
    }
  })

  const moveColumn = (index: number, direction: -1 | 1) => setDesign(current => {
    const target = index + direction
    if (target < 0 || target >= current.columns.length) return current
    const columns = [...current.columns]
    const [moved] = columns.splice(index, 1)
    columns.splice(target, 0, moved)
    return { ...current, columns }
  })

  const validate = async () => {
    setProblems([])
    setError('')
    try {
      const result = await api<{ valid: boolean; problems: string[] }>('/report-builder/validate', {
        method: 'POST', body: body(payloadOf(design)),
      })
      if (result.valid) setNotice('The design is valid against this workspace’s tables.')
      else setProblems(result.problems)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The design could not be validated')
    }
  }

  const preview = async () => {
    setPreviewing(true)
    setError('')
    setProblems([])
    try {
      const result = await api<ReportRun>('/report-builder/preview', {
        method: 'POST', body: body({ design: payloadOf(design), params: {} }), action: 'Previewing the report',
      })
      setRun(result)
      setStep(5)
    } catch (caught) {
      const apiError = caught as ApiError
      setError(apiError.message)
      if (apiError.details?.length) setProblems(apiError.details)
    } finally {
      setPreviewing(false)
    }
  }

  if (loading) return <Box py={12} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box>

  const stepContent = [
    <DataStep key="data" design={design} catalog={catalog} detail={detail} update={update} changeSource={table => void changeSource(table)}/>,
    <ColumnsStep key="columns" design={design} options={options} updateColumn={updateColumn} addColumn={addColumn}
      removeColumn={removeColumn} moveColumn={moveColumn}/>,
    <LayoutStep key="layout" design={design} update={update} setDesign={setDesign} numericColumns={numericColumns}/>,
    <FiltersStep key="filters" design={design} options={options} setDesign={setDesign}/>,
    <SharingStep key="sharing" design={design} update={update} setDesign={setDesign} lookups={lookups}/>,
    <PreviewStep key="preview" design={design} run={run} previewing={previewing} onPreview={() => void preview()} record={record}/>,
  ][step]

  return <>
    <PageHeading
      eyebrow="REPORTS / REPORT BUILDER"
      title={record ? record.name : 'New report'}
      subtitle={record
        ? `Version ${record.version} · ${record.status === 'published' ? 'published' : 'draft'} · ${record.source_table}`
        : 'Six short steps: where the data comes from, what to show, how to arrange it, what to ask, who sees it, and a live preview before you save.'}
      action={<>
        <Button variant="outlined" startIcon={<ArrowBackRounded/>} onClick={() => navigate('/reports/builder')}>All reports</Button>
        <Button variant="outlined" startIcon={<VisibilityOutlined/>} onClick={() => void validate()}>Check design</Button>
        <Button variant="outlined" startIcon={<SaveOutlined/>} disabled={saving} onClick={() => void save(false)}>{saving ? 'Saving...' : 'Save draft'}</Button>
        <Button variant="contained" startIcon={<PublishOutlined/>} disabled={saving || publishing}
          onClick={() => void save(true)}>{publishing ? 'Publishing...' : record?.status === 'published' ? 'Save & keep published' : 'Save & publish'}</Button>
      </>}
    />
    <ErrorMessage message={error}/>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    {problems.length > 0 && <Alert severity="error" sx={{ mb: 2 }}>
      <Typography fontWeight={800} fontSize={12.5} sx={{ mb: .5 }}>This design needs attention</Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.2 }}>
        {problems.map(problem => <li key={problem}><Typography fontSize={12.5}>{problem}</Typography></li>)}
      </Box>
    </Alert>}

    <Stepper activeStep={step} alternativeLabel sx={{ mb: 3, '& .MuiStepLabel-label': { fontSize: 11.5, fontWeight: 700 } }}>
      {STEPS.map((label, index) => <Step key={label} completed={index < step}>
        <StepLabel onClick={() => setStep(index)} sx={{ cursor: 'pointer' }}>{label}</StepLabel>
      </Step>)}
    </Stepper>

    <Paper variant="outlined" sx={{ p: { xs: 2, md: 2.8 }, borderRadius: 2, minHeight: 320 }}>{stepContent}</Paper>

    <Box display="flex" justifyContent="space-between" gap={1} mt={2.5} flexWrap="wrap">
      <Button startIcon={<ArrowBackRounded/>} disabled={step === 0} onClick={() => setStep(value => Math.max(0, value - 1))}>Back</Button>
      <Box display="flex" gap={1}>
        {step === 5 && <Button variant="outlined" startIcon={<PlayArrowRounded/>} disabled={previewing} onClick={() => void preview()}>{previewing ? 'Running...' : 'Run preview again'}</Button>}
        {step < 5 && <Button variant="contained" endIcon={<ArrowForwardRounded/>} onClick={() => setStep(value => Math.min(5, value + 1))}>Next: {STEPS[step + 1]}</Button>}
      </Box>
    </Box>
    {guard}
  </>
}

// ---------------------------------------------------------------------------
// Step 1 — data and date basis
// ---------------------------------------------------------------------------

function DataStep({ design, catalog, detail, update, changeSource }: {
  design: ReportDesign
  catalog: Catalog | null
  detail: CatalogDetail | null
  update: (patch: Partial<ReportDesign>) => void
  changeSource: (table: string) => void
}) {
  const tables = catalog?.tables ?? []
  const grouped = (catalog?.groups ?? []).map(group => ({
    group: group.group,
    tables: group.tables.map(name => tables.find(item => item.table === name)).filter((item): item is NonNullable<typeof item> => Boolean(item)),
  }))
  const dateColumns = detail?.columns.filter(column => column.data_type === 'date') ?? []
  return <Stack spacing={2.4}>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>What is this report called?</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.6 }}>The name appears in Custom Reports once published. The description tells people what question it answers.</Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField label="Report name" required value={design.name} fullWidth inputProps={{ maxLength: 160 }}
          onChange={event => update({ name: event.target.value })} placeholder="e.g. Daily cost by well"/>
        <TextField label="Description" value={design.description} fullWidth inputProps={{ maxLength: 1000 }}
          onChange={event => update({ description: event.target.value })} placeholder="What the report shows and when to use it"/>
      </Stack>
    </Box>
    <Divider/>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>Which table does it read?</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.6 }}>
        Only this workspace's tables are listed. Related columns follow one declared link, so a report cannot reach another table by accident.
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField select label="Source table" value={design.source_table} sx={{ minWidth: 280 }} fullWidth
          onChange={event => { const next = event.target.value; if (next !== design.source_table) changeSource(next) }}
          helperText={detail ? `${detail.column_count} columns · ${detail.relation_count} related tables · ${detail.scope}` : 'Choose the table'}>
          {grouped.map(group => [
            <MenuItem key={`group-${group.group}`} disabled value={`__group_${group.group}`} sx={{ fontWeight: 800, fontSize: 10.5, letterSpacing: 1, textTransform: 'uppercase' }}>{group.group}</MenuItem>,
            ...group.tables.map(table => <MenuItem key={table.table} value={table.table}>{table.label} · {table.table}</MenuItem>),
          ])}
        </TextField>
        <TextField select label="Date basis" value={design.date_basis} fullWidth
          onChange={event => update({ date_basis: event.target.value as ReportDesign['date_basis'], date_column: event.target.value === 'COLUMN' ? (design.date_column || dateColumns[0]?.column || '') : '' })}
          helperText="Which date the “from / to” questions filter on.">
          <MenuItem value="NONE">No date filter</MenuItem>
          <MenuItem value="CREATED_AT">When the row was created</MenuItem>
          <MenuItem value="UPDATED_AT">When the row was last changed</MenuItem>
          <MenuItem value="COLUMN" disabled={dateColumns.length === 0}>A date column in this table</MenuItem>
        </TextField>
        {design.date_basis === 'COLUMN' && <TextField select label="Date column" value={design.date_column} fullWidth
          onChange={event => update({ date_column: event.target.value })}>
          {dateColumns.map(column => <MenuItem key={column.column} value={column.column}>{column.label}</MenuItem>)}
        </TextField>}
      </Stack>
    </Box>
    <Divider/>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>How should the rows be arranged?</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.6 }}>Detail rows list every record; grouped summarises them; a matrix cross-tabulates two of the columns.</Typography>
      <Stack direction="row" spacing={1.2} flexWrap="wrap">
        {(['TABULAR', 'MATRIX'] as const).map(type => <Paper key={type} variant="outlined" role="button" tabIndex={0}
          onClick={() => update({ report_type: type })}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') update({ report_type: type }) }}
          sx={{ p: 1.6, borderRadius: 2, cursor: 'pointer', minWidth: 190, flex: '1 1 200px',
            borderColor: design.report_type === type ? 'primary.main' : 'divider',
            bgcolor: design.report_type === type ? 'action.selected' : 'transparent' }}>
          <Typography fontWeight={800} fontSize={13}>{reportTypeLabel(type)}</Typography>
          <Typography color="text.secondary" fontSize={11.5} sx={{ mt: .3 }}>
            {type === 'TABULAR' ? 'Every matching record, optionally grouped and summarised.' : 'Two dimensions against one measure, with row and column totals.'}
          </Typography>
        </Paper>)}
      </Stack>
    </Box>
  </Stack>
}

// ---------------------------------------------------------------------------
// Step 2 — columns
// ---------------------------------------------------------------------------

function ColumnsStep({ design, options, updateColumn, addColumn, removeColumn, moveColumn }: {
  design: ReportDesign
  options: FieldOption[]
  updateColumn: (index: number, patch: Partial<ReportColumn>) => void
  addColumn: (kind: ColumnKind) => void
  removeColumn: (index: number) => void
  moveColumn: (index: number, direction: -1 | 1) => void
}) {
  const taken = design.columns.map(column => column.key)
  return <Stack spacing={2}>
    <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={2} flexWrap="wrap">
      <Box>
        <Typography variant="h6" sx={{ mb: .4 }}>What should appear on the report?</Typography>
        <Typography color="text.secondary" fontSize={12.5} sx={{ maxWidth: 720 }}>
          Add a column from this table, a column reached through a related table, or a calculated value. The order here is the order on screen.
        </Typography>
      </Box>
      <Box display="flex" gap={1} flexWrap="wrap">
        <Button size="small" variant="outlined" startIcon={<AddRounded/>} onClick={() => addColumn('DATA')}>From this table</Button>
        <Button size="small" variant="outlined" startIcon={<AddRounded/>} disabled={!options.some(option => option.value.startsWith('RELATED'))}
          onClick={() => addColumn('RELATED')}>From a related table</Button>
        <Button size="small" variant="outlined" startIcon={<FunctionsRounded/>} onClick={() => addColumn('CALCULATED')}>Calculated</Button>
      </Box>
    </Box>
    {design.columns.length === 0 && <Alert severity="info">No columns yet. Add at least one; the first step lets you change the table later.</Alert>}
    {design.columns.map((column, index) => <ColumnCard key={`${column.key}-${index}`} column={column} index={index}
      options={options} taken={taken} last={index === design.columns.length - 1}
      updateColumn={updateColumn} removeColumn={removeColumn} moveColumn={moveColumn}/>)}
  </Stack>
}

function ColumnCard({ column, index, options, taken, last, updateColumn, removeColumn, moveColumn }: {
  column: ReportColumn
  index: number
  options: FieldOption[]
  taken: string[]
  last: boolean
  updateColumn: (index: number, patch: Partial<ReportColumn>) => void
  removeColumn: (index: number) => void
  moveColumn: (index: number, direction: -1 | 1) => void
}) {
  const relatedKeys = Array.from(new Set(options.filter(option => option.value.startsWith('RELATED')).map(option => option.value.split('::')[1])))
  const visible = options.filter(option => column.kind === 'RELATED'
    ? option.value.startsWith('RELATED') && option.value.split('::')[1] === column.related_key_column
    : option.value.startsWith('DATA'))
  const numeric = column.data_type === 'number' || column.aggregate === 'COUNT' || column.aggregate === 'COUNT_DISTINCT'
  const aggregateOptions = column.data_type === 'number' ? AGGREGATES : TEXT_AGGREGATES

  return <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
    <Box display="flex" alignItems="center" gap={1} mb={1.6} flexWrap="wrap">
      <Chip size="small" label={`${index + 1}`} sx={{ fontWeight: 800 }}/>
      <Typography fontWeight={800} fontSize={13.5}>{column.label || column.formula || 'New column'}</Typography>
      <Tag tone={column.kind === 'CALCULATED' ? 'info' : column.kind === 'RELATED' ? 'warning' : 'neutral'}>
        {column.kind === 'CALCULATED' ? 'Calculated' : column.kind === 'RELATED' ? 'Related' : 'This table'}
      </Tag>
      {column.hidden && <Tag tone="neutral">Hidden</Tag>}
      <Box flex={1}/>
      <IconButton size="small" aria-label="Move column up" disabled={index === 0} onClick={() => moveColumn(index, -1)}><ArrowBackRounded sx={{ fontSize: 16, transform: 'rotate(90deg)' }}/></IconButton>
      <IconButton size="small" aria-label="Move column down" disabled={last} onClick={() => moveColumn(index, 1)}><ArrowForwardRounded sx={{ fontSize: 16, transform: 'rotate(90deg)' }}/></IconButton>
      <IconButton size="small" aria-label="Remove column" onClick={() => removeColumn(index)}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
    </Box>
    <Box sx={{ display: 'grid', gap: 1.6, gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' } }}>
      <TextField size="small" label="Heading" value={column.label} inputProps={{ maxLength: 160 }}
        onChange={event => updateColumn(index, { label: event.target.value })}
        helperText="What the reader sees on the column"/>
      <TextField size="small" select label="Kind" value={column.kind}
        onChange={event => {
          const kind = event.target.value as ColumnKind
          const first = options.find(option => (kind === 'RELATED' ? option.value.startsWith('RELATED') : option.value.startsWith('DATA')))
          updateColumn(index, kind === 'CALCULATED'
            ? { kind, column_name: '', related_table: '', related_key_column: '', data_type: 'number', formula: column.formula || '' }
            : { kind, ...decodeField(first?.value ?? 'DATA::::'), data_type: (first?.dataType as ReportColumn['data_type']) || 'text' })
        }}>
        <MenuItem value="DATA">A column in this table</MenuItem>
        <MenuItem value="RELATED">A column in a related table</MenuItem>
        <MenuItem value="CALCULATED">A calculated value</MenuItem>
      </TextField>
      {column.kind === 'RELATED' && <TextField size="small" select label="Through the link" value={column.related_key_column}
        onChange={event => updateColumn(index, { related_key_column: event.target.value, related_table: '', column_name: '' })}>
        {relatedKeys.map(key => <MenuItem key={key} value={key}>{options.find(option => option.value.startsWith(`RELATED::${key}::`))?.group || key}</MenuItem>)}
      </TextField>}
      {column.kind !== 'CALCULATED' && <TextField size="small" select label="Field" value={encodeField(column)}
        onChange={event => {
          const decoded = decodeField(event.target.value)
          const meta = options.find(option => option.value === event.target.value)
          updateColumn(index, {
            ...decoded,
            data_type: meta?.dataType === 'boolean' ? 'text' : (meta?.dataType as ReportColumn['data_type']) || column.data_type,
            label: column.label || meta?.label || '',
          })
        }}>
        {visible.map(option => <MenuItem key={option.value} value={option.value}>{option.label} · {option.dataType}</MenuItem>)}
      </TextField>}
      {column.kind === 'CALCULATED' && <TextField size="small" label="Result type" select value={column.data_type}
        onChange={event => updateColumn(index, { data_type: event.target.value as ReportColumn['data_type'] })}>
        <MenuItem value="number">Number</MenuItem>
        <MenuItem value="text">Text</MenuItem>
        <MenuItem value="date">Date</MenuItem>
      </TextField>}
      <TextField size="small" select label="Summary" value={column.aggregate}
        onChange={event => updateColumn(index, { aggregate: event.target.value as Aggregate, show_total: event.target.value !== 'NONE' ? column.show_total : false })}
        helperText={column.aggregate === 'NONE' ? 'One value per row' : aggregateLabel(column.aggregate)}>
        {aggregateOptions.map(aggregate => <MenuItem key={aggregate} value={aggregate}>{aggregateLabel(aggregate)}</MenuItem>)}
      </TextField>
      <TextField size="small" label="Decimals" type="number" value={column.decimals} inputProps={{ min: 0, max: 8 }}
        onChange={event => updateColumn(index, { decimals: Number(event.target.value) })} disabled={column.data_type !== 'number'}/>
      <TextField size="small" label="Prefix" value={column.prefix} inputProps={{ maxLength: 20 }}
        onChange={event => updateColumn(index, { prefix: event.target.value })} placeholder="$"/>
      <TextField size="small" label="Suffix" value={column.suffix} inputProps={{ maxLength: 20 }}
        onChange={event => updateColumn(index, { suffix: event.target.value })} placeholder="%"/>
      <Box display="flex" alignItems="center" gap={1.5} flexWrap="wrap">
        <FormControlLabel control={<Checkbox size="small" checked={column.show_total} disabled={!numeric}
          onChange={event => updateColumn(index, { show_total: event.target.checked })}/>} label={<Typography fontSize={12.5}>Show total</Typography>}/>
        <FormControlLabel control={<Checkbox size="small" checked={column.hidden}
          onChange={event => updateColumn(index, { hidden: event.target.checked })}/>} label={<Typography fontSize={12.5}>Hide on screen</Typography>}/>
      </Box>
    </Box>
    {column.kind === 'CALCULATED' && <FormulaEditor column={column} index={index} updateColumn={updateColumn}/>}
    {column.kind !== 'CALCULATED' && <ConditionEditor column={column} index={index} options={options}
      onChange={conditions => updateColumn(index, { conditions })}
      onLogic={logic => updateColumn(index, { condition_logic: logic })}/>}
    <Typography color="text.secondary" fontSize={11} sx={{ mt: 1 }}>
      Key: <Box component="code">{column.key}</Box>{taken.filter(key => key === column.key).length > 1 ? ' — duplicate key, rename the heading' : ''}
    </Typography>
  </Paper>
}

function FormulaEditor({ column, index, updateColumn }: {
  column: ReportColumn
  index: number
  updateColumn: (index: number, patch: Partial<ReportColumn>) => void
}) {
  const [help, setHelp] = useState<{ help: { signature: string; description: string }[]; operators: string[] } | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open || help) return
    void api<{ help: { signature: string; description: string }[]; operators: string[] }>('/report-builder/formula-help', { silent: true })
      .then(setHelp).catch(() => undefined)
  }, [open, help])
  return <Box sx={{ mt: 1.6 }}>
    <TextField fullWidth label="Formula" value={column.formula} inputProps={{ maxLength: 2000, style: { fontFamily: 'monospace' } }}
      onChange={event => updateColumn(index, { formula: event.target.value })}
      placeholder="ROUND([cost_total] / NULLIF([days], 0), 2)"
      helperText="Reference other columns by their key in square brackets. The value is computed for every row before any summary is applied."/>
    <Accordion expanded={open} onChange={(_, expanded) => setOpen(expanded)} disableGutters elevation={0} sx={{ mt: 1, border: '1px solid', borderColor: 'divider', borderRadius: 2, '&:before': { display: 'none' } }}>
      <AccordionSummary expandIcon={<ExpandMoreRounded/>}><Typography fontSize={12.5} fontWeight={700}>Functions and operators</Typography></AccordionSummary>
      <AccordionDetails>
        <Box sx={{ display: 'grid', gap: .8, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' } }}>
          {(help?.help ?? []).map(item => <Box key={item.signature}>
            <Typography fontFamily="monospace" fontSize={11.5} fontWeight={700}>{item.signature}</Typography>
            <Typography color="text.secondary" fontSize={11}>{item.description}</Typography>
          </Box>)}
        </Box>
        {help && <Typography color="text.secondary" fontSize={11} sx={{ mt: 1.4 }}>Operators: {help.operators.join(' · ')}. A blank stays blank through arithmetic, so a missing reading never becomes zero; wrap a risky division in IFERROR.</Typography>}
      </AccordionDetails>
    </Accordion>
  </Box>
}

function ConditionEditor({ column, index, options, onChange, onLogic }: {
  column: ReportColumn
  index: number
  options: FieldOption[]
  onChange: (conditions: ReportCondition[]) => void
  onLogic: (logic: 'AND' | 'OR') => void
}) {
  const [open, setOpen] = useState(column.conditions.length > 0)
  const add = () => {
    setOpen(true)
    onChange([...column.conditions, { source_kind: 'DATA', column_name: '', related_table: '', related_key_column: '', operator: 'eq', value: '', value2: '' }])
  }
  return <Box sx={{ mt: 1.4 }}>
    <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
      <Button size="small" variant="text" onClick={() => setOpen(value => !value)}>{open ? 'Hide' : 'Compare only some rows'}</Button>
      <Typography color="text.secondary" fontSize={11.5}>
        {column.conditions.length
          ? `Only rows that ${column.condition_logic === 'AND' ? 'match every rule' : 'match any rule'} contribute to this column; the rest show blank.`
          : 'Optional. Turn this column into a comparison measure, for example “approved AFEs” beside “all AFEs”.'}
      </Typography>
    </Box>
    {open && <Box sx={{ mt: 1.2, pl: { md: 1 }, borderLeft: { md: '2px solid' }, borderColor: { md: 'divider' } }}>
      {column.conditions.length > 1 && <TextField select size="small" label="Combine rules" value={column.condition_logic}
        onChange={event => onLogic(event.target.value as 'AND' | 'OR')} sx={{ mb: 1.2, minWidth: 180 }}>
        <MenuItem value="AND">All rules must match</MenuItem>
        <MenuItem value="OR">Any rule may match</MenuItem>
      </TextField>}
      {column.conditions.map((condition, position) => {
        const operator = OPERATORS.find(item => item.value === condition.operator)
        return <Box key={position} sx={{ display: 'grid', gap: 1.2, gridTemplateColumns: { xs: '1fr', md: '2fr 1.2fr 1.4fr 1.4fr auto' }, alignItems: 'center', mb: 1.2 }}>
          <TextField size="small" select label="Field" value={encodeField(condition)}
            onChange={event => {
              const next = [...column.conditions]
              next[position] = { ...condition, ...decodeField(event.target.value) }
              onChange(next)
            }}>
            {options.map(option => <MenuItem key={option.value} value={option.value}>{option.group} · {option.label}</MenuItem>)}
          </TextField>
          <TextField size="small" select label="Rule" value={condition.operator}
            onChange={event => { const next = [...column.conditions]; next[position] = { ...condition, operator: event.target.value }; onChange(next) }}>
            {OPERATORS.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Value" value={condition.value} disabled={!operator?.needs_value}
            onChange={event => { const next = [...column.conditions]; next[position] = { ...condition, value: event.target.value }; onChange(next) }}/>
          <TextField size="small" label="Second value" value={condition.value2} disabled={!operator?.second}
            onChange={event => { const next = [...column.conditions]; next[position] = { ...condition, value2: event.target.value }; onChange(next) }}/>
          <IconButton size="small" aria-label="Remove rule" onClick={() => onChange(column.conditions.filter((_, item) => item !== position))}><CloseRounded sx={{ fontSize: 16 }}/></IconButton>
        </Box>
      })}
      <Button size="small" startIcon={<AddRounded/>} onClick={add}>Add rule</Button>
    </Box>}
    <Box sx={{ display: 'none' }}>{index}</Box>
  </Box>
}

// ---------------------------------------------------------------------------
// Step 3 — layout
// ---------------------------------------------------------------------------

function LayoutStep({ design, update, setDesign, numericColumns }: {
  design: ReportDesign
  update: (patch: Partial<ReportDesign>) => void
  setDesign: React.Dispatch<React.SetStateAction<ReportDesign>>
  numericColumns: ReportColumn[]
}) {
  const usable = design.columns
  const grouped = design.groupings.filter(item => item.kind === 'group')
  const matrixRows = design.groupings.filter(item => item.kind === 'matrix_row')
  const matrixColumn = design.groupings.find(item => item.kind === 'matrix_column')

  const setGroupings = (items: ReportDesign['groupings']) => setDesign(current => ({ ...current, groupings: items }))

  if (design.report_type === 'MATRIX') {
    return <Stack spacing={2.2}>
      <Box>
        <Typography variant="h6" sx={{ mb: .4 }}>The matrix</Typography>
        <Typography color="text.secondary" fontSize={12.5}>Rows down the side, the columns across the top, and one number in each cell. Totals follow the same rules as a grouped report.</Typography>
      </Box>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField select fullWidth label="Rows (down the side)" value={matrixRows[0]?.column_key || ''}
          onChange={event => setGroupings([
            ...design.groupings.filter(item => item.kind !== 'matrix_row'),
            ...(event.target.value ? [{ kind: 'matrix_row' as const, column_key: event.target.value, bucket: matrixRows[0]?.bucket || 'VALUE' }] : []),
            ...(matrixColumn ? [matrixColumn] : []),
          ])}>
          {usable.map(column => <MenuItem key={column.key} value={column.key}>{column.label || column.key}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label="Row bucket" value={matrixRows[0]?.bucket || 'VALUE'}
          onChange={event => setGroupings(design.groupings.map(item => item.kind === 'matrix_row' ? { ...item, bucket: event.target.value } : item))}>
          {BUCKETS.map(bucket => <MenuItem key={bucket.value} value={bucket.value}>{bucket.label}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label="Columns (across the top)" value={matrixColumn?.column_key || ''}
          onChange={event => setGroupings([
            ...design.groupings.filter(item => item.kind !== 'matrix_column'),
            ...(event.target.value ? [{ kind: 'matrix_column' as const, column_key: event.target.value, bucket: matrixColumn?.bucket || 'VALUE' }] : []),
          ])}>
          {usable.map(column => <MenuItem key={column.key} value={column.key}>{column.label || column.key}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label="Column bucket" value={matrixColumn?.bucket || 'VALUE'}
          onChange={event => setGroupings(design.groupings.map(item => item.kind === 'matrix_column' ? { ...item, bucket: event.target.value } : item))}>
          {BUCKETS.map(bucket => <MenuItem key={bucket.value} value={bucket.value}>{bucket.label}</MenuItem>)}
        </TextField>
      </Stack>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
        <TextField select fullWidth label="Value in each cell" value={design.matrix_value_key}
          onChange={event => update({ matrix_value_key: event.target.value })}
          helperText={numericColumns.length ? 'Only numeric or counted columns can be summarised.' : 'Add a number column or a count first.'}>
          {numericColumns.map(column => <MenuItem key={column.key} value={column.key}>{column.label || column.key}</MenuItem>)}
        </TextField>
        <TextField select fullWidth label="Summarise with" value={design.matrix_aggregate}
          onChange={event => update({ matrix_aggregate: event.target.value as Aggregate })}>
          {AGGREGATES.filter(aggregate => aggregate !== 'NONE').map(aggregate => <MenuItem key={aggregate} value={aggregate}>{aggregateLabel(aggregate)}</MenuItem>)}
        </TextField>
        <Box display="flex" alignItems="center">
          <FormControlLabel control={<Checkbox checked={design.matrix_show_totals} onChange={event => update({ matrix_show_totals: event.target.checked })}/>}
            label={<Typography fontSize={12.5}>Show row and grand totals</Typography>}/>
        </Box>
      </Stack>
      <Alert severity="info">Cells left empty mean “no rows for that combination”; they are not the same as zero.</Alert>
    </Stack>
  }

  return <Stack spacing={2.2}>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>Groups, totals and order</Typography>
      <Typography color="text.secondary" fontSize={12.5}>Leave the group list empty for one row per record. Add groups to summarise — each column's own summary decides what the group shows.</Typography>
    </Box>
    {grouped.length === 0 && <Alert severity="info">This report shows every matching record.</Alert>}
    {grouped.map((grouping, index) => <Box key={`${grouping.column_key}-${index}`} sx={{ display: 'grid', gap: 1.4, gridTemplateColumns: { xs: '1fr', md: '2fr 1fr auto' }, alignItems: 'center' }}>
      <TextField size="small" select label="Group by" value={grouping.column_key}
        onChange={event => setGroupings(design.groupings.map((item, position) => position === design.groupings.indexOf(grouping) ? { ...item, column_key: event.target.value } : item))}>
        {usable.map(column => <MenuItem key={column.key} value={column.key}>{column.label || column.key}</MenuItem>)}
      </TextField>
      <TextField size="small" select label="Bucket" value={grouping.bucket}
        onChange={event => setGroupings(design.groupings.map(item => item === grouping ? { ...item, bucket: event.target.value } : item))}>
        {BUCKETS.map(bucket => <MenuItem key={bucket.value} value={bucket.value}>{bucket.label}</MenuItem>)}
      </TextField>
      <IconButton aria-label="Remove group" onClick={() => setGroupings(design.groupings.filter(item => item !== grouping))}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
    </Box>)}
    <Box>
      <Button size="small" startIcon={<AddRounded/>} disabled={!usable.length}
        onClick={() => setGroupings([...design.groupings, { kind: 'group', column_key: usable[0]?.key || '', bucket: 'VALUE' }])}>Add a group</Button>
    </Box>
    <Divider/>
    <Box>
      <Typography fontWeight={800} fontSize={13.5} sx={{ mb: .6 }}>Order</Typography>
      {design.sorts.length === 0 && <Typography color="text.secondary" fontSize={12}>Rows appear in the order the database returns them. Add a sort to make the report predictable.</Typography>}
      {design.sorts.map((sort, index) => <Box key={`${sort.column_key}-${index}`} sx={{ display: 'grid', gap: 1.4, gridTemplateColumns: { xs: '1fr', md: '2fr 1fr auto' }, alignItems: 'center', mb: 1.2 }}>
        <TextField size="small" select label="Sort by" value={sort.column_key}
          onChange={event => setDesign(current => ({ ...current, sorts: current.sorts.map(item => item === sort ? { ...item, column_key: event.target.value } : item) }))}>
          {usable.map(column => <MenuItem key={column.key} value={column.key}>{column.label || column.key}</MenuItem>)}
        </TextField>
        <TextField size="small" select label="Direction" value={sort.direction}
          onChange={event => setDesign(current => ({ ...current, sorts: current.sorts.map(item => item === sort ? { ...item, direction: event.target.value as 'ASC' | 'DESC' } : item) }))}>
          <MenuItem value="ASC">Smallest first</MenuItem>
          <MenuItem value="DESC">Largest first</MenuItem>
        </TextField>
        <IconButton aria-label="Remove sort" onClick={() => setDesign(current => ({ ...current, sorts: current.sorts.filter(item => item !== sort) }))}><CloseRounded sx={{ fontSize: 17 }}/></IconButton>
      </Box>)}
      <Button size="small" startIcon={<AddRounded/>} disabled={!usable.length}
        onClick={() => setDesign(current => ({ ...current, sorts: [...current.sorts, { column_key: usable[0]?.key || '', direction: 'ASC' }] }))}>Add a sort</Button>
    </Box>
    <Divider/>
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
      <Box display="flex" alignItems="center">
        <FormControlLabel control={<Checkbox checked={design.show_totals} onChange={event => update({ show_totals: event.target.checked })}/>}
          label={<Typography fontSize={12.5}>Show a totals row (for columns marked “show total”)</Typography>}/>
      </Box>
      <TextField size="small" select label="Rows per page" value={design.page_size} onChange={event => update({ page_size: Number(event.target.value) })} sx={{ minWidth: 160 }}>
        {[20, 50, 100].map(size => <MenuItem key={size} value={size}>{size} rows</MenuItem>)}
      </TextField>
      <TextField size="small" label="Message when there is nothing to show" value={design.empty_text} fullWidth
        onChange={event => update({ empty_text: event.target.value })} placeholder="No cost sheets were posted in this period."/>
    </Stack>
  </Stack>
}

// ---------------------------------------------------------------------------
// Step 4 — filters and run-time questions
// ---------------------------------------------------------------------------

function FiltersStep({ design, options, setDesign }: {
  design: ReportDesign
  options: FieldOption[]
  setDesign: React.Dispatch<React.SetStateAction<ReportDesign>>
}) {
  const setFilters = (filters: ReportFilter[]) => setDesign(current => ({ ...current, filters }))
  const setRuntime = (runtime_filters: ReportRuntimeFilter[]) => setDesign(current => ({ ...current, runtime_filters }))
  return <Stack spacing={2.4}>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>Built-in filters</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.4 }}>Always applied, for everybody. Use them to keep a report inside its purpose, for example “Drilling AFEs only”.</Typography>
      {design.filters.length === 0 && <Typography color="text.secondary" fontSize={12}>No built-in filters.</Typography>}
      {design.filters.map((filter, index) => {
        const operator = OPERATORS.find(item => item.value === filter.operator)
        return <Box key={index} sx={{ display: 'grid', gap: 1.2, gridTemplateColumns: { xs: '1fr', md: '2fr 1.2fr 1.4fr 1.4fr auto' }, alignItems: 'center', mb: 1.2 }}>
          <TextField size="small" select label="Field" value={encodeField(filter)}
            onChange={event => setFilters(design.filters.map((item, position) => position === index ? { ...item, ...decodeField(event.target.value) } : item))}>
            {options.map(option => <MenuItem key={option.value} value={option.value}>{option.group} · {option.label}</MenuItem>)}
          </TextField>
          <TextField size="small" select label="Rule" value={filter.operator}
            onChange={event => setFilters(design.filters.map((item, position) => position === index ? { ...item, operator: event.target.value } : item))}>
            {OPERATORS.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Value" value={filter.value} disabled={!operator?.needs_value}
            onChange={event => setFilters(design.filters.map((item, position) => position === index ? { ...item, value: event.target.value } : item))}/>
          <TextField size="small" label="Second value" value={filter.value2} disabled={!operator?.second}
            onChange={event => setFilters(design.filters.map((item, position) => position === index ? { ...item, value2: event.target.value } : item))}/>
          <IconButton aria-label="Remove filter" onClick={() => setFilters(design.filters.filter((_, position) => position !== index))}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
        </Box>
      })}
      <Box display="flex" gap={1.2} alignItems="center" flexWrap="wrap">
        <Button size="small" startIcon={<AddRounded/>} disabled={!options.length}
          onClick={() => setFilters([...design.filters, { label: '', source_kind: 'DATA', column_name: '', related_table: '', related_key_column: '', operator: 'eq', value: '', value2: '' }])}>Add a built-in filter</Button>
        {design.filters.length > 1 && <TextField size="small" select label="Combine" value={design.filter_logic}
          onChange={event => setDesign(current => ({ ...current, filter_logic: event.target.value as 'AND' | 'OR' }))} sx={{ minWidth: 210 }}>
          <MenuItem value="AND">All filters must match</MenuItem>
          <MenuItem value="OR">Any filter may match</MenuItem>
        </TextField>}
      </Box>
    </Box>
    <Divider/>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>Questions asked each time the report runs</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.4 }}>
        A question becomes a control above the results. Mark it required when the report is meaningless without an answer.
      </Typography>
      {design.runtime_filters.length === 0 && <Typography color="text.secondary" fontSize={12}>No questions: the reader only chooses a date range.</Typography>}
      {design.runtime_filters.map((question, index) => <Paper key={index} variant="outlined" sx={{ p: 1.6, borderRadius: 2, mb: 1.4 }}>
        <Box sx={{ display: 'grid', gap: 1.2, gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' }, alignItems: 'center' }}>
          <TextField size="small" label="Question" value={question.label}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index ? { ...item, label: event.target.value, key: item.key || keyFromLabel(event.target.value, design.runtime_filters.map(entry => entry.key)) } : item))}/>
          <TextField size="small" select label="Field it filters" value={encodeField(question)}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index ? { ...item, ...decodeField(event.target.value) } : item))}>
            {options.map(option => <MenuItem key={option.value} value={option.value}>{option.group} · {option.label}</MenuItem>)}
          </TextField>
          <TextField size="small" select label="Control" value={question.filter_type}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index ? { ...item, filter_type: event.target.value as ReportRuntimeFilter['filter_type'] } : item))}>
            <MenuItem value="text">Text box</MenuItem>
            <MenuItem value="select">Choose one</MenuItem>
            <MenuItem value="number">Number</MenuItem>
            <MenuItem value="date">Date</MenuItem>
            <MenuItem value="boolean">Yes / no</MenuItem>
          </TextField>
          <TextField size="small" select label="Match" value={question.operator}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index ? { ...item, operator: event.target.value } : item))}>
            {OPERATORS.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Choices (comma separated)" value={question.options.join(', ')}
            disabled={question.filter_type !== 'select'}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index
              ? { ...item, options: event.target.value.split(',').map(choice => choice.trim()).filter(Boolean) } : item))}/>
          <TextField size="small" label="Default answer" value={question.default_value}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index ? { ...item, default_value: event.target.value } : item))}/>
        </Box>
        <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap" sx={{ mt: .8 }}>
          <FormControlLabel control={<Checkbox size="small" checked={question.required}
            onChange={event => setRuntime(design.runtime_filters.map((item, position) => position === index ? { ...item, required: event.target.checked } : item))}/>}
            label={<Typography fontSize={12.5}>Answer required before the report runs</Typography>}/>
          <Button size="small" color="error" startIcon={<DeleteOutlineRounded sx={{ fontSize: 16 }}/>}
            onClick={() => setRuntime(design.runtime_filters.filter((_, position) => position !== index))}>Remove</Button>
        </Box>
      </Paper>)}
      <Button size="small" startIcon={<AddRounded/>} disabled={!options.length}
        onClick={() => setRuntime([...design.runtime_filters, {
          key: `question_${design.runtime_filters.length + 1}`, label: '', filter_type: 'select',
          source_kind: 'DATA', column_name: '', related_table: '', related_key_column: '',
          operator: 'eq', required: false, default_value: '', options: [],
        }])}>Add a question</Button>
    </Box>
  </Stack>
}

// ---------------------------------------------------------------------------
// Step 5 — sharing
// ---------------------------------------------------------------------------

function SharingStep({ design, update, setDesign, lookups }: {
  design: ReportDesign
  update: (patch: Partial<ReportDesign>) => void
  setDesign: React.Dispatch<React.SetStateAction<ReportDesign>>
  lookups: Lookups
}) {
  const setGrants = (grants: ReportGrant[]) => setDesign(current => ({ ...current, grants }))
  const addGrant = () => {
    const role = lookups.roles.find(item => !item.is_owner)
    setGrants([...design.grants, { grant_type: 'role', role_id: role?.id || '', user_id: '', level: 'view' }])
  }
  return <Stack spacing={2.4}>
    <Box>
      <Typography variant="h6" sx={{ mb: .4 }}>Who can run this report?</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.4 }}>
        A report only appears in Custom Reports once it is published, and only for the people this visibility or these grants allow.
      </Typography>
      <Stack spacing={1}>
        {(['private', 'shared', 'internal'] as const).map(option => <Paper key={option} variant="outlined" role="button" tabIndex={0}
          onClick={() => update({ visibility: option })}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') update({ visibility: option }) }}
          sx={{ p: 1.4, borderRadius: 2, cursor: 'pointer', borderColor: design.visibility === option ? 'primary.main' : 'divider', bgcolor: design.visibility === option ? 'action.selected' : 'transparent' }}>
          <Typography fontWeight={800} fontSize={12.8}>{visibilityLabel(option)}</Typography>
          <Typography color="text.secondary" fontSize={11.5}>
            {option === 'private' ? 'Only you, and whoever you grant below. Best while designing.'
              : option === 'shared' ? 'Only the people and roles you name below.' : 'Everybody in this workspace who can read custom reports.'}
          </Typography>
        </Paper>)}
      </Stack>
    </Box>
    <Divider/>
    <Box>
      <Typography fontWeight={800} fontSize={13.5} sx={{ mb: .4 }}>Named access</Typography>
      <Typography color="text.secondary" fontSize={12.5} sx={{ mb: 1.4 }}>
        A role covers everybody who holds it. “Can view” runs the report; “Can edit” may also change the design.
      </Typography>
      {design.grants.length === 0 && <Typography color="text.secondary" fontSize={12}>No named grants.</Typography>}
      {design.grants.map((grant, index) => {
        const target = grant.grant_type === 'role' ? grant.role_id : grant.user_id
        return <Box key={index} sx={{ display: 'grid', gap: 1.2, gridTemplateColumns: { xs: '1fr', md: '1fr 2fr 1.2fr auto' }, alignItems: 'center', mb: 1.2 }}>
          <TextField size="small" select label="Share with" value={grant.grant_type}
            onChange={event => {
              const type = event.target.value as 'role' | 'user'
              setGrants(design.grants.map((item, position) => position === index
                ? { ...item, grant_type: type, role_id: type === 'role' ? (lookups.roles[0]?.id ?? '') : '', user_id: type === 'user' ? (lookups.users[0]?.id ?? '') : '' }
                : item))
            }}>
            <MenuItem value="role">A role</MenuItem>
            <MenuItem value="user">One person</MenuItem>
          </TextField>
          <TextField size="small" select label={grant.grant_type === 'role' ? 'Role' : 'Person'} value={target}
            onChange={event => setGrants(design.grants.map((item, position) => position === index
              ? (grant.grant_type === 'role' ? { ...item, role_id: event.target.value } : { ...item, user_id: event.target.value })
              : item))}>
            {grant.grant_type === 'role'
              ? lookups.roles.map(role => <MenuItem key={role.id} value={role.id}>{role.name}{role.is_owner ? ' (owner)' : ''}</MenuItem>)
              : lookups.users.map(person => <MenuItem key={person.id} value={person.id}>{person.name} · {person.email}</MenuItem>)}
          </TextField>
          <TextField size="small" select label="Access" value={grant.level}
            onChange={event => setGrants(design.grants.map((item, position) => position === index ? { ...item, level: event.target.value as 'view' | 'edit' } : item))}>
            <MenuItem value="view">Can view and run</MenuItem>
            <MenuItem value="edit">Can edit the design</MenuItem>
          </TextField>
          <IconButton aria-label="Remove grant" onClick={() => setGrants(design.grants.filter((_, position) => position !== index))}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></IconButton>
        </Box>
      })}
      <Button size="small" startIcon={<AddRounded/>} onClick={addGrant} disabled={lookups.roles.length === 0 && lookups.users.length === 0}>Add access</Button>
    </Box>
  </Stack>
}

// ---------------------------------------------------------------------------
// Step 6 — preview
// ---------------------------------------------------------------------------

function PreviewStep({ design, run, previewing, onPreview, record }: {
  design: ReportDesign
  run: ReportRun
  previewing: boolean
  onPreview: () => void
  record: ReportDefinition | null
}) {
  return <Stack spacing={2}>
    <Box display="flex" alignItems="flex-start" justifyContent="space-between" gap={2} flexWrap="wrap">
      <Box>
        <Typography variant="h6" sx={{ mb: .4 }}>Preview against live data</Typography>
        <Typography color="text.secondary" fontSize={12.5}>
          Runs the design as it stands, first page only. Nothing is saved by a preview. Roles, permissions and workspace limits still apply when somebody else runs it.
        </Typography>
      </Box>
      <Button variant="contained" startIcon={<PlayArrowRounded/>} disabled={previewing} onClick={onPreview}>{previewing ? 'Running...' : 'Run preview'}</Button>
    </Box>
    {record && <Box display="flex" gap={1} flexWrap="wrap">
      <Tag tone={record.status === 'published' ? 'success' : 'neutral'}>{record.status === 'published' ? 'Published' : 'Draft'}</Tag>
      <Tag tone="info">Version {record.version}</Tag>
      <Tag tone="neutral">{record.run_count} run{record.run_count === 1 ? '' : 's'}</Tag>
      {record.grants.map(grant => <Tag key={`${grant.grant_type}-${grant.id}`} tone="info">{grant.name} · {grant.level}</Tag>)}
    </Box>}
    {run.generated_at && <>
      {run.warnings.map(warning => <Alert key={warning} severity="warning">{warning}</Alert>)}
      <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'auto', maxHeight: '52vh' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {run.columns.map(column => <th key={column.key} style={{
                textAlign: column.align === 'right' ? 'right' : 'left', padding: '9px 12px', fontWeight: 800,
                fontSize: 10.5, letterSpacing: 1.1, textTransform: 'uppercase', borderBottom: '1px solid var(--wcp-line)',
                position: 'sticky', top: 0, background: 'var(--wcp-paper)', whiteSpace: 'nowrap',
              }}>{column.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {run.rows.length === 0 && <tr><td colSpan={Math.max(1, run.columns.length)} style={{ padding: 20, color: 'var(--wcp-muted)' }}>
              {design.empty_text || 'No rows match this design.'}
            </td></tr>}
            {run.rows.map((row, index) => <tr key={index}>
              {run.columns.map(column => <td key={column.key} style={{
                padding: '7px 12px', textAlign: column.align === 'right' ? 'right' : 'left',
                borderBottom: '1px solid var(--wcp-line)', fontVariantNumeric: 'tabular-nums',
              }}>{row[column.key] ?? ''}</td>)}
            </tr>)}
            {run.totals && Object.keys(run.totals).length > 0 && <tr>
              {run.columns.map(column => <td key={column.key} style={{
                padding: '9px 12px', fontWeight: 800, textAlign: column.align === 'right' ? 'right' : 'left',
                borderTop: '2px solid var(--wcp-line-strong)', fontVariantNumeric: 'tabular-nums',
              }}>{run.totals?.[column.key] ?? (run.columns[0]?.key === column.key ? 'Total' : '')}</td>)}
            </tr>}
          </tbody>
        </table>
      </Paper>
      <Stack direction="row" gap={2.5} flexWrap="wrap">
        <Typography fontSize={12} color="text.secondary">Rows shown: {run.rows.length} of {run.total_rows.toLocaleString()}{run.matrix ? ' · matrix' : run.grouped ? ' · grouped' : ''}</Typography>
        <Typography fontSize={12} color="text.secondary">Scanned: {(run.stats?.scanned ?? 0).toLocaleString()}</Typography>
        <Typography fontSize={12} color="text.secondary">Calculated in {run.stats?.elapsed_ms ?? 0} ms</Typography>
        {run.date_from || run.date_to ? <Typography fontSize={12} color="text.secondary">Dates: {run.date_from || '…'} → {run.date_to || '…'}</Typography> : null}
      </Stack>
      {run.notes.map(note => <Typography key={note} fontSize={11.5} color="text.secondary">{note}</Typography>)}
    </>}
    {!run.generated_at && <Alert severity="info">Run the preview to see the first rows this design returns. If a table or column has changed since the report was saved, the preview says so instead of showing a database error.</Alert>}
    <Alert severity="success" icon={<ContentCopyRounded/>}>
      Saving keeps a version snapshot, so an earlier design can always be inspected after a change. Publishing puts the report in Custom Reports.
    </Alert>
  </Stack>
}
