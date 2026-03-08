import { request } from '@/api/client'
import type { PaginatedResponse } from '@/types'

export interface NotificationLog {
  id: string
  user_id: string | null
  category: string
  title: string
  body: string
  url: string | null
  recipients: number
  delivered: number
  failed: number
  source_event: string | null
  source_data: Record<string, unknown> | null
  created_at: string
}

export interface SendPayload {
  category: string
  title: string
  body?: string
  url?: string
  icon?: string | null
  tag?: string | null
  severity?: string
  user_id?: string | null
}

export interface SendResult {
  recipients: number
  delivered: number
  failed: number
  channels: { web_push: number; bark: boolean; ntfy: boolean }
}

export function sendNotification(data: SendPayload): Promise<SendResult> {
  return request<SendResult>('/notification/send', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function listHistory(params: {
  page?: number
  page_size?: number
  category?: string
}): Promise<PaginatedResponse<NotificationLog>> {
  const qs = new URLSearchParams()
  if (params.page) qs.set('page', String(params.page))
  if (params.page_size) qs.set('page_size', String(params.page_size))
  if (params.category) qs.set('category', params.category)
  return request<PaginatedResponse<NotificationLog>>(`/notification/history?${qs.toString()}`)
}

export interface Subscription {
  id: string
  user_id: string
  endpoint: string
  app_scope: string
  active: boolean
  preferences: Record<string, boolean>
  created_at: string
  updated_at: string
}

export function listSubscriptions(): Promise<Subscription[]> {
  return request<Subscription[]>('/notification/subscriptions')
}

export function deleteSubscription(endpoint: string): Promise<{ unsubscribed: boolean }> {
  const qs = new URLSearchParams({ endpoint })
  return request<{ unsubscribed: boolean }>(`/notification/subscriptions?${qs.toString()}`, {
    method: 'DELETE',
  })
}
