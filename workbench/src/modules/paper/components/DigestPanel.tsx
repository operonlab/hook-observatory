import { Box, Lightbulb, Zap } from 'lucide-react'
import type { Digest } from '../types'
import RelevanceBadge from './RelevanceBadge'

interface DigestPanelProps {
  digest: Digest
}

const SECTION_LABEL_STYLE: React.CSSProperties = {
  fontSize: '10px',
  textTransform: 'uppercase',
  letterSpacing: '0.1em',
  color: 'var(--pp-text-dim)',
  fontFamily: 'var(--pp-font-ui)',
}

export default function DigestPanel({ digest }: DigestPanelProps) {
  const confidencePct = digest.confidence != null ? Math.round(digest.confidence * 100) : null

  return (
    <div
      style={{
        border: '1px solid var(--pp-accent)',
        backgroundColor: 'var(--pp-bg-elevated)',
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '11px 16px',
          borderBottom: '1px solid var(--pp-border)',
          backgroundColor: 'rgba(137, 180, 250, 0.06)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Box size={12} style={{ color: 'var(--pp-accent)' }} />
          <span
            style={{
              fontSize: '11px',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--pp-accent)',
              fontFamily: 'var(--pp-font-ui)',
              fontWeight: 500,
            }}
          >
            AI 摘要
          </span>
          {confidencePct != null && (
            <span
              style={{
                fontSize: '10px',
                color: 'var(--pp-text-dim)',
                borderLeft: '1px solid var(--pp-border)',
                paddingLeft: 8,
              }}
            >
              信心度 {confidencePct}%
            </span>
          )}
        </div>
        <RelevanceBadge relevance={digest.workshop_relevance} />
      </div>

      <div style={{ padding: '16px 16px 14px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* One-liner */}
        {digest.one_liner && (
          <p
            style={{
              fontFamily: 'var(--pp-font-display)',
              fontSize: '1.05rem',
              lineHeight: 1.65,
              color: 'var(--pp-text)',
              letterSpacing: '0.01em',
            }}
          >
            {digest.one_liner}
          </p>
        )}

        {/* Key findings */}
        {digest.key_findings && digest.key_findings.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 9 }}>
              <Lightbulb size={12} style={{ color: 'var(--pp-accent)', flexShrink: 0 }} />
              <span style={SECTION_LABEL_STYLE}>關鍵發現</span>
            </div>
            <ol
              style={{
                margin: 0,
                padding: 0,
                listStyle: 'none',
                display: 'flex',
                flexDirection: 'column',
                gap: 7,
              }}
            >
              {digest.key_findings.map((item, i) => (
                <li
                  key={i}
                  style={{
                    display: 'flex',
                    gap: 10,
                    alignItems: 'flex-start',
                  }}
                >
                  <span
                    style={{
                      fontSize: '10px',
                      color: 'var(--pp-accent)',
                      fontVariantNumeric: 'tabular-nums',
                      letterSpacing: '0.04em',
                      marginTop: 2,
                      flexShrink: 0,
                      minWidth: 16,
                    }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span
                    style={{
                      fontSize: '12.5px',
                      lineHeight: 1.6,
                      color: 'var(--pp-text-secondary)',
                    }}
                  >
                    {item}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Actionable insight */}
        {digest.actionable_insight && (
          <div
            style={{
              borderLeft: '2px solid var(--pp-accent)',
              paddingLeft: 12,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 7 }}>
              <Zap size={11} style={{ color: 'var(--pp-accent)', flexShrink: 0 }} />
              <span style={SECTION_LABEL_STYLE}>可執行洞察</span>
            </div>
            <p
              style={{
                fontSize: '12.5px',
                lineHeight: 1.65,
                color: 'var(--pp-text-secondary)',
              }}
            >
              {digest.actionable_insight}
            </p>
          </div>
        )}

        {/* Footer metadata */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            flexWrap: 'wrap',
            paddingTop: 10,
            borderTop: '1px solid var(--pp-border)',
          }}
        >
          {digest.applicable_modules && digest.applicable_modules.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ ...SECTION_LABEL_STYLE, letterSpacing: '0.06em' }}>適用模組</span>
              {digest.applicable_modules.map((mod) => (
                <span
                  key={mod}
                  style={{
                    fontSize: '10px',
                    padding: '1px 6px',
                    border: '1px solid var(--pp-border)',
                    color: 'var(--pp-text-tertiary)',
                  }}
                >
                  {mod}
                </span>
              ))}
            </div>
          )}
          {digest.effort_estimate && (
            <span style={{ fontSize: '10px', color: 'var(--pp-text-dim)' }}>
              預估工時: {digest.effort_estimate}
            </span>
          )}
          {digest.model_used && (
            <span style={{ fontSize: '10px', color: 'var(--pp-text-dim)', marginLeft: 'auto' }}>
              {digest.model_used}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
