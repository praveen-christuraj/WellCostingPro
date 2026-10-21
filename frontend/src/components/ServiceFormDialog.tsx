import { Box, Divider, MenuItem, TextField, Typography } from '@mui/material'
import { ErrorMessage, FormDialog, useFormDirty } from './Common'
import { SERVICE_CATEGORIES, SERVICE_PROVIDER_TYPES, serviceFormToPayload, type ServiceFormState, type ServicePayload } from '../lib/serviceMaster'
import { SERVICE_GROUPS, type ServiceGroup } from '../lib/serviceGroups'
import type { VendorOption } from '../lib/vendorMaster'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <Typography fontSize={11} fontWeight={800} letterSpacing={1.1} color="text.secondary" textTransform="uppercase">{children}</Typography>
}

// Both provider types require a workspace vendor; codes are entered manually.
export function ServiceFormDialog({ open, title, subtitle, form, setForm, vendors, busy, error, onClose, onSubmit }: {
  open: boolean
  title: string
  subtitle: string
  form: ServiceFormState
  setForm: (patch: Partial<ServiceFormState>) => void
  vendors: VendorOption[]
  busy: boolean
  error: string
  onClose: () => void
  onSubmit: (payload: ServicePayload) => void
}) {
  const hasCurrentVendorOption = vendors.some(vendor => vendor.id === form.vendor_id)
  const dirty = useFormDirty(form, open)

  return <FormDialog
    open={open}
    title={title}
    subtitle={subtitle}
    onClose={onClose}
    onSubmit={() => onSubmit(serviceFormToPayload(form))}
    busy={busy}
    dirty={dirty}
    submitDisabled={!form.service_group}
    submitLabel={title.startsWith('Edit') ? 'Save changes' : 'Create service'}
  >
    <Box display="grid" gap={2} pt={.5}>
      <SectionTitle>Service details</SectionTitle>
      <TextField
        label="Service code"
        value={form.service_code}
        required
        onChange={event => setForm({ service_code: event.target.value })}
        inputProps={{ maxLength: 50 }}
        fullWidth
        helperText="Enter a code unique in this workspace. Codes are upper-cased."
      />
      <TextField
        label="Service name"
        required
        fullWidth
        value={form.service_name}
        onChange={event => setForm({ service_name: event.target.value })}
        inputProps={{ maxLength: 200 }}
      />
      <TextField
        select
        label="Service group"
        required
        fullWidth
        value={form.service_group}
        error={!form.service_group}
        onChange={event => setForm({ service_group: event.target.value as ServiceGroup })}
        helperText="Report group: AFE and Daily Cost reports list services in this order — Rig Operations, Formation Evaluation, Well Services, Land Facilities and Preparation, Miscellaneous Services, Supervisions."
      >
        {SERVICE_GROUPS.map(group => <MenuItem key={group} value={group}>{group}</MenuItem>)}
      </TextField>
      <Box display="grid" gap={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }}>
        <TextField
          select
          label="Service category"
          required
          fullWidth
          value={form.service_category}
          onChange={event => setForm({ service_category: event.target.value as ServiceFormState['service_category'] })}
          helperText="Choose the drilling or completion service catalogue."
        >
          {SERVICE_CATEGORIES.map(category => <MenuItem key={category} value={category}>{category}</MenuItem>)}
        </TextField>
        <TextField
          select
          label="Provider type"
          required
          fullWidth
          value={form.provider_type}
          onChange={event => {
            const providerType = event.target.value as ServiceFormState['provider_type']
            setForm({ provider_type: providerType })
          }}
          helperText="Set whether the service is delivered in house or by a third party."
        >
          {SERVICE_PROVIDER_TYPES.map(providerType => <MenuItem key={providerType} value={providerType}>{providerType}</MenuItem>)}
        </TextField>
      </Box>

      <Divider/>
      <SectionTitle>Service provider</SectionTitle>
      <TextField
        select
        label="Vendor / service provider"
        required
        fullWidth
        value={form.vendor_id}
        disabled={busy}
        error={!form.vendor_id}
        onChange={event => setForm({ vendor_id: event.target.value })}
        helperText="Required for both in-house and third-party services so costs can be attributed to a vendor."
      >
        <MenuItem value="">Select a vendor</MenuItem>
        {form.vendor_id && !hasCurrentVendorOption && <MenuItem value={form.vendor_id} disabled>Previously linked vendor — restore or replace it</MenuItem>}
        {vendors.map(vendor => <MenuItem key={vendor.id} value={vendor.id}>
          {vendor.label} · {vendor.vendor_type}{vendor.status !== 'active' ? ` · ${vendor.status}` : ''}
        </MenuItem>)}
      </TextField>
      <TextField
        label="Description"
        fullWidth
        multiline
        minRows={3}
        value={form.description}
        onChange={event => setForm({ description: event.target.value })}
        helperText="Scope, service notes, or internal guidance."
        inputProps={{ maxLength: 500 }}
      />
      <ErrorMessage message={error}/>
    </Box>
  </FormDialog>
}
