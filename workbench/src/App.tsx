import React, { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { useManifest } from '@/hooks/useManifest'
import AppsPage from '@/pages/AppsPage'
import Login from '@/pages/Login'
import NotFound from '@/pages/NotFound'
import AppShell from '@/shell/AppShell'

const FinancePage = React.lazy(() => import('./modules/finance/pages'))
const TaskflowPage = React.lazy(() => import('./modules/taskflow/pages'))
const IdeagraphPage = React.lazy(() => import('./modules/ideagraph/pages'))
const AdminPage = React.lazy(() => import('./modules/admin/pages'))
const IntelflowPage = React.lazy(() => import('./modules/intelflow/pages'))
const MemvaultPage = React.lazy(() => import('./modules/memvault/pages'))
const SkillpathPage = React.lazy(() => import('./modules/skillpath/pages'))
const WorkpoolPage = React.lazy(() => import('./modules/workpool/pages'))
const MatchcorePage = React.lazy(() => import('./modules/matchcore/pages'))

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

export default function App() {
  return (
    <BrowserRouter basename={__BASE_PATH__ || '/'}>
      <AppRoutes />
    </BrowserRouter>
  )
}
