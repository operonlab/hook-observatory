import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import type { DomainSummary } from '../types'

interface DomainSectionProps {
  domain: DomainSummary
  children: React.ReactNode
  defaultOpen?: boolean
}

export default function DomainSection({ domain, children, defaultOpen = false }: DomainSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div
      className="border"
      style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full px-4 sm:px-5 py-3 text-left"
      >
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium" style={{ color: 'var(--bf-text)' }}>
            {domain.display_name}
          </h3>
          <div className="flex items-center gap-2">
            <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
              {domain.sources_count} 來源
            </span>
            <span className="text-[10px]" style={{ color: 'var(--bf-text-dim)' }}>
              {domain.analysts_count} 分析師
            </span>
            {domain.has_conclusion && (
              <span
                className="text-[10px] px-1.5 py-0.5 border"
                style={{ borderColor: 'var(--bf-conclusion-border)', color: 'var(--bf-confidence-high)' }}
              >
                已結論
              </span>
            )}
          </div>
        </div>
        <span style={{ color: 'var(--bf-text-muted)' }}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>
      {open && <div className="px-4 sm:px-5 pb-4 sm:pb-5">{children}</div>}
    </div>
  )
}
