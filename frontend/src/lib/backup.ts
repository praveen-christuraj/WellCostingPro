// Backup & Recovery contracts and display helpers.
// The API stores every fact as a column, so nothing here parses a payload.

export type BackupSettings = {
  id: string
  enabled: boolean
  schedule_mode: 'minutes' | 'hours' | 'daily' | 'weekly'
  interval_value: number
  run_time: string
  retention_days: number
  keep_minimum: number
  backup_directory: string
  scope: 'workspace' | 'full'
  compression_enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  folder: string
  multi_tenant: boolean
  allowed_scope: string
  server_time: string
}

export type BackupJob = {
  id: string
  backup_number: string
  scope: string
  trigger_source: string
  status: string
  description: string
  file_name: string
  file_size_bytes: number
  checksum_sha256: string
  format_version: number
  compression: string
  schema_revision: string
  table_count: number
  row_count: number
  audit_row_count: number
  requested_by_display: string
  started_at: string | null
  completed_at: string | null
  checksum_verified_at: string | null
  error_message: string
  retention_hold: boolean
  created_at: string
  can_download: boolean
  can_restore: boolean
  open_request: string
}

export type BackupJobTable = {
  table_name: string
  module_group: string
  row_count: number
  column_count: number
}

export type BackupJobList = { items: BackupJob[]; total: number; page: number; page_size: number; pages: number }

export type BackupReadiness = {
  directory: string
  directory_writable: boolean
  scheduled: boolean
  next_run_at: string | null
  last_run_at: string | null
  retention_days: number
  keep_minimum: number
  scope: string
  backup_count: number
  completed_count: number
  open_restore_requests: number
  failed_recently: number
  total_size_bytes: number
  latest_backup: BackupJob | null
  warnings: string[]
}

export type BackupOverview = {
  total_backups: number
  completed: number
  failed: number
  checksum_mismatch: number
  running: number
  total_size_bytes: number
  latest_completed_at: string | null
  verified_count: number
  scheduled: boolean
  next_run_at: string | null
  open_requests: number
  restored_count: number
  readiness: BackupReadiness
}

export type BackupValidation = {
  id: string
  validation_number: string
  status: string
  checksum_matched: boolean
  dry_run_performed: boolean
  table_count: number
  row_count: number
  missing_tables: number
  changed_tables: number
  error_message: string
  started_by_display: string
  started_at: string
  completed_at: string | null
}

export type BackupValidationTable = {
  table_name: string
  archive_rows: number
  database_rows: number
  status: string
}

export type BackupValidationDetail = { validation: BackupValidation; tables: BackupValidationTable[] }

export type BackupRestoreRequest = {
  id: string
  request_number: string
  backup_job_id: string
  backup_number: string
  backup_file_name: string
  backup_scope: string
  backup_status: string
  status: string
  reason: string
  business_impact: string
  requested_by_display: string
  requested_at: string
  reviewed_by_display: string
  reviewed_at: string | null
  review_remarks: string
  validated_at: string | null
  executed_by_display: string
  executed_at: string | null
  execution_remarks: string
  pre_restore_backup_number: string
  tables_restored: number
  rows_restored: number
  error_message: string
  confirmation_phrase: string
  can_approve: boolean
  can_validate: boolean
  can_execute: boolean
  can_cancel: boolean
  latest_validation_status: string
}

export type BackupRestoreRequestList = {
  items: BackupRestoreRequest[]
  total: number
  page: number
  page_size: number
  pages: number
}

export type BackupCleanup = {
  deleted_jobs: string[]
  deleted_count: number
  freed_bytes: number
  kept_count: number
  retention_days: number
  keep_minimum: number
  dry_run: boolean
}

export type BackupChecksum = {
  matched: boolean
  expected_checksum: string
  actual_checksum: string
  verified_at: string | null
  status: string
}

/** Bytes as a person reads them (1.2 MB, 640 KB, 12 bytes). */
export function fileSize(bytes: number | null | undefined): string {
  const value = Number(bytes || 0)
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export function stamp(value: string | null | undefined, withTime = true): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, withTime
    ? { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { year: 'numeric', month: 'short', day: '2-digit' })
}

export function relative(value: string | null | undefined): string {
  if (!value) return ''
  const moment = new Date(value).getTime()
  if (Number.isNaN(moment)) return ''
  const minutes = Math.round((Date.now() - moment) / 60000)
  if (Math.abs(minutes) < 1) return 'just now'
  if (minutes > 0) {
    if (minutes < 60) return `${minutes} min ago`
    if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`
    return `${Math.round(minutes / (60 * 24))} d ago`
  }
  const ahead = Math.abs(minutes)
  if (ahead < 60) return `in ${ahead} min`
  if (ahead < 60 * 24) return `in ${Math.round(ahead / 60)} h`
  return `in ${Math.round(ahead / (60 * 24))} d`
}

export function jobLabel(status: string): string {
  return ({
    pending: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed',
    checksum_mismatch: 'Checksum mismatch',
  } as Record<string, string>)[status] || status
}

export function jobTone(status: string): 'neutral' | 'success' | 'warning' | 'error' | 'info' {
  if (status === 'completed') return 'success'
  if (status === 'running' || status === 'pending') return 'info'
  if (status === 'checksum_mismatch') return 'warning'
  if (status === 'failed') return 'error'
  return 'neutral'
}

export function requestLabel(status: string): string {
  return ({
    pending_approval: 'Awaiting approval', approved: 'Approved', rejected: 'Rejected',
    validated: 'Validated', validation_failed: 'Validation failed', restore_running: 'Restoring',
    restored: 'Restored', restore_failed: 'Restore failed', cancelled: 'Cancelled',
  } as Record<string, string>)[status] || status.replaceAll('_', ' ')
}

export function requestTone(status: string): 'neutral' | 'success' | 'warning' | 'error' | 'info' {
  if (status === 'restored' || status === 'validated') return 'success'
  if (status === 'pending_approval' || status === 'approved' || status === 'restore_running') return 'info'
  if (status === 'validation_failed' || status === 'restore_failed' || status === 'rejected') return 'error'
  if (status === 'cancelled') return 'neutral'
  return 'warning'
}

export function triggerLabel(source: string): string {
  return ({ manual: 'Manual', scheduled: 'Scheduled', 'pre-restore': 'Safety copy', import: 'Imported' } as Record<string, string>)[source]
    || source
}

export function scopeLabel(scope: string): string {
  return scope === 'full' ? 'Whole database' : 'This workspace'
}

/** The schedule in one sentence, so the setting never needs decoding. */
export function scheduleText(settings: BackupSettings | null): string {
  if (!settings) return 'Not configured'
  if (!settings.enabled) return 'Scheduled backups are off'
  if (settings.schedule_mode === 'minutes') return `Every ${settings.interval_value} minute${settings.interval_value === 1 ? '' : 's'}`
  if (settings.schedule_mode === 'hours') return `Every ${settings.interval_value} hour${settings.interval_value === 1 ? '' : 's'}`
  if (settings.schedule_mode === 'weekly') return `Every ${settings.interval_value} week${settings.interval_value === 1 ? '' : 's'} at ${settings.run_time} UTC`
  return `Daily at ${settings.run_time} UTC`
}
