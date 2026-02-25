// Sound notification engine — Web Audio API synthesis + ambient soundscape (C4)

class SoundEngine {
  private ctx: AudioContext | null = null;
  private _muted = false;
  private _volume = 0.3;

  // Ambient soundscape state
  private ambientNode: AudioBufferSourceNode | null = null;
  private ambientGain: GainNode | null = null;
  private _ambientRunning = false;
  private keyClickTimer: ReturnType<typeof setInterval> | null = null;

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
  set muted(v: boolean) {
    this._muted = v;
    if (v) this.stopAmbient();
  }

  get volume() { return this._volume; }
  set volume(v: number) {
    this._volume = Math.max(0, Math.min(1, v));
    if (this.ambientGain) {
      this.ambientGain.gain.setValueAtTime(this._volume * 0.03, this.ctx?.currentTime ?? 0);
    }
  }

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

  // ── Ambient Soundscape (C4) ──────────────────────

  /** Subtle keyboard click — random pitch variation */
  playKeyClick() {
    const ctx = this.getCtx();
    if (!ctx) return;
    const now = ctx.currentTime;
    // Random frequency between 2000-6000 Hz for click variation
    const freq = 2000 + Math.random() * 4000;
    const vol = this._volume * (0.015 + Math.random() * 0.015); // very quiet
    this.playTone(ctx, freq, now, 0.02 + Math.random() * 0.015, 'square', vol);
  }

  /** Start ambient office hum (filtered white noise loop) */
  startAmbient() {
    if (this._ambientRunning || this._muted) return;
    const ctx = this.getCtx();
    if (!ctx) return;

    // Create white noise buffer (2 seconds, looped)
    const sampleRate = ctx.sampleRate;
    const bufferLen = sampleRate * 2;
    const buffer = ctx.createBuffer(1, bufferLen, sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferLen; i++) {
      data[i] = (Math.random() * 2 - 1) * 0.5;
    }

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;

    // Low-pass filter to make it a gentle hum, not harsh white noise
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(200, ctx.currentTime); // very low cutoff = muffled hum
    filter.Q.setValueAtTime(1, ctx.currentTime);

    // Gain control (very quiet)
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(this._volume * 0.03, ctx.currentTime);

    source.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    source.start();

    this.ambientNode = source;
    this.ambientGain = gain;
    this._ambientRunning = true;
  }

  /** Stop ambient office hum */
  stopAmbient() {
    if (this.ambientNode) {
      try { this.ambientNode.stop(); } catch { /* already stopped */ }
      this.ambientNode = null;
    }
    this.ambientGain = null;
    this._ambientRunning = false;
    if (this.keyClickTimer) {
      clearInterval(this.keyClickTimer);
      this.keyClickTimer = null;
    }
  }

  /** Start periodic keyboard clicks based on typing agent count */
  startKeyClicks(getTypingCount: () => number) {
    if (this.keyClickTimer) return;
    this.keyClickTimer = setInterval(() => {
      if (this._muted) return;
      const count = getTypingCount();
      if (count <= 0) return;
      // More typing agents = more frequent clicks
      // Base: ~40% chance per tick per agent, capped at high frequency
      const probability = Math.min(0.8, count * 0.15);
      if (Math.random() < probability) {
        this.playKeyClick();
      }
    }, 200); // check every 200ms
  }

  get ambientRunning() { return this._ambientRunning; }

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
