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
// Note: body_effects = remainder.png, wing_left/wing_right match actual filenames
// ---------------------------------------------------------------------------

const LAYER_NAMES = [
  "book",
  "legs",
  "dress",
  "body_effects",
  "face",
  "left_eye",
  "right_eye",
  "silver_hair",
  "star_clip",
  "wing_left",
  "wing_right",
] as const;

type LayerName = (typeof LAYER_NAMES)[number];

// ---------------------------------------------------------------------------
// Spring physics
// ---------------------------------------------------------------------------

class Spring {
  position = 0;
  velocity = 0;
  target   = 0;
  stiffness: number;
  damping: number;

  constructor(stiffness: number, damping: number) {
    this.stiffness = stiffness;
    this.damping   = damping;
  }

  update(dt: number): void {
    const force    = (this.target - this.position) * this.stiffness;
    this.velocity  = (this.velocity + force) * this.damping;
    this.position += this.velocity;
  }
}

// ---------------------------------------------------------------------------
// Particle helper type
// ---------------------------------------------------------------------------

interface Particle {
  gfx: Graphics;
  x: number;
  y: number;
  vy: number;       // upward speed px/s
  vx: number;       // horizontal drift
  life: number;     // 0-1, decreases over time
  maxLife: number;  // seconds until fully faded
  active: boolean;
}

// ---------------------------------------------------------------------------
// SpriteAnimator
// ---------------------------------------------------------------------------

/**
 * SpriteAnimator renders the mascot as 11 stacked RGBA PNG layers using
 * PixiJS v8. All animation is driven by a single ticker callback.
 *
 * Scene graph:
 *   app.stage
 *   ├── root Container (centered in canvas)
 *   │   ├── book Sprite (static)
 *   │   ├── bodyGroup Container (slight mouse follow)
 *   │   │   ├── wing_left Sprite (spring physics)
 *   │   │   ├── wing_right Sprite (spring physics)
 *   │   │   ├── legs Sprite
 *   │   │   ├── dress Sprite
 *   │   │   └── body_effects Sprite
 *   │   └── headGroup Container (strong mouse follow)
 *   │       ├── face Sprite
 *   │       ├── left_eye Sprite (eye tracking offset)
 *   │       ├── right_eye Sprite (eye tracking offset)
 *   │       ├── silver_hair Sprite (spring physics)
 *   │       └── star_clip Sprite (spring follows hair)
 *   └── particles (on stage directly)
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

  /** Root container that holds bodyGroup + headGroup + book. */
  private root!: Container;
  /** Group for body parts: wings, legs, dress, body_effects. */
  private bodyGroup!: Container;
  /** Group for head parts: face, eyes, hair, star_clip. */
  private headGroup!: Container;
  /** Individual layer sprites, keyed by name. */
  private layers: Map<LayerName, Sprite> = new Map();

  /** Glow overlay: blurred duplicate of face behind the face sprite. */
  private glowSprite: Sprite | null = null;

  // Smoothed mouse offsets in [-1, 1] range from MouseTracker.
  private rawMouseX = 0;
  private rawMouseY = 0;
  // Lerp targets for head and body groups.
  private headTargetX  = 0;
  private headTargetY  = 0;
  private bodyTargetX  = 0;
  private bodyTargetY  = 0;
  // Current smoothed positions for groups.
  private headCurrentX = 0;
  private headCurrentY = 0;
  private bodyCurrentX = 0;
  private bodyCurrentY = 0;

  // Eye tracking per-sprite offsets (relative to their base position).
  private eyeTargetX   = 0;
  private eyeTargetY   = 0;
  private eyeCurrentX  = 0;
  private eyeCurrentY  = 0;
  // Store base positions of eye sprites so we can apply offsets on top.
  private leftEyeBaseX  = 0;
  private leftEyeBaseY  = 0;
  private rightEyeBaseX = 0;
  private rightEyeBaseY = 0;

  private lipSyncAmplitude = 0;

  // Blink state.
  private blinkTimer    = 0;
  private blinkTarget   = this.nextBlinkTarget();
  private blinking      = false;
  private blinkElapsed  = 0;

  // Wave one-shot entrance tween.
  private waveTweenActive  = false;
  private waveTweenElapsed = 0;
  private readonly WAVE_TWEEN_DURATION = 800; // ms

  // Particle pool.
  private particles: Particle[] = [];
  private particleAccum = 0; // fractional particle accumulator

  // Spring physics instances.
  // Hair springs: X offset (horizontal sway) and rotation.
  private hairSpringX   = new Spring(0.15, 0.7);
  private hairSpringRot = new Spring(0.15, 0.7);
  // Star clip springs (stiffer, follows hair).
  private starSpringX   = new Spring(0.3, 0.8);
  private starSpringRot = new Spring(0.3, 0.8);
  // Wing springs: rotation for left and right (slow, floaty).
  private wingLeftSpring  = new Spring(0.08, 0.6);
  private wingRightSpring = new Spring(0.08, 0.6);

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
    // params.eyeX / eyeY are in [-1, 1].
    this.rawMouseX = params.eyeX;
    this.rawMouseY = params.eyeY;
  }

  /**
   * Drive lip-sync from normalised audio amplitude [0, 1].
   * Slightly adjusts face sprite Y position (±1px) for a subtle talking motion.
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

    // Scale all layers uniformly to fit the display size.
    const scale = Math.min(width / SRC_W, height / SRC_H);

    // Helper to configure a sprite at center with uniform scale.
    const setupSprite = (sprite: Sprite): void => {
      sprite.anchor.set(0.5, 0.5);
      sprite.scale.set(scale);
      sprite.x = 0;
      sprite.y = 0;
    };

    this.root = new Container();

    // --- book (static, no group) ---
    const bookSprite = this.layers.get("book")!;
    setupSprite(bookSprite);
    this.root.addChild(bookSprite);

    // --- bodyGroup ---
    this.bodyGroup = new Container();
    // Layers in body group (bottom → top within group): wing_left, wing_right, legs, dress, body_effects.
    for (const name of ["wing_left", "wing_right", "legs", "dress", "body_effects"] as LayerName[]) {
      const sprite = this.layers.get(name)!;
      setupSprite(sprite);
      this.bodyGroup.addChild(sprite);
    }
    this.root.addChild(this.bodyGroup);

    // --- headGroup ---
    this.headGroup = new Container();
    // Layers in head group (bottom → top within group): face, left_eye, right_eye, silver_hair, star_clip.
    for (const name of ["face", "left_eye", "right_eye", "silver_hair", "star_clip"] as LayerName[]) {
      const sprite = this.layers.get(name)!;
      setupSprite(sprite);
      this.headGroup.addChild(sprite);
    }
    this.root.addChild(this.headGroup);

    // Store eye base positions (currently 0,0 relative to headGroup since all sprites centered).
    this.leftEyeBaseX  = 0;
    this.leftEyeBaseY  = 0;
    this.rightEyeBaseX = 0;
    this.rightEyeBaseY = 0;

    // Glow overlay: blurred duplicate of the face sprite (inserted just below the face layer in headGroup).
    const faceTex = this.layers.get("face")!.texture;
    this.glowSprite = new Sprite(faceTex);
    this.glowSprite.anchor.set(0.5, 0.5);
    this.glowSprite.scale.set(scale);
    this.glowSprite.alpha = 0;
    const blur = new BlurFilter({ strength: 12 });
    this.glowSprite.filters = [blur];
    // Insert at index 0 in headGroup (below face).
    this.headGroup.addChildAt(this.glowSprite, 0);

    // Centre the root container in the canvas.
    this.root.x = width  / 2;
    this.root.y = height / 2;

    this.app.stage.addChild(this.root);
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

    const dt = deltaMs / 1000; // seconds
    const t  = performance.now() / 1000; // seconds

    // Advance motion manager crossfade.
    this.motionManager.tick(deltaMs);
    const p = this.motionManager.current;

    // --- Float (applied to root Y) ---
    const floatY = p.float.amplitude > 0
      ? Math.sin((t * 2 * Math.PI) / p.float.period) * p.float.amplitude
      : 0;

    // --- Breathe (uniform scale on root) ---
    const breatheScale = lerp(
      p.breathe.min,
      p.breathe.max,
      (Math.sin((t * 2 * Math.PI) / p.breathe.period) + 1) / 2,
    );

    // --- Sway (rotation on root) ---
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

    // Apply float + wave to root container.
    this.root.y = this.opts.height / 2 - floatY;
    this.root.x = this.opts.width  / 2;
    this.root.scale.set(breatheScale * waveTweenScale);
    this.root.rotation = swayRot + waveTweenRot;

    // --- Mouse tracking targets ---
    // rawMouseX/Y are in [-1, 1].
    const headGainX = 8;
    const headGainY = 5;
    const bodyGainX = 2;
    const bodyGainY = 1;

    this.headTargetX = this.rawMouseX * headGainX;
    this.headTargetY = this.rawMouseY * headGainY;
    this.bodyTargetX = this.rawMouseX * bodyGainX;
    this.bodyTargetY = this.rawMouseY * bodyGainY;

    // Lerp head and body group positions (smooth interpolation at 0.08/frame).
    const LERP_RATE = 0.08;
    this.headCurrentX = lerp(this.headCurrentX, this.headTargetX, LERP_RATE);
    this.headCurrentY = lerp(this.headCurrentY, this.headTargetY, LERP_RATE);
    this.bodyCurrentX = lerp(this.bodyCurrentX, this.bodyTargetX, LERP_RATE);
    this.bodyCurrentY = lerp(this.bodyCurrentY, this.bodyTargetY, LERP_RATE);

    this.headGroup.x        = this.headCurrentX;
    this.headGroup.y        = this.headCurrentY;
    this.headGroup.rotation = (this.headCurrentX / headGainX) * 3 * DEG_TO_RAD;

    this.bodyGroup.x = this.bodyCurrentX;
    this.bodyGroup.y = this.bodyCurrentY;

    // --- Eye tracking (relative to their base, ±3px X, ±2px Y) ---
    const eyeGainX = 3;
    const eyeGainY = 2;
    this.eyeTargetX  = this.rawMouseX * eyeGainX;
    this.eyeTargetY  = this.rawMouseY * eyeGainY;
    this.eyeCurrentX = lerp(this.eyeCurrentX, this.eyeTargetX, 0.1);
    this.eyeCurrentY = lerp(this.eyeCurrentY, this.eyeTargetY, 0.1);

    const leftEye  = this.layers.get("left_eye");
    const rightEye = this.layers.get("right_eye");
    if (leftEye) {
      leftEye.x  = this.leftEyeBaseX  + this.eyeCurrentX;
      leftEye.y  = this.leftEyeBaseY  + this.eyeCurrentY;
    }
    if (rightEye) {
      rightEye.x = this.rightEyeBaseX + this.eyeCurrentX;
      rightEye.y = this.rightEyeBaseY + this.eyeCurrentY;
    }

    // --- Hair spring physics ---
    // Spring target driven by head group displacement + motion manager hair sway.
    const hairSwayBase = p.hairSway.amplitude > 0
      ? Math.sin((t * 2 * Math.PI) / p.hairSway.period) * p.hairSway.amplitude
      : 0;
    this.hairSpringX.target   = this.headCurrentX * 0.3 + hairSwayBase;
    this.hairSpringRot.target = this.headCurrentX * 0.02; // subtle tilt follows head

    this.hairSpringX.update(dt);
    this.hairSpringRot.update(dt);

    const hairSprite = this.layers.get("silver_hair");
    if (hairSprite) {
      hairSprite.x        = this.hairSpringX.position;
      hairSprite.rotation = clamp(this.hairSpringRot.position, -5, 5) * DEG_TO_RAD;
    }

    // --- Star clip spring (stiffer, follows hair spring position) ---
    this.starSpringX.target   = this.hairSpringX.position * 0.8;
    this.starSpringRot.target = this.hairSpringRot.position * 0.8;

    this.starSpringX.update(dt);
    this.starSpringRot.update(dt);

    const clipSprite = this.layers.get("star_clip");
    if (clipSprite) {
      clipSprite.x        = this.starSpringX.position;
      clipSprite.rotation = clamp(this.starSpringRot.position, -5, 5) * DEG_TO_RAD;
    }

    // --- Wing spring physics ---
    // Wings driven by body group + idle sin-wave oscillation.
    const idleWingOscil = Math.sin((t * 2 * Math.PI) / 2.0) * 3; // 2s period, 3° amplitude

    const wingFlap = p.wingFlap.amplitude > 0
      ? Math.sin((t * 2 * Math.PI) / p.wingFlap.period) *
        (p.wingFlap.amplitude * DEG_TO_RAD)
      : 0;

    // Spring target: body displacement tilt + motion flap + idle oscillation.
    const wingBaseRot = wingFlap + idleWingOscil * DEG_TO_RAD;
    this.wingLeftSpring.target  = -wingBaseRot - this.bodyCurrentX * 0.005;
    this.wingRightSpring.target =  wingBaseRot + this.bodyCurrentX * 0.005;

    this.wingLeftSpring.update(dt);
    this.wingRightSpring.update(dt);

    const lWing = this.layers.get("wing_left");
    const rWing = this.layers.get("wing_right");
    if (lWing) {
      lWing.rotation = this.wingLeftSpring.position;
    }
    if (rWing) {
      rWing.rotation = this.wingRightSpring.position;
    }

    // --- Lip sync: subtle face Y position shift (±1px) ---
    const faceSprite = this.layers.get("face");
    if (faceSprite) {
      faceSprite.y = 0 + this.lipSyncAmplitude * 1;
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
      const progress = this.blinkElapsed / BLINK_DURATION; // 0 → 1
      if (progress >= 1) {
        // End blink: restore full scaleY.
        this.setEyeScaleY(1.0);
        this.blinking    = false;
        this.blinkTimer  = 0;
        this.blinkTarget = this.nextBlinkTarget();
      } else {
        // Ease in-out: 0 → 0.5 close (scaleY 1→0.1), 0.5 → 1 open (scaleY 0.1→1).
        let scaleY: number;
        if (progress < 0.5) {
          const t = progress / 0.5;
          scaleY = lerp(1.0, 0.1, easeInOut(t));
        } else {
          const t = (progress - 0.5) / 0.5;
          scaleY = lerp(0.1, 1.0, easeInOut(t));
        }
        this.setEyeScaleY(scaleY);
      }
    } else {
      this.blinkTimer += deltaMs;
      if (this.blinkTimer >= this.blinkTarget) {
        // Start blink.
        this.blinking     = true;
        this.blinkElapsed = 0;
      }
    }
  }

  private setEyeScaleY(scaleY: number): void {
    const leftEye  = this.layers.get("left_eye");
    const rightEye = this.layers.get("right_eye");
    if (leftEye)  leftEye.scale.y  = leftEye.scale.x  * scaleY;
    if (rightEye) rightEye.scale.y = rightEye.scale.x * scaleY;
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

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

/** Cubic ease in-out (0→1 input, 0→1 output). */
function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
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
