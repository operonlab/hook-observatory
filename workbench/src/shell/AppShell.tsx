import { useEffect, useMemo, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { APP_LIST } from '@/shared/constants/apps'
import AppHeader from '@/shell/AppHeader'

// Import the Web Component (side-effect: registers <ai-assistant>)
import '@workshop/ai-assistant'

interface AppShellProps {
  children: React.ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const location = useLocation()
  const assistantRef = useRef<HTMLElement>(null)

  // Sync current module to ai-assistant Web Component
  const currentAppId = useMemo(
    () => APP_LIST.find((a) => location.pathname.startsWith(a.path))?.id ?? null,
    [location.pathname],
  )

  useEffect(() => {
    if (assistantRef.current) {
      assistantRef.current.setAttribute('module', currentAppId ?? '')
    }
  }, [currentAppId])

  return (
    <>
      <AppHeader />
      <div className="pt-12 h-screen">
        <div className="h-full overflow-y-auto">{children}</div>
      </div>
      {/* @ts-expect-error Web Component not typed in JSX */}
      <ai-assistant
        ref={assistantRef}
        mode="workshop"
        api-url="/api/assistant/chat"
        position="bottom-right"
        greeting="有什麼我可以幫忙的嗎？"
      />
    </>
  )
}
