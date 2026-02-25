// Timeline recorder + replay system (C6)
// Records agent position/state snapshots at intervals, supports playback

import type { AgentEntry } from '../stores/agentStore';
import type { AnimationState } from '../types/agent';

export interface AgentSnapshot {
  id: string;
  cliType: string;
  sessionId: string;
  x: number;
  y: number;
  state: AnimationState;
  bubble: string | null;
  subAgentCount: number;
}

export interface TimelineFrame {
  timestamp: number;
  agents: AgentSnapshot[];
}

const RECORD_INTERVAL = 5000;  // snapshot every 5s
const MAX_FRAMES = 720;        // ~1 hour at 5s intervals

export class TimelineRecorder {
  private frames: TimelineFrame[] = [];
  private recording = true;
  private lastRecordTime = 0;

  /** Record a snapshot of current agent state */
  record(agents: Map<string, AgentEntry>) {
    if (!this.recording) return;
    const now = Date.now();
    if (now - this.lastRecordTime < RECORD_INTERVAL) return;
    this.lastRecordTime = now;

    const snapshots: AgentSnapshot[] = [];
    for (const [id, entry] of agents) {
      if (entry.fsm.despawning) continue;
      snapshots.push({
        id,
        cliType: entry.agent.cli_type,
        sessionId: entry.agent.session_id ?? id,
        x: entry.fsm.pixelX,
        y: entry.fsm.pixelY,
        state: entry.fsm.state,
        bubble: entry.fsm.bubble,
        subAgentCount: entry.fsm.subAgents.length,
      });
    }

    this.frames.push({ timestamp: now, agents: snapshots });

    // Ring buffer — drop oldest when full
    if (this.frames.length > MAX_FRAMES) {
      this.frames = this.frames.slice(-MAX_FRAMES);
    }
  }

  /** Get all recorded frames */
  getFrames(): readonly TimelineFrame[] {
    return this.frames;
  }

  /** Get frame count */
  get frameCount(): number {
    return this.frames.length;
  }

  /** Get the time range covered */
  getTimeRange(): { start: number; end: number } | null {
    if (this.frames.length === 0) return null;
    return {
      start: this.frames[0].timestamp,
      end: this.frames[this.frames.length - 1].timestamp,
    };
  }

  /** Get frame at specific index */
  getFrame(index: number): TimelineFrame | null {
    return this.frames[index] ?? null;
  }

  /** Find closest frame to a timestamp */
  getFrameAtTime(t: number): TimelineFrame | null {
    if (this.frames.length === 0) return null;
    // Binary search
    let lo = 0, hi = this.frames.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.frames[mid].timestamp < t) lo = mid + 1;
      else hi = mid;
    }
    return this.frames[lo];
  }

  /** Pause recording (during replay) */
  pause() { this.recording = false; }

  /** Resume recording */
  resume() { this.recording = true; }

  /** Clear all recorded data */
  clear() { this.frames = []; }
}

/** Global singleton */
export const timelineRecorder = new TimelineRecorder();
