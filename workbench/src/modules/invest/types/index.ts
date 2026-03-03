import type { BaseEntity } from '@/types'

// ─── Asset Type ───

export type AssetType = 'stock' | 'etf' | 'bond' | 'crypto' | 'fund'
export type TradeType = 'buy' | 'sell' | 'dividend' | 'split'

// ─── Account ───

export interface Account extends BaseEntity {
  name: string
  broker: string | null
  currency: string
  finance_wallet_id: string | null
  notes: string | null
}

export interface AccountCreate {
  name: string
  broker?: string
  currency?: string
  finance_wallet_id?: string
  notes?: string
}

export interface AccountUpdate {
  name?: string
  broker?: string
  currency?: string
  finance_wallet_id?: string
  notes?: string
}

export interface AccountSummary extends Account {
  total_market_value: number
  total_cost: number
  total_gain: number
  gain_pct: number
  position_count: number
}

// ─── Position ───

export interface Position extends BaseEntity {
  account_id: string
  symbol: string
  exchange: string | null
  asset_type: AssetType
  shares: number
  avg_cost: number
  current_price: number
  currency: string
  notes: string | null
  market_value: number
  total_cost: number
  unrealized_gain: number
  gain_pct: number
}

export interface PositionCreate {
  account_id: string
  symbol: string
  exchange?: string
  asset_type?: AssetType
  shares?: number
  avg_cost?: number
  current_price?: number
  currency?: string
  notes?: string
}

export interface PositionUpdate {
  symbol?: string
  exchange?: string
  asset_type?: AssetType
  shares?: number
  avg_cost?: number
  current_price?: number
  notes?: string
}

// ─── Trade ───

export interface Trade extends BaseEntity {
  position_id: string
  type: TradeType
  shares: number
  price: number
  fee: number
  tax: number
  currency: string
  notes: string | null
  traded_at: string
  total_amount: number
}

export interface TradeCreate {
  position_id: string
  type: TradeType
  shares: number
  price: number
  fee?: number
  tax?: number
  currency?: string
  notes?: string
  traded_at: string
}

export interface TradeUpdate {
  type?: TradeType
  shares?: number
  price?: number
  fee?: number
  tax?: number
  notes?: string
  traded_at?: string
}

// ─── Quote ───

export interface Quote {
  id: string
  symbol: string
  price: number
  prev_close: number | null
  change_pct: number | null
  currency: string
  source: string
  quoted_at: string
}

// ─── Portfolio ───

export interface PortfolioSummary {
  total_market_value: number
  total_cost: number
  total_gain: number
  gain_pct: number
  account_count: number
  position_count: number
  accounts: AccountSummary[]
}

// ─── Display Config ───

export const ASSET_TYPE_CONFIG: Record<AssetType, { label: string; icon: string; color: string }> =
  {
    stock: { label: '股票', icon: '📈', color: '#89b4fa' },
    etf: { label: 'ETF', icon: '📊', color: '#a6e3a1' },
    bond: { label: '債券', icon: '📃', color: '#f9e2af' },
    crypto: { label: '加密貨幣', icon: '₿', color: '#fab387' },
    fund: { label: '基金', icon: '💼', color: '#cba6f7' },
  }

export const TRADE_TYPE_LABELS: Record<TradeType, string> = {
  buy: '買入',
  sell: '賣出',
  dividend: '股息',
  split: '分割',
}

export const fmtAmt = (v: number | string): string =>
  Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const fmtPct = (v: number | string): string =>
  `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
