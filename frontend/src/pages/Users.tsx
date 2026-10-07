import { useCallback, useEffect, useMemo, useState } from 'react'
import { Avatar, Box, Button, Checkbox, FormControlLabel, MenuItem, Select, TextField, Typography } from '@mui/material'
import { AddRounded, EditOutlined, ManageAccountsOutlined } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body } from '../lib/api'
import type { Role, User } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'

export default function Users() {
  const { can, user: me } = useAuth()
  const [rows, setRows] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [dialog, setDialog] = useState<'create' | 'edit' | 'roles' | null>(null)
  const [selected, setSelected] = useState<User | null>(null)
  const [form, setForm] = useState({ full_name: '', email: '', password: '', role_ids: [] as string[], is_active: true })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { try { setRows(await api<User[]>('/users')); if (can('roles:read')) setRoles(await api<Role[]>('/roles')) } catch (e) { setError((e as Error).message) } }, [can])
  useEffect(() => { load() }, [load])
  const open = (type: 'create' | 'edit' | 'roles', row?: User) => { setSelected(row || null); setForm({ full_name: row?.full_name || '', email: row?.email || '', password: '', role_ids: row?.roles.map(r => r.id) || [], is_active: row?.is_active ?? true }); setError(''); setDialog(type) }
  const save = async () => { setBusy(true); setError(''); try {
    if (dialog === 'create') await api('/users', { method: 'POST', body: body({ full_name: form.full_name, email: form.email, password: form.password, role_ids: form.role_ids }) })
    if (dialog === 'edit' && selected) await api(`/users/${selected.id}`, { method: 'PATCH', body: body({ full_name: form.full_name, is_active: form.is_active }) })
    if (dialog === 'roles' && selected) await api(`/users/${selected.id}/roles`, { method: 'PUT', body: body({ ids: form.role_ids }) })
    setDialog(null); await load()
  } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  const columns = useMemo<ColDef<User>[]>(() => [
    { headerName: 'USER', field: 'full_name', minWidth: 235, flex: 1.5, cellRenderer: ({ data }: { data: User }) => data && <Box display="flex" alignItems="center" gap={1.2} height="100%"><Avatar sx={{ width: 31, height: 31, bgcolor: '#e9f3f0', color: '#10766f', fontSize: 11, fontWeight: 800 }}>{data.full_name.split(' ').map(x => x[0]).slice(0,2).join('').toUpperCase()}</Avatar><Box><Typography fontWeight={700} fontSize={12}>{data.full_name}</Typography><Typography color="text.secondary" fontSize={11}>{data.email}</Typography></Box></Box> },
    { headerName: 'ROLES', valueGetter: p => p.data?.roles.map(r => r.name).join(', ') || '—', minWidth: 160, cellRenderer: ({ data }: { data: User }) => <Box display="flex" alignItems="center" gap={.5} height="100%" flexWrap="wrap">{data.roles.length ? data.roles.slice(0, 2).map(r => <Tag key={r.id}>{r.name}</Tag>) : <Typography color="text.secondary" fontSize={12}>No role</Typography>}</Box> },
    { headerName: 'STATUS', field: 'is_active', width: 125, flex: 0, cellRenderer: ({ value }: { value: boolean }) => <Box display="flex" alignItems="center" height="100%"><Tag tone={value ? 'green' : 'neutral'}>{value ? 'Active' : 'Inactive'}</Tag></Box> },
    { headerName: 'JOINED', field: 'created_at', valueFormatter: p => p.value ? new Date(p.value).toLocaleDateString() : '', minWidth: 120 },
    { headerName: 'ACTIONS', width: 185, flex: 0, sortable: false, cellRenderer: ({ data }: { data: User }) => <Box display="flex" height="100%" alignItems="center" gap={.5}>{can('users:update') && <Button size="small" onClick={() => open('edit', data)} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>} sx={{ fontSize: 11, minWidth: 0 }}>Edit</Button>}{can('assignments:write') && !data.roles.some(r => r.is_owner) && <Button size="small" onClick={() => open('roles', data)} startIcon={<ManageAccountsOutlined sx={{ fontSize: 15 }}/>} sx={{ fontSize: 11, minWidth: 0 }}>Roles</Button>}</Box> },
  ], [can])
  return <><PageHeading eyebrow="ACCESS MANAGEMENT / PEOPLE" title="Users" subtitle="Invite, manage and organize everyone in your workspace." action={can('users:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => open('create')}>Add user</Button>}/><ErrorMessage message={!dialog ? error : ''}/><DataTable rows={rows} columns={columns} searchPlaceholder="Search users..."/><FormDialog open={!!dialog} onClose={() => setDialog(null)} onSubmit={save} busy={busy} title={dialog === 'create' ? 'Add a new user' : dialog === 'roles' ? 'Assign roles' : 'Edit user'} subtitle={dialog === 'roles' ? `Choose roles for ${selected?.full_name}` : 'Set up workspace access for your team member.'} submitLabel={dialog === 'create' ? 'Create user' : 'Save changes'}><Box display="grid" gap={2} pt={.5}>{dialog !== 'roles' ? <><TextField label="Full name" required fullWidth value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })}/>{dialog === 'create' ? <><TextField label="Email address" type="email" required fullWidth value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}/><TextField label="Temporary password" type="password" required fullWidth helperText="At least 12 characters. Share it securely with the user." value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}/>{can('roles:read') && can('assignments:write') && <Select multiple displayEmpty fullWidth size="small" value={form.role_ids} onChange={e => setForm({ ...form, role_ids: e.target.value as string[] })} renderValue={ids => ids.length ? roles.filter(r => ids.includes(r.id)).map(r => r.name).join(', ') : 'Select roles (optional)'}>{roles.filter(r => !r.is_owner).map(r => <MenuItem key={r.id} value={r.id}>{r.name}</MenuItem>)}</Select>}</> : <FormControlLabel control={<Checkbox checked={form.is_active} disabled={selected?.id === me?.id || selected?.roles.some(r => r.is_owner)} onChange={e => setForm({ ...form, is_active: e.target.checked })}/>} label="Active account"/>}</> : <>{roles.filter(r => !r.is_owner).map(r => <FormControlLabel key={r.id} control={<Checkbox checked={form.role_ids.includes(r.id)} onChange={e => setForm({ ...form, role_ids: e.target.checked ? [...form.role_ids, r.id] : form.role_ids.filter(id => id !== r.id) })}/>} label={<Box><Typography fontSize={13} fontWeight={700}>{r.name}</Typography><Typography fontSize={11} color="text.secondary">{r.description || `${r.permissions.length} permissions`}</Typography></Box>}/>)}{!roles.filter(r => !r.is_owner).length && <Typography color="text.secondary" fontSize={13}>No assignable roles yet. Create a role first.</Typography>}</>}<ErrorMessage message={error}/></Box></FormDialog></>
}
