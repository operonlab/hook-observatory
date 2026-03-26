/**
 * Mascot animation states driven by AI assistant events.
 * - idle:     default breathing loop
 * - thinking: processing / loading
 * - speaking: lip-sync active
 * - wave:     greeting gesture
 */
export type MascotState = "idle" | "thinking" | "speaking" | "wave";

/** Options passed to Live2DRenderer on construction. */
export interface Live2DRendererOptions {
  /** Target canvas element to render into. */
  canvas: HTMLCanvasElement;
  /** URL or local path to the .model3.json file. */
  modelPath: string;
  /** Canvas width in pixels. Defaults to canvas.width or 300. */
  width?: number;
  /** Canvas height in pixels. Defaults to canvas.height or 400. */
  height?: number;
  /** Enable transparent background. Defaults to true. */
  transparent?: boolean;
}

/**
 * Live2D parameter values computed from mouse position.
 * All values are in the range [-1, 1] unless documented otherwise.
 */
export interface ParamValues {
  /** Horizontal eye-tracking angle. Range: [-1, 1]. */
  eyeX: number;
  /** Vertical eye-tracking angle. Range: [-1, 1]. */
  eyeY: number;
  /** Head rotation X (yaw). Range: [-30, 30] (Live2D units). */
  headX: number;
  /** Head rotation Y (pitch). Range: [-30, 30] (Live2D units). */
  headY: number;
  /** Body sway X. Range: [-10, 10] (Live2D units). */
  bodyX: number;
}
