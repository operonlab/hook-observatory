// Resource store — receives process data via WebSocket push (resource_snapshot messages)
// Falls back to REST polling if WebSocket is unavailable.

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ProcessInfo } from '../types/ws';

interface ResourceState {
  processes: ProcessInfo[];
  polling: boolean;
  // Called by wsStore when a resource_snapshot WS message arrives
  setProcesses: (procs: ProcessInfo[]) => void;
  // REST polling fallback — used when WS is not connected
  startPolling: () => void;
  stopPolling: () => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
const API_BASE = import.meta.env.BASE_URL.replace(/\/$/, '');
const POLL_INTERVAL = 5000; // 5s fallback (matches backend monitor interval)

export const useResourceStore = create<ResourceState>()(persist((set, get) => ({
  processes: [],
  polling: false,

  setProcesses(procs: ProcessInfo[]) {
    set({ processes: procs });
  },

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
