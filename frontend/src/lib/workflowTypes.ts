export type PasswordResetRequest = {
  id: string; request_number: string; user_id: string; user_name: string; user_email: string
  status: string; reason: string; requested_at: string; requested_by_ip: string
  reviewed_at: string | null; review_notes: string; reset_token_expires_at: string | null; completed_at: string | null
}

export type UserNotification = {
  id: string; notification_type: string; severity: 'info' | 'success' | 'warning' | 'error'
  title: string; message: string; action_path: string; read_at: string | null; created_at: string
}

export type WorkflowTask = {
  id: string; task_number: string; task_type: string; title: string; description: string
  status: 'open' | 'in_progress' | 'completed' | 'cancelled'; priority: 'low' | 'normal' | 'high' | 'critical'
  required_permission: string; assignee_user_id: string | null; assignee_name: string; due_at: string | null
  related_entity_label: string; action_path: string; created_at: string; updated_at: string
}
