/**
 * Tauri invoke wrapper with mock fallback for development.
 * When running outside Tauri (e.g., in a browser), returns mock data.
 */

import type { DependencyResult, ToolPaths, ToolDetailInfo } from "./store";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let tauriInvoke: ((cmd: string, args?: Record<string, unknown>) => Promise<any>) | null = null;

try {
  // Dynamic import — only available inside Tauri runtime
  // @ts-expect-error Tauri API may not exist in dev
  const tauri = window.__TAURI__;
  if (tauri?.core?.invoke) {
    tauriInvoke = tauri.core.invoke;
  }
} catch {
  // Not in Tauri
}

const isTauri = tauriInvoke !== null;

// ── Mock Data ──

const MOCK_DEPS: DependencyResult[] = [
  { name: "python", found: true, path: "/usr/local/bin/python3", version: "3.12.4" },
  { name: "claude_code", found: true, path: "/usr/local/bin/claude", version: "1.0.0" },
  { name: "git", found: true, path: "/usr/bin/git", version: "2.43.0" },
];

const MOCK_TOOL_DETAILS: ToolDetailInfo[] = [
  { name: "python", path: "/usr/local/bin/python3", version: "3.12.4", installed: true, install_command: "brew install python@3.12", required: true },
  { name: "git", path: "/usr/bin/git", version: "2.43.0", installed: true, install_command: "brew install git", required: true },
  { name: "ruff", path: "/usr/local/bin/ruff", version: "0.8.0", installed: true, install_command: "brew install ruff", required: false },
  { name: "biome", path: null, version: null, installed: false, install_command: "pnpm add -g @biomejs/biome", required: false },
  { name: "gh", path: "/usr/local/bin/gh", version: "2.62.0", installed: true, install_command: "brew install gh", required: false },
];

// ── Public API ──

export async function checkDependencies(): Promise<DependencyResult[]> {
  if (isTauri && tauriInvoke) {
    return tauriInvoke("check_dependencies");
  }
  // Mock: simulate network delay
  await new Promise((r) => setTimeout(r, 1200));
  return MOCK_DEPS;
}

export async function detectTools(): Promise<ToolDetailInfo[]> {
  if (isTauri && tauriInvoke) {
    return tauriInvoke("detect_tools");
  }
  await new Promise((r) => setTimeout(r, 800));
  return MOCK_TOOL_DETAILS;
}

export interface InstallOptions {
  components: string[];
  toolPaths: ToolPaths;
}

export interface InstallProgress {
  step: number;
  total: number;
  label: string;
  status: "running" | "done" | "error";
  error?: string;
}

export async function installHooks(
  options: InstallOptions,
  onProgress: (progress: InstallProgress) => void,
): Promise<boolean> {
  if (isTauri && tauriInvoke) {
    // Real Tauri: use a command that reports progress via events
    // For now, call the single install command
    try {
      await tauriInvoke("install_hooks", { options });
      return true;
    } catch (e) {
      throw e;
    }
  }

  // Mock installation
  const steps = [
    "Copying dispatcher...",
    "Registering hook events...",
    "Generating config...",
    "Verifying installation...",
  ];

  for (let i = 0; i < steps.length; i++) {
    onProgress({ step: i, total: steps.length, label: steps[i], status: "running" });
    await new Promise((r) => setTimeout(r, 800 + Math.random() * 600));
    onProgress({ step: i, total: steps.length, label: steps[i], status: "done" });
  }

  return true;
}

export async function closeWindow(): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().close();
  } catch {
    // Not in Tauri runtime
    console.log("Close requested (no-op in browser)");
  }
}
