import { Route, Routes } from 'react-router-dom'
import DailyosLayout from '../components/DailyosLayout'
import HistoryPage from './HistoryPage'
import MethodsPage from './MethodsPage'
import PlannerPage from './PlannerPage'

export default function DailyosPages() {
  return (
    <Routes>
      <Route element={<DailyosLayout />}>
        <Route index element={<PlannerPage />} />
        <Route path="methods" element={<MethodsPage />} />
        <Route path="history" element={<HistoryPage />} />
      </Route>
    </Routes>
  )
}
