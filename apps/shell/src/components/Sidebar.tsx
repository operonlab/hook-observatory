import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { APP_LIST } from "@/constants/apps";

interface SidebarProps {
  isOpen: boolean;
  collapsed: boolean;
  onClose: () => void;
  onToggleCollapse: () => void;
}

export default function Sidebar({
  isOpen,
  collapsed,
  onClose,
  onToggleCollapse,
}: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();

  const sidebarWidth = collapsed ? "w-16" : "w-60";

  return (
    <>
      {/* Mobile overlay backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-14 z-40 flex h-[calc(100vh-3.5rem)] flex-col border-r transition-all duration-200 ${sidebarWidth} ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        } md:translate-x-0`}
        style={{
          backgroundColor: "var(--mantle)",
          borderColor: "var(--surface0)",
        }}
      >
        {/* Collapse toggle (desktop only) */}
        <div className="hidden items-center justify-end p-2 md:flex">
          <button
            onClick={onToggleCollapse}
            className="flex h-8 w-8 items-center justify-center rounded-md"
            style={{ color: "var(--subtext0)" }}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d={
                  collapsed
                    ? "M6 3l5 5-5 5"
                    : "M10 3l-5 5 5 5"
                }
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>

        {/* Nav items */}
        <nav className="flex-1 space-y-1 overflow-y-auto p-2">
          {APP_LIST.map((app) => {
            const isActive = location.pathname.startsWith(app.path);
            const isDisabled = app.status === "coming-soon";

            return (
              <button
                key={app.id}
                onClick={() => {
                  if (!isDisabled) {
                    navigate(app.path);
                    onClose();
                  }
                }}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm ${
                  collapsed ? "justify-center" : ""
                }`}
                style={{
                  minHeight: 44,
                  backgroundColor: isActive
                    ? "var(--surface0)"
                    : "transparent",
                  color: isDisabled
                    ? "var(--surface1)"
                    : isActive
                      ? "var(--text)"
                      : "var(--subtext0)",
                  cursor: isDisabled ? "not-allowed" : "pointer",
                  opacity: isDisabled ? 0.5 : 1,
                }}
                onMouseEnter={(e) => {
                  if (!isActive && !isDisabled) {
                    (e.currentTarget as HTMLElement).style.backgroundColor =
                      "var(--surface0)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isActive) {
                    (e.currentTarget as HTMLElement).style.backgroundColor =
                      "transparent";
                  }
                }}
                disabled={isDisabled}
              >
                <span className="text-lg" style={{ color: app.color }}>
                  {app.icon}
                </span>
                {!collapsed && (
                  <span className="truncate">{app.name}</span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Bottom version */}
        {!collapsed && (
          <div
            className="border-t p-3 text-xs"
            style={{
              borderColor: "var(--surface0)",
              color: "var(--surface1)",
            }}
          >
            Pulso v0.0.1
          </div>
        )}
      </aside>
    </>
  );
}
