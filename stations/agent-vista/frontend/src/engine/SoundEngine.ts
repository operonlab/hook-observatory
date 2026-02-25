// Sound notification engine — Web Audio API synthesis

class SoundEngine {
  private ctx: AudioContext | null = null;
  private _muted = false;
  private _volume = 0.3;

  /** Lazy-init AudioContext (must be called after user interaction) */
  private getCtx(): AudioContext | null {
    if (this._muted) return null;
    if (!this.ctx) {
      try {
        this.ctx = new AudioContext();
      } catch {
        return null;
      }
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
    return this.ctx;
  }

  get muted() { return this._muted; }
  set muted(v: boolean) { this._muted = v; }

  get volume() { return this._volume; }
  set volume(v: number) { this._volume = Math.max(0, Math.min(1, v)); }

  /** Permission needed — two-tone ascending alert (C5 -> E5) */
  playAlert() {
    const ctx = this.getCtx();
    if (!ctx) return;
    const now = ctx.currentTime;

    // First tone
    this.playTone(ctx, 523.25, now, 0.15, 'sine', this._volume * 0.6);
    // Second tone (higher)
    this.playTone(ctx, 659.25, now + 0.15, 0.2, 'sine', this._volume * 0.8);
    // Repeat after a short pause
    this.playTone(ctx, 523.25, now + 0.5, 0.15, 'sine', this._volume * 0.4);
    this.playTone(ctx, 659.25, now + 0.65, 0.2, 'sine', this._volume * 0.6);
  }

  /** Session start — soft welcome ping (G4) */
  playPing() {
    const ctx = this.getCtx();
    if (!ctx) return;
    this.playTone(ctx, 392, ctx.currentTime, 0.25, 'sine', this._volume * 0.4);
  }

  /** Session end — descending farewell (E4 -> C4) */
  playFarewell() {
    const ctx = this.getCtx();
    if (!ctx) return;
    const now = ctx.currentTime;
    this.playTone(ctx, 329.63, now, 0.2, 'sine', this._volume * 0.4);
    this.playTone(ctx, 261.63, now + 0.2, 0.3, 'sine', this._volume * 0.3);
  }

  /** Error — low buzz (A3) */
  playError() {
    const ctx = this.getCtx();
    if (!ctx) return;
    this.playTone(ctx, 220, ctx.currentTime, 0.2, 'sawtooth', this._volume * 0.3);
  }

  /** Sub-agent spawn — high sparkle (C6) */
  playSparkle() {
    const ctx = this.getCtx();
    if (!ctx) return;
    const now = ctx.currentTime;
    this.playTone(ctx, 1046.5, now, 0.08, 'sine', this._volume * 0.25);
    this.playTone(ctx, 1318.5, now + 0.08, 0.1, 'sine', this._volume * 0.2);
  }

  private playTone(
    ctx: AudioContext,
    freq: number,
    startTime: number,
    duration: number,
    type: OscillatorType,
    vol: number,
  ) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.type = type;
    osc.frequency.setValueAtTime(freq, startTime);
    gain.gain.setValueAtTime(vol, startTime);
    gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

    osc.start(startTime);
    osc.stop(startTime + duration + 0.05);
  }
}

/** Global singleton */
export const soundEngine = new SoundEngine();
