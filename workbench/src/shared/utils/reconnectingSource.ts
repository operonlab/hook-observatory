/**
 * Utility for creating an EventSource with automatic exponential backoff reconnection.
 *
 * Extracts the common pattern used in useVoiceGateway and useStreamingEntry.
 *
 * Usage:
 *   import { createReconnectingSource } from '@/shared/utils/reconnectingSource'
 *
 *   const source = createReconnectingSource('/api/stream', {
 *     maxRetries: 3,
 *     onOpen: () => setConnected(true),
 *     onError: (retriesLeft) => console.warn('retrying', retriesLeft),
 *     onMaxRetriesReached: () => setError('Connection lost'),
 *     // Called each time a new EventSource is created — re-attach message handlers here.
 *     onSetup: (es) => {
 *       es.onmessage = (e) => handleMessage(e)
 *       es.addEventListener('custom', handler)
 *     },
 *   })
 *
 *   // Cleanup
 *   source.close()
 */

export interface ReconnectingSourceOptions {
  /** Maximum number of retry attempts. Default: Infinity (keep retrying). */
  maxRetries?: number
  /** Base delay in ms for exponential backoff. Default: 1000. */
  baseDelay?: number
  /** Maximum delay cap in ms. Default: 30000. */
  maxDelay?: number
  /**
   * Called each time a new EventSource instance is created.
   * Use this to attach onmessage / addEventListener handlers — they must be
   * re-attached on every reconnect because a new EventSource object is created.
   */
  onSetup?: (es: EventSource) => void
  /** Called when EventSource opens successfully. */
  onOpen?: () => void
  /** Called when EventSource encounters an error and will retry. */
  onError?: (retriesLeft: number) => void
  /** Called when all retries are exhausted. */
  onMaxRetriesReached?: () => void
  /** EventSource init options (e.g. withCredentials). */
  eventSourceInit?: EventSourceInit
}

export interface ReconnectingSource {
  /** The underlying EventSource (null if not connected or closed). */
  readonly eventSource: EventSource | null
  /** Manually close and stop all reconnect attempts. */
  close(): void
  /** Manually reconnect and reset the retry counter. */
  reconnect(): void
}

/**
 * Create an EventSource with automatic exponential backoff reconnection.
 */
export function createReconnectingSource(
  url: string,
  options: ReconnectingSourceOptions = {},
): ReconnectingSource {
  const {
    maxRetries = Number.POSITIVE_INFINITY,
    baseDelay = 1000,
    maxDelay = 30000,
    onSetup,
    onOpen,
    onError,
    onMaxRetriesReached,
    eventSourceInit,
  } = options

  let es: EventSource | null = null
  let retryCount = 0
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let closed = false

  function connect() {
    if (closed) return
    es = new EventSource(url, eventSourceInit)

    // Allow caller to attach message/event handlers on the fresh EventSource.
    onSetup?.(es)

    es.onopen = () => {
      retryCount = 0
      onOpen?.()
    }

    es.onerror = () => {
      es?.close()
      es = null

      if (retryCount < maxRetries && !closed) {
        const delay = Math.min(baseDelay * 2 ** retryCount, maxDelay)
        retryCount++
        const retriesLeft =
          maxRetries === Number.POSITIVE_INFINITY
            ? Number.POSITIVE_INFINITY
            : maxRetries - retryCount
        onError?.(retriesLeft)
        retryTimer = setTimeout(connect, delay)
      } else if (!closed) {
        onMaxRetriesReached?.()
      }
    }
  }

  connect()

  return {
    get eventSource() {
      return es
    },
    close() {
      closed = true
      if (retryTimer !== null) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      es?.close()
      es = null
    },
    reconnect() {
      closed = false
      retryCount = 0
      if (retryTimer !== null) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      es?.close()
      es = null
      connect()
    },
  }
}
