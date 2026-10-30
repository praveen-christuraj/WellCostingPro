import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, CircularProgress, Divider, FormControlLabel, MenuItem, Paper,
  Stack, Switch, TextField, Typography,
} from '@mui/material'
import {
  BackupOutlined, CheckCircleOutlineRounded, CloudDownloadOutlined, CloudUploadOutlined,
  DeleteOutlineRounded, HistoryOutlined, PlayArrowRounded, RestoreOutlined,
  RuleRounded, ScheduleRounded, SettingsOutlined, ShieldOutlined, StorageOutlined,
  VerifiedOutlined, WarningAmberRounded,
} from '@mui/icons-material'
import type { ColDef } from 'ag-grid-community'
import { api, body, downloadFile, uploadFiles } from '../lib/api'
import { DataTable } from '../components/DataTable'
import { ErrorMessage, FormDialog, PageHeading, PanelDialog, Tag } from '../components/Common'
import { useAuth } from '../context/AuthContext'
import {
  fileSize, jobLabel, jobTone, relative, requestLabel, requestTone, scopeLabel, stamp,
  triggerLabel, type BackupChecksum, type BackupCleanup, type BackupJob, type BackupJobList,
  type BackupJobTable, type BackupOverview, type BackupRestoreRequest, type BackupRestoreRequestList,
  type BackupSettings, type BackupValidation, type BackupValidationDetail, type BackupValidationTable,
} from '../lib/backup'

const SETTINGS_BLANK: Omit<BackupSettings, 'id' | 'last_run_at' | 'next_run_at' | 'folder' | 'multi_tenant' | 'allowed_scope' | 'server_time'> = {
  enabled: false, schedule_mode: 'daily', interval_value: 1, run_time: '02:00',
  retention_days: 30, keep_minimum: 5, backup_directory: '', scope: 'workspace', compression_enabled: true,
}

function StatCard({ label, value, note, icon }: { label: string; value: string | number | undefined; note: string; icon: React.ReactNode }) {
  return <Paper className="stat-card" variant="outlined" sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
    <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
      <Typography color="text.secondary" fontSize={10.5} fontWeight={800} letterSpacing={.8} textTransform="uppercase">{label}</Typography>
      <Box className="table-icon">{icon}</Box>
    </Box>
    <Typography className="stat-value" sx={{ fontSize: 25, my: 1 }}>{value === undefined ? '…' : value}</Typography>
    <Typography color="text.secondary" fontSize={11.2} lineHeight={1.45}>{note}</Typography>
  </Paper>
}

export default function BackupRecovery() {
  const { can } = useAuth()
  const canCreate = can('backup:create')
  const canDownload = can('backup:download')
  const canDelete = can('backup:delete')
  const canSettings = can('backup:settings')
  const canRequest = can('backup:restore-request')
  const canApprove = can('backup:restore-approve')
  const canExecute = can('backup:restore-execute')

  const [overview, setOverview] = useState<BackupOverview | null>(null)
  const [jobs, setJobs] = useState<BackupJobList | null>(null)
  const [requests, setRequests] = useState<BackupRestoreRequestList | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // Backup dialogs
  const [backupDialog, setBackupDialog] = useState(false)
  const [backupForm, setBackupForm] = useState({ description: '', scope: 'workspace' as 'workspace' | 'full' })
  const [backupError, setBackupError] = useState('')
  const [running, setRunning] = useState(false)
  const [importDialog, setImportDialog] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importDescription, setImportDescription] = useState('')
  const [importError, setImportError] = useState('')
  const [importing, setImporting] = useState(false)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [settingsDialog, setSettingsDialog] = useState(false)
  const [settingsForm, setSettingsForm] = useState({ ...SETTINGS_BLANK })
  const [settingsError, setSettingsError] = useState('')
  const [savingSettings, setSavingSettings] = useState(false)
  const [tablesDialog, setTablesDialog] = useState<{ job: BackupJob; rows: BackupJobTable[] } | null>(null)
  const [checksumDialog, setChecksumDialog] = useState<{ job: BackupJob; result: BackupChecksum } | null>(null)
  const [cleanupPreview, setCleanupPreview] = useState<BackupCleanup | null>(null)
  const [cleanupBusy, setCleanupBusy] = useState(false)

  // Restore dialogs
  const [requestDialog, setRequestDialog] = useState<BackupJob | null>(null)
  const [requestForm, setRequestForm] = useState({ reason: '', business_impact: '' })
  const [requestError, setRequestError] = useState('')
  const [requestBusy, setRequestBusy] = useState(false)
  const [decision, setDecision] = useState<{ request: BackupRestoreRequest; approve: boolean } | null>(null)
  const [decisionRemarks, setDecisionRemarks] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [decisionBusy, setDecisionBusy] = useState(false)
  const [cancelRequest, setCancelRequest] = useState<BackupRestoreRequest | null>(null)
  const [cancelRemarks, setCancelRemarks] = useState('')
  const [cancelBusy, setCancelBusy] = useState(false)
  const [validation, setValidation] = useState<{ request: BackupRestoreRequest; detail: BackupValidationDetail } | null>(null)
  const [validating, setValidating] = useState('')
  const [executeDialog, setExecuteDialog] = useState<BackupRestoreRequest | null>(null)
  const [executeText, setExecuteText] = useState('')
  const [executeRemarks, setExecuteRemarks] = useState('')
  const [executeError, setExecuteError] = useState('')
  const [executing, setExecuting] = useState(false)
  const [historyDialog, setHistoryDialog] = useState<{ request: BackupRestoreRequest; items: BackupValidation[] } | null>(null)

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const [summary, backups, restore] = await Promise.all([
        api<BackupOverview>('/backup/overview'),
        api<BackupJobList>('/backup/jobs?page_size=50'),
        api<BackupRestoreRequestList>('/backup/restore-requests?page_size=50'),
      ])
      setOverview(summary)
      setJobs(backups)
      setRequests(restore)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The backup module could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const openSettings = async () => {
    setSettingsError('')
    try {
      const current = await api<BackupSettings>('/backup/settings')
      setSettingsForm({
        enabled: current.enabled, schedule_mode: current.schedule_mode, interval_value: current.interval_value,
        run_time: current.run_time, retention_days: current.retention_days, keep_minimum: current.keep_minimum,
        backup_directory: current.backup_directory, scope: current.scope, compression_enabled: current.compression_enabled,
      })
      setSettingsDialog(true)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The backup settings could not be loaded')
    }
  }

  const saveSettings = async () => {
    setSavingSettings(true)
    setSettingsError('')
    try {
      await api<BackupSettings>('/backup/settings', { method: 'PUT', body: body(settingsForm) })
      setSettingsDialog(false)
      setNotice('Backup schedule saved.')
      await load()
    } catch (caught) {
      setSettingsError(caught instanceof Error ? caught.message : 'The settings could not be saved')
    } finally {
      setSavingSettings(false)
    }
  }

  const takeBackup = async () => {
    setRunning(true)
    setBackupError('')
    try {
      const job = await api<BackupJob>('/backup/jobs', {
        method: 'POST', body: body({ description: backupForm.description, scope: backupForm.scope }),
      })
      setBackupDialog(false)
      setBackupForm({ description: '', scope: 'workspace' })
      setNotice(job.status === 'completed'
        ? `Backup ${job.backup_number} completed: ${job.row_count.toLocaleString()} rows across ${job.table_count} tables (${fileSize(job.file_size_bytes)}).`
        : `Backup ${job.backup_number} finished with status ${jobLabel(job.status).toLowerCase()}.`)
      await load()
    } catch (caught) {
      setBackupError(caught instanceof Error ? caught.message : 'The backup could not be taken')
    } finally {
      setRunning(false)
    }
  }

  const importArchive = async () => {
    if (!importFile) { setImportError('Choose the .jsonl.gz archive to import.'); return }
    setImporting(true)
    setImportError('')
    try {
      const job = await uploadFiles<BackupJob>('/backup/jobs/import', [importFile], { description: importDescription }, 'file')
      setImportDialog(false)
      setImportFile(null)
      setImportDescription('')
      if (fileInput.current) fileInput.current.value = ''
      setNotice(`Imported ${job.backup_number} (${job.row_count.toLocaleString()} rows, ${fileSize(job.file_size_bytes)}). It can be validated and restored.`)
      await load()
    } catch (caught) {
      setImportError(caught instanceof Error ? caught.message : 'The archive could not be imported')
    } finally {
      setImporting(false)
    }
  }

  const verify = async (job: BackupJob) => {
    try {
      const result = await api<BackupChecksum>(`/backup/jobs/${job.id}/verify`, { method: 'POST' })
      setChecksumDialog({ job, result })
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The archive could not be verified')
    }
  }

  const showTables = async (job: BackupJob) => {
    try {
      const rows = await api<BackupJobTable[]>(`/backup/jobs/${job.id}/tables`)
      setTablesDialog({ job, rows })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The table list could not be loaded')
    }
  }

  const removeJob = async (job: BackupJob) => {
    try {
      await api<void>(`/backup/jobs/${job.id}`, { method: 'DELETE', action: `Deleting backup ${job.backup_number}` })
      setNotice(`Backup ${job.backup_number} and its file were deleted.`)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The backup could not be deleted')
    }
  }

  const previewCleanup = async () => {
    setCleanupBusy(true)
    try {
      setCleanupPreview(await api<BackupCleanup>('/backup/cleanup?dry_run=true', { method: 'POST' }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Retention could not be checked')
    } finally {
      setCleanupBusy(false)
    }
  }

  const applyCleanup = async () => {
    setCleanupBusy(true)
    try {
      const result = await api<BackupCleanup>('/backup/cleanup', { method: 'POST' })
      setCleanupPreview(null)
      setNotice(result.deleted_count
        ? `Retention removed ${result.deleted_count} archive(s) and freed ${fileSize(result.freed_bytes)}.`
        : 'Retention found nothing to remove: every archive is inside the policy.')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Retention could not be applied')
    } finally {
      setCleanupBusy(false)
    }
  }

  const raiseRequest = async () => {
    if (!requestDialog) return
    setRequestBusy(true)
    setRequestError('')
    try {
      const request = await api<BackupRestoreRequest>('/backup/restore-requests', {
        method: 'POST',
        body: body({ backup_job_id: requestDialog.id, reason: requestForm.reason, business_impact: requestForm.business_impact }),
      })
      setRequestDialog(null)
      setRequestForm({ reason: '', business_impact: '' })
      setNotice(`Restore request ${request.request_number} raised. It needs a second person to approve it.`)
      await load()
    } catch (caught) {
      setRequestError(caught instanceof Error ? caught.message : 'The restore request could not be raised')
    } finally {
      setRequestBusy(false)
    }
  }

  const decide = async () => {
    if (!decision) return
    setDecisionBusy(true)
    setDecisionError('')
    try {
      await api<BackupRestoreRequest>(
        `/backup/restore-requests/${decision.request.id}/${decision.approve ? 'approve' : 'reject'}`,
        { method: 'POST', body: body({ remarks: decisionRemarks }) },
      )
      setNotice(`${decision.request.request_number} ${decision.approve ? 'approved' : 'rejected'}.`)
      setDecision(null)
      setDecisionRemarks('')
      await load()
    } catch (caught) {
      setDecisionError(caught instanceof Error ? caught.message : 'The decision could not be saved')
    } finally {
      setDecisionBusy(false)
    }
  }

  const cancel = async () => {
    if (!cancelRequest) return
    setCancelBusy(true)
    try {
      await api<BackupRestoreRequest>(`/backup/restore-requests/${cancelRequest.id}/cancel`, {
        method: 'POST', body: body({ remarks: cancelRemarks }),
      })
      setNotice(`${cancelRequest.request_number} cancelled.`)
      setCancelRequest(null)
      setCancelRemarks('')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The request could not be cancelled')
    } finally {
      setCancelBusy(false)
    }
  }

  const validate = async (request: BackupRestoreRequest) => {
    setValidating(request.id)
    setError('')
    try {
      const detail = await api<BackupValidationDetail>(`/backup/restore-requests/${request.id}/validate`, { method: 'POST' })
      setValidation({ request, detail })
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The restore could not be validated')
    } finally {
      setValidating('')
    }
  }

  const execute = async () => {
    if (!executeDialog) return
    setExecuting(true)
    setExecuteError('')
    try {
      const result = await api<BackupRestoreRequest>(`/backup/restore-requests/${executeDialog.id}/execute`, {
        method: 'POST', body: body({ confirmation_text: executeText, remarks: executeRemarks }),
      })
      setExecuteDialog(null)
      setExecuteText('')
      setExecuteRemarks('')
      setNotice(`Restored ${result.backup_number}: ${result.rows_restored.toLocaleString()} rows across ${result.tables_restored} tables. A safety backup (${result.pre_restore_backup_number}) was taken first.`)
      await load()
    } catch (caught) {
      setExecuteError(caught instanceof Error ? caught.message : 'The restore could not be completed')
    } finally {
      setExecuting(false)
    }
  }

  const showHistory = async (request: BackupRestoreRequest) => {
    try {
      const items = await api<BackupValidation[]>(`/backup/restore-requests/${request.id}/validations`)
      setHistoryDialog({ request, items })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The restore history could not be loaded')
    }
  }

  const jobRows = jobs?.items ?? []
  const requestRows = requests?.items ?? []

  const jobColumns = useMemo<ColDef<BackupJob>[]>(() => [
    {
      headerName: 'BACKUP', field: 'backup_number', minWidth: 200,
      cellRenderer: ({ data }: { data?: BackupJob }) => data ? <Box display="flex" flexDirection="column" justifyContent="center" height="100%">
        <Typography fontFamily="monospace" fontWeight={700} fontSize={12.5}>{data.backup_number}</Typography>
        <Typography color="text.secondary" fontSize={11}>{data.description || scopeLabel(data.scope)}</Typography>
      </Box> : null,
    },
    {
      headerName: 'STATUS', field: 'status', width: 165, flex: 0,
      cellRenderer: ({ data }: { data?: BackupJob }) => data ? <Box display="flex" alignItems="center" height="100%" gap={.6}>
        <Tag tone={jobTone(data.status)}>{jobLabel(data.status)}</Tag>
      </Box> : null,
    },
    { headerName: 'TRIGGER', field: 'trigger_source', width: 130, flex: 0, valueFormatter: ({ value }) => triggerLabel(String(value)) },
    {
      headerName: 'CONTENTS', field: 'row_count', width: 165, flex: 0, type: 'rightAligned',
      valueFormatter: ({ data }) => data ? `${data.row_count.toLocaleString()} rows · ${data.table_count} tables` : '',
    },
    { headerName: 'SIZE', field: 'file_size_bytes', width: 110, flex: 0, type: 'rightAligned', valueFormatter: ({ value }) => fileSize(Number(value)) },
    {
      headerName: 'TAKEN', field: 'created_at', width: 175, flex: 0,
      valueFormatter: ({ value }) => stamp(String(value)),
    },
    { headerName: 'BY', field: 'requested_by_display', minWidth: 130 },
    {
      headerName: 'ACTIONS', width: 330, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data?: BackupJob }) => {
        if (!data) return null
        const open = Boolean(data.open_request)
        return <Box display="flex" alignItems="center" height="100%" gap={.5}>
          <Button size="small" onClick={() => void showTables(data)} title="Tables in this archive">Tables</Button>
          {canCreate && data.status !== 'running' && data.status !== 'pending' && (
            <Button size="small" onClick={() => void verify(data)} title="Re-hash the file and compare">Verify</Button>
          )}
          {canDownload && data.can_download && (
            <Button size="small" startIcon={<CloudDownloadOutlined sx={{ fontSize: 15 }}/>}
              onClick={() => void downloadFile(`/backup/jobs/${data.id}/download`, `${data.backup_number}.jsonl.gz`)}>Download</Button>
          )}
          {canRequest && data.can_restore && !open && (
            <Button size="small" startIcon={<RestoreOutlined sx={{ fontSize: 15 }}/>}
              onClick={() => { setRequestDialog(data); setRequestForm({ reason: '', business_impact: '' }); setRequestError('') }}>Restore</Button>
          )}
          {open && <Tag tone="info">{open}</Tag>}
          {canDelete && !open && (
            <Button size="small" color="error" onClick={() => void removeJob(data)} title="Delete this archive and its file">
              <DeleteOutlineRounded sx={{ fontSize: 16 }}/>
            </Button>
          )}
        </Box>
      },
    },
  ], [canCreate, canDelete, canDownload, canRequest, load]) // eslint-disable-line react-hooks/exhaustive-deps

  const requestColumns = useMemo<ColDef<BackupRestoreRequest>[]>(() => [
    {
      headerName: 'REQUEST', field: 'request_number', minWidth: 220,
      cellRenderer: ({ data }: { data?: BackupRestoreRequest }) => data ? <Box display="flex" flexDirection="column" justifyContent="center" height="100%">
        <Typography fontFamily="monospace" fontWeight={700} fontSize={12.5}>{data.request_number}</Typography>
        <Typography color="text.secondary" fontSize={11}>from {data.backup_number}</Typography>
      </Box> : null,
    },
    {
      headerName: 'STATUS', field: 'status', width: 165, flex: 0,
      cellRenderer: ({ data }: { data?: BackupRestoreRequest }) => data ? <Box display="flex" alignItems="center" height="100%">
        <Tag tone={requestTone(data.status)}>{requestLabel(data.status)}</Tag>
      </Box> : null,
    },
    { headerName: 'REQUESTED BY', field: 'requested_by_display', minWidth: 135 },
    { headerName: 'REQUESTED', field: 'requested_at', width: 160, flex: 0, valueFormatter: ({ value }) => stamp(String(value)) },
    { headerName: 'REVIEWED BY', field: 'reviewed_by_display', minWidth: 130 },
    {
      headerName: 'VALIDATION', field: 'latest_validation_status', width: 150, flex: 0,
      cellRenderer: ({ data }: { data?: BackupRestoreRequest }) => data ? <Box display="flex" alignItems="center" height="100%">
        {data.latest_validation_status
          ? <Tag tone={data.latest_validation_status === 'passed' ? 'success' : data.latest_validation_status === 'passed_with_warnings' ? 'warning' : 'error'}>
            {data.latest_validation_status.replaceAll('_', ' ')}
          </Tag>
          : <Typography color="text.secondary" fontSize={12}>Not validated</Typography>}
      </Box> : null,
    },
    {
      headerName: 'ACTIONS', width: 420, flex: 0, sortable: false,
      cellRenderer: ({ data }: { data?: BackupRestoreRequest }) => {
        if (!data) return null
        return <Box display="flex" alignItems="center" height="100%" gap={.4} flexWrap="wrap">
          {data.can_approve && canApprove && <>
            <Button size="small" onClick={() => { setDecision({ request: data, approve: true }); setDecisionRemarks(''); setDecisionError('') }}>Approve</Button>
            <Button size="small" color="error" onClick={() => { setDecision({ request: data, approve: false }); setDecisionRemarks(''); setDecisionError('') }}>Reject</Button>
          </>}
          {data.can_validate && canApprove && (
            <Button size="small" startIcon={<RuleRounded sx={{ fontSize: 15 }}/>} disabled={validating === data.id}
              onClick={() => void validate(data)}>{validating === data.id ? 'Checking...' : 'Validate'}</Button>
          )}
          {data.can_execute && canExecute && (
            <Button size="small" color="error" variant="outlined" startIcon={<PlayArrowRounded sx={{ fontSize: 15 }}/>}
              onClick={() => { setExecuteDialog(data); setExecuteText(''); setExecuteRemarks(''); setExecuteError('') }}>Run restore</Button>
          )}
          <Button size="small" startIcon={<HistoryOutlined sx={{ fontSize: 15 }}/>} onClick={() => void showHistory(data)}>History</Button>
          {data.can_cancel && <Button size="small" color="inherit" onClick={() => { setCancelRequest(data); setCancelRemarks('') }}>Cancel</Button>}
        </Box>
      },
    },
  ], [canApprove, canExecute, validating]) // eslint-disable-line react-hooks/exhaustive-deps

  const warnings = overview?.readiness.warnings ?? []

  return <>
    <PageHeading
      eyebrow="OTHER MANAGEMENTS / BACKUP & RECOVERY"
      title="Backup & Recovery"
      subtitle="Workspace archives with a checksum you can re-verify, a retention policy, and a restore that needs a second person and a dry run before anything is replaced."
      action={<>
        {canSettings && <Button variant="outlined" startIcon={<SettingsOutlined/>} onClick={() => void openSettings()}>Settings</Button>}
        {canCreate && <Button variant="outlined" startIcon={<CloudUploadOutlined/>} onClick={() => { setImportDialog(true); setImportError('') }}>Import archive</Button>}
        {canDelete && <Button variant="outlined" startIcon={<DeleteOutlineRounded/>} disabled={cleanupBusy} onClick={() => void previewCleanup()}>Retention</Button>}
        {canCreate && <Button variant="contained" startIcon={<BackupOutlined/>} onClick={() => { setBackupDialog(true); setBackupError('') }}>Take backup now</Button>}
      </>}
    />
    <ErrorMessage message={error}/>
    {notice && <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 2 }}>{notice}</Alert>}
    {warnings.map(warning => <Alert key={warning} severity="warning" icon={<WarningAmberRounded/>} sx={{ mb: 1.5 }}>{warning}</Alert>)}

    {busy && !overview ? <Box py={10} display="grid" sx={{ placeItems: 'center' }}><CircularProgress size={28}/></Box> : <>
      <Box className="stat-grid" sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(5, minmax(0, 1fr))' }, mb: 2.5 }}>
        <StatCard label="Archives" value={overview?.total_backups.toLocaleString()} note={`${overview?.completed ?? 0} completed · ${overview?.failed ?? 0} failed`} icon={<BackupOutlined sx={{ fontSize: 17 }}/>}/>
        <StatCard label="Verified" value={overview?.verified_count.toLocaleString()} note="Checksum re-checked against the file on disk" icon={<VerifiedOutlined sx={{ fontSize: 17 }}/>}/>
        <StatCard label="Open requests" value={overview?.open_requests.toLocaleString()} note="Restore requests waiting for a decision or a run" icon={<RestoreOutlined sx={{ fontSize: 17 }}/>}/>
        <StatCard label="Storage used" value={fileSize(overview?.total_size_bytes)} note={`${overview?.readiness.total_size_bytes ? fileSize(overview.readiness.total_size_bytes) : '0 B'} in this workspace folder`} icon={<StorageOutlined sx={{ fontSize: 17 }}/>}/>
        <StatCard label="Next backup" value={overview?.next_run_at ? relative(overview.next_run_at) : 'Not scheduled'}
          note={overview?.next_run_at ? stamp(overview.next_run_at) : 'Turn the schedule on in Settings'} icon={<ScheduleRounded sx={{ fontSize: 17 }}/>}/>
      </Box>

      <Paper variant="outlined" sx={{ p: 2, mb: 2.5, borderRadius: 2, display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'center' }}>
        <Box display="flex" alignItems="center" gap={1}>
          <ShieldOutlined sx={{ fontSize: 17, color: overview?.readiness.directory_writable ? 'success.main' : 'error.main' }}/>
          <Typography fontSize={12.5}>
            <b>Archive folder:</b> <Box component="code" sx={{ fontSize: 12 }}>{overview?.readiness.directory || '—'}</Box>
          </Typography>
        </Box>
        <Box display="flex" alignItems="center" gap={.8}>
          <Typography fontSize={12.5}><b>Schedule:</b> {scheduleLabel(overview)}</Typography>
        </Box>
        <Typography fontSize={12.5}><b>Retention:</b> {overview?.readiness.retention_days ?? 30} days, keeping at least {overview?.readiness.keep_minimum ?? 5}</Typography>
        <Typography fontSize={12.5}><b>Scope:</b> {scopeLabel(overview?.readiness.scope || 'workspace')}</Typography>
        {overview?.latest_completed_at && <Typography fontSize={12.5} color="text.secondary">Last good backup {relative(overview.latest_completed_at)}</Typography>}
      </Paper>

      <Typography variant="h6" sx={{ mb: 1.2 }}>Archives</Typography>
      <DataTable<BackupJob>
        rows={jobRows}
        columns={jobColumns}
        rowKey="id"
        searchPlaceholder="Search backup number, description, person..."
        exportName="backup-archives"
      />

      <Box display="flex" alignItems="center" justifyContent="space-between" gap={2} mt={3} mb={1.2} flexWrap="wrap">
        <Typography variant="h6">Restore requests</Typography>
        <Typography color="text.secondary" fontSize={12}>
          Two people are always involved: whoever raises the request cannot approve it, and nothing is replaced until a dry run passes.
        </Typography>
      </Box>
      <DataTable<BackupRestoreRequest>
        rows={requestRows}
        columns={requestColumns}
        rowKey="id"
        searchPlaceholder="Search request, backup, person..."
        exportName="restore-requests"
      />
    </>}

    {/* ---------------------------------------------------------------- dialogs */}

    <FormDialog open={backupDialog} title="Take a backup now" maxWidth="sm"
      subtitle="The archive is written to the server, hashed and registered here. It stays available for download and restore."
      onClose={() => setBackupDialog(false)} onSubmit={() => void takeBackup()} busy={running} busyLabel="Writing archive..."
      submitLabel="Take backup" submitDisabled={false}>
      <Stack spacing={2.2} sx={{ pt: .5 }}>
        <TextField label="What is this backup for?" value={backupForm.description} inputProps={{ maxLength: 500 }}
          onChange={event => setBackupForm(form => ({ ...form, description: event.target.value }))}
          helperText="Optional. Recorded with the archive, for example “Before the AFE import”." fullWidth/>
        <TextField select label="Scope" value={backupForm.scope}
          onChange={event => setBackupForm(form => ({ ...form, scope: event.target.value as 'workspace' | 'full' }))}
          helperText={overview?.readiness.scope === 'workspace'
            ? 'This deployment holds more than one workspace, so only this workspace can be archived.'
            : 'Whole database archives include every workspace on this server.'} fullWidth>
          <MenuItem value="workspace">This workspace</MenuItem>
          {overview?.readiness.scope === 'full' && <MenuItem value="full">Whole database</MenuItem>}
        </TextField>
        <Typography color="text.secondary" fontSize={12}>
          {overview?.completed ? `${overview.completed} archive${overview.completed === 1 ? '' : 's'} already on the server; ${fileSize(overview.total_size_bytes)} in total.` : 'This will be the first archive in this workspace.'}
        </Typography>
        <ErrorMessage message={backupError}/>
      </Stack>
    </FormDialog>

    <FormDialog open={importDialog} title="Import an archive" maxWidth="sm"
      subtitle="Register a previously downloaded WellCostIQ archive so it can be validated and restored. It is copied into this workspace folder and hashed."
      onClose={() => setImportDialog(false)} onSubmit={() => void importArchive()} busy={importing} busyLabel="Importing..."
      submitLabel="Import archive" submitDisabled={!importFile}>
      <Stack spacing={2.2} sx={{ pt: .5 }}>
        <Button variant="outlined" component="label" startIcon={<CloudUploadOutlined/>} sx={{ alignSelf: 'flex-start' }}>
          {importFile ? importFile.name : 'Choose archive (.jsonl.gz)'}
          <input ref={fileInput} type="file" hidden accept=".gz,.jsonl.gz,application/gzip"
            onChange={event => { setImportFile(event.target.files?.[0] ?? null); setImportError('') }}/>
        </Button>
        {importFile && <Typography color="text.secondary" fontSize={12}>{fileSize(importFile.size)} · {importFile.name}</Typography>}
        <TextField label="Description" value={importDescription} inputProps={{ maxLength: 500 }}
          onChange={event => setImportDescription(event.target.value)} helperText="Optional, shown with the archive." fullWidth/>
        <Typography color="text.secondary" fontSize={12}>
          An archive from another workspace is refused, and a file that is not a WellCostIQ archive is reported instead of being stored.
        </Typography>
        <ErrorMessage message={importError}/>
      </Stack>
    </FormDialog>

    <FormDialog open={settingsDialog} title="Backup settings" maxWidth="md"
      subtitle="Schedule, retention and where the archives live. The folder is always kept inside the server's backup root."
      onClose={() => setSettingsDialog(false)} onSubmit={() => void saveSettings()} busy={savingSettings}
      submitLabel="Save settings">
      <Stack spacing={2.2} sx={{ pt: .5 }}>
        <FormControlLabel control={<Switch checked={settingsForm.enabled} onChange={event => setSettingsForm(form => ({ ...form, enabled: event.target.checked }))}/>}
          label="Take backups automatically"/>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField select label="Repeat" value={settingsForm.schedule_mode} fullWidth
            onChange={event => setSettingsForm(form => ({ ...form, schedule_mode: event.target.value as typeof form.schedule_mode }))}>
            <MenuItem value="minutes">Every few minutes</MenuItem>
            <MenuItem value="hours">Every few hours</MenuItem>
            <MenuItem value="daily">Every day</MenuItem>
            <MenuItem value="weekly">Every week</MenuItem>
          </TextField>
          <TextField label={settingsForm.schedule_mode === 'daily' || settingsForm.schedule_mode === 'weekly' ? 'Every (days/weeks)' : 'Interval'}
            type="number" value={settingsForm.interval_value} fullWidth inputProps={{ min: 1, max: 10080 }}
            onChange={event => setSettingsForm(form => ({ ...form, interval_value: Number(event.target.value) }))}
            helperText={settingsForm.schedule_mode === 'minutes' ? 'Minutes between backups' : settingsForm.schedule_mode === 'hours' ? 'Hours between backups' : 'Kept for the daily/weekly rhythm'}/>
          <TextField label="Run at (UTC)" value={settingsForm.run_time} fullWidth placeholder="02:00"
            onChange={event => setSettingsForm(form => ({ ...form, run_time: event.target.value }))}
            helperText="24-hour clock, used by the daily and weekly schedules"/>
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField label="Keep for (days)" type="number" value={settingsForm.retention_days} fullWidth inputProps={{ min: 1, max: 3650 }}
            onChange={event => setSettingsForm(form => ({ ...form, retention_days: Number(event.target.value) }))}/>
          <TextField label="Always keep at least" type="number" value={settingsForm.keep_minimum} fullWidth inputProps={{ min: 1, max: 100 }}
            onChange={event => setSettingsForm(form => ({ ...form, keep_minimum: Number(event.target.value) }))}
            helperText="The newest archives are never removed by retention"/>
        </Stack>
        <TextField label="Folder name" value={settingsForm.backup_directory} fullWidth inputProps={{ maxLength: 120 }}
          onChange={event => setSettingsForm(form => ({ ...form, backup_directory: event.target.value }))}
          helperText="A folder name, not a path. Leave blank to use the workspace name."/>
        <TextField select label="Default scope" value={settingsForm.scope} fullWidth
          onChange={event => setSettingsForm(form => ({ ...form, scope: event.target.value as 'workspace' | 'full' }))}
          helperText={settingsForm.scope === 'full' ? 'Full archives are only possible while this server holds one workspace.' : 'Recommended: every workspace keeps its own archive.'}>
          <MenuItem value="workspace">This workspace</MenuItem>
          <MenuItem value="full" disabled={overview?.readiness.scope !== 'full'}>Whole database</MenuItem>
        </TextField>
        <FormControlLabel control={<Checkbox checked={settingsForm.compression_enabled}
          onChange={event => setSettingsForm(form => ({ ...form, compression_enabled: event.target.checked }))}/>}
          label="Compress archives (gzip)"/>
        <ErrorMessage message={settingsError}/>
      </Stack>
    </FormDialog>

    <PanelDialog open={Boolean(tablesDialog)} title={tablesDialog ? `Tables in ${tablesDialog.job.backup_number}` : 'Tables'}
      subtitle="What the archive holds, table by table. Empty tables are listed too."
      onClose={() => setTablesDialog(null)}>
      <Box sx={{ maxHeight: '58vh', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              {['TABLE', 'MODULE', 'ROWS', 'COLUMNS'].map((header, index) => <th key={header} style={{ textAlign: index > 1 ? 'right' : 'left', padding: '8px 10px', fontWeight: 800, fontSize: 10.5, letterSpacing: 1.1, borderBottom: '1px solid var(--wcp-line)' }}>{header}</th>)}
            </tr>
          </thead>
          <tbody>
            {(tablesDialog?.rows ?? []).map(row => <tr key={row.table_name}>
              <td style={{ padding: '7px 10px', fontFamily: 'monospace' }}>{row.table_name}</td>
              <td style={{ padding: '7px 10px', color: 'var(--wcp-muted)' }}>{row.module_group}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right' }} className="tnum">{row.row_count.toLocaleString()}</td>
              <td style={{ padding: '7px 10px', textAlign: 'right' }} className="tnum">{row.column_count}</td>
            </tr>)}
          </tbody>
        </table>
      </Box>
    </PanelDialog>

    <PanelDialog open={Boolean(checksumDialog)} title="Checksum verification"
      subtitle={checksumDialog ? `${checksumDialog.job.backup_number} · ${checksumDialog.job.file_name}` : ''}
      onClose={() => setChecksumDialog(null)}>
      {checksumDialog && <Stack spacing={2}>
        <Alert severity={checksumDialog.result.matched ? 'success' : 'error'} icon={checksumDialog.result.matched ? <CheckCircleOutlineRounded/> : <WarningAmberRounded/>}>
          {checksumDialog.result.matched
            ? 'The file on disk is byte-for-byte the archive that was taken. It is safe to restore from.'
            : 'The file no longer matches its recorded checksum. Treat this archive as damaged and take a fresh backup.'}
        </Alert>
        <Box>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={1.1} color="text.secondary">EXPECTED (SHA-256)</Typography>
          <Typography fontFamily="monospace" fontSize={12.5} sx={{ wordBreak: 'break-all' }}>{checksumDialog.result.expected_checksum || '—'}</Typography>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={1.1} color="text.secondary" sx={{ mt: 1.2 }}>FOUND ON DISK</Typography>
          <Typography fontFamily="monospace" fontSize={12.5} sx={{ wordBreak: 'break-all' }}>{checksumDialog.result.actual_checksum || '—'}</Typography>
        </Box>
        <Typography color="text.secondary" fontSize={12}>Checked {stamp(checksumDialog.result.verified_at)}. The register now shows “{jobLabel(checksumDialog.result.status)}”.</Typography>
      </Stack>}
    </PanelDialog>

    <PanelDialog open={Boolean(cleanupPreview)} title="Retention preview"
      subtitle="Nothing has been removed yet. This is what the policy would delete right now."
      onClose={() => setCleanupPreview(null)}
      footer={<>
        <Button onClick={() => setCleanupPreview(null)} color="inherit">Cancel</Button>
        <Button variant="contained" color="error" disabled={cleanupBusy || !cleanupPreview?.deleted_count} onClick={() => void applyCleanup()}>
          {cleanupBusy ? 'Removing...' : `Remove ${cleanupPreview?.deleted_count ?? 0} archive(s)`}
        </Button>
      </>}>
      {cleanupPreview && <Stack spacing={1.5}>
        <Typography fontSize={13}>
          {cleanupPreview.deleted_count
            ? `${cleanupPreview.deleted_count} archive(s) are older than ${cleanupPreview.retention_days} days and beyond the ${cleanupPreview.keep_minimum} newest, freeing ${fileSize(cleanupPreview.freed_bytes)}.`
            : `Nothing to remove: every archive is inside the ${cleanupPreview.retention_days}-day policy or among the ${cleanupPreview.keep_minimum} newest.`}
        </Typography>
        {cleanupPreview.deleted_jobs.length > 0 && <Box>
          {cleanupPreview.deleted_jobs.map(number => <Typography key={number} fontFamily="monospace" fontSize={12.5}>{number}</Typography>)}
        </Box>}
        <Typography color="text.secondary" fontSize={12}>Archives referenced by an open restore request, or marked as a hold, are always kept.</Typography>
      </Stack>}
    </PanelDialog>

    {/* restore request creation */}
    <FormDialog open={Boolean(requestDialog)} title="Ask for a restore" maxWidth="md"
      subtitle={requestDialog ? `Restoring ${requestDialog.backup_number} (${requestDialog.row_count.toLocaleString()} rows) will replace this workspace's data with the contents of that archive.` : ''}
      onClose={() => setRequestDialog(null)} onSubmit={() => void raiseRequest()} busy={requestBusy}
      submitLabel="Raise request" submitDisabled={requestForm.reason.trim().length < 10}>
      <Stack spacing={2.2} sx={{ pt: .5 }}>
        <Alert severity="info" icon={<RestoreOutlined/>}>
          Someone else must approve this request, and a dry run must pass before the restore can be run. A safety backup of the current data is taken automatically first.
        </Alert>
        <TextField label="Why is this restore needed?" multiline minRows={3} required value={requestForm.reason}
          inputProps={{ maxLength: 1000 }} onChange={event => setRequestForm(form => ({ ...form, reason: event.target.value }))}
          helperText={`${requestForm.reason.trim().length}/10 characters minimum. This text is shown to the approver.`} fullWidth/>
        <TextField label="Business impact while the restore runs" multiline minRows={2} value={requestForm.business_impact}
          inputProps={{ maxLength: 1000 }} onChange={event => setRequestForm(form => ({ ...form, business_impact: event.target.value }))} fullWidth/>
        <ErrorMessage message={requestError}/>
      </Stack>
    </FormDialog>

    <FormDialog open={Boolean(decision)} title={decision?.approve ? 'Approve this restore?' : 'Reject this restore?'} maxWidth="sm"
      subtitle={decision ? `${decision.request.request_number} · ${decision.request.backup_number} · raised by ${decision.request.requested_by_display}` : ''}
      onClose={() => setDecision(null)} onSubmit={() => void decide()} busy={decisionBusy}
      submitLabel={decision?.approve ? 'Approve' : 'Reject'} danger={!decision?.approve}>
      <Stack spacing={2} sx={{ pt: .5 }}>
        {decision && <Box>
          <Typography fontSize={10.5} fontWeight={800} letterSpacing={1.1} color="text.secondary">REASON GIVEN</Typography>
          <Typography fontSize={13} sx={{ whiteSpace: 'pre-wrap' }}>{decision.request.reason}</Typography>
          {decision.request.business_impact && <>
            <Typography fontSize={10.5} fontWeight={800} letterSpacing={1.1} color="text.secondary" sx={{ mt: 1.4 }}>BUSINESS IMPACT</Typography>
            <Typography fontSize={13} sx={{ whiteSpace: 'pre-wrap' }}>{decision.request.business_impact}</Typography>
          </>}
        </Box>}
        <TextField label="Remarks" multiline minRows={2} value={decisionRemarks} inputProps={{ maxLength: 1000 }}
          onChange={event => setDecisionRemarks(event.target.value)} helperText="Recorded against the request." fullWidth/>
        <ErrorMessage message={decisionError}/>
      </Stack>
    </FormDialog>

    <FormDialog open={Boolean(cancelRequest)} title="Cancel this restore request?" maxWidth="sm"
      subtitle={cancelRequest ? `${cancelRequest.request_number} will be closed and can no longer be run.` : ''}
      onClose={() => setCancelRequest(null)} onSubmit={() => void cancel()} busy={cancelBusy} submitLabel="Cancel request" danger>
      <Stack spacing={2} sx={{ pt: .5 }}>
        <TextField label="Remarks" multiline minRows={2} value={cancelRemarks} inputProps={{ maxLength: 1000 }}
          onChange={event => setCancelRemarks(event.target.value)} fullWidth/>
      </Stack>
    </FormDialog>

    <PanelDialog open={Boolean(validation)} title="Restore validation"
      subtitle={validation ? `${validation.detail.validation.validation_number} · ${validation.detail.validation.status.replaceAll('_', ' ')}` : ''}
      onClose={() => setValidation(null)}>
      {validation && <Stack spacing={2}>
        <Alert severity={validation.detail.validation.status === 'passed' ? 'success' : validation.detail.validation.status === 'passed_with_warnings' ? 'warning' : 'error'}>
          {validation.detail.validation.status === 'passed'
            ? 'The archive applies cleanly. The restore can be run.'
            : validation.detail.validation.status === 'passed_with_warnings'
              ? 'The archive applies, but some tables differ from the current data (rows were added or changed since the backup). Review the list before running it.'
              : 'The archive cannot be applied as it stands. Do not run this restore; take a fresh backup instead.'}
        </Alert>
        <Stack direction="row" gap={3} flexWrap="wrap">
          <Typography fontSize={12.5}><b>Tables:</b> {validation.detail.validation.table_count}</Typography>
          <Typography fontSize={12.5}><b>Rows:</b> {validation.detail.validation.row_count.toLocaleString()}</Typography>
          <Typography fontSize={12.5}><b>Checksum:</b> {validation.detail.validation.checksum_matched ? 'matched' : 'not matched'}</Typography>
          <Typography fontSize={12.5}><b>Dry run:</b> {validation.detail.validation.dry_run_performed ? 'done and rolled back' : 'not run'}</Typography>
        </Stack>
        {validation.detail.validation.error_message && <Alert severity="error">{validation.detail.validation.error_message}</Alert>}
        <Box sx={{ maxHeight: '42vh', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
            <thead><tr>
              {['TABLE', 'ARCHIVE ROWS', 'CURRENT ROWS', 'RESULT'].map((header, index) => <th key={header} style={{ textAlign: index ? 'right' : 'left', padding: '8px 10px', fontWeight: 800, fontSize: 10.5, letterSpacing: 1.1, borderBottom: '1px solid var(--wcp-line)' }}>{header}</th>)}
            </tr></thead>
            <tbody>
              {validation.detail.tables.map((row: BackupValidationTable) => <tr key={row.table_name}>
                <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>{row.table_name}</td>
                <td style={{ padding: '6px 10px', textAlign: 'right' }} className="tnum">{row.archive_rows.toLocaleString()}</td>
                <td style={{ padding: '6px 10px', textAlign: 'right' }} className="tnum">{row.database_rows.toLocaleString()}</td>
                <td style={{ padding: '6px 10px', textAlign: 'right' }}><Tag tone={row.status === 'matches' ? 'success' : row.status === 'missing' ? 'error' : 'warning'}>{row.status}</Tag></td>
              </tr>)}
            </tbody>
          </table>
        </Box>
      </Stack>}
    </PanelDialog>

    <FormDialog open={Boolean(executeDialog)} title="Run this restore" maxWidth="md" danger
      subtitle={executeDialog ? `${executeDialog.request_number} · ${executeDialog.backup_number}. This replaces live workspace data.` : ''}
      onClose={() => setExecuteDialog(null)} onSubmit={() => void execute()} busy={executing} busyLabel="Restoring..."
      submitLabel="Restore now" submitDisabled={executeText.trim() !== (executeDialog?.confirmation_phrase ?? '')}>
      <Stack spacing={2.2} sx={{ pt: .5 }}>
        <Alert severity="warning" icon={<WarningAmberRounded/>}>
          Everything currently in this workspace is replaced by the archive. A safety backup is taken automatically first, so this step can be undone by restoring that copy.
        </Alert>
        <Box>
          <Typography fontSize={12.5} sx={{ mb: .8 }}>
            Type <Box component="b" fontFamily="monospace">{executeDialog?.confirmation_phrase}</Box> to confirm.
          </Typography>
          <TextField fullWidth value={executeText} onChange={event => setExecuteText(event.target.value)}
            placeholder={executeDialog?.confirmation_phrase} inputProps={{ style: { fontFamily: 'monospace' } }} autoFocus/>
        </Box>
        <TextField label="Remarks" multiline minRows={2} value={executeRemarks} inputProps={{ maxLength: 1000 }}
          onChange={event => setExecuteRemarks(event.target.value)} fullWidth/>
        <ErrorMessage message={executeError}/>
      </Stack>
    </FormDialog>

    <PanelDialog open={Boolean(historyDialog)} title="Restore history"
      subtitle={historyDialog ? `${historyDialog.request.request_number} · ${historyDialog.request.backup_number}` : ''}
      onClose={() => setHistoryDialog(null)}>
      {historyDialog && <Stack spacing={2}>
        <Stack spacing={.6}>
          <Typography fontSize={12.5}><b>Status:</b> <Tag tone={requestTone(historyDialog.request.status)}>{requestLabel(historyDialog.request.status)}</Tag></Typography>
          <Typography fontSize={12.5}><b>Reason:</b> {historyDialog.request.reason}</Typography>
          <Typography fontSize={12.5}><b>Raised:</b> {historyDialog.request.requested_by_display} · {stamp(historyDialog.request.requested_at)}</Typography>
          {historyDialog.request.reviewed_by_display && <Typography fontSize={12.5}><b>Reviewed:</b> {historyDialog.request.reviewed_by_display} · {stamp(historyDialog.request.reviewed_at)}{historyDialog.request.review_remarks ? ` — ${historyDialog.request.review_remarks}` : ''}</Typography>}
          {historyDialog.request.executed_by_display && <Typography fontSize={12.5}><b>Executed:</b> {historyDialog.request.executed_by_display} · {stamp(historyDialog.request.executed_at)}</Typography>}
          {historyDialog.request.pre_restore_backup_number && <Typography fontSize={12.5}><b>Safety backup:</b> <Box component="span" fontFamily="monospace">{historyDialog.request.pre_restore_backup_number}</Box></Typography>}
          {historyDialog.request.error_message && <Alert severity="error">{historyDialog.request.error_message}</Alert>}
        </Stack>
        <Divider/>
        <Typography fontWeight={800} fontSize={13}>Validation runs</Typography>
        {historyDialog.items.length === 0 ? <Typography color="text.secondary" fontSize={12.5}>The restore has not been validated yet.</Typography>
          : historyDialog.items.map(item => <Paper key={item.id} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
            <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap">
              <Typography fontFamily="monospace" fontSize={12.5}>{item.validation_number}</Typography>
              <Tag tone={item.status === 'passed' ? 'success' : item.status === 'passed_with_warnings' ? 'warning' : item.status === 'running' ? 'info' : 'error'}>{item.status.replaceAll('_', ' ')}</Tag>
            </Box>
            <Typography color="text.secondary" fontSize={11.5} sx={{ mt: .5 }}>
              {item.started_by_display} · {stamp(item.started_at)} · {item.table_count} tables · {item.row_count.toLocaleString()} rows
              {item.changed_tables ? ` · ${item.changed_tables} different, ${item.missing_tables} missing` : ''}
            </Typography>
            {item.error_message && <Typography color="error" fontSize={11.5} sx={{ mt: .5 }}>{item.error_message}</Typography>}
          </Paper>)}
      </Stack>}
    </PanelDialog>
  </>
}

function scheduleLabel(overview: BackupOverview | null): string {
  if (!overview) return 'Not configured'
  if (!overview.scheduled) return 'Scheduled backups are off'
  const next = overview.next_run_at ? `next ${relative(overview.next_run_at)}` : 'next run pending'
  const previous = overview.readiness.last_run_at ? `, last ${relative(overview.readiness.last_run_at)}` : ''
  return `On, ${next}${previous}`
}
