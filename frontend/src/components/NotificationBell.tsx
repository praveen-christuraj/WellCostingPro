import { useCallback, useEffect, useState } from 'react'
import { Badge, Box, Button, Divider, IconButton, List, ListItemButton, ListItemText, Popover, Tooltip, Typography } from '@mui/material'
import { DoneAllRounded, NotificationsNoneRounded } from '@mui/icons-material'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { NotificationPage, UserNotification } from '../lib/workflowTypes'
import { notifyNotificationsChanged, onNotificationsChanged } from '../lib/uiEvents'

const SEVERITY_COLOUR: Record<string, string> = {
  info: 'var(--wcp-tone-info-fg)',
  success: 'var(--wcp-tone-success-fg)',
  warning: 'var(--wcp-tone-warning-fg)',
  error: 'var(--wcp-tone-error-fg)',
}

export default function NotificationBell() {
  const navigate = useNavigate()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [items, setItems] = useState<UserNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [total, setTotal] = useState(0)

  // A background poll must never raise the global error pop-up: a flaky network
  // here is not a failed user action, so the request is silent and simply retries.
  const load = useCallback(() => api<NotificationPage>('/notifications?limit=15', { silent: true })
    .then(data => { setItems(data.items); setUnread(data.unread_count); setTotal(data.total) })
    .catch(() => undefined), [])
  useEffect(() => { void load(); const timer = window.setInterval(load, 60000); return () => window.clearInterval(timer) }, [load])
  // The notification centre changes the same rows; follow it instead of waiting
  // for the next poll, so the badge never contradicts the list on screen.
  useEffect(() => onNotificationsChanged(() => void load()), [load])

  const openItem = async (item: UserNotification) => {
    if (!item.read_at) {
      await api(`/notifications/${item.id}/read`, { method: 'POST', action: 'Mark the notification read' }).catch(() => undefined)
      setItems(rows => rows.map(row => row.id === item.id ? { ...row, read_at: new Date().toISOString() } : row))
      setUnread(value => Math.max(0, value - 1))
      notifyNotificationsChanged()
    }
    setAnchor(null)
    if (item.action_path) navigate(item.action_path)
  }

  const markAll = async () => {
    await api('/notifications/read-all', { method: 'POST', action: 'Mark every notification read' })
    setUnread(0)
    setItems(rows => rows.map(row => ({ ...row, read_at: row.read_at || new Date().toISOString() })))
    notifyNotificationsChanged()
  }

  return <>
    <Tooltip title={unread ? `${unread} unread notification${unread === 1 ? '' : 's'}` : 'Notifications'}>
      <IconButton size="small" onClick={event => { setAnchor(event.currentTarget); void load() }} aria-label={`${unread} unread notifications`}>
        <Badge badgeContent={unread} color="error" max={99}><NotificationsNoneRounded sx={{ fontSize: 21 }}/></Badge>
      </IconButton>
    </Tooltip>
    <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
      <Box sx={{ width: { xs: 320, sm: 400 }, maxWidth: 'calc(100vw - 24px)' }}>
        <Box display="flex" alignItems="center" justifyContent="space-between" px={2} py={1.4} gap={1}>
          <Box>
            <Typography fontWeight={800} fontSize={13.5}>Notifications</Typography>
            <Typography color="text.secondary" fontSize={11}>{unread} unread · {total} in your inbox</Typography>
          </Box>
          {unread > 0 && <Button size="small" startIcon={<DoneAllRounded sx={{ fontSize: 15 }}/>} onClick={() => void markAll()}>Mark all read</Button>}
        </Box><Divider/>
        <List disablePadding sx={{ maxHeight: 420, overflowY: 'auto' }}>
          {items.length === 0 && <Typography color="text.secondary" fontSize={13} p={3} textAlign="center">Nothing yet. Security decisions and task assignments arrive here.</Typography>}
          {items.map(item => <ListItemButton key={item.id} onClick={() => void openItem(item)} sx={{ alignItems: 'flex-start', bgcolor: item.read_at ? 'transparent' : 'action.hover', py: 1.3, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box sx={{ width: 3, alignSelf: 'stretch', borderRadius: 2, mr: 1.2, bgcolor: SEVERITY_COLOUR[item.severity] ?? 'divider', flex: 'none' }}/>
            <ListItemText
              primary={item.title}
              secondary={<>{item.message}<br/>{new Date(item.created_at).toLocaleString()} · {item.notification_type}</>}
              primaryTypographyProps={{ fontSize: 12.8, fontWeight: item.read_at ? 600 : 800, noWrap: true }}
              secondaryTypographyProps={{ fontSize: 11.5, lineHeight: 1.45, mt: .3, sx: { display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }}/>
          </ListItemButton>)}
        </List>
        <Divider/>
        <Button fullWidth onClick={() => { setAnchor(null); navigate('/other-management/notifications') }} sx={{ py: 1.2, fontSize: 12.5 }}>Open notification centre</Button>
      </Box>
    </Popover>
  </>
}
