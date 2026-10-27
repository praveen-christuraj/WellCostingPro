import { useEffect, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AppBar, Avatar, Box, Button, Divider, IconButton, Menu, MenuItem, TextField, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material'
import { DashboardOutlined, PeopleOutline, AdminPanelSettingsOutlined, VpnKeyOutlined, KeyboardArrowDownRounded, LogoutRounded, AccountTreeOutlined, LightModeOutlined, DarkModeOutlined, MenuRounded, HistoryOutlined, DataObjectOutlined, DeleteOutlineRounded, TableChartOutlined, StorefrontOutlined, DescriptionOutlined, BuildOutlined, GridViewOutlined, PrecisionManufacturingOutlined, OpacityOutlined, ListAltOutlined, BusinessOutlined, PublicOutlined, TaskAltOutlined, RequestQuoteOutlined, InsightsOutlined, SettingsOutlined, StorageOutlined, PlaylistAddCheckRounded, WaterDropOutlined, AssessmentOutlined, LocalGasStationOutlined, ScienceOutlined, Inventory2Outlined, ScheduleRounded, FactCheckOutlined } from '@mui/icons-material'
import Brand from './Brand'
import { FormDialog, ErrorMessage } from './Common'
import { api, body } from '../lib/api'
import { pageTitle } from '../lib/appInfo'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'

type NavItem = { label: string; path: string; icon: typeof DashboardOutlined; permission?: string; anyOf?: string[]; requires?: string[] }
type NavModule = { label: string; icon: typeof DashboardOutlined; items: NavItem[] }

// Top-side navigation with dropdown module menus (no side navigation).
const modules: NavModule[] = [
  { label: 'User Management', icon: PeopleOutline, items: [
    { label: 'Dashboard', path: '/dashboard', icon: DashboardOutlined },
    { label: 'Users', path: '/users', icon: PeopleOutline, permission: 'users:read' },
    { label: 'Roles', path: '/roles', icon: AdminPanelSettingsOutlined, permission: 'roles:read' },
    { label: 'Permissions', path: '/permissions', icon: VpnKeyOutlined, permission: 'permissions:read' },
    { label: 'Assignments', path: '/assignments', icon: AccountTreeOutlined, permission: 'assignments:write', requires: ['users:read', 'roles:read', 'permissions:read'] },
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
    { label: 'Overview', path: '/other-management', icon: DashboardOutlined, anyOf: ['audit:read', 'database-browser:read'] },
    { label: 'Audit Log', path: '/other-management/audit', icon: HistoryOutlined, permission: 'audit:read' },
    { label: 'Database Browser', path: '/other-management/database', icon: StorageOutlined, permission: 'database-browser:read' },
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
  const [scrolled, setScrolled] = useState(false)

  const changePassword = async () => { setSavingPassword(true); setPasswordError(''); try { await api('/auth/change-password', { method: 'POST', body: body({ current_password: currentPassword, new_password: newPassword }) }); setPasswordDialog(false); setCurrentPassword(''); setNewPassword(''); await logout() } catch (e) { setPasswordError((e as Error).message) } finally { setSavingPassword(false) } }

  const visible = (item: NavItem) => (!item.permission || can(item.permission)) && (!item.anyOf || item.anyOf.some(can)) && (!item.requires || item.requires.every(can))
  // The business dashboard spans three modules, so it sits directly in the bar
  // rather than inside one module's dropdown.
  const showBusinessDashboard = can('rig-well:read') || can('afe:read') || can('daily-cost:read')
  const businessDashboardActive = location.pathname.startsWith('/business-dashboard')
  const modulesForUser = modules.map(m => ({ ...m, items: m.items.filter(visible) })).filter(m => m.items.length > 0)
  const currentModule = modulesForUser.find(m => m.items.some(i => location.pathname === i.path || location.pathname.startsWith(`${i.path}/`)))

  // The sticky bar only claims elevation once content is actually under it.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 6)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Browser tabs and history say which screen you are on.
  useEffect(() => {
    // The most specific route wins, so /other-management/audit is not labelled with the module overview.
    // `/` is a landing redirect to User Management; the dashboard lives at /dashboard.
    const page = location.pathname.startsWith('/business-dashboard')
      ? 'Dashboard'
      : location.pathname === '/'
      ? 'User Management'
      : modulesForUser.flatMap(m => m.items)
        .filter(i => location.pathname === i.path || location.pathname.startsWith(`${i.path}/`))
        .sort((a, b) => b.path.length - a.path.length)[0]?.label
    document.title = pageTitle(page)
  }, [location.pathname]) // eslint-disable-line react-hooks/exhaustive-deps

  return <Box display="flex" flexDirection="column" minHeight="100vh">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <AppBar position="sticky" elevation={0} sx={{
      bgcolor: 'background.paper',
      color: 'text.primary',
      borderBottom: '1px solid',
      borderColor: 'divider',
      boxShadow: scrolled ? 2 : 'none',
      transition: 'box-shadow 160ms cubic-bezier(0.2, 0, 0, 1)',
    }}>
      <Toolbar sx={{ gap: { xs: 1, sm: 1.5 }, minHeight: { xs: 58, sm: 62 }, px: { xs: 1.5, sm: 2.5 }, flexWrap: 'wrap' }}>
        <IconButton sx={{ display: { md: 'none' }, color: 'text.primary' }} onClick={e => setMobileAnchor(e.currentTarget)} aria-label="Open navigation" aria-haspopup="menu" aria-expanded={!!mobileAnchor}><MenuRounded/></IconButton>
        <Brand/>
        {!compact && showBusinessDashboard && <Button
          className={`topnav-item${businessDashboardActive ? ' active' : ''}`}
          onClick={() => navigate('/business-dashboard')}
          sx={{ ml: { md: 1.5 } }}
        >Dashboard</Button>}
        {!compact && <Box component="nav" aria-label="Modules" display="flex" alignItems="center" flexWrap="wrap" rowGap={.25} columnGap={.25} sx={{ ml: { xs: 0, md: 1 }, minWidth: 0, flex: '1 1 auto' }}>
          {modulesForUser.map(module => {
            const active = currentModule?.label === module.label
            return <Button
              key={module.label}
              className={`topnav-item${active ? ' active' : ''}`}
              onClick={e => setModuleAnchor({ el: e.currentTarget, module })}
              aria-haspopup="menu"
              aria-expanded={moduleAnchor?.module.label === module.label}
              endIcon={<KeyboardArrowDownRounded sx={{ fontSize: 18 }}/>}
            >{module.label}</Button>
          })}
        </Box>}
        <Box display="flex" alignItems="center" gap={1.2} ml="auto" sx={{ flex: '0 0 auto' }}>
          <Tooltip title={mode === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}>
            <IconButton onClick={toggle} size="small" aria-label="Toggle color theme" sx={{ color: 'text.secondary' }}>{mode === 'light' ? <DarkModeOutlined sx={{ fontSize: 20 }}/> : <LightModeOutlined sx={{ fontSize: 20 }}/>}</IconButton>
          </Tooltip>
          <Box textAlign="right" sx={{ display: { xs: 'none', sm: 'block' } }}>
            <Typography fontWeight={700} fontSize={12.5} lineHeight={1.3}>{user?.full_name}</Typography>
            <Typography color="text.secondary" fontSize={11.5}>{user?.organization_name}</Typography>
          </Box>
          <Tooltip title="Account menu"><IconButton onClick={e => setAccountAnchor(e.currentTarget)} sx={{ p: .4, borderRadius: 2 }} aria-label="Account menu" aria-haspopup="menu" aria-expanded={!!accountAnchor}><Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.light', color: 'primary.dark', fontSize: 12, fontWeight: 800 }}>{user?.full_name.split(' ').map(x => x[0]).slice(0, 2).join('').toUpperCase()}</Avatar><KeyboardArrowDownRounded sx={{ color: 'text.secondary', ml: .4, fontSize: 18 }}/></IconButton></Tooltip>
        </Box>
      </Toolbar>
    </AppBar>

    <Menu anchorEl={moduleAnchor?.el} open={!!moduleAnchor} onClose={() => setModuleAnchor(null)}>
      {moduleAnchor?.module.items.map(item => <MenuItem key={item.path} selected={location.pathname === item.path} onClick={() => { setModuleAnchor(null); navigate(item.path) }}><item.icon sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>{item.label}</MenuItem>)}
    </Menu>
    <Menu anchorEl={mobileAnchor} open={!!mobileAnchor} onClose={() => setMobileAnchor(null)}>
      {showBusinessDashboard && <MenuItem selected={businessDashboardActive} onClick={() => { setMobileAnchor(null); navigate('/business-dashboard') }}>
        <DashboardOutlined sx={{ fontSize: 18, mr: 1.2, color: 'text.secondary' }}/>Dashboard
      </MenuItem>}
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

    <Box component="main" id="main-content" tabIndex={-1} sx={{ flexGrow: 1, minWidth: 0, width: '100%', overflowX: 'clip', '&:focus': { outline: 'none' } }}>
      <Box sx={{ px: { xs: 2, sm: 3, xl: 4 }, py: { xs: 2.5, sm: 3 }, maxWidth: 1600, mx: 'auto' }}><Outlet/></Box>
    </Box>

    <FormDialog open={passwordDialog} title="Change your password" subtitle="You will be signed out of all sessions after updating." onClose={() => setPasswordDialog(false)} onSubmit={changePassword} busy={savingPassword} submitLabel="Update password">
      <Box display="grid" gap={2} pt={.5}>
        <TextField label="Current password" type="password" fullWidth value={currentPassword} onChange={e => setCurrentPassword(e.target.value)}/><TextField label="New password" type="password" fullWidth helperText="At least 12 characters" value={newPassword} onChange={e => setNewPassword(e.target.value)}/>
        <ErrorMessage message={passwordError}/>
      </Box>
    </FormDialog>
  </Box>
}
