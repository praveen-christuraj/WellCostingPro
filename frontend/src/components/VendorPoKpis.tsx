import { useEffect, useState } from 'react'
import { Box, CircularProgress, Paper, Typography } from '@mui/material'
import { AttachFileRounded, BlockRounded, DescriptionOutlined, HistoryOutlined, StorefrontOutlined } from '@mui/icons-material'
import { api } from '../lib/api'
import { formatBytes, type VendorPoOverview } from '../lib/vendorMaster'
import { ErrorMessage } from './Common'

// Shared KPI strip for the Vendors and PO/SO Orders tabs: one module, one summary.
export function VendorPoKpis({ active }: { active: 'vendors' | 'orders' }) {
  const [data, setData] = useState<VendorPoOverview | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<VendorPoOverview>('/master-data/vendor-po/overview')
      .then(setData)
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : 'Could not load the module summary'))
  }, [active])

  if (error) return <ErrorMessage message={error}/>
  if (!data) return <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={22}/></Box>

  const cards = active === 'vendors'
    ? [
      { icon: <StorefrontOutlined sx={{ fontSize: 20 }}/>, value: String(data.vendors_active), label: 'Active vendors', hint: `${data.vendors_inactive} inactive in the workspace` },
      { icon: <BlockRounded sx={{ fontSize: 20 }}/>, value: String(data.vendors_blocked), label: 'Blocked vendors', hint: 'New PO/SO orders are refused' },
      { icon: <DescriptionOutlined sx={{ fontSize: 20 }}/>, value: String(data.orders_active), label: 'PO/SO orders', hint: `${data.orders_deleted} in deleted entries` },
      { icon: <HistoryOutlined sx={{ fontSize: 20 }}/>, value: String(data.orders_amendments), label: 'Amendments raised', hint: 'Revisions after the original' },
      { icon: <AttachFileRounded sx={{ fontSize: 20 }}/>, value: String(data.documents_active), label: 'Files attached', hint: `${formatBytes(data.storage_bytes)} stored` },
    ]
    : [
      { icon: <DescriptionOutlined sx={{ fontSize: 20 }}/>, value: String(data.orders_active), label: 'PO/SO orders', hint: data.orders_by_type.map(type => `${type.key} ${type.count}`).join(' · ') },
      { icon: <HistoryOutlined sx={{ fontSize: 20 }}/>, value: String(data.orders_amendments), label: 'Amendments raised', hint: 'Latest revision is the one to quote' },
      { icon: <AttachFileRounded sx={{ fontSize: 20 }}/>, value: String(data.documents_active), label: 'Files attached', hint: `${formatBytes(data.storage_bytes)} stored` },
      { icon: <StorefrontOutlined sx={{ fontSize: 20 }}/>, value: String(data.vendors_active), label: 'Active vendors', hint: `${data.vendors_blocked} blocked` },
      { icon: <BlockRounded sx={{ fontSize: 20 }}/>, value: String(data.orders_deleted + data.documents_deleted), label: 'Deleted entries', hint: 'Orders and files, recoverable' },
    ]

  return <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(3, 1fr)', lg: 'repeat(5, 1fr)' }, mb: 2.5 }}>
    {cards.map(card => <Paper key={card.label} className="stat-card" variant="outlined" sx={{ padding: 2.2 }}>
      <Box className="stat-icon" sx={{ color: 'primary.main', bgcolor: 'var(--surface-accent)' }}>{card.icon}</Box>
      <Typography className="stat-value" sx={{ fontSize: 26, margin: '14px 0 1px !important' }}>{card.value}</Typography>
      <Typography fontWeight={700} fontSize={12.5}>{card.label}</Typography>
      <Typography color="text.secondary" fontSize={11} mt={.4}>{card.hint}</Typography>
    </Paper>)}
  </Box>
}
