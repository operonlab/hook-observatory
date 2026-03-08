import { Route, Routes } from 'react-router-dom'
import CaptureConsole from './CaptureConsole'

export default function CapturePages() {
  return (
    <Routes>
      <Route index element={<CaptureConsole />} />
    </Routes>
  )
}
