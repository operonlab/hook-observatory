import { Route, Routes } from 'react-router-dom'
import PaperLayout from '../components/PaperLayout'
import ArticleDetailPage from './ArticleDetailPage'
import ArticleListPage from './ArticleListPage'
import DashboardPage from './DashboardPage'
import SearchPage from './SearchPage'

export default function PaperPages() {
  return (
    <Routes>
      <Route element={<PaperLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="articles" element={<ArticleListPage />} />
        <Route path="articles/:id" element={<ArticleDetailPage />} />
        <Route path="search" element={<SearchPage />} />
      </Route>
    </Routes>
  )
}
