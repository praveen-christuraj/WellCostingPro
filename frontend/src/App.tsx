import { lazy, Suspense, type ReactNode } from 'react'
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
const AuditLog = lazy(() => import('./pages/AuditLog'))
const MasterDataOverview = lazy(() => import('./pages/MasterDataOverview'))
const MasterDataRecords = lazy(() => import('./pages/MasterDataRecords'))
const DeletedMasterData = lazy(() => import('./pages/DeletedMasterData'))
const Vendors = lazy(() => import('./pages/Vendors'))
const Services = lazy(() => import('./pages/Services'))
const PoSoOrders = lazy(() => import('./pages/PoSoOrders'))

function Guard({ permission, children }: { permission: string | string[]; children: ReactNode }) {
  const { can } = useAuth()
  const allowed = Array.isArray(permission) ? permission.every(can) : can(permission)
  return allowed ? children : <Navigate to="/" replace/>
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Box display="grid" sx={{ placeItems: 'center', minHeight: '100vh' }}><CircularProgress/></Box>

  return <Suspense fallback={<Box display="grid" sx={{ placeItems: 'center', minHeight: '60vh' }}><CircularProgress/></Box>}>
    <Routes>
      {!user ? <>
        <Route path="/login" element={<Login/>}/>
        <Route path="*" element={<Navigate to="/login" replace/>}/>
      </> : <>
        <Route path="/login" element={<Navigate to="/" replace/>}/>
        <Route element={<Layout/>}>
          <Route index element={<Overview/>}/>
          <Route path="users" element={<Guard permission="users:read"><Users/></Guard>}/>
          <Route path="roles" element={<Guard permission="roles:read"><Roles/></Guard>}/>
          <Route path="permissions" element={<Guard permission="permissions:read"><Permissions/></Guard>}/>
          <Route path="assignments" element={<Guard permission={["assignments:write", "users:read", "roles:read", "permissions:read"]}><Assignments/></Guard>}/>
          <Route path="audit" element={<Guard permission="audit:read"><AuditLog/></Guard>}/>
          <Route path="master-data" element={<Guard permission="master-data:read"><MasterDataOverview/></Guard>}/>
          <Route path="master-data/records" element={<Guard permission="master-data:read"><MasterDataRecords/></Guard>}/>
          <Route path="master-data/services" element={<Guard permission="master-data:read"><Services/></Guard>}/>
          <Route path="master-data/vendors" element={<Guard permission="master-data:read"><Vendors/></Guard>}/>
          <Route path="master-data/po-so-orders" element={<Guard permission="master-data:read"><PoSoOrders/></Guard>}/>
          <Route path="master-data/deleted" element={<Guard permission="master-data:read"><DeletedMasterData/></Guard>}/>
          <Route path="*" element={<Navigate to="/" replace/>}/>
        </Route>
      </>}
    </Routes>
  </Suspense>
}
