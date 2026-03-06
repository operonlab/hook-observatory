import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function MarkdownBlock({ content }: { content: string }) {
  return (
    <article
      className="prose prose-invert max-w-none text-sm leading-relaxed"
      style={{ color: 'var(--bf-text-secondary)', fontFamily: 'var(--bf-font-ui)' }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1
              className="text-xl font-light mt-6 mb-3"
              style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
            >
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2
              className="text-lg font-light mt-5 mb-2"
              style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
            >
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-base font-medium mt-4 mb-2" style={{ color: 'var(--bf-text)' }}>
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="text-sm leading-relaxed my-3" style={{ color: 'var(--bf-text-secondary)' }}>
              {children}
            </p>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
              style={{ color: 'var(--bf-accent)' }}
            >
              {children}
            </a>
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = className?.includes('language-')
            if (isBlock) {
              return (
                <pre
                  className="overflow-x-auto p-3 my-4 text-xs"
                  style={{
                    backgroundColor: 'var(--bf-bg)',
                    borderLeft: '2px solid var(--bf-accent)',
                    fontFamily: 'var(--bf-font-mono)',
                  }}
                >
                  <code>{children}</code>
                </pre>
              )
            }
            return (
              <code
                className="px-1 py-0.5 text-xs"
                style={{
                  backgroundColor: 'var(--bf-bg-surface)',
                  color: 'var(--bf-accent)',
                  fontFamily: 'var(--bf-font-mono)',
                }}
                {...props}
              >
                {children}
              </code>
            )
          },
          blockquote: ({ children }) => (
            <blockquote
              className="pl-4 my-4 text-sm"
              style={{ borderLeft: '2px solid var(--bf-accent)', color: 'var(--bf-text-tertiary)' }}
            >
              {children}
            </blockquote>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-5 space-y-1.5 my-3 text-sm">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 space-y-1.5 my-3 text-sm">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed" style={{ color: 'var(--bf-text-secondary)' }}>
              {children}
            </li>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  )
}
