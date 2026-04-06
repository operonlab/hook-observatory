import { useState } from 'react'
import { useDocvaultStore } from '../stores'
import { useQAMutation } from '../hooks/queries'
import QAChat from '../components/QAChat'
import CitationPanel from '../components/CitationPanel'
import type { QAResponse } from '../types'

export default function QAPage() {
  const store = useDocvaultStore()
  const qaMutation = useQAMutation()
  const [history, setHistory] = useState<QAResponse[]>([])

  const handleAsk = async () => {
    if (!store.qaQuestion.trim()) return

    const result = await qaMutation.mutateAsync({
      question: store.qaQuestion,
      mode: store.qaMode,
      domain: store.qaDomain,
    })
    setHistory((prev) => [...prev, result])
    store.setQAQuestion('')
  }

  const latestResponse = history[history.length - 1] ?? null

  return (
    <div className="flex h-full min-h-0 flex-1">
      {/* Main QA area */}
      <div className="flex flex-1 flex-col p-6">
        <h1 className="mb-4 text-2xl font-bold">Document QA</h1>

        {/* Mode selector */}
        <div className="mb-4 flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={store.qaMode === 'factual'}
              onChange={() => store.setQAMode('factual')}
            />
            Factual (Pipeline A)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={store.qaMode === 'mixed'}
              onChange={() => store.setQAMode('mixed')}
            />
            Mixed (Pipeline C)
          </label>
          <select
            value={store.qaDomain}
            onChange={(e) => store.setQADomain(e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="default">Default</option>
            <option value="legal">Legal</option>
            <option value="medical">Medical</option>
            <option value="finance">Finance</option>
          </select>
        </div>

        {/* Chat history */}
        <div className="flex-1 overflow-y-auto">
          <QAChat history={history} isLoading={qaMutation.isPending} />
        </div>

        {/* Input */}
        <div className="mt-4 flex gap-2">
          <input
            type="text"
            value={store.qaQuestion}
            onChange={(e) => store.setQAQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
            placeholder="Ask a question about your documents..."
            className="flex-1 rounded-lg border px-4 py-2"
            disabled={qaMutation.isPending}
          />
          <button
            onClick={handleAsk}
            disabled={qaMutation.isPending || !store.qaQuestion.trim()}
            className="rounded-lg bg-blue-600 px-6 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {qaMutation.isPending ? 'Thinking...' : 'Ask'}
          </button>
        </div>
      </div>

      {/* Citation sidebar */}
      {latestResponse && latestResponse.citations.length > 0 && (
        <div className="w-80 shrink-0 overflow-y-auto border-l bg-gray-50 p-4">
          <CitationPanel citations={latestResponse.citations} />
        </div>
      )}
    </div>
  )
}
