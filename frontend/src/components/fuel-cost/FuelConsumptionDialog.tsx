import { type ReactNode, useEffect, useMemo, useState } from 'react'
import {
  AddRounded, DeleteOutlineRounded, LocalGasStationOutlined, LockOutlined, PlaylistAddRounded,
  SwapVertRounded,
} from '@mui/icons-material'
import {
  Alert, Box, Button, CircularProgress, Divider, IconButton, MenuItem, Paper, TextField, Tooltip, Typography,
} from '@mui/material'
import { ErrorMessage, FormDialog, Tag } from '../Common'
import { api, body } from '../../lib/api'
import { displayDate } from '../../lib/dailyCost'
import {
  blankFuelLine, fuelBalancePreview, fuelDraftDirty, fuelDraftFromDay, fuelHasErrors,
  fuelLineKey, fuelLitres, fuelSavePayload, validateFuelDraft,
  type FuelCompany, type FuelCostDay, type FuelCostReference, type FuelCostRigOption, type FuelDraft,
  type FuelDraftErrors, type FuelDraftLine,
} from '../../lib/fuelCost'

type InlineEditor = {
  key: string
  kind: 'company' | 'category'
  name: string
  vendorId: string
  companyId: string
  isDefault: boolean
}

function emptyErrors(): FuelDraftErrors {
  return { lines: {}, summary: [] }
}

export function FuelConsumptionDialog({
  open, day, loading, loadError, rig, costDate, companies, vendors, canEdit, canManageCompanies,
  canOverrideOpening, saving, saveError, onClose, onSave, onCompaniesChanged,
}: {
  open: boolean
  day: FuelCostDay | null
  loading: boolean
  loadError: string
  rig: FuelCostRigOption | null
  costDate: string
  companies: FuelCompany[]
  vendors: FuelCostReference['vendors']
  canEdit: boolean
  canManageCompanies: boolean
  canOverrideOpening: boolean
  saving: boolean
  saveError: string
  onClose: () => void
  onSave: (payload: ReturnType<typeof fuelSavePayload>) => Promise<boolean>
  onCompaniesChanged: () => Promise<void> | void
}) {
  const [draft, setDraft] = useState<FuelDraft | null>(null)
  const [baseline, setBaseline] = useState<FuelDraft | null>(null)
  const [errors, setErrors] = useState<FuelDraftErrors>(emptyErrors)
  const [inline, setInline] = useState<InlineEditor | null>(null)
  const [inlineError, setInlineError] = useState('')
  const [inlineBusy, setInlineBusy] = useState(false)

  const dayKey = day
    ? `${day.rig_id}:${day.cost_date}:${day.entry?.id ?? 'new'}:${day.entry?.revision ?? 0}`
    : ''

  useEffect(() => {
    if (!open || !day) return
    const next = fuelDraftFromDay(day)
    setDraft(next)
    setBaseline(next)
    setErrors(emptyErrors())
    setInline(null)
    setInlineError('')
    // Re-seed only when a different day/revision is loaded, never on a parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dayKey])

  const activeCompanies = useMemo(
    () => companies.filter(company => !company.is_deleted),
    [companies],
  )
  const categoriesFor = (companyId: string) =>
    (activeCompanies.find(company => company.id === companyId)?.categories ?? [])
      .filter(category => !category.is_deleted)

  if (!open) return null

  const dirty = Boolean(draft && baseline && fuelDraftDirty(draft, baseline))
  const preview = day && draft ? fuelBalancePreview(day, draft) : null
  const isFirst = Boolean(day && (day.entry ? day.entry.balance.is_first_entry : day.balance.is_first_entry))
  const openingEditable = isFirst || Boolean(draft?.openingOverride)

  const update = (patch: Partial<FuelDraft>) =>
    setDraft(current => (current ? { ...current, ...patch } : current))

  const updateLine = (key: string, patch: Partial<FuelDraftLine>) =>
    setDraft(current => current
      ? { ...current, lines: current.lines.map(line => (line.key === key ? { ...line, ...patch } : line)) }
      : current)

  const addLine = (line?: Partial<FuelDraftLine>) =>
    setDraft(current => current
      ? { ...current, lines: [...current.lines, { ...blankFuelLine(), ...line }] }
      : current)

  const removeLine = (key: string) =>
    setDraft(current => current
      ? { ...current, lines: current.lines.filter(line => line.key !== key) }
      : current)

  const addDailySet = () => {
    if (!draft) return
    const present = new Set(draft.lines.map(line => line.company_id))
    const additions = activeCompanies
      .filter(company => company.is_default && !present.has(company.id))
      .map(company => ({
        ...blankFuelLine(),
        company_id: company.id,
        key: fuelLineKey(),
      }))
    if (!additions.length) return
    setDraft(current => current ? { ...current, lines: [...current.lines, ...additions] } : current)
  }

  const toggleOverride = (next: boolean) => {
    if (!draft || !canOverrideOpening) return
    if (next) {
      update({
        openingOverride: true,
        opening: draft.opening.trim() || String(preview?.carried ?? day?.balance.carried_opening ?? ''),
      })
    } else {
      update({ openingOverride: false, opening: '' })
    }
  }

  const submit = async () => {
    if (!day || !draft || !rig) return
    const found = validateFuelDraft(draft, day)
    setErrors(found)
    if (fuelHasErrors(found)) return
    if (draft.openingOverride && !canOverrideOpening) {
      setErrors({ ...found, opening: 'You do not have permission to override the opening stock.' })
      return
    }
    await onSave(fuelSavePayload({
      rigId: rig.id,
      costDate,
      draft,
      day,
      expectedRevision: day.entry?.revision ?? null,
    }))
  }

  const beginInline = (line: FuelDraftLine, kind: 'company' | 'category') => {
    if (kind === 'company') {
      setInline({ key: line.key, kind, name: '', vendorId: '', companyId: '', isDefault: false })
    } else {
      if (!line.company_id) return
      setInline({ key: line.key, kind, name: '', vendorId: '', companyId: line.company_id, isDefault: false })
    }
    setInlineError('')
  }

  const runInline = async () => {
    if (!inline) return
    const name = inline.name.trim()
    if (!name) {
      setInlineError(inline.kind === 'company' ? 'Enter the company name.' : 'Enter the category name.')
      return
    }
    setInlineBusy(true)
    setInlineError('')
    try {
      if (inline.kind === 'company') {
        const created = await api<FuelCompany>('/fuel-cost/companies', {
          method: 'POST',
          body: body({
            company_name: name,
            vendor_id: inline.vendorId,
            is_default: inline.isDefault,
            remarks: '',
          }),
        })
        await onCompaniesChanged()
        updateLine(inline.key, { company_id: created.id, category_id: '' })
      } else {
        const company = await api<FuelCompany>(`/fuel-cost/companies/${inline.companyId}/categories`, {
          method: 'POST',
          body: body({ category_name: name, remarks: '' }),
        })
        await onCompaniesChanged()
        const category = company.categories.find(item => item.category_name.toLowerCase() === name.toLowerCase())
        updateLine(inline.key, { category_id: category?.id ?? '' })
      }
      setInline(null)
    } catch (caught) {
      setInlineError(caught instanceof Error ? caught.message : 'The record could not be created')
    } finally {
      setInlineBusy(false)
    }
  }

  const lineLabel = (line: FuelDraftLine) => {
    const company = activeCompanies.find(item => item.id === line.company_id)
    const category = company?.categories.find(item => item.id === line.category_id)
    if (!company) return ''
    return category ? `${company.company_name} · ${category.category_name}` : company.company_name
  }

  return <FormDialog
    open={open}
    title={`Fuel consumption · ${rig?.rig_code ?? ''} · ${displayDate(costDate)}`}
    subtitle={day?.entry
      ? `Edit the stored fuel day of ${rig?.rig_code ?? day.rig_code} on ${displayDate(costDate)}. AGO is measured in litres; gas is recorded separately and never mixed into AGO.`
      : `Record the AGO and gas of ${rig?.rig_code ?? 'the rig'} for ${displayDate(costDate)}. Opening stock is captured on the rig's first day and carried forward afterwards.`}
    onClose={onClose}
    onSubmit={() => void submit()}
    busy={saving}
    busyLabel={day?.entry ? 'Saving the fuel day…' : 'Adding the fuel day…'}
    submitLabel={day?.entry ? 'Save fuel day' : 'Add fuel day'}
    submitDisabled={loading || !canEdit || !draft || Boolean(loadError)}
    dirty={dirty}
    maxWidth="xl"
  >
    {loading ? <Box py={6} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={26}/></Box>
      : loadError ? <ErrorMessage message={loadError}/>
      : !draft || !day || !preview ? <Typography color="text.secondary">This fuel day is not available.</Typography>
      : <Box display="grid" gap={1.8}>
        <Box display="flex" gap={1} flexWrap="wrap" alignItems="center">
          <Tag tone="info">{rig?.rig_code ?? day.rig_code}</Tag>
          <Tag>{displayDate(costDate)}</Tag>
          {isFirst && <Tag tone="warning">First fuel entry — opening stock required</Tag>}
          {!isFirst && !draft.openingOverride && <Tag>Opening carried from {displayDate(day.balance.previous_date)}</Tag>}
          {draft.openingOverride && <Tag tone="warning">Opening stock overridden</Tag>}
          {!canEdit && <Tag tone="neutral">Read only</Tag>}
          {day.entry && <Tag>Revision {day.entry.revision}</Tag>}
        </Box>

        {/* AGO on the rig engines and the separately recorded gas. */}
        <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
          <SectionTitle
            icon={<LocalGasStationOutlined sx={{ fontSize: 18 }}/>}
            title="Rig engines"
            subtitle="AGO burnt by the rig engines themselves, and the separately recorded gas."
          />
          <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', md: '1fr 2fr' } }}>
            <TextField
              type="number"
              size="small"
              label="Rig engine consumption (litres)"
              value={draft.rigEngine}
              onChange={event => update({ rigEngine: event.target.value })}
              error={Boolean(errors.engine)}
              helperText={errors.engine ?? 'AGO used by the rig engines.'}
              inputProps={{ min: 0, step: 'any' }}
              disabled={!canEdit}
            />
            <TextField
              size="small"
              label="Rig engine remarks"
              value={draft.rigEngineRemarks}
              onChange={event => update({ rigEngineRemarks: event.target.value })}
              inputProps={{ maxLength: 500 }}
              disabled={!canEdit}
            />
            <TextField
              type="number"
              size="small"
              label="Gas consumption (litres)"
              value={draft.gas}
              onChange={event => update({ gas: event.target.value })}
              error={Boolean(errors.gas)}
              helperText={errors.gas ?? 'Recorded for information only — not part of the AGO balance.'}
              inputProps={{ min: 0, step: 'any' }}
              disabled={!canEdit}
            />
            <TextField
              size="small"
              label="Gas remarks"
              value={draft.gasRemarks}
              onChange={event => update({ gasRemarks: event.target.value })}
              inputProps={{ maxLength: 500 }}
              disabled={!canEdit}
            />
          </Box>
        </Paper>

        {/* Stock and receipts: the opening is captured once and carried forward. */}
        <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
          <SectionTitle
            icon={<SwapVertRounded sx={{ fontSize: 18 }}/>}
            title="Stock and receipts"
            subtitle={isFirst
              ? 'Enter the rig’s physical opening stock. Every later day carries the actual closing stock forward.'
              : 'Opening stock comes from the previous day’s actual closing stock. Override it only when the physical stock differs.'}
          />
          <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', md: '1fr 1.4fr' } }}>
            <Box>
              <Box display="flex" gap={.8} alignItems="flex-start">
                <TextField
                  type="number"
                  size="small"
                  fullWidth
                  label="Opening stock (litres)"
                  value={openingEditable ? draft.opening : String(preview.opening)}
                  onChange={event => update({ opening: event.target.value })}
                  error={Boolean(errors.opening)}
                  helperText={errors.opening ?? (isFirst
                    ? 'Mandatory on the first entry of this rig.'
                    : draft.openingOverride
                      ? `Carried opening was ${fuelLitres(preview.carried)} L; the difference is an adjustment.`
                      : `Carried from the closing stock on ${displayDate(day.balance.previous_date)}.`)}
                  inputProps={{ min: 0, step: 'any' }}
                  disabled={!canEdit || !openingEditable}
                  InputProps={!openingEditable ? { readOnly: true, startAdornment: <LockOutlined sx={{ fontSize: 15, mr: .6, color: 'text.disabled' }}/> } : undefined}
                />
                <Tooltip title={canOverrideOpening
                  ? 'Override the carried opening stock and report the difference as an adjustment'
                  : 'Overriding the opening stock needs the fuel opening-stock permission'}>
                  <span>
                    <Button
                      size="small"
                      variant="outlined"
                      sx={{ mt: .4, minWidth: 118, whiteSpace: 'nowrap' }}
                      startIcon={<SwapVertRounded sx={{ fontSize: 16 }}/>}
                      disabled={!canEdit || !canOverrideOpening || isFirst || saving}
                      onClick={() => toggleOverride(!draft.openingOverride)}
                    >
                      {draft.openingOverride ? 'Use carried' : 'Override'}
                    </Button>
                  </span>
                </Tooltip>
              </Box>
              {(openingEditable || draft.openingRemarks) && <TextField
                size="small"
                fullWidth
                sx={{ mt: 1 }}
                label="Opening stock remarks"
                value={draft.openingRemarks}
                onChange={event => update({ openingRemarks: event.target.value })}
                inputProps={{ maxLength: 500 }}
                disabled={!canEdit}
              />}
            </Box>
            <Box>
              <Box display="grid" gap={1.2} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                <TextField
                  type="number"
                  size="small"
                  label="Receipt (litres)"
                  value={draft.receipt}
                  onChange={event => update({ receipt: event.target.value })}
                  error={Boolean(errors.receipt)}
                  helperText={errors.receipt ?? 'Daily receipt; empty counts as zero.'}
                  inputProps={{ min: 0, step: 'any' }}
                  disabled={!canEdit}
                />
                <TextField
                  type="number"
                  size="small"
                  label="Actual closing stock (litres)"
                  value={draft.closing}
                  onChange={event => update({ closing: event.target.value })}
                  error={Boolean(errors.closing)}
                  helperText={errors.closing ?? `Empty accepts the book closing (${fuelLitres(preview.bookClosing)} L).`}
                  inputProps={{ min: 0, step: 'any' }}
                  disabled={!canEdit}
                />
                <TextField
                  size="small"
                  label="Receipt remarks"
                  value={draft.receiptRemarks}
                  onChange={event => update({ receiptRemarks: event.target.value })}
                  inputProps={{ maxLength: 500 }}
                  disabled={!canEdit}
                />
                <TextField
                  size="small"
                  label="Closing stock remarks"
                  value={draft.closingRemarks}
                  onChange={event => update({ closingRemarks: event.target.value })}
                  inputProps={{ maxLength: 500 }}
                  disabled={!canEdit}
                />
              </Box>
            </Box>
          </Box>
        </Paper>

        {/* Company-wise AGO consumption, classified by company and category. */}
        <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start" gap={1} flexWrap="wrap" mb={1}>
            <SectionTitle
              icon={<PlaylistAddRounded sx={{ fontSize: 18 }}/>}
              title="Company consumption (AGO)"
              subtitle="Book the rig's AGO under each company, and under a company category where it applies. The company total is added to the rig engine consumption to give the rig's AGO consumption."
            />
            <Box display="flex" gap={.8} flexWrap="wrap">
              <Button size="small" variant="outlined" startIcon={<PlaylistAddRounded sx={{ fontSize: 16 }}/>}
                onClick={addDailySet} disabled={!canEdit || !activeCompanies.some(company => company.is_default)}>
                Add daily set
              </Button>
              <Button size="small" variant="outlined" startIcon={<AddRounded sx={{ fontSize: 16 }}/>}
                onClick={() => addLine()} disabled={!canEdit}>
                Add company
              </Button>
            </Box>
          </Box>
          {!activeCompanies.length && <Alert severity="info" sx={{ mb: 1.2 }}>
            No companies are registered yet. Use <strong>Add company</strong> on a row to register one, or manage
            the daily set from the Companies &amp; categories panel on the register.
          </Alert>}
          {draft.lines.length === 0 && <Typography color="text.secondary" fontSize={12.5} mb={1}>
            No company consumption on this day yet. Use <strong>Add daily set</strong> to list the default companies,
            or <strong>Add company</strong> for a single entry.
          </Typography>}
          <Box display="grid" gap={1.2}>
            {draft.lines.map(line => {
              const categories = categoriesFor(line.company_id)
              const company = activeCompanies.find(item => item.id === line.company_id)
              return <Box key={line.key} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, p: 1.1 }}>
                <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', md: '1.3fr 1fr .7fr 1.3fr auto' } }} alignItems="start">
                  <TextField
                    select
                    size="small"
                    label="Company"
                    value={line.company_id}
                    onChange={event => {
                      if (event.target.value === '__new') { beginInline(line, 'company'); return }
                      updateLine(line.key, { company_id: event.target.value, category_id: '' })
                    }}
                    disabled={!canEdit}
                    error={Boolean(errors.lines[line.key])}
                  >
                    <MenuItem value="">Choose company</MenuItem>
                    {activeCompanies.map(item => <MenuItem key={item.id} value={item.id}>{item.company_name}</MenuItem>)}
                    {canManageCompanies && <MenuItem value="__new">＋ Register new company…</MenuItem>}
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label="Category"
                    value={line.category_id}
                    onChange={event => {
                      if (event.target.value === '__new') { beginInline(line, 'category'); return }
                      updateLine(line.key, { category_id: event.target.value })
                    }}
                    disabled={!canEdit || !line.company_id}
                    helperText={line.company_id && !categories.length ? 'Optional — register a category to classify further.' : undefined}
                  >
                    <MenuItem value="">No category</MenuItem>
                    {categories.map(category => <MenuItem key={category.id} value={category.id}>{category.category_name}</MenuItem>)}
                    {canManageCompanies && <MenuItem value="__new">＋ New category…</MenuItem>}
                  </TextField>
                  <TextField
                    type="number"
                    size="small"
                    label="Litres (AGO)"
                    value={line.litres}
                    onChange={event => updateLine(line.key, { litres: event.target.value })}
                    inputProps={{ min: 0, step: 'any' }}
                    disabled={!canEdit}
                    error={Boolean(errors.lines[line.key])}
                  />
                  <TextField
                    size="small"
                    label="Remarks"
                    value={line.remarks}
                    onChange={event => updateLine(line.key, { remarks: event.target.value })}
                    inputProps={{ maxLength: 500 }}
                    disabled={!canEdit}
                  />
                  <Tooltip title="Remove this company row">
                    <span><IconButton size="small" color="error" aria-label="Remove company consumption row"
                      onClick={() => removeLine(line.key)} disabled={!canEdit}>
                      <DeleteOutlineRounded sx={{ fontSize: 17 }}/>
                    </IconButton></span>
                  </Tooltip>
                </Box>
                {errors.lines[line.key] && <Box mt={.6}><ErrorMessage message={errors.lines[line.key]}/></Box>}
                {company && <Typography fontSize={10.5} color="text.secondary" mt={.5}>
                  {lineLabel(line)}{line.litres.trim() ? ` · ${fuelLitres(line.litres)} L` : ''}
                </Typography>}
                {inline && inline.key === line.key && <Box mt={1} sx={{ border: '1px dashed', borderColor: 'divider', borderRadius: 1.5, p: 1.1 }}>
                  <Typography fontSize={11.5} fontWeight={800} mb={.8}>
                    {inline.kind === 'company' ? 'Register a new fuel company' : `New category under ${company?.company_name ?? 'this company'}`}
                  </Typography>
                  <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: inline.kind === 'company' ? '1.4fr 1.2fr auto auto' : '1.6fr auto auto' } }} alignItems="start">
                    <TextField autoFocus size="small" label={inline.kind === 'company' ? 'Company name' : 'Category name'}
                      value={inline.name}
                      onChange={event => setInline({ ...inline, name: event.target.value })}
                      inputProps={{ maxLength: inline.kind === 'company' ? 200 : 120 }}/>
                    {inline.kind === 'company' && <TextField select size="small" label="Vendor (optional)"
                      value={inline.vendorId} onChange={event => setInline({ ...inline, vendorId: event.target.value })}>
                      <MenuItem value="">Not a vendor</MenuItem>
                      {vendors.map(vendor => <MenuItem key={vendor.id} value={vendor.id}>{vendor.display_name}</MenuItem>)}
                    </TextField>}
                    {inline.kind === 'company' && <Button size="small" variant={inline.isDefault ? 'contained' : 'outlined'}
                      onClick={() => setInline({ ...inline, isDefault: !inline.isDefault })}>
                      {inline.isDefault ? 'In daily set' : 'Add to daily set'}
                    </Button>}
                    <Box display="flex" gap={.6}>
                      <Button size="small" variant="contained" onClick={() => void runInline()} disabled={inlineBusy}>
                        {inlineBusy ? 'Saving…' : 'Add'}
                      </Button>
                      <Button size="small" color="inherit" onClick={() => { setInline(null); setInlineError('') }} disabled={inlineBusy}>
                        Cancel
                      </Button>
                    </Box>
                  </Box>
                  {inlineError && <ErrorMessage message={inlineError}/>}
                </Box>}
              </Box>
            })}
          </Box>
          <Box display="flex" justifyContent="space-between" gap={1} flexWrap="wrap" mt={1.2}>
            <Typography fontSize={12} color="text.secondary">
              {draft.lines.filter(line => line.company_id).length} company row(s) · {fuelLitres(preview.company)} L
            </Typography>
            <Typography fontSize={12} fontWeight={800}>Company AGO total: {fuelLitres(preview.company)} L</Typography>
          </Box>
        </Paper>

        {/* Live material balance. */}
        <Paper variant="outlined" sx={{ p: 1.6, borderRadius: 2 }}>
          <SectionTitle
            icon={<SwapVertRounded sx={{ fontSize: 18 }}/>}
            title="Material balance"
            subtitle="Calculated automatically in litres. Opening + receipts − AGO consumption = book closing; the physical count and any opening override explain the adjustments."
          />
          <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' } }}>
            <BalanceTile label="Opening stock" value={fuelLitres(preview.opening)} note={isFirst ? 'Entered on the first day' : draft.openingOverride ? 'Overridden' : 'Carried forward'}/>
            <BalanceTile label="Opening adjustment" value={fuelLitres(preview.openingAdjustment)} note={isFirst ? 'First day — no adjustment' : 'Override minus carried stock'}/>
            <BalanceTile label="Receipts" value={fuelLitres(preview.receipt)} note="Daily receipt"/>
            <BalanceTile label="Rig engine AGO" value={fuelLitres(preview.engine)} note="Rig engines"/>
            <BalanceTile label="Company AGO" value={fuelLitres(preview.company)} note="All company rows"/>
            <BalanceTile label="Total AGO consumption" value={fuelLitres(preview.totalConsumption)} note="Engines + companies" strong/>
            <BalanceTile label="Book closing stock" value={fuelLitres(preview.bookClosing)} note="Opening + receipts − AGO"/>
            <BalanceTile label="Actual closing stock" value={fuelLitres(preview.actualClosing)} note={draft.closing.trim() ? 'Entered count' : 'Book closing accepted'}/>
            <BalanceTile label="Adjustments" value={fuelLitres(preview.adjustments)} note="Opening + closing adjustments" strong/>
          </Box>
          <Divider sx={{ my: 1.2 }}/>
          <Box display="flex" justifyContent="space-between" gap={1} flexWrap="wrap">
            <Typography fontSize={12} color="text.secondary">
              Gas recorded separately: <strong>{fuelLitres(preview.gas)} L</strong> — not included in AGO consumption or the material balance.
            </Typography>
            <Typography fontSize={12} fontWeight={800}>
              AGO consumption {fuelLitres(preview.totalConsumption)} L · Closing stock {fuelLitres(preview.actualClosing)} L
            </Typography>
          </Box>
        </Paper>

        <TextField
          size="small"
          label="Day remarks"
          value={draft.remarks}
          onChange={event => update({ remarks: event.target.value })}
          multiline
          minRows={2}
          inputProps={{ maxLength: 1000 }}
          disabled={!canEdit}
          helperText="Context for the day, for example a delivery, a shutdown or a stock count."
        />

        {errors.summary.length > 0 && <Alert severity="error">
          <Box component="ul" sx={{ m: 0, pl: 2 }}>
            {errors.summary.map(message => <li key={message}><Typography fontSize={12.5}>{message}</Typography></li>)}
          </Box>
        </Alert>}
        {saveError && <ErrorMessage message={saveError}/>}
      </Box>}
  </FormDialog>
}

function SectionTitle({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle: string }) {
  return <Box mb={1.1}>
    <Box display="flex" alignItems="center" gap={.7}>
      <Box sx={{ color: 'primary.main', display: 'flex' }}>{icon}</Box>
      <Typography fontWeight={800} fontSize={14}>{title}</Typography>
    </Box>
    <Typography color="text.secondary" fontSize={11.5} mt={.2} sx={{ maxWidth: 760, lineHeight: 1.45 }}>{subtitle}</Typography>
  </Box>
}

function BalanceTile({ label, value, note, strong = false }: { label: string; value: string; note: string; strong?: boolean }) {
  return <Box sx={{
    border: '1px solid', borderColor: 'divider', borderRadius: 1.5, px: 1.2, py: .9,
    bgcolor: strong ? 'action.hover' : 'transparent',
  }}>
    <Typography fontSize={9.5} fontWeight={800} letterSpacing={.5} color="text.secondary">{label.toUpperCase()}</Typography>
    <Typography fontSize={16} fontWeight={800} mt={.2}>{value}</Typography>
    <Typography fontSize={10.5} color="text.secondary" mt={.2}>{note}</Typography>
  </Box>
}
