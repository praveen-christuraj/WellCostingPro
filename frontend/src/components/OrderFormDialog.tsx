import { Alert, Box, Checkbox, Divider, FormControlLabel, MenuItem, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog } from './Common'
import {
  ORDER_STATUSES,
  ORDER_TYPES,
  orderFormToAmendment,
  orderFormToPayload,
  vendorStatusLabel,
  type AmendmentPayload,
  type OrderFormState,
  type OrderPayload,
  type PoSoOrder,
  type VendorOption,
} from '../lib/vendorMaster'

function SectionTitle({ children }: { children: string }) {
  return <Typography fontSize={11} fontWeight={800} letterSpacing={1.1} color="text.secondary" textTransform="uppercase">{children}</Typography>
}

// Create, edit or amend a PO/SO order. Values and prices are deliberately absent:
// the scanned copy attached to the order is the record the team refers back to.
export function OrderFormDialog({ open, mode, order, vendors, form, setForm, busy, error, onClose, onSubmit }: {
  open: boolean
  mode: 'create' | 'edit' | 'amend'
  order: PoSoOrder | null
  vendors: VendorOption[]
  form: OrderFormState
  setForm: (patch: Partial<OrderFormState>) => void
  busy: boolean
  error: string
  onClose: () => void
  onSubmit: (payload: OrderPayload | AmendmentPayload) => void
}) {
  const selectedVendor = vendors.find(vendor => vendor.id === form.vendor_id)
  const nextRevision = order ? order.revision_count : 0
  const submit = () => onSubmit(mode === 'amend' ? orderFormToAmendment(form) : orderFormToPayload(form))

  return <FormDialog
    open={open}
    title={mode === 'create' ? 'Add PO/SO order' : mode === 'edit' ? `Edit ${order?.order_number ?? ''} (Rev ${order?.revision_number ?? 0})` : `Amend ${order?.order_number ?? ''}`}
    subtitle={mode === 'amend'
      ? `Raises revision ${nextRevision} of this order and marks it as the one to quote.`
      : 'Attach the scanned PO/SO copy after saving; no prices or values are stored here.'}
    onClose={onClose}
    onSubmit={submit}
    busy={busy}
    submitLabel={mode === 'create' ? 'Create order' : mode === 'edit' ? 'Save changes' : `Create revision ${nextRevision}`}
  >
    <Box display="grid" gap={2} pt={.5}>
      {mode === 'amend' && order && <Alert severity="info" icon={false} sx={{ fontSize: 12.5 }}>
        Source: <strong>{order.order_type} {order.order_number}</strong> · revision {order.revision_number} · {order.vendor_code} — {order.vendor_name}
        {order.document_count ? ` · ${order.document_count} file(s) attached` : ''}
      </Alert>}

      <SectionTitle>Order</SectionTitle>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 130px' }}>
        <TextField
          label="PO/SO number"
          required
          fullWidth
          disabled={mode === 'amend'}
          value={form.order_number}
          onChange={event => setForm({ order_number: event.target.value })}
          helperText={mode === 'edit' && order && order.revision_count > 1 ? 'Renaming updates every revision of this order' : 'Upper-cased, unique per revision in this workspace'}
          inputProps={{ maxLength: 100 }}
        />
        <TextField select label="Type" required fullWidth value={form.order_type} onChange={event => setForm({ order_type: event.target.value as OrderFormState['order_type'] })}>
          {ORDER_TYPES.map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}
        </TextField>
      </Box>
      <TextField
        select
        label="Vendor / supplier"
        required
        fullWidth
        disabled={mode === 'amend' || (mode === 'edit' && !!order && order.revision_count > 1)}
        value={form.vendor_id}
        onChange={event => setForm({ vendor_id: event.target.value })}
        helperText={mode === 'amend' || (mode === 'edit' && !!order && order.revision_count > 1)
          ? 'The vendor of an amendment chain cannot change'
          : selectedVendor && selectedVendor.status !== 'active' ? `This vendor is ${vendorStatusLabel(selectedVendor.status)}` : 'Blocked vendors are refused by the API'}
      >
        {vendors.map(vendor => <MenuItem key={vendor.id} value={vendor.id} disabled={vendor.status === 'blocked'}>
          {vendor.label}{vendor.status === 'blocked' ? ' (blocked)' : ''}
        </MenuItem>)}
      </TextField>

      <Divider/>
      <SectionTitle>Dates and status</SectionTitle>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr 1fr' }}>
        <TextField label="Issue date" type="date" fullWidth value={form.issue_date} onChange={event => setForm({ issue_date: event.target.value })} InputLabelProps={{ shrink: true }}/>
        <TextField label="Expiry / valid until" type="date" fullWidth value={form.expiry_date} onChange={event => setForm({ expiry_date: event.target.value })} InputLabelProps={{ shrink: true }}/>
        <TextField select label="Status" required fullWidth value={form.status} onChange={event => setForm({ status: event.target.value as OrderFormState['status'] })}>
          {ORDER_STATUSES.map(status => <MenuItem key={status.value} value={status.value}>{status.label}</MenuItem>)}
        </TextField>
      </Box>
      <TextField label="Scope / description" fullWidth multiline minRows={2} value={form.description} onChange={event => setForm({ description: event.target.value })} helperText="Short reference only; the attached copy carries the detail" inputProps={{ maxLength: 500 }}/>

      {mode === 'amend' && <>
        <Divider/>
        <SectionTitle>Amendment</SectionTitle>
        <TextField
          label="Reason for this revision"
          required
          fullWidth
          multiline
          minRows={2}
          value={form.revision_note}
          onChange={event => setForm({ revision_note: event.target.value })}
          helperText="Recorded on the audit trail and shown in the revision history"
          inputProps={{ maxLength: 500 }}
        />
        <FormControlLabel
          control={<Checkbox checked={form.copy_documents} onChange={event => setForm({ copy_documents: event.target.checked })}/>}
          label={<Typography fontSize={13}>Carry the files from revision {order?.revision_number ?? 0} into this amendment</Typography>}
        />
      </>}
      <ErrorMessage message={error}/>
    </Box>
  </FormDialog>
}
