import { useCallback, useEffect, useState } from 'react'
import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import { portfolioApi } from '../api'
import PortfolioCard from '../components/PortfolioCard'
import PositionTable from '../components/PositionTable'
import type { PortfolioSummary, Position } from '../types'

export default function OverviewPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, posRes] = await Promise.all([
        portfolioApi.summary(),
        request<PaginatedResponse<Position>>('/invest/positions?page=1&page_size=100'),
      ])
      setPortfolio(p)
      setPositions(posRes.items)
    } catch {
      // silently fail — empty state shown
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="flex flex-col gap-4">
      <PortfolioCard data={portfolio} loading={loading} />
      <div>
        <h3 className="mb-3 text-base font-semibold" style={{ color: 'var(--text)' }}>
          所有持倉
        </h3>
        <PositionTable positions={positions} loading={loading} />
      </div>
    </div>
  )
}
