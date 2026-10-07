import { lazy, Suspense } from 'react'
import { Box, CircularProgress } from '@mui/material'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
const Layout = lazy(() => import('./components/Layout'))
const Login = lazy(() => import('./pages/Login'))
const Overview = lazy(() => import('./pages/Overview'))
const Users = lazy(() => import('./pages/Users'))
const Roles = lazy(() => import('./pages/Roles'))
const Permissions = lazy(() => import('./pages/Permissions'))
const Assignments = lazy(() => import('./pages/Assignments'))
function Guard({ permission, children }: { permission: string | string[]; children: React.ReactNode }) { const { can } = useAuth(); return (Array.isArray(permission) ? permission.every(can) : can(permission)) ? children : <Navigate to="/" replace/> }
export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Box display="grid" sx={{ placeItems: 'center', minHeight: '100vh' }}><CircularProgress/></Box>
  return <Suspense fallback={<Box display="grid" sx={{ placeItems: 'center', minHeight: '60vh' }}><CircularProgress/></Box>}><Routes>{!user ? <><Route path="/login" element={<Login/>}/><Route path="*" element={<Navigate to="/login" replace/>}/></> : <><Route path="/login" element={<Navigate to="/" replace/>}/><Route element={<Layout/>}><Route index element={<Overview/>}/><Route path="users" element={<Guard permission="users:read"><Users/></Guard>}/><Route path="roles" element={<Guard permission="roles:read"><Roles/></Guard>}/><Route path="permissions" element={<Guard permission="permissions:read"><Permissions/></Guard>}/><Route path="assignments" element={<Guard permission={["assignments:write", "users:read", "roles:read", "permissions:read"]}><Assignments/></Guard>}/><Route path="*" element={<Navigate to="/" replace/>}/></Route></>}</Routes></Suspense>
}
