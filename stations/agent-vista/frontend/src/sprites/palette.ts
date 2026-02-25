// CLI color palettes and hue-shift utilities

export interface ColorPalette {
  skin: string;
  hair: string;
  primary: string;    // clothes main color
  secondary: string;  // clothes accent
  outline: string;
  badge: string;
  eyes: string;
  shoes: string;
}

// Base CLI palettes
export const CLI_PALETTES: Record<string, ColorPalette> = {
  claude: {
    skin: '#FFD4A0',
    hair: '#5C3A1E',
    primary: '#4A90D9',
    secondary: '#3670B0',
    outline: '#2A2A3A',
    badge: '#4A90D9',
    eyes: '#2A2A3A',
    shoes: '#3A3A4A',
  },
  codex: {
    skin: '#FFD4A0',
    hair: '#2E4A1E',
    primary: '#4CAF50',
    secondary: '#388E3C',
    outline: '#2A2A3A',
    badge: '#4CAF50',
    eyes: '#2A2A3A',
    shoes: '#3A3A4A',
  },
  gemini: {
    skin: '#FFD4A0',
    hair: '#3A1E4A',
    primary: '#9C27B0',
    secondary: '#7B1FA2',
    outline: '#2A2A3A',
    badge: '#9C27B0',
    eyes: '#2A2A3A',
    shoes: '#3A3A4A',
  },
};

// Hue-shift a hex color by degrees (-30 to +30)
export function hueShiftHex(hex: string, degrees: number): string {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;

  const [h, s, l] = rgbToHsl(r, g, b);
  const shifted = [(h + degrees / 360 + 1) % 1, s, l] as const;
  const [nr, ng, nb] = hslToRgb(shifted[0], shifted[1], shifted[2]);

  return (
    '#' +
    Math.round(nr * 255).toString(16).padStart(2, '0') +
    Math.round(ng * 255).toString(16).padStart(2, '0') +
    Math.round(nb * 255).toString(16).padStart(2, '0')
  );
}

// Create a shifted palette for a specific session index
export function shiftPalette(base: ColorPalette, sessionIndex: number): ColorPalette {
  if (sessionIndex === 0) return base;
  // Alternate ±30° shifts: index 1 → +30, index 2 → -30, index 3 → +20, etc.
  const shift = sessionIndex % 2 === 1 ? 30 : -30;
  const amount = shift * Math.ceil(sessionIndex / 2) / Math.ceil(sessionIndex / 2);
  return {
    ...base,
    primary: hueShiftHex(base.primary, amount),
    secondary: hueShiftHex(base.secondary, amount),
    badge: hueShiftHex(base.badge, amount),
    hair: hueShiftHex(base.hair, amount),
  };
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = 0;
  if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
  else if (max === g) h = ((b - r) / d + 2) / 6;
  else h = ((r - g) / d + 4) / 6;
  return [h, s, l];
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  if (s === 0) return [l, l, l];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return [hue2rgb(p, q, h + 1 / 3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1 / 3)];
}

function hue2rgb(p: number, q: number, t: number): number {
  let tt = t;
  if (tt < 0) tt += 1;
  if (tt > 1) tt -= 1;
  if (tt < 1 / 6) return p + (q - p) * 6 * tt;
  if (tt < 1 / 2) return q;
  if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
  return p;
}
