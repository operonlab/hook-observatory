# 前端配色系統修復 -- 經驗記錄

## 日期

2026-02-27

## 背景

Workshop 是一個模組化工作台前端（React 19 + TypeScript + Rsbuild），使用 Catppuccin Mocha 作為全域深色主題。在 v2 重構期間，首頁（/v2/apps）和記憶金庫模組（/v2/memvault）的配色出現嚴重問題。

## 問題一：CSS var() 拼接無效

### 現象

首頁 App 卡片的背景色、邊框色、圖示容器全部顯示為接近黑色（rgba(0,0,0,0)），與設計稿的半透明彩色效果完全不符。

### 根因

`apps.ts` 中的模組顏色使用 CSS 變數引用：

```typescript
{ id: "finance", color: "var(--green)", ... }
```

在 JSX inline style 中進行字串拼接：

```tsx
backgroundColor: app.color + "40"  // "var(--green)40"
```

**CSS var() 替換產生的是獨立 token，不是字串拼接。** `var(--green)40` 會被解析為 `#a6e3a1` 後面跟著一個無意義的 `40`，整個值無效，回退為 transparent。

### 修復

將 `apps.ts` 中所有模組顏色改為原始 hex 值：

```typescript
{ id: "finance", color: "#a6e3a1", ... }  // raw hex, not var()
```

這樣 `"#a6e3a1" + "40"` = `"#a6e3a140"` 是合法的 8 位 hex color（含 alpha）。

### 教訓

- **CSS var() 不能用於字串拼接**。`var(--color)XX` 永遠不會產生 `#rrggbbXX`。
- 需要動態 alpha 的合法方案：
  1. 原始 hex + alpha 後綴：`"#a6e3a1" + "40"` -> `"#a6e3a140"`
  2. `color-mix(in srgb, var(--green) 25%, transparent)` -- 可與 CSS 變數搭配
  3. 用 JS 工具函式（如 hexToRgba）在 runtime 計算
- **永遠用 Playwright computed style 驗證** -- 肉眼看「黑色」無法區分是 transparent 還是真的黑色

## 問題二：Memvault Midnight Neural 主題色調異常

### 現象

記憶金庫模組的所有頁面色調「詭異」-- 背景幾乎全黑，強調色過於刺眼，整體觀感不協調。

### 根因

`memvault.css` 使用 `.memvault` class scope 覆蓋所有 Catppuccin CSS 變數，但色彩選擇有兩大問題：

1. **背景過暗**：`--base: #0B0D1A` 比全域 Catppuccin Mocha `#1e1e2e` 暗了將近一倍，接近純黑
2. **強調色過飽和**：使用 Tailwind 400 級色彩（`#4ADE80`, `#F87171`, `#FACC15` 等），這些色彩是為淺色背景設計的，在深色背景上對比太強烈、刺眼

| 顏色 | 舊值（Tailwind 400） | 新值（Catppuccin-adjacent） | 問題 |
|------|----------------------|---------------------------|------|
| blue | #7C8FFF | #9AB4F2 | 過飽和紫藍 -> 柔和天藍 |
| green | #4ADE80 | #92D8A6 | 螢光綠 -> 柔和鼠尾草 |
| red | #F87171 | #E8A0B4 | 刺眼紅 -> 柔和玫瑰 |
| yellow | #FACC15 | #E2D4A0 | 刺眼金 -> 柔和金沙 |
| teal | #2DD4BF | #88D0C6 | 螢光青 -> 柔和海泡 |

### 修復

- 背景提亮 1.5-2 階：`#0B0D1A` -> `#151726`（保留 midnight blue 特色但可辨識）
- 所有強調色改為 Catppuccin-adjacent：保持色相但降低飽和度、提高明度
- 硬編碼 `rgba(124, 143, 255, 0.12)` 改為 `color-mix(in srgb, var(--blue) 12%, transparent)`
- 3D 場景背景配合新 `--crust` 更新

### 教訓

- **深色主題的強調色不能直接用為淺色背景設計的色板**（如 Tailwind 400 級）
- 在深色背景（亮度 < 15%）上，強調色的飽和度應降低 20-30%、明度提高 10-15%
- **模組級 CSS scope override 會完全隔離全域變數修改** -- 改了 globals.css 的 `--blue` 不會影響 `.memvault` 內部
- 硬編碼 rgba 值會在主題變更時脫節，應優先使用 `color-mix()` 跟隨 CSS 變數

## 問題三：Build 路徑遺漏

### 現象

Build 後所有資源 404，頁面空白。

### 根因

忘記加 `BASE_PATH=/v2` 環境變數，導致資源路徑從 `/v2/static/` 變成 `/static/`。

### 修復

正確指令：`BASE_PATH=/v2 pnpm run build`

### 教訓

- Build 指令已記錄於 `.claude/rules/frontend-build.md`，**每次 build 前應檢查 rules**
- Service Worker 的 CACHE_NAME 包含 git hash，build 後會自動失效舊 cache

## 通用教訓

1. **CSS 變數的限制**：var() 是 token 替換，不是字串拼接。需要動態 alpha 時用 `color-mix()` 或原始 hex。
2. **模組化主題的隔離性**：CSS scope override 是雙刃劍 -- 提供隔離但也阻擋全域修改的傳播。
3. **深色主題配色原則**：Catppuccin Mocha 的成功在於精心調校的低飽和度。自定義深色主題時應以 Catppuccin 為參照基線。
4. **視覺驗證不可省略**：每次 CSS 修改後必須用 Playwright computed style 驗證，不能只看程式碼。
5. **色彩一致性**：同一設計系統內的所有色彩應來自同一家族（如都是 Catppuccin-adjacent），不要混用不同體系。

## 修改檔案清單

| 檔案 | 修改內容 |
|------|---------|
| `workbench/src/styles/globals.css` | 新增 --flamingo, --maroon, --accent；調整 --blue |
| `workbench/src/shared/constants/apps.ts` | CSS var 引用改為原始 hex 值 |
| `workbench/src/pages/Home.tsx` | 完整重寫，per-module 配色 + 新背景色 |
| `workbench/src/shell/AppHeader.tsx` | 動態模組配色跟隨 |
| `workbench/src/shell/AppLauncher.tsx` | 配色感知的 active/hover 狀態 |
| `workbench/src/pages/Login.tsx` | 品牌色改為 --accent |
| `workbench/src/pages/NotFound.tsx` | 品牌色改為 --accent |
| `workbench/src/App.tsx` | Loading spinner 配色 |
| `workbench/src/modules/memvault/styles/memvault.css` | Midnight Neural 主題全面調校 |
| `workbench/src/modules/memvault/components/MemvaultLayout.tsx` | 硬編碼 rgba -> color-mix |
| `workbench/src/modules/memvault/components/GalaxyCanvas.tsx` | 3D 場景背景更新 |
