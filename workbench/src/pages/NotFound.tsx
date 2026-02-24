import React from "react";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <h1
        className="text-8xl font-bold"
        style={{ color: "var(--surface1)" }}
      >
        404
      </h1>
      <p
        className="mt-4 text-lg"
        style={{ color: "var(--subtext0)" }}
      >
        找不到此頁面
      </p>
      <Link
        to="/"
        className="mt-6 rounded-lg px-5 py-2.5 text-sm font-medium"
        style={{
          backgroundColor: "var(--blue)",
          color: "var(--crust)",
          minHeight: 44,
          display: "inline-flex",
          alignItems: "center",
        }}
      >
        返回首頁
      </Link>
    </div>
  );
}
