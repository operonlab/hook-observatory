import { Route, Routes } from 'react-router-dom'
import DashboardPage from './DashboardPage'
import BrowserPage from './BrowserPage'
import QAPage from './QAPage'

export default function DocvaultPages() {
  return (
    <Routes>
      <Route index element={<DashboardPage />} />
      <Route path="browser" element={<BrowserPage />} />
      <Route path="qa" element={<QAPage />} />
    </Routes>
  )
}
