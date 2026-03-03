import { Route, Routes } from 'react-router-dom'
import InvestLayout from '../components/InvestLayout'
import AccountsPage from './AccountsPage'
import OverviewPage from './OverviewPage'
import PositionsPage from './PositionsPage'
import TradesPage from './TradesPage'

export default function InvestPages() {
  return (
    <Routes>
      <Route element={<InvestLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="accounts" element={<AccountsPage />} />
      </Route>
    </Routes>
  )
}
