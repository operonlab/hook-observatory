import { buildParams, createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Budget,
  BudgetSet,
  Category,
  CategoryCreate,
  InstallmentPlan,
  InstallmentPlanCreate,
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

// ─── Icon Upload ───

export async function uploadIcon(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/finance/upload-icon', {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  if (!res.ok) throw new Error('Upload failed')
  const data = await res.json()
  return data.icon_url as string
}

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
  }) =>
    request<PaginatedResponse<Transaction>>(
      `/finance/transactions${buildParams(params as Record<string, unknown>)}`,
    ),
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
  delete: (id: string) => request<void>(`/finance/categories/${id}`, { method: 'DELETE' }),
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
      `/finance/installment-plans?page=${page}&page_size=${pageSize}`,
    ),

  get: (id: string) => request<InstallmentPlan>(`/finance/installment-plans/${id}`),

  create: (data: InstallmentPlanCreate) =>
    request<InstallmentPlan>('/finance/installment-plans', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  cancel: (id: string) =>
    request<void>(`/finance/installment-plans/${id}/cancel`, { method: 'POST' }),

  payoff: (id: string) =>
    request<void>(`/finance/installment-plans/${id}/payoff`, { method: 'POST' }),
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

// ─── Tag Styles ───

export const tagStyleApi = {
  get: () => request<{ styles: Record<string, string> }>('/finance/tag-styles'),
  put: (styles: Record<string, string>) =>
    request<{ styles: Record<string, string> }>('/finance/tag-styles', {
      method: 'PUT',
      body: JSON.stringify({ styles }),
    }),
}

// ─── Exchange Rates ───

export interface ExchangeRates {
  base: string
  rates: Record<string, number>
  date: string
}

export const exchangeRateApi = {
  get: () => request<ExchangeRates>('/finance/exchange-rates'),
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
