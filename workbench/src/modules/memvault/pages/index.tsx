import { Route, Routes } from 'react-router-dom'
import JourneyView from '../components/JourneyView'
import MemvaultLayout from '../components/MemvaultLayout'
import RecallView from '../components/RecallView'
import UnderstandView from '../components/UnderstandView'
import { useMemvaultStore } from '../stores'

function LensRouter() {
  const activeLens = useMemvaultStore((s) => s.activeLens)

  if (activeLens === 'journey') return <JourneyView />
  if (activeLens === 'understand') return <UnderstandView />

  return <RecallView />
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
