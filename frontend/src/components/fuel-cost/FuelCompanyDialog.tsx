import { useEffect, useState } from 'react'
import { AddRounded, DeleteOutlineRounded, RestoreRounded, StarOutlineRounded, StarRounded } from '@mui/icons-material'
import {
  Box, Button, Checkbox, CircularProgress, FormControlLabel, IconButton, MenuItem, Paper, TextField, Tooltip, Typography,
} from '@mui/material'
import { ErrorMessage, PanelDialog, Tag } from '../Common'
import { api, body } from '../../lib/api'
import type { FuelCompany, FuelCostVendorOption } from '../../lib/fuelCost'

/**
 * The daily entry set and its categories.
 *
 * Companies are usually extracted from Master Data vendors, but a free-text
 * company is allowed. Companies flagged as default are pre-listed by the
 * consumption dialog ("Add daily set"). Each company owns its own categories, so
 * consumption can be accounted per company and per category.
 */
export function FuelCompanyDialog({
  open, companies, vendors, canManage, onClose, onChanged,
}: {
  open: boolean
  companies: FuelCompany[]
  vendors: FuelCostVendorOption[]
  canManage: boolean
  onClose: () => void
  onChanged: () => Promise<void> | void
}) {
  const [name, setName] = useState('')
  const [vendorId, setVendorId] = useState('')
  const [isDefault, setIsDefault] = useState(true)
  const [categoryNames, setCategoryNames] = useState<Record<string, string>>({})
  const [showRemoved, setShowRemoved] = useState(false)
  const [removed, setRemoved] = useState<FuelCompany[]>([])
  const [removedLoading, setRemovedLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!open) {
      setName(''); setVendorId(''); setIsDefault(true); setCategoryNames({})
      setShowRemoved(false); setRemoved([]); setBusy(''); setError(''); setNotice('')
    }
  }, [open])

  const loadRemoved = async () => {
    setRemovedLoading(true)
    try {
      setRemoved(await api<FuelCompany[]>('/fuel-cost/companies/deleted'))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The removed companies could not be loaded')
    } finally {
      setRemovedLoading(false)
    }
  }

  useEffect(() => {
    if (open && showRemoved && !removed.length) void loadRemoved()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, showRemoved])

  const run = async (key: string, action: () => Promise<unknown>, message?: string) => {
    setBusy(key)
    setError('')
    setNotice('')
    try {
      await action()
      await onChanged()
      if (showRemoved) await loadRemoved()
      if (message) setNotice(message)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The change could not be saved')
    } finally {
      setBusy('')
    }
  }

  const addCompany = () => {
    const trimmed = name.trim()
    if (!trimmed) { setError('Enter the company name.'); return }
    void run('new-company', async () => {
      await api<FuelCompany>('/fuel-cost/companies', {
        method: 'POST',
        body: body({ company_name: trimmed, vendor_id: vendorId, is_default: isDefault, remarks: '' }),
      })
      setName(''); setVendorId(''); setIsDefault(true)
    }, `“${trimmed}” is registered${isDefault ? ' in the daily entry set' : ''}.`)
  }

  const toggleDefault = (company: FuelCompany) => void run(`default-${company.id}`, async () => {
    await api(`/fuel-cost/companies/${company.id}`, {
      method: 'PUT', body: body({ is_default: !company.is_default }),
    })
  })

  const removeCompany = (company: FuelCompany) => void run(`remove-${company.id}`, async () => {
    await api(`/fuel-cost/companies/${company.id}`, { method: 'DELETE' })
  }, `“${company.company_name}” was removed. Its recorded consumption is kept.`)

  const restoreCompany = (company: FuelCompany) => void run(`restore-${company.id}`, async () => {
    await api(`/fuel-cost/companies/${company.id}/restore`, { method: 'POST' })
  }, `“${company.company_name}” was restored.`)

  const addCategory = (company: FuelCompany) => {
    const value = (categoryNames[company.id] ?? '').trim()
    if (!value) { setError('Enter the category name.'); return }
    void run(`cat-${company.id}`, async () => {
      await api(`/fuel-cost/companies/${company.id}/categories`, {
        method: 'POST', body: body({ category_name: value, remarks: '' }),
      })
      setCategoryNames(current => ({ ...current, [company.id]: '' }))
    }, `“${value}” was added under ${company.company_name}.`)
  }

  const removeCategory = (company: FuelCompany, categoryId: string, categoryName: string) =>
    void run(`cat-remove-${categoryId}`, async () => {
      await api(`/fuel-cost/categories/${categoryId}`, { method: 'DELETE' })
    }, `“${categoryName}” was removed from ${company.company_name}. Recorded consumption is kept.`)

  const restoreCategory = (company: FuelCompany, categoryId: string, categoryName: string) =>
    void run(`cat-restore-${categoryId}`, async () => {
      await api(`/fuel-cost/categories/${categoryId}/restore`, { method: 'POST' })
    }, `“${categoryName}” was restored under ${company.company_name}.`)

  return <PanelDialog
    open={open}
    title="Fuel companies & categories"
    subtitle="Register the companies that draw AGO from the rigs. Companies marked as daily are pre-listed in the consumption dialog; categories split one company's consumption further. Company names can be taken from Master Data vendors."
    onClose={onClose}
    maxWidth="md"
    footer={<Box display="flex" gap={1} alignItems="center" width="100%">
      <Button color="inherit" onClick={() => setShowRemoved(value => !value)} startIcon={<RestoreRounded sx={{ fontSize: 17 }}/>}>
        {showRemoved ? 'Hide removed' : 'Show removed'}
      </Button>
      <Box sx={{ flex: 1 }}/>
      <Button onClick={onClose} color="inherit">Close</Button>
    </Box>}
  >
    <Box display="grid" gap={1.6}>
      {notice && <Tag tone="success">{notice}</Tag>}
      {error && <ErrorMessage message={error}/>}

      {canManage && <Paper variant="outlined" sx={{ p: 1.4, borderRadius: 2 }}>
        <Typography fontWeight={800} fontSize={13} mb={1}>Register a company</Typography>
        <Box display="grid" gap={1} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.3fr 1.2fr auto auto' } }} alignItems="center">
          <TextField size="small" label="Company name" value={name} onChange={event => setName(event.target.value)}
            inputProps={{ maxLength: 200 }} onKeyDown={event => { if (event.key === 'Enter') addCompany() }}/>
          <TextField select size="small" label="Vendor (optional)" value={vendorId}
            onChange={event => {
              setVendorId(event.target.value)
              const vendor = vendors.find(item => item.id === event.target.value)
              if (vendor && !name.trim()) setName(vendor.vendor_name)
            }}>
            <MenuItem value="">Not a vendor</MenuItem>
            {vendors.map(vendor => <MenuItem key={vendor.id} value={vendor.id}>
              {vendor.display_name}{vendor.registered ? ' · registered' : ''}
            </MenuItem>)}
          </TextField>
          <FormControlLabel
            control={<Checkbox checked={isDefault} onChange={event => setIsDefault(event.target.checked)} size="small"/>}
            label={<Typography fontSize={12}>Daily set</Typography>}
          />
          <Button variant="contained" startIcon={<AddRounded/>} onClick={addCompany} disabled={busy === 'new-company'}>
            {busy === 'new-company' ? 'Adding…' : 'Add company'}
          </Button>
        </Box>
      </Paper>}

      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1}>
        <Typography fontWeight={800} fontSize={14}>Registered companies</Typography>
        <Tag>{companies.length} active · {companies.filter(company => company.is_default).length} in the daily set</Tag>
      </Box>

      {!companies.length && <Typography color="text.secondary" fontSize={12.5}>
        No company is registered yet. Add one above (or import a file) to start classifying consumption.
      </Typography>}

      {companies.map(company => <Paper key={company.id} variant="outlined" sx={{ p: 1.3, borderRadius: 2 }}>
        <Box display="flex" alignItems="center" gap={.8} flexWrap="wrap">
          <Typography fontWeight={800} fontSize={13.5}>{company.company_name}</Typography>
          {company.vendor_code && <Tag>{company.vendor_code}</Tag>}
          {company.is_default && <Tag tone="info">Daily set</Tag>}
          <Box sx={{ flex: 1 }}/>
          {canManage && <Tooltip title={company.is_default ? 'Remove from the daily entry set' : 'Add to the daily entry set'}>
            <span><IconButton size="small" aria-label="Toggle daily entry set" disabled={busy === `default-${company.id}`}
              onClick={() => toggleDefault(company)}>
              {company.is_default ? <StarRounded sx={{ fontSize: 18 }} color="primary"/> : <StarOutlineRounded sx={{ fontSize: 18 }}/>}
            </IconButton></span>
          </Tooltip>}
          {canManage && <Tooltip title="Remove this company (recorded consumption is kept)">
            <span><IconButton size="small" color="error" aria-label="Remove fuel company"
              disabled={busy === `remove-${company.id}`} onClick={() => removeCompany(company)}>
              <DeleteOutlineRounded sx={{ fontSize: 17 }}/>
            </IconButton></span>
          </Tooltip>}
        </Box>
        <Box display="flex" gap={.8} flexWrap="wrap" alignItems="center" mt={1}>
          {company.categories.filter(category => !category.is_deleted).map(category => (
            <Box key={category.id} sx={{
              display: 'flex', alignItems: 'center', gap: .3, border: '1px solid', borderColor: 'divider',
              borderRadius: 1.5, pl: 1, pr: .3, py: .2,
            }}>
              <Typography fontSize={11.5}>{category.category_name}</Typography>
              {canManage && <IconButton size="small" aria-label={`Remove ${category.category_name}`}
                disabled={busy === `cat-remove-${category.id}`}
                onClick={() => removeCategory(company, category.id, category.category_name)}>
                <DeleteOutlineRounded sx={{ fontSize: 14 }}/>
              </IconButton>}
            </Box>
          ))}
          {!company.categories.filter(category => !category.is_deleted).length &&
            <Typography fontSize={11.5} color="text.secondary">No categories yet.</Typography>}
          {canManage && <Box display="flex" gap={.6} alignItems="center">
            <TextField size="small" label="New category" value={categoryNames[company.id] ?? ''}
              onChange={event => setCategoryNames(current => ({ ...current, [company.id]: event.target.value }))}
              inputProps={{ maxLength: 120 }}
              onKeyDown={event => { if (event.key === 'Enter') addCategory(company) }}
              sx={{ width: 160 }}/>
            <Button size="small" startIcon={<AddRounded sx={{ fontSize: 16 }}/>}
              onClick={() => addCategory(company)} disabled={busy === `cat-${company.id}`}>Add</Button>
          </Box>}
        </Box>
      </Paper>)}

      {showRemoved && <Box mt={1}>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <Typography fontWeight={800} fontSize={13.5}>Removed companies</Typography>
          {removedLoading && <CircularProgress size={14}/>}
        </Box>
        {!removed.length && !removedLoading && <Typography color="text.secondary" fontSize={12.5}>
          No company has been removed.
        </Typography>}
        {removed.map(company => <Paper key={company.id} variant="outlined" sx={{ p: 1.2, borderRadius: 2, mb: 1 }}>
          <Box display="flex" alignItems="center" gap={.8} flexWrap="wrap">
            <Typography fontWeight={800} fontSize={13}>{company.company_name}</Typography>
            <Tag tone="warning">Removed</Tag>
            {company.categories.filter(category => category.is_deleted).length > 0 && <Tag>
              {company.categories.filter(category => category.is_deleted).length} removed categor{company.categories.filter(category => category.is_deleted).length === 1 ? 'y' : 'ies'}
            </Tag>}
            <Box sx={{ flex: 1 }}/>
            {canManage && <Button size="small" startIcon={<RestoreRounded sx={{ fontSize: 16 }}/>}
              disabled={busy === `restore-${company.id}`} onClick={() => restoreCompany(company)}>
              Restore company
            </Button>}
          </Box>
          <Box display="flex" gap={.8} flexWrap="wrap" mt={.8}>
            {company.categories.filter(category => category.is_deleted).map(category => (
              <Box key={category.id} sx={{
                display: 'flex', alignItems: 'center', gap: .4, border: '1px dashed', borderColor: 'divider',
                borderRadius: 1.5, px: 1, py: .2,
              }}>
                <Typography fontSize={11.5}>{category.category_name}</Typography>
                {canManage && <Button size="small" sx={{ minWidth: 0, py: 0, fontSize: 11 }}
                  disabled={busy === `cat-restore-${category.id}`}
                  onClick={() => restoreCategory(company, category.id, category.category_name)}>
                  Restore
                </Button>}
              </Box>
            ))}
          </Box>
        </Paper>)}
      </Box>}
    </Box>
  </PanelDialog>
}
