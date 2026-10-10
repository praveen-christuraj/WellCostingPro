import { useNavigate } from 'react-router-dom'
import { Tab, Tabs } from '@mui/material'
import { MASTER_DATA_MODULES } from '../lib/masterData'

// One tab strip for the whole Master Data Management module. The five reference
// lists share /master-data/records; Vendors and PO/SO Orders have their own pages
// because they carry relationships, revisions and attachments.
export const MASTER_DATA_TABS = [
  ...MASTER_DATA_MODULES.map(module => ({ key: module.key, label: module.label, path: `/master-data/records?module=${module.key}` })),
  { key: 'vendors', label: 'Vendors', path: '/master-data/vendors' },
  { key: 'po-so-orders', label: 'PO/SO Orders', path: '/master-data/po-so-orders' },
] as const

export function MasterDataTabs({ active }: { active: string }) {
  const navigate = useNavigate()
  const select = (_event: React.SyntheticEvent, key: string) => {
    const tab = MASTER_DATA_TABS.find(item => item.key === key)
    if (tab) navigate(tab.path, { replace: true })
  }
  return <Tabs
    value={active}
    onChange={select}
    variant="scrollable"
    scrollButtons="auto"
    allowScrollButtonsMobile
    aria-label="Master data types"
    sx={{ px: { xs: 1, sm: 2 }, borderBottom: '1px solid', borderColor: 'divider' }}
  >
    {MASTER_DATA_TABS.map(tab => <Tab key={tab.key} value={tab.key} label={tab.label}/>)}
  </Tabs>
}
