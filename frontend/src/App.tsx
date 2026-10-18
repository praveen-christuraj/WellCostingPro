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
const OtherManagementOverview = lazy(() => import('./pages/OtherManagementOverview'))
const DatabaseBrowser = lazy(() => import('./pages/DatabaseBrowser'))
const DatabaseTableView = lazy(() => import('./pages/DatabaseTableView'))
const MasterDataOverview = lazy(() => import('./pages/MasterDataOverview'))
const MasterDataRecords = lazy(() => import('./pages/MasterDataRecords'))
const DeletedMasterData = lazy(() => import('./pages/DeletedMasterData'))
const Vendors = lazy(() => import('./pages/Vendors'))
const Services = lazy(() => import('./pages/Services'))
const PoSoOrders = lazy(() => import('./pages/PoSoOrders'))
const Tangibles = lazy(() => import('./pages/Tangibles'))
const Consumables = lazy(() => import('./pages/Consumables'))
const CatalogueLists = lazy(() => import('./pages/CatalogueLists'))
const RigWellOverview = lazy(() => import('./pages/RigWellOverview'))
const Rigs = lazy(() => import('./pages/Rigs'))
const Wells = lazy(() => import('./pages/Wells'))
const WellSubActivities = lazy(() => import('./pages/WellSubActivities'))
const RigWellDeleted = lazy(() => import('./pages/RigWellDeleted'))
const AfeOverview = lazy(() => import('./pages/AfeOverview'))
const AfeManagement = lazy(() => import('./pages/AfeManagement'))
const AfeEstimate = lazy(() => import('./pages/AfeEstimate'))
const DailyCostManagement = lazy(() => import('./pages/DailyCostManagement'))
const DailyCostSheet = lazy(() => import('./pages/DailyCostSheet'))
const DailyCostAnalysis = lazy(() => import('./pages/DailyCostAnalysis'))
const MudCostAnalysis = lazy(() => import('./pages/MudCostAnalysis'))
const CostingSets = lazy(() => import('./pages/CostingSets'))

// Every listed permission is required (AND).
function Guard({ permission, children }: { permission: string | string[]; children: ReactNode }) {
  const { can } = useAuth()
  const allowed = Array.isArray(permission) ? permission.every(can) : can(permission)
  return allowed ? children : <Navigate to="/" replace/>
}

// Any listed permission is enough (OR), used by the module overview.
function GuardAny({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { can } = useAuth()
  return permissions.some(can) ? children : <Navigate to="/" replace/>
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
          <Route path="audit" element={<Navigate to="/other-management/audit" replace/>}/>
          <Route path="other-management" element={<GuardAny permissions={['audit:read', 'database-browser:read']}><OtherManagementOverview/></GuardAny>}/>
          <Route path="other-management/audit" element={<Guard permission="audit:read"><AuditLog/></Guard>}/>
          <Route path="other-management/database" element={<Guard permission="database-browser:read"><DatabaseBrowser/></Guard>}/>
          <Route path="other-management/database/:tableName" element={<Guard permission="database-browser:read"><DatabaseTableView/></Guard>}/>
          <Route path="master-data" element={<Guard permission="master-data:read"><MasterDataOverview/></Guard>}/>
          <Route path="master-data/records" element={<Guard permission="master-data:read"><MasterDataRecords/></Guard>}/>
          <Route path="master-data/services" element={<Guard permission="master-data:read"><Services/></Guard>}/>
          <Route path="master-data/vendors" element={<Guard permission="master-data:read"><Vendors/></Guard>}/>
          <Route path="master-data/po-so-orders" element={<Guard permission="master-data:read"><PoSoOrders/></Guard>}/>
          <Route path="master-data/tangibles" element={<Guard permission="master-data:read"><Tangibles/></Guard>}/>
          <Route path="master-data/consumables" element={<Guard permission="master-data:read"><Consumables/></Guard>}/>
          <Route path="master-data/catalogue-lists" element={<Guard permission="master-data:read"><CatalogueLists/></Guard>}/>
          <Route path="master-data/deleted" element={<Guard permission="master-data:read"><DeletedMasterData/></Guard>}/>
          <Route path="rig-well" element={<Guard permission="rig-well:read"><RigWellOverview/></Guard>}/>
          <Route path="rig-well/rigs" element={<Guard permission="rig-well:read"><Rigs/></Guard>}/>
          <Route path="rig-well/wells" element={<Guard permission="rig-well:read"><Wells/></Guard>}/>
          <Route path="rig-well/sub-activities" element={<Guard permission="rig-well:read"><WellSubActivities/></Guard>}/>
          <Route path="rig-well/deleted" element={<Guard permission="rig-well:read"><RigWellDeleted/></Guard>}/>
          <Route path="costing-sets" element={<Guard permission="costing-sets:read"><CostingSets/></Guard>}/>
          <Route path="afe" element={<Guard permission="afe:read"><AfeOverview/></Guard>}/>
          <Route path="afe/register" element={<Guard permission="afe:read"><AfeManagement/></Guard>}/>
          <Route path="afe/estimate/:afeId" element={<Guard permission="afe:read"><AfeEstimate/></Guard>}/>
          <Route path="daily-cost" element={<Guard permission="daily-cost:read"><DailyCostManagement/></Guard>}/>
          <Route path="daily-cost/entries/:entryId" element={<Guard permission="daily-cost:read"><DailyCostSheet/></Guard>}/>
          <Route path="daily-cost/analysis" element={<Guard permission="daily-cost:read"><DailyCostAnalysis/></Guard>}/>
          <Route path="daily-cost/analysis/:wellId" element={<Guard permission="daily-cost:read"><DailyCostAnalysis/></Guard>}/>
          <Route path="daily-cost/mud-cost-analysis" element={<Guard permission="daily-cost:read"><MudCostAnalysis/></Guard>}/>
          <Route path="*" element={<Navigate to="/" replace/>}/>
        </Route>
      </>}
    </Routes>
  </Suspense>
}
