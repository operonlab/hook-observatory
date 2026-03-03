import { createCrudApi, request } from '@/api/client'
import type { PaginatedResponse } from '@/types'
import type {
  Account,
  AccountCreate,
  AccountSummary,
  AccountUpdate,
  PortfolioSummary,
  Position,
  PositionCreate,
  PositionUpdate,
  Quote,
  Trade,
  TradeCreate,
  TradeUpdate,
} from '../types'

// ─── CRUD APIs ───

export const accountApi = {
  ...createCrudApi<Account, AccountCreate, AccountUpdate>('/invest/accounts'),

  summary: (id: string) => request<AccountSummary>(`/invest/accounts/${id}/summary`),
}

export const positionApi = {
  ...createCrudApi<Position, PositionCreate, PositionUpdate>('/invest/positions'),

  listByAccount: (accountId: string, page = 1, pageSize = 50) =>
    request<PaginatedResponse<Position>>(
      `/invest/positions?account_id=${accountId}&page=${page}&page_size=${pageSize}`,
    ),

  updatePrice: (id: string, price: number) =>
    request<Position>(`/invest/positions/${id}/price`, {
      method: 'PUT',
      body: JSON.stringify({ price }),
    }),
}

export const tradeApi = {
  ...createCrudApi<Trade, TradeCreate, TradeUpdate>('/invest/trades'),

  listByPosition: (positionId: string, page = 1, pageSize = 20) =>
    request<PaginatedResponse<Trade>>(
      `/invest/trades?position_id=${positionId}&page=${page}&page_size=${pageSize}`,
    ),
}

// ─── Portfolio APIs ───

export const portfolioApi = {
  summary: () => request<PortfolioSummary>('/invest/portfolio'),

  refreshQuotes: (symbols?: string[]) =>
    request<Quote[]>('/invest/quotes/refresh', {
      method: 'POST',
      body: JSON.stringify({ symbols: symbols ?? [] }),
    }),
}
