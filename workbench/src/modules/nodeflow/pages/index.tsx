import { Route, Routes } from 'react-router-dom'
import NodeflowLayout from '../components/NodeflowLayout'
import FlowEditorPage from './FlowEditorPage'
import FlowListPage from './FlowListPage'

export default function NodeflowPages() {
  return (
    <Routes>
      <Route element={<NodeflowLayout />}>
        <Route index element={<FlowListPage />} />
      </Route>
      <Route path=":flowId" element={<FlowEditorPage />} />
    </Routes>
  )
}
