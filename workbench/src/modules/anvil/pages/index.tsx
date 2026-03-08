import { Route, Routes } from 'react-router-dom'
import AnvilLayout from '../components/AnvilLayout'
import DashboardPage from './DashboardPage'
import HealthPage from './HealthPage'
import RunDetailPage from './RunDetailPage'
import RunsPage from './RunsPage'
import SecurityPage from './SecurityPage'

export default function AnvilPages() {
  return (
    <Routes>
      <Route element={<AnvilLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="security" element={<SecurityPage />} />
      </Route>
    </Routes>
  )
}
