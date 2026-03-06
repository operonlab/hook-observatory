import MarkdownBlock from './MarkdownBlock'

interface DebateBubbleProps {
  analystName: string
  analystColor: string
  content: string
  side: 'left' | 'right'
}

export default function DebateBubble({ analystName, analystColor, content, side }: DebateBubbleProps) {
  const isLeft = side === 'left'

  return (
    <div
      className={`flex ${isLeft ? 'justify-start' : 'justify-end'} ${isLeft ? 'bf-bubble-left' : 'bf-bubble-right'}`}
    >
      <div className="max-w-[85%] sm:max-w-[75%]">
        {/* Analyst label */}
        <div
          className={`text-[10px] uppercase tracking-widest mb-1 ${isLeft ? 'text-left' : 'text-right'}`}
          style={{ color: analystColor }}
        >
          {analystName}
        </div>

        {/* Bubble */}
        <div
          className="border px-4 py-3"
          style={{
            backgroundColor: isLeft ? 'var(--bf-bubble-left)' : 'var(--bf-bubble-right)',
            borderColor: 'var(--bf-border)',
            borderLeftWidth: isLeft ? 3 : 1,
            borderRightWidth: isLeft ? 1 : 3,
            borderLeftColor: isLeft ? analystColor : 'var(--bf-border)',
            borderRightColor: isLeft ? 'var(--bf-border)' : analystColor,
          }}
        >
          <MarkdownBlock content={content} />
        </div>
      </div>
    </div>
  )
}
