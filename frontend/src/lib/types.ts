export type Permission = { id: string; key: string; description: string; created_at: string }
export type Role = { id: string; name: string; description: string; is_owner: boolean; created_at: string; permissions: Permission[] }
export type User = { id: string; email: string; full_name: string; is_active: boolean; created_at: string; roles: Role[] }
export type Me = User & { organization_name: string; organization_slug: string; permission_keys: string[]; is_owner: boolean }
export type Overview = { users: number; active_users: number; roles: number; permissions: number; recent_users: User[]; role_distribution: { name: string; count: number }[] }
