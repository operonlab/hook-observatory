import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReconnectingSource } from '@/shared/utils/reconnectingSource'
import { createReconnectingSource } from '@/shared/utils/reconnectingSource'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StreamBlock {
  id: string
  type: 'thinking' | 'content' | 'source' | 'progress' | 'error' | 'done'
  data: Record<string, unknown>
  timestamp: string
}

export interface UseStreamingEntryReturn {
  blocks: StreamBlock[]
  /** Accumulated content text (delta blocks are appended, full blocks replace) */
  content: string
  /** Current lifecycle phase reported by progress blocks */
  phase: string
  /** Generation progress 0-1 */
  progress: number
  isStreaming: boolean
  error: string | null
  connect: (entryId: string) => void
  disconnect: () => void
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_RETRIES = 3
const BASE_RETRY_DELAY_MS = 1_000

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useStreamingEntry(): UseStreamingEntryReturn {
  const [blocks, setBlocks] = useState<StreamBlock[]>([])
  const [content, setContent] = useState('')
  const [phase, setPhase] = useState('')
  const [progress, setProgress] = useState(0)
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sourceRef = useRef<ReconnectingSource | null>(null)
  const entryIdRef = useRef<string | null>(null)

  // ---------------------------------------------------------------------------
  // Internal: teardown reconnecting source
  // ---------------------------------------------------------------------------

  const _teardown = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
  }, [])

  // ---------------------------------------------------------------------------
  // Internal: attach reconnecting source for a given entry ID
  // ---------------------------------------------------------------------------

  const _attach = useCallback(
    (entryId: string) => {
      _teardown()

      const url = `/api/briefing/entries/${entryId}/stream`

      setIsStreaming(true)
      setError(null)

      // --- per-type handlers ---

      const _handleContent = (block: StreamBlock) => {
        const isDelta = block.data.is_delta !== false
        const text = typeof block.data.text === 'string' ? block.data.text : ''
        if (isDelta) {
          setContent((prev) => prev + text)
        } else {
          setContent(text)
        }
      }

      const _handleProgress = (block: StreamBlock) => {
        const p = typeof block.data.phase === 'string' ? block.data.phase : ''
        const pct = typeof block.data.progress === 'number' ? block.data.progress : 0
        setPhase(p)
        setProgress(pct)
      }

      const _handleTerminal = (block: StreamBlock) => {
        if (block.type === 'error') {
          const msg = typeof block.data.message === 'string' ? block.data.message : 'Stream error'
          setError(msg)
        }
        setIsStreaming(false)
        _teardown()
      }

      const blockHandlers: Partial<Record<StreamBlock['type'], (b: StreamBlock) => void>> = {
        content: _handleContent,
        progress: _handleProgress,
        error: _handleTerminal,
        done: _handleTerminal,
      }

      const handleBlock = (event: MessageEvent, type: StreamBlock['type']) => {
        try {
          const block: StreamBlock = JSON.parse(event.data)
          setBlocks((prev) => [...prev, block])
          blockHandlers[type]?.(block)
        } catch {
          // malformed JSON — skip
        }
      }

      const source = createReconnectingSource(url, {
        maxRetries: MAX_RETRIES,
        baseDelay: BASE_RETRY_DELAY_MS,
        eventSourceInit: { withCredentials: true },
        onSetup: (es) => {
          es.addEventListener('thinking', (e) => handleBlock(e, 'thinking'))
          es.addEventListener('content', (e) => handleBlock(e, 'content'))
          es.addEventListener('source', (e) => handleBlock(e, 'source'))
          es.addEventListener('progress', (e) => handleBlock(e, 'progress'))
          es.addEventListener('error', (e) => handleBlock(e, 'error'))
          es.addEventListener('done', (e) => handleBlock(e, 'done'))
        },
        onMaxRetriesReached: () => {
          setError('Connection lost')
          setIsStreaming(false)
        },
      })

      sourceRef.current = source
    },
    [_teardown],
  )

  // ---------------------------------------------------------------------------
  // Public: connect
  // ---------------------------------------------------------------------------

  const connect = useCallback(
    (entryId: string) => {
      entryIdRef.current = entryId

      // Reset state for new stream
      setBlocks([])
      setContent('')
      setPhase('')
      setProgress(0)
      setError(null)

      _attach(entryId)
    },
    [_attach],
  )

  // ---------------------------------------------------------------------------
  // Public: disconnect
  // ---------------------------------------------------------------------------

  const disconnect = useCallback(() => {
    entryIdRef.current = null
    _teardown()
    setIsStreaming(false)
  }, [_teardown])

  // ---------------------------------------------------------------------------
  // Cleanup on unmount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      _teardown()
    }
  }, [_teardown])

  return {
    blocks,
    content,
    phase,
    progress,
    isStreaming,
    error,
    connect,
    disconnect,
  }
}
