import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import DailyosLayout from '../components/DailyosLayout'
import HistoryPage from './HistoryPage'
import MethodsPage from './MethodsPage'
import PlannerPage from './PlannerPage'

const RecurringPage = lazy(() => import('./RecurringPage'))

export default function DailyosPages() {
  return (
    <Routes>
      <Route element={<DailyosLayout />}>
        <Route index element={<PlannerPage />} />
        {/* Backward-compat redirects: old routes → unified view */}
        <Route path="week" element={<Navigate to="/dailyos?view=week" replace />} />
        <Route path="calendar" element={<Navigate to="/dailyos?view=month" replace />} />
        <Route path="methods" element={<MethodsPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route
          path="recurring"
          element={
            <Suspense>
              <RecurringPage />
            </Suspense>
          }
        />
      </Route>
    </Routes>
  )
}
