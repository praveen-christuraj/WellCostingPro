import { useEffect, useState } from 'react'
import { Autocomplete, TextField } from '@mui/material'
import { api } from '../../lib/api'
import type { MasterDataRecord } from '../../lib/masterData'

// Picks an existing Unit of Measure or Currency from Master Data. Values are not created here.
export function MasterSelect({ label, source, value, onChange, required = false, helper, onError }: {
  label: string
  source: 'uom' | 'currencies'
  value: string
  onChange: (code: string) => void
  required?: boolean
  helper?: string
  onError?: (message: string) => void
}) {
  const [codes, setCodes] = useState<MasterDataRecord[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    api<MasterDataRecord[]>(`/master-data/${source}`)
      .then(setCodes)
      .catch(caught => onError?.(caught instanceof Error ? caught.message : `Could not load ${label}`))
      .finally(() => setLoading(false))
  }, [source]) // eslint-disable-line react-hooks/exhaustive-deps

  const options = codes.map(record => record.code)
  // Keep a stored value visible even if its master record was later removed.
  const current = value && !options.includes(value) ? [...options, value] : options

  return <Autocomplete<string, false, false, true>
    options={current}
    value={value || null}
    onChange={(_event, next) => onChange(next ?? '')}
    loading={loading}
    fullWidth
    freeSolo
    renderInput={params => <TextField {...params} label={label} required={required} helperText={helper ?? (source === 'uom' ? 'From Master Data → UOM.' : 'From Master Data → Currency.')}/>}
  />
}
