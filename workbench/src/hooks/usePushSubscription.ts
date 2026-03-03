import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

declare const __BASE_PATH__: string

type PushPermission = NotificationPermission | 'unsupported'

interface UsePushSubscriptionReturn {
  permission: PushPermission
  subscribed: boolean
  subscribe: () => Promise<void>
  unsubscribe: () => Promise<void>
  loading: boolean
  error: string | null
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const output = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) {
    output[i] = raw.charCodeAt(i)
  }
  return output
}

export function usePushSubscription(): UsePushSubscriptionReturn {
  const [permission, setPermission] = useState<PushPermission>(() => {
    if (!('Notification' in window) || !('PushManager' in window)) return 'unsupported'
    return Notification.permission
  })
  const [subscribed, setSubscribed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Check existing subscription on mount
  useEffect(() => {
    if (permission === 'unsupported' || permission === 'denied') return

    navigator.serviceWorker?.ready?.then(async (reg) => {
      const sub = await reg.pushManager.getSubscription()
      setSubscribed(!!sub)
    })
  }, [permission])

  const subscribe = useCallback(async () => {
    if (permission === 'unsupported') {
      setError('Push notifications not supported')
      return
    }

    setLoading(true)
    setError(null)

    try {
      // Request notification permission
      const perm = await Notification.requestPermission()
      setPermission(perm)
      if (perm !== 'granted') {
        setError('Notification permission denied')
        return
      }

      // Get VAPID public key from server
      const { public_key } = await request<{ public_key: string }>('/notification/vapid-key')

      // Subscribe via Push API
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      })

      // Send subscription to server
      const subJson = sub.toJSON()
      await request('/notification/subscriptions', {
        method: 'POST',
        body: JSON.stringify({
          endpoint: sub.endpoint,
          keys: {
            p256dh: subJson.keys?.p256dh || '',
            auth: subJson.keys?.auth || '',
          },
          app_scope: `${__BASE_PATH__}/`,
        }),
      })

      setSubscribed(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to subscribe')
    } finally {
      setLoading(false)
    }
  }, [permission])

  const unsubscribe = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        await request(`/notification/subscriptions?endpoint=${encodeURIComponent(sub.endpoint)}`, {
          method: 'DELETE',
        })
        await sub.unsubscribe()
      }
      setSubscribed(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to unsubscribe')
    } finally {
      setLoading(false)
    }
  }, [])

  return { permission, subscribed, subscribe, unsubscribe, loading, error }
}
