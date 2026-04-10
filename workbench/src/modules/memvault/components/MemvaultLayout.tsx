import { NavLink, Outlet } from 'react-router-dom'
import '../styles/memvault.css'

const LENSES = [
  { to: 'recall', label: 'Recall' },
  { to: 'journey', label: 'Journey' },
  { to: 'knowledge', label: 'Knowledge' },
] as const

export default function MemvaultLayout() {
  return (
    <div className="memvault flex flex-col h-full">
      <header
        className="flex items-center gap-4 px-4 py-3 border-b shrink-0"
        style={{
          backgroundColor: 'var(--crust)',
          borderColor: 'var(--surface0)',
        }}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="text-sm"
            style={{ color: 'var(--blue)', fontWeight: 500, letterSpacing: '0.04em' }}
          >
            MemVault
          </span>
          <span
            className="text-[10px] uppercase tracking-widest hidden sm:inline"
            style={{ color: 'var(--subtext1)', letterSpacing: '0.1em' }}
          >
            記憶金庫
          </span>
        </div>

        <nav
          className="inline-flex rounded-xl border p-1"
          style={{
            backgroundColor: 'var(--crust)',
            borderColor: 'var(--surface0)',
          }}
        >
          {LENSES.map((lens) => (
            <NavLink
              key={lens.to}
              to={lens.to}
              className="rounded-lg px-5 py-2 text-sm font-medium transition-all"
              style={({ isActive }) => ({
                backgroundColor: isActive
                  ? 'color-mix(in srgb, var(--blue) 18%, var(--surface0))'
                  : 'transparent',
                color: isActive ? 'var(--blue)' : 'var(--subtext1)',
                minHeight: 36,
              })}
            >
              {lens.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="flex-1 min-w-0 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
