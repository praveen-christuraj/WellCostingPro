import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Alert, AppBar, Avatar, Box, Collapse, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Menu, MenuItem, Snackbar, TextField, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material'
import { DashboardOutlined, PeopleOutline, AdminPanelSettingsOutlined, VpnKeyOutlined, KeyboardArrowDownRounded, KeyboardArrowUpRounded, ChevronLeftRounded, ChevronRightRounded, LogoutRounded, AccountTreeOutlined, LightModeOutlined, DarkModeOutlined, MenuRounded, HistoryOutlined, DataObjectOutlined, DeleteOutlineRounded, TableChartOutlined, StorefrontOutlined, DescriptionOutlined, BuildOutlined, GridViewOutlined, PrecisionManufacturingOutlined, OpacityOutlined, ListAltOutlined, BusinessOutlined, PublicOutlined, TaskAltOutlined, RequestQuoteOutlined, InsightsOutlined, SettingsOutlined, StorageOutlined, PlaylistAddCheckRounded, WaterDropOutlined, AssessmentOutlined, LocalGasStationOutlined, ScienceOutlined, Inventory2Outlined, ScheduleRounded, FactCheckOutlined, SecurityRounded, NotificationsOutlined } from '@mui/icons-material'
import Brand from './Brand'
import { FormDialog, ErrorMessage } from './Common'
import { api, body } from '../lib/api'
import { pageTitle } from '../lib/appInfo'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import NotificationBell from './NotificationBell'

type NavItem = { label: string; path: string; icon: typeof DashboardOutlined; permission?: string; anyOf?: string[]; requires?: string[] }
type NavModule = { label: string; icon: typeof DashboardOutlined; items: NavItem[] }

const modules: NavModule[] = [
  { label: 'User Management', icon: PeopleOutline, items: [
    { label: 'Dashboard', path: '/dashboard', icon: DashboardOutlined },
    { label: 'Users', path: '/users', icon: PeopleOutline, permission: 'users:read' },
    { label: 'Roles', path: '/roles', icon: AdminPanelSettingsOutlined, permission: 'roles:read' },
    { label: 'Permissions', path: '/permissions', icon: VpnKeyOutlined, permission: 'permissions:read' },
    { label: 'Assignments', path: '/assignments', icon: AccountTreeOutlined, permission: 'assignments:write', requires: ['users:read', 'roles:read', 'permissions:read'] },
    // The reset queue is readable with security:password-reset alone, so a reviewer
    // reaches the page without needing the wider register capability.
    { label: 'Security centre', path: '/security', icon: SecurityRounded, anyOf: ['security:read', 'security:password-reset', 'security:unlock'] },
  ] },
  { label: 'Master Data Management', icon: DataObjectOutlined, items: [
    { label: 'Overview', path: '/master-data', icon: DataObjectOutlined, permission: 'master-data:read' },
    { label: 'Master data', path: '/master-data/records', icon: TableChartOutlined, permission: 'master-data:read' },
    { label: 'Services', path: '/master-data/services', icon: BuildOutlined, permission: 'master-data:read' },
    { label: 'Vendors', path: '/master-data/vendors', icon: StorefrontOutlined, permission: 'master-data:read' },
    { label: 'PO/SO Orders', path: '/master-data/po-so-orders', icon: DescriptionOutlined, permission: 'master-data:read' },
    { label: 'Tangibles', path: '/master-data/tangibles', icon: PrecisionManufacturingOutlined, permission: 'master-data:read' },
    { label: 'Consumables', path: '/master-data/consumables', icon: OpacityOutlined, permission: 'master-data:read' },
    { label: 'Catalogue lists', path: '/master-data/catalogue-lists', icon: ListAltOutlined, permission: 'master-data:read' },
    { label: 'Deleted entries', path: '/master-data/deleted', icon: DeleteOutlineRounded, permission: 'master-data:read' },
  ] },
  { label: 'Rig & Well Management', icon: BusinessOutlined, items: [
    { label: 'Overview', path: '/rig-well', icon: BusinessOutlined, permission: 'rig-well:read' },
    { label: 'Blocks', path: '/rig-well/blocks', icon: GridViewOutlined, permission: 'rig-well:read' },
    { label: 'Rigs', path: '/rig-well/rigs', icon: BusinessOutlined, permission: 'rig-well:read' },
    { label: 'Wells', path: '/rig-well/wells', icon: PublicOutlined, permission: 'rig-well:read' },
    { label: 'Well sub activities', path: '/rig-well/sub-activities', icon: TaskAltOutlined, permission: 'rig-well:read' },
    { label: 'Deleted entries', path: '/rig-well/deleted', icon: DeleteOutlineRounded, permission: 'rig-well:read' },
  ] },
  { label: 'AFE Management', icon: DescriptionOutlined, items: [
    { label: 'Overview', path: '/afe', icon: DashboardOutlined, permission: 'afe:read' },
    { label: 'AFE & cost estimation', path: '/afe/register', icon: DescriptionOutlined, permission: 'afe:read' },
    { label: 'Reusable costing sets', path: '/costing-sets', icon: PlaylistAddCheckRounded, permission: 'costing-sets:read' },
  ] },
  { label: 'Daily Cost Management', icon: RequestQuoteOutlined, items: [
    { label: 'Daily cost register', path: '/daily-cost', icon: RequestQuoteOutlined, permission: 'daily-cost:read' },
    { label: 'Mud Cost Analysis', path: '/daily-cost/mud-cost-analysis', icon: WaterDropOutlined, permission: 'daily-cost:read' },
    { label: 'LIH Cost Register', path: '/daily-cost/lih-register', icon: PlaylistAddCheckRounded, permission: 'daily-cost:read' },
    { label: 'Fuel Cost Register', path: '/daily-cost/fuel-cost-register', icon: LocalGasStationOutlined, permission: 'daily-cost:read' },
    { label: 'NDT Inspection Register', path: '/daily-cost/ndt-inspections', icon: FactCheckOutlined, permission: 'daily-cost:read' },
    { label: 'Well Cost Analysis', path: '/daily-cost/analysis', icon: InsightsOutlined, permission: 'daily-cost:read' },
  ] },
  { label: 'Reports', icon: AssessmentOutlined, items: [
    { label: 'Overview', path: '/reports', icon: AssessmentOutlined, anyOf: ['rig-well:read', 'afe:read', 'daily-cost:read'] },
    { label: 'Well-wise cost comparisons', path: '/reports/well-cost-comparison', icon: InsightsOutlined, requires: ['rig-well:read'], anyOf: ['afe:read', 'daily-cost:read'] },
    { label: 'Consumption and losses', path: '/reports/consumption-losses', icon: WaterDropOutlined, permission: 'daily-cost:read' },
    { label: 'Mud chemicals usage', path: '/reports/mud-chemicals-usage', icon: ScienceOutlined, permission: 'daily-cost:read' },
    { label: 'Drill bits usage', path: '/reports/drill-bits-usage', icon: PrecisionManufacturingOutlined, permission: 'daily-cost:read' },
    { label: 'Tangibles usage', path: '/reports/tangibles-usage', icon: Inventory2Outlined, permission: 'daily-cost:read' },
    { label: 'Service-wise cost', path: '/reports/service-wise-cost', icon: BuildOutlined, permission: 'daily-cost:read' },
    { label: 'Vendor/company-wise cost', path: '/reports/vendor-wise-cost', icon: StorefrontOutlined, permission: 'daily-cost:read' },
    { label: 'NPT/UPA report', path: '/reports/npt-upa', icon: ScheduleRounded, permission: 'daily-cost:read' },
  ] },
  { label: 'Other Managements', icon: SettingsOutlined, items: [
    { label: 'Overview', path: '/other-management', icon: DashboardOutlined, anyOf: ['audit:read', 'database-browser:read', 'tasks:read'] },
    { label: 'Task Manager', path: '/other-management/tasks', icon: TaskAltOutlined, permission: 'tasks:read' },
    { label: 'Notifications', path: '/other-management/notifications', icon: NotificationsOutlined },
    { label: 'Audit Log', path: '/other-management/audit', icon: HistoryOutlined, permission: 'audit:read' },
    { label: 'Database Browser', path: '/other-management/database', icon: StorageOutlined, permission: 'database-browser:read' },
  ] },
]

export default function Layout() {
  const { user, can, logout } = useAuth()
  const { mode, toggle } = useColorMode()
  const mui = useTheme()
  const desktop = useMediaQuery(mui.breakpoints.up('md'))
  const navigate = useNavigate()
  const location = useLocation()
  const [moduleAnchor, setModuleAnchor] = useState<{ el: HTMLElement; module: NavModule } | null>(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [navExpanded, setNavExpanded] = useState(() => localStorage.getItem('wcp-nav-expanded') !== 'false')
  const [openModules, setOpenModules] = useState<string[]>([])
  const [accountAnchor, setAccountAnchor] = useState<null | HTMLElement>(null)
  const [passwordDialog, setPasswordDialog] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [apiNotice, setApiNotice] = useState<{ message: string; status: number } | null>(null)

  const changePassword = async () => {
    setSavingPassword(true)
    setPasswordError('')
    try {
      await api('/auth/change-password', { method: 'POST', body: body({ current_password: currentPassword, new_password: newPassword }) })
      setPasswordDialog(false)
      setCurrentPassword('')
      setNewPassword('')
      await logout()
    } catch (error) {
      setPasswordError((error as Error).message)
    } finally {
      setSavingPassword(false)
    }
  }

  const visible = (item: NavItem) => (!item.permission || can(item.permission)) && (!item.anyOf || item.anyOf.some(can)) && (!item.requires || item.requires.every(can))
  const showBusinessDashboard = can('rig-well:read') || can('afe:read') || can('daily-cost:read')
  const businessDashboardActive = location.pathname.startsWith('/business-dashboard')
  const modulesForUser = useMemo(
    () => modules.map(module => ({ ...module, items: module.items.filter(visible) })).filter(module => module.items.length > 0),
    [user], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const currentModule = modulesForUser.find(module => module.items.some(item => location.pathname === item.path || location.pathname.startsWith(`${item.path}/`)))
  const currentItem = modulesForUser.flatMap(module => module.items)
    .filter(item => location.pathname === item.path || location.pathname.startsWith(`${item.path}/`))
    .sort((a, b) => b.path.length - a.path.length)[0]

  useEffect(() => { localStorage.setItem('wcp-nav-expanded', String(navExpanded)) }, [navExpanded])
  useEffect(() => {
    if (currentModule) setOpenModules(values => values.includes(currentModule.label) ? values : [...values, currentModule.label])
    setMobileOpen(false)
  }, [location.pathname, currentModule?.label]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    // One pop-up per distinct message: background polling must not stack duplicates,
    // and a repeated failure keeps a single readable notice on screen.
    const show = (event: Event) => {
      const detail = (event as CustomEvent<{ message?: string; status?: number }>).detail
      const message = detail?.message?.trim()
      if (!message || detail?.status === 401) return
      setApiNotice(current => current?.message === message ? current : { message, status: detail?.status ?? 0 })
    }
    window.addEventListener('api-error', show)
    return () => window.removeEventListener('api-error', show)
  }, [])
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 6)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    document.title = pageTitle(businessDashboardActive ? 'Dashboard' : currentItem?.label ?? (location.pathname === '/' ? 'User Management' : undefined))
  }, [businessDashboardActive, currentItem?.label, location.pathname])

  const toggleModule = (label: string) => setOpenModules(values => values.includes(label) ? values.filter(value => value !== label) : [...values, label])
  const go = (path: string) => { navigate(path); setMobileOpen(false); setModuleAnchor(null) }
  const navWidth = navExpanded ? 272 : 76
  const navigation = (temporary = false) => {
    const showText = navExpanded || temporary
    return <Box component="nav" aria-label="Primary navigation" display="flex" flexDirection="column" height="100%" sx={{ overflow: 'hidden' }}>
      <Box display="flex" alignItems="center" justifyContent={showText ? 'space-between' : 'center'} gap={1} sx={{ px: showText ? 2 : 1, minHeight: 72, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ minWidth: 0, overflow: 'hidden', '& > div': { whiteSpace: 'nowrap' } }}>
          {showText ? <Brand/> : <Box className="brand-mark" aria-label="WellCostIQ"><span className="brand-line"/><span className="brand-dot"/></Box>}
        </Box>
        {!temporary && <Tooltip title={navExpanded ? 'Collapse navigation' : 'Expand navigation'} placement="right">
          <IconButton size="small" onClick={() => setNavExpanded(value => !value)} aria-label={navExpanded ? 'Collapse navigation' : 'Expand navigation'}>
            {navExpanded ? <ChevronLeftRounded/> : <ChevronRightRounded/>}
          </IconButton>
        </Tooltip>}
      </Box>
      <Box sx={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', px: 1, py: 1.5 }}>
        {showBusinessDashboard && <Tooltip title={!showText ? 'Dashboard' : ''} placement="right">
          <ListItemButton selected={businessDashboardActive} onClick={() => go('/business-dashboard')} sx={{ minHeight: 42, px: 1.25, mb: .5, borderRadius: 1.5, justifyContent: showText ? 'initial' : 'center' }}>
            <ListItemIcon sx={{ minWidth: showText ? 38 : 0, color: businessDashboardActive ? 'primary.main' : 'text.secondary', justifyContent: 'center' }}><DashboardOutlined fontSize="small"/></ListItemIcon>
            {showText ? <ListItemText primary="Dashboard" primaryTypographyProps={{ fontSize: 12.5, fontWeight: businessDashboardActive ? 750 : 600 }}/> : null}
          </ListItemButton>
        </Tooltip>}
        <List disablePadding>
          {modulesForUser.map(module => {
            const ModuleIcon = module.icon
            const active = currentModule?.label === module.label
            const open = openModules.includes(module.label)
            return <Box key={module.label} sx={{ mb: .5 }}>
              <Tooltip title={!showText ? module.label : ''} placement="right">
                <ListItemButton onClick={event => showText ? toggleModule(module.label) : setModuleAnchor({ el: event.currentTarget, module })} aria-expanded={showText ? open : undefined} aria-haspopup={!showText ? 'menu' : undefined} sx={{ minHeight: 42, px: 1.25, borderRadius: 1.5, justifyContent: showText ? 'initial' : 'center', color: active ? 'primary.main' : 'text.primary' }}>
                  <ListItemIcon sx={{ minWidth: showText ? 38 : 0, color: active ? 'primary.main' : 'text.secondary', justifyContent: 'center' }}><ModuleIcon fontSize="small"/></ListItemIcon>
                  {showText && <><ListItemText primary={module.label} primaryTypographyProps={{ fontSize: 12.5, fontWeight: active ? 750 : 650, noWrap: true }}/>{open ? <KeyboardArrowUpRounded fontSize="small"/> : <KeyboardArrowDownRounded fontSize="small"/>}</>}
                </ListItemButton>
              </Tooltip>
              {showText && <Collapse in={open} timeout={120} unmountOnExit>
                <List disablePadding sx={{ mt: .25, ml: 1.25, pl: 1.25, borderLeft: '1px solid', borderColor: 'divider' }}>
                  {module.items.map(item => {
                    const ItemIcon = item.icon
                    const selected = currentItem?.path === item.path
                    return <ListItemButton key={item.path} selected={selected} onClick={() => go(item.path)} sx={{ minHeight: 38, px: 1.25, borderRadius: 1.5 }}>
                      <ListItemIcon sx={{ minWidth: 34, color: selected ? 'primary.main' : 'text.secondary' }}><ItemIcon sx={{ fontSize: 17 }}/></ListItemIcon>
                      <ListItemText primary={item.label} primaryTypographyProps={{ fontSize: 12, fontWeight: selected ? 750 : 550 }}/>
                    </ListItemButton>
                  })}
                </List>
              </Collapse>}
            </Box>
          })}
        </List>
      </Box>
      {showText && <Box sx={{ px: 2, py: 1.5, borderTop: '1px solid', borderColor: 'divider' }}><Typography color="text.secondary" fontSize={10.5} noWrap>{user?.organization_name}</Typography></Box>}
    </Box>
  }

  return <Box display="flex" minHeight="100vh">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    {desktop ? <Box component="aside" sx={{ width: navWidth, flex: '0 0 auto', transition: 'width 160ms cubic-bezier(0.2, 0, 0, 1)' }}>
      <Box sx={{ position: 'fixed', inset: '0 auto 0 0', width: navWidth, bgcolor: 'background.paper', borderRight: '1px solid', borderColor: 'divider', zIndex: 1100, transition: 'width 160ms cubic-bezier(0.2, 0, 0, 1)' }}>{navigation()}</Box>
    </Box> : <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} ModalProps={{ keepMounted: true }} PaperProps={{ sx: { width: 292 } }}>{navigation(true)}</Drawer>}

    <Box display="flex" flexDirection="column" minWidth={0} flex={1}>
      <AppBar position="sticky" elevation={0} sx={{ bgcolor: 'background.paper', color: 'text.primary', borderBottom: '1px solid', borderColor: 'divider', boxShadow: scrolled ? 2 : 'none', transition: 'box-shadow 160ms cubic-bezier(0.2, 0, 0, 1)' }}>
        <Toolbar sx={{ gap: 1.5, minHeight: { xs: 56, sm: 60 }, px: { xs: 1.5, sm: 2.5 } }}>
          {!desktop && <IconButton onClick={() => setMobileOpen(true)} aria-label="Open navigation" aria-expanded={mobileOpen}><MenuRounded/></IconButton>}
          <Box minWidth={0}>
            <Typography fontSize={11} color="text.secondary" fontWeight={650} noWrap>{currentModule?.label ?? (businessDashboardActive ? 'Business overview' : 'WellCostIQ')}</Typography>
            <Typography fontSize={14} fontWeight={750} noWrap>{currentItem?.label ?? (businessDashboardActive ? 'Dashboard' : 'Workspace')}</Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={1.2} ml="auto" sx={{ flex: '0 0 auto' }}>
            <NotificationBell/>
            <Tooltip title={mode === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}>
              <IconButton onClick={toggle} size="small" aria-label="Toggle color theme" sx={{ color: 'text.secondary' }}>{mode === 'light' ? <DarkModeOutlined sx={{ fontSize: 20 }}/> : <LightModeOutlined sx={{ fontSize: 20 }}/>}</IconButton>
            </Tooltip>
            <Box textAlign="right" sx={{ display: { xs: 'none', sm: 'block' } }}>
              <Typography fontWeight={700} fontSize={12.5} lineHeight={1.3}>{user?.full_name}</Typography>
              <Typography color="text.secondary" fontSize={11.5}>{user?.organization_name}</Typography>
            </Box>
            <Tooltip title="Account menu"><IconButton onClick={event => setAccountAnchor(event.currentTarget)} sx={{ p: .4, borderRadius: 2 }} aria-label="Account menu" aria-haspopup="menu" aria-expanded={!!accountAnchor}><Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.light', color: 'primary.dark', fontSize: 12, fontWeight: 800 }}>{user?.full_name.split(' ').map(value => value[0]).slice(0, 2).join('').toUpperCase()}</Avatar><KeyboardArrowDownRounded sx={{ color: 'text.secondary', ml: .4, fontSize: 18 }}/></IconButton></Tooltip>
          </Box>
        </Toolbar>
      </AppBar>

      <Menu anchorEl={moduleAnchor?.el} open={!!moduleAnchor} onClose={() => setModuleAnchor(null)}>
        {moduleAnchor?.module.items.map(item => <MenuItem key={item.path} selected={currentItem?.path === item.path} onClick={() => go(item.path)}><item.icon sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>{item.label}</MenuItem>)}
      </Menu>
      <Menu anchorEl={accountAnchor} open={!!accountAnchor} onClose={() => setAccountAnchor(null)}>
        <MenuItem onClick={() => { setAccountAnchor(null); setPasswordDialog(true); setPasswordError('') }}>Change password</MenuItem>
        <MenuItem onClick={() => { setAccountAnchor(null); logout() }}><LogoutRounded sx={{ mr: 1, fontSize: 18 }}/> Sign out</MenuItem>
      </Menu>

      <Box component="main" id="main-content" tabIndex={-1} sx={{ flexGrow: 1, minWidth: 0, width: '100%', overflowX: 'clip', '&:focus': { outline: 'none' } }}>
        <Box sx={{ px: { xs: 1.5, sm: 2.5, xl: 3 }, py: { xs: 2, sm: 2.5 }, width: '100%' }}><Outlet/></Box>
      </Box>
    </Box>

    <Snackbar open={!!apiNotice} onClose={() => setApiNotice(null)} anchorOrigin={{ vertical: 'top', horizontal: 'right' }} sx={{ mt: 7, maxWidth: 480 }}>
      <Alert severity={apiNotice && apiNotice.status === 403 ? 'warning' : 'error'} variant="filled" onClose={() => setApiNotice(null)}
        sx={{ width: '100%', boxShadow: 8, alignItems: 'center' }}>{apiNotice?.message}</Alert>
    </Snackbar>

    <FormDialog open={passwordDialog} title="Change your password" subtitle="You will be signed out of all sessions after updating." onClose={() => setPasswordDialog(false)} onSubmit={changePassword} busy={savingPassword} submitLabel="Update password">
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Current password" type="password" fullWidth autoComplete="current-password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)}/>
        <TextField label="New password" type="password" fullWidth autoComplete="new-password"
          helperText="12–128 characters, at least three of lowercase, uppercase, number and symbol. The last five passwords cannot be reused."
          value={newPassword} onChange={event => setNewPassword(event.target.value)}/>
        <ErrorMessage message={passwordError}/>
      </Box>
    </FormDialog>
  </Box>
}
