import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AppBar, Avatar, Box, Button, Divider, IconButton, Menu, MenuItem, TextField, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material'
import { DashboardOutlined, PeopleOutline, AdminPanelSettingsOutlined, VpnKeyOutlined, KeyboardArrowDownRounded, LogoutRounded, AccountTreeOutlined, LightModeOutlined, DarkModeOutlined, MenuRounded, HistoryOutlined, DataObjectOutlined, DeleteOutlineRounded, TableChartOutlined } from '@mui/icons-material'
import Brand from './Brand'
import { FormDialog, ErrorMessage } from './Common'
import { api, body } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'

type NavItem = { label: string; path: string; icon: typeof DashboardOutlined; permission?: string; requires?: string[] }
type NavModule = { label: string; icon: typeof DashboardOutlined; items: NavItem[] }

// Top-side navigation with dropdown module menus (no side navigation).
const modules: NavModule[] = [
  { label: 'User Management', icon: PeopleOutline, items: [
    { label: 'Users', path: '/users', icon: PeopleOutline, permission: 'users:read' },
    { label: 'Roles', path: '/roles', icon: AdminPanelSettingsOutlined, permission: 'roles:read' },
    { label: 'Permissions', path: '/permissions', icon: VpnKeyOutlined, permission: 'permissions:read' },
    { label: 'Assignments', path: '/assignments', icon: AccountTreeOutlined, permission: 'assignments:write', requires: ['users:read', 'roles:read', 'permissions:read'] },
  ] },
  { label: 'Master Data Management', icon: DataObjectOutlined, items: [
    { label: 'Overview', path: '/master-data', icon: DataObjectOutlined, permission: 'master-data:read' },
    { label: 'Master data', path: '/master-data/records', icon: TableChartOutlined, permission: 'master-data:read' },
    { label: 'Deleted entries', path: '/master-data/deleted', icon: DeleteOutlineRounded, permission: 'master-data:read' },
  ] },
  { label: 'Auditing', icon: HistoryOutlined, items: [
    { label: 'Audit Log', path: '/audit', icon: HistoryOutlined, permission: 'audit:read' },
  ] },
]

export default function Layout() {
  const { user, can, logout } = useAuth()
  const { mode, toggle } = useColorMode()
  const mui = useTheme()
  const compact = useMediaQuery(mui.breakpoints.down('md'))
  const navigate = useNavigate()
  const location = useLocation()
  const [moduleAnchor, setModuleAnchor] = useState<{ el: HTMLElement; module: NavModule } | null>(null)
  const [mobileAnchor, setMobileAnchor] = useState<null | HTMLElement>(null)
  const [accountAnchor, setAccountAnchor] = useState<null | HTMLElement>(null)
  const [passwordDialog, setPasswordDialog] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  const changePassword = async () => { setSavingPassword(true); setPasswordError(''); try { await api('/auth/change-password', { method: 'POST', body: body({ current_password: currentPassword, new_password: newPassword }) }); setPasswordDialog(false); setCurrentPassword(''); setNewPassword(''); await logout() } catch (e) { setPasswordError((e as Error).message) } finally { setSavingPassword(false) } }

  const visible = (item: NavItem) => (!item.permission || can(item.permission)) && (!item.requires || item.requires.every(can))
  const modulesForUser = modules.map(m => ({ ...m, items: m.items.filter(visible) })).filter(m => m.items.length > 0)
  const currentModule = modulesForUser.find(m => m.items.some(i => i.path === location.pathname))

  return <Box display="flex" flexDirection="column" minHeight="100vh">
    <AppBar position="sticky" elevation={0} sx={{ bgcolor: 'background.paper', color: 'text.primary', borderBottom: '1px solid', borderColor: 'divider' }}>
      <Toolbar sx={{ gap: 2, minHeight: 64, px: { xs: 2, sm: 3.5 } }}>
        <IconButton sx={{ display: { md: 'none' }, color: 'text.primary' }} onClick={e => setMobileAnchor(e.currentTarget)} aria-label="Open navigation"><MenuRounded/></IconButton>
        <Brand/>
        {!compact && <Box display="flex" alignItems="center" gap={.5} ml={3}>
          <NavLink to="/" end className={({ isActive }) => `topnav-item${isActive ? ' active' : ''}`}><DashboardOutlined sx={{ fontSize: 17 }}/>&nbsp;Dashboard</NavLink>
          {modulesForUser.map(module => {
            const active = currentModule?.label === module.label
            return <Button key={module.label} className={`topnav-item${active ? ' active' : ''}`} onClick={e => setModuleAnchor({ el: e.currentTarget, module })} endIcon={<KeyboardArrowDownRounded sx={{ fontSize: 18 }}/>}>{module.label}</Button>
          })}
        </Box>}
        <Box display="flex" alignItems="center" gap={1.2} ml="auto">
          <Tooltip title={mode === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}>
            <IconButton onClick={toggle} size="small" aria-label="Toggle color theme" sx={{ color: 'text.secondary' }}>{mode === 'light' ? <DarkModeOutlined sx={{ fontSize: 20 }}/> : <LightModeOutlined sx={{ fontSize: 20 }}/>}</IconButton>
          </Tooltip>
          <Box textAlign="right" sx={{ display: { xs: 'none', sm: 'block' } }}>
            <Typography fontWeight={700} fontSize={12.5} lineHeight={1.3}>{user?.full_name}</Typography>
            <Typography color="text.secondary" fontSize={11.5}>{user?.organization_name}</Typography>
          </Box>
          <Tooltip title="Account menu"><IconButton onClick={e => setAccountAnchor(e.currentTarget)} sx={{ p: .4, borderRadius: 2 }}><Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.light', color: 'primary.dark', fontSize: 12, fontWeight: 800 }}>{user?.full_name.split(' ').map(x => x[0]).slice(0, 2).join('').toUpperCase()}</Avatar><KeyboardArrowDownRounded sx={{ color: 'text.secondary', ml: .4, fontSize: 18 }}/></IconButton></Tooltip>
        </Box>
      </Toolbar>
    </AppBar>

    <Menu anchorEl={moduleAnchor?.el} open={!!moduleAnchor} onClose={() => setModuleAnchor(null)}>
      {moduleAnchor?.module.items.map(item => <MenuItem key={item.path} selected={location.pathname === item.path} onClick={() => { setModuleAnchor(null); navigate(item.path) }}><item.icon sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>{item.label}</MenuItem>)}
    </Menu>
    <Menu anchorEl={mobileAnchor} open={!!mobileAnchor} onClose={() => setMobileAnchor(null)}>
      <MenuItem selected={location.pathname === '/'} onClick={() => { setMobileAnchor(null); navigate('/') }}><DashboardOutlined sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>Dashboard</MenuItem>
      {modulesForUser.map(module => <Box key={module.label}>
        <Divider/>
        <Typography fontSize={10} fontWeight={800} letterSpacing={1.2} color="text.secondary" sx={{ px: 2, pt: 1.2, pb: .5 }}>{module.label.toUpperCase()}</Typography>
        {module.items.map(item => <MenuItem key={item.path} selected={location.pathname === item.path} onClick={() => { setMobileAnchor(null); navigate(item.path) }}><item.icon sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>{item.label}</MenuItem>)}
      </Box>)}
    </Menu>
    <Menu anchorEl={accountAnchor} open={!!accountAnchor} onClose={() => setAccountAnchor(null)}>
      <MenuItem onClick={() => { setAccountAnchor(null); setPasswordDialog(true); setPasswordError('') }}>Change password</MenuItem>
      <MenuItem onClick={() => { setAccountAnchor(null); logout() }}><LogoutRounded sx={{ mr: 1, fontSize: 18 }}/> Sign out</MenuItem>
    </Menu>

    <Box component="main" sx={{ flexGrow: 1, minWidth: 0 }}>
      <Box sx={{ px: { xs: 2.5, sm: 4, xl: 6 }, py: { xs: 3, sm: 4 }, maxWidth: 1600, mx: 'auto' }}><Outlet/></Box>
    </Box>

    <FormDialog open={passwordDialog} title="Change your password" subtitle="You will be signed out of all sessions after updating." onClose={() => setPasswordDialog(false)} onSubmit={changePassword} busy={savingPassword} submitLabel="Update password">
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Current password" type="password" fullWidth value={currentPassword} onChange={e => setCurrentPassword(e.target.value)}/>
        <TextField label="New password" type="password" fullWidth helperText="At least 12 characters" value={newPassword} onChange={e => setNewPassword(e.target.value)}/>
        <ErrorMessage message={passwordError}/>
      </Box>
    </FormDialog>
  </Box>
}
