import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Avatar, Box, Divider, Drawer, IconButton, Menu, MenuItem, TextField, Tooltip, Typography } from '@mui/material'
import { DashboardOutlined, PeopleOutline, AdminPanelSettingsOutlined, VpnKeyOutlined, MenuRounded, KeyboardArrowDownRounded, LogoutRounded, ChevronRightRounded, HelpOutlineRounded, ShieldOutlined, AccountTreeOutlined } from '@mui/icons-material'
import Brand from './Brand'
import { FormDialog, ErrorMessage } from './Common'
import { api, body } from '../lib/api'
import { useAuth } from '../context/AuthContext'

const links = [
  { label: 'Overview', path: '/', icon: DashboardOutlined },
  { label: 'Users', path: '/users', icon: PeopleOutline, permission: 'users:read' },
  { label: 'Roles', path: '/roles', icon: AdminPanelSettingsOutlined, permission: 'roles:read' },
  { label: 'Permissions', path: '/permissions', icon: VpnKeyOutlined, permission: 'permissions:read' },
  { label: 'Assignments', path: '/assignments', icon: AccountTreeOutlined, permission: 'assignments:write', requires: ['users:read', 'roles:read', 'permissions:read'] },
]
const width = 258
export default function Layout() {
  const { user, can, logout } = useAuth()
  const [mobile, setMobile] = useState(false)
  const [anchor, setAnchor] = useState<null | HTMLElement>(null)
  const [passwordDialog, setPasswordDialog] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)
  const changePassword = async () => { setSavingPassword(true); setPasswordError(''); try { await api('/auth/change-password', { method: 'POST', body: body({ current_password: currentPassword, new_password: newPassword }) }); setPasswordDialog(false); setCurrentPassword(''); setNewPassword(''); await logout() } catch (e) { setPasswordError((e as Error).message) } finally { setSavingPassword(false) } }
  const location = useLocation()
  const title = links.find(l => l.path === location.pathname)?.label || 'Workspace'
  const sidebar = <Box className="sidebar-content"><Box sx={{ px: 3.3, pt: 4, pb: 4.5 }}><Brand light/></Box><Box sx={{ px: 2 }}><Typography className="nav-caption">WORKSPACE</Typography>{links.filter(l => (!l.permission || can(l.permission)) && (!l.requires || l.requires.every(can))).map(({ label, path, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} onClick={() => setMobile(false)} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}><Icon sx={{ fontSize: 19 }}/><span>{label}</span>{path === location.pathname && <ChevronRightRounded sx={{ ml: 'auto', fontSize: 18 }}/>}</NavLink>)}</Box><Box sx={{ mt: 'auto', px: 2.5, pb: 2.8 }}><Box className="sidebar-note"><ShieldOutlined sx={{ color: '#60d5bb', fontSize: 21, mb: 1.2 }}/><Typography sx={{ color: 'white', fontWeight: 700, fontSize: 13 }}>Access under control</Typography><Typography sx={{ color: '#97aeb8', fontSize: 11.5, mt: .7, lineHeight: 1.55 }}>Manage your team securely with role-based access.</Typography></Box><Divider sx={{ borderColor: '#2c4756', my: 2.5 }}/><Box display="flex" alignItems="center" gap={1.1} sx={{ color: '#91aab5', px: 1 }}><HelpOutlineRounded sx={{ fontSize: 16 }}/><Typography fontSize={12}>WellCosting Pro · v0.1</Typography></Box></Box></Box>
  return <Box display="flex" minHeight="100vh"><Box component="nav" sx={{ width: { md: width }, flexShrink: { md: 0 } }}><Drawer variant="permanent" sx={{ display: { xs: 'none', md: 'block' }, '& .MuiDrawer-paper': { width, bgcolor: '#102b3a', border: 0 } }} open>{sidebar}</Drawer><Drawer variant="temporary" open={mobile} onClose={() => setMobile(false)} sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { width, bgcolor: '#102b3a', border: 0 } }}>{sidebar}</Drawer></Box><Box component="main" sx={{ flexGrow: 1, minWidth: 0 }}><Box className="topbar"><Box display="flex" alignItems="center" gap={1.5}><IconButton sx={{ display: { md: 'none' } }} onClick={() => setMobile(true)}><MenuRounded/></IconButton><Typography sx={{ color: '#8c9ca5', fontSize: 13, display: { xs: 'none', sm: 'block' } }}>Workspace</Typography><ChevronRightRounded sx={{ fontSize: 16, color: '#b0bdc4', display: { xs: 'none', sm: 'block' } }}/><Typography sx={{ color: '#1d3442', fontSize: 13, fontWeight: 700 }}>{title}</Typography></Box><Box display="flex" alignItems="center" gap={2}><Box textAlign="right" sx={{ display: { xs: 'none', sm: 'block' } }}><Typography fontWeight={700} fontSize={12.5} lineHeight={1.3}>{user?.full_name}</Typography><Typography color="text.secondary" fontSize={11.5}>{user?.organization_name}</Typography></Box><Tooltip title="Account menu"><IconButton onClick={e => setAnchor(e.currentTarget)} sx={{ p: .4, borderRadius: 2 }}><Avatar sx={{ width: 34, height: 34, bgcolor: '#d8ede8', color: '#08665e', fontSize: 12, fontWeight: 800 }}>{user?.full_name.split(' ').map(x => x[0]).slice(0, 2).join('').toUpperCase()}</Avatar><KeyboardArrowDownRounded sx={{ color: '#7f9299', ml: .4, fontSize: 18 }}/></IconButton></Tooltip><Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}><MenuItem onClick={() => { setAnchor(null); setPasswordDialog(true); setPasswordError('') }}>Change password</MenuItem><MenuItem onClick={() => { setAnchor(null); logout() }}><LogoutRounded sx={{ mr: 1, fontSize: 18 }}/> Sign out</MenuItem></Menu></Box></Box><Box sx={{ px: { xs: 2.5, sm: 4, xl: 6 }, py: { xs: 3, sm: 4 }, maxWidth: 1600, mx: 'auto' }}><Outlet/></Box><FormDialog open={passwordDialog} title="Change your password" subtitle="You will be signed out of all sessions after updating." onClose={() => setPasswordDialog(false)} onSubmit={changePassword} busy={savingPassword} submitLabel="Update password"><Box display="grid" gap={2} pt={.5}><TextField label="Current password" type="password" fullWidth value={currentPassword} onChange={e => setCurrentPassword(e.target.value)}/><TextField label="New password" type="password" fullWidth helperText="At least 12 characters" value={newPassword} onChange={e => setNewPassword(e.target.value)}/><ErrorMessage message={passwordError}/></Box></FormDialog></Box></Box>
}
