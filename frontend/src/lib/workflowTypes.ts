export type PasswordResetRequest = {
  id: string; request_number: string; user_id: string; user_name: string; user_email: string
  status: 'pending' | 'approved' | 'rejected' | 'completed' | 'expired'
  reason: string; requested_at: string; requested_by_ip: string
  reviewed_by_user_id: string | null; reviewed_at: string | null; review_notes: string
  reset_token_expires_at: string | null; completed_at: string | null
  initiated_by: 'user' | 'administrator'
}

export type SecurityAccount = {
  id: string; full_name: string; email: string; is_active: boolean
  failed_logins: number; locked_until: string | null
  must_change_password: boolean; password_changed_at: string | null; last_login_at: string | null
  password_expires_at: string | null; password_expired: boolean; password_days_remaining: number | null
  active_sessions: number; role_names: string[]; is_owner: boolean
}

export type SecurityOverview = {
  users: number; active_users: number; locked_users: number; pending_requests: number
  awaiting_use: number; must_change_password: number; completed_30d: number
  announcements_30d: number; reset_minutes: number; recent_requests: PasswordResetRequest[]
}

export type ResetCode = { request: PasswordResetRequest; reset_code: string; expires_at: string }

export type SecurityBulkAction = 'force-password-change' | 'revoke-sessions' | 'lock' | 'unlock'

export type UserNotification = {
  id: string; notification_type: string; severity: 'info' | 'success' | 'warning' | 'error'
  title: string; message: string; action_path: string; announcement_id: string | null
  read_at: string | null; created_at: string
}

export type NotificationPage = {
  items: UserNotification[]; total: number; unread_count: number; page: number; page_size: number
  counts: Record<string, number>
}

export type NotificationOverview = {
  total: number; unread: number; by_severity: Record<string, number>; by_type: Record<string, number>
  announcements_sent: number; oldest_unread_days: number
}

export type Announcement = {
  id: string; title: string; message: string; severity: string; action_path: string
  audience: 'all' | 'roles' | 'users'; audience_label: string; recipient_count: number
  created_by_name: string; created_at: string; recalled_at: string | null; read_count: number
}

export type AnnouncementPage = { items: Announcement[]; total: number; page: number; page_size: number }

export type TaskStatus = 'open' | 'in_progress' | 'completed' | 'cancelled'
export type TaskPriority = 'low' | 'normal' | 'high' | 'critical'

export type WorkflowTask = {
  id: string; task_number: string; task_type: string; title: string; description: string
  status: TaskStatus; priority: TaskPriority
  required_permission: string; assignee_user_id: string | null; assignee_name: string
  created_by_user_id: string | null; created_by_name: string
  due_at: string | null; related_entity_type: string; related_entity_id: string; related_entity_label: string
  action_path: string; completed_at: string | null; created_at: string; updated_at: string
  overdue: boolean; is_mine: boolean; can_manage: boolean
}

export type TaskPage = { items: WorkflowTask[]; total: number; page: number; page_size: number }

export type TaskOverview = {
  open: number; in_progress: number; overdue: number; due_today: number; completed_7d: number
  mine: number; unassigned: number; by_priority: Record<string, number>; by_type: Record<string, number>
}

export type TaskEvent = {
  id: string; event_type: string; old_status: string; new_status: string
  actor_name: string; notes: string; created_at: string
}
