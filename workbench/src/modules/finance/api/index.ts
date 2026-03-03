import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Budget,
  BudgetSet,
  Category,
  CategoryBreakdown,
  CategoryCreate,
  InstallmentPlan,
  MonthlySummary,
  MonthlyTrend,
  NetWorthPoint,
  Subscription,
  SubscriptionCreate,
  SubscriptionUpdate,
  Transaction,
  TransactionCreate,
  TransactionUpdate,
  Wallet,
  WalletCreate,
  WalletUpdate,
} from '../types'

// ─── CRUD APIs ───

export const transactionApi = {
  ...createCrudApi<Transaction, TransactionCreate, TransactionUpdate>('/finance/transactions'),

  listFiltered: (params: {
    page?: number
    page_size?: number
    month?: string
    type?: string
    category_id?: string
    wallet_id?: string
    payment_method?: string
    tag?: string
    search?: string
    status?: string
  }) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') qs.set(k, String(v))
    }
    if (!qs.has('page')) qs.set('page', '1')
    if (!qs.has('page_size')) qs.set('page_size', '20')
    return request<PaginatedResponse<Transaction>>(`/finance/transactions?${qs}`)
  },
}

export const categoryApi = {
  list: () => request<Category[]>('/finance/categories'),
  create: (data: CategoryCreate) =>
    request<Category>('/finance/categories', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: Partial<CategoryCreate>) =>
    request<Category>(`/finance/categories/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
}

export const subscriptionApi = createCrudApi<Subscription, SubscriptionCreate, SubscriptionUpdate>(
  '/finance/subscriptions',
)

export const walletApi = {
  ...createCrudApi<Wallet, WalletCreate, WalletUpdate>('/finance/wallets'),

  sync: (id: string, synced_balance: number, notes?: string) =>
    request<void>(`/finance/wallets/${id}/sync`, {
      method: 'POST',
      body: JSON.stringify({ synced_balance, notes }),
    }),

  reconcile: () =>
    request<{
      wallets: Array<{
        wallet_id: string
        wallet_name: string
        calculated: number
        difference: number
      }>
    }>('/finance/wallets/reconcile'),
}

export const installmentApi = {
  list: (page = 1, pageSize = 20) =>
    request<PaginatedResponse<InstallmentPlan>>(
      `/finance/installments?page=${page}&page_size=${pageSize}`,
    ),

  get: (id: string) => request<InstallmentPlan>(`/finance/installments/${id}`),

  cancel: (id: string) => request<void>(`/finance/installments/${id}/cancel`, { method: 'POST' }),

  payoff: (id: string) => request<void>(`/finance/installments/${id}/payoff`, { method: 'POST' }),
}

export const budgetApi = {
  list: (yearMonth: string) =>
    request<PaginatedResponse<Budget>>(`/finance/budgets?year_month=${yearMonth}`).then(
      (res) => res.items,
    ),

  set: (data: BudgetSet) =>
    request<Budget>('/finance/budgets', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}

// ─── Analytics APIs ───

export const analyticsApi = {
  summary: (yearMonth?: string) => {
    const ym = yearMonth ?? new Date().toISOString().slice(0, 7)
    return request<MonthlySummary>(`/finance/summary/${ym}`)
  },

  insights: (months = 6) => request<MonthlyTrend[]>(`/finance/insights?months=${months}`),

  categoryBreakdown: (yearMonth: string) =>
    request<MonthlySummary>(`/finance/summary/${yearMonth}`).then((s) => s.category_breakdown),

  netWorth: () => request<NetWorthPoint[]>('/finance/wallets/net-worth'),
}
