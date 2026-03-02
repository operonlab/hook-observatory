# Agent Vista: RWD + PWA 實作計畫

## Context

Agent Vista 目前是純桌面體驗：Canvas 2D 全螢幕渲染、滑鼠操作、無 PWA 基礎設施。
本計畫評估加入 RWD + PWA 的範圍與成本。

**現況診斷**：RWD ~20% 就緒、PWA 0% 就緒。
**核心挑戰**：像素藝術 Canvas 的觸控/DPR 適配 + 固定寬度 UI panels 的響應式重構。

## 關鍵決策

| 決策 | 選擇 | 理由 |
|------|------|------|
| DPR 策略 | Cap 2x（不用 3x） | 4 倍 vs 9 倍 buffer，像素藝術 2x 已足夠清晰 |
| 行動端佈局編輯 | View-only | 右鍵拖曳+鍵盤快捷鍵在觸控上無等價物，使用頻率極低 |
| 離線深度 | 最小化（precache 靜態資產） | 即時監控工具離線無意義，僅保留「上次已知狀態」 |
| SW 方案 | vite-plugin-pwa | 自動 precache manifest + SW 註冊，維護成本最低 |
| Push Notification | 不做 | localhost 工具 + 已有 Web Notification，不值得建 push 基礎設施 |

## 分階段計畫

### Phase 0：PWA 基礎（3-4hr）★★★★★ 最高 ROI

可安裝 + 啟動快 + 專業感。完全不影響現有功能。

**0.1** 安裝 vite-plugin-pwa
- `frontend/package.json` — 加入 `vite-plugin-pwa` 依賴
- `frontend/vite.config.ts` — VitePWA plugin 設定：
  - `registerType: 'autoUpdate'`（自動替換舊 SW）
  - workbox precache `**/*.{js,css,html,woff2}`
  - runtimeCaching: Open-Meteo API → StaleWhileRevalidate 30 分鐘
  - manifest: name/short_name/theme_color/background_color/display:standalone/orientation:any

**0.2** 產生像素藝術圖示
- 建立 `frontend/scripts/generate-icons.ts`（用 `@napi-rs/canvas`）
- 從 `sprites/templates.ts` 的 `downIdle0` 幀渲染角色到 192x192 和 512x512 PNG
- 輸出到 `frontend/public/icons/`
- 或更簡單：手動建立一個 16x16 像素圖，用 nearest-neighbor 放大

**0.3** index.html 增強
- `frontend/index.html` 加入：
  - `<meta name="theme-color" content="#1a1a2e" />`
  - `<meta name="apple-mobile-web-app-capable" content="yes" />`
  - `<link rel="apple-touch-icon" href="./icons/icon-192.png" />`

**0.4** 離線狀態指示
- `Dashboard.tsx` 加入 `navigator.onLine` 監聽，wsStatus 旁顯示網路狀態

---

### Phase 1：觸控互動（4-5hr）★★★★☆ 手機可操作

**1.1** Camera 觸控支援
- `frontend/src/engine/Camera.ts` — 新增 `attachTouch(canvas)` 方法：
  - 單指拖曳 = 平移（取代 mouse drag）
  - 雙指 pinch = 整數倍 zoom（取代 mouse wheel）
  - 以雙指中點為縮放基準，保持穩定
  - `passive: false` + `preventDefault()` 防止瀏覽器預設滾動

**1.2** 觸控 tap vs drag 判定
- `BubbleOverlay.tsx` — 記錄 touchstart 位置，click 時檢查位移 < 10px 才視為 tap
- 避免拖曳結束時誤觸 agent 選取

**1.3** viewport meta 調整
- `frontend/index.html` — viewport 加入 `maximum-scale=1.0, user-scalable=no`
- 防止瀏覽器雙擊縮放干擾 canvas 操作

**1.4** PixelOffice 觸控綁定
- `PixelOffice.tsx` — `usePixelEngine` hook 中 attach touch events

---

### Phase 2：DPR 清晰度（2-3hr）★★★☆☆ 視覺提升

**2.1** Renderer DPR 處理
- `frontend/src/engine/Renderer.ts` L79-84：
  - `const dpr = Math.min(devicePixelRatio || 1, 2)`
  - canvas buffer = `cw * dpr` × `ch * dpr`
  - CSS size 維持 `cw` × `ch`
  - `ctx.setTransform(dpr, 0, 0, dpr, 0, 0)` — Camera 座標系不變（最乾淨）

**2.2** Minimap DPR
- `Minimap.tsx` — 同步 DPR 處理（buffer 小，開銷可忽略）

**2.3** DPR 變更監聽
- `matchMedia(\`(resolution: ${dpr}dppx)\`)` change 時清除 sprite cache

---

### Phase 3：響應式 Panel Layout（4-5hr）★★★★☆ 手機 UI 可讀

**3.1** Breakpoint hook
- 新增 `frontend/src/hooks/useBreakpoint.ts`
- `mobile < 640px` | `tablet 640-1024px` | `desktop > 1024px`
- `useSyncExternalStore` 實作（零依賴）

**3.2** Dashboard 響應式
- `Dashboard.tsx`:
  - **Mobile**：底部可收合 drawer，預設收合只顯示摘要行「3 活躍 | 15.2K tokens」
  - **Tablet**：右側 180px（從 220px 縮減）
  - **Desktop**：不變
  - Mobile 隱藏「編輯佈局」按鈕

**3.3** AgentDetailPanel 響應式
- `AgentDetailPanel.tsx`:
  - **Mobile**：bottom sheet（從底部滑入，全寬，50-70% 高度）
  - **Tablet**：寬度 240px
  - **Desktop**：不變（300px）

**3.4** Minimap 響應式
- `Minimap.tsx`:
  - **Mobile**：預設隱藏（`uiStore.minimapVisible = false`）
  - **Tablet**：MINIMAP_SCALE=3（150×102px）

**3.5** BubbleOverlay 響應式
- `BubbleOverlay.tsx`: 寬度改為 `min(280px, calc(100vw - 24px))`

**3.6** ChatChannel 微調
- `ChatChannel.tsx`: Mobile 時 fontSize 縮小、gap 縮減

---

### Phase 4：進階觸控 UX（3-4hr）★★☆☆☆ 錦上添花，可選

- **4.1** 慣性滑動：touchend 時計算速度 → rAF 減速（friction 0.95）
- **4.2** Double-tap zoom：300ms 內兩次 tap → toggle zoom 1⟷2
- **4.3** Long-press context menu：600ms 長按 agent 顯示 action menu
- **4.4** 首次使用手勢教學 overlay（localStorage 記錄已顯示）

## 工時與風險

| Phase | 工時 | 累計 | 風險 |
|-------|------|------|------|
| Phase 0: PWA | 3-4hr | 3-4hr | 低（vite-plugin-pwa 與 Go embed 相容性需驗證） |
| Phase 1: Touch | 4-5hr | 7-9hr | 中（tap vs drag 判定需實機測試） |
| Phase 2: DPR | 2-3hr | 9-12hr | 低（setTransform 方案不改 Camera 座標系） |
| Phase 3: Panels | 4-5hr | 13-17hr | 中（Dashboard drawer 動畫需微調） |
| Phase 4: UX | 3-4hr | 16-21hr | 低（獨立增量，可隨時停） |

**核心（Phase 0-3）= 13-17hr，可選（Phase 4）= +3-4hr**

## 修改檔案清單

| 檔案 | Phase | 動作 |
|------|-------|------|
| `frontend/package.json` | 0 | 加依賴 |
| `frontend/vite.config.ts` | 0 | VitePWA 設定 |
| `frontend/index.html` | 0,1 | meta tags |
| `frontend/public/icons/` | 0 | 新增 PNG 圖示 |
| `frontend/scripts/generate-icons.ts` | 0 | 新增圖示產生腳本 |
| `frontend/src/engine/Camera.ts` | 1,4 | 觸控事件 |
| `frontend/src/engine/Renderer.ts` | 2 | DPR 處理 |
| `frontend/src/hooks/useBreakpoint.ts` | 3 | 新增 |
| `frontend/src/components/Dashboard.tsx` | 0,3 | 響應式 + 離線指示 |
| `frontend/src/components/AgentDetailPanel.tsx` | 3 | bottom sheet |
| `frontend/src/components/Minimap.tsx` | 2,3 | DPR + 響應式 |
| `frontend/src/components/BubbleOverlay.tsx` | 1,3 | tap 判定 + 寬度 |
| `frontend/src/components/PixelOffice.tsx` | 1 | 觸控綁定 |
| `frontend/src/components/ChatChannel.tsx` | 3 | Mobile 微調 |
| `frontend/src/stores/uiStore.ts` | 3 | Mobile 預設值 |

## 驗證方式

1. **PWA**: Chrome DevTools → Application → Manifest/Service Worker 面板確認可安裝
2. **觸控**: Chrome DevTools 開啟 Device Emulation（iPhone 14 Pro / iPad），測試 pan/zoom/tap
3. **DPR**: DevTools 設定 DPR=2/3，確認 canvas 清晰度
4. **響應式**: 拖拽 DevTools 寬度跨越 640/1024 斷點，確認 panel 切換
5. **Build**: `make build-all` → 啟動 binary → 瀏覽器確認 SW 註冊 + manifest
6. **實機**: 手機連 Tailscale → `http://100.104.237.69:8840` 測試真實觸控
