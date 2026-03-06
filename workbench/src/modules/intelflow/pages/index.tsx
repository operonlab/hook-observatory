import { Route, Routes } from 'react-router-dom'
import IntelflowLayout from '../components/IntelflowLayout'
import Dashboard from './Dashboard'
import ReportDetail from './ReportDetail'
import ReportList from './ReportList'
import SemanticSearch from './SemanticSearch'
import SmartQA from './SmartQA'
import TopicDetail from './TopicDetail'
import TopicsOverview from './TopicsOverview'

export default function IntelflowPages() {
  return (
    <Routes>
      <Route element={<IntelflowLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="reports" element={<ReportList />} />
        <Route path="reports/:id" element={<ReportDetail />} />
        <Route path="search" element={<SemanticSearch />} />
        <Route path="qa" element={<SmartQA />} />
        <Route path="topics" element={<TopicsOverview />} />
        <Route path="topics/:id" element={<TopicDetail />} />
      </Route>
    </Routes>
  )
}
