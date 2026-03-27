// Public surface of @workshop/live2d-core
// Import from this entry point only — internal modules are subject to change.

export { SpriteAnimator } from "./sprite-animator.js";
// CubismRenderer is NOT exported from main entry to avoid pulling in the
// Cubism engine at bundle time (it checks for window.Live2DCubismCore on load).
// Import directly: import { CubismRenderer } from "@workshop/live2d-core/cubism"
export { MotionManager } from "./motion-manager.js";
export { MouseTracker } from "./mouse-tracker.js";
export type {
  MascotState,
  ParamValues,
  SpriteAnimatorOptions,
  LayerConfig,
} from "./types.js";
export type { CubismRendererOptions } from "./cubism-renderer.js";
