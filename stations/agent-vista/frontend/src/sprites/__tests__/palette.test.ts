import { describe, it, expect } from 'vitest';
import { hueShiftHex, shiftPalette, CLI_PALETTES } from '../palette';

describe('hueShiftHex', () => {
  it('returns same color for 0 degree shift', () => {
    expect(hueShiftHex('#FF0000', 0)).toBe('#ff0000');
  });

  it('shifts red toward yellow at +60°', () => {
    const result = hueShiftHex('#FF0000', 60);
    // Should be yellowish
    const r = parseInt(result.slice(1, 3), 16);
    const g = parseInt(result.slice(3, 5), 16);
    expect(r).toBeGreaterThan(200);
    expect(g).toBeGreaterThan(200);
  });

  it('returns valid hex string', () => {
    const result = hueShiftHex('#4A90D9', 30);
    expect(result).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('wraps around at 360°', () => {
    const original = hueShiftHex('#4A90D9', 0);
    const wrapped = hueShiftHex('#4A90D9', 360);
    expect(wrapped).toBe(original);
  });

  it('handles grayscale (no saturation) without NaN', () => {
    const result = hueShiftHex('#808080', 30);
    expect(result).toMatch(/^#[0-9a-f]{6}$/);
    // Gray has no hue, should stay gray-ish
    expect(result).toBe('#808080');
  });
});

describe('shiftPalette', () => {
  it('returns base palette for index 0', () => {
    const base = CLI_PALETTES.claude;
    const result = shiftPalette(base, 0);
    expect(result).toBe(base);
  });

  it('shifts primary color for index > 0', () => {
    const base = CLI_PALETTES.claude;
    const shifted = shiftPalette(base, 1);
    expect(shifted.primary).not.toBe(base.primary);
    expect(shifted.skin).toBe(base.skin); // skin unchanged
  });

  it('returns valid hex colors', () => {
    const base = CLI_PALETTES.gemini;
    const shifted = shiftPalette(base, 2);
    expect(shifted.primary).toMatch(/^#[0-9a-f]{6}$/);
    expect(shifted.badge).toMatch(/^#[0-9a-f]{6}$/);
  });
});

describe('CLI_PALETTES', () => {
  it('has all three CLI types', () => {
    expect(CLI_PALETTES).toHaveProperty('claude');
    expect(CLI_PALETTES).toHaveProperty('codex');
    expect(CLI_PALETTES).toHaveProperty('gemini');
  });

  it('each palette has required color fields', () => {
    for (const pal of Object.values(CLI_PALETTES)) {
      expect(pal.skin).toBeDefined();
      expect(pal.primary).toBeDefined();
      expect(pal.secondary).toBeDefined();
      expect(pal.outline).toBeDefined();
      expect(pal.badge).toBeDefined();
    }
  });
});
