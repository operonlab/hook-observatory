import { Route, Routes } from 'react-router-dom'
import MemvaultLayout from '../components/MemvaultLayout'
import RecallView from '../components/RecallView'
import { useMemvaultStore } from '../stores'

function LensRouter() {
  const activeLens = useMemvaultStore((s) => s.activeLens)

  if (activeLens === 'recall') return <RecallView />

  return (
    <div
      className="mx-auto max-w-5xl px-3 py-16 text-center"
      style={{ color: 'var(--subtext0)' }}
    >
      <p className="text-sm">
        {activeLens === 'journey' ? 'Journey — 即將推出' : 'Understand — 即將推出'}
      </p>
    </div>
  )
}

export default function MemvaultPages() {
  return (
    <Routes>
      <Route element={<MemvaultLayout />}>
        <Route index element={<LensRouter />} />
      </Route>
    </Routes>
  )
}
