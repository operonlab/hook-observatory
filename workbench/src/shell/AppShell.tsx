import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { APP_LIST } from '@/shared/constants/apps'
import AppHeader from '@/shell/AppHeader'
import ChatPanel from '@/shell/ChatPanel'
import { useChatStore } from '@/stores/chat'

interface AppShellProps {
  children: React.ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const location = useLocation()
  const setCurrentModule = useChatStore((s) => s.setCurrentModule)

  // Sync current module to chat store
  useEffect(() => {
    const app = APP_LIST.find((a) => location.pathname.startsWith(a.path))
    setCurrentModule(app?.id ?? null)
  }, [location.pathname, setCurrentModule])

  return (
    <>
      <AppHeader />
      <div className="pt-12 h-screen">
        <div className="h-full overflow-y-auto">{children}</div>
      </div>
      <ChatPanel />
    </>
  )
}
