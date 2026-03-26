import type { Live2DRendererOptions, MascotState } from "./types.js";
import { MouseTracker } from "./mouse-tracker.js";
import { MotionManager } from "./motion-manager.js";

/**
 * Live2DRenderer is the main entry point for the live2d-core library.
 *
 * Current status: SCAFFOLD — actual Live2D / Pixi calls are marked TODO.
 * The structure is ready to wire up once the .moc3 model file is available.
 *
 * Integration plan:
 *   1. Drop pixi-live2d-display into node_modules (pnpm install).
 *   2. Call `Live2DModel.from(modelPath)` inside init().
 *   3. Replace each TODO block with real SDK calls.
 *   4. Remove this comment block.
 */
export class Live2DRenderer {
  private readonly options: Required<Live2DRendererOptions>;
  private readonly mouseTracker: MouseTracker;
  private readonly motionManager: MotionManager;

  /**
   * Pixi application instance.
   * TODO: type as `import('pixi.js').Application` once SDK is wired.
   */
  private app: unknown = null;

  /**
   * Live2D model instance managed by pixi-live2d-display.
   * TODO: type as `import('pixi-live2d-display').Live2DModel` once SDK is wired.
   */
  private model: unknown = null;

  /** Whether the renderer has been fully initialised. */
  private ready = false;

  constructor(options: Live2DRendererOptions) {
    this.options = {
      width: options.canvas.width || 300,
      height: options.canvas.height || 400,
      transparent: true,
      ...options,
    };

    this.mouseTracker = new MouseTracker();
    this.motionManager = new MotionManager();

    // Wire motion requests from the state machine to the SDK loader.
    this.motionManager.onMotionRequest = (motionPath, state) => {
      this.loadMotion(motionPath, state);
    };

    // Kick off async init (fire-and-forget; callers can await isReady).
    void this.init();
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Update the model's look-at direction based on a mouse position.
   * Safe to call at 60 fps from a mousemove listener.
   *
   * @param x - Mouse X in viewport pixels.
   * @param y - Mouse Y in viewport pixels.
   */
  setMousePosition(x: number, y: number): void {
    if (!this.ready) return;

    const rect = this.options.canvas.getBoundingClientRect();
    const params = this.mouseTracker.update(x, y, rect);

    // TODO: apply params to Live2D model once SDK is wired.
    //   this.model.setParameterValueById('ParamEyeBallX', params.eyeX);
    //   this.model.setParameterValueById('ParamEyeBallY', params.eyeY);
    //   this.model.setParameterValueById('ParamAngleX',   params.headX);
    //   this.model.setParameterValueById('ParamAngleY',   params.headY);
    //   this.model.setParameterValueById('ParamBodyAngleX', params.bodyX);
    void params; // suppress unused-variable warning until TODO is resolved
  }

  /**
   * Transition to a new mascot state (idle, thinking, speaking, wave).
   * Repeated calls with the same state are no-ops.
   */
  setState(state: MascotState): void {
    this.motionManager.setState(state);
  }

  /**
   * Drive lip-sync from an audio amplitude value.
   *
   * @param amplitude - Normalised amplitude in [0, 1].
   *                    Pass 0 when not speaking to close the mouth.
   */
  setLipSync(amplitude: number): void {
    if (!this.ready) return;

    const clamped = Math.max(0, Math.min(1, amplitude));

    // TODO: apply lip-sync to Live2D model once SDK is wired.
    //   this.model.setParameterValueById('ParamMouthOpenY', clamped);
    void clamped; // suppress unused-variable warning until TODO is resolved
  }

  /**
   * Tear down the Pixi application and release all GPU resources.
   * Call this when the host component is unmounted.
   */
  destroy(): void {
    this.ready = false;

    // TODO: destroy Live2D model and Pixi app once SDK is wired.
    //   this.model?.destroy();
    //   (this.app as Application)?.destroy(false, { children: true });

    this.app = null;
    this.model = null;
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  /**
   * Initialise the Pixi application and load the Live2D model.
   * Runs once during construction.
   */
  private async init(): Promise<void> {
    const { canvas, width, height, transparent, modelPath } = this.options;

    // TODO: create Pixi Application once SDK is wired.
    //   const { Application } = await import('pixi.js');
    //   const { Live2DModel } = await import('pixi-live2d-display');
    //
    //   this.app = new Application({
    //     view: canvas,
    //     width,
    //     height,
    //     backgroundAlpha: transparent ? 0 : 1,
    //     autoStart: true,
    //   });
    //
    //   this.model = await Live2DModel.from(modelPath);
    //   (this.app as Application).stage.addChild(this.model as DisplayObject);

    // Suppress "unused variable" warnings until TODOs are filled in.
    void canvas;
    void width;
    void height;
    void transparent;
    void modelPath;

    // Mark as ready so public API calls are processed.
    // TODO: move this line below the real await above.
    this.ready = true;

    // Start idle motion by default.
    this.motionManager.setState("idle");
  }

  /**
   * Load and play a motion file on the Live2D model.
   * Called by MotionManager via the onMotionRequest callback.
   */
  private loadMotion(motionPath: string, _state: MascotState): void {
    if (!this.ready) return;

    // TODO: play motion on model once SDK is wired.
    //   (this.model as Live2DModel).motion(motionPath);

    void motionPath; // suppress unused-variable warning until TODO is resolved
  }
}
