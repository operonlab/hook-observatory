# Sprite System v2 — Hatchery 接管 Atlas 標準

> 狀態：**規劃中** | 日期：2026-05-11
> 前置：v1 (`sprite-system-v1.md`) — 已規劃但未實作的 sprite sheet + manifest 結構
> 來源：蠶食自 OpenAI `hatch-pet` skill（MIT，2026-05-11 snapshot）

## 背景變化

v1 規劃了 sprite sheet + manifest，但內容生產（150-220 幀繪製）卡住了：
- 依賴 Aseprite ($20) 手繪 — 工時不可控
- 17 張靜態散圖只覆蓋 idle/typing 2 種狀態 × 3 CLI，動畫幀缺 90%
- 沒有 identity 一致性保障，新增 agent persona 要重畫一輪

v2 引入 `~/.claude/skills/agent-hatchery` 接管內容生產：用 AI 生圖 + deterministic QA pipeline 自動孵化每個 agent 的完整 sprite atlas。Vista 只負責「消費 atlas + 渲染」。

## 核心決策

### 1. Atlas Geometry — 採 hatch-pet 8×9 標準

固定 1536×1872 px atlas / 8 cols × 9 rows / 192×208 per cell。

理由：
- 與 Codex 桌寵體系相容（未來可橋接）
- 9 row 涵蓋 agent-vista 所有需要的狀態（含未來擴充）
- Cell 比例 192×208（略高於正方形）容得下抬手揮舞等高姿勢
- Hatchery 出來的 atlas 直接 drop-in

對應細節見 `~/.claude/skills/agent-hatchery/references/atlas-spec.md`。

### 2. FSM 擴充 — 6 → 8 種狀態

| 既有 FSM | Atlas row | 備註 |
|---|---|---|
| IDLE | 0 `idle` | 直接 |
| WALK (right) | 1 `running-right` | 既有 4 方向 → 水平 2 直接，垂直 2 由 render rotate |
| WALK (left) | 2 `running-left` | 直接 |
| TYPE | 7 `running` | hatch-pet `running` 是「工作中 loop」非腳跑 |
| THINK | 8 `review` | 「focused inspecting」 |
| WAIT | 6 `waiting` | 直接 |
| ERROR | 5 `failed` | 直接 |

**新增**：

| 新 FSM | Atlas row | 觸發 | 行為 |
|---|---|---|---|
| GREET | 3 `waving` | Agent spawn / new session detected | Play once on entry, then auto → IDLE |
| CELEBRATE | 4 `jumping` | Task completed (commit/PR merge/test pass) | Play once, then auto → IDLE |

GREET / CELEBRATE 是 **transient** 狀態（play-once），不 loop。Renderer 一輪 cycle 結束自動回 IDLE。

### 3. 4 方向 WALK 處理

| 方向 | v2.0 做法 | v2.1+ |
|---|---|---|
| right | row 1 直接用 | - |
| left | row 2 直接用 | - |
| down | row 1 render 時旋轉 90° | atlas 擴充 row 9 (running-down) |
| up | row 1 render 時旋轉 90° 反向 | atlas 擴充 row 10 (running-up) |

v2.0 先用 render rotation — 像素 chibi 旋轉看起來尚可。v2.1 視效果決定要不要擴 atlas（會 break Codex pet 相容）。

### 4. 內容生產：Hatchery skill 接管

```
創作端                              消費端
┌──────────────────┐               ┌──────────────────┐
│ agent-hatchery   │  avatar.json  │  agent-vista     │
│ ─ AI 生圖 pipe   │ + atlas.webp  │  sprite loader   │
│ ─ 9 row QA       │ ─────────────→│  ─ row+frame idx │
│ ─ identity lock  │               │  ─ Canvas 2D     │
│ ─ contact sheet  │               │                  │
└──────────────────┘               └──────────────────┘
        ↑                                  ↑
   少爺啟動 hatch                    Renderer 載入 avatar
   提供 reference                   程序化精靈作為 fallback
```

Hatchery 路徑：`~/.claude/skills/agent-hatchery/`
產出位置：`~/workshop/stations/agent-vista/frontend/src/sprites/avatars/<agent-slug>/`

每個 avatar 一個資料夾：
```
sprites/avatars/
├── claude/
│   ├── avatar.json       # manifest
│   └── spritesheet.webp  # 1536×1872 atlas
├── codex/
│   ├── avatar.json
│   └── spritesheet.webp
├── gemini/
│   ├── avatar.json
│   └── spritesheet.webp
└── ...
```

## avatar.json Schema

```typescript
interface AvatarManifest {
  schema: "agent-vista/sprite-v2";
  slug: string;              // "claude", "codex", "gemini", "worker-bot"
  display_name: string;      // "Claude"
  description: string;       // one-line
  atlas: {
    file: string;            // "spritesheet.webp"
    width: 1536;
    height: 1872;
    columns: 8;
    rows: 9;
    cell_width: 192;
    cell_height: 208;
  };
  rows: AvatarRow[];
  generated: {
    hatchery_version: string;     // "agent-hatchery/v1"
    run_dir: string;              // provenance
    canonical_base: string;       // path to base ref used
    adapter: string;              // "manual_handoff" | "openai_image_api" | ...
    created_at: string;           // ISO 8601
  };
}

interface AvatarRow {
  row_index: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
  state: AtlasState;       // "idle" | "running-right" | ... (9 atlas states)
  fsm_state: FsmState;     // "IDLE" | "WALK_RIGHT" | "GREET" | ...
  used_columns: number;    // 4-8
  frame_durations_ms: number[];  // length == used_columns
  loop: boolean;           // false for GREET/CELEBRATE (play-once)
}
```

`frame_durations_ms` 直接內嵌在 manifest 裡，渲染器不用查表。

## Loader API (frontend/src/sprites/loader-v2.ts)

```typescript
// 載入單一 avatar 的 atlas 圖 + manifest
export async function loadAvatar(slug: string): Promise<LoadedAvatar | null>;

interface LoadedAvatar {
  manifest: AvatarManifest;
  image: HTMLImageElement;     // spritesheet.webp 載完
  rowByState: Map<AtlasState, AvatarRow>;
}

// 取指定 (cliType, fsm_state, frame_idx) 的 sprite 區域
export function getAvatarFrame(
  avatar: LoadedAvatar,
  fsmState: FsmState,
  frameIdx: number,
): { sx: number; sy: number; sw: number; sh: number } | null;

// 取 reduced-motion 靜態圖（idle row 0, frame 0）
export function getStaticFrame(avatar: LoadedAvatar): {
  sx: number; sy: number; sw: number; sh: number;
};

// 啟動：批次預載所有 avatars（manifest.json index 列出可用 slug）
export async function preloadAllAvatars(): Promise<Map<string, LoadedAvatar>>;
```

Renderer 改寫（`engine/Renderer.ts`）：

```typescript
drawCharacter(fsm: CharacterFsm, ...) {
  const avatar = this.avatars.get(fsm.cliType);
  if (avatar) {
    const frame = getAvatarFrame(avatar, fsm.state, fsm.frameIdx);
    if (frame) {
      ctx.drawImage(avatar.image, frame.sx, frame.sy, frame.sw, frame.sh, dx, dy, dw, dh);
      return;
    }
  }
  // Fallback: programmatic sprite (sprite-system-v1, 永遠保留)
  this.drawCharacterProgrammatic(fsm, ...);
}
```

## 遷移路線圖

```
現在（v1 已部分實作）        v2.0                      v2.1（之後）
┌─────────────────┐         ┌────────────────────┐    ┌──────────────────┐
│ 程序化精靈 +     │         │ Hatchery 孵化 3 個  │    │ 11-row atlas      │
│ 17 張散圖        │  Step 1 │ baseline avatar     │    │ 加 running-up/down │
│ (idle/type only) │ ──────→│ (claude/codex/gem)  │ → │ 真 4 方向 walk    │
│                  │         │ + loader-v2 + render│    │                   │
│ sprite-system-v1 │  Step 2 │ FSM 擴充 GREET/CEL  │    │ atlas v3 (?)      │
│ manifest 結構    │         │                     │    │                   │
└─────────────────┘         └────────────────────┘    └──────────────────┘
         │                          │                           │
         └──── 程序化精靈作為 fallback 永遠保留 ─────────────────┘
```

### Step 1 — Hatchery baseline 三隻

孵化 `claude` / `codex` / `gemini` 三個基線 avatar。每隻：

1. 用 `prepare_hatchery_run.py` 起 run dir
2. 跑 base + 9 row（adapter = manual_handoff，少爺挑 provider）
3. `validate_atlas.py` 過 → `finalize` → `package_avatar.py`
4. drop 進 `frontend/src/sprites/avatars/<slug>/`

預估工時：每隻 1-2 小時（含 provider 等待 + 視覺驗收 + repair loop），三隻 4-6 小時。

### Step 2 — Loader v2 + Renderer 改寫

新增：
- `frontend/src/sprites/loader-v2.ts`
- `frontend/src/sprites/avatars/manifest.json`（index of available avatars）

修改：
- `frontend/src/engine/Renderer.ts` — `drawCharacter()` 加 avatar 分支
- `frontend/src/engine/CharacterFsm.ts` — 加 GREET / CELEBRATE 狀態 + 轉換邏輯

預估工時：4-6 小時。

### Step 3 — FSM 觸發整合

- spawn event → GREET
- task completion event (commit / PR merge / test pass) → CELEBRATE
- 已有的 IDLE/WALK/TYPE/THINK/WAIT/ERROR 轉換邏輯沿用

預估工時：2-3 小時（看現有 event 介接複雜度）。

## 與 v1 的關係

v1 文件（`sprite-system-v1.md`）**保留**作為以下用途：

1. **Fallback 規範** — 程序化精靈邏輯永遠當 v2 的 fallback path
2. **Manifest 結構參考** — v1 的 TypeScript types 是 v2 schema 的起點
3. **Aseprite workflow** — 如果未來想手繪而非 AI 生圖，v1 的 Aseprite pipeline 仍有效

v2 是「內容生產方式」的升級，不是 v1 的全盤替換。

## 不在 v2 範圍

下列暫不做：
- **家具 sprite atlas 化** — 17 張家具圖維持散裝（單幀，無動畫，atlas 化無收益）
- **天使（sub-agent）sprite** — 不孵新 atlas，沿用既有實作
- **語音氣泡 / spawn 特效** — 與 sprite 系統正交
- **Layout 編輯器** — 與 sprite 系統正交
- **Sprite preview 面板（vista edit mode）** — 可在 hatchery 端用 contact sheet 看；vista 端先不開

## 驗證清單

1. `make build-all` 後 vista 載入 → 三 baseline avatar PNG sprite 渲染正常
2. FSM 切換：IDLE → TYPE → WALK → THINK → WAIT → ERROR → 確認 frame 順暢
3. GREET / CELEBRATE 觸發後 play-once → 自動回 IDLE
4. 方向測試：4 方向 WALK 看起來 OK（render rotate 可接受？）
5. Fallback 測試：刪 codex avatar → 確認降級程序化精靈
6. Identity 一致性：claude 在不同狀態臉長一樣（hatchery QA 應該已保證）
7. 效能：FPS 不下降（spritesheet 載一次，cache 有效）

## 蠶食 Provenance

來源：openai/skills `.curated/hatch-pet` (MIT, 2026-05-11)
url: https://github.com/openai/skills/tree/main/skills/.curated/hatch-pet

蠶食的「設計模式」（不蠶食引擎）：
- 8×9 atlas geometry 標準
- 9 row state 命名 + duration 表
- Identity Lock（canonical base + grounding）
- Layout guide 構造引導圖
- Deterministic QA pipeline（validation.json + contact sheet + animation videos）
- Repair loop（row-level regen）
- Subagent row generation pattern
- Visible progress checklist
- Transparency / effects 規則

**沒有**蠶食的部分：
- OpenAI `$imagegen` 生圖引擎 → 改用 image-prompt skill + 手動 provider
- Codex `pet.json` packaging → 改用 `avatar.json` 對齊 vista
- OpenAI subagent API → 改用 Claude Code Agent tool

詳見 `~/.claude/skills/agent-hatchery/SKILL.md`。
