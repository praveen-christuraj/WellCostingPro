import { useCallback, useEffect, useMemo, useState } from 'react'
import { Box, Button, TextField, Typography } from '@mui/material'
import { AddRounded, DeleteOutlineRounded, EditOutlined, VpnKeyOutlined } from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body } from '../lib/api'
import type { Permission } from '../lib/types'
import { useAuth } from '../context/AuthContext'
import { ErrorMessage, FormDialog, PageHeading, Tag } from '../components/Common'
import { DataTable } from '../components/DataTable'

export default function Permissions() {
  const { can } = useAuth()
  const [rows, setRows] = useState<Permission[]>([])
  const [dialog, setDialog] = useState<'create' | 'edit' | 'delete' | null>(null)
  const [selected, setSelected] = useState<Permission | null>(null)
  const [key, setKey] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => { try { setRows(await api<Permission[]>('/permissions')) } catch (e) { setError((e as Error).message) } }, [])
  useEffect(() => { load() }, [load])
  const open = (type: 'create' | 'edit' | 'delete', row?: Permission) => { setDialog(type); setSelected(row || null); setKey(row?.key || ''); setDescription(row?.description || ''); setError('') }
  const save = async () => { setBusy(true); setError(''); try { if (dialog === 'create') await api('/permissions', { method: 'POST', body: body({ key, description }) }); if (dialog === 'edit' && selected) await api(`/permissions/${selected.id}`, { method: 'PATCH', body: body({ description }) }); if (dialog === 'delete' && selected) await api(`/permissions/${selected.id}`, { method: 'DELETE' }); setDialog(null); await load() } catch (e) { setError((e as Error).message) } finally { setBusy(false) } }
  const columns = useMemo<ColDef<Permission>[]>(() => [
    { headerName: 'PERMISSION KEY', field: 'key', minWidth: 225, cellRenderer: ({ data }: { data: Permission }) => <Box display="flex" height="100%" alignItems="center" gap={1}><Box className="table-icon"><VpnKeyOutlined sx={{ fontSize: 16 }}/></Box><Typography fontWeight={700} fontSize={12} sx={{ fontFamily: 'monospace' }}>{data.key}</Typography></Box> },
    { headerName: 'RESOURCE', minWidth: 140, valueGetter: p => p.data?.key.split(':')[0] || '', cellRenderer: ({ value }: { value: string }) => <Box display="flex" alignItems="center" height="100%"><Tag>{value}</Tag></Box> },
    { headerName: 'DESCRIPTION', field: 'description', minWidth: 240, valueFormatter: p => p.value || 'No description' },
    { headerName: 'CREATED', field: 'created_at', valueFormatter: p => p.value ? new Date(p.value).toLocaleDateString() : '', minWidth: 120 },
    { headerName: 'ACTIONS', width: 135, flex: 0, sortable: false, cellRenderer: ({ data }: { data: Permission }) => <Box display="flex" alignItems="center" height="100%">{can('permissions:update') && <Button size="small" onClick={() => open('edit', data)} sx={{ fontSize: 11 }} startIcon={<EditOutlined sx={{ fontSize: 15 }}/>}>Edit</Button>}{can('permissions:delete') && <Button size="small" color="error" onClick={() => open('delete', data)} sx={{ minWidth: 28, px: .5 }} aria-label={`Delete ${data.key}`}><DeleteOutlineRounded sx={{ fontSize: 17 }}/></Button>}</Box> },
  ], [can])
  return <><PageHeading eyebrow="ACCESS MANAGEMENT / CAPABILITIES" title="Permissions" subtitle="Define granular capabilities that can be assigned to roles." action={can('permissions:create') && <Button variant="contained" startIcon={<AddRounded/>} onClick={() => open('create')}>Add permission</Button>}/><ErrorMessage message={!dialog ? error : ''}/><DataTable rows={rows} columns={columns} searchPlaceholder="Search permissions..."/><FormDialog open={!!dialog} title={dialog === 'create' ? 'Add a permission' : dialog === 'edit' ? 'Edit permission' : 'Delete permission?'} onClose={() => setDialog(null)} onSubmit={save} busy={busy} submitLabel={dialog === 'delete' ? 'Delete permission' : 'Save changes'}><Box display="grid" gap={2} pt={.5}>{dialog === 'delete' ? <Typography fontSize={13}>Delete <b>{selected?.key}</b>? This capability will be removed from every role that uses it.</Typography> : <><TextField label="Permission key" required fullWidth value={key} disabled={dialog === 'edit'} onChange={e => setKey(e.target.value.toLowerCase())} helperText="Use resource:action format, e.g. reports:export"/><TextField label="Description" fullWidth multiline rows={3} value={description} onChange={e => setDescription(e.target.value)}/></>}<ErrorMessage message={error}/></Box></FormDialog></>
}
