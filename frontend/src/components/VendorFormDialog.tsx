import { Box, Divider, MenuItem, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog } from './Common'
import {
  VENDOR_CATEGORIES,
  VENDOR_TYPES,
  VENDOR_STATUSES,
  vendorFormToPayload,
  type VendorFormState,
  type VendorPayload,
} from '../lib/vendorMaster'

function SectionTitle({ children }: { children: string }) {
  return <Typography fontSize={11} fontWeight={800} letterSpacing={1.1} color="text.secondary" textTransform="uppercase">{children}</Typography>
}

// Create/edit a vendor. The parent page owns the field state so the same form can
// serve the Vendors tab and the Deleted Entries view. Codes are upper-cased by the
// API and unique per workspace; a blocked vendor cannot receive new PO/SO orders.
export function VendorFormDialog({ open, title, subtitle, form, setForm, busy, error, onClose, onSubmit }: {
  open: boolean
  title: string
  subtitle: string
  form: VendorFormState
  setForm: (patch: Partial<VendorFormState>) => void
  busy: boolean
  error: string
  onClose: () => void
  onSubmit: (payload: VendorPayload) => void
}) {
  return <FormDialog
    open={open}
    title={title}
    subtitle={subtitle}
    onClose={onClose}
    onSubmit={() => onSubmit(vendorFormToPayload(form))}
    busy={busy}
    submitLabel={title.startsWith('Edit') ? 'Save changes' : 'Create vendor'}
  >
    <Box display="grid" gap={2} pt={.5}>
      <SectionTitle>Identification</SectionTitle>
      <TextField select label="Vendor type" required fullWidth value={form.vendor_type} onChange={event => setForm({ vendor_type: event.target.value as VendorFormState['vendor_type'] })}>
        {VENDOR_TYPES.map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}
      </TextField>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1.6fr' }}>
        <TextField label="Vendor code" required fullWidth value={form.vendor_code} onChange={event => setForm({ vendor_code: event.target.value })} helperText="Upper-cased, unique in this workspace" inputProps={{ maxLength: 50 }}/>
        <TextField label="Vendor / supplier name" required fullWidth value={form.vendor_name} onChange={event => setForm({ vendor_name: event.target.value })} inputProps={{ maxLength: 200 }}/>
      </Box>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
        <TextField select label="Category" fullWidth value={form.category} onChange={event => setForm({ category: event.target.value })} helperText="Choose the vendor's primary service or supply category.">
          <MenuItem value="">Not categorized</MenuItem>
          {VENDOR_CATEGORIES.map(category => <MenuItem key={category} value={category}>{category}</MenuItem>)}
        </TextField>
        <TextField select label="Status" required fullWidth value={form.status} onChange={event => setForm({ status: event.target.value as VendorFormState['status'] })} helperText={VENDOR_STATUSES.find(item => item.value === form.status)?.hint}>
          {VENDOR_STATUSES.map(status => <MenuItem key={status.value} value={status.value}>{status.label}</MenuItem>)}
        </TextField>
      </Box>

      <Divider/>
      <SectionTitle>Contact</SectionTitle>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
        <TextField label="Contact person" fullWidth value={form.contact_person} onChange={event => setForm({ contact_person: event.target.value })} inputProps={{ maxLength: 150 }}/>
        <TextField label="Phone" fullWidth value={form.phone} onChange={event => setForm({ phone: event.target.value })} inputProps={{ maxLength: 60 }}/>
        <TextField label="E-mail" fullWidth value={form.email} onChange={event => setForm({ email: event.target.value })} inputProps={{ maxLength: 255 }}/>
        <TextField label="Website" fullWidth value={form.website} onChange={event => setForm({ website: event.target.value })} helperText="Optional" inputProps={{ maxLength: 255 }}/>
      </Box>

      <Divider/>
      <SectionTitle>Business details</SectionTitle>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
        <TextField label="Country" fullWidth value={form.country} onChange={event => setForm({ country: event.target.value })} inputProps={{ maxLength: 100 }}/>
        <TextField label="Tax / registration no." fullWidth value={form.tax_registration_no} onChange={event => setForm({ tax_registration_no: event.target.value })} inputProps={{ maxLength: 60 }}/>
        <TextField label="Credit terms (days)" type="number" fullWidth value={form.credit_terms_days} onChange={event => setForm({ credit_terms_days: event.target.value })} inputProps={{ min: 0, max: 365 }}/>
        <TextField label="Address" fullWidth multiline minRows={2} value={form.address} onChange={event => setForm({ address: event.target.value })} inputProps={{ maxLength: 500 }}/>
      </Box>
      <TextField label="Description" fullWidth multiline minRows={2} value={form.description} onChange={event => setForm({ description: event.target.value })} helperText="Scope of supply, notes for the team" inputProps={{ maxLength: 500 }}/>
      <ErrorMessage message={error}/>
    </Box>
  </FormDialog>
}
