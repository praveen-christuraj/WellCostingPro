import { useCallback, useEffect, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { DashboardOutlined } from '@mui/icons-material'
import { Box, Button, Tab, Tabs } from '@mui/material'
import { ErrorMessage, PageHeading } from '../components/Common'
import { AfeRegisterTab } from '../components/afe/AfeRegisterTab'
import { AfeEstimationTab } from '../components/afe/AfeEstimationTab'
import { AfeDeletedTab } from '../components/afe/AfeDeletedTab'
import { api } from '../lib/api'
import type { AfeReference } from '../lib/afe'

const TABS = [
  { key: 'afe', label: 'AFE' },
  { key: 'estimation', label: 'AFE Cost Estimation' },
  { key: 'deleted', label: 'Deleted entries' },
] as const

type TabKey = typeof TABS[number]['key']

// The AFE register, cost estimation approvals and deleted entries share one page.
// The active tab lives in the URL (?tab=) so links and reloads return to the same view.
export default function AfeManagement() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const active: TabKey = TABS.some(tab => tab.key === requested) ? (requested as TabKey) : 'afe'
  const [reference, setReference] = useState<AfeReference | null>(null)
  const [referenceError, setReferenceError] = useState('')

  const loadReference = useCallback(async () => {
    try {
      setReference(await api<AfeReference>('/afe/reference'))
      setReferenceError('')
    } catch (caught) {
      setReferenceError(caught instanceof Error ? caught.message : 'Rig, well and master data references could not be loaded')
    }
  }, [])

  useEffect(() => { void loadReference() }, [loadReference])

  return <>
    <PageHeading
      eyebrow="AFE MANAGEMENT / REGISTER AND ESTIMATES"
      title="AFE Management"
      subtitle="Create well-scoped AFEs, price them against the well plan, and move them through review and approval."
      action={<Button component={RouterLink} to="/afe" variant="outlined" startIcon={<DashboardOutlined/>}>Overview</Button>}
    />
    <ErrorMessage message={referenceError}/>
    <Box borderBottom={1} borderColor="divider" mb={2}>
      <Tabs value={active} onChange={(_event, value: TabKey) => setParams(value === 'afe' ? {} : { tab: value })} aria-label="AFE sections">
        {TABS.map(tab => <Tab key={tab.key} value={tab.key} label={tab.label} id={`afe-tab-${tab.key}`} aria-controls={`afe-panel-${tab.key}`}/>)}
      </Tabs>
    </Box>
    <Box role="tabpanel" id={`afe-panel-${active}`} aria-labelledby={`afe-tab-${active}`}>
      {active === 'afe' && <AfeRegisterTab reference={reference} onReferenceChanged={() => void loadReference()}/>}
      {active === 'estimation' && <AfeEstimationTab/>}
      {active === 'deleted' && <AfeDeletedTab/>}
    </Box>
  </>
}
