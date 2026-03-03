import { NavLink, Outlet } from 'react-router-dom'

const TABS = [{ to: '/nodeflow', label: '流程列表', end: true }] as const

export default function NodeflowLayout() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b px-4 py-2" style={{ borderColor: 'var(--surface1)' }}>
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={'end' in tab ? tab.end : false}
            className="rounded-lg px-3 py-1.5 text-sm font-medium transition-colors"
            style={({ isActive }) => ({
              backgroundColor: isActive ? 'var(--surface1)' : 'transparent',
              color: isActive ? 'var(--text)' : 'var(--subtext0)',
            })}
          >
            {tab.label}
          </NavLink>
        ))}
      </div>
      <div className="flex-1 overflow-auto p-4">
        <Outlet />
      </div>
    </div>
  )
}
