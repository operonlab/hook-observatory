import { Route, Routes } from 'react-router-dom'
import NotificationLayout from '../components/NotificationLayout'
import HistoryPage from './HistoryPage'
import SendPage from './SendPage'

export default function NotificationPages() {
  return (
    <Routes>
      <Route element={<NotificationLayout />}>
        <Route index element={<HistoryPage />} />
        <Route path="send" element={<SendPage />} />
      </Route>
    </Routes>
  )
}
