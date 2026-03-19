import { ArrowUpRight, Bug, Loader2, Send, Sparkles, Zap } from 'lucide-react'
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
  moduleFilter: string | null
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
        已解析：{parsed.module}/{parsed.entity_type}
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
        {applying ? '套用中…' : hasSelected ? '套用到選取項目' : '建立捕捉'}
      </button>
    </div>
  )
}

function AssistantMessage({
  msg,
  applying,
  hasSelected,
  debugMode,
  onApply,
}: {
  msg: ChatMessage
  applying: boolean
  hasSelected: boolean
  debugMode: boolean
  onApply: (p: ParsedCapture) => void
}) {
  const hasParsed = !!msg.parsed
  // In normal mode with parsed result: show only notes (if any)
  // In debug mode or no parsed result: show full raw content
  const showRawContent = debugMode || !hasParsed

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        {showRawContent && (
          <div
            className="px-3 py-2 rounded-lg text-[13px] whitespace-pre-wrap"
            style={{ backgroundColor: 'var(--surface0)', color: 'var(--text)' }}
          >
            {msg.content}
          </div>
        )}
        {hasParsed && !debugMode && msg.parsed?.notes && (
          <div
            className="px-3 py-1.5 rounded-lg text-[12px]"
            style={{ backgroundColor: 'var(--surface0)', color: 'var(--subtext0)' }}
          >
            {msg.parsed.notes}
          </div>
        )}
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

const MODULE_LABELS: Record<string, string> = {
  finance: '記帳',
  taskflow: '任務',
  invest: '投資',
  dailyos: '日程',
  intelflow: '情報',
  ideagraph: '靈感',
}

export default function EnrichmentChat({
  selectedCapture,
  moduleFilter,
  onCaptureCreated,
  onUpdate,
  onPromote,
}: EnrichmentChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'system',
      content:
        '捕捉台就緒。輸入任何內容，AI 會自動解析成結構化資料。\n\n範例：\n- 「午餐 星巴克 180」\n- 「買 10 張台積電 850」\n- 「週五前修好登入 bug」',
      timestamp: Date.now(),
    },
  ])
  const [input, setInput] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [applying, setApplying] = useState(false)
  const [debugMode, setDebugMode] = useState(false)
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

  // Focus effect when selected capture changes (dedup: skip if last msg is same capture)
  useEffect(() => {
    if (selectedCapture) {
      const payload = selectedCapture.payload
      const desc =
        (payload.description as string) ||
        (payload.title as string) ||
        selectedCapture.raw_input ||
        ''
      const tag = `[${selectedCapture.module}/${selectedCapture.entity_type}] ${desc}`
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (last?.role === 'system' && last.content.includes(tag)) return prev
        return [
          ...prev,
          {
            role: 'system',
            content: `已選取：${tag}\n完整度：${Math.round(selectedCapture.completeness * 100)}%${
              selectedCapture.missing_fields.length > 0
                ? `\n缺少：${selectedCapture.missing_fields.join(', ')}`
                : ''
            }`,
            timestamp: Date.now(),
          },
        ]
      })
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

      // Add module hint prefix when a tab is selected (no capture selected)
      let prefixedText = text.trim()
      if (!selectedCapture && moduleFilter) {
        const label = MODULE_LABELS[moduleFilter] ?? moduleFilter
        prefixedText = `[模組: ${moduleFilter} (${label})] ${prefixedText}`
      }

      wsRef.current.send(
        JSON.stringify({
          type: 'message',
          text: prefixedText,
          context,
        }),
      )
    },
    [selectedCapture, moduleFilter],
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
          { role: 'system', content: '已套用欄位到捕捉紀錄。', timestamp: Date.now() },
        ])
      } else {
        // Create new capture from parsed data — include raw_input for auto-enrichment
        const lastUserMsg = messages.findLast((m) => m.role === 'user')
        await captureApi.create({
          module: parsed.module,
          entity_type: parsed.entity_type,
          payload: parsed.payload,
          raw_input: lastUserMsg?.content,
        })
        onCaptureCreated()
        setMessages((prev) => [
          ...prev,
          {
            role: 'system',
            content: `已建立捕捉：${parsed.module}/${parsed.entity_type}`,
            timestamp: Date.now(),
          },
        ])
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: '套用失敗。', timestamp: Date.now() },
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
          ? `已提升為正式紀錄：${result.promoted_id}`
          : `提升失敗：${result.error || result.missing_fields.join(', ')}`,
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
            AI 對話
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: isConnected ? 'var(--green)' : 'var(--red)',
              color: 'var(--base)',
            }}
          >
            {isConnected ? '已連線' : '離線'}
          </span>
          <button
            type="button"
            onClick={() => setDebugMode((d) => !d)}
            className="p-1 rounded transition-opacity"
            style={{
              color: debugMode ? 'var(--yellow)' : 'var(--overlay0)',
              opacity: debugMode ? 1 : 0.5,
            }}
            title={debugMode ? '關閉除錯模式' : '開啟除錯模式'}
          >
            <Bug size={13} />
          </button>
        </div>
        {selectedCapture && selectedCapture.status === 'pending' && (
          <button
            type="button"
            onClick={handlePromoteSelected}
            className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md font-medium"
            style={{ backgroundColor: 'var(--green)', color: 'var(--base)' }}
          >
            <ArrowUpRight size={12} />
            提升
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
                debugMode={debugMode}
                onApply={handleApplyParsed}
              />
            )}
          </div>
        ))}

        {isStreaming && (
          <div className="flex items-center gap-1.5" style={{ color: 'var(--overlay0)' }}>
            <Loader2 size={12} className="animate-spin" />
            <span className="text-[11px]">思考中…</span>
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
              selectedCapture ? `補充 ${selectedCapture.entity_type}…` : '輸入內容快速捕捉…'
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
