import type { MascotState } from "./types.js";

/**
 * Motion file path mapped to each mascot state.
 *
 * Paths are relative to the model root directory (i.e., where the
 * .model3.json lives). Replace these with the actual filenames from
 * your .moc3 asset bundle once the model is available.
 */
const STATE_MOTION_MAP: Record<MascotState, string> = {
  idle: "motions/idle.motion3.json",
  thinking: "motions/thinking.motion3.json",
  speaking: "motions/speaking.motion3.json",
  wave: "motions/wave.motion3.json",
};

/**
 * MotionManager drives mascot animation by mapping logical states to
 * motion file paths, then handing the path to the Live2D SDK caller.
 *
 * The actual SDK call (model.motion()) is delegated to the renderer so
 * this class stays free of SDK / Pixi imports, making it unit-testable.
 */
export class MotionManager {
  private currentState: MascotState = "idle";

  /**
   * Callback invoked whenever a state change requires loading a new motion.
   * The renderer wires this up after construction.
   */
  onMotionRequest?: (motionPath: string, state: MascotState) => void;

  /**
   * Transition to a new mascot state and fire onMotionRequest if registered.
   * Repeated calls with the same state are ignored to avoid motion restart.
   */
  setState(state: MascotState): void {
    if (state === this.currentState) return;

    this.currentState = state;
    const motionPath = STATE_MOTION_MAP[state];
    this.onMotionRequest?.(motionPath, state);
  }

  /** Returns the currently active state. */
  getState(): MascotState {
    return this.currentState;
  }

  /**
   * Resolve the motion file path for a given state without triggering a
   * state transition. Useful for pre-loading assets.
   */
  getMotionPath(state: MascotState): string {
    return STATE_MOTION_MAP[state];
  }
}
