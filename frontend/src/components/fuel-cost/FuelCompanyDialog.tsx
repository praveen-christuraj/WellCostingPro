import { useEffect, useMemo, useState } from 'react'
import { Add, DeleteOutline, RestoreFromTrash, Search } from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { api } from '../../lib/api'
import type { FuelCompany, FuelCostVendorOption } from '../../lib/fuelCost'
import { PanelDialog, Tag } from '../Common'

type Props = {
  open: boolean
  companies: FuelCompany[]
  vendors: FuelCostVendorOption[]
  canCreate: boolean
  canUpdate: boolean
  canDelete: boolean
  canRestore: boolean
  onClose: () => void
  onChanged: () => Promise<void> | void
}

type CompanyFilter = 'all' | 'default' | 'other'

export function FuelCompanyDialog({
  open,
  companies,
  vendors,
  canCreate,
  canUpdate,
  canDelete,
  canRestore,
  onClose,
  onChanged,
}: Props) {
  const [source, setSource] = useState<'vendor' | 'manual'>('vendor')
  const [vendorId, setVendorId] = useState('')
  const [name, setName] = useState('')
  const [isDefault, setIsDefault] = useState(true)
  const [categoryInputs, setCategoryInputs] = useState<Record<string, string>>({})
  const [showDeleted, setShowDeleted] = useState(false)
  const [deleted, setDeleted] = useState<FuelCompany[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<CompanyFilter>('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<20 | 50 | 100>(20)

  const availableVendors = useMemo(
    () => vendors.filter(vendor => !vendor.registered && vendor.status === 'active'),
    [vendors],
  )
  const activeCompanies = useMemo(
    () => companies.filter(company => !company.is_deleted),
    [companies],
  )

  useEffect(() => {
    if (!open) return
    setError('')
    setSource(availableVendors.length ? 'vendor' : 'manual')
    setVendorId(availableVendors[0]?.id ?? '')
  }, [open, availableVendors.length]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open || !showDeleted) return
    api<FuelCompany[]>('/fuel-cost/companies/deleted').then(setDeleted).catch(err => setError((err as Error).message))
  }, [open, showDeleted])

  useEffect(() => {
    setPage(1)
  }, [search, filter, showDeleted, pageSize])

  const refresh = async () => {
    await onChanged()
    if (showDeleted) setDeleted(await api<FuelCompany[]>('/fuel-cost/companies/deleted'))
  }

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await work()
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const addCompany = () =>
    run(async () => {
      const payload = source === 'vendor'
        ? { vendor_id: vendorId, is_default: isDefault }
        : { company_name: name.trim(), is_default: isDefault }
      await api('/fuel-cost/companies', { method: 'POST', body: JSON.stringify(payload) })
      setName('')
    })

  const bulkRegisterVendors = () =>
    run(async () => {
      for (const vendor of availableVendors) {
        await api('/fuel-cost/companies', {
          method: 'POST',
          body: JSON.stringify({ vendor_id: vendor.id, is_default: false }),
        })
      }
    })

  const addCategory = (companyId: string) => {
    const text = (categoryInputs[companyId] ?? '').trim()
    if (!text) return
    run(async () => {
      await api(`/fuel-cost/companies/${companyId}/categories`, {
        method: 'POST',
        body: JSON.stringify({ category_name: text }),
      })
      setCategoryInputs(current => ({ ...current, [companyId]: '' }))
    })
  }

  const baseList = showDeleted ? deleted : activeCompanies
  const defaultCount = useMemo(
    () => activeCompanies.filter(company => company.is_default).length,
    [activeCompanies],
  )

  const filteredList = useMemo(() => {
    const query = search.trim().toLowerCase()
    return baseList.filter(company => {
      if (!showDeleted) {
        if (filter === 'default' && !company.is_default) return false
        if (filter === 'other' && company.is_default) return false
      }
      if (!query) return true
      const cats = company.categories.map(cat => cat.category_name).join(' ')
      return `${company.company_name} ${company.vendor_code} ${cats}`.toLowerCase().includes(query)
    })
  }, [baseList, showDeleted, filter, search])

  const totalPages = Math.max(1, Math.ceil(filteredList.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const pagedList = useMemo(
    () => filteredList.slice((safePage - 1) * pageSize, safePage * pageSize),
    [filteredList, safePage, pageSize],
  )

  return (
    <PanelDialog
      open={open}
      title="Fuel companies and categories"
      subtitle="Manage the daily entry set and each company's consumption categories."
      maxWidth="md"
      onClose={onClose}
    >
      <Stack spacing={1.75}>
        {error ? <Alert severity="error">{error}</Alert> : null}

        {canCreate && !showDeleted ? (
          <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              alignItems={{ sm: 'center' }}
              justifyContent="space-between"
              sx={{ mb: 1.25 }}
            >
              <Typography sx={{ fontWeight: 700, fontSize: 13.5 }}>Add company</Typography>
              {availableVendors.length > 1 ? (
                <Button
                  size="small"
                  variant="text"
                  disabled={busy}
                  onClick={bulkRegisterVendors}
                >
                  Register all {availableVendors.length} Master Data vendors
                </Button>
              ) : null}
            </Stack>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} alignItems={{ md: 'center' }}>
              <TextField
                select
                size="small"
                label="Source"
                value={source}
                onChange={event => setSource(event.target.value as 'vendor' | 'manual')}
                sx={{ minWidth: 165 }}
              >
                <MenuItem value="vendor" disabled={!availableVendors.length}>From Master Data</MenuItem>
                <MenuItem value="manual">Manual name</MenuItem>
              </TextField>
              {source === 'vendor' ? (
                <TextField
                  select
                  size="small"
                  label="Vendor"
                  value={vendorId}
                  onChange={event => setVendorId(event.target.value)}
                  sx={{ flex: 1, minWidth: 210 }}
                >
                  {availableVendors.map(vendor => (
                    <MenuItem key={vendor.id} value={vendor.id}>{vendor.display_name}</MenuItem>
                  ))}
                </TextField>
              ) : (
                <TextField
                  size="small"
                  label="Company name"
                  value={name}
                  onChange={event => setName(event.target.value)}
                  placeholder="Contractor or rig support company"
                  sx={{ flex: 1, minWidth: 210 }}
                />
              )}
              <FormControlLabel
                control={(
                  <Checkbox
                    size="small"
                    checked={isDefault}
                    onChange={event => setIsDefault(event.target.checked)}
                  />
                )}
                label={<Typography sx={{ fontSize: 12.5 }}>Daily set</Typography>}
              />
              <Button
                variant="contained"
                size="small"
                startIcon={<Add />}
                disabled={busy || (source === 'vendor' ? !vendorId : !name.trim())}
                onClick={addCompany}
              >
                Add
              </Button>
            </Stack>
          </Paper>
        ) : null}

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          justifyContent="space-between"
          alignItems={{ sm: 'center' }}
        >
          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField
              size="small"
              placeholder="Search companies or categories…"
              value={search}
              onChange={event => setSearch(event.target.value)}
              inputProps={{ 'aria-label': 'Search companies or categories' }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Search fontSize="small" color="action" />
                  </InputAdornment>
                ),
              }}
              sx={{ width: { xs: '100%', sm: 250 } }}
            />
            {!showDeleted ? (
              <>
                <Button
                  size="small"
                  variant={filter === 'all' ? 'contained' : 'outlined'}
                  onClick={() => setFilter('all')}
                  sx={{ py: 0.25 }}
                >
                  All ({activeCompanies.length})
                </Button>
                <Button
                  size="small"
                  variant={filter === 'default' ? 'contained' : 'outlined'}
                  onClick={() => setFilter('default')}
                  sx={{ py: 0.25 }}
                >
                  Daily set ({defaultCount})
                </Button>
                <Button
                  size="small"
                  variant={filter === 'other' ? 'contained' : 'outlined'}
                  onClick={() => setFilter('other')}
                  sx={{ py: 0.25 }}
                >
                  Other ({activeCompanies.length - defaultCount})
                </Button>
              </>
            ) : null}
          </Stack>

          <Button size="small" onClick={() => setShowDeleted(current => !current)}>
            {showDeleted ? 'Active companies' : 'Deleted companies'}
          </Button>
        </Stack>

        {!filteredList.length ? (
          <Typography color="text.secondary" sx={{ fontSize: 13 }}>
            {showDeleted
              ? 'No deleted companies.'
              : search
                ? 'No companies match your search.'
                : 'No companies added yet.'}
          </Typography>
        ) : (
          <Stack spacing={1} sx={{ maxHeight: 420, overflowY: 'auto', pr: 0.5 }}>
            {pagedList.map(company => (
              <Paper key={company.id} variant="outlined" sx={{ p: 1.25, borderRadius: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" flexWrap="wrap">
                  <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography sx={{ fontWeight: 700, fontSize: 13.5 }}>{company.company_name}</Typography>
                    {company.vendor_code ? <Tag tone="info">{company.vendor_code}</Tag> : <Tag>Manual</Tag>}
                    {company.is_default && !company.is_deleted ? <Tag tone="success">Daily set</Tag> : null}
                  </Stack>
                  {company.is_deleted ? (
                    canRestore ? (
                      <Button
                        size="small"
                        startIcon={<RestoreFromTrash fontSize="small" />}
                        disabled={busy}
                        onClick={() => run(() => api(`/fuel-cost/companies/${company.id}/restore`, { method: 'POST' }))}
                      >
                        Restore
                      </Button>
                    ) : null
                  ) : (
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      {canUpdate ? (
                        <Button
                          size="small"
                          disabled={busy}
                          onClick={() =>
                            run(() => api(`/fuel-cost/companies/${company.id}`, {
                              method: 'PUT',
                              body: JSON.stringify({ is_default: !company.is_default }),
                            }))}
                        >
                          {company.is_default ? 'Remove from daily set' : 'Add to daily set'}
                        </Button>
                      ) : null}
                      {canDelete ? (
                        <Tooltip title="Delete company">
                          <span>
                            <IconButton
                              size="small"
                              aria-label={`Delete ${company.company_name}`}
                              disabled={busy}
                              onClick={() => run(() => api(`/fuel-cost/companies/${company.id}`, { method: 'DELETE' }))}
                            >
                              <DeleteOutline fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      ) : null}
                    </Stack>
                  )}
                </Stack>

                {!company.is_deleted ? (
                  <Box sx={{ mt: 1 }}>
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap alignItems="center">
                      {company.categories.filter(cat => !cat.is_deleted).map(category => (
                        <Stack
                          key={category.id}
                          direction="row"
                          spacing={0.25}
                          alignItems="center"
                          sx={{
                            pl: 1,
                            pr: 0.4,
                            py: 0.15,
                            borderRadius: 1,
                            border: '1px solid',
                            borderColor: 'divider',
                          }}
                        >
                          <Typography sx={{ fontSize: 12 }}>{category.category_name}</Typography>
                          {canDelete ? (
                            <IconButton
                              size="small"
                              aria-label={`Delete category ${category.category_name}`}
                              disabled={busy}
                              onClick={() => run(() => api(`/fuel-cost/categories/${category.id}`, { method: 'DELETE' }))}
                              sx={{ p: 0.2 }}
                            >
                              <DeleteOutline sx={{ fontSize: 14 }} />
                            </IconButton>
                          ) : null}
                        </Stack>
                      ))}
                      {!company.categories.some(cat => !cat.is_deleted) ? (
                        <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                          Uncategorised (add categories if needed)
                        </Typography>
                      ) : null}
                    </Stack>
                    {canCreate ? (
                      <Stack direction="row" spacing={0.75} sx={{ mt: 1 }} alignItems="center">
                        <TextField
                          size="small"
                          placeholder="New category (e.g. Crew, Camp, Cranes)"
                          value={categoryInputs[company.id] ?? ''}
                          onChange={event =>
                            setCategoryInputs(current => ({ ...current, [company.id]: event.target.value }))}
                          onKeyDown={event => {
                            if (event.key === 'Enter') {
                              event.preventDefault()
                              addCategory(company.id)
                            }
                          }}
                          sx={{ maxWidth: 280 }}
                        />
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={busy || !(categoryInputs[company.id] ?? '').trim()}
                          onClick={() => addCategory(company.id)}
                        >
                          Add category
                        </Button>
                      </Stack>
                    ) : null}
                  </Box>
                ) : null}
              </Paper>
            ))}
          </Stack>
        )}

        {filteredList.length > 20 ? (
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1}
            alignItems={{ sm: 'center' }}
            justifyContent="space-between"
          >
            <Typography color="text.secondary" sx={{ fontSize: 12 }}>
              Showing {(safePage - 1) * pageSize + 1}–{Math.min(safePage * pageSize, filteredList.length)} of {filteredList.length}
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center">
              <TextField
                select
                size="small"
                label="Rows"
                value={pageSize}
                onChange={event => setPageSize(Number(event.target.value) as 20 | 50 | 100)}
                sx={{ width: 92 }}
              >
                <MenuItem value={20}>20</MenuItem>
                <MenuItem value={50}>50</MenuItem>
                <MenuItem value={100}>100</MenuItem>
              </TextField>
              <Button size="small" disabled={safePage <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>
                Prev
              </Button>
              <Typography sx={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                {safePage} / {totalPages}
              </Typography>
              <Button size="small" disabled={safePage >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
                Next
              </Button>
            </Stack>
          </Stack>
        ) : null}
      </Stack>
    </PanelDialog>
  )
}
