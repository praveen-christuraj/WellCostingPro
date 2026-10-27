import type { ReactNode } from 'react'
import { Alert, Box, Paper, Typography } from '@mui/material'
import { radius, space } from '../../designSystem'
import { dailyMoney } from '../../lib/dailyCost'
import {
  mudQuantity,
  type MudCostBalanceRow, type MudCostMaterialBalance, type MudCostReconciliation,
  type MudCostReconciliationSection, type MudCostSectionOption, type MudCostSectionSetting,
} from '../../lib/mudCost'

export type MudCostKpiSnapshot = {
  rigId: string
  wellId: string
  balance: MudCostMaterialBalance | null
  reconciliation: MudCostReconciliation | null
  balanceError: string
  reconciliationError: string
}

type SectionLabel = Pick<MudCostSectionOption, 'section_code' | 'section_name' | 'display_name' | 'scope' | 'is_current'>

type SectionKpi = {
  section: MudCostSectionOption
  balance: MudCostBalanceRow | undefined
  reconciliation: MudCostReconciliationSection | undefined
  mudLabel: string
  sharedRate: boolean
}

const sectionKey = (scope: string, holeSectionId: string) => `${scope}:${holeSectionId}`
const sectionName = (section: SectionLabel) =>
  [section.section_code, section.section_name].filter(Boolean).join(' · ') || section.display_name
const sectionContext = (section: SectionLabel) =>
  `${section.scope === 'completion' ? 'Completion' : 'Drilling'}${section.is_current ? '' : ' · Historical'}`

function KpiCard({ children, label }: { children: ReactNode; label: string }) {
  return <Paper component="section" aria-label={label} className="stat-card" variant="outlined"
    sx={{ p: `${space[4]}px`, borderRadius: `${radius.lg}px`, minWidth: 0 }}>
    {children}
  </Paper>
}

function Metric({ label, value }: { label: string; value: string }) {
  return <Box component="div" sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 1 }}>
    <Typography component="dt" color="text.secondary" fontSize={12.5}>{label}</Typography>
    <Typography component="dd" fontSize={13} fontWeight={800} sx={{ m: 0, textAlign: 'right', fontVariantNumeric: 'tabular-nums', overflowWrap: 'anywhere' }}>{value}</Typography>
  </Box>
}

function SectionValue({ section, value }: { section: SectionLabel; value: string }) {
  return <Box component="div" sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 1 }}>
    <Box component="dt" sx={{ minWidth: 0 }}>
      <Typography fontSize={12.5} fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>{sectionName(section)}</Typography>
      <Typography color="text.secondary" fontSize={11.5}>{sectionContext(section)}</Typography>
    </Box>
    <Typography component="dd" fontSize={13} fontWeight={800} sx={{ m: 0, textAlign: 'right', fontVariantNumeric: 'tabular-nums', overflowWrap: 'anywhere' }}>{value}</Typography>
  </Box>
}

/**
 * A well-wide snapshot, deliberately independent of the three register tabs'
 * section/date filters. Balance quantities come from the server's inception
 * aggregation; reconciliation supplies the same pricing figures as the report.
 */
export function MudCostKpis({ sections, settings, snapshot, loading }: {
  sections: MudCostSectionOption[]
  settings: MudCostSectionSetting[]
  snapshot: MudCostKpiSnapshot | null
  loading: boolean
}) {
  const balances = new Map((snapshot?.balance?.rows ?? []).map(row => [row.section_id, row]))
  // Reconciliation groups by scope + hole-section rather than a historical
  // well-section snapshot ID. Show that rate for every corresponding snapshot,
  // but never present its combined totals as one snapshot's material balance.
  const reconciliations = new Map((snapshot?.reconciliation?.sections ?? []).map(row => [sectionKey(row.section_scope, row.hole_section_id), row]))
  const settingBySection = new Map(settings.map(row => [sectionKey(row.section_scope, row.hole_section_id), row]))
  const snapshotCounts = new Map<string, number>()
  sections.forEach(section => {
    const key = sectionKey(section.scope, section.hole_section_id)
    snapshotCounts.set(key, (snapshotCounts.get(key) ?? 0) + 1)
  })
  const items: SectionKpi[] = sections.map(section => {
    const key = sectionKey(section.scope, section.hole_section_id)
    const reconciliation = reconciliations.get(key)
    const setting = settingBySection.get(key)
    const mudType = reconciliation?.mud_type ?? setting?.mud_type
    return {
      section,
      balance: balances.get(section.id),
      reconciliation,
      mudLabel: mudType ?? (reconciliation || setting ? 'Mud type not configured' : 'Mud type unavailable'),
      sharedRate: (snapshotCounts.get(key) ?? 0) > 1,
    }
  })
  const hasSharedRates = items.some(item => item.sharedRate)
  const balanceAvailable = Boolean(snapshot?.balance)
  const reconciliationAvailable = Boolean(snapshot?.reconciliation)
  const currency = snapshot?.reconciliation?.currency ?? ''

  return <Box component="section" aria-labelledby="mud-kpi-heading" sx={{ mb: `${space[4]}px` }}>
    <Typography component="h2" id="mud-kpi-heading" fontSize={14} fontWeight={800}>Section mud position</Typography>
    <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 0.5, mb: 1.5 }}>
      Since each section’s first active entry, across all saved dates (including future-dated entries). Quantities use the unit entered for each section; draft Daily Cost sheets are included in rates. The filters below do not change these cards.
    </Typography>
    {loading && <Typography color="text.secondary" fontSize={12.5} aria-live="polite" sx={{ mb: 1 }}>Loading section mud position…</Typography>}
    {snapshot?.balanceError && <Alert severity="error" sx={{ mb: 1 }}>Section material balances are unavailable: {snapshot.balanceError}</Alert>}
    {snapshot?.reconciliationError && <Alert severity="error" sx={{ mb: 1 }}>Cost/BBL and reconciliation figures are unavailable: {snapshot.reconciliationError}</Alert>}
    <Box sx={{ display: 'grid', gap: `${space[4]}px`, gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(2, minmax(0, 1fr))', md: 'repeat(3, minmax(0, 1fr))', lg: 'repeat(5, minmax(0, 1fr))' } }}>
      {items.map(item => {
        const balance = item.balance
        // The reconciliation engine combines historical IDs for one logical
        // section; those combined totals cannot be attributed to either card.
        const pricing = balance && !item.sharedRate ? item.reconciliation : undefined
        const amount = (value: string | undefined) => value == null ? '—' : mudQuantity(value)
        return <KpiCard key={item.section.id} label={`Material balance: ${sectionName(item.section)} · ${sectionContext(item.section)}`}>
          <Typography component="h3" fontSize={14} fontWeight={800} sx={{ overflowWrap: 'anywhere' }}>{sectionName(item.section)}</Typography>
          <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 0.5, mb: 1.5 }}>
            {sectionContext(item.section)} · {item.mudLabel}
          </Typography>
          <Box component="dl" sx={{ display: 'grid', gap: 0.75, m: 0 }}>
            <Metric label="Opening stock" value={amount(balance?.opening_stock)}/>
            <Metric label="Receipt" value={amount(balance?.receipt)}/>
            <Metric label="Additions" value={amount(balance?.additions)}/>
            <Metric label="Total mud (pricing)" value={amount(pricing?.total_mud)}/>
            <Metric label="Consumption / losses" value={amount(balance?.consumption_losses)}/>
            <Metric label="Others" value={amount(balance?.others)}/>
            <Metric label="Reconciled cost" value={pricing?.reconciled_cost == null ? '—' : dailyMoney(pricing.reconciled_cost, pricing.currency || currency)}/>
          </Box>
          {!loading && balanceAvailable && !balance && <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1.5 }}>No active entries.</Typography>}
          {item.sharedRate && <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1.5 }}>Pricing totals are shared across section snapshots; see Reconciliation.</Typography>}
        </KpiCard>
      })}
      <KpiCard label="Latest closing stock by section">
        <Typography component="h3" fontSize={14} fontWeight={800}>Latest closing stock</Typography>
        <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 0.5, mb: 1.5 }}>Each section’s last calculated balance</Typography>
        <Box component="dl" sx={{ display: 'grid', gap: 1.25, m: 0 }}>
          {items.map(item => <SectionValue key={item.section.id} section={item.section} value={item.balance ? mudQuantity(item.balance.closing_stock) : '—'}/>)}
        </Box>
        {!items.length && <Typography color="text.secondary" fontSize={12.5}>No sections available.</Typography>}
      </KpiCard>
      <KpiCard label="Latest cost per barrel by section">
        <Typography component="h3" fontSize={14} fontWeight={800}>Latest Cost/BBL</Typography>
        <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 0.5, mb: 1.5 }}>Latest cumulative rate for each section</Typography>
        <Box component="dl" sx={{ display: 'grid', gap: 1.25, m: 0 }}>
          {items.map(item => <SectionValue key={item.section.id} section={item.section} value={item.reconciliation?.cost_per_bbl == null ? '—' : dailyMoney(item.reconciliation.cost_per_bbl, item.reconciliation.currency || currency)}/>)}
        </Box>
        {!items.length && <Typography color="text.secondary" fontSize={12.5}>No sections available.</Typography>}
        {!loading && reconciliationAvailable && items.some(item => item.reconciliation?.cost_per_bbl == null) && <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1.5 }}>— means no derived rate is available.</Typography>}
      </KpiCard>
    </Box>
    <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 1 }}>
      Total mud for pricing = opening stock + extra OBM received + additions; other receipts also affect closing stock. “Others” is a separate stock deduction, not consumption/losses.
      {hasSharedRates && ' Cost/BBL is shared by historical snapshots of the same hole section and scope.'}
    </Typography>
  </Box>
}

/** The Reconciliation tab has its own filters, so keep its rate card scoped to
 * those results while still displaying every returned section separately. */
export function MudCostReconciliationRateKpi({ reconciliation }: { reconciliation: MudCostReconciliation }) {
  return <KpiCard label="Selected reconciliation cost per barrel by section">
    <Typography component="h3" fontSize={14} fontWeight={800}>Latest Cost/BBL</Typography>
    <Typography color="text.secondary" fontSize={11.5} sx={{ mt: 0.5, mb: 1.5 }}>Per section through the selected To date</Typography>
    <Box component="dl" sx={{ display: 'grid', gap: 1.25, m: 0 }}>
      {reconciliation.sections.map(row => <SectionValue key={row.section_id} section={{
        section_code: row.section_code, section_name: row.section_name, display_name: row.section_label,
        scope: row.section_scope, is_current: row.is_current,
      }} value={row.cost_per_bbl == null ? '—' : dailyMoney(row.cost_per_bbl, row.currency || reconciliation.currency)}/>)}
    </Box>
    {!reconciliation.sections.length && <Typography color="text.secondary" fontSize={12.5}>No section rates for this scope.</Typography>}
  </KpiCard>
}
