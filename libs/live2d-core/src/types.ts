/**
 * Mascot animation states driven by AI assistant events.
 * - idle:     default breathing loop
 * - thinking: processing / loading
 * - speaking: lip-sync active
 * - wave:     greeting gesture
 */
export type MascotState = "idle" | "thinking" | "speaking" | "wave";

/**
 * Options passed to SpriteAnimator on construction.
 */
export interface SpriteAnimatorOptions {
  /** Target canvas element to render into. */
  canvas: HTMLCanvasElement;
  /** Canvas width in pixels. Default 255. */
  width?: number;
  /** Canvas height in pixels. Default 255. */
  height?: number;
  /** URL path prefix for layer PNGs (e.g. "/static/mascot/layers"). */
  layerBasePath: string;
}

/**
 * Per-layer configuration for the sprite animator.
 */
export interface LayerConfig {
  name: string;
  zIndex: number;
  anchor?: { x: number; y: number };
  /** Per-layer Y oscillation override. */
  idleFloat?: { amplitude: number; period: number; phase: number };
  /** Per-layer rotation oscillation override. */
  idleSway?: { angle: number; period: number; phase: number };
}

/**
 * Live2D-compatible parameter values computed from mouse position.
 * All values are in the range [-1, 1] unless documented otherwise.
 */
export interface ParamValues {
  /** Horizontal eye-tracking angle. Range: [-1, 1]. */
  eyeX: number;
  /** Vertical eye-tracking angle. Range: [-1, 1]. */
  eyeY: number;
  /** Head rotation X (yaw). Range: [-30, 30]. */
  headX: number;
  /** Head rotation Y (pitch). Range: [-30, 30]. */
  headY: number;
  /** Body sway X. Range: [-10, 10]. */
  bodyX: number;
}
