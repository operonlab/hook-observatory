/**
 * Separate entry point for CubismRenderer.
 *
 * Import via: import("@workshop/live2d-core/cubism-entry")
 *
 * This is NOT in the main index.ts because the engine checks for
 * window.Live2DCubismCore at module init time, which crashes if the
 * Cubism Core script hasn't loaded yet.
 */
export { CubismRenderer } from "./cubism-renderer.js";
export type { CubismRendererOptions } from "./cubism-renderer.js";
