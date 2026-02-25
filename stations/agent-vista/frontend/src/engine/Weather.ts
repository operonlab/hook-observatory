// Weather system (C3) — deterministic weather based on date/hour seed
// No external API needed; generates pseudo-random weather cycles

export type WeatherType = 'clear' | 'cloudy' | 'rain' | 'snow';

export interface WeatherState {
  type: WeatherType;
  intensity: number;    // 0-1 (0 = mild, 1 = heavy)
  windSpeed: number;    // 0-1 horizontal drift factor
  label: string;        // Chinese display label
}

/** Simple hash from string to 0..1 */
function hashSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return (Math.abs(h) % 10000) / 10000;
}

/** Get current weather state (changes every ~3 hours, deterministic per day) */
export function getWeatherState(): WeatherState {
  const now = new Date();
  const dayKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}`;
  const period = Math.floor(now.getHours() / 3); // 8 periods per day
  const seed = hashSeed(`${dayKey}:${period}`);

  // Weather distribution: 40% clear, 25% cloudy, 25% rain, 10% snow
  let type: WeatherType;
  if (seed < 0.40) {
    type = 'clear';
  } else if (seed < 0.65) {
    type = 'cloudy';
  } else if (seed < 0.90) {
    type = 'rain';
  } else {
    type = 'snow';
  }

  // Intensity varies within the period
  const minuteSeed = hashSeed(`${dayKey}:${period}:${Math.floor(now.getMinutes() / 10)}`);
  const intensity = type === 'clear' ? 0 : 0.3 + minuteSeed * 0.7;
  const windSpeed = type === 'rain' ? 0.3 + minuteSeed * 0.4 : minuteSeed * 0.2;

  return {
    type,
    intensity,
    windSpeed,
    label: weatherLabel(type, intensity),
  };
}

function weatherLabel(type: WeatherType, intensity: number): string {
  switch (type) {
    case 'clear': return '晴朗';
    case 'cloudy': return intensity > 0.6 ? '多雲' : '少雲';
    case 'rain': return intensity > 0.7 ? '大雨' : '小雨';
    case 'snow': return intensity > 0.7 ? '大雪' : '小雪';
  }
}

export const WEATHER_ICONS: Record<WeatherType, string> = {
  clear: '☀️',
  cloudy: '☁️',
  rain: '🌧️',
  snow: '❄️',
};

// ── Particle system for rain/snow ──────────────────────────────────────

export interface WeatherParticle {
  x: number;
  y: number;
  speed: number;
  size: number;
  opacity: number;
  drift: number;  // horizontal movement
}

const MAX_PARTICLES = 200;

/** Managed pool of weather particles */
export class WeatherParticleSystem {
  particles: WeatherParticle[] = [];
  private canvasW = 0;
  private canvasH = 0;

  /** Update canvas dimensions */
  resize(w: number, h: number) {
    this.canvasW = w;
    this.canvasH = h;
  }

  /** Update particles for current frame */
  update(dt: number, weather: WeatherState) {
    if (weather.type === 'clear' || weather.type === 'cloudy') {
      // Fade out existing particles
      this.particles = this.particles.filter(p => {
        p.y += p.speed * dt / 16;
        p.opacity -= 0.02;
        return p.opacity > 0;
      });
      return;
    }

    const targetCount = Math.floor(MAX_PARTICLES * weather.intensity);

    // Spawn new particles
    while (this.particles.length < targetCount) {
      this.particles.push(this.createParticle(weather));
    }

    // Update existing
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      const speedMul = weather.type === 'snow' ? 0.3 : 1;
      p.y += p.speed * speedMul * dt / 16;
      p.x += p.drift * weather.windSpeed * dt / 16;

      // Snow sways horizontally
      if (weather.type === 'snow') {
        p.x += Math.sin(p.y * 0.01 + p.size * 10) * 0.3;
      }

      // Remove if off screen
      if (p.y > this.canvasH + 10 || p.x > this.canvasW + 20 || p.x < -20) {
        this.particles.splice(i, 1);
      }
    }

    // Trim excess
    if (this.particles.length > targetCount + 20) {
      this.particles.length = targetCount;
    }
  }

  private createParticle(weather: WeatherState): WeatherParticle {
    const isSnow = weather.type === 'snow';
    return {
      x: Math.random() * (this.canvasW + 40) - 20,
      y: -10 - Math.random() * 50,
      speed: isSnow ? 0.5 + Math.random() * 1 : 2 + Math.random() * 4,
      size: isSnow ? 1.5 + Math.random() * 2.5 : 1 + Math.random() * 1.5,
      opacity: 0.3 + Math.random() * 0.4,
      drift: 0.5 + Math.random() * 1.5,
    };
  }
}
