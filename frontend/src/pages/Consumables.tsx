import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { ListAltOutlined } from '@mui/icons-material'
import { Box, Button, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { CatalogueItemRegister } from '../components/catalogue/CatalogueItemRegister'
import { FuelRegister } from '../components/catalogue/FuelRegister'
import { PageHeading } from '../components/Common'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { CONSUMABLE_TYPES, type CatalogueTypeKey, type TypeConfig } from '../lib/catalogue'

const DEFAULT_TYPE: CatalogueTypeKey = 'mud-chemicals'

const HINTS: Record<string, string> = {
  'mud-chemicals': 'Drilling fluid chemicals by group, with unit rates and price history.',
  'cement-additives': 'Cement additives by type, with unit rates and price history.',
  'fuel-types': 'Fuel prices per litre. Update a price only when it changes.',
  'drill-bits': 'Drill bits by type, make and size, with unit rates and price history.',
}

// Consumable types are a single toggle group driven by ?type=, so each type has a stable,
// shareable address and the page header stays put while the register changes.
export default function Consumables() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('type')
  const config: TypeConfig = CONSUMABLE_TYPES.find(item => item.key === requested) ?? CONSUMABLE_TYPES.find(item => item.key === DEFAULT_TYPE)!

  const choose = (key: string | null) => {
    if (!key) return
    setParams({ type: key }, { replace: true })
  }

  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / CONSUMABLES"
      title="Consumables"
      subtitle="Mud chemicals, cement additives, fuel and drill bits. Choose a type below."
      action={<Button component={RouterLink} to="/master-data/catalogue-lists" variant="outlined" startIcon={<ListAltOutlined/>}>Manage lists</Button>}
    />
    <MasterDataTabs active="consumables"/>

    <Box display="flex" justifyContent="space-between" alignItems="center" gap={2} flexWrap="wrap" mt={2.5} mb={2}>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={config.key}
        onChange={(_event, key) => choose(key)}
        aria-label="Consumable type"
      >
        {CONSUMABLE_TYPES.map(item => <ToggleButton key={item.key} value={item.key} sx={{ px: 2, textTransform: 'none', fontWeight: 700 }}>{item.label}</ToggleButton>)}
      </ToggleButtonGroup>
      <Typography color="text.secondary" fontSize={12.5}>{HINTS[config.key]}</Typography>
    </Box>

    {config.key === 'fuel-types'
      ? <FuelRegister key="fuel-types"/>
      : <CatalogueItemRegister key={config.key} config={config}/>}
  </>
}
