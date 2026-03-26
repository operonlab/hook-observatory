import type { ParamValues } from "./types.js";

/**
 * MouseTracker converts raw screen coordinates into Live2D parameter values.
 *
 * Gain rationale:
 *   - Eye   ×1  — subtle, mirrors actual eye movement range
 *   - Body  ×10 — gentle sway, physical inertia feel
 *   - Head  ×30 — full head-turn range used for engagement
 *
 * Coordinates are normalised to [-1, 1] relative to the canvas centre
 * before gains are applied.
 */
export class MouseTracker {
  private static readonly EYE_GAIN = 1;
  private static readonly BODY_GAIN = 10;
  private static readonly HEAD_GAIN = 30;

  /**
   * Compute Live2D param values from a mouse event position.
   *
   * @param mouseX    - Mouse X position in viewport pixels.
   * @param mouseY    - Mouse Y position in viewport pixels.
   * @param canvasRect - Bounding rect of the canvas (from getBoundingClientRect).
   * @returns         Param values ready to be applied to the Live2D model.
   */
  update(mouseX: number, mouseY: number, canvasRect: DOMRect): ParamValues {
    // Normalise to [-1, 1] relative to canvas centre.
    const normX = this.normalise(
      mouseX,
      canvasRect.left,
      canvasRect.left + canvasRect.width
    );
    const normY = this.normalise(
      mouseY,
      canvasRect.top,
      canvasRect.top + canvasRect.height
    );

    return {
      eyeX: this.clamp(normX * MouseTracker.EYE_GAIN),
      eyeY: this.clamp(normY * MouseTracker.EYE_GAIN),
      headX: this.clamp(normX * MouseTracker.HEAD_GAIN, -30, 30),
      headY: this.clamp(normY * MouseTracker.HEAD_GAIN, -30, 30),
      bodyX: this.clamp(normX * MouseTracker.BODY_GAIN, -10, 10),
    };
  }

  /** Map a value within [min, max] to the [-1, 1] range. */
  private normalise(value: number, min: number, max: number): number {
    const range = max - min;
    if (range === 0) return 0;
    return ((value - min) / range) * 2 - 1;
  }

  /** Clamp a value to [lo, hi]. Defaults to [-1, 1]. */
  private clamp(value: number, lo = -1, hi = 1): number {
    return Math.max(lo, Math.min(hi, value));
  }
}
