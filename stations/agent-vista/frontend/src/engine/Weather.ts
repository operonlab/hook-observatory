// Weather system (C3) — real weather based on user's geolocation
// Uses Open-Meteo free API (no key required) + ipapi.co for geolocation fallback
// Weather affects only ambient lighting tint — no particle effects to avoid visual clutter

export type WeatherType = 'clear' | 'cloudy' | 'rain' | 'snow' | 'fog';

export interface WeatherState {
  type: WeatherType;
  intensity: number;    // 0-1 (0 = mild, 1 = heavy)
  label: string;        // Chinese display label
  temperature?: number; // Celsius
  city?: string;        // Location name (from timezone or IP geolocation)
}

// ── Cached state ──────────────────────────────────────────────────────────

let cachedWeather: WeatherState = { type: 'clear', intensity: 0, label: '晴朗' };
let lastFetchTime = 0;
const CACHE_DURATION = 30 * 60 * 1000; // 30 min cache
let fetchInProgress = false;

/** Get current weather state (cached, non-blocking) */
export function getWeatherState(): WeatherState {
  const now = Date.now();
  if (now - lastFetchTime > CACHE_DURATION && !fetchInProgress) {
    fetchInProgress = true;
    fetchRealWeather()
      .then(w => {
        cachedWeather = w;
        lastFetchTime = Date.now();
      })
      .catch(() => {
        // On failure, keep cached value; retry next interval
        lastFetchTime = Date.now() - CACHE_DURATION + 5 * 60 * 1000; // retry in 5 min
      })
      .finally(() => { fetchInProgress = false; });
  }
  return cachedWeather;
}

// Eagerly kick off weather fetch on module load (don't wait for first render)
fetchRealWeather()
  .then(w => { cachedWeather = w; lastFetchTime = Date.now(); })
  .catch(() => { /* will retry via getWeatherState */ });

// ── Real weather fetch ────────────────────────────────────────────────────

interface GeoLocation {
  latitude: number;
  longitude: number;
}

let cachedGeo: GeoLocation | null = null;
let cachedCity = '';

async function getLocation(): Promise<GeoLocation> {
  if (cachedGeo) return cachedGeo;

  // Try browser Geolocation API first (more accurate, short timeout)
  try {
    const pos = await new Promise<GeolocationPosition>((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        timeout: 2000,
        maximumAge: 3600000, // cache for 1h
      });
    });
    cachedGeo = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
    return cachedGeo;
  } catch {
    // Fall through to IP-based geolocation
  }

  // Fallback: IP-based geolocation (short timeout, may be rate-limited)
  try {
    const res = await fetch('https://ipapi.co/json/', { signal: AbortSignal.timeout(2000) });
    if (res.ok) {
      const data = await res.json();
      if (data.latitude && data.longitude) {
        cachedGeo = { latitude: data.latitude, longitude: data.longitude };
        if (data.city) cachedCity = data.city;
        return cachedGeo;
      }
    }
  } catch {
    // Fall through to default
  }

  // Default: Taipei
  cachedGeo = { latitude: 25.033, longitude: 121.565 };
  if (!cachedCity) cachedCity = 'Taipei';
  return cachedGeo;
}

/** WMO Weather interpretation codes → our simplified types */
function wmoToWeather(code: number): { type: WeatherType; intensity: number } {
  // WMO codes: https://open-meteo.com/en/docs
  if (code <= 1) return { type: 'clear', intensity: 0 };
  if (code <= 3) return { type: 'cloudy', intensity: code === 2 ? 0.4 : 0.7 };
  if (code <= 49) return { type: 'fog', intensity: 0.5 }; // fog/rime
  if (code <= 59) return { type: 'rain', intensity: 0.3 }; // drizzle
  if (code <= 69) return { type: 'rain', intensity: code >= 65 ? 0.9 : 0.6 }; // rain
  if (code <= 79) return { type: 'snow', intensity: code >= 75 ? 0.9 : 0.5 }; // snow
  if (code <= 82) return { type: 'rain', intensity: 0.8 }; // rain showers
  if (code <= 86) return { type: 'snow', intensity: 0.7 }; // snow showers
  if (code >= 95) return { type: 'rain', intensity: 0.9 }; // thunderstorm
  return { type: 'clear', intensity: 0 };
}

function weatherLabel(type: WeatherType, intensity: number): string {
  switch (type) {
    case 'clear': return '晴朗';
    case 'cloudy': return intensity > 0.6 ? '多雲' : '少雲';
    case 'rain': return intensity > 0.7 ? '大雨' : '小雨';
    case 'snow': return intensity > 0.7 ? '大雪' : '小雪';
    case 'fog': return '霧';
  }
}

async function fetchRealWeather(): Promise<WeatherState> {
  const geo = await getLocation();
  const url = `https://api.open-meteo.com/v1/forecast?latitude=${geo.latitude}&longitude=${geo.longitude}&current=weather_code,temperature_2m&timezone=auto`;

  const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`Weather API ${res.status}`);

  const data = await res.json();
  const code = data.current?.weather_code ?? 0;
  const temp = data.current?.temperature_2m ?? 20;

  // Extract city from timezone if not already cached (e.g. "Asia/Taipei" → "Taipei")
  if (!cachedCity && data.timezone) {
    cachedCity = data.timezone.split('/').pop()?.replace(/_/g, ' ') || '';
  }

  const { type, intensity } = wmoToWeather(code);
  return {
    type,
    intensity,
    label: weatherLabel(type, intensity),
    temperature: Math.round(temp),
    city: cachedCity,
  };
}

// ── Display helpers ───────────────────────────────────────────────────────

export const WEATHER_ICONS: Record<WeatherType, string> = {
  clear: '☀️',
  cloudy: '☁️',
  rain: '🌧️',
  snow: '❄️',
  fog: '🌫️',
};

// ── Ambient tint for weather overlay (subtle, non-intrusive) ──────────────

export interface WeatherTint {
  r: number;
  g: number;
  b: number;
  alpha: number; // very low — max ~0.06
}

// ── Sky color helpers ──────────────────────────────────────────────────────

type RGB = [number, number, number];

function lerpRGB(a: RGB, b: RGB, t: number): RGB {
  const c = Math.max(0, Math.min(1, t));
  return [
    Math.round(a[0] + (b[0] - a[0]) * c),
    Math.round(a[1] + (b[1] - a[1]) * c),
    Math.round(a[2] + (b[2] - a[2]) * c),
  ];
}

function rgbStr(c: RGB): string {
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

// Sky color tables: [night, day] per weather type
// Night ≈ ambientLight 0.5, Day ≈ ambientLight 1.0
const SKY_COLORS: Record<WeatherType, { night: RGB; day: RGB; dusk: RGB }> = {
  clear:  { night: [8, 12, 36],    day: [100, 165, 220],  dusk: [200, 110, 55] },
  cloudy: { night: [16, 16, 22],   day: [155, 168, 182],  dusk: [150, 110, 80] },
  rain:   { night: [8, 10, 22],    day: [95, 112, 132],   dusk: [100, 80, 65] },
  snow:   { night: [14, 18, 28],   day: [165, 180, 195],  dusk: [150, 130, 110] },
  fog:    { night: [12, 12, 16],   day: [125, 130, 140],  dusk: [110, 100, 85] },
};

// Window colors are slightly brighter/more saturated than background sky
const WIN_COLORS: Record<WeatherType, { night: RGB; day: RGB; dusk: RGB }> = {
  clear:  { night: [14, 22, 60],   day: [120, 185, 240],  dusk: [220, 130, 65] },
  cloudy: { night: [22, 22, 32],   day: [170, 182, 196],  dusk: [165, 125, 90] },
  rain:   { night: [12, 16, 32],   day: [110, 128, 150],  dusk: [115, 95, 75] },
  snow:   { night: [20, 24, 38],   day: [180, 195, 210],  dusk: [165, 145, 120] },
  fog:    { night: [18, 18, 24],   day: [140, 145, 155],  dusk: [125, 115, 95] },
};

/**
 * Interpolate sky color based on ambientLight (0.5=night → 1.0=day)
 * and optional phase for warm dusk/evening tones.
 */
function interpolateSky(
  table: Record<WeatherType, { night: RGB; day: RGB; dusk: RGB }>,
  weather: WeatherState,
  ambientLight: number,
  phase?: string,
): string {
  const entry = table[weather.type] ?? table.clear;
  // Normalize ambientLight 0.5..1.0 → 0..1
  const t = Math.max(0, Math.min(1, (ambientLight - 0.5) / 0.5));

  if (phase === 'dusk') {
    // Dusk: blend from day color towards warm dusk, then towards night
    // ambientLight goes 1.0→0.72 during dusk (t goes 1.0→0.44)
    const duskBlend = Math.max(0, Math.min(1, (1 - t) / 0.56)); // 0 at full day, 1 at amb=0.72
    const warmSky = lerpRGB(entry.day, entry.dusk, duskBlend);
    return rgbStr(warmSky);
  }
  if (phase === 'evening') {
    // Evening: blend from warm dusk towards night
    // ambientLight goes 0.72→0.5 during evening (t goes 0.44→0)
    const eveningBlend = Math.max(0, Math.min(1, 1 - t / 0.44)); // 0 at amb=0.72, 1 at night
    const warmSky = lerpRGB(entry.dusk, entry.night, eveningBlend);
    return rgbStr(warmSky);
  }
  if (phase === 'dawn') {
    // Dawn: blend from night towards day with a slight warm tint
    const dawnMid = lerpRGB(entry.night, entry.dusk, 0.4); // subtle warmth at midpoint
    if (t < 0.5) {
      return rgbStr(lerpRGB(entry.night, dawnMid, t * 2));
    }
    return rgbStr(lerpRGB(dawnMid, entry.day, (t - 0.5) * 2));
  }

  // Default: straight night↔day lerp
  return rgbStr(lerpRGB(entry.night, entry.day, t));
}

/** Sky background color for void/outdoor areas — varies by weather + time of day */
export function getWeatherSkyColor(weather: WeatherState, ambientLight: number, phase?: string): string {
  return interpolateSky(SKY_COLORS, weather, ambientLight, phase);
}

/** Brighter sky color for "window" elements on walls */
export function getWindowSkyColor(weather: WeatherState, ambientLight: number, phase?: string): string {
  return interpolateSky(WIN_COLORS, weather, ambientLight, phase);
}

/** Get a subtle color tint based on weather for ambient overlay */
export function getWeatherTint(weather: WeatherState): WeatherTint {
  switch (weather.type) {
    case 'rain':
      return { r: 30, g: 50, b: 80, alpha: 0.04 + weather.intensity * 0.04 };
    case 'snow':
      return { r: 200, g: 210, b: 230, alpha: 0.02 + weather.intensity * 0.03 };
    case 'cloudy':
      return { r: 40, g: 40, b: 50, alpha: 0.02 + weather.intensity * 0.04 };
    case 'fog':
      return { r: 160, g: 160, b: 180, alpha: 0.03 + weather.intensity * 0.03 };
    case 'clear':
    default:
      return { r: 0, g: 0, b: 0, alpha: 0 };
  }
}
