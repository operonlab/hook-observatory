import { create } from "zustand";

export interface DependencyResult {
  name: string;
  found: boolean;
  path?: string;
  version?: string;
}

export interface InstallStep {
  label: string;
  status: "pending" | "running" | "done" | "error";
  error?: string;
}

export type ComponentCategory = "required" | "optional" | "advanced";

export interface HookComponent {
  id: string;
  category: ComponentCategory;
  enabled: boolean;
  locked: boolean; // required components are locked on
  icon: string;
}

export const DEFAULT_COMPONENTS: HookComponent[] = [
  // Required (locked on)
  { id: "bash_safety", category: "required", enabled: true, locked: true, icon: "🛡️" },
  { id: "auto_format", category: "required", enabled: true, locked: true, icon: "✨" },
  { id: "secret_scan", category: "required", enabled: true, locked: true, icon: "🔐" },
  { id: "agent_naming", category: "required", enabled: true, locked: true, icon: "🏷️" },
  { id: "observability", category: "required", enabled: true, locked: true, icon: "📹" },
  // Optional (default on)
  { id: "verify_commit", category: "optional", enabled: true, locked: false, icon: "✅" },
  { id: "review_gate", category: "optional", enabled: true, locked: false, icon: "👀" },
  { id: "plan_impl_gate", category: "optional", enabled: true, locked: false, icon: "📋" },
  { id: "skill_security", category: "optional", enabled: true, locked: false, icon: "🔒" },
  // Advanced (default off)
  { id: "voice_notify", category: "advanced", enabled: false, locked: false, icon: "🔊" },
  { id: "pm_autopilot", category: "advanced", enabled: false, locked: false, icon: "🤖" },
];

export interface ToolPaths {
  python: string;
  ruff: string;
  biome: string;
}

interface InstallerState {
  currentStep: number;
  dependencies: DependencyResult[];
  components: HookComponent[];
  toolPaths: ToolPaths;
  installSteps: InstallStep[];
  installError: string | null;

  setStep: (step: number) => void;
  nextStep: () => void;
  prevStep: () => void;
  setDependencies: (deps: DependencyResult[]) => void;
  toggleComponent: (id: string) => void;
  setToolPaths: (paths: Partial<ToolPaths>) => void;
  setInstallSteps: (steps: InstallStep[]) => void;
  updateInstallStep: (index: number, update: Partial<InstallStep>) => void;
  setInstallError: (error: string | null) => void;
  reset: () => void;
}

const initialState = {
  currentStep: 1,
  dependencies: [],
  components: DEFAULT_COMPONENTS.map((c) => ({ ...c })),
  toolPaths: { python: "", ruff: "", biome: "" },
  installSteps: [],
  installError: null,
};

export const useInstallerStore = create<InstallerState>((set) => ({
  ...initialState,

  setStep: (step) => set({ currentStep: step }),
  nextStep: () => set((s) => ({ currentStep: Math.min(s.currentStep + 1, 6) })),
  prevStep: () => set((s) => ({ currentStep: Math.max(s.currentStep - 1, 1) })),

  setDependencies: (deps) => set({ dependencies: deps }),

  toggleComponent: (id) =>
    set((s) => ({
      components: s.components.map((c) =>
        c.id === id && !c.locked ? { ...c, enabled: !c.enabled } : c,
      ),
    })),

  setToolPaths: (paths) =>
    set((s) => ({ toolPaths: { ...s.toolPaths, ...paths } })),

  setInstallSteps: (steps) => set({ installSteps: steps }),

  updateInstallStep: (index, update) =>
    set((s) => ({
      installSteps: s.installSteps.map((step, i) =>
        i === index ? { ...step, ...update } : step,
      ),
    })),

  setInstallError: (error) => set({ installError: error }),

  reset: () => set({ ...initialState, components: DEFAULT_COMPONENTS.map((c) => ({ ...c })) }),
}));
