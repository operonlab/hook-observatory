---
doc_version: 2
content_hash: 9c75f789
source_version: 2
target_lang: en
translated_at: 2026-02-24
source_hash: fac097fb
source_lang: zh-TW
---

# RWD + PWA Development Guidelines

Frontend applications (`workbench/`) must adhere to these guidelines.

## Responsive Web Design (RWD)

### Breakpoints (Tailwind CSS)

| Token | Min-width | Target |
|-------|-----------|--------|
| `sm`  | 640px     | Mobile Landscape |
| `md`  | 768px     | Tablet |
| `lg`  | 1024px    | Desktop |
| `xl`  | 1280px    | Large Desktop |

### Rules

1. **Mobile First**: Default styles target `<640px`. Use `sm:`, `md:`, `lg:` for wider screens.
2. **Touch Targets**: All interactive elements must be a minimum of 44×44px.
3. **No Horizontal Scrolling**: Ever, at any breakpoint. Test down to 320px.
4. **Fluid Typography**: Use `rem` units (base 16px). Scale with viewport using `clamp()`.
5. **Responsive Images**: Use `srcset` / `<picture>` or CSS `object-fit`.
6. **Container Queries**: Prefer over media queries for component-level responsiveness.

### Test Checklist

- [ ] 320px (Small mobile)
- [ ] 375px (iPhone SE)
- [ ] 768px (iPad Portrait)
- [ ] 1024px (iPad Landscape / Small Desktop)
- [ ] 1280px+ (Desktop)

## Progressive Web App (PWA)

### Required Files

#### `manifest.json`
```json
{
  "name": "Full App Name",
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

Strategies by Asset Type:

| Asset | Strategy | Rationale |
|-------|----------|-----------|
| App shell (HTML/CSS/JS) | **Cache-first** | Instant load, update in background |
| API Responses | **Network-first**, with cache fallback | Prioritize fresh data |
| Static Assets (images, fonts) | **Cache-first**, stale-while-revalidate | Changes rarely |

### HTML Requirements

```html
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#1e1e2e" />
<link rel="manifest" href="/manifest.json" />
<link rel="apple-touch-icon" href="/icons/icon-192.png" />
```

### Installation Criteria (Chrome)

1. A valid `manifest.json` with `name`, `icons` (≥192px), `start_url`, and `display`
2. A registered service worker with a `fetch` event handler
3. Served over HTTPS (localhost is fine for development)

### Offline Behavior

- App shell loads from cache (instant)
- Show an offline indicator when network is unavailable
- Queue mutations to be replayed on reconnect (future feature)

## Implementation in the Web App

The workbench app (`workbench/`) serves as the reference implementation:
- Tailwind breakpoint configuration from shared styles
- PWA manifest and SW registration from the web app entry point
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
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2508ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2536ms
