import { MessageCircle, Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '@/stores/chat'

export default function ChatPanel() {
  const { open, setOpen, messages, currentModule, addMessage } = useChatStore()
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [open])

  function handleSend() {
    const text = input.trim()
    if (!text) return

    addMessage({
      role: 'user',
      content: text,
      module: currentModule ?? undefined,
    })
    setInput('')

    // Simulated echo reply
    setTimeout(() => {
      const moduleName = currentModule ?? 'global'
      addMessage({
        role: 'assistant',
        content: `[${moduleName}] 收到：「${text}」\n（Chat backend 尚未連接，這是模擬回覆）`,
        module: currentModule ?? undefined,
      })
    }, 600)
  }

  return (
    <>
      {/* ── Floating Chat Toggle ── */}

      {/* Desktop: right-edge vertical tab, vertically centered */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed right-0 top-1/2 -translate-y-1/2 z-40 hidden md:flex items-center justify-center"
        style={{
          width: '36px',
          height: '44px',
          backgroundColor: 'rgba(15, 15, 22, 0.9)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          borderRadius: '8px 0 0 8px',
          borderLeft: '1px solid rgba(255, 255, 255, 0.08)',
          borderTop: '1px solid rgba(255, 255, 255, 0.08)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          borderRight: 'none',
          color: 'rgba(180, 190, 254, 0.7)',
          boxShadow: '-2px 0 12px rgba(0, 0, 0, 0.3)',
          transition: 'opacity 0.25s, transform 0.3s',
          opacity: open ? 0 : 1,
          pointerEvents: open ? 'none' : 'auto',
          transform: open ? 'translateY(-50%) translateX(100%)' : 'translateY(-50%)',
        }}
        aria-label="開啟 Chat"
      >
        <MessageCircle size={16} />
      </button>

      {/* Mobile: bottom-right FAB, above potential tab bars */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed z-40 flex md:hidden items-center justify-center"
        style={{
          right: '16px',
          bottom: 'calc(80px + env(safe-area-inset-bottom, 0px))',
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          backgroundColor: 'rgba(180, 190, 254, 0.15)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          border: '1px solid rgba(180, 190, 254, 0.12)',
          color: 'var(--accent)',
          boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
          transition: 'opacity 0.25s, transform 0.3s',
          opacity: open ? 0 : 1,
          pointerEvents: open ? 'none' : 'auto',
          transform: open ? 'scale(0.8)' : 'scale(1)',
        }}
        aria-label="開啟 Chat"
      >
        <MessageCircle size={20} />
      </button>

      {/* ── Mobile overlay ── */}
      {open && (
        <button
          type="button"
          className="fixed inset-0 z-[35] md:hidden border-none cursor-default"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
          onClick={() => setOpen(false)}
          aria-label="關閉 Chat"
        />
      )}

      {/* ── Chat Panel ── */}
      <div
        className="fixed top-12 bottom-0 right-0 z-40 flex flex-col"
        style={{
          width: 'min(360px, 100vw)',
          backgroundColor: 'rgba(15, 15, 22, 0.98)',
          borderLeft: '1px solid rgba(255, 255, 255, 0.06)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          transform: open ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
          boxShadow: open ? '-8px 0 32px rgba(0, 0, 0, 0.4)' : 'none',
        }}
      >
        {/* Header */}
        <div
          className="flex h-12 shrink-0 items-center justify-between px-4"
          style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.06)' }}
        >
          <div className="flex items-center gap-2">
            <MessageCircle size={14} style={{ color: 'var(--accent)' }} />
            <span className="text-xs font-medium" style={{ color: 'rgba(255, 255, 255, 0.7)' }}>
              Workshop Chat
            </span>
            {currentModule && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: 'rgba(180, 190, 254, 0.1)',
                  color: 'var(--accent)',
                }}
              >
                {currentModule}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="flex h-6 w-6 items-center justify-center rounded transition-colors"
            style={{ color: 'rgba(255, 255, 255, 0.35)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.7)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'rgba(255, 255, 255, 0.35)'
            }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-3 opacity-50">
              <MessageCircle size={24} style={{ color: 'rgba(255, 255, 255, 0.15)' }} />
              <p className="text-xs text-center" style={{ color: 'rgba(255, 255, 255, 0.25)' }}>
                開始對話
                <br />
                Chat backend 連接後即可使用
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className="flex flex-col gap-1"
              style={{
                alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
              }}
            >
              <div
                className="max-w-[85%] px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap"
                style={{
                  backgroundColor:
                    msg.role === 'user' ? 'rgba(180, 190, 254, 0.12)' : 'rgba(255, 255, 255, 0.04)',
                  color: 'rgba(255, 255, 255, 0.75)',
                  borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                }}
              >
                {msg.content}
              </div>
              <span className="text-[10px] px-1" style={{ color: 'rgba(255, 255, 255, 0.15)' }}>
                {new Date(msg.timestamp).toLocaleTimeString('zh-TW', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div
          className="shrink-0 px-4 py-3"
          style={{ borderTop: '1px solid rgba(255, 255, 255, 0.06)' }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSend()
            }}
            className="flex items-center gap-2"
          >
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="輸入訊息..."
              className="flex-1 h-9 bg-transparent px-3 text-xs outline-none rounded"
              style={{
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                color: 'rgba(255, 255, 255, 0.8)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                caretColor: 'var(--accent)',
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = 'rgba(180, 190, 254, 0.3)'
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)'
              }}
            />
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded transition-colors"
              style={{
                backgroundColor: input.trim()
                  ? 'rgba(180, 190, 254, 0.15)'
                  : 'rgba(255, 255, 255, 0.04)',
                color: input.trim() ? 'var(--accent)' : 'rgba(255, 255, 255, 0.15)',
              }}
            >
              <Send size={14} />
            </button>
          </form>
        </div>
      </div>
    </>
  )
}
