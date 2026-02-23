---
doc_version: 2
content_hash: 9c75f789
source_version: 2
target_lang: zh-TW
translated_at: 2026-02-23
---

# RWD + PWA 開發規範

前端應用程式 (`workbench/`) 必須遵守這些規範。

## 響應式網頁設計 (RWD)

### 斷點 (Tailwind CSS)

| Token | 最小寬度 | 目標 |
|-------|-----------|--------|
| `sm`  | 640px     | 手機橫向 |
| `md`  | 768px     | 平板 |
| `lg`  | 1024px    | 桌上型電腦 |
| `xl`  | 1280px    | 大型桌上型電腦 |

### 規則

1. **行動優先**：預設樣式針對 `<640px`。較寬的螢幕請使用 `sm:`、`md:`、`lg:`。
2. **觸控目標**：所有互動元素最小需為 44×44px。
3. **禁止橫向捲動**：在任何斷點下皆然。最低請在 320px 進行測試。
4. **流體字型**：使用 `rem` 單位（基準為 16px）。透過 `clamp()` 隨視窗大小縮放。
5. **響應式圖片**：使用 `srcset` / `<picture>` 或 CSS `object-fit`。
6. **容器查詢**：在元件級別的響應式設計中，優先於媒體查詢使用。

### 測試檢查清單

- [ ] 320px (小型手機)
- [ ] 375px (iPhone SE)
- [ ] 768px (iPad 縱向)
- [ ] 1024px (iPad 橫向 / 小型桌上型電腦)
- [ ] 1280px+ (桌上型電腦)

## 漸進式網路應用程式 (PWA)

### 必要檔案

#### `manifest.json`
```json
{
  "name": "應用程式全名",
  "short_name": "應用程式",
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

各資產類型的策略：

| 資產 | 策略 | 原理說明 |
|-------|----------|-----------|
| App shell (HTML/CSS/JS) | **Cache-first** | 即時載入，在背景更新 |
| API 回應 | **Network-first**, 快取備援 | 優先取得最新數據 |
| 靜態資產 (圖片、字型) | **Cache-first**, stale-while-revalidate | 極少變動 |

### HTML 要求

```html
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#1e1e2e" />
<link rel="manifest" href="/manifest.json" />
<link rel="apple-touch-icon" href="/icons/icon-192.png" />
```

### 安裝標準 (Chrome)

1. 包含 `name`、`icons` (≥192px)、`start_url`、`display` 的有效 `manifest.json`
2. 已註冊且包含 `fetch` 事件處理器的 service worker
3. 透過 HTTPS 傳輸（開發環境可使用 localhost）

### 離線行為

- App shell 從快取載入（即時）
- 網路不可用時顯示離線指示器
- 將變更放入佇列，待重新連線後重播（未來功能）

## 在 Web App 中的實作

workbench 應用程式 (`workbench/`) 作為參考實作：
- 來自共用樣式的 Tailwind 斷點配置
- 來自 Web App 進入點的 PWA manifest 和 SW 註冊
- 透過 CSS 自定義屬性實現深色/淺色主題變數 (Catppuccin Mocha)

## 主題：Catppuccin Mocha

預設深色主題調色盤 (CSS 自定義屬性)：

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
