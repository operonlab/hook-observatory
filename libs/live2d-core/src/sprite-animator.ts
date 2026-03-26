import {
  Application,
  Assets,
  BlurFilter,
  Container,
  Graphics,
  Sprite,
} from "pixi.js";

import type { MascotState, SpriteAnimatorOptions } from "./types.js";
import { MotionManager } from "./motion-manager.js";
import { MouseTracker } from "./mouse-tracker.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Source dimensions of every layer PNG. */
const SRC_W = 625;
const SRC_H = 667;

/** Default display size. */
const DEFAULT_SIZE = 255;

/** Blink timing (milliseconds). */
const BLINK_INTERVAL_MIN = 3000;
const BLINK_INTERVAL_MAX = 5000;
const BLINK_DURATION     = 150;

/** Maximum number of pooled star particles. */
const MAX_PARTICLES = 20;

// ---------------------------------------------------------------------------
// Layer name ordering (bottom → top)
// ---------------------------------------------------------------------------

const LAYER_NAMES = [
  "book",
  "legs",
  "dress",
  "sleeves",
  "face",
  "left_eye",
  "right_eye",
  "silver_hair",
  "star_clip",
  "left_wing",
  "right_wing",
] as const;

type LayerName = (typeof LAYER_NAMES)[number];

// ---------------------------------------------------------------------------
// Particle helper type
// ---------------------------------------------------------------------------

interface Particle {
  gfx: Graphics;
  x: number;
  y: number;
  vy: number;        // upward speed px/s
  vx: number;        // horizontal drift
  life: number;      // 0-1, decreases over time
  maxLife: number;   // seconds until fully faded
  active: boolean;
}

// ---------------------------------------------------------------------------
// SpriteAnimator
// ---------------------------------------------------------------------------

/**
 * SpriteAnimator renders the mascot as 11 stacked RGBA PNG layers using
 * PixiJS v8. All animation is driven by a single ticker callback.
 *
 * Usage:
 *   const animator = new SpriteAnimator({ canvas, layerBasePath: '/static/mascot/layers' });
 *   await animator.init();
 *   animator.setState('thinking');
 */
export class SpriteAnimator {
  private readonly opts: Required<SpriteAnimatorOptions>;
  private readonly motionManager = new MotionManager();
  private readonly mouseTracker  = new MouseTracker();

  private app: Application | null = null;
  private ready = false;

  /** Root container that holds all layer sprites. */
  private root!: Container;
  /** Individual layer sprites, keyed by name. */
  private layers: Map<LayerName, Sprite> = new Map();

  /** Glow overlay: blurred duplicate of face behind the face sprite. */
  private glowSprite: Sprite | null = null;

  // Mouse-tracking offsets applied to root each tick.
  private mouseOffsetX = 0;
  private mouseOffsetY = 0;
  private lipSyncAmplitude = 0;

  // Blink state.
  private blinkTimer   = 0;
  private blinkTarget  = this.nextBlinkTarget();
  private blinking     = false;
  private blinkElapsed = 0;

  // Wave one-shot entrance tween.
  private waveTweenActive   = false;
  private waveTweenElapsed  = 0;
  private readonly WAVE_TWEEN_DURATION = 800; // ms

  // Particle pool.
  private particles: Particle[] = [];
  private particleAccum = 0; // fractional particle accumulator

  // Hair base X (reset to 0 each tick before oscillation is added).
  private hairBaseX = 0;

  constructor(options: SpriteAnimatorOptions) {
    this.opts = {
      width:  DEFAULT_SIZE,
      height: DEFAULT_SIZE,
      ...options,
    };
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Initialise PixiJS, load all layer PNGs, and start the animation ticker.
   * Must be awaited before the first frame is visible.
   */
  async init(): Promise<void> {
    const { canvas, width, height } = this.opts;

    this.app = new Application();
    await this.app.init({
      canvas,
      width,
      height,
      backgroundAlpha: 0,
      preference: "webgl",
      antialias: true,
    });

    await this.loadLayers();
    this.buildSceneGraph();
    this.initParticlePool();

    // Kick off idle state.
    this.motionManager.setState("idle");
    this.ready = true;

    this.app.ticker.add((ticker) => this.onTick(ticker.deltaMS));
  }

  /**
   * Transition to a new mascot state.
   * Repeated calls with the same state are ignored.
   */
  setState(state: MascotState): void {
    const prev = this.motionManager.getState();
    this.motionManager.setState(state);
    if (state === "wave" && prev !== "wave") {
      this.waveTweenActive  = true;
      this.waveTweenElapsed = 0;
    }
  }

  /**
   * Update mouse-tracking offsets (safe to call at 60fps from mousemove).
   *
   * @param x - Mouse X in viewport pixels.
   * @param y - Mouse Y in viewport pixels.
   */
  setMousePosition(x: number, y: number): void {
    if (!this.ready) return;
    const rect   = this.opts.canvas.getBoundingClientRect();
    const params = this.mouseTracker.update(x, y, rect);
    // Map [-1,1] eye range to ±2px container shift.
    this.mouseOffsetX = params.eyeX * 2;
    this.mouseOffsetY = params.eyeY * 2;
  }

  /**
   * Drive lip-sync from normalised audio amplitude [0, 1].
   * Currently scales the mouth/face sprite slightly on the Y axis.
   */
  setLipSync(amplitude: number): void {
    this.lipSyncAmplitude = Math.max(0, Math.min(1, amplitude));
  }

  /**
   * Destroy the PixiJS application and release all GPU resources.
   * Call when the host component unmounts.
   */
  destroy(): void {
    this.ready = false;
    this.app?.destroy(false, { children: true });
    this.app = null;
  }

  // ---------------------------------------------------------------------------
  // Setup helpers
  // ---------------------------------------------------------------------------

  private async loadLayers(): Promise<void> {
    const base = this.opts.layerBasePath.replace(/\/$/, "");
    const urls: Record<string, string> = {};
    for (const name of LAYER_NAMES) {
      urls[name] = `${base}/${name}.png`;
    }
    // Load all assets in parallel.
    await Assets.load(Object.values(urls));

    for (const name of LAYER_NAMES) {
      const sprite = Sprite.from(urls[name]);
      this.layers.set(name, sprite);
    }
  }

  private buildSceneGraph(): void {
    if (!this.app) return;
    const { width, height } = this.opts;

    this.root = new Container();
    this.app.stage.addChild(this.root);

    // Scale all layers uniformly to fit the display size.
    const scale = Math.min(width / SRC_W, height / SRC_H);

    for (const name of LAYER_NAMES) {
      const sprite = this.layers.get(name)!;
      sprite.anchor.set(0.5, 0.5);
      sprite.scale.set(scale);
      // Position at center.
      sprite.x = 0;
      sprite.y = 0;
      this.root.addChild(sprite);
    }

    // Glow overlay: blurred duplicate of the face sprite (behind face layer).
    const faceTex = this.layers.get("face")!.texture;
    this.glowSprite = new Sprite(faceTex);
    this.glowSprite.anchor.set(0.5, 0.5);
    this.glowSprite.scale.set(scale);
    this.glowSprite.alpha = 0;
    const blur = new BlurFilter({ strength: 12 });
    this.glowSprite.filters = [blur];
    // Insert just below the face layer (face is at index 4 in LAYER_NAMES).
    const faceSprite = this.layers.get("face")!;
    const faceIdx = this.root.children.indexOf(faceSprite);
    this.root.addChildAt(this.glowSprite, Math.max(0, faceIdx));

    // Centre the root container in the canvas.
    this.root.x = width  / 2;
    this.root.y = height / 2;
  }

  private initParticlePool(): void {
    if (!this.app) return;
    const { width, height } = this.opts;

    for (let i = 0; i < MAX_PARTICLES; i++) {
      const gfx = new Graphics();
      gfx.alpha = 0;
      drawStar(gfx, 4, 3, 1.5);
      this.app.stage.addChild(gfx);

      this.particles.push({
        gfx,
        x: width / 2,
        y: height / 2,
        vx: 0,
        vy: 0,
        life: 0,
        maxLife: 1,
        active: false,
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Ticker
  // ---------------------------------------------------------------------------

  private onTick(deltaMs: number): void {
    if (!this.ready || !this.root) return;

    const t = performance.now() / 1000; // seconds

    // Advance motion manager crossfade.
    this.motionManager.tick(deltaMs);
    const p = this.motionManager.current;

    // --- Float ---
    const floatY = p.float.amplitude > 0
      ? Math.sin((t * 2 * Math.PI) / p.float.period) * p.float.amplitude
      : 0;

    // --- Breathe (uniform scale) ---
    const breatheScale = lerp(
      p.breathe.min,
      p.breathe.max,
      (Math.sin((t * 2 * Math.PI) / p.breathe.period) + 1) / 2,
    );

    // --- Sway (rotation) ---
    const swayRot = p.sway.period > 0.1
      ? Math.sin((t * 2 * Math.PI) / p.sway.period) * (p.sway.angle * DEG_TO_RAD)
      : p.sway.angle * DEG_TO_RAD;

    // --- Wave one-shot tween ---
    let waveTweenScale = 1;
    let waveTweenRot   = 0;
    if (this.waveTweenActive) {
      this.waveTweenElapsed += deltaMs;
      const tw = Math.min(1, this.waveTweenElapsed / this.WAVE_TWEEN_DURATION);
      waveTweenScale = waveScaleCurve(tw);
      waveTweenRot   = waveRotCurve(tw) * DEG_TO_RAD;
      if (tw >= 1) this.waveTweenActive = false;
    }

    // Apply to root container.
    this.root.y = -floatY + this.mouseOffsetY;
    this.root.x = this.mouseOffsetX;
    this.root.scale.set(breatheScale * waveTweenScale);
    this.root.rotation = swayRot + waveTweenRot;

    // --- Hair extra sway ---
    const hairSprite = this.layers.get("silver_hair");
    if (hairSprite && p.hairSway.amplitude > 0) {
      hairSprite.x = this.hairBaseX +
        Math.sin((t * 2 * Math.PI) / p.hairSway.period) * p.hairSway.amplitude;
    }

    const clipSprite = this.layers.get("star_clip");
    if (clipSprite && p.hairSway.amplitude > 0) {
      clipSprite.x = this.hairBaseX +
        Math.sin((t * 2 * Math.PI) / p.hairSway.period) * p.hairSway.amplitude * 0.6;
    }

    // --- Wings ---
    const lWing = this.layers.get("left_wing");
    const rWing = this.layers.get("right_wing");
    if (lWing && rWing) {
      const wingRot = p.wingFlap.amplitude > 0
        ? Math.sin((t * 2 * Math.PI) / p.wingFlap.period) *
          (p.wingFlap.amplitude * DEG_TO_RAD)
        : 0;
      lWing.rotation = -wingRot;
      rWing.rotation =  wingRot;
    }

    // --- Lip sync: subtle face Y scale ---
    const faceSprite = this.layers.get("face");
    if (faceSprite) {
      faceSprite.scale.y = faceSprite.scale.x * (1 + this.lipSyncAmplitude * 0.04);
    }

    // --- Glow (thinking state) ---
    if (this.glowSprite) {
      const glowPulse = p.glowStrength > 0
        ? p.glowStrength * ((Math.sin(t * 2.5) + 1) / 2) * 0.8
        : 0;
      this.glowSprite.alpha = glowPulse;
    }

    // --- Blink ---
    this.tickBlink(deltaMs);

    // --- Particles ---
    this.tickParticles(deltaMs, p.particleRate);
  }

  // ---------------------------------------------------------------------------
  // Blink
  // ---------------------------------------------------------------------------

  private tickBlink(deltaMs: number): void {
    if (this.blinking) {
      this.blinkElapsed += deltaMs;
      if (this.blinkElapsed >= BLINK_DURATION) {
        // End blink: restore eye sprites.
        this.setEyeVisible(true);
        this.blinking     = false;
        this.blinkTimer   = 0;
        this.blinkTarget  = this.nextBlinkTarget();
      }
    } else {
      this.blinkTimer += deltaMs;
      if (this.blinkTimer >= this.blinkTarget) {
        // Start blink: hide eye sprites.
        this.setEyeVisible(false);
        this.blinking     = true;
        this.blinkElapsed = 0;
      }
    }
  }

  private setEyeVisible(visible: boolean): void {
    this.layers.get("left_eye")!.visible  = visible;
    this.layers.get("right_eye")!.visible = visible;
  }

  private nextBlinkTarget(): number {
    return BLINK_INTERVAL_MIN +
      Math.random() * (BLINK_INTERVAL_MAX - BLINK_INTERVAL_MIN);
  }

  // ---------------------------------------------------------------------------
  // Particles
  // ---------------------------------------------------------------------------

  private tickParticles(deltaMs: number, rate: number): void {
    const dt = deltaMs / 1000;
    const { width, height } = this.opts;

    // Spawn new particles.
    this.particleAccum += rate * dt;
    while (this.particleAccum >= 1) {
      this.particleAccum -= 1;
      this.spawnParticle(width, height);
    }

    // Update active particles.
    for (const p of this.particles) {
      if (!p.active) continue;

      p.life -= dt / p.maxLife;
      if (p.life <= 0) {
        p.active    = false;
        p.gfx.alpha = 0;
        continue;
      }

      p.x += p.vx * dt;
      p.y += p.vy * dt;

      p.gfx.x     = p.x;
      p.gfx.y     = p.y;
      p.gfx.alpha = Math.min(1, p.life * 2); // fade out in last 50% of life
    }
  }

  private spawnParticle(canvasW: number, canvasH: number): void {
    const p = this.particles.find((p) => !p.active);
    if (!p) return;

    // Spawn near center-top of the mascot.
    p.x      = canvasW / 2 + (Math.random() - 0.5) * 60;
    p.y      = canvasH * 0.35 + (Math.random() - 0.5) * 30;
    p.vx     = (Math.random() - 0.5) * 25;
    p.vy     = -(20 + Math.random() * 30);
    p.maxLife = 1.2 + Math.random() * 0.8;
    p.life   = 1;
    p.active = true;

    p.gfx.x     = p.x;
    p.gfx.y     = p.y;
    p.gfx.alpha = 1;
    p.gfx.tint  = STAR_TINTS[Math.floor(Math.random() * STAR_TINTS.length)];
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

const DEG_TO_RAD = Math.PI / 180;

const STAR_TINTS = [0xffd700, 0xffffff, 0xadd8e6, 0xffb6c1];

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Scale curve for the wave entrance tween: 0.8 → 1.1 → 1.0 */
function waveScaleCurve(t: number): number {
  if (t < 0.5) return lerp(0.8, 1.1, t / 0.5);
  return lerp(1.1, 1.0, (t - 0.5) / 0.5);
}

/** Rotation curve for the wave entrance tween: swing ±8° */
function waveRotCurve(t: number): number {
  return Math.sin(t * Math.PI * 2) * 8 * (1 - t);
}

/**
 * Draw a simple N-pointed star centered at origin onto a Graphics object.
 * @param gfx     - Target Graphics instance (will be cleared first).
 * @param points  - Number of points.
 * @param outer   - Outer radius in pixels.
 * @param inner   - Inner radius in pixels.
 */
function drawStar(
  gfx: Graphics,
  points: number,
  outer: number,
  inner: number,
): void {
  gfx.clear();
  gfx.beginFill(0xffffff);
  const step = Math.PI / points;
  let first = true;
  for (let i = 0; i < points * 2; i++) {
    const r   = i % 2 === 0 ? outer : inner;
    const ang = i * step - Math.PI / 2;
    const x   = Math.cos(ang) * r;
    const y   = Math.sin(ang) * r;
    if (first) {
      gfx.moveTo(x, y);
      first = false;
    } else {
      gfx.lineTo(x, y);
    }
  }
  gfx.closePath();
  gfx.endFill();
}
