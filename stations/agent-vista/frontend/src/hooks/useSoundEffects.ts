// Hook: trigger sound effects based on agent events

import { useEffect, useRef } from 'react';
import { useAgentStore } from '../stores/agentStore';
import { useUIStore } from '../stores/uiStore';
import { soundEngine } from '../engine/SoundEngine';

export function useSoundEffects() {
  const agents = useAgentStore(s => s.agents);
  const soundMuted = useUIStore(s => s.soundMuted);
  const prevAgentIds = useRef(new Set<string>());
  const prevStatuses = useRef(new Map<string, string>());

  // Sync mute state
  useEffect(() => {
    soundEngine.muted = soundMuted;
  }, [soundMuted]);

  useEffect(() => {
    const currentIds = new Set(agents.keys());
    const prevIds = prevAgentIds.current;
    const prevStatus = prevStatuses.current;

    // New agents (session start)
    for (const id of currentIds) {
      if (!prevIds.has(id)) {
        soundEngine.playPing();
        break; // Only one ping per batch
      }
    }

    // Removed agents (session end)
    for (const id of prevIds) {
      if (!currentIds.has(id)) {
        soundEngine.playFarewell();
        break;
      }
    }

    // Status changes
    for (const [id, entry] of agents) {
      const prev = prevStatus.get(id);
      const curr = entry.agent.status;
      if (prev && prev !== curr) {
        if (curr === 'waiting') {
          soundEngine.playAlert();
        } else if (curr === 'error') {
          soundEngine.playError();
        }
      }
      // Sub-agent spawn detection
      const fsm = entry.fsm;
      if (fsm.subAgents.length > 0) {
        // Check if we have new sub-agents (simple heuristic: compare count)
        const prevEntry = prevStatus.get(id + ':subs');
        const currCount = String(fsm.subAgents.length);
        if (prevEntry && prevEntry !== currCount && Number(currCount) > Number(prevEntry)) {
          soundEngine.playSparkle();
        }
        prevStatus.set(id + ':subs', currCount);
      }
    }

    // Update refs
    prevAgentIds.current = currentIds;
    const nextStatus = new Map<string, string>();
    for (const [id, entry] of agents) {
      nextStatus.set(id, entry.agent.status);
      nextStatus.set(id + ':subs', String(entry.fsm.subAgents.length));
    }
    prevStatuses.current = nextStatus;
  }, [agents]);
}
