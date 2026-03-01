import { Routes, Route, Navigate, Link, useLocation } from "react-router-dom";
import AuthGuard from "./components/AuthGuard.tsx";
import Dashboard from "./pages/Dashboard.tsx";
import Events from "./pages/Events.tsx";

export default function App() {
  return (
    <AuthGuard>
      <div className="min-h-screen bg-surface-0">
        {/* Header */}
        <header
          className="sticky top-0 z-40 flex items-center justify-between px-6 h-12"
          style={{
            background: "rgba(10, 10, 14, 0.85)",
            backdropFilter: "blur(12px)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.04)",
          }}
        >
          <div className="flex items-center gap-3">
            <span className="text-lg">📡</span>
            <span className="text-sm font-medium text-white/80">Hook Observatory</span>
          </div>
          <nav className="flex gap-4">
            <NavLink to="/">Dashboard</NavLink>
            <NavLink to="/events">Events</NavLink>
          </nav>
        </header>

        {/* Content */}
        <main className="mx-auto max-w-7xl px-6 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/events" element={<Events />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </AuthGuard>
  );
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const isActive = pathname === to;
  return (
    <Link
      to={to}
      className="text-xs transition-colors"
      style={{
        color: isActive ? "#89b4fa" : "rgba(255, 255, 255, 0.4)",
        borderBottom: isActive ? "1px solid #89b4fa" : "1px solid transparent",
        paddingBottom: 2,
      }}
    >
      {children}
    </Link>
  );
}
