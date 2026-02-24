import React, { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import Layout from "@/shell/Layout";
import Home from "@/pages/Home";
import Login from "@/pages/Login";
import NotFound from "@/pages/NotFound";

const FinancePage = React.lazy(() => import("./modules/finance/pages"));
const QuestPage = React.lazy(() => import("./modules/quest/pages"));
const MusePage = React.lazy(() => import("./modules/muse/pages"));
const AdminPage = React.lazy(() => import("./modules/admin/pages"));

function ModuleSuspense({ children }: { children: React.ReactNode }) {
  return (
    <React.Suspense
      fallback={
        <div
          className="flex min-h-[40vh] items-center justify-center"
          style={{ backgroundColor: "var(--base)" }}
        >
          <div
            className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
            style={{ borderColor: "var(--blue)", borderTopColor: "transparent" }}
          />
        </div>
      }
    >
      {children}
    </React.Suspense>
  );
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, initialized } = useAuth();

  if (!initialized) {
    return (
      <div
        className="flex min-h-screen items-center justify-center"
        style={{ backgroundColor: "var(--base)" }}
      >
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: "var(--blue)", borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

function AppRoutes() {
  const { checkSession, initialized } = useAuth();

  useEffect(() => {
    if (!initialized) {
      void checkSession();
    }
  }, [checkSession, initialized]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <AuthGuard>
            <Layout>
              <Home />
            </Layout>
          </AuthGuard>
        }
      />
      <Route
        path="/finance/*"
        element={
          <AuthGuard>
            <Layout>
              <ModuleSuspense>
                <FinancePage />
              </ModuleSuspense>
            </Layout>
          </AuthGuard>
        }
      />
      <Route
        path="/quest/*"
        element={
          <AuthGuard>
            <Layout>
              <ModuleSuspense>
                <QuestPage />
              </ModuleSuspense>
            </Layout>
          </AuthGuard>
        }
      />
      <Route
        path="/muse/*"
        element={
          <AuthGuard>
            <Layout>
              <ModuleSuspense>
                <MusePage />
              </ModuleSuspense>
            </Layout>
          </AuthGuard>
        }
      />
      <Route
        path="/settings/*"
        element={
          <AuthGuard>
            <Layout>
              <ModuleSuspense>
                <AdminPage />
              </ModuleSuspense>
            </Layout>
          </AuthGuard>
        }
      />
      <Route
        path="*"
        element={
          <AuthGuard>
            <Layout>
              <NotFound />
            </Layout>
          </AuthGuard>
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
