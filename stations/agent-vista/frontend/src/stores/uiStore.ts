// UI state store — selection, panels, toggles

import { create } from 'zustand';

interface UIState {
  selectedAgentId: string | null;
  selectAgent: (id: string | null) => void;
  detailPanelOpen: boolean;
  toggleDetailPanel: () => void;
  minimapVisible: boolean;
  toggleMinimap: () => void;
  soundMuted: boolean;
  toggleSound: () => void;
}

export const useUIStore = create<UIState>((set, get) => ({
  selectedAgentId: null,
  selectAgent: (id) => set({ selectedAgentId: id, detailPanelOpen: id !== null }),
  detailPanelOpen: false,
  toggleDetailPanel: () => set({ detailPanelOpen: !get().detailPanelOpen }),
  minimapVisible: true,
  toggleMinimap: () => set({ minimapVisible: !get().minimapVisible }),
  soundMuted: typeof localStorage !== 'undefined' ? localStorage.getItem('agent-vista-muted') === 'true' : false,
  toggleSound: () => {
    const next = !get().soundMuted;
    set({ soundMuted: next });
    localStorage.setItem('agent-vista-muted', String(next));
  },
}));
