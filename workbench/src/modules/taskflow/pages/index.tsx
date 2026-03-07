import { Route, Routes } from 'react-router-dom'
import TaskflowLayout from '../components/TaskflowLayout'
import DashboardPage from './DashboardPage'
import StatsPage from './StatsPage'
import TasksPage from './TasksPage'

export default function TaskflowPages() {
  return (
    <Routes>
      <Route element={<TaskflowLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="stats" element={<StatsPage />} />
      </Route>
    </Routes>
  )
}
