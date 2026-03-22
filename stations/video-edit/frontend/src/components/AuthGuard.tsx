import { useEffect, useState } from "react";
import { api, ApiError } from "../api";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"loading" | "ok" | "unauthorized">(
    "loading",
  );

  useEffect(() => {
    api
      .health()
      .then(() => setState("ok"))
      .catch((err) => {
        setState(err instanceof ApiError && err.status === 401 ? "unauthorized" : "ok");
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
          className="rounded border border-accent/30 bg-accent/10 px-4 py-2 text-sm text-accent transition-colors hover:bg-accent/20"
        >
          前往登入
        </a>
      </div>
    );
  }

  return <>{children}</>;
}
