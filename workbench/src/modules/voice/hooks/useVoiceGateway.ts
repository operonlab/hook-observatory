import { useCallback, useEffect, useRef } from 'react'
import type { ReconnectingSource } from '@/shared/utils/reconnectingSource'
import { createReconnectingSource } from '@/shared/utils/reconnectingSource'
import { useVoiceStore } from '../stores/voiceStore'
import type { VoiceClientConfig, VoiceEvent, VoiceStatus } from '../types'

const GATEWAY_BASE = '/apps/voice'

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${GATEWAY_BASE}${path}`, init)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

/** Post a voice event to the gateway (Path A: browser → server). */
async function postEvent(type: string, payload: Record<string, unknown> = {}) {
  return fetchJSON('/api/voice/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, payload }),
  })
}

/**
 * Hook that connects to the voice-gateway SSE stream and manages lifecycle.
 * Call this once at the App level.
 */
export function useVoiceGateway() {
  const { enabled, setConnected, handleEvent, setConfig, setState, setMode } = useVoiceStore()
  const sourceRef = useRef<ReconnectingSource | null>(null)
  const heartbeatRef = useRef<ReturnType<typeof setInterval>>()

  // Fetch initial status + config
  const refresh = useCallback(async () => {
    try {
      const [status, config] = await Promise.all([
        fetchJSON<VoiceStatus>('/status'),
        fetchJSON<VoiceClientConfig>('/api/voice/config'),
      ])
      setState(status.state)
      setMode(status.active_mode)
      setConfig(config)
      setConnected(true)
    } catch {
      setConnected(false)
    }
  }, [setState, setMode, setConfig, setConnected])

  // SSE connection
  useEffect(() => {
    if (!enabled) {
      sourceRef.current?.close()
      sourceRef.current = null
      return
    }

    const source = createReconnectingSource(`${GATEWAY_BASE}/api/voice/stream`, {
      onSetup: (es) => {
        es.onmessage = (e) => {
          try {
            const event: VoiceEvent = JSON.parse(e.data)
            if (event.type === 'heartbeat') return
            handleEvent(event)
          } catch {
            /* ignore parse errors */
          }
        }
      },
      onOpen: () => {
        setConnected(true)
        refresh()
      },
      onError: () => {
        setConnected(false)
      },
    })

    sourceRef.current = source

    // Client heartbeat every 30s
    heartbeatRef.current = setInterval(() => {
      postEvent('voice.client.heartbeat').catch(() => {})
    }, 30_000)

    return () => {
      source.close()
      sourceRef.current = null
      clearInterval(heartbeatRef.current)
    }
  }, [enabled, handleEvent, setConnected, refresh])

  // Notify gateway when browser voice is enabled/disabled
  const enable = useCallback(async () => {
    useVoiceStore.getState().setEnabled(true)
    await postEvent('voice.client.connected', { user_agent: navigator.userAgent })
  }, [])

  const disable = useCallback(async () => {
    useVoiceStore.getState().setEnabled(false)
    await postEvent('voice.client.disconnected', { reason: 'user_disabled' })
  }, [])

  return { refresh, enable, disable, postEvent }
}
