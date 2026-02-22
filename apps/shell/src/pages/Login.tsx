import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

type Tab = "login" | "register";

export default function Login() {
  const navigate = useNavigate();
  const { login, register, loading } = useAuth();

  const [tab, setTab] = useState<Tab>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    // Basic validation
    if (!email.trim() || !password.trim()) {
      setError("請填寫所有必填欄位");
      return;
    }
    if (tab === "register" && !name.trim()) {
      setError("請填寫名稱");
      return;
    }
    if (password.length < 6) {
      setError("密碼至少需要 6 個字元");
      return;
    }

    try {
      if (tab === "login") {
        await login(email, password);
      } else {
        await register(email, password, name);
      }
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "發生錯誤，請稍後再試");
    }
  };

  return (
    <div
      className="flex min-h-screen items-center justify-center p-4"
      style={{ backgroundColor: "var(--base)" }}
    >
      <div
        className="w-full max-w-sm rounded-2xl border p-6"
        style={{
          backgroundColor: "var(--mantle)",
          borderColor: "var(--surface0)",
        }}
      >
        {/* Logo */}
        <h1
          className="mb-6 text-center text-3xl font-bold"
          style={{ color: "var(--blue)" }}
        >
          Pulso
        </h1>

        {/* Tabs */}
        <div
          className="mb-5 flex rounded-lg p-1"
          style={{ backgroundColor: "var(--surface0)" }}
        >
          {(["login", "register"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                setError("");
              }}
              className="flex-1 rounded-md py-2 text-sm font-medium transition-colors"
              style={{
                backgroundColor:
                  tab === t ? "var(--mantle)" : "transparent",
                color:
                  tab === t ? "var(--text)" : "var(--subtext0)",
                minHeight: 44,
              }}
            >
              {t === "login" ? "登入" : "註冊"}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          {tab === "register" && (
            <div>
              <label
                className="mb-1 block text-sm"
                style={{ color: "var(--subtext0)" }}
              >
                名稱
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
                style={{
                  backgroundColor: "var(--base)",
                  borderColor: "var(--surface0)",
                  color: "var(--text)",
                  minHeight: 44,
                }}
                placeholder="你的名稱"
                autoComplete="name"
              />
            </div>
          )}

          <div>
            <label
              className="mb-1 block text-sm"
              style={{ color: "var(--subtext0)" }}
            >
              電子郵件
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
              style={{
                backgroundColor: "var(--base)",
                borderColor: "var(--surface0)",
                color: "var(--text)",
                minHeight: 44,
              }}
              placeholder="name@example.com"
              autoComplete="email"
            />
          </div>

          <div>
            <label
              className="mb-1 block text-sm"
              style={{ color: "var(--subtext0)" }}
            >
              密碼
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none focus:ring-2"
              style={{
                backgroundColor: "var(--base)",
                borderColor: "var(--surface0)",
                color: "var(--text)",
                minHeight: 44,
              }}
              placeholder="至少 6 個字元"
              autoComplete={
                tab === "login" ? "current-password" : "new-password"
              }
            />
          </div>

          {/* Error */}
          {error && (
            <p
              className="rounded-lg px-3 py-2 text-sm"
              style={{
                backgroundColor: "var(--red)" + "15",
                color: "var(--red)",
              }}
            >
              {error}
            </p>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg py-2.5 text-sm font-medium transition-opacity disabled:opacity-50"
            style={{
              backgroundColor: "var(--blue)",
              color: "var(--crust)",
              minHeight: 44,
            }}
          >
            {loading
              ? "處理中..."
              : tab === "login"
                ? "登入"
                : "建立帳號"}
          </button>
        </form>
      </div>
    </div>
  );
}
