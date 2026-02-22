import React, { useState } from "react";
import NavBar from "./NavBar";
import Sidebar from "./Sidebar";

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const mainMarginLeft = sidebarCollapsed ? "md:ml-16" : "md:ml-60";

  return (
    <div className="min-h-screen">
      <NavBar onToggleSidebar={() => setSidebarOpen((v) => !v)} />
      <Sidebar
        isOpen={sidebarOpen}
        collapsed={sidebarCollapsed}
        onClose={() => setSidebarOpen(false)}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      />
      <main
        className={`pt-14 transition-all duration-200 ${mainMarginLeft}`}
      >
        <div className="p-4 sm:p-6 lg:p-8">{children}</div>
      </main>
    </div>
  );
}
