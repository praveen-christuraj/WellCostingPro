import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Collapse, Divider, IconButton, MenuItem,
  Table, TableBody, TableCell, TableHead, TablePagination, TableRow, TextField, Tooltip, Typography,
} from '@mui/material'
import {
  AttachFileRounded, CloudUploadRounded, DeleteForeverOutlined, DescriptionOutlined,
  DownloadRounded, EditOutlined, RestoreOutlined, VisibilityOutlined,
} from '@mui/icons-material'
import { ErrorMessage, FormDialog, PanelDialog } from './Common'
import { useAuth } from '../context/AuthContext'
import { api, body, downloadFile, previewFile, uploadFiles } from '../lib/api'
import {
  ACCEPTED_DOCUMENT_EXTENSIONS,
  DOCUMENT_KINDS,
  MAX_DOCUMENT_MB,
  canPreview,
  documentKindLabel,
  formatBytes,
  orderStatusLabel,
  type DocumentUploadResult,
  type OrderDocument,
  type OrderRevision,
  type PoSoOrder,
} from '../lib/vendorMaster'

// The attachment workspace for one PO/SO revision: attach the scanned copies, keep
// the older revisions' files, and recover anything that was removed by mistake.
export function OrderDocumentsDialog({ open, order, onClose, onChanged }: {
  open: boolean
  order: PoSoOrder | null
  onClose: () => void
  onChanged: () => void
}) {
  const { can } = useAuth()
  const [documents, setDocuments] = useState<OrderDocument[]>([])
  const [revisions, setRevisions] = useState<OrderRevision[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [kind, setKind] = useState('po_copy')
  const [label, setLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [bulkResult, setBulkResult] = useState<DocumentUploadResult | null>(null)
  const [removedOpen, setRemovedOpen] = useState(false)
  const [editing, setEditing] = useState<OrderDocument | null>(null)
  const [editForm, setEditForm] = useState({ document_kind: 'po_copy', label: '', notes: '' })
  const [editError, setEditError] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [removing, setRemoving] = useState<OrderDocument | null>(null)
  const [removeError, setRemoveError] = useState('')
  const [busyRemove, setBusyRemove] = useState(false)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)

  const load = useCallback(async (target: PoSoOrder) => {
    setLoading(true)
    setError('')
    try {
      const [files_, history] = await Promise.all([
        api<OrderDocument[]>(`/master-data/po-so-orders/${target.id}/documents?include_deleted=true`),
        api<OrderRevision[]>(`/master-data/po-so-orders/${target.id}/revisions`),
      ])
      setDocuments(files_)
      setRevisions(history)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the attached files')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open || !order) return
    setFiles([]); setLabel(''); setNotes(''); setKind('po_copy')
    setNotice(''); setUploadError(''); setBulkResult(null); setPage(0)
    void load(order)
  }, [open, order, load])

  const active = useMemo(() => documents.filter(item => !item.is_deleted), [documents])
  const removed = useMemo(() => documents.filter(item => item.is_deleted), [documents])
  const paged = active.slice(page * pageSize, page * pageSize + pageSize)
  const canUpload = can('master-data:document-upload')
  const canDownload = can('master-data:document-download')

  const refresh = async (message?: string) => {
    if (order) await load(order)
    onChanged()
    if (message) setNotice(message)
  }

  const attach = async () => {
    if (!order || !files.length) return
    setUploading(true); setUploadError(''); setBulkResult(null)
    try {
      const result = await uploadFiles<DocumentUploadResult>(
        `/master-data/po-so-orders/${order.id}/documents`,
        files,
        { document_kind: kind, label, notes },
      )
      setFiles([]); setLabel(''); setNotes('')
      setBulkResult(result.rejected_count ? result : null)
      await refresh(
        `${result.uploaded_count} ${result.uploaded_count === 1 ? 'file was' : 'files were'} attached to ${order.order_number} (Rev ${order.revision_number})`
        + (result.rejected_count ? `; ${result.rejected_count} not attached — see the list below.` : '.'),
      )
    } catch (caught) {
      setUploadError(caught instanceof Error ? caught.message : 'Could not attach these files')
    } finally {
      setUploading(false)
    }
  }

  const bulkAttach = async () => {
    if (!files.length) return
    setUploading(true); setUploadError(''); setBulkResult(null)
    try {
      const result = await uploadFiles<DocumentUploadResult>('/master-data/po-so-orders/documents/bulk', files, { document_kind: kind })
      setBulkResult(result)
      setFiles([])
      await refresh(result.uploaded_count ? `${result.uploaded_count} file(s) matched to their orders.` : undefined)
    } catch (caught) {
      setUploadError(caught instanceof Error ? caught.message : 'Could not attach these files')
    } finally {
      setUploading(false)
    }
  }

  const download = async (document: OrderDocument) => {
    setError('')
    try { await downloadFile(`/master-data/po-so-orders/documents/${document.id}`, document.file_name) }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not download this file') }
  }

  const preview = async (document: OrderDocument) => {
    setError('')
    try { await previewFile(`/master-data/po-so-orders/documents/${document.id}?inline=true`) }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not preview this file') }
  }

  const openEdit = (document: OrderDocument) => {
    setEditing(document)
    setEditForm({ document_kind: document.document_kind, label: document.label, notes: document.notes })
    setEditError('')
  }

  const saveEdit = async () => {
    if (!editing) return
    setSavingEdit(true); setEditError('')
    try {
      await api(`/master-data/po-so-orders/documents/${editing.id}`, {
        method: 'PATCH',
        body: body({ document_kind: editForm.document_kind, label: editForm.label.trim(), notes: editForm.notes.trim() }),
      })
      setEditing(null)
      await refresh('File details updated.')
    } catch (caught) {
      setEditError(caught instanceof Error ? caught.message : 'Could not update this file')
    } finally {
      setSavingEdit(false)
    }
  }

  const softRemove = async (document: OrderDocument) => {
    setBusyRemove(true); setRemoveError('')
    try {
      await api(`/master-data/po-so-orders/documents/${document.id}`, { method: 'DELETE' })
      setRemoving(null)
      await refresh(`${document.file_name} moved to removed files.`)
    } catch (caught) {
      setRemoveError(caught instanceof Error ? caught.message : 'Could not remove this file')
    } finally {
      setBusyRemove(false)
    }
  }

  const restore = async (document: OrderDocument) => {
    try {
      await api(`/master-data/po-so-orders/documents/${document.id}/restore`, { method: 'POST' })
      await refresh(`${document.file_name} restored.`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not restore this file')
    }
  }

  const purge = async (document: OrderDocument) => {
    setBusyRemove(true); setRemoveError('')
    try {
      await api(`/master-data/po-so-orders/documents/${document.id}/permanent`, { method: 'DELETE' })
      setRemoving(null)
      await refresh(`${document.file_name} permanently deleted.`)
    } catch (caught) {
      setRemoveError(caught instanceof Error ? caught.message : 'Could not permanently delete this file')
    } finally {
      setBusyRemove(false)
    }
  }

  if (!order) return null

  return <>
    <PanelDialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      title={`${order.order_type} ${order.order_number} — attached files`}
      subtitle={`Revision ${order.revision_number} · ${order.vendor_code} — ${order.vendor_name} · ${orderStatusLabel(order.status)}`}
    >
      <Box display="grid" gap={2} pt={.5}>
        {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ fontSize: 12.5 }}>{notice}</Alert>}
        <ErrorMessage message={error}/>

        {canUpload && <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2 }}>
          <Typography fontSize={12.5} fontWeight={800} mb={.4}>Attach the scanned copy</Typography>
          <Typography fontSize={11.5} color="text.secondary" mb={1.5}>
            PDF, Office, image and mail files up to {MAX_DOCUMENT_MB} MB. Filenames such as <code>{order.order_number}.pdf</code> or
            <code> {order.order_number}_Rev1.pdf</code> let bulk attach find the right order and revision.
          </Typography>
          <Box display="flex" gap={1.2} flexWrap="wrap" alignItems="center">
            <Button component="label" variant="outlined" size="small" startIcon={<CloudUploadRounded sx={{ fontSize: 18 }}/>} disabled={uploading}>
              Choose files
              <input
                hidden
                multiple
                type="file"
                accept={ACCEPTED_DOCUMENT_EXTENSIONS}
                onChange={event => { setFiles(Array.from(event.target.files ?? [])); event.target.value = '' }}
              />
            </Button>
            <TextField select size="small" label="File type" value={kind} onChange={event => setKind(event.target.value)} sx={{ minWidth: 165 }}>
              {DOCUMENT_KINDS.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Label" value={label} onChange={event => setLabel(event.target.value)} sx={{ minWidth: 150 }} inputProps={{ maxLength: 200 }}/>
            <TextField size="small" label="Note" value={notes} onChange={event => setNotes(event.target.value)} sx={{ minWidth: 190 }} inputProps={{ maxLength: 500 }}/>
          </Box>
          {files.length > 0 && <Box mt={1.2} display="flex" gap={.6} flexWrap="wrap">
            {files.map(file => <Chip key={`${file.name}-${file.size}`} size="small" label={`${file.name} · ${formatBytes(file.size)}`}/>)}
          </Box>}
          <Box mt={1.5} display="flex" gap={1} flexWrap="wrap">
            <Button variant="contained" size="small" disabled={!files.length || uploading} onClick={() => void attach()} startIcon={<AttachFileRounded sx={{ fontSize: 17 }}/>}>
              {uploading ? 'Attaching...' : `Attach ${files.length || ''} to this revision`.trim()}
            </Button>
            <Tooltip title="Matches each file name to an order number in this workspace and attaches it to that revision">
              <span><Button variant="outlined" size="small" disabled={!files.length || uploading} onClick={() => void bulkAttach()}>Bulk attach by file name</Button></span>
            </Tooltip>
          </Box>
          <ErrorMessage message={uploadError}/>
          {bulkResult && <Box mt={1.5} display="grid" gap={.6}>
            <Typography fontSize={12} fontWeight={800}>{bulkResult.uploaded_count} attached · {bulkResult.rejected_count} not attached</Typography>
            {bulkResult.items.map(item => <Typography key={`${item.file_name}-${item.document_id ?? item.message}`} fontSize={11.5} color={item.accepted ? 'text.secondary' : 'error.main'}>
              {item.accepted ? '•' : '✕'} {item.file_name} — {item.message}
            </Typography>)}
          </Box>}
        </Box>}

        <Box>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={.8}>
            <Typography fontSize={12.5} fontWeight={800}>Files on this revision ({active.length})</Typography>
            {removed.length > 0 && <Button size="small" color="inherit" onClick={() => setRemovedOpen(value => !value)}>
              {removedOpen ? 'Hide' : 'Show'} {removed.length} removed
            </Button>}
          </Box>
          {loading ? <Box py={4} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={22}/></Box>
            : active.length === 0 ? <Typography fontSize={12.5} color="text.secondary" py={2}>No files attached to this revision yet.</Typography>
            : <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, overflow: 'hidden' }}>
              <Table size="small">
                <TableHead><TableRow>
                  {['File', 'Type', 'Size', 'Uploaded', 'Actions'].map(header => <TableCell key={header} sx={{ fontWeight: 800, fontSize: 11 }}>{header}</TableCell>)}
                </TableRow></TableHead>
                <TableBody>{paged.map(document => <TableRow key={document.id} hover>
                  <TableCell sx={{ fontSize: 12 }}>
                    <Typography fontSize={12.5} fontWeight={700}>{document.file_name}</Typography>
                    <Typography fontSize={11} color="text.secondary">{document.label || documentKindLabel(document.document_kind)}{document.notes ? ` · ${document.notes}` : ''}</Typography>
                  </TableCell>
                  <TableCell sx={{ fontSize: 12 }}>{documentKindLabel(document.document_kind)}</TableCell>
                  <TableCell sx={{ fontSize: 12 }}>{formatBytes(document.size_bytes)}</TableCell>
                  <TableCell sx={{ fontSize: 12 }}>
                    {document.uploaded_by_name || '—'}
                    <Typography fontSize={11} color="text.secondary">{new Date(document.created_at).toLocaleString()}</Typography>
                  </TableCell>
                  <TableCell>
                    <Box display="flex" gap={.2}>
                      {canDownload && <Tooltip title="Preview"><span><IconButton size="small" disabled={!canPreview(document.content_type, document.file_name)} onClick={() => void preview(document)} aria-label={`Preview ${document.file_name}`}><VisibilityOutlined sx={{ fontSize: 17 }}/></IconButton></span></Tooltip>}
                      {canDownload && <Tooltip title="Download"><IconButton size="small" onClick={() => void download(document)} aria-label={`Download ${document.file_name}`}><DownloadRounded sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
                      {can('master-data:update') && <Tooltip title="Edit details"><IconButton size="small" onClick={() => openEdit(document)} aria-label={`Edit details of ${document.file_name}`}><EditOutlined sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
                      {can('master-data:document-delete') && <Tooltip title="Remove (recoverable)"><IconButton size="small" color="error" onClick={() => { setRemoving(document); setRemoveError('') }} aria-label={`Remove ${document.file_name}`}><DeleteForeverOutlined sx={{ fontSize: 17 }}/></IconButton></Tooltip>}
                    </Box>
                  </TableCell>
                </TableRow>)}</TableBody>
              </Table>
              <TablePagination
                component="div"
                count={active.length}
                page={page}
                onPageChange={(_event, value) => setPage(value)}
                rowsPerPage={pageSize}
                onRowsPerPageChange={event => { setPageSize(Number(event.target.value)); setPage(0) }}
                rowsPerPageOptions={[20, 50, 100]}
                sx={{ borderTop: '1px solid', borderColor: 'divider' }}
              />
            </Box>}
        </Box>

        <Collapse in={removedOpen} unmountOnExit>
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
            <Typography fontSize={12} fontWeight={800} mb={1}>Removed files ({removed.length})</Typography>
            {removed.map(document => <Box key={document.id} display="flex" alignItems="center" gap={1} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1 }}>
              <DescriptionOutlined sx={{ fontSize: 16, color: 'text.secondary' }}/>
              <Box flex={1} minWidth={0}>
                <Typography fontSize={12} fontWeight={700} noWrap>{document.file_name}</Typography>
                <Typography fontSize={11} color="text.secondary">Removed {document.deleted_at ? new Date(document.deleted_at).toLocaleString() : ''}</Typography>
              </Box>
              {canDownload && <Button size="small" onClick={() => void download(document)} aria-label={`Download removed ${document.file_name}`}>Download</Button>}
              {can('master-data:restore') && <Button size="small" onClick={() => void restore(document)} startIcon={<RestoreOutlined sx={{ fontSize: 15 }}/>} aria-label={`Restore ${document.file_name}`}>Restore</Button>}
              {can('master-data:permanent-delete') && <Button size="small" color="error" onClick={() => { setRemoving(document); setRemoveError('') }} aria-label={`Permanently delete ${document.file_name}`}>Delete</Button>}
            </Box>)}
          </Box>
        </Collapse>

        <Divider/>
        <Box>
          <Typography fontSize={12.5} fontWeight={800} mb={.8}>Revision history</Typography>
          {revisions.map(revision => <Box key={revision.id} display="flex" alignItems="center" gap={1.2} sx={{ borderTop: '1px solid', borderColor: 'divider', py: 1.1 }}>
            <Chip size="small" label={revision.revision_number === 0 ? 'Original' : `Rev ${revision.revision_number}`} color={revision.is_current ? 'primary' : 'default'} variant={revision.is_current ? 'filled' : 'outlined'} sx={{ height: 22, fontSize: 11 }}/>
            <Box flex={1} minWidth={0}>
              <Typography fontSize={12} fontWeight={700} noWrap>{revision.revision_note || (revision.revision_number === 0 ? 'Original issue' : 'Amendment')}</Typography>
              <Typography fontSize={11} color="text.secondary">
                {revision.issue_date ? new Date(revision.issue_date).toLocaleDateString() : 'No issue date'} · {orderStatusLabel(revision.status)} · {revision.document_count} file(s)
                {revision.is_deleted ? ' · in deleted entries' : ''}
              </Typography>
            </Box>
            {revision.is_current && <Chip size="small" label="Current" color="success" sx={{ height: 22, fontSize: 11 }}/>}
          </Box>)}
        </Box>
      </Box>
    </PanelDialog>

    <FormDialog
      open={!!editing}
      title="Edit file details"
      subtitle="Labels and notes make the attachment easy to find later."
      onClose={() => { if (!savingEdit) setEditing(null) }}
      onSubmit={() => void saveEdit()}
      busy={savingEdit}
      submitLabel="Save details"
    >
      <Box display="grid" gap={2} pt={.5}>
        <Typography fontSize={12.5} fontWeight={700}>{editing?.file_name}</Typography>
        <TextField select label="File type" fullWidth value={editForm.document_kind} onChange={event => setEditForm({ ...editForm, document_kind: event.target.value })}>
          {DOCUMENT_KINDS.map(item => <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>)}
        </TextField>
        <TextField label="Label" fullWidth value={editForm.label} onChange={event => setEditForm({ ...editForm, label: event.target.value })} inputProps={{ maxLength: 200 }}/>
        <TextField label="Note" fullWidth multiline minRows={2} value={editForm.notes} onChange={event => setEditForm({ ...editForm, notes: event.target.value })} inputProps={{ maxLength: 500 }}/>
        <ErrorMessage message={editError}/>
      </Box>
    </FormDialog>

    <FormDialog
      open={!!removing}
      title={removing?.is_deleted ? 'Permanently delete this file?' : 'Remove this file?'}
      subtitle={removing?.is_deleted ? 'This cannot be undone.' : 'The file moves to removed files and can be restored from this panel.'}
      onClose={() => { if (!busyRemove) { setRemoving(null); setRemoveError('') } }}
      onSubmit={() => removing && (removing.is_deleted ? void purge(removing) : void softRemove(removing))}
      busy={busyRemove}
      submitLabel={removing?.is_deleted ? 'Permanently delete' : 'Remove file'}
    >
      <Box display="grid" gap={1.5} pt={.5}>
        <Typography fontSize={13}>“{removing?.file_name}” ({formatBytes(removing?.size_bytes ?? 0)}) on {order.order_number} revision {order.revision_number}.</Typography>
        <ErrorMessage message={removeError}/>
      </Box>
    </FormDialog>
  </>
}
