import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

interface ToolEntry {
  id: string
  name: string
  description: string
  icon: string
  color: string
  url: string
}

const TOOL_LIST: ToolEntry[] = [
  {
    id: 'srt-fixer',
    name: 'SRT 字幕修正',
    description: 'SRT 批次修正 — 時間重疊、異常偵測、格式修復',
    icon: '✂️',
    color: '#6c8aff',
    url: '/tools/srt-fixer/',
  },
  {
    id: 'memvault-techstack',
    name: 'Memvault 技術全景',
    description: 'Memvault 記憶引擎架構視覺化、pipeline operators 全景圖',
    icon: '🗺️',
    color: '#cba6f7',
    url: '/tools/memvault-techstack/',
  },
]

function ToolCard({
  tool,
  isHovered,
  onHover,
  onClick,
}: {
  tool: ToolEntry
  isHovered: boolean
  onHover: (id: string | null) => void
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => onHover(tool.id)}
      onMouseLeave={() => onHover(null)}
      className="group relative flex items-start gap-4 p-6 text-left transition-all"
      style={{
        backgroundColor: isHovered ? `${tool.color}14` : 'transparent',
        cursor: 'pointer',
        border: '1px solid rgba(255, 255, 255, 0.04)',
        borderLeft: `2px solid ${isHovered ? tool.color : `${tool.color}40`}`,
        transition: 'border 0.15s, background-color 0.2s',
      }}
    >
      <span
        className="flex h-11 w-11 shrink-0 items-center justify-center text-xl"
        style={{
          backgroundColor: isHovered ? `${tool.color}30` : `${tool.color}20`,
          border: `1px solid ${tool.color}${isHovered ? '50' : '35'}`,
          borderRadius: '8px',
          transition: 'all 0.2s ease',
        }}
      >
        {tool.icon}
      </span>
      <div className="min-w-0 flex-1">
        <h3
          className="text-sm font-medium transition-colors"
          style={{
            color: isHovered ? tool.color : 'rgba(255, 255, 255, 0.85)',
          }}
        >
          {tool.name}
        </h3>
        <p
          className="mt-1 text-xs leading-relaxed"
          style={{
            color: isHovered ? 'rgba(255, 255, 255, 0.45)' : 'rgba(255, 255, 255, 0.3)',
          }}
        >
          {tool.description}
        </p>
      </div>
      <span
        className="mt-1 text-xs opacity-0 transition-opacity group-hover:opacity-100"
        style={{ color: tool.color }}
      >
        ↗
      </span>
    </button>
  )
}

export default function ToolboxPage() {
  const navigate = useNavigate()
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  return (
    <div className="min-h-full flex flex-col" style={{ backgroundColor: '#1a1b2e' }}>
      {/* Hero */}
      <div className="flex flex-col items-center pt-16 pb-12 px-6">
        <button
          type="button"
          onClick={() => navigate('/apps')}
          className="text-xs mb-3 transition-colors"
          style={{
            color: 'rgba(255, 255, 255, 0.35)',
            letterSpacing: '0.1em',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          ← 返回應用列表
        </button>
        <p
          className="text-sm tracking-widest uppercase mb-3"
          style={{ color: 'rgba(255, 255, 255, 0.25)', letterSpacing: '0.2em' }}
        >
          Toolbox
        </p>
        <h1
          style={{
            fontFamily: "'Cormorant Garamond', Georgia, serif",
            fontSize: 'clamp(1.75rem, 4vw, 2.5rem)',
            fontWeight: 400,
            color: 'rgba(255, 255, 255, 0.9)',
            letterSpacing: '0.02em',
          }}
        >
          工具箱
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'rgba(255, 255, 255, 0.3)' }}>
          獨立靜態網頁小工具集合
        </p>
      </div>

      {/* Tools grid */}
      <div className="mx-auto w-full max-w-6xl px-6 pb-16">
        {TOOL_LIST.length === 0 ? (
          <p className="text-center text-sm" style={{ color: 'rgba(255, 255, 255, 0.3)' }}>
            目前尚無工具
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-px sm:grid-cols-2 lg:grid-cols-3">
            {TOOL_LIST.map((tool) => (
              <ToolCard
                key={tool.id}
                tool={tool}
                isHovered={hoveredId === tool.id}
                onHover={setHoveredId}
                onClick={() => {
                  window.location.href = tool.url
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
