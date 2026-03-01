import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { APP_LIST } from "@/shared/constants/apps";

export default function Home() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const available = APP_LIST.filter((a) => a.status === "available" || a.status === "external");
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

      {/* App grid — available */}
      <div className="mx-auto w-full max-w-4xl px-6 pb-8">
        <div className="grid grid-cols-1 gap-px sm:grid-cols-2 lg:grid-cols-3">
          {available.map((app) => {
            const isHovered = hoveredId === app.id;
            return (
              <button
                key={app.id}
                onClick={() => {
                  if (app.externalUrl) {
                    window.location.href = app.externalUrl;
                  } else {
                    navigate(app.path);
                  }
                }}
                onMouseEnter={() => setHoveredId(app.id)}
                onMouseLeave={() => setHoveredId(null)}
                className="group relative flex items-start gap-4 p-6 text-left transition-all"
                style={{
                  backgroundColor: isHovered
                    ? app.color + "14"
                    : "transparent",
                  cursor: "pointer",
                  border: "1px solid rgba(255, 255, 255, 0.04)",
                  borderLeft: `2px solid ${isHovered ? app.color : app.color + "40"}`,
                }}
              >
                {/* Icon */}
                <span
                  className="flex h-11 w-11 shrink-0 items-center justify-center text-xl"
                  style={{
                    backgroundColor: isHovered
                      ? app.color + "30"
                      : app.color + "20",
                    border: `1px solid ${app.color}${isHovered ? "50" : "35"}`,
                    borderRadius: "8px",
                    transition: "all 0.2s ease",
                  }}
                >
                  {app.icon}
                </span>

                {/* Text */}
                <div className="min-w-0 flex-1">
                  <h3
                    className="text-sm font-medium transition-colors"
                    style={{
                      color: isHovered
                        ? app.color
                        : "rgba(255, 255, 255, 0.85)",
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

                {/* Arrow indicator */}
                <span
                  className="mt-1 text-xs opacity-0 transition-opacity group-hover:opacity-100"
                  style={{ color: app.color }}
                >
                  {app.externalUrl ? "↗" : "→"}
                </span>
              </button>
            );
          })}
        </div>
      </div>

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
