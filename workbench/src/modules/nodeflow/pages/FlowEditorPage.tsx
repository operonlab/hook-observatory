import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { PaginatedResponse } from '@/types'
import { flowApi, flowRunApi } from '../api'
import FlowEditor from '../components/FlowEditor'
import { FlowStatusBadge, RunStatusBadge } from '../components/FlowStatusBadge'
import type { FlowDetail, FlowRun } from '../types'

export default function FlowEditorPage() {
  const { flowId } = useParams<{ flowId: string }>()
  const navigate = useNavigate()
  const [flow, setFlow] = useState<FlowDetail | null>(null)
  const [runs, setRuns] = useState<FlowRun[]>([])
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)

  const load = useCallback(async () => {
    if (!flowId) return
    setLoading(true)
    try {
      const [flowData, runsData] = await Promise.all([
        flowApi.get(flowId),
        flowRunApi.listByFlow(flowId, 1, 10) as Promise<PaginatedResponse<FlowRun>>,
      ])
      setFlow(flowData as FlowDetail)
      setRuns(runsData.items)
    } catch {
      navigate('/nodeflow')
    } finally {
      setLoading(false)
    }
  }, [flowId, navigate])

  useEffect(() => {
    void load()
  }, [load])

  const handleActivate = async () => {
    if (!flowId) return
    await flowApi.activate(flowId)
    void load()
  }

  const handlePause = async () => {
    if (!flowId) return
    await flowApi.pause(flowId)
    void load()
  }

  const handleTrigger = async () => {
    if (!flowId) return
    setTriggering(true)
    try {
      await flowApi.trigger(flowId)
      void load()
    } finally {
      setTriggering(false)
    }
  }

  if (loading || !flow) {
    return (
      <div className="animate-pulse rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
        <div className="h-6 w-48 rounded" style={{ backgroundColor: 'var(--surface1)' }} />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="rounded-lg px-2 py-1 text-sm"
            style={{ color: 'var(--subtext0)' }}
            onClick={() => navigate('/nodeflow')}
          >
            &larr; 返回
          </button>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--text)' }}>
            {flow.name}
          </h2>
          <FlowStatusBadge status={flow.status} />
        </div>
        <div className="flex gap-2">
          {flow.status !== 'active' && (
            <button
              type="button"
              className="rounded-lg px-3 py-1.5 text-sm font-medium"
              style={{ backgroundColor: 'var(--green)', color: 'var(--base)' }}
              onClick={handleActivate}
            >
              啟用
            </button>
          )}
          {flow.status === 'active' && (
            <button
              type="button"
              className="rounded-lg px-3 py-1.5 text-sm font-medium"
              style={{ backgroundColor: 'var(--yellow)', color: 'var(--base)' }}
              onClick={handlePause}
            >
              暫停
            </button>
          )}
          <button
            type="button"
            className="rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            style={{ backgroundColor: 'var(--blue)', color: 'var(--base)' }}
            onClick={handleTrigger}
            disabled={triggering}
          >
            {triggering ? '觸發中...' : '手動觸發'}
          </button>
        </div>
      </div>

      {/* DAG Editor */}
      <div className="min-h-[400px] flex-1">
        <FlowEditor flow={flow} onSave={load} />
      </div>

      {/* Recent Runs */}
      {runs.length > 0 && (
        <div className="rounded-xl p-4" style={{ backgroundColor: 'var(--surface0)' }}>
          <h3 className="mb-3 font-semibold" style={{ color: 'var(--text)' }}>
            最近執行
          </h3>
          <div className="space-y-2">
            {runs.map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between rounded-lg px-3 py-2"
                style={{ backgroundColor: 'var(--surface1)' }}
              >
                <div className="flex items-center gap-2">
                  <RunStatusBadge status={run.status} />
                  <span className="text-xs" style={{ color: 'var(--subtext0)' }}>
                    {new Date(run.started_at).toLocaleString('zh-TW')}
                  </span>
                </div>
                {run.finished_at && (
                  <span className="text-xs" style={{ color: 'var(--subtext0)' }}>
                    {Math.round(
                      (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) /
                        1000,
                    )}
                    s
                  </span>
                )}
                {run.error && (
                  <span
                    className="truncate text-xs"
                    style={{ color: 'var(--red)', maxWidth: '200px' }}
                  >
                    {run.error}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
