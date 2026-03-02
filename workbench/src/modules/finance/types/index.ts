import type { BaseEntity } from '@/types'

// ─── Transaction ───

export type TransactionType = 'income' | 'expense' | 'transfer'
export type TransactionStatus = 'completed' | 'scheduled' | 'cancelled' | 'pending'
export type PaymentMethod = 'cash' | 'credit_card' | 'debit_card' | 'e_payment' | 'bank_transfer'

export interface Transaction extends BaseEntity {
  type: TransactionType
  amount: number
  currency: string
  description: string | null
  merchant: string | null
  payment_method: PaymentMethod
  payment_detail: string | null
  category_id: string | null
  category_name: string | null
  wallet_id: string
  wallet_name: string | null
  transfer_to_wallet_id: string | null
  installment_plan_id: string | null
  installment_number: number | null
  paired_transaction_id: string | null
  status: TransactionStatus
  fee: number
  invoice_number: string | null
  is_private: boolean
  tags: string[]
  transacted_at: string
}

export interface TransactionCreate {
  type: TransactionType
  amount: number
  currency?: string
  description?: string
  merchant?: string
  payment_method: PaymentMethod
  payment_detail?: string
  category_id?: string
  wallet_id: string
  transfer_to_wallet_id?: string
  fee?: number
  invoice_number?: string
  is_private?: boolean
  tags?: string[]
  transacted_at: string
}

export interface TransactionUpdate {
  type?: TransactionType
  amount?: number
  description?: string
  merchant?: string
  payment_method?: PaymentMethod
  payment_detail?: string
  category_id?: string
  wallet_id?: string
  fee?: number
  invoice_number?: string
  is_private?: boolean
  tags?: string[]
  transacted_at?: string
}

// ─── Category ───

export interface Category {
  id: string
  space_id: string
  parent_id: string | null
  name: string
  icon: string | null
  color: string | null
  sort_order: number
  is_active: boolean
  children?: Category[]
}

export interface CategoryCreate {
  name: string
  parent_id?: string
  icon?: string
  color?: string
  sort_order?: number
}

// ─── Subscription ───

export type BillingCycle = 'monthly' | 'yearly' | 'weekly'
export type SubscriptionStatus = 'active' | 'paused' | 'cancelled'

export interface Subscription extends BaseEntity {
  name: string
  amount: number
  currency: string
  billing_cycle: BillingCycle
  billing_day: number | null
  category_id: string | null
  category_name: string | null
  wallet_id: string | null
  payment_method: string | null
  payment_detail: string | null
  start_date: string
  end_date: string | null
  status: SubscriptionStatus
  next_billing: string | null
  notes: string | null
  is_private: boolean
}

export interface SubscriptionCreate {
  name: string
  amount: number
  currency?: string
  billing_cycle: BillingCycle
  billing_day?: number
  category_id?: string
  wallet_id?: string
  payment_method?: string
  payment_detail?: string
  start_date: string
  end_date?: string
  notes?: string
  is_private?: boolean
}

export interface SubscriptionUpdate {
  name?: string
  amount?: number
  billing_cycle?: BillingCycle
  billing_day?: number
  category_id?: string
  wallet_id?: string
  status?: SubscriptionStatus
  notes?: string
  is_private?: boolean
}

// ─── Wallet ───

export type WalletType = 'bank_account' | 'credit_card' | 'cash' | 'e_wallet' | 'investment'

export interface Wallet extends BaseEntity {
  name: string
  type: WalletType
  currency: string
  initial_balance: number
  current_balance: number
  credit_limit: number | null
  icon: string | null
  color: string | null
  sort_order: number
  is_active: boolean
  is_private: boolean
}

export interface WalletCreate {
  name: string
  type: WalletType
  currency?: string
  initial_balance?: number
  credit_limit?: number
  icon?: string
  color?: string
  is_private?: boolean
}

export interface WalletUpdate {
  name?: string
  icon?: string
  color?: string
  credit_limit?: number
  is_active?: boolean
  is_private?: boolean
}

// ─── Installment Plan ───

export type InstallmentStatus = 'active' | 'completed' | 'cancelled'

export interface InstallmentPlan extends BaseEntity {
  description: string
  total_amount: number
  currency: string
  num_installments: number
  installment_amount: number
  interest_rate: number
  billing_day: number | null
  merchant: string | null
  category_id: string | null
  wallet_id: string
  payment_method: string
  payment_detail: string | null
  start_date: string
  end_date: string | null
  status: InstallmentStatus
  is_private: boolean
  paid_count: number
  paid_amount: number
  remaining_amount: number
}

// ─── Budget ───

export interface Budget {
  id: string
  space_id: string
  year_month: string
  category_id: string | null
  category_name: string | null
  budget_amount: number
  savings_target: number | null
  spent_amount: number
  remaining_amount: number
  used_pct: number
  is_private: boolean
}

export interface BudgetSet {
  year_month: string
  category_id?: string
  budget_amount: number
  savings_target?: number
}

// ─── Summary / Analytics ───

export interface MonthlySummary {
  year_month: string
  total_income: number
  total_expense: number
  net: number
  by_category: CategoryBreakdown[]
  wallet_overview: WalletOverview[]
}

export interface CategoryBreakdown {
  category_id: string | null
  category_name: string
  category_icon: string | null
  amount: number
  pct: number
  count: number
}

export interface WalletOverview {
  wallet_id: string
  wallet_name: string
  wallet_type: WalletType
  current_balance: number
  change: number
}

export interface MonthlyTrend {
  year_month: string
  income: number
  expense: number
  net: number
}

export interface NetWorthPoint {
  date: string
  total: number
  bank: number
  cash: number
  e_wallet: number
  investment: number
  credit_card: number
}

// ─── Wallet type display config ───

export const WALLET_TYPE_CONFIG: Record<
  WalletType,
  { label: string; icon: string; color: string }
> = {
  bank_account: { label: '銀行帳戶', icon: '🏦', color: '#89b4fa' },
  credit_card: { label: '信用卡', icon: '💳', color: '#f38ba8' },
  cash: { label: '現金', icon: '💵', color: '#a6e3a1' },
  e_wallet: { label: '電子錢包', icon: '📱', color: '#cba6f7' },
  investment: { label: '投資帳戶', icon: '📈', color: '#f9e2af' },
}

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  cash: '現金',
  credit_card: '信用卡',
  debit_card: '簽帳卡',
  e_payment: '電子支付',
  bank_transfer: '銀行轉帳',
}

/** Format a numeric amount for display (max 0 fraction digits for TWD) */
export const fmtAmt = (v: number | string): string =>
  Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
