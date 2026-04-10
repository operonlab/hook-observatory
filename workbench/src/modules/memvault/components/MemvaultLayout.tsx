import { Outlet } from 'react-router-dom'
import '../styles/memvault.css'
import LensSelector from './LensSelector'

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

        <LensSelector />
      </header>

      <main className="flex-1 min-w-0 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
