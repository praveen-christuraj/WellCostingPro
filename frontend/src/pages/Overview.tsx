import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Avatar, Box, Button, CircularProgress, Paper, Typography } from '@mui/material'
import { ArrowForwardRounded, ArrowOutwardRounded, AdminPanelSettingsOutlined, PeopleOutline, ShieldOutlined, VpnKeyOutlined } from '@mui/icons-material'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
import { api } from '../lib/api'
import type { Overview as OverviewType } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { useColorMode } from '../context/ThemeContext'
import { PageHeading, Tag } from '../components/Common'

// Module dashboard/summary for User Management (the module shipped so far).
export default function Overview() {
  const { user, can } = useAuth()
  const { mode } = useColorMode()
  const [data, setData] = useState<OverviewType | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api<OverviewType>('/overview').then(setData).catch(e => setError(e.message)) }, [])
  const dark = mode === 'dark'
  const cards = [
    { title: 'Total users', value: data?.users, icon: PeopleOutline, color: dark ? '#8FB8E4' : '#123A63', bg: dark ? '#1B2F48' : '#E8EEF6', note: `${data?.active_users ?? 0} active members` },
    { title: 'Active roles', value: data?.roles, icon: AdminPanelSettingsOutlined, color: dark ? '#A7B8CB' : '#4A6F96', bg: dark ? '#22364E' : '#EDF1F7', note: 'Defined access groups' },
    { title: 'Permissions', value: data?.permissions, icon: VpnKeyOutlined, color: dark ? '#E8C27A' : '#8A5A00', bg: dark ? '#2E2718' : '#F7F1E4', note: 'Available capabilities' },
    { title: 'Access status', value: data ? `${data.users ? Math.round(data.active_users / data.users * 100) : 0}%` : undefined, icon: ShieldOutlined, color: dark ? '#82C7A2' : '#1E6B45', bg: dark ? '#1B2E24' : '#E7F2EC', note: 'Users currently active' },
  ]
  return <><PageHeading eyebrow="DASHBOARD / USER MANAGEMENT" title={`Good to see you, ${user?.full_name.split(' ')[0]}.`} subtitle={`Module summary for ${user?.organization_name}.`} action={can('users:create') ? <Button component={Link} to="/users" variant="contained" endIcon={<ArrowForwardRounded/>}>Manage team</Button> : undefined}/>{error && <Typography color="error">{error}</Typography>}{!data ? <Box py={8} textAlign="center"><CircularProgress/></Box> : <><Box className="stat-grid">{cards.map(({ title, value, icon: Icon, color, bg, note }) => <Paper key={title} className="stat-card" variant="outlined"><Box display="flex" justifyContent="space-between" alignItems="start"><Box className="stat-icon" sx={{ color, bgcolor: bg }}><Icon sx={{ fontSize: 21 }}/></Box><ArrowOutwardRounded sx={{ color: 'text.disabled', fontSize: 18 }}/></Box><Typography className="stat-value">{value}</Typography><Typography fontWeight={700} fontSize={13}>{title}</Typography><Typography color="text.secondary" fontSize={11.5} mt={.5}>{note}</Typography></Paper>)}</Box><Box className="overview-grid"><Paper className="content-card" variant="outlined"><Box display="flex" justifyContent="space-between" alignItems="start"><Box><Typography fontWeight={800} fontFamily="Manrope" fontSize={16}>Role distribution</Typography><Typography fontSize={12} color="text.secondary" mt={.5}>Members assigned to each role</Typography></Box><Tag tone="success">Live data</Tag></Box>{data.role_distribution.length ? <ReactEChartsCore echarts={echarts} style={{ height: 272, width: '100%', marginTop: 14 }} option={{ grid: { left: 8, right: 15, top: 25, bottom: 12, containLabel: true }, xAxis: { type: 'category', data: data.role_distribution.map(r => r.name), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: dark ? '#A7B8CB' : '#5B6B7F', fontSize: 11 } }, yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: dark ? '#27405C' : '#E3E9F0', type: 'dashed' } }, axisLabel: { color: dark ? '#A7B8CB' : '#5B6B7F' } }, tooltip: { trigger: 'axis' }, series: [{ type: 'bar', data: data.role_distribution.map(r => r.count), barMaxWidth: 42, itemStyle: { color: dark ? '#8FB8E4' : '#123A63', borderRadius: [3, 3, 0, 0] } }] }} /> : <Box display="grid" sx={{ placeItems: 'center', height: 260, color: 'text.secondary' }}>Create a role to see distribution</Box>}</Paper><Paper className="content-card" variant="outlined"><Box display="flex" justifyContent="space-between" alignItems="center" mb={2.2}><Box><Typography fontWeight={800} fontFamily="Manrope" fontSize={16}>Recently added</Typography><Typography fontSize={12} color="text.secondary" mt={.5}>The latest people in your workspace</Typography></Box>{can('users:read') && <Button component={Link} to="/users" size="small" endIcon={<ArrowForwardRounded/>}>View all</Button>}</Box>{data.recent_users.map(person => <Box key={person.id} display="flex" alignItems="center" gap={1.5} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.5 }}><Avatar sx={{ width: 35, height: 35, bgcolor: 'primary.light', color: 'primary.dark', fontSize: 12, fontWeight: 800 }}>{person.full_name.split(' ').map(x => x[0]).slice(0, 2).join('').toUpperCase()}</Avatar><Box flex={1} minWidth={0}><Typography fontSize={12.5} fontWeight={700} noWrap>{person.full_name}</Typography><Typography fontSize={11} color="text.secondary" noWrap>{person.email}</Typography></Box><Tag tone={person.is_active ? 'success' : 'neutral'}>{person.is_active ? 'Active' : 'Inactive'}</Tag></Box>)}</Paper></Box><Paper variant="outlined" className="welcome-strip"><Box className="welcome-symbol"><ShieldOutlined sx={{ fontSize: 26 }}/></Box><Box flex={1}><Typography fontFamily="Manrope" fontWeight={800} fontSize={15}>Your workspace, your rules.</Typography><Typography fontSize={12} color="text.secondary" mt={.5}>Create custom roles and permissions to give every team member exactly the access they need.</Typography></Box>{can('roles:read') && <Button component={Link} to="/roles" variant="outlined" size="small" endIcon={<ArrowForwardRounded/>}>Explore roles</Button>}</Paper></>}</>
}
