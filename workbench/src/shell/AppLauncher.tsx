import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { APP_LIST } from "@/shared/constants/apps";

interface AppLauncherProps {
  onClose: () => void;
}

export default function AppLauncher({ onClose }: AppLauncherProps) {
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute right-0 top-12 z-50 grid grid-cols-2 gap-2 rounded-xl border p-4 shadow-lg md:grid-cols-3"
      style={{
        backgroundColor: "var(--mantle)",
        borderColor: "var(--surface0)",
        minWidth: 240,
      }}
    >
      {APP_LIST.map((app) => (
        <button
          key={app.id}
          onClick={() => {
            if (app.status === "available") {
              navigate(app.path);
            }
            onClose();
          }}
          className="flex flex-col items-center gap-1.5 rounded-lg p-3 hover:opacity-80"
          style={{
            backgroundColor: "transparent",
            opacity: app.status === "coming-soon" ? 0.45 : 1,
            minHeight: 44,
            minWidth: 44,
            cursor:
              app.status === "coming-soon" ? "not-allowed" : "pointer",
          }}
          onMouseEnter={(e) => {
            if (app.status === "available") {
              (e.currentTarget as HTMLElement).style.backgroundColor =
                "var(--surface0)";
            }
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.backgroundColor =
              "transparent";
          }}
          disabled={app.status === "coming-soon"}
        >
          <span
            className="flex h-10 w-10 items-center justify-center rounded-full text-xl"
            style={{ backgroundColor: app.color + "22", color: app.color }}
          >
            {app.icon}
          </span>
          <span className="text-xs" style={{ color: "var(--text)" }}>
            {app.name}
          </span>
        </button>
      ))}
    </div>
  );
}
