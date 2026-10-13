import { Autocomplete, Box, TextField, Typography, type AutocompleteRenderInputParams } from '@mui/material'
import { amountText, type AfeReference } from '../../lib/afe'

type Service = AfeReference['services'][number]
type Tangible = AfeReference['tangibles'][number]
type DrillBit = AfeReference['drill_bits'][number]

// Every whitespace-separated word in the query must appear in one of the fields (case-insensitive).
export function matchesKeywords(query: string, fields: (string | null | undefined)[]): boolean {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const haystack = fields.filter(Boolean).join(' ').toLowerCase()
  return words.every(word => haystack.includes(word))
}

export const keywordFilter = <T,>(fields: (option: T) => (string | null | undefined)[]) =>
  (options: T[], state: { inputValue: string }) => options.filter(option => matchesKeywords(state.inputValue, fields(option)))

export function ServicePicker({ value, options, onChange, error, helperText }: {
  value: string
  options: Service[]
  onChange: (id: string) => void
  error?: boolean
  helperText?: string
}) {
  const selected = options.find(option => option.id === value) ?? null
  return <Autocomplete<Service, false, false, false>
    options={options}
    value={selected}
    onChange={(_event, next) => onChange(next?.id ?? '')}
    getOptionLabel={option => `${option.service_code} · ${option.service_name}`}
    filterOptions={keywordFilter(option => [option.service_code, option.service_name, option.service_category, option.provider_type, option.vendor_name, option.description])}
    isOptionEqualToValue={(option, current) => option.id === current.id}
    renderOption={(props, option) => <li {...props} key={option.id}>
      <Box>
        <Typography fontSize={13} fontWeight={700}>{option.service_code} · {option.service_name}</Typography>
        <Typography fontSize={11.5} color="text.secondary">{option.service_category} · {option.provider_type} · {option.vendor_name || 'No vendor'}</Typography>
      </Box>
    </li>}
    renderInput={(params: AutocompleteRenderInputParams) => <TextField {...params} label="Service" required error={error} helperText={helperText ?? 'Search by code, name, category, provider or vendor.'}/>}
    noOptionsText="No services match. Add services in Master Data → Services."
    fullWidth
  />
}

export function TangiblePicker({ value, options, onChange, error, helperText }: {
  value: string
  options: Tangible[]
  onChange: (id: string) => void
  error?: boolean
  helperText?: string
}) {
  const selected = options.find(option => option.id === value) ?? null
  return <Autocomplete<Tangible, false, false, false>
    options={options}
    value={selected}
    onChange={(_event, next) => onChange(next?.id ?? '')}
    getOptionLabel={option => `${option.tangible_code} · ${option.tangible_name}`}
    filterOptions={keywordFilter(option => [option.tangible_code, option.tangible_name, option.manufacturer_name, option.description, option.category_name, option.subcategory_name, option.scope])}
    isOptionEqualToValue={(option, current) => option.id === current.id}
    renderOption={(props, option) => <li {...props} key={option.id}>
      <Box minWidth={0}>
        <Typography fontSize={13} fontWeight={700}>{option.tangible_code} · {option.tangible_name}</Typography>
        <Typography fontSize={11.5} color="text.secondary" noWrap>{option.manufacturer_name || 'No manufacturer'} · {option.description || 'No description'}</Typography>
      </Box>
    </li>}
    renderInput={(params: AutocompleteRenderInputParams) => <TextField {...params} label="Tangible" required error={error} helperText={helperText ?? 'Search by code, name, manufacturer, description or category.'}/>}
    noOptionsText="No tangibles match. Add tangibles in Master Data → Tangibles."
    fullWidth
  />
}

export function DrillBitPicker({ value, options, onChange, error, helperText }: {
  value: string
  options: DrillBit[]
  onChange: (id: string) => void
  error?: boolean
  helperText?: string
}) {
  const selected = options.find(option => option.id === value) ?? null
  return <Autocomplete<DrillBit, false, false, false>
    options={options}
    value={selected}
    onChange={(_event, next) => onChange(next?.id ?? '')}
    getOptionLabel={option => `${option.bit_code} · ${option.bit_name}`}
    filterOptions={keywordFilter(option => [option.bit_code, option.bit_name, option.bit_type, option.manufacturer_name, option.model_no, option.size, option.iadc_code, option.serial_number, option.description, option.currency, option.captured_rate])}
    isOptionEqualToValue={(option, current) => option.id === current.id}
    renderOption={(props, option) => <li {...props} key={option.id}>
      <Box minWidth={0} flex={1} display="flex" alignItems="center" gap={1.5} justifyContent="space-between">
        <Box minWidth={0}>
          <Typography fontSize={13} fontWeight={700} noWrap>{option.bit_code} · {option.bit_name}</Typography>
          <Typography fontSize={11.5} color="text.secondary" noWrap>{option.manufacturer_name || 'No make'} · {option.bit_type} · {option.size} · {option.description || 'No description'}</Typography>
        </Box>
        {/* Final cost from the drill bit's master record (revised rate with uplift when present,
            otherwise the unit rate) — visible right in the dropdown, so no opening is needed to compare prices. */}
        <Box flex="none" textAlign="right">
          <Typography fontSize={12.5} fontWeight={800}>{amountText(option.captured_rate, option.currency)}</Typography>
          <Typography fontSize={10} color="text.secondary">final cost</Typography>
        </Box>
      </Box>
    </li>}
    renderInput={(params: AutocompleteRenderInputParams) => <TextField {...params} label="Drill bit" required error={error}
      helperText={helperText ?? (selected
        ? `Search by code, make, type, size, IADC or serial. Final cost ${amountText(selected.captured_rate, selected.currency)}.`
        : 'Search by code, make, type, size, IADC or serial. Each option shows its final cost.')}/>}
    noOptionsText="No drill bits match. Add drill bits in Master Data → Consumables."
    fullWidth
  />
}

// A read-only panel of facts about the chosen master record, so the user can confirm the right item.
export function FactPanel({ rows }: { rows: { label: string; value: string }[] }) {
  return <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1.5, p: 1.5, bgcolor: 'action.hover' }}>
    <Box display="grid" gap={.9} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
      {rows.map(row => <Box key={row.label} minWidth={0}>
        <Typography fontSize={10.5} fontWeight={800} color="text.secondary" textTransform="uppercase" letterSpacing={.6}>{row.label}</Typography>
        <Typography fontSize={12.5} sx={{ overflowWrap: 'anywhere' }}>{row.value || '—'}</Typography>
      </Box>)}
    </Box>
  </Box>
}
