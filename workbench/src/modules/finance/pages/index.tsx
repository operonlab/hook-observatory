import { Route, Routes } from 'react-router-dom'
import FinanceLayout from '../components/FinanceLayout'
import AnalyticsPage from './AnalyticsPage'
import BudgetPage from './BudgetPage'
import ReportPage from './ReportPage'
import TransactionsPage from './TransactionsPage'
import WalletsPage from './WalletsPage'

export default function FinancePages() {
  return (
    <Routes>
      <Route element={<FinanceLayout />}>
        <Route index element={<TransactionsPage />} />
        <Route path="wallets" element={<WalletsPage />} />
        <Route path="budget" element={<BudgetPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="report" element={<ReportPage />} />
      </Route>
    </Routes>
  )
}
