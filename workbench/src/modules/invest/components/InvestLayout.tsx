import { NavLink, Outlet } from 'react-router-dom'

const tabs = [
  { to: '', label: '總覽', end: true },
  { to: 'positions', label: '持倉' },
  { to: 'trades', label: '交易紀錄' },
  { to: 'accounts', label: '帳戶管理' },
]

export default function InvestLayout() {
  return (
    <div className="flex h-full flex-col">
      <nav className="flex gap-1 border-b px-4 py-2" style={{ borderColor: 'var(--surface1)' }}>
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                isActive ? 'text-white' : 'hover:opacity-80'
              }`
            }
            style={({ isActive }) => ({
              backgroundColor: isActive ? 'var(--accent)' : 'transparent',
              color: isActive ? 'var(--base)' : 'var(--text)',
            })}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <div className="flex-1 overflow-auto p-4">
        <Outlet />
      </div>
    </div>
  )
}
