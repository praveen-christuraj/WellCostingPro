import { useCallback, useEffect, useState } from 'react'
import { Badge, Box, Button, Divider, IconButton, List, ListItemButton, ListItemText, Popover, Typography } from '@mui/material'
import { NotificationsNoneRounded } from '@mui/icons-material'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { UserNotification } from '../lib/workflowTypes'

export default function NotificationBell() {
  const navigate = useNavigate()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [items, setItems] = useState<UserNotification[]>([])
  const [unread, setUnread] = useState(0)
  const load = useCallback(() => api<{ items: UserNotification[]; unread_count: number }>('/notifications?limit=20')
    .then(data => { setItems(data.items); setUnread(data.unread_count) }).catch(() => undefined), [])
  useEffect(() => { void load(); const timer = window.setInterval(load, 60000); return () => window.clearInterval(timer) }, [load])
  const openItem = async (item: UserNotification) => {
    if (!item.read_at) { await api(`/notifications/${item.id}/read`, { method: 'POST' }); setUnread(value => Math.max(0, value - 1)) }
    setAnchor(null)
    if (item.action_path) navigate(item.action_path)
  }
  return <>
    <IconButton size="small" onClick={event => { setAnchor(event.currentTarget); void load() }} aria-label={`${unread} unread notifications`}>
      <Badge badgeContent={unread} color="error" max={99}><NotificationsNoneRounded sx={{ fontSize: 21 }}/></Badge>
    </IconButton>
    <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
      <Box sx={{ width: { xs: 320, sm: 390 }, maxWidth: 'calc(100vw - 24px)' }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" px={2} py={1.5}>
          <Typography fontWeight={800}>Notifications</Typography>
          {unread > 0 && <Button size="small" onClick={async () => { await api('/notifications/read-all', { method: 'POST' }); setUnread(0); setItems(rows => rows.map(row => ({ ...row, read_at: row.read_at || new Date().toISOString() }))) }}>Mark all read</Button>}
        </Box><Divider/>
        <List disablePadding sx={{ maxHeight: 430, overflowY: 'auto' }}>
          {items.length === 0 && <Typography color="text.secondary" fontSize={13} p={3} textAlign="center">No notifications yet.</Typography>}
          {items.map(item => <ListItemButton key={item.id} onClick={() => void openItem(item)} sx={{ alignItems: 'flex-start', bgcolor: item.read_at ? 'transparent' : 'action.hover', py: 1.4 }}>
            <ListItemText primary={item.title} secondary={<>{item.message}<br/>{new Date(item.created_at).toLocaleString()}</>} primaryTypographyProps={{ fontSize: 13, fontWeight: item.read_at ? 650 : 800 }} secondaryTypographyProps={{ fontSize: 11.5, lineHeight: 1.45, mt: .4 }}/>
          </ListItemButton>)}
        </List>
        <Divider/><Button fullWidth onClick={() => { setAnchor(null); navigate('/other-management/notifications') }} sx={{ py: 1.2 }}>Open notification centre</Button>
      </Box>
    </Popover>
  </>
}
