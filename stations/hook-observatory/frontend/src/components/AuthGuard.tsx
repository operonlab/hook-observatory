import { useEffect, useState } from "react";
import { api, AuthError } from "../api/client.ts";

interface Props {
  children: React.ReactNode;
}

export default function AuthGuard({ children }: Props) {
  const [state, setState] = useState<"loading" | "ok" | "unauthorized">("loading");

  useEffect(() => {
    api
      .health()
      .then(() => api.summary())
      .then(() => setState("ok"))
      .catch((err) => {
        if (err instanceof AuthError) {
          setState("unauthorized");
        } else {
          // Server might be down, still show UI
          setState("ok");
        }
      });
  }, []);

  if (state === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-0">
        <div className="text-sm text-white/30">Loading...</div>
      </div>
    );
  }

  if (state === "unauthorized") {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-6 bg-surface-0">
        <span className="text-4xl">🔒</span>
        <p className="text-sm text-white/50">請先登入 Workshop</p>
        <a
          href="/login"
          className="rounded px-4 py-2 text-sm transition-colors"
          style={{
            backgroundColor: "#89b4fa20",
            color: "#89b4fa",
            border: "1px solid #89b4fa30",
          }}
        >
          前往登入
        </a>
      </div>
    );
  }

  return <>{children}</>;
}
