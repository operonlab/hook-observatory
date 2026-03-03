import { useCallback, useEffect, useState } from 'react'
import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import PositionTable from '../components/PositionTable'
import type { Position } from '../types'

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await request<PaginatedResponse<Position>>(
        '/invest/positions?page=1&page_size=100',
      )
      setPositions(res.items)
    } catch {
      // empty state
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold" style={{ color: 'var(--text)' }}>
        持倉管理
      </h2>
      <PositionTable positions={positions} loading={loading} />
    </div>
  )
}
