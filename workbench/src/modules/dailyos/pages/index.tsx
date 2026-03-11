import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import DailyosLayout from '../components/DailyosLayout'
import HistoryPage from './HistoryPage'
import MethodsPage from './MethodsPage'
import PlannerPage from './PlannerPage'

const RecurringPage = lazy(() => import('./RecurringPage'))
const CalendarPage = lazy(() => import('./CalendarPage'))
const WeekViewPage = lazy(() => import('./WeekViewPage'))

export default function DailyosPages() {
  return (
    <Routes>
      <Route element={<DailyosLayout />}>
        <Route index element={<PlannerPage />} />
        <Route
          path="calendar"
          element={
            <Suspense>
              <CalendarPage />
            </Suspense>
          }
        />
        <Route
          path="week"
          element={
            <Suspense>
              <WeekViewPage />
            </Suspense>
          }
        />
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
