import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Button, Checkbox, FormControlLabel, TextField, Typography } from '@mui/material'
import { AddRounded, EditOutlined, DeleteOutlineRounded, TuneRounded } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body } from '../lib/api'
import type { Role, Permission } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'

export default function Roles() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [dialog, setDialog] = useState<'create' | 'edit' | 'assign' | 'delete' | null>(null)
  const [selected, setSelected] = useState<Role | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [ids, setIds] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { try { setRows(await api<Role[]>('/roles')); if (can('permissions:read')) setPermissions(await api<Permission[]>('/permissions')) } catch (e) { setError((e as Error).message) } }, [can])
  useEffect(() => { load() }, [load])
  const open = (type: 'create' | 'edit' | 'assign' | 'delete', row?: Role) => { setDialog(type); setSelected(row || null); setName(row?.name || ''); setDescription(row?.description || ''); setIds(row?.permissions.map(p => p.id) || []); setError('') }
  const save = async () => { setBusy(true); setError(''); try { if (dialog === 'create') await api('/roles', { method: 'POST', body: body({ name, description }) }); if (dialog === 'edit' && selected) await api(`/roles/${selected.id}`, { method: 'PATCH', body: body({ name, description }) }); if (dialog === 'assign' && selected) await api(`/roles/${selected.id}/permissions`, { method: 'PUT', body: body({ ids }) }); if (dialog === 'delete' && selected) await api(`/roles/${selected.id}`, { method: 'DELETE' }); setDialog(null); await load() } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  const groups = useMemo(() => Object.entries(permissions.reduce<Record<string, Permission[]>>((acc, p) => { const group = p.key.split(':')[0]; (acc[group] ||= []).push(p); return acc }, {})), [permissions])
  const columns = useMemo<ColDef<Role>[]>(() => [
    { headerName: 'ROLE NAME', field: 'name', minWidth: 180, cellRenderer: ({ data }: { data: Role }) => <Box display="flex" alignItems="center" height="100%" gap={1}><Box className="table-icon"><TuneRounded sx={{ fontSize: 17 }}/></Box><Typography fontSize={12} fontWeight={700}>{data.name}</Typography>{data.is_owner && <Tag tone="gold">Owner</Tag>}</Box> },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 220, valueFormatter: p => p.value || 'No description' },
    { headerName: 'PERMISSIONS', minWidth: 140, valueGetter: p => p.data?.permissions.length || 0, cellRenderer: ({ value }: { value: number }) => <Box display="flex" alignItems="center" height="100%"><Tag tone="green">{value} capabilities</Tag></Box> },
    { headerName: 'CREATED', field: 'created_at', valueFormatter: p => p.value ? new Date(p.value).toLocaleDateString() : '', minWidth: 120 },
    { headerName: 'ACTIONS', width: 230, flex: 0, sortable: false, cellRenderer: ({ data }: { data: Role }) => <Box display="flex" alignItems="center" height="100%">{!data.is_owner && <>{can('roles:update') && <Button size="small" sx={{ fontSize: 11 }} onClick={() => open('edit', data)} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}{can('assignments:write') && <Button size="small" sx={{ fontSize: 11 }} onClick={() => open('assign', data)} startIcon={<TuneRounded sx={{ fontSize: 15 }}/>}>Access</Button>}{can('roles:delete') && <Button color="error" size="small" sx={{ minWidth: 28, px: .5 }} onClick={() => open('delete', data)} aria-label={`Delete ${data.name}`}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button>}</>}</Box> },
  ], [can])
  return <><PageHeading eyebrow="ACCESS MANAGEMENT / GROUPS" title="Roles" subtitle="Create meaningful access groups and define what each can do." action={can('roles:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => open('create')}>Create role</Button>}/><ErrorMessage message={!dialog ? error : ''}/><DataTable rows={rows} columns={columns} searchPlaceholder="Search roles..."/><FormDialog open={!!dialog} title={dialog === 'create' ? 'Create a role' : dialog === 'edit' ? 'Edit role' : dialog === 'delete' ? 'Delete role?' : `Manage ${selected?.name} access`} subtitle={dialog === 'assign' ? 'Select the capabilities members of this role should have.' : undefined} onClose={() => setDialog(null)} onSubmit={save} busy={busy} submitLabel={dialog === 'delete' ? 'Delete role' : 'Save changes'}><Box display="grid" gap={2} pt={.5}>{dialog === 'delete' ? <Typography fontSize={13}>Deleting <b>{selected?.name}</b> will remove this role from all assigned users. This cannot be undone.</Typography> : dialog === 'assign' ? groups.length ? groups.map(([group, items]) => <Box key={group} sx={{ border: '1px solid #e8eef0', borderRadius: 2, p: 2 }}><Typography textTransform="capitalize" fontWeight={800} fontSize={12} mb={1}>{group}</Typography><Box display="grid" gridTemplateColumns="repeat(2,minmax(0,1fr))">{items.map(p => <FormControlLabel key={p.id} control={<Checkbox size="small" checked={ids.includes(p.id)} onChange={e => setIds(e.target.checked ? [...ids, p.id] : ids.filter(id => id !== p.id))}/>} label={<Typography fontSize={12}>{p.description || p.key}</Typography>}/>)}</Box></Box>) : <Typography fontSize={13} color="text.secondary">No permissions available. Add permissions first.</Typography> : <><TextField label="Role name" required fullWidth value={name} onChange={e => setName(e.target.value)}/><TextField label="Description" fullWidth multiline rows={3} value={description} onChange={e => setDescription(e.target.value)}/></>}<ErrorMessage message={error}/></Box></FormDialog></>
}
