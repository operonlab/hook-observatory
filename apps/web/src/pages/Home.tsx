import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { APP_LIST } from "@/shared/constants/apps";

export default function Home() {
  const { user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-5xl">
      {/* Welcome */}
      <h1 className="mb-6 text-2xl font-bold sm:text-3xl">
        <span style={{ color: "var(--subtext0)" }}>你好，</span>
        <span style={{ color: "var(--blue)" }}>{user?.name}</span>
      </h1>

      {/* App grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {APP_LIST.map((app) => {
          const isComingSoon = app.status === "coming-soon";

          return (
            <button
              key={app.id}
              onClick={() => {
                if (!isComingSoon) navigate(app.path);
              }}
              className="relative flex flex-col items-start gap-3 rounded-xl border p-5 text-left transition-transform hover:scale-[1.02]"
              style={{
                backgroundColor: "var(--mantle)",
                borderColor: "var(--surface0)",
                opacity: isComingSoon ? 0.55 : 1,
                cursor: isComingSoon ? "not-allowed" : "pointer",
                minHeight: 44,
              }}
              onMouseEnter={(e) => {
                if (!isComingSoon) {
                  (e.currentTarget as HTMLElement).style.borderColor =
                    app.color;
                  (e.currentTarget as HTMLElement).style.boxShadow =
                    `0 4px 20px ${app.color}15`;
                }
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.borderColor =
                  "var(--surface0)";
                (e.currentTarget as HTMLElement).style.boxShadow = "none";
              }}
              disabled={isComingSoon}
            >
              {/* Coming soon badge */}
              {isComingSoon && (
                <span
                  className="absolute right-3 top-3 rounded-full px-2 py-0.5 text-xs"
                  style={{
                    backgroundColor: "var(--surface0)",
                    color: "var(--subtext0)",
                  }}
                >
                  即將推出
                </span>
              )}

              {/* Icon */}
              <span
                className="flex h-12 w-12 items-center justify-center rounded-xl text-2xl"
                style={{
                  backgroundColor: app.color + "18",
                }}
              >
                {app.icon}
              </span>

              {/* Text */}
              <div>
                <h3
                  className="text-base font-semibold"
                  style={{ color: "var(--text)" }}
                >
                  {app.name}
                </h3>
                <p
                  className="mt-0.5 text-sm"
                  style={{ color: "var(--subtext0)" }}
                >
                  {app.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
