import { ArrowUpRight, Loader2, Send, Sparkles, Zap } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Capture, CapturePromoteResult } from '../api'
import { captureApi } from '../api'

interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  parsed?: ParsedCapture | null
  timestamp: number
}

interface ParsedCapture {
  module: string
  entity_type: string
  payload: Record<string, unknown>
  confidence?: number
  notes?: string
}

interface EnrichmentChatProps {
  selectedCapture: Capture | null
  onCaptureCreated: () => void
  onUpdate: (id: string, payload: Record<string, unknown>) => Promise<void>
  onPromote: (id: string) => Promise<CapturePromoteResult>
}

const CAPTURE_CONSOLE_WS = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/apps/capture-console/ws`

function tryParseCapture(text: string): ParsedCapture | null {
  const jsonMatch =
    text.match(/```json\s*([\s\S]*?)```/) ||
    text.match(/\{[\s\S]*"module"[\s\S]*"payload"[\s\S]*\}/)
  if (!jsonMatch) return null
  try {
    const raw = jsonMatch[1] ?? jsonMatch[0]
    const parsed = JSON.parse(raw)
    if (parsed.module && parsed.payload) {
      return parsed as ParsedCapture
    }
  } catch {
    // Not valid JSON
  }
  return null
}

function SystemMessage({ content }: { content: string }) {
  return (
    <div
      className="text-[11px] px-3 py-2 rounded-md whitespace-pre-wrap"
      style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
    >
      <Zap size={10} className="inline mr-1" style={{ color: 'var(--yellow)' }} />
      {content}
    </div>
  )
}

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div
        className="max-w-[80%] px-3 py-2 rounded-lg text-[13px] whitespace-pre-wrap"
        style={{ backgroundColor: 'var(--accent)', color: 'var(--base)' }}
      >
        {content}
      </div>
    </div>
  )
}

function ParsedCaptureCard({
  parsed,
  applying,
  hasSelected,
  onApply,
}: {
  parsed: ParsedCapture
  applying: boolean
  hasSelected: boolean
  onApply: (p: ParsedCapture) => void
}) {
  return (
    <div
      className="mt-1.5 px-3 py-2 rounded-md border"
      style={{ borderColor: 'var(--green)', backgroundColor: 'var(--surface0)' }}
    >
      <div className="text-[10px] font-medium mb-1" style={{ color: 'var(--green)' }}>
        Parsed: {parsed.module}/{parsed.entity_type}
        {parsed.confidence && (
          <span className="ml-2 opacity-70">({Math.round(parsed.confidence * 100)}%)</span>
        )}
      </div>
      <div className="space-y-0.5 mb-2">
        {Object.entries(parsed.payload).map(([k, v]) => (
          <div key={k} className="flex gap-2 text-[11px]">
            <span style={{ color: 'var(--overlay0)' }}>{k}:</span>
            <span style={{ color: 'var(--text)' }}>{String(v)}</span>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => onApply(parsed)}
        disabled={applying}
        className="text-[11px] px-3 py-1 rounded font-medium transition-opacity"
        style={{
          backgroundColor: 'var(--green)',
          color: 'var(--base)',
          opacity: applying ? 0.5 : 1,
        }}
      >
        {applying ? 'Applying...' : hasSelected ? 'Apply to selected' : 'Create capture'}
      </button>
    </div>
  )
}

function AssistantMessage({
  msg,
  applying,
  hasSelected,
  onApply,
}: {
  msg: ChatMessage
  applying: boolean
  hasSelected: boolean
  onApply: (p: ParsedCapture) => void
}) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div
          className="px-3 py-2 rounded-lg text-[13px] whitespace-pre-wrap"
          style={{ backgroundColor: 'var(--surface0)', color: 'var(--text)' }}
        >
          {msg.content}
        </div>
        {msg.parsed && (
          <ParsedCaptureCard
            parsed={msg.parsed}
            applying={applying}
            hasSelected={hasSelected}
            onApply={onApply}
          />
        )}
      </div>
    </div>
  )
}

function handleWsChunk(
  data: { text: string; msg_id: number },
  pendingChunks: React.MutableRefObject<string>,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
) {
  pendingChunks.current += data.text
  setMessages((prev) => {
    const last = prev[prev.length - 1]
    if (last?.role === 'assistant' && last.timestamp === data.msg_id) {
      return [...prev.slice(0, -1), { ...last, content: pendingChunks.current }]
    }
    return [...prev, { role: 'assistant', content: data.text, timestamp: data.msg_id }]
  })
}

function handleWsDone(
  pendingChunks: React.MutableRefObject<string>,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setIsStreaming: React.Dispatch<React.SetStateAction<boolean>>,
) {
  setIsStreaming(false)
  const parsed = tryParseCapture(pendingChunks.current)
  if (parsed) {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.role === 'assistant') {
        return [...prev.slice(0, -1), { ...last, parsed }]
      }
      return prev
    })
  }
  pendingChunks.current = ''
}

function handleWsMessage(
  e: MessageEvent,
  pendingChunks: React.MutableRefObject<string>,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setIsStreaming: React.Dispatch<React.SetStateAction<boolean>>,
) {
  try {
    const data = JSON.parse(e.data)
    if (data.type === 'chunk') {
      handleWsChunk(data, pendingChunks, setMessages)
    } else if (data.type === 'done') {
      handleWsDone(pendingChunks, setMessages, setIsStreaming)
    } else if (data.type === 'error') {
      setIsStreaming(false)
      pendingChunks.current = ''
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: `Error: ${data.message}`, timestamp: Date.now() },
      ])
    } else if (data.type === 'status') {
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: data.message, timestamp: Date.now() },
      ])
    }
  } catch {
    // Ignore parse errors
  }
}

export default function EnrichmentChat({
  selectedCapture,
  onCaptureCreated,
  onUpdate,
  onPromote,
}: EnrichmentChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'system',
      content:
        'Capture Console ready. Type anything to capture — I will parse it into structured data.\n\nExamples:\n- "午餐 星巴克 180"\n- "buy 10 TSMC at 850"\n- "fix login bug by Friday"',
      timestamp: Date.now(),
    },
  ])
  const [input, setInput] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [applying, setApplying] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const pendingChunks = useRef('')

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  // WebSocket connection
  useEffect(() => {
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    function connect() {
      ws = new WebSocket(CAPTURE_CONSOLE_WS)

      ws.onopen = () => {
        setIsConnected(true)
      }

      ws.onmessage = (e) => handleWsMessage(e, pendingChunks, setMessages, setIsStreaming)

      ws.onclose = () => {
        setIsConnected(false)
        reconnectTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws?.close()
      }

      wsRef.current = ws
    }

    connect()

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [])

  // Focus effect when selected capture changes
  useEffect(() => {
    if (selectedCapture) {
      const payload = selectedCapture.payload
      const desc =
        (payload.description as string) ||
        (payload.title as string) ||
        selectedCapture.raw_input ||
        ''
      setMessages((prev) => [
        ...prev,
        {
          role: 'system',
          content: `Selected: [${selectedCapture.module}/${selectedCapture.entity_type}] ${desc}\nCompleteness: ${Math.round(selectedCapture.completeness * 100)}%${
            selectedCapture.missing_fields.length > 0
              ? `\nMissing: ${selectedCapture.missing_fields.join(', ')}`
              : ''
          }`,
          timestamp: Date.now(),
        },
      ])
    }
  }, [selectedCapture?.id])

  const sendMessage = useCallback(
    (text: string) => {
      if (!text.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

      const userMsg: ChatMessage = {
        role: 'user',
        content: text.trim(),
        timestamp: Date.now(),
      }
      setMessages((prev) => [...prev, userMsg])
      setIsStreaming(true)
      pendingChunks.current = ''

      // If a capture is selected, include context
      const context = selectedCapture
        ? {
            capture_id: selectedCapture.id,
            module: selectedCapture.module,
            entity_type: selectedCapture.entity_type,
            payload: selectedCapture.payload,
            missing_fields: selectedCapture.missing_fields,
          }
        : null

      wsRef.current.send(
        JSON.stringify({
          type: 'message',
          text: text.trim(),
          context,
        }),
      )
    },
    [selectedCapture],
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
    setInput('')
    inputRef.current?.focus()
  }

  const handleApplyParsed = async (parsed: ParsedCapture) => {
    setApplying(true)
    try {
      if (selectedCapture) {
        // Update existing capture with parsed fields
        await onUpdate(selectedCapture.id, parsed.payload)
        setMessages((prev) => [
          ...prev,
          { role: 'system', content: 'Fields applied to capture.', timestamp: Date.now() },
        ])
      } else {
        // Create new capture from parsed data
        await captureApi.create({
          module: parsed.module,
          entity_type: parsed.entity_type,
          payload: parsed.payload,
        })
        onCaptureCreated()
        setMessages((prev) => [
          ...prev,
          {
            role: 'system',
            content: `Capture created: ${parsed.module}/${parsed.entity_type}`,
            timestamp: Date.now(),
          },
        ])
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: 'Failed to apply.', timestamp: Date.now() },
      ])
    } finally {
      setApplying(false)
    }
  }

  const handlePromoteSelected = async () => {
    if (!selectedCapture) return
    const result = await onPromote(selectedCapture.id)
    setMessages((prev) => [
      ...prev,
      {
        role: 'system',
        content: result.success
          ? `Promoted to ${result.promoted_id}`
          : `Promote failed: ${result.error || result.missing_fields.join(', ')}`,
        timestamp: Date.now(),
      },
    ])
  }

  return (
    <div className="flex flex-col h-full">
      {/* Chat header */}
      <div
        className="flex items-center justify-between px-4 py-2.5 border-b shrink-0"
        style={{ borderColor: 'var(--surface0)' }}
      >
        <div className="flex items-center gap-2">
          <Sparkles size={14} style={{ color: 'var(--yellow)' }} />
          <span className="text-xs font-medium" style={{ color: 'var(--text)' }}>
            Enrichment Chat
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: isConnected ? 'var(--green)' : 'var(--red)',
              color: 'var(--base)',
            }}
          >
            {isConnected ? 'connected' : 'offline'}
          </span>
        </div>
        {selectedCapture && selectedCapture.status === 'pending' && (
          <button
            type="button"
            onClick={handlePromoteSelected}
            className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md font-medium"
            style={{ backgroundColor: 'var(--green)', color: 'var(--base)' }}
          >
            <ArrowUpRight size={12} />
            Promote
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg) => (
          <div key={`${msg.timestamp}-${msg.role}`}>
            {msg.role === 'system' && <SystemMessage content={msg.content} />}
            {msg.role === 'user' && <UserMessage content={msg.content} />}
            {msg.role === 'assistant' && (
              <AssistantMessage
                msg={msg}
                applying={applying}
                hasSelected={!!selectedCapture}
                onApply={handleApplyParsed}
              />
            )}
          </div>
        ))}

        {isStreaming && (
          <div className="flex items-center gap-1.5" style={{ color: 'var(--overlay0)' }}>
            <Loader2 size={12} className="animate-spin" />
            <span className="text-[11px]">Thinking...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="px-4 py-3 border-t shrink-0"
        style={{ borderColor: 'var(--surface0)' }}
      >
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg border"
          style={{
            borderColor: 'var(--surface1)',
            backgroundColor: 'var(--base)',
          }}
        >
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              selectedCapture ? `Enrich ${selectedCapture.entity_type}...` : 'Type to capture...'
            }
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: 'var(--text)' }}
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="p-1.5 rounded-md transition-opacity"
            style={{
              backgroundColor: input.trim() ? 'var(--accent)' : 'var(--surface1)',
              color: 'var(--base)',
              opacity: input.trim() && !isStreaming ? 1 : 0.5,
            }}
          >
            <Send size={14} />
          </button>
        </div>
      </form>
    </div>
  )
}
