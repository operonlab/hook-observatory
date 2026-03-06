import { Route, Routes } from 'react-router-dom'
import BriefingLayout from '../components/BriefingLayout'
import BriefingCalendar from './BriefingCalendar'
import BriefingConfig from './BriefingConfig'
import BriefingHistory from './BriefingHistory'
import TodayBriefing from './TodayBriefing'

export default function BriefingPages() {
  return (
    <Routes>
      <Route element={<BriefingLayout />}>
        <Route index element={<TodayBriefing />} />
        <Route path="history" element={<BriefingHistory />} />
        <Route path="calendar" element={<BriefingCalendar />} />
        <Route path="config" element={<BriefingConfig />} />
      </Route>
    </Routes>
  )
}
