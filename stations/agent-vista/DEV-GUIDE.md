# Agent Vista — Development Guide

## Build Pipeline

### Architecture: Single Binary with Embedded Frontend

Agent Vista 採用 Go `//go:embed` 將前端靜態檔案嵌入單一執行檔。

```
frontend/src/ → (pnpm build) → frontend/dist/ → (cp) → web/dist/ → (go build) → bin/agent-vista
                                                         ↑
                                              go:embed all:dist
                                              嵌入時間點：go build 編譯時
```

**關鍵檔案**: `web/embed.go`
```go
//go:embed all:dist
var DistFS embed.FS
```

### 正確的構建流程

**務必使用 `make build-all`**，它確保三步依序執行：

```bash
make build-all
```

等同於：
```bash
# Step 1: 構建前端
cd frontend && pnpm build        # → frontend/dist/

# Step 2: 複製到 Go embed 目錄
rm -rf web/dist
cp -r frontend/dist web/dist     # → web/dist/

# Step 3: 構建 Go binary（此刻嵌入 web/dist/ 的內容）
go build -o bin/agent-vista ./cmd/agent-vista
```

### 常見構建錯誤

#### 問題：前端修改後頁面沒有更新

**症狀**：修改了 `frontend/src/` 的程式碼，重新構建後瀏覽器顯示的仍是舊版本。

**根因**：Go `//go:embed` 在 **編譯時** 捕捉 `web/dist/` 的檔案內容。如果以下任一情況發生，binary 會嵌入過期的前端：

| 錯誤操作 | 結果 |
|----------|------|
| 只執行 `pnpm build` + `go build`，跳過 `cp` 步驟 | `web/dist/` 仍是舊的 |
| `pnpm build` 和 `go build` 並行執行 | Race condition，可能嵌入不完整的 dist |
| 只執行 `go build` 未重建前端 | 嵌入上一次的前端版本 |
| 使用 `make build`（非 `build-all`） | 只構建 Go，不包含前端流程 |

**診斷方式**：
```bash
# 1. 檢查磁碟上的 JS 檔名
ls web/dist/assets/*.js
# 例如：index-CtK_kiDY.js

# 2. 檢查伺服器提供的 JS 檔名
curl -s http://localhost:8840/ | grep -o 'assets/index-[^"]*\.js'
# 例如：assets/index-SmSk4IzP.js

# 如果兩者不同 → binary 嵌入了舊的前端
```

**修復方式**：
```bash
make build-all    # 完整重建
pkill -f agent-vista && ./bin/agent-vista &
# 瀏覽器 Cmd+Shift+R 強制刷新（清除快取）
```

#### 問題：瀏覽器快取舊的 JS

**症狀**：伺服器已提供新檔案，但瀏覽器仍執行舊版。

**修復**：`Cmd+Shift+R`（macOS）強制刷新，或開 DevTools → Network → Disable cache。

### 開發模式 vs 產品模式

| 模式 | 前端 | 後端 | 用途 |
|------|------|------|------|
| `make dev-frontend` + `make dev-backend` | Vite HMR (port 5173) | Go (port 8840, no embed) | 開發時使用，前端熱更新 |
| `make build-all` → `./bin/agent-vista` | 嵌入 binary | Go (port 8840) | 產品/測試模式 |

開發時建議使用雙終端分別跑 `dev-frontend` 和 `dev-backend`，避免反覆 build-all。

## Service Management

### 啟動
```bash
cd /path/to/agent-vista
./bin/agent-vista &           # 背景執行
# 或
nohup ./bin/agent-vista > /tmp/agent-vista.log 2>&1 &
```

### 停止
```bash
pkill -f agent-vista
```

### 重啟（構建後）
```bash
make build-all
pkill -f agent-vista || true
sleep 1
./bin/agent-vista &
```

## Frontend Canvas Architecture

### Render Pipeline（每幀執行順序）

```
0. Weather sky background  — 填滿整個 canvas（void 區域的天空底色）
1. Floor tiles             — 房間/走廊/牆壁覆蓋天空
1a. Outer wall windows     — 外牆上的窗戶顯示室外天氣
1b. Door portals           — 入口 + 房間門
2. Seat indicators
3. Z-sorted scene          — 傢俱 + 角色（依 Y 排序）
4. Name labels
5. Speech bubbles
6. Spawn/despawn effects
7. Sub-agent angels
8. CLI legend (bottom-left)
9. Day/Night overlay       — 光影 + 窗戶光暈 + 桌燈
10. Weather ambient tint   — 全螢幕微調色
11. Proximity interactions
12. Edit mode overlay
```

### Grid Layout

- 50 x 34 tiles, TILE = 16px
- 4 rooms + cross-shaped corridors
- At zoom 2 (default): grid = 1600 x 1088px on screen — **填滿大部分螢幕**
- Void tiles (rooms 之間的空隙) 僅有 4 格，極小

### Weather System (C3)

- **API**: Open-Meteo（免費，無需 API key）
- **地理位置**: Browser Geolocation API → ipapi.co IP fallback → default Taipei
- **快取**: 30 分鐘，失敗時 5 分鐘後重試
- **顯示方式**:
  - 外牆窗戶：顯示天空色 + 天氣動畫（雨滴/雪花/星星）
  - Canvas 背景：天氣主題色（zoom out 時可見），使用 ambientLight 連續插值 + phase 感知暖色調
  - Ambient tint：全螢幕微色調
  - Dashboard 面板：溫度 + 城市 + 天氣圖示（整合於右上角 DayNightIndicator）

### Day/Night System (C1)

- 基於系統時間，5 個階段：night → dawn → day → dusk → evening
- 控制：overlay 色調、ambient light、窗戶光暈強度、桌燈
