import type { QAResponse } from '../types'

interface Props {
  history: QAResponse[]
  isLoading: boolean
}

const VERDICT_STYLE: Record<string, string> = {
  correct: 'text-green-600',
  ambiguous: 'text-yellow-600',
  incorrect: 'text-red-600',
}

export default function QAChat({ history, isLoading }: Props) {
  if (!history.length && !isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        <p>Ask a question about your documents to get started.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {history.map((qa, i) => (
        <div key={i} className="space-y-2">
          {/* Question */}
          <div className="flex justify-end">
            <div className="max-w-[70%] rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">
              {qa.question}
            </div>
          </div>

          {/* Answer */}
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-lg border bg-white px-4 py-3">
              <p className="whitespace-pre-wrap text-sm">{qa.answer}</p>

              <div className="mt-2 flex items-center gap-3 text-xs text-gray-400">
                <span>Pipeline {qa.pipeline_used}</span>
                {qa.confidence != null && (
                  <span>Confidence: {Math.round(qa.confidence * 100)}%</span>
                )}
                {qa.crag_verdict && (
                  <span className={VERDICT_STYLE[qa.crag_verdict] || ''}>
                    {qa.crag_verdict}
                  </span>
                )}
                {qa.citations.length > 0 && (
                  <span>{qa.citations.length} citations</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}

      {isLoading && (
        <div className="flex justify-start">
          <div className="rounded-lg border bg-white px-4 py-3 text-sm text-gray-400">
            Searching documents and generating answer...
          </div>
        </div>
      )}
    </div>
  )
}
