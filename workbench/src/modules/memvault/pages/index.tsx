import { Navigate, Route, Routes } from 'react-router-dom'
import JourneyView from '../components/JourneyView'
import MemvaultLayout from '../components/MemvaultLayout'
import RecallView from '../components/RecallView'
import KnowledgeLayout from '../components/knowledge/KnowledgeLayout'
import DashboardPage from '../components/knowledge/DashboardPage'
import BlocksPage from '../components/knowledge/BlocksPage'
import TriplesPage from '../components/knowledge/TriplesPage'
import CommunitiesPage from '../components/knowledge/CommunitiesPage'
import InsightsPage from '../components/knowledge/InsightsPage'

export default function MemvaultPages() {
  return (
    <Routes>
      <Route element={<MemvaultLayout />}>
        <Route index element={<Navigate to="recall" replace />} />
        <Route path="recall" element={<RecallView />} />
        <Route path="journey" element={<JourneyView />} />
        <Route path="knowledge" element={<KnowledgeLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="blocks" element={<BlocksPage />} />
          <Route path="triples" element={<TriplesPage />} />
          <Route path="communities" element={<CommunitiesPage />} />
          <Route path="insights" element={<InsightsPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
