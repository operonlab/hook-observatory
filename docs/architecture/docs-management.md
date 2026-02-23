---
doc_version: 3
content_hash: 5cdc4d23
source_version: 3
target_lang: zh-TW
translated_at: 2026-02-23
---

# 文件管理

## 混合模式：集中式 + 分散式

### 集中式 (`docs/`)

跨網域、系統層級的文件，適用於整個平台。

```
docs/
├── architecture/        # 系統設計決策
│   ├── modular-monolith.md      # 後端架構指南
│   ├── frontend.md              # 前端架構指南
│   ├── event-driven.md          # 事件驅動架構
│   ├── plugin-system.md         # Hook/插件系統
│   ├── observability.md         # 可觀測性策略
│   ├── auth.md                  # 認證與權限
│   ├── communication.md         # 通訊模式
│   ├── folder-structure.md      # 佈局與命名規則
│   ├── tech-stack.md            # 技術選擇
│   ├── rwd-pwa.md               # RWD + PWA 標準
│   ├── docs-management.md       # 此文件
│   ├── feature-lifecycle.md     # POC → 生產工作流
│   └── adr/                     # 架構決策紀錄
│       └── 001-template.md
├── api/                 # API 設計標準
│   ├── conventions.md         # 命名、版本控制、錯誤格式
│   └── openapi/               # OpenAPI 規格
├── runbooks/            # 運作程序
│   ├── deploy.md
│   ├── rollback.md
│   └── incident-response.md
└── guides/              # 開發者指南
    ├── getting-started.md     # 新開發者入職
    ├── add-new-module.md      # 如何新增領域模組
    └── create-plugin.md       # 如何建立插件
```

### 分散式 (按領域)

領域專屬的文件存放在每個模組/服務**內部**的 `README.md`。

```
core/README.md                           ← 如何執行、環境變數、模組概覽
core/src/modules/finance/                ← 程式碼註釋中的模組級別文件
core/services/realtime/README.md         ← Realtime 服務設置
dashboard/README.md                      ← 前端開發指南
```

## 東西該放哪？

| 內容 | 位置 | 範例 |
|---------|----------|---------|
| 架構決策 | `docs/architecture/` | 「為什麼選擇 Modular Monolith 而非微服務」 |
| API 設計標準 | `docs/api/` | 「所有端點使用 camelCase」 |
| 部署程序 | `docs/runbooks/` | 「如何部署核心服務」 |
| 入職指南 | `docs/guides/` | 「設置開發環境」 |
| 模組專屬設置 | `core/README.md` | 「核心需要 CORE_DB_URL 環境變數」 |
| 插件開發 | `docs/guides/create-plugin.md` | 「如何建置插件」 |
| 共享函式庫用法 | `libs/<lang>/README.md` | 「匯入 corelib.db 進行連線」 |

## ADR (架構決策紀錄)

對於重大的技術決策，請在 `docs/architecture/adr/` 建立 ADR：

```markdown
# ADR-NNN: <標題>

## 狀態
已接受 | 提議中 | 已棄用

## 上下文
是什麼情況促成了這個決策？

## 決策
我們決定了什麼？

## 後果
有哪些權衡？
```

## 翻譯工作流 (zh-TW)

### 結構

英文文件是**單一事實來源**。繁體中文翻譯存放在 `docs/zh-TW/`，並鏡像原始碼樹：

```
docs/architecture/modular-monolith.md     →  docs/zh-TW/architecture/modular-monolith.zh-TW.md
docs/vision/roadmap.md                    →  docs/zh-TW/vision/roadmap.zh-TW.md
CLAUDE.md                                 →  docs/zh-TW/CLAUDE.zh-TW.md
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

1. **永遠不要直接編輯 zh-TW 檔案** —— 它們是由英文來源自動產生的
2. **在文件更改後執行翻譯** —— `python3 scripts/translate-docs.py` 會檢測更改的檔案
3. **Claude Code 讀取英文** —— zh-TW 僅供人類快速閱讀

## 維護規則

1. **隨程式碼更新文件** —— 如果您更改了行為，請在同一個 PR 中更新相關文件
2. **README.md 是強制性的** —— 每個服務和重要的模組都必須有一個
3. **不要留存過時的文件** —— 刪除已移除功能的文件；過時的文件比沒有文件更糟糕
4. **程式碼文件使用英文** —— 技術文件使用英文以確保工具相容性
5. **更改後進行翻譯** —— 在更新任何文件後執行 `python3 scripts/translate-docs.py`
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
