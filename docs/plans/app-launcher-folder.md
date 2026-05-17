# App Launcher — Folder & Drag-into Plan

**Status**: Draft (2026-05-17)
**Owner**: 少爺
**Scope**: `workbench/src/pages/Home.tsx`, `useAppOrder.ts`, `apps.ts`, `tools.ts`, `ToolboxPopover.tsx`
**Backend touchpoint**: `core/src/modules/auth/services.py::user_preferences` (additive only)

---

## 1. 目標

把 `/apps/` 從「平面拖曳交換順序」進化為「App + Folder 兩層 launcher」，支援：

1. **拖曳 App 短停頓 (~600ms) 於 Folder 上 → drop-into**（而非交換順序）
2. **拖兩個 App 疊一起 → 自動建 Folder**（iOS 風）
3. **Folder 點擊展開**（沿用既有 ToolboxPopover 動畫）
4. **Folder 內可繼續拖曳排序，可拖出 Folder 回到外層**
5. **單一資料模型 `LauncherItem`** 取代 `AppInfo` + `ToolEntry` 雙軌

## 2. 設計決策（已定案）

| 主題 | 決策 |
|------|------|
| Drop-into 觸發 | 短停頓 ~600ms，folder 邊框高亮 + 微縮放回饋 |
| 資料模型 | 單一 `LauncherItem`，`kind: 'app' \| 'folder'`，`parentId?` 表示父 folder |
| Folder 來源 | 預設（apps.ts 寫死，如 toolbox）+ User 自建（拖兩 app 疊起來） |
| Folder 嵌套 | **不允許** — folder 內只能放 app（簡化心智模型，跟 iOS 一致） |
| 跨 section 拖曳 | 允許（internal ↔ external，僅 reorder；drop-into folder 也允許） |

## 3. 資料模型

### `LauncherItem`（取代 `AppInfo` + `ToolEntry`）

```ts
type LauncherKind = 'app' | 'folder'
type AppSection = 'internal' | 'external' | 'coming-soon'

interface LauncherItem {
  id: string
  kind: LauncherKind
  name: string
  description?: string
  icon: string           // emoji or component slot
  color: string

  // app-only
  path?: string          // internal route
  externalUrl?: string   // external link (站 / station)
  status?: AppSection    // 'coming-soon' 仍適用

  // folder-only
  builtIn?: boolean      // true = 寫死在 apps.ts，user 不能刪
}
```

### 排序儲存（取代現有 `SavedOrder`）

```ts
interface AppLayout {
  version: 2

  // top-level ordering (含 folders + 散裝 apps)
  // 用 section 分組，每組是 ID 陣列
  internal: string[]
  external: string[]

  // folder 內容（folder id → 子 app id 陣列）
  // 同時隱含 parentId：若 app id 出現在某 folder.children，就不會出現在 top-level
  folders: Record<string, string[]>

  // user-created folder 的中繼資料（builtIn folder 不放這）
  userFolders: Record<string, { name: string; icon: string; color: string }>

  hidden: string[]
}
```

**Backward compat**：localStorage 讀到 v1 (`{internal, external, hidden}`) → 自動 migrate 成 v2（所有 user-defined item 都在 top-level，`folders` 空，`userFolders` 空）。Backend preferences 也走同 migrate。

## 4. UX 規格

### 4.1 拖曳狀態機

```
idle ──drag start app──> dragging
  dragging ──hover folder 600ms──> drop-into-armed
  dragging ──hover app──> reorder-armed (current behavior)
  drop-into-armed ──hover off──> dragging
  drop-into-armed ──drop──> add to folder, persist, idle
  reorder-armed ──drop──> swap order, persist, idle
  dragging ──drag end (no drop)──> idle
```

### 4.2 視覺反饋（必做）

| 狀態 | 視覺 |
|------|------|
| `dragging` 中的 app 卡片 | `opacity: 0.4`（沿用） |
| Reorder target | 左邊框換色（沿用） |
| Drop-into-armed folder | 邊框 + `box-shadow: 0 0 0 2px {color}, inset 0 0 0 2px {color}40`；`transform: scale(0.95)` 微縮回饋 |
| Drop-into-armed app（觸發 auto-folder） | 邊框 dashed + glow，提示「放開將建立資料夾」 |
| Folder hover countdown | 邊框環形 progress（0 → 360deg 在 600ms，純 CSS `conic-gradient` + transition） |

### 4.3 自動建 folder（iOS-style）

- 拖 App A 在 App B 上停留 ~600ms → 進入「pre-folder」狀態
- 放開 → 建立 folder：
  - id = `folder-{nanoid(6)}`
  - name = 預設「新資料夾」（雙擊重新命名）
  - icon = `📁`
  - color = `#89dceb`
  - children = [B, A]
- 在 top-level 替換 B 的位置為新 folder id，A 從 top-level 移除

### 4.4 展開 folder

- 沿用 `ToolboxPopover` 動畫（從卡片位置縮放展開）
- Header 顯示 folder name（user folder 可雙擊改名）
- Grid 顯示 children
- **Folder 內也支援拖曳**：
  - 拖排序：交換 folder.children 順序
  - 拖到 folder 邊界外 ~80px → 「即將拖出」視覺 → 放開：app 回到 top-level（插在原 folder 後面）
- 空 folder 自動刪除（非 builtIn）

### 4.5 長按隱藏（沿用）

- App 長按 = 隱藏（沿用）
- Folder 長按 = 隱藏整個 folder（含 children）
  - 從 hidden 復原時，folder 與 children 一起回來

## 5. 元件拆分

### 新增

- `src/shell/launcher/LauncherGrid.tsx` — 取代 `Home.tsx` 內 `DraggableGrid`，支援 drop-into-folder
- `src/shell/launcher/FolderCard.tsx` — folder 卡片（hover countdown ring + drop-into 視覺）
- `src/shell/launcher/AppCard.tsx` — 抽離 `Home.tsx` 內 `AppCard`
- `src/shell/launcher/FolderPopover.tsx` — 由 `ToolboxPopover` 重構而來，泛化支援任意 folder + 內部拖曳
- `src/hooks/useDragController.ts` — 管理 dragging / hover-timer / drop-into-armed 狀態機
- `src/hooks/useLauncherLayout.ts` — 取代 `useAppOrder`，操作 `AppLayout` v2

### 修改

- `src/pages/Home.tsx` — 改用 `LauncherGrid` + `useLauncherLayout`
- `src/shared/constants/apps.ts` — 改為 `LAUNCHER_ITEMS: LauncherItem[]`，將 toolbox 標 `kind: 'folder'`, `builtIn: true`
- `src/shared/constants/tools.ts` — 砍除，內容 merge 進 `LAUNCHER_ITEMS`（每個 tool 變 `kind: 'app'`, `externalUrl` 指原 url），預設 layout 把它們 children 進 `toolbox` folder
- `src/types/index.ts` — `AppInfo` 標記 deprecated，新增 `LauncherItem` 與 `AppLayout`

### 刪除

- `src/shell/ToolboxPopover.tsx` — 由 `FolderPopover` 取代

## 6. 後端

`user_preferences.app_order` (JSONB) 已存在。新增 schema 版本：

- 寫入時 `version: 2`
- 讀取時若無 `version` 或 `version === 1` → migrate to v2 in-memory（不寫回，避免單向同步問題）
- 全部讀寫已透過 `getPreferences()` / `updatePreferences()`，**無 Alembic migration 需求**（JSONB free-form）

## 7. 階段執行（Vertical Slice）

每階段都 end-to-end 可 demo + 測試（遵循 [[../../.claude/rules/coding-discipline.md]] 第 5 條 Vertical Slice）。

### Phase 1 — 資料模型統一（1 PR, ~3h）
- 新增 `LauncherItem` / `AppLayout` types
- `LAUNCHER_ITEMS` 取代 `APP_LIST`，toolbox 變 `kind: 'folder'`, builtIn
- tools merge 進 `LAUNCHER_ITEMS` 並預設掛 toolbox children
- `useLauncherLayout` 平行存在於 `useAppOrder`（feature toggle，預設關）
- v1 → v2 migration 函式 + unit test
- **Demo**: 切 toggle 後，launcher 正常顯示 + toolbox 內仍是原工具集

### Phase 2 — drop-into-folder UX（1 PR, ~5h）
- `useDragController` hover-timer 狀態機
- `FolderCard` countdown ring + drop-into 視覺
- `LauncherGrid` 整合：app drop on folder → 加入 folder.children
- Folder 內透過 `FolderPopover` 顯示，沿用 iOS-style 縮放動畫
- **Demo**: 拖一個 app 到 toolbox 上停留 600ms 後放開 → app 進 toolbox

### Phase 3 — 自動建 folder（1 PR, ~4h）
- App-on-app hover 600ms → 進入 pre-folder 視覺
- Drop → 建 user folder，自動命名「新資料夾」
- Folder 內雙擊 header 改名
- **Demo**: 拖 finance 疊到 taskflow → 自動建 folder，兩者進去

### Phase 4 — folder 內互動完善（1 PR, ~3h）
- Folder 內排序拖曳
- 拖出 folder 回 top-level
- 空 folder 自動刪除
- 長按隱藏整 folder
- **Demo**: 完整 iOS-like folder UX

### Phase 5 — 清理（1 PR, ~1h）
- 移除 `useAppOrder` / `APP_LIST` / `AppInfo` 別名
- 移除 `tools.ts` / `ToolboxPopover.tsx`
- 移除 feature toggle，全量 v2

## 8. 風險與邊界

| 風險 | 緩解 |
|------|------|
| HTML5 DnD 在 Safari iPad 觸控不完整 | 後續若反映再評估 `@dnd-kit/core` 移植；目前先以桌面為主 |
| Hover countdown 視覺 jank | 用 CSS `conic-gradient` + `transition: --p` (CSS @property)；fallback 純 setTimeout + 邊框閃爍 |
| Folder 多到塞滿首頁 | 不在本次處理；未來可加 launcher 搜尋 |
| Preferences 同步 race（多裝置） | 沿用 last-write-wins，user 短時間多裝置編輯極少；後續可考慮 server diff merge |
| Migration v1→v2 失敗 | migration 函式必須 fail-safe（catch → 回傳預設 layout），加 sentry-style log |

## 9. 非目標（本次不做）

- Folder 嵌套（folder 內裝 folder）
- Folder 自訂 icon / color UI（先沿用預設 📁 + `#89dceb`）
- Launcher 搜尋 / 分類 tag
- 跨用戶共享 folder 設定
- 拖曳到「即將推出」區（coming-soon 仍唯讀）

## 10. 驗收條件

- [ ] 拖一個 app 到 toolbox 停 600ms 後放 → app 進 toolbox，刷新後仍在
- [ ] 拖兩個 app 疊起 → 自動建 folder，雙擊 header 可改名
- [ ] Folder 點開後可拖內部 app 排序
- [ ] 拖 folder 內 app 出邊界 → 回 top-level
- [ ] 把 folder 內最後一個 app 拖出 → folder 自動消失（非 builtIn）
- [ ] 跨 section（internal ↔ external）拖曳 reorder OK
- [ ] iPad 觸控長按可拖（HTML5 DnD 限制範圍內）
- [ ] localStorage v1 → v2 自動 migrate，無資料遺失
- [ ] Cmd+R / 重新登入後狀態一致

## 11. 相關記憶 / Rules 連結

- [[../../.claude/rules/coding-discipline.md]] — Vertical Slice (第 5 條)
- [[../../.claude/rules/agents.md]] — 並行 agent worktree base trap（若拆任務委派）
- [[../.claude/rules/dev-patterns.md]] — Frontend 規則（rebuild + Playwright E2E）
- `useAppOrder.ts` — 現有 LWW localStorage + backend sync 範式，本次延用
