/**
 * CubismRenderer — renders a Live2D Cubism model (.moc3) using
 * untitled-pixi-live2d-engine on PixiJS 8.
 *
 * Exposes the same interaction API as SpriteAnimator so ai-assistant
 * can swap between sprite-based and Cubism-based rendering.
 */

import { Application, Container } from "pixi.js";
import { Live2DModel } from "untitled-pixi-live2d-engine/cubism";

import type { MascotState } from "./types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CubismRendererOptions {
  canvas: HTMLCanvasElement;
  width?: number;
  height?: number;
  /** URL to model3.json */
  modelPath: string;
  /** URL to live2dcubismcore.min.js (default: /static/models/live2dcubismcore.min.js) */
  cubismCorePath?: string;
}

// Map MascotState → Cubism motion group name
const STATE_MOTION: Record<MascotState, { group: string; index: number }> = {
  idle: { group: "idle", index: 0 },
  thinking: { group: "thinking", index: 0 },
  speaking: { group: "speaking", index: 0 },
  wave: { group: "wave", index: 0 },
};

const STATE_EXPRESSION: Record<MascotState, string | null> = {
  idle: null,
  thinking: "thinking",
  speaking: "speaking",
  wave: "happy",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Dynamically load Cubism Core if not already present on window */
async function ensureCubismCore(src: string): Promise<void> {
  if ((globalThis as any).Live2DCubismCore) return;

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load Cubism Core from ${src}`));
    document.head.appendChild(script);
  });
}

// ---------------------------------------------------------------------------
// CubismRenderer
// ---------------------------------------------------------------------------

export class CubismRenderer {
  private app!: Application;
  private model!: Live2DModel;
  private container!: Container;
  private opts: Required<CubismRendererOptions>;
  private currentState: MascotState = "idle";
  private lipSyncValue = 0;
  private destroyed = false;

  constructor(opts: CubismRendererOptions) {
    this.opts = {
      width: 510,
      height: 510,
      cubismCorePath: "/static/models/live2dcubismcore.min.js",
      ...opts,
    };
  }

  // -----------------------------------------------------------------------
  // Lifecycle
  // -----------------------------------------------------------------------

  async init(): Promise<void> {
    // 1. Ensure Cubism Core is loaded (required by the engine)
    await ensureCubismCore(this.opts.cubismCorePath);

    // 2. Init PixiJS 8
    this.app = new Application();
    await this.app.init({
      canvas: this.opts.canvas,
      width: this.opts.width,
      height: this.opts.height,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: window.devicePixelRatio || 1,
    });

    this.container = new Container();
    this.app.stage.addChild(this.container);

    // 3. Load the Live2D model
    this.model = await Live2DModel.from(this.opts.modelPath, {
      autoHitTest: false,
      autoFocus: false,
    });

    // 4. Scale model to fit canvas (use anchor for centering)
    const scaleX = this.opts.width / this.model.width;
    const scaleY = this.opts.height / this.model.height;
    const scale = Math.min(scaleX, scaleY) * 0.45;
    this.model.anchor.set(0.5, 0.5);
    this.model.scale.set(scale);
    this.model.x = this.opts.width / 2;
    this.model.y = this.opts.height / 2;

    this.container.addChild(this.model);

    // 5. Hook lip sync into the engine's update cycle (before model.update())
    this.model.internalModel.on("beforeModelUpdate", () => {
      if (this.destroyed || this.lipSyncValue <= 0) return;
      this.applyLipSync();
    });
  }

  destroy(): void {
    this.destroyed = true;
    try {
      // Remove model from stage FIRST (prevents double-free when app.destroy cleans children)
      if (this.model && this.container) {
        this.container.removeChild(this.model);
      }
      this.model?.destroy();
    } catch { /* Cubism assertion on double-free — safe to ignore */ }
    try {
      this.app?.destroy(true);
    } catch { /* PixiJS may throw if not fully initialized */ }
    this.model = null as any;
    this.app = null as any;
  }

  // -----------------------------------------------------------------------
  // Public API (matches SpriteAnimator interface)
  // -----------------------------------------------------------------------

  setState(state: MascotState): void {
    if (state === this.currentState) return;
    this.currentState = state;

    const motionDef = STATE_MOTION[state];
    const expressionName = STATE_EXPRESSION[state];

    try {
      this.model?.motion(motionDef.group, motionDef.index);
    } catch {
      // Motion group may not exist in this model
    }

    if (expressionName) {
      try {
        this.model?.expression(expressionName);
      } catch {
        // Expression may not exist
      }
    }
  }

  /**
   * Update model focus (eye/head tracking).
   * Accepts raw clientX/clientY — converts to [-1,1] relative to canvas.
   */
  setMousePosition(clientX: number, clientY: number): void {
    if (!this.model?.internalModel) return;
    const rect = this.opts.canvas.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * 2 - 1;
    const y = ((clientY - rect.top) / rect.height) * 2 - 1;
    this.model.internalModel.focusController.focus(
      Math.max(-1, Math.min(1, x)),
      Math.max(-1, Math.min(1, -y)), // invert Y for Live2D convention
    );
  }

  /** Set lip sync amplitude (0–1). */
  setLipSync(amplitude: number): void {
    this.lipSyncValue = Math.max(0, Math.min(1, amplitude));
  }

  // -----------------------------------------------------------------------
  // Internal
  // -----------------------------------------------------------------------

  /** Write lip sync value directly to the native Cubism parameter buffer.
   *  Bypasses CubismIdHandle (which requires CubismId objects, not strings)
   *  by indexing into the raw Float32Array via string ID lookup. */
  private applyLipSync(): void {
    try {
      const cm = this.model.internalModel.coreModel as any;
      const nativeModel = cm.getModel(); // Live2DCubismCore.Model
      const idx = nativeModel.parameters.ids.indexOf("ParamMouthOpenY");
      if (idx >= 0) {
        nativeModel.parameters.values[idx] = this.lipSyncValue;
      }
    } catch { /* safe to ignore */ }
  }
}
