import { Link as RouterLink } from 'react-router-dom'
import { ListAltOutlined } from '@mui/icons-material'
import { Button } from '@mui/material'
import { CatalogueItemRegister } from '../components/catalogue/CatalogueItemRegister'
import { PageHeading } from '../components/Common'
import { MasterDataTabs } from '../components/MasterDataTabs'
import { TANGIBLE_CONFIG } from '../lib/catalogue'

export default function Tangibles() {
  return <>
    <PageHeading
      eyebrow="MASTER DATA MANAGEMENT / TANGIBLES"
      title="Tangibles"
      subtitle="Tangible equipment and materials with their category, subcategory, make and unit rate. Every rate change is kept in the price history."
      action={<Button component={RouterLink} to="/master-data/catalogue-lists" variant="outlined" startIcon={<ListAltOutlined/>}>Manage lists</Button>}
    />
    <MasterDataTabs active="tangibles"/>
    <CatalogueItemRegister key={TANGIBLE_CONFIG.key} config={TANGIBLE_CONFIG}/>
  </>
}
