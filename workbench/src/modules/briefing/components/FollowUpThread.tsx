import { Loader2, MessageCircle, Send } from 'lucide-react'
import { useState } from 'react'
import { briefingApi } from '../api/client'
import type { FollowUp } from '../types'
import MarkdownBlock from './MarkdownBlock'

interface FollowUpThreadProps {
  briefingId: string
  followUps: FollowUp[]
  onNewFollowUp?: (followUp: FollowUp) => void
  onFollowUpUpdate?: (followUp: FollowUp) => void
}

export default function FollowUpThread({
  briefingId,
  followUps,
  onNewFollowUp,
  onFollowUpUpdate,
}: FollowUpThreadProps) {
  const [question, setQuestion] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [answeringIds, setAnsweringIds] = useState<Set<string>>(new Set())

  const handleSubmit = async () => {
    if (!question.trim() || submitting) return
    setSubmitting(true)
    try {
      const result = await briefingApi.createFollowUp(briefingId, { question: question.trim() })
      setQuestion('')
      onNewFollowUp?.(result)

      // Immediately trigger answer generation
      setAnsweringIds((prev) => new Set(prev).add(result.id))
      try {
        const answered = await briefingApi.answerFollowUp(result.id)
        onFollowUpUpdate?.(answered)
      } catch {
        // Answer generation failed silently; user can see "thinking..." state
      } finally {
        setAnsweringIds((prev) => {
          const next = new Set(prev)
          next.delete(result.id)
          return next
        })
      }
    } catch {
      // error handled by store
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="border"
      style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-4 sm:px-5 py-3 border-b"
        style={{ borderColor: 'var(--bf-border)' }}
      >
        <MessageCircle size={14} style={{ color: 'var(--bf-accent)' }} />
        <span
          className="text-xs uppercase tracking-widest"
          style={{ color: 'var(--bf-text-tertiary)' }}
        >
          延伸提問 ({followUps.length})
        </span>
      </div>

      {/* Existing follow-ups */}
      {followUps.length > 0 && (
        <div className="divide-y" style={{ borderColor: 'var(--bf-border)' }}>
          {followUps.map((fu) => {
            const isAnswering = answeringIds.has(fu.id)
            return (
              <div key={fu.id} className="px-4 sm:px-5 py-3">
                <div className="flex items-start gap-2 mb-2">
                  <span className="text-xs font-medium" style={{ color: 'var(--bf-accent)' }}>
                    Q:
                  </span>
                  <span className="text-sm" style={{ color: 'var(--bf-text)' }}>
                    {fu.question}
                  </span>
                </div>
                {fu.answer ? (
                  <div className="ml-4">
                    <MarkdownBlock content={fu.answer} />
                  </div>
                ) : (
                  <div
                    className="ml-4 flex items-center gap-2 text-xs"
                    style={{ color: 'var(--bf-text-dim)' }}
                  >
                    <Loader2 size={12} className="animate-spin" />
                    {isAnswering ? '思考中...' : '處理中...'}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Input */}
      <div
        className="flex items-center gap-2 px-4 sm:px-5 py-3 border-t"
        style={{ borderColor: 'var(--bf-border)' }}
      >
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSubmit()
            }
          }}
          placeholder="輸入延伸問題..."
          className="flex-1 bg-transparent text-sm outline-none placeholder:opacity-40"
          style={{ color: 'var(--bf-text)', caretColor: 'var(--bf-accent)' }}
          disabled={submitting}
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!question.trim() || submitting}
          className="p-2 transition-colors disabled:opacity-30"
          style={{ color: 'var(--bf-accent)' }}
        >
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  )
}
