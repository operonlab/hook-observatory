import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { configApi, methodApi } from '../api'
import MethodCard from '../components/MethodCard'
import type { Method, MethodSelection } from '../types'

export default function MethodsPage() {
  const [methods, setMethods] = useState<Method[]>([])
  const [activeSelection, setActiveSelection] = useState<MethodSelection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const loadData = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([
      methodApi
        .listAll({ include_presets: true })
        .catch(() => ({ items: [], total: 0, page: 1, page_size: 50 })),
      configApi.getActive().catch(() => null),
    ])
      .then(([result, selection]) => {
        setMethods(result.items)
        setActiveSelection(selection)
      })
      .catch(() => setError('載入失敗'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleActivate = useCallback((method: Method) => {
    setActionLoading(method.id)
    configApi
      .switchMethod({ method_id: method.id })
      .then((sel) => {
        setActiveSelection(sel)
      })
      .catch(() => {})
      .finally(() => setActionLoading(null))
  }, [])

  const handleClone = useCallback((method: Method) => {
    setActionLoading(method.id)
    methodApi
      .clone(method.id)
      .then((cloned) => {
        setMethods((prev) => [...prev, cloned])
      })
      .catch(() => {})
      .finally(() => setActionLoading(null))
  }, [])

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: 'var(--do-accent)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 md:p-6 max-w-4xl mx-auto">
        <div
          className="rounded-lg border p-6 text-center"
          style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
        >
          <p className="text-[13px] mb-3">{error}</p>
          <button
            type="button"
            onClick={loadData}
            className="flex items-center gap-1.5 mx-auto px-3 py-1.5 rounded-md text-[12px]"
            style={{ color: 'var(--do-accent)', backgroundColor: 'var(--do-accent-alpha)' }}
          >
            <RefreshCw size={12} />
            重試
          </button>
        </div>
      </div>
    )
  }

  const presets = methods.filter((m) => m.is_preset)
  const custom = methods.filter((m) => !m.is_preset)
  const activeMethodId = activeSelection?.method_id || null

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-medium" style={{ color: 'var(--do-text)' }}>
          方法論管理
        </h1>
      </div>

      {/* System Methods */}
      {presets.length > 0 && (
        <section>
          <h2
            className="text-[13px] font-medium mb-3"
            style={{ color: 'var(--do-text-secondary)' }}
          >
            系統方法論 ({presets.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {presets.map((method) => (
              <div key={method.id} style={{ opacity: actionLoading === method.id ? 0.6 : 1 }}>
                <MethodCard
                  method={method}
                  isActive={method.id === activeMethodId}
                  onActivate={handleActivate}
                  onClone={handleClone}
                />
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Custom Methods */}
      <section>
        <h2 className="text-[13px] font-medium mb-3" style={{ color: 'var(--do-text-secondary)' }}>
          自訂方法論 ({custom.length})
        </h2>
        {custom.length === 0 ? (
          <div
            className="rounded-lg border p-6 text-center text-[13px]"
            style={{ borderColor: 'var(--do-border)', color: 'var(--do-text-muted)' }}
          >
            尚無自訂方法論，可複製系統方法論後自行調整
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {custom.map((method) => (
              <div key={method.id} style={{ opacity: actionLoading === method.id ? 0.6 : 1 }}>
                <MethodCard
                  method={method}
                  isActive={method.id === activeMethodId}
                  onActivate={handleActivate}
                />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
