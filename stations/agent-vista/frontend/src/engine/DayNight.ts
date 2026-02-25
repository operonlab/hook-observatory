// Day/Night cycle — time-based ambient lighting overlay (C1)
// Phases: night → dawn → day → dusk → evening → night

export type DayPhase = 'night' | 'dawn' | 'day' | 'dusk' | 'evening';

export interface DayNightState {
  phase: DayPhase;
  /** RGBA overlay color string */
  overlayR: number;
  overlayG: number;
  overlayB: number;
  overlayA: number;
  /** 0-1 brightness multiplier (1 = full daylight) */
  ambientLight: number;
  /** 0-1 intensity for indoor lighting (desk lamps, window glow) */
  windowGlowIntensity: number;
}

/** Smooth cosine interpolation between 0 and 1 */
function smoothstep(t: number): number {
  const c = Math.max(0, Math.min(1, t));
  return c * c * (3 - 2 * c);
}

/** Get current day/night state based on system time */
export function getDayNightState(): DayNightState {
  const now = new Date();
  const t = now.getHours() + now.getMinutes() / 60; // fractional hour

  // Night: 23:00 - 05:00
  if (t >= 23 || t < 5) {
    return {
      phase: 'night',
      overlayR: 10, overlayG: 15, overlayB: 50,
      overlayA: 0.28,
      ambientLight: 0.5,
      windowGlowIntensity: 0.85,
    };
  }

  // Dawn: 05:00 - 07:30
  if (t >= 5 && t < 7.5) {
    const p = smoothstep((t - 5) / 2.5);
    return {
      phase: 'dawn',
      overlayR: lerp(10, 255, p * 0.8),
      overlayG: lerp(15, 200, p * 0.8),
      overlayB: lerp(50, 100, p * 0.5),
      overlayA: lerp(0.28, 0, p),
      ambientLight: lerp(0.5, 1, p),
      windowGlowIntensity: lerp(0.85, 0, p),
    };
  }

  // Day: 07:30 - 17:00
  if (t >= 7.5 && t < 17) {
    return {
      phase: 'day',
      overlayR: 0, overlayG: 0, overlayB: 0,
      overlayA: 0,
      ambientLight: 1,
      windowGlowIntensity: 0,
    };
  }

  // Dusk: 17:00 - 19:00
  if (t >= 17 && t < 19) {
    const p = smoothstep((t - 17) / 2);
    return {
      phase: 'dusk',
      overlayR: lerp(0, 255, p * 0.6),
      overlayG: lerp(0, 120, p * 0.4),
      overlayB: lerp(0, 60, p * 0.3),
      overlayA: lerp(0, 0.12, p),
      ambientLight: lerp(1, 0.72, p),
      windowGlowIntensity: lerp(0, 0.4, p),
    };
  }

  // Evening: 19:00 - 23:00
  const p = smoothstep((t - 19) / 4);
  return {
    phase: 'evening',
    overlayR: lerp(255 * 0.6, 10, p),
    overlayG: lerp(120 * 0.4, 15, p),
    overlayB: lerp(60 * 0.3, 50, p),
    overlayA: lerp(0.12, 0.28, p),
    ambientLight: lerp(0.72, 0.5, p),
    windowGlowIntensity: lerp(0.4, 0.85, p),
  };
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Phase display label (Chinese) */
export function phaseLabel(phase: DayPhase): string {
  switch (phase) {
    case 'night': return '深夜';
    case 'dawn': return '黎明';
    case 'day': return '白天';
    case 'dusk': return '黃昏';
    case 'evening': return '夜晚';
  }
}
