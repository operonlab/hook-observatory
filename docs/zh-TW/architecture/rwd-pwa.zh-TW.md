---
doc_version: 2
content_hash: 9c75f789
source_version: 2
translated_at: 2026-02-23
---

# RWD + PWA 開發標準

前端應用程式 (`dashboard/`) 必須遵循這些標準。

## Responsive Web Design (RWD)

### 斷點 (Tailwind CSS)

| Token | 最小寬度 | 目標裝置 |
|-------|-----------|--------|
| `sm`  | 640px     | 手機橫向 |
| `md`  | 768px     | 平板 |
| `lg`  | 1024px    | 桌機 |
| `xl`  | 1280px    | 大型桌機 |

### 規則

1. **Mobile-first**：預設樣式針對 `<640px`。對較寬螢幕使用 `sm:`、`md:`、`lg:`。
2. **Touch targets**：所有互動元素最小為 44×44px。
3. **No horizontal scroll**：在任何斷點皆不可出現。測試環境最小為 320px。
4. **Fluid typography**：使用 `rem` 單位（基數為 16px）。透過 `clamp()` 隨視窗縮放。
5. **Responsive images**：使用 `srcset` / `<picture>` 或 CSS `object-fit`。
6. **Container queries**：在組件級別的響應式設計中優先於媒體查詢。

### 測試清單

- [ ] 320px (小型手機)
- [ ] 375px (iPhone SE)
- [ ] 768px (iPad 直向)
- [ ] 1024px (iPad 橫向 / 小型桌機)
- [ ] 1280px+ (桌機)

## Progressive Web App (PWA)

### 必要檔案

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

各資源類型的策略：

| 資源 | 策略 | 原理 |
|-------|----------|-----------|
| App shell (HTML/CSS/JS) | **Cache-first** | 立即載入，在背景更新 |
| API 回應 | **Network-first**, 快取回退 | 優先選用新鮮數據 |
| 靜態資源 (圖片、字型) | **Cache-first**, stale-while-revalidate | 極少變動 |

### HTML 要求

```html
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#1e1e2e" />
<link rel="manifest" href="/manifest.json" />
<link rel="apple-touch-icon" href="/icons/icon-192.png" />
```

### 安裝標準 (Chrome)

1. 包含 `name`、`icons` (≥192px)、`start_url`、`display` 的有效 `manifest.json`
2. 已註冊且具有 `fetch` 事件處理器的 `Service Worker`
3. 透過 `HTTPS` 服務（開發環境可使用 `localhost`）

### 離線行為

- `App shell` 從快取載入（立即）
- 當網路不可用時顯示離線指示器
- 將變更加入佇列，待恢復連線時重放（未來功能）

## 在 Web App 中的實作

`dashboard` 應用程式 (`dashboard/`) 作為參考實作：
- 來自共享樣式的 `Tailwind` 斷點配置
- 來自 Web App 入口點的 `PWA manifest` 與 `SW` 註冊
- 透過 `CSS custom properties` 定義的深淺主題變數 (`Catppuccin Mocha`)

## 主題：Catppuccin Mocha

預設深色主題調色盤 (`CSS custom properties`)：

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
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
