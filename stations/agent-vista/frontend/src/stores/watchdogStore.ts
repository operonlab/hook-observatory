// Usage Watchdog store — tracks token consumption rate and budget alerts

import { create } from 'zustand';
import { useAgentStore } from './agentStore';

export type AlertLevel = 'normal' | 'warn' | 'critical';

interface TokenSnapshot {
  timestamp: number;
  total: number;
}

interface WatchdogState {
  // Budget settings (0 = no limit)
  dailyBudgetUSD: number;
  setDailyBudget: (usd: number) => void;

  // Token history (1-minute snapshots, last 60 entries = 1 hour)
  snapshots: TokenSnapshot[];

  // Computed rates
  tokensPerMinute: number;
  tokensPerHour: number;
  estimatedDailyCostUSD: number;

  // Alert state
  alertLevel: AlertLevel;
  alertMessage: string | null;

  // Session totals
  sessionStartTime: number;
  sessionTokensStart: number;

  // Control
  startWatching: () => void;
  stopWatching: () => void;
}

// Rough blended cost per 1M tokens by CLI type
const COST_PER_MTOK: Record<string, number> = {
  claude: 12,
  codex: 8,
  gemini: 3.5,
};

let watchTimer: ReturnType<typeof setInterval> | null = null;

function computeTotalTokens(): { total: number; costPerMTok: number } {
  const agents = useAgentStore.getState().agents;
  let total = 0;
  let weightedCost = 0;
  for (const { agent } of agents.values()) {
    total += agent.tokens_total;
    const rate = COST_PER_MTOK[agent.cli_type] ?? 5;
    weightedCost += agent.tokens_total * rate;
  }
  const avgCost = total > 0 ? weightedCost / total : 5;
  return { total, costPerMTok: avgCost };
}

export const useWatchdogStore = create<WatchdogState>((set, get) => ({
  dailyBudgetUSD: 0,
  snapshots: [],
  tokensPerMinute: 0,
  tokensPerHour: 0,
  estimatedDailyCostUSD: 0,
  alertLevel: 'normal',
  alertMessage: null,
  sessionStartTime: Date.now(),
  sessionTokensStart: 0,

  setDailyBudget(usd) {
    set({ dailyBudgetUSD: usd });
  },

  startWatching() {
    if (watchTimer) return;
    const { total } = computeTotalTokens();
    set({ sessionStartTime: Date.now(), sessionTokensStart: total });

    watchTimer = setInterval(() => {
      const state = get();
      const { total, costPerMTok } = computeTotalTokens();
      const now = Date.now();

      // Add snapshot
      const snapshots = [...state.snapshots, { timestamp: now, total }];
      // Keep last 60 entries (1 hour of 1-minute snapshots)
      while (snapshots.length > 60) snapshots.shift();

      // Calculate rate from snapshots
      let tokensPerMinute = 0;
      let tokensPerHour = 0;
      if (snapshots.length >= 2) {
        const oldest = snapshots[0];
        const newest = snapshots[snapshots.length - 1];
        const elapsedMin = (newest.timestamp - oldest.timestamp) / 60000;
        if (elapsedMin > 0) {
          const deltaTokens = newest.total - oldest.total;
          tokensPerMinute = Math.max(0, deltaTokens / elapsedMin);
          tokensPerHour = tokensPerMinute * 60;
        }
      }

      // Estimate daily cost based on hourly rate
      const estimatedDailyCostUSD = (tokensPerHour * 24 / 1_000_000) * costPerMTok;

      // Alert logic
      let alertLevel: AlertLevel = 'normal';
      let alertMessage: string | null = null;
      const budget = state.dailyBudgetUSD;

      if (budget > 0) {
        // Session spend so far
        const sessionTokens = total - state.sessionTokensStart;
        const sessionCost = (sessionTokens / 1_000_000) * costPerMTok;
        const sessionHours = (now - state.sessionStartTime) / 3600000;
        const projectedDailyCost = sessionHours > 0 ? (sessionCost / sessionHours) * 24 : 0;

        if (projectedDailyCost > budget) {
          alertLevel = 'critical';
          alertMessage = `預測日花費 $${projectedDailyCost.toFixed(2)} 超過預算 $${budget}`;
        } else if (projectedDailyCost > budget * 0.7) {
          alertLevel = 'warn';
          alertMessage = `預測日花費 $${projectedDailyCost.toFixed(2)} 接近預算 $${budget}`;
        }
      } else if (tokensPerMinute > 50000) {
        // No budget set but very high burn rate
        alertLevel = 'warn';
        alertMessage = `高消耗速率：${Math.round(tokensPerMinute).toLocaleString()} tok/min`;
      }

      set({
        snapshots,
        tokensPerMinute,
        tokensPerHour,
        estimatedDailyCostUSD,
        alertLevel,
        alertMessage,
      });
    }, 60000); // Check every 60 seconds
  },

  stopWatching() {
    if (watchTimer) {
      clearInterval(watchTimer);
      watchTimer = null;
    }
  },
}));
