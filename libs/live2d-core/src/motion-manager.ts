import type { MascotState } from "./types.js";

/**
 * Animation parameters for a single mascot state.
 * All timing values are in seconds.
 */
export interface StateAnimation {
  /** Y oscillation: peak displacement in px, full cycle period in seconds. */
  float: { amplitude: number; period: number };
  /** Scale oscillation: min and max scale, full cycle period. */
  breathe: { min: number; max: number; period: number };
  /** Container rotation oscillation: half-angle in degrees, full cycle period. */
  sway: { angle: number; period: number };
  /** Additional hair X oscillation: amplitude in px, period in seconds. */
  hairSway: { amplitude: number; period: number };
  /** Wing rotation oscillation: half-angle in degrees, period in seconds. */
  wingFlap: { amplitude: number; period: number };
  /** Particle emission rate (particles per second). */
  particleRate: number;
  /** Glow intensity 0-1 (applied to thinking state blur overlay). */
  glowStrength: number;
  /** Crossfade duration when entering this state, in milliseconds. */
  crossfadeDuration: number;
}

const PRESETS: Record<MascotState, StateAnimation> = {
  idle: {
    float:            { amplitude: 5,   period: 3   },
    breathe:          { min: 0.98, max: 1.02, period: 4   },
    sway:             { angle: 0.5, period: 5   },
    hairSway:         { amplitude: 3,   period: 2.5 },
    wingFlap:         { amplitude: 5,   period: 2   },
    particleRate:     0.3,
    glowStrength:     0,
    crossfadeDuration: 600,
  },
  thinking: {
    float:            { amplitude: 0,   period: 3   },
    breathe:          { min: 0.97, max: 1.03, period: 2   },
    sway:             { angle: -2,  period: 99  },  // static tilt, very slow
    hairSway:         { amplitude: 1.5, period: 4   },
    wingFlap:         { amplitude: 0,   period: 2   },
    particleRate:     0.1,
    glowStrength:     0.5,
    crossfadeDuration: 800,
  },
  speaking: {
    float:            { amplitude: 3,   period: 0.6 },
    breathe:          { min: 1.0,  max: 1.03, period: 0.6 },
    sway:             { angle: 0,   period: 5   },
    hairSway:         { amplitude: 4,   period: 1.2 },
    wingFlap:         { amplitude: 2,   period: 1.5 },
    particleRate:     1,
    glowStrength:     0,
    crossfadeDuration: 300,
  },
  wave: {
    float:            { amplitude: 5,   period: 3   },
    breathe:          { min: 0.98, max: 1.02, period: 4   },
    sway:             { angle: 0.5, period: 5   },
    hairSway:         { amplitude: 8,   period: 1   },
    wingFlap:         { amplitude: 15,  period: 0.8 },
    particleRate:     3,
    glowStrength:     0,
    crossfadeDuration: 400,
  },
};

/**
 * MotionManager is a pure state machine — no SDK / Pixi imports.
 * It interpolates animation parameter presets and exposes the current
 * blended values for the renderer to consume each tick.
 */
export class MotionManager {
  private currentState: MascotState = "idle";
  private targetState:  MascotState = "idle";

  /** Current blended animation parameters (mutated in place each tick). */
  readonly current: StateAnimation = { ...PRESETS.idle };

  /** Progress of the active crossfade: 0 = just started, 1 = complete. */
  private crossfadeProgress = 1;
  private crossfadeDurationMs = 0;
  private fromSnapshot: StateAnimation = { ...PRESETS.idle };

  /** Returns the currently active target state. */
  getState(): MascotState {
    return this.targetState;
  }

  /**
   * Transition to a new mascot state.
   * Immediately begins crossfading animation params toward the target preset.
   * Repeated calls with the same state are ignored.
   */
  setState(state: MascotState): void {
    if (state === this.targetState) return;

    // Snapshot whatever blended values we're at right now as the crossfade origin.
    this.fromSnapshot = { ...this.current };
    this.targetState = state;
    this.crossfadeDurationMs = PRESETS[state].crossfadeDuration;
    this.crossfadeProgress = 0;
  }

  /**
   * Advance the state machine by `deltaMs` milliseconds.
   * Call this once per ticker tick before reading `this.current`.
   */
  tick(deltaMs: number): void {
    if (this.crossfadeProgress >= 1) {
      // Fully settled — copy preset directly to avoid drift.
      Object.assign(this.current, PRESETS[this.targetState]);
      this.currentState = this.targetState;
      return;
    }

    this.crossfadeProgress = Math.min(
      1,
      this.crossfadeProgress + deltaMs / this.crossfadeDurationMs,
    );
    const t = this.easeInOut(this.crossfadeProgress);
    const target = PRESETS[this.targetState];
    const from   = this.fromSnapshot;

    // Lerp all numeric scalar fields.
    this.current.float.amplitude   = lerp(from.float.amplitude,   target.float.amplitude,   t);
    this.current.float.period      = lerp(from.float.period,      target.float.period,      t);
    this.current.breathe.min       = lerp(from.breathe.min,       target.breathe.min,       t);
    this.current.breathe.max       = lerp(from.breathe.max,       target.breathe.max,       t);
    this.current.breathe.period    = lerp(from.breathe.period,    target.breathe.period,    t);
    this.current.sway.angle        = lerp(from.sway.angle,        target.sway.angle,        t);
    this.current.sway.period       = lerp(from.sway.period,       target.sway.period,       t);
    this.current.hairSway.amplitude= lerp(from.hairSway.amplitude,target.hairSway.amplitude,t);
    this.current.hairSway.period   = lerp(from.hairSway.period,   target.hairSway.period,   t);
    this.current.wingFlap.amplitude= lerp(from.wingFlap.amplitude,target.wingFlap.amplitude,t);
    this.current.wingFlap.period   = lerp(from.wingFlap.period,   target.wingFlap.period,   t);
    this.current.particleRate      = lerp(from.particleRate,      target.particleRate,      t);
    this.current.glowStrength      = lerp(from.glowStrength,      target.glowStrength,      t);
    this.current.crossfadeDuration = target.crossfadeDuration;

    if (this.crossfadeProgress >= 1) {
      this.currentState = this.targetState;
    }
  }

  /** Returns the raw preset for a given state (useful for one-shot tweens). */
  getPreset(state: MascotState): Readonly<StateAnimation> {
    return PRESETS[state];
  }

  private easeInOut(t: number): number {
    return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
  }
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}
