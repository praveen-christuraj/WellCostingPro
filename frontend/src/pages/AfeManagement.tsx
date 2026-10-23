import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { DashboardOutlined } from '@mui/icons-material'
import { Box, Button, Tab, Tabs, Typography } from '@mui/material'
import { ErrorMessage, PageHeading } from '../components/Common'
import { AfeRegisterTab } from '../components/afe/AfeRegisterTab'
import { AfeScopeList } from '../components/afe/AfeScopeList'
import { AfeEstimationTab } from '../components/afe/AfeEstimationTab'
import { AfeDeletedTab } from '../components/afe/AfeDeletedTab'
import { api } from '../lib/api'
import type { Afe, AfeReference } from '../lib/afe'

const TABS = [
  { key: 'afe', label: 'AFE' },
  { key: 'estimation', label: 'AFE Cost Estimation' },
  { key: 'final_review', label: 'Wells for final review' },
  { key: 'completed', label: 'Completed Wells' },
  { key: 'deleted', label: 'Deleted entries' },
] as const

type TabKey = typeof TABS[number]['key']

// The AFE register, cost estimation approvals, the well-scope views and deleted
// entries share one page. The active tab lives in the URL (?tab=) so links and
// reloads return to the same view. An AFE appears on the "Wells for final review"
// or "Completed Wells" tab according to its well's scope lifecycle state
// (drilling AFE follows the drilling scope, completion AFE the completion scope),
// so a well can show on both tabs with different scopes.
export default function AfeManagement() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const active: TabKey = TABS.some(tab => tab.key === requested) ? (requested as TabKey) : 'afe'
  const [rows, setRows] = useState<Afe[]>([])
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

  const load = useCallback(async () => {
    try {
      setRows(await api<Afe[]>('/afe/afes'))
    } catch (caught) {
      setReferenceError(caught instanceof Error ? caught.message : 'AFE register could not be loaded')
    }
  }, [])

  useEffect(() => { void loadReference(); void load() }, [loadReference, load])

  const wellsById = useMemo(() => Object.fromEntries((reference?.wells ?? []).map(well => [well.id, well])), [reference])
  const scopeConfigStatus = (well: AfeReference['wells'][number], scope: 'drilling' | 'completion') =>
    scope === 'completion' ? well.completion_config_status : well.config_status

  const finalReviewRows = useMemo(() => rows.filter(afe => {
    const well = wellsById[afe.well_id]
    if (!well) return false
    return afe.well_status === 'active' && scopeConfigStatus(well, afe.configuration_scope) === 'final_review'
  }), [rows, wellsById])

  const completedRows = useMemo(() => rows.filter(afe => afe.well_status === 'completed'), [rows])

  return <>
    <PageHeading
      eyebrow="AFE MANAGEMENT / REGISTER AND ESTIMATES"
      title="AFE Management"
      subtitle="Create well-scoped AFEs, price them against the well plan, and move them through review and approval. AFEs surface on the final-review and completed tabs according to their well's scope lifecycle state."
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
      {active === 'final_review' && <>
        <Box sx={{ mb: 1 }}>
          <Typography fontWeight={800} fontSize={15}>Wells for final review</Typography>
          <Typography color="text.secondary" fontSize={12}>
            {finalReviewRows.length} AFE{finalReviewRows.length === 1 ? '' : 's'} whose well scope is marked for final review
          </Typography>
        </Box>
        <AfeScopeList afees={finalReviewRows} exportName="afes-final-review"/>
      </>}
      {active === 'completed' && <>
        <Box sx={{ mb: 1 }}>
          <Typography fontWeight={800} fontSize={15}>Completed Wells</Typography>
          <Typography color="text.secondary" fontSize={12}>
            {completedRows.length} AFE{completedRows.length === 1 ? '' : 's'} whose well scope is completed
          </Typography>
        </Box>
        <AfeScopeList afees={completedRows} exportName="afes-completed"/>
      </>}
      {active === 'deleted' && <AfeDeletedTab/>}
    </Box>
  </>
}
