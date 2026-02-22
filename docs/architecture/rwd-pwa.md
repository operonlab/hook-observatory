# RWD + PWA Development Standards

All frontend applications (`apps/*`) MUST follow these standards.

## Responsive Web Design (RWD)

### Breakpoints (Tailwind CSS)

| Token | Min Width | Target |
|-------|-----------|--------|
| `sm`  | 640px     | Mobile landscape |
| `md`  | 768px     | Tablet |
| `lg`  | 1024px    | Desktop |
| `xl`  | 1280px    | Large desktop |

### Rules

1. **Mobile-first**: Default styles target `<640px`. Use `sm:`, `md:`, `lg:` for wider screens.
2. **Touch targets**: Minimum 44×44px for all interactive elements.
3. **No horizontal scroll**: At any breakpoint. Test at 320px minimum.
4. **Fluid typography**: Use `rem` units (base 16px). Scale with viewport via `clamp()`.
5. **Responsive images**: Use `srcset` / `<picture>` or CSS `object-fit`.
6. **Container queries**: Prefer over media queries for component-level responsiveness.

### Testing Checklist

- [ ] 320px (small mobile)
- [ ] 375px (iPhone SE)
- [ ] 768px (iPad portrait)
- [ ] 1024px (iPad landscape / small desktop)
- [ ] 1280px+ (desktop)

## Progressive Web App (PWA)

### Required Files

#### `manifest.json`
```json
{
  "name": "App Full Name",
  "short_name": "App",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1e1e2e",
  "theme_color": "#89b4fa",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

#### Service Worker

Strategy per asset type:

| Asset | Strategy | Rationale |
|-------|----------|-----------|
| App shell (HTML/CSS/JS) | **Cache-first** | Instant load, update in background |
| API responses | **Network-first**, cache fallback | Fresh data preferred |
| Static assets (images, fonts) | **Cache-first**, stale-while-revalidate | Rarely change |

### HTML Requirements

```html
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#1e1e2e" />
<link rel="manifest" href="/manifest.json" />
<link rel="apple-touch-icon" href="/icons/icon-192.png" />
```

### Install Criteria (Chrome)

1. Valid `manifest.json` with `name`, `icons` (≥192px), `start_url`, `display`
2. Registered service worker with `fetch` event handler
3. Served over HTTPS (or localhost for dev)

### Offline Behavior

- App shell loads from cache (instant)
- Show offline indicator when network unavailable
- Queue mutations for replay when back online (future)

## Implementation in Web App

The web app (`apps/web/`) serves as the reference implementation:
- Tailwind breakpoint config from shared styles
- PWA manifest and SW registration from web app entry point
- Dark/light theme variables via CSS custom properties (Catppuccin Mocha)

## Theme: Catppuccin Mocha

Default dark theme palette (CSS custom properties):

```css
:root {
  --base: #1e1e2e;
  --mantle: #181825;
  --crust: #11111b;
  --surface0: #313244;
  --surface1: #45475a;
  --text: #cdd6f4;
  --subtext0: #a6adc8;
  --blue: #89b4fa;
  --lavender: #b4befe;
  --mauve: #cba6f7;
  --green: #a6e3a1;
  --red: #f38ba8;
  --peach: #fab387;
  --yellow: #f9e2af;
  --teal: #94e2d5;
}
```
