/**
 * CubismRenderer — renders a Live2D Cubism model (.moc3) using
 * untitled-pixi-live2d-engine on PixiJS 8.
 *
 * Exposes the same interaction API as SpriteAnimator so ai-assistant
 * can swap between sprite-based and Cubism-based rendering.
 */

import { Application, Container } from "pixi.js";
import { Live2DModel } from "untitled-pixi-live2d-engine";

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
      autoInteract: false,
    });

    // 4. Scale model to fit canvas
    const scaleX = this.opts.width / this.model.width;
    const scaleY = this.opts.height / this.model.height;
    const scale = Math.min(scaleX, scaleY) * 0.85;
    this.model.scale.set(scale);
    this.model.x = (this.opts.width - this.model.width * scale) / 2;
    this.model.y = (this.opts.height - this.model.height * scale) / 2;

    this.container.addChild(this.model);

    // 5. Per-frame lip sync update
    this.app.ticker.add(() => {
      if (this.destroyed) return;
      this.updateLipSync();
    });
  }

  destroy(): void {
    this.destroyed = true;
    this.model?.destroy();
    this.app?.destroy(true);
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

  private updateLipSync(): void {
    if (!this.model?.internalModel) return;
    const coreModel = this.model.internalModel.coreModel;
    if (!coreModel) return;

    // Cubism 4/5 uses setParameterValueById
    if ("setParameterValueById" in coreModel) {
      try {
        (coreModel as any).setParameterValueById("ParamMouthOpenY", this.lipSyncValue);
      } catch { /* parameter may not exist */ }
    }
    // Cubism 2 fallback uses setParamFloat
    else if ("setParamFloat" in coreModel) {
      try {
        (coreModel as any).setParamFloat("PARAM_MOUTH_OPEN_Y", this.lipSyncValue);
      } catch { /* parameter may not exist */ }
    }
  }
}
