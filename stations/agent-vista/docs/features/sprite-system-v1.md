# Sprite System v1 — 像素精靈升級計畫

> 狀態：**規劃中** | 日期：2026-02-26

## 背景

Agent Vista 目前使用程序化精靈（10×14 indexed color 陣列），透過 `OffscreenCanvas` 逐像素繪製。
已準備 17 張像素風 sprite PNG（`sprites/` 目錄），目標是用 PNG sprite sheet 取代程序化精靈，
同時保留程序化精靈作為 fallback。

核心問題：**多檔案管理會不會失控？該用什麼工具鏈？資料結構怎麼設計？**

---

## 1. 規模估算

| 維度 | 數量 | 說明 |
|------|------|------|
| CLI 類型 | 3 | claude / codex / gemini |
| 動畫狀態 | 6 | IDLE, WALK, TYPE, THINK, WAIT, ERROR |
| 方向 | 3 | down, up, right（left = right 翻轉） |
| 每動畫幀數 | 2-4 | 流暢度最低門檻 |
| 家具 | 11 | 靜態單幀 |
| **總估計** | **~150-220 幀** | 不含未來擴充 |

結論：規模不大，但需要好的組織方式。

---

## 2. 儲存策略：Embedded（非 RustFS）

| 面向 | 判斷 |
|------|------|
| 規模 | 全部 sprites < 50KB，Go binary 50-100MB，佔比可忽略 |
| 用途 | Agent Vista 是本地 station，單用戶，無共享需求 |
| 延遲 | embedded = 0ms，RustFS = 10-50ms/request |
| 可靠性 | RustFS 停機 = 角色消失 |
| 架構 | RustFS 是「共享層」設計，station 不該依賴它 |

**結論：保持 embedded in Go binary，零依賴最可靠。**

> 未來如果有「sprite 商城」或跨工作站共享才考慮 RustFS。

---

## 3. 工具鏈

### 推薦方案：Aseprite + Sprite Sheet

```
創作階段                     建置階段                    運行時
┌─────────────┐         ┌──────────────┐         ┌──────────────┐
│  Aseprite   │  CLI    │ Sprite Sheet │ embed   │  Canvas 2D   │
│  .aseprite  │ ──────→ │  PNG + JSON  │ ──────→ │  drawImage() │
│  (每角色1檔) │  export │  (每角色1組)  │ go:embed│  source rect │
└─────────────┘         └──────────────┘         └──────────────┘
```

**為什麼用 Sprite Sheet 而非散裝檔案：**

- 散裝 150+ 張 = 150+ 次 `Image()` 建構，效能浪費
- Sprite Sheet 每角色 1 張 PNG + 1 份 JSON = 3 次載入搞定所有角色
- 創作時仍可用多檔案 — Aseprite 負責打包

### 工具比較

| 工具 | 價格 | 動畫標籤 | CLI 自動化 | 推薦度 |
|------|------|---------|-----------|--------|
| **Aseprite** | $20 一次性 | 一流 | 完整 CLI + Lua | 業界標準 |
| **Pixelorama** | 免費開源 | 支援 | 無 CLI | 零預算替代 |
| Piskel | 免費 | 無標籤 | 無 | 只適合草稿 |
| LibreSprite | 免費 | 基本 | 不成熟 | 不推薦 |

### Aseprite 工作流

```bash
# 每個角色 = 1 個 .aseprite 檔，內含 animation tags:
#   idle (2 frames), walk (4 frames), type (2 frames), think (1), wait (1), error (1)
# × 3 directions: down, up, right

# 一鍵匯出：
aseprite -b sprites/char_claude.aseprite \
  --sheet sprites/out/char_claude.png \
  --sheet-type rows \
  --data sprites/out/char_claude.json \
  --format json-array \
  --list-tags \
  --trim
```

產出：
- `char_claude.png` — 一張大圖含所有幀
- `char_claude.json` — Aseprite JSON Atlas，含 `frameTags` 陣列

### 零預算替代方案

1. 用 Pixelorama（免費）繪製 sprite
2. 手動排列成 sprite sheet（統一 cell 大小如 16×16）
3. 手寫 JSON manifest（格式見下方）

---

## 4. 資料結構設計

### 評估過的三個方案

| 方案 | 概念 | 優點 | 缺點 |
|------|------|------|------|
| A. Aseprite JSON Atlas | 直接用 Aseprite 匯出格式 | 零手寫 | 綁定 Aseprite |
| **B. 自訂 Manifest** | 工具無關的 JSON 定義 | 靈活、簡單 | 需手寫或腳本轉換 |
| C. 檔案命名約定 | 目錄結構自動推斷 | 最簡 | Go embed 無法動態掃描 |

### 推薦：方案 B — 自訂 Manifest

理由：
- 不綁定特定工具（Aseprite / Pixelorama / 手畫皆可）
- 一份 `manifest.json` = 所有 sprites 的 single source of truth
- 可從 Aseprite JSON 自動轉換（寫個小腳本）
- Runtime 解析簡單

```typescript
// sprites/manifest.json 對應的 TypeScript 型別

interface SpriteManifest {
  version: 1;
  characters: Record<string, CharacterDef>;
  furniture: Record<string, FurnitureDef>;
}

interface CharacterDef {
  sheet: string;                    // "char_claude.png"
  cellWidth: number;                // 16
  cellHeight: number;               // 16
  directions: ('down' | 'up' | 'right')[];  // left = mirror right
  animations: Record<AnimKey, {
    row: number;                    // sprite sheet 的第幾行
    frames: number;                 // 幀數
    fps: number;                    // 播放速度
  }>;
}

interface FurnitureDef {
  file: string;                     // "furn_desk.png"
  width: number;                    // tiles
  height: number;
}
```

### Aseprite JSON Atlas（參考）

Aseprite 匯出的 JSON 已含所有資訊，可直接解析或轉換為上述 Manifest：

```typescript
interface AsepriteAtlas {
  frames: {
    filename: string;
    frame: { x: number; y: number; w: number; h: number };
    duration: number;
  }[];
  meta: {
    frameTags: { name: string; from: number; to: number; direction: string }[];
    size: { w: number; h: number };
  };
}
```

---

## 5. 管理頁面

| 方案 | 開發成本 | 適用場景 |
|------|---------|----------|
| **Aseprite 本身** | $20 | 單人開發，Aseprite 就是管理工具 |
| **Sprite Preview 面板** | 4-8h | Agent Vista edit mode 加預覽/測試 |
| **完整管理後台** | 40-80h | 多人團隊、sprite 商城 |

**結論**：先不做獨立管理頁面。Aseprite 本身 = 創作 + 管理工具。
後續可在 Agent Vista edit mode 加一個「Sprite Preview」面板。

---

## 6. 實作計畫

### Step 1：Sprite Loader + Manifest（核心基建）

**新增檔案：**
- `frontend/src/sprites/loader.ts` — 載入 sprite sheet + manifest
- `frontend/src/sprites/manifest.json` — sprite 定義

**修改檔案：**
- `frontend/src/sprites/custom.ts` — 整合新 loader

```typescript
// loader.ts 核心 API
export function loadSpriteManifest(): Promise<SpriteManifest>;

export function getCharacterFrame(
  cliType: string,
  animKey: AnimKey,
  direction: Direction,
  frameIdx: number,
): { img: HTMLImageElement; sx: number; sy: number; sw: number; sh: number } | null;

export function getFurnitureSprite(
  type: string,
): HTMLImageElement | null;
```

### Step 2：替換 Renderer 繪製邏輯

**修改檔案：**
- `frontend/src/engine/Renderer.ts` — 修改 `drawCharacter()` + `drawFurniture()`

邏輯：
```typescript
// drawCharacter() 中：
const frame = getCharacterFrame(cliType, animKey, dir, fsm.frameIdx);
if (frame) {
  // PNG sprite path — 直接繪製
  ctx.drawImage(frame.img, frame.sx, frame.sy, frame.sw, frame.sh, dx, dy, dw, dh);
} else {
  // Fallback — 程序化精靈（永遠保留）
  this.drawCharacterProgrammatic(fsm, ...);
}
```

### Step 3：Aseprite 匯出自動化（可選）

**新增檔案：**
- `sprites/Makefile` — 自動化匯出
- `sprites/convert-aseprite.sh` — Aseprite JSON → manifest.json 轉換

```makefile
# sprites/Makefile
CHARACTERS = claude codex gemini

all: $(CHARACTERS:%=out/char_%.png) manifest.json

out/char_%.png: char_%.aseprite
	aseprite -b $< --sheet $@ --data out/char_$*.json \
	  --format json-array --list-tags --trim

manifest.json: $(CHARACTERS:%=out/char_%.json)
	node scripts/gen-manifest.js $^ > $@
```

---

## 7. 遷移路線圖

```
現在（已有）                      Step 1                    Step 2
┌─────────────┐              ┌──────────────┐          ┌──────────────┐
│ 程序化精靈    │              │ + Loader +    │          │ Renderer 整合  │
│ 10×14 陣列   │  ──新增──→   │   Manifest    │  ──替換→ │ PNG 優先       │
│ templates.ts │              │   loader.ts   │          │ 程序化 fallback │
└─────────────┘              └──────────────┘          └──────────────┘
        │                                                       │
        └──── 保留為 fallback（永遠不刪）────────────────────────┘
```

Step 1 + 2 預估工時：6-10 小時。Step 3 是錦上添花的自動化。

---

## 8. 驗證清單

1. `make build-all` 後載入 Agent Vista
2. 角色使用 PNG sprite 渲染（確認圖片正確載入）
3. 切換動畫狀態：IDLE → TYPE → WALK → 確認幀切換流暢
4. 方向測試：角色朝 4 個方向移動（left = right 翻轉）
5. Fallback 測試：刪除某 CLI 的 sprite sheet → 確認降級到程序化精靈
6. 家具測試：確認 PNG 家具取代程序化家具
7. 效能：確認 FPS 無下降（sprite sheet 載入一次，cache 有效）

---

## 附錄：現有 Sprite 素材

`sprites/` 目錄已有 17 張 PNG：

**角色（10×14 px）：**
- `char_claude_idle.png` / `char_claude_typing.png`
- `char_codex_idle.png` / `char_codex_typing.png`
- `char_gemini_idle.png` / `char_gemini_typing.png`

**家具：**
- `furn_desk.png` — 桌子（含螢幕）
- `furn_plant.png` — 盆栽
- `furn_sofa.png` — 沙發
- `furn_bookshelf.png` — 書架
- `furn_whiteboard.png` — 白板
- `furn_coffee.png` — 咖啡機
- `furn_server.png` — 伺服器機架
- `furn_lamp.png` — 檯燈
- `furn_rug.png` — 地毯
- `furn_clock.png` — 時鐘
- `furn_window.png` — 窗戶
