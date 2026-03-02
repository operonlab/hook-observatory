// Resource store — polls /api/resources for system process data

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ProcessInfo } from '../types/ws';

interface ResourceState {
  processes: ProcessInfo[];
  polling: boolean;
  startPolling: () => void;
  stopPolling: () => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
const API_BASE = import.meta.env.BASE_URL.replace(/\/$/, '');
const POLL_INTERVAL = 5000; // 5s (matches backend monitor interval)

export const useResourceStore = create<ResourceState>()(persist((set, get) => ({
  processes: [],
  polling: false,

  startPolling() {
    if (get().polling) return;
    set({ polling: true });

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/resources`);
        if (res.ok) {
          const procs: ProcessInfo[] = await res.json();
          set({ processes: procs });
        }
      } catch {
        // Will retry next interval
      }
    };

    poll(); // immediate first fetch
    pollTimer = setInterval(poll, POLL_INTERVAL);
  },

  stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    set({ polling: false });
  },
}), {
  name: 'agent-vista-resources',
  partialize: (state) => ({ processes: state.processes }),
}));
