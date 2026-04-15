import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React, { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useManifest } from '@/hooks/useManifest'
import AppsPage from '@/pages/AppsPage'
import Login from '@/pages/Login'
import NotFound from '@/pages/NotFound'
import ToolboxPage from '@/pages/ToolboxPage'
import AppShell from '@/shell/AppShell'

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean }> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '100vh',
            gap: '16px',
            backgroundColor: '#0a0a0a',
            color: 'rgba(255, 255, 255, 0.7)',
            fontFamily: 'system-ui, sans-serif',
          }}
        >
          <p style={{ fontSize: '1rem', margin: 0 }}>發生錯誤，請重新整理頁面</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              padding: '8px 20px',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              borderRadius: '6px',
              backgroundColor: 'transparent',
              color: 'rgba(255, 255, 255, 0.7)',
              cursor: 'pointer',
              fontSize: '0.875rem',
            }}
          >
            重新整理
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

/** Lazy import with automatic retry on ChunkLoadError (stale cache / network glitch). */
function lazyRetry<T extends React.ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
): React.LazyExoticComponent<T> {
  return React.lazy(() =>
    factory().catch(() => {
      // Chunk failed — reload page once to get fresh assets
      const key = 'chunk-retry'
      if (!sessionStorage.getItem(key)) {
        sessionStorage.setItem(key, '1')
        window.location.reload()
      }
      // If already retried, surface the error to ErrorBoundary
      return factory()
    }),
  )
}

const FinancePage = lazyRetry(() => import('./modules/finance/pages'))
const TaskflowPage = lazyRetry(() => import('./modules/taskflow/pages'))
const IdeagraphPage = lazyRetry(() => import('./modules/ideagraph/pages'))
const AdminPage = lazyRetry(() => import('./modules/admin/pages'))
const IntelflowPage = lazyRetry(() => import('./modules/intelflow/pages'))
const MemvaultPage = lazyRetry(() => import('./modules/memvault/pages'))
const SkillpathPage = lazyRetry(() => import('./modules/skillpath/pages'))
const WorkpoolPage = lazyRetry(() => import('./modules/workpool/pages'))
const InvestPage = lazyRetry(() => import('./modules/invest/pages'))
const MatchcorePage = lazyRetry(() => import('./modules/matchcore/pages'))
const NodeflowPage = lazyRetry(() => import('./modules/nodeflow/pages'))
const AnvilPage = lazyRetry(() => import('./modules/anvil/pages'))
const CapturePage = lazyRetry(() => import('./modules/capture/pages'))
const DailyosPage = lazyRetry(() => import('./modules/dailyos/pages'))
const BriefingPage = lazyRetry(() => import('./modules/briefing/pages'))
const NotificationPage = lazyRetry(() => import('./modules/notification/pages'))
const PaperPage = lazyRetry(() => import('./modules/paper/pages'))

function ModuleSuspense({ children }: { children: React.ReactNode }) {
  return (
    <React.Suspense
      fallback={
        <div
          className="flex min-h-[40vh] items-center justify-center"
          style={{ backgroundColor: 'var(--base)' }}
        >
          <div
            className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
            style={{
              borderColor: 'var(--accent)',
              borderTopColor: 'transparent',
            }}
          />
        </div>
      }
    >
      {children}
    </React.Suspense>
  )
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, initialized } = useAuth()

  if (!initialized) {
    return (
      <div
        className="flex min-h-screen items-center justify-center"
        style={{ backgroundColor: 'var(--base)' }}
      >
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{
            borderColor: 'var(--accent)',
            borderTopColor: 'transparent',
          }}
        />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function AppRoutes() {
  const { checkSession, initialized } = useAuth()
  useManifest()

  useEffect(() => {
    if (!initialized) {
      void checkSession()
    }
  }, [checkSession, initialized])

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Navigate to="/apps" replace />} />
      <Route
        path="/apps"
        element={
          <AuthGuard>
            <AppShell>
              <AppsPage />
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/toolbox"
        element={
          <AuthGuard>
            <AppShell>
              <ToolboxPage />
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/finance/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <FinancePage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/taskflow/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <TaskflowPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/ideagraph/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <IdeagraphPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/admin/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <AdminPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/intelflow/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <IntelflowPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/memvault/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <MemvaultPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/skillpath/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <SkillpathPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/workpool/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <WorkpoolPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/invest/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <InvestPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/nodeflow/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <NodeflowPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/matchcore/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <MatchcorePage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/anvil/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <AnvilPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/capture/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <CapturePage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/dailyos/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <DailyosPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/briefing/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <BriefingPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/notification/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <NotificationPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="/paper/*"
        element={
          <AuthGuard>
            <AppShell>
              <ModuleSuspense>
                <PaperPage />
              </ModuleSuspense>
            </AppShell>
          </AuthGuard>
        }
      />
      <Route
        path="*"
        element={
          <AuthGuard>
            <AppShell>
              <NotFound />
            </AppShell>
          </AuthGuard>
        }
      />
    </Routes>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes — matches existing _fetchedAt STALE_TTL
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={__BASE_PATH__ || '/'}>
          <AppRoutes />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
