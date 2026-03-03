import { useCallback, useEffect, useState } from 'react'
import type { PaginatedResponse } from '@/types'
import { accountApi } from '../api'
import type { Account } from '../types'

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = (await accountApi.list()) as PaginatedResponse<Account>
      setAccounts(res.items)
    } catch {
      // empty state
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return (
      <div className="animate-pulse rounded-xl p-6" style={{ backgroundColor: 'var(--surface0)' }}>
        <div className="h-6 w-32 rounded" style={{ backgroundColor: 'var(--surface1)' }} />
      </div>
    )
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold" style={{ color: 'var(--text)' }}>
        投資帳戶
      </h2>

      {accounts.length === 0 ? (
        <div
          className="rounded-xl p-8 text-center"
          style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
        >
          尚無投資帳戶
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {accounts.map((acct) => (
            <div
              key={acct.id}
              className="rounded-xl p-4"
              style={{ backgroundColor: 'var(--surface0)' }}
            >
              <h3 className="font-semibold" style={{ color: 'var(--text)' }}>
                {acct.name}
              </h3>
              {acct.broker && (
                <p className="text-sm" style={{ color: 'var(--subtext0)' }}>
                  {acct.broker}
                </p>
              )}
              <p className="mt-2 text-xs" style={{ color: 'var(--subtext0)' }}>
                {acct.currency}
              </p>
              {acct.notes && (
                <p className="mt-1 text-xs" style={{ color: 'var(--subtext0)' }}>
                  {acct.notes}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
