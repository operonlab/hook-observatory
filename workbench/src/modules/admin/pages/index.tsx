import { Navigate, Route, Routes } from 'react-router-dom'
import Dashboard from './Dashboard'
import UserDetail from './UserDetail'
import UserList from './UserList'

export default function AdminPage() {
  return (
    <Routes>
      <Route index element={<Dashboard />} />
      <Route path="dashboard" element={<Dashboard />} />
      <Route path="users" element={<UserList />} />
      <Route path="users/:userId" element={<UserDetail />} />
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}
