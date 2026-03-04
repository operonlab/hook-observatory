---
doc_version: 4
content_hash: pending
source_version: 4
target_lang: zh-TW
translated_at: 2026-02-23
---

# 文件管理

## 混合模式：集中式 + 分散式

### 集中式 (`docs/`)

跨網域、系統層級的文件，適用於整個平台。

```
docs/
├── README.md                        # 頂層入口索引
├── architecture/                    # 系統架構（ADR、設計模式、技術規格）
│   ├── README.md                    # 架構文件索引
│   ├── architecture-decisions.md    # 11 項 ADR
│   ├── modular-monolith.md          # 後端架構指南
│   ├── composite-architecture.md    # SDK→CLI→MCP→Skill 四層架構
│   ├── event-driven.md              # 事件驅動架構
│   ├── event-resilience-patterns.md # 6 個事件韌性模式
│   ├── frontend.md                  # 前端架構指南
│   ├── frontend-design-system.md    # 色彩系統 + 模組主題
│   ├── ux-shell-redesign.md         # App Launcher 架構
│   ├── widget-manifest-spec.md      # Widget 系統規格
│   ├── auth.md                      # 認證與權限
│   ├── notification.md              # 通知與橋接
│   ├── communication.md             # 通訊模式
│   ├── plugin-system.md             # Hook/插件系統
│   ├── observability.md             # 可觀測性策略
│   ├── scheduling.md                # 系統排程管理
│   ├── four-tier-data-lifecycle.md  # 熱暖冷冰資料策略
│   ├── shared-layer-patterns.md     # 共享層模式（含軟刪除）
│   ├── folder-structure.md          # 佈局與命名規則
│   ├── tech-stack.md                # 技術選擇
│   ├── rwd-pwa.md                   # RWD + PWA 標準
│   └── principles.md                # 設計原則
├── vision/                          # 平台願景
│   ├── README.md                    # 願景文件索引
│   ├── workshop-manifesto.md        # Workshop 宣言
│   ├── domain-catalog.md            # 服務目錄 + 組合配方
│   ├── composition-model.md         # 樂高組合模型
│   └── roadmap.md                   # 四階段路線圖
├── blueprint/                       # 建設藍圖（各模組實作規格）
│   ├── v1-feature-inventory.md      # V1 功能盤點
│   ├── v2-priorities.md             # V2 優先級矩陣
│   └── p1~p10-*.md                  # 各模組藍圖
├── plans/                           # 戰略計劃（跨模組演進）
│   ├── composite-architecture-roadmap.md  # 四層架構推進計劃
│   └── skill-ecosystem-hardening.md       # Skill 生態加固
├── reference/                       # 參考資料
│   ├── sandbox-executor.md          # Sandbox 執行器規格
│   ├── memvault-kg-research.md      # Memvault KG 研究
│   └── memvault-growth-loops.md     # Memvault 成長飛輪
├── guides/                          # 開發者指南
│   ├── docs-management.md           # 此文件
│   └── feature-lifecycle.md         # POC → 生產工作流
└── lessons/                         # 實戰教訓
    ├── README.md                    # 教訓索引
    ├── frontend-color-system-fix.md # 前端色彩系統修復
    └── hook-observatory-resilience.md  # Hook 韌性模式
```

### 分散式 (按領域)

領域專屬的文件存放在每個模組/服務**內部**的 `README.md`。

```
core/README.md                           ← 如何執行、環境變數、模組概覽
core/src/modules/finance/                ← 程式碼註釋中的模組級別文件
core/services/realtime/README.md         ← Realtime 服務設置
workbench/README.md                      ← 前端開發指南
```

## 東西該放哪？

| 內容 | 位置 | 範例 |
|---------|----------|---------|
| 架構決策與設計模式 | `docs/architecture/` | ADR、事件韌性、複合架構、排程管理 |
| 平台願景 | `docs/vision/` | Workshop 宣言、服務目錄、路線圖 |
| 建設藍圖（各模組實作規格） | `docs/blueprint/` | P1-P10 各模組藍圖、V2 優先級矩陣 |
| 戰略計劃（跨模組演進） | `docs/plans/` | 四層架構推進、熱暖冷冰資料策略 |
| 開發者指南 | `docs/guides/` | 文件管理、功能生命週期 |
| 參考資料（研究與規格） | `docs/reference/` | Sandbox 規格、Memvault KG 研究 |
| 實戰教訓 | `docs/lessons/` | 前端色彩修復、Hook 韌性模式 |
| 模組專屬設置 | `core/README.md` | 核心需要 CORE_DB_URL 環境變數 |
| 共享函式庫用法 | `libs/<lang>/README.md` | 匯入 corelib.db 進行連線 |

## ADR (架構決策紀錄)

對於重大的技術決策，在 `docs/architecture/architecture-decisions.md` 中添加新 ADR：

```markdown
## AD-N: <標題>

**決策**：我們決定了什麼？

**決策理由**：
- 為什麼？有哪些考量？

**限制條件**：
- 有哪些約束或權衡？
```

如果決策內容較長（>50 行），另建獨立檔案放在 `docs/architecture/` 中，並從 ADR 中交叉引用。

## 翻譯工作流 (zh-TW)

### 結構

繁體中文文件是**單一事實來源**（`docs/`），英文版本保留於 `docs-en/` 作為備份。

```
docs/architecture/modular-monolith.md     ← 繁體中文（source of truth）
docs/vision/roadmap.md                    ← 繁體中文（source of truth）
docs-en/architecture/modular-monolith.md  ← 英文備份
```

### 版本追蹤

每個 `.md` 檔案都有帶有版本追蹤的 YAML frontmatter：

```yaml
---
doc_version: 3
content_hash: a1b2c3d4
---
```

- `content_hash`: 檔案內容的 SHA-256（前 8 位十六進位字元）。當內容更改時會變動。
- `doc_version`: 當 `content_hash` 更改時自動遞增。用於檢測翻譯是否過時。

### 翻譯腳本

```bash
# 將所有更改的文件翻譯為 zh-TW (透過 Gemini CLI)
python3 scripts/translate-docs.py

# 檢查哪些文件需要翻譯更新
python3 scripts/translate-docs.py --status

# 測試執行 (顯示將會翻譯的內容)
python3 scripts/translate-docs.py --dry-run

# 僅更新版本號 (不進行翻譯)
python3 scripts/translate-docs.py --version-only

# 強制重新翻譯所有文件
python3 scripts/translate-docs.py --force
```

### 規則

1. **`docs/` 是繁體中文 source of truth** —— 所有編輯直接在 `docs/` 進行
2. **`docs-en/` 是英文備份** —— 需要時由翻譯腳本從 `docs/` 產生
3. **Claude Code 讀取 `docs/`** —— 繁體中文即為主要文件

## 維護規則

1. **隨程式碼更新文件** —— 如果您更改了行為，請在同一個 PR 中更新相關文件
2. **README.md 是強制性的** —— 每個服務和重要的模組都必須有一個
3. **不要留存過時的文件** —— 刪除已移除功能的文件；過時的文件比沒有文件更糟糕
4. **程式碼文件使用英文** —— 技術文件使用英文以確保工具相容性
5. **更改後進行翻譯** —— 在更新任何文件後執行 `python3 scripts/translate-docs.py`
