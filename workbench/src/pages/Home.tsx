import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { APP_LIST } from "@/shared/constants/apps";
import type { AppInfo } from "@/types";

function AppCard({
  app,
  isHovered,
  onHover,
  onClick,
}: {
  app: AppInfo;
  isHovered: boolean;
  onHover: (id: string | null) => void;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => onHover(app.id)}
      onMouseLeave={() => onHover(null)}
      className="group relative flex items-start gap-4 p-6 text-left transition-all"
      style={{
        backgroundColor: isHovered ? app.color + "14" : "transparent",
        cursor: "pointer",
        border: "1px solid rgba(255, 255, 255, 0.04)",
        borderLeft: `2px solid ${isHovered ? app.color : app.color + "40"}`,
      }}
    >
      <span
        className="flex h-11 w-11 shrink-0 items-center justify-center text-xl"
        style={{
          backgroundColor: isHovered ? app.color + "30" : app.color + "20",
          border: `1px solid ${app.color}${isHovered ? "50" : "35"}`,
          borderRadius: "8px",
          transition: "all 0.2s ease",
        }}
      >
        {app.icon}
      </span>
      <div className="min-w-0 flex-1">
        <h3
          className="text-sm font-medium transition-colors"
          style={{
            color: isHovered ? app.color : "rgba(255, 255, 255, 0.85)",
          }}
        >
          {app.name}
        </h3>
        <p
          className="mt-1 text-xs leading-relaxed"
          style={{
            color: isHovered
              ? "rgba(255, 255, 255, 0.45)"
              : "rgba(255, 255, 255, 0.3)",
          }}
        >
          {app.description}
        </p>
      </div>
      <span
        className="mt-1 text-xs opacity-0 transition-opacity group-hover:opacity-100"
        style={{ color: app.color }}
      >
        {app.externalUrl ? "↗" : "→"}
      </span>
    </button>
  );
}

export default function Home() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const internal = APP_LIST.filter((a) => a.status === "available");
  const external = APP_LIST.filter((a) => a.status === "external");
  const comingSoon = APP_LIST.filter((a) => a.status === "coming-soon");

  return (
    <div
      className="min-h-full flex flex-col"
      style={{ backgroundColor: "#1a1b2e" }}
    >
      {/* Hero section */}
      <div className="flex flex-col items-center pt-16 pb-12 px-6">
        <p
          className="text-sm tracking-widest uppercase mb-3"
          style={{ color: "rgba(255, 255, 255, 0.25)", letterSpacing: "0.2em" }}
        >
          Workshop
        </p>
        <h1
          style={{
            fontFamily: "'Cormorant Garamond', Georgia, serif",
            fontSize: "clamp(1.75rem, 4vw, 2.5rem)",
            fontWeight: 400,
            color: "rgba(255, 255, 255, 0.9)",
            letterSpacing: "0.02em",
          }}
        >
          {user?.name ? `${user.name}` : "Welcome"}
        </h1>
        <p
          className="mt-2 text-sm"
          style={{ color: "rgba(255, 255, 255, 0.3)" }}
        >
          選擇一個應用開始
        </p>
      </div>

      {/* Internal apps — same React project */}
      <div className="mx-auto w-full max-w-4xl px-6 pb-8">
        <p
          className="mb-4 text-xs tracking-wider uppercase"
          style={{ color: "rgba(255, 255, 255, 0.2)", letterSpacing: "0.15em" }}
        >
          內部系統
        </p>
        <div className="grid grid-cols-1 gap-px sm:grid-cols-2 lg:grid-cols-3">
          {internal.map((app) => (
            <AppCard
              key={app.id}
              app={app}
              isHovered={hoveredId === app.id}
              onHover={setHoveredId}
              onClick={() => navigate(app.path)}
            />
          ))}
        </div>
      </div>

      {/* External apps — standalone stations */}
      {external.length > 0 && (
        <div className="mx-auto w-full max-w-4xl px-6 pb-8">
          <p
            className="mb-4 text-xs tracking-wider uppercase"
            style={{ color: "rgba(255, 255, 255, 0.2)", letterSpacing: "0.15em" }}
          >
            外部系統
          </p>
          <div className="grid grid-cols-1 gap-px sm:grid-cols-2 lg:grid-cols-3">
            {external.map((app) => (
              <AppCard
                key={app.id}
                app={app}
                isHovered={hoveredId === app.id}
                onHover={setHoveredId}
                onClick={() => { window.location.href = app.externalUrl!; }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Coming soon section */}
      {comingSoon.length > 0 && (
        <div className="mx-auto w-full max-w-4xl px-6 pb-16">
          <p
            className="mb-4 text-xs tracking-wider uppercase"
            style={{
              color: "rgba(255, 255, 255, 0.15)",
              letterSpacing: "0.15em",
            }}
          >
            即將推出
          </p>
          <div className="flex flex-wrap gap-6">
            {comingSoon.map((app) => (
              <div
                key={app.id}
                className="flex items-center gap-3"
                style={{ opacity: 0.4 }}
              >
                <span
                  className="flex h-6 w-6 items-center justify-center text-sm"
                  style={{
                    backgroundColor: app.color + "18",
                    borderRadius: "4px",
                  }}
                >
                  {app.icon}
                </span>
                <span
                  className="text-xs"
                  style={{ color: "rgba(255, 255, 255, 0.5)" }}
                >
                  {app.name}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
