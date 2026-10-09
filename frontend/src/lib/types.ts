export type Permission = { id: string; key: string; description: string; created_at: string }
export type Role = { id: string; name: string; description: string; is_owner: boolean; created_at: string; permissions: Permission[] }
export type User = { id: string; email: string; full_name: string; is_active: boolean; created_at: string; roles: Role[] }
export type Me = User & { organization_name: string; organization_slug: string; permission_keys: string[]; is_owner: boolean }
export type Overview = { users: number; active_users: number; roles: number; permissions: number; recent_users: User[]; role_distribution: { name: string; count: number }[] }
export type AuditEntry = { id: string; actor_user_id: string | null; actor_email: string; actor_name: string; action: string; entity_type: string; entity_id: string | null; entity_label: string; summary: string; ip_address: string; created_at: string }
export type AuditPage = { items: AuditEntry[]; total: number; page: number; page_size: number }
