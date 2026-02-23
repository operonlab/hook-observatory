---
doc_version: 1
content_hash: 25063671
source_version: 1
translated_at: 2026-02-23
---

# Workshop 願景文件

> 2026-02-23 腦力激盪會議產出 — Workshop 平台願景的完整紀錄。

## 文件

| 檔案 | 內容 |
|------|----------|
| [workshop-manifesto.md](./workshop-manifesto.md) | 什麼是 Workshop、Core/Stations/Bridges 分類法、設計原則 |
| [domain-catalog.md](./domain-catalog.md) | 10 個核心模組 + 5 個專案想法 + 依賴圖 + 分類索引 |
| [architecture-decisions.md](./architecture-decisions.md) | 7 個架構決策紀錄 (ADR)：Monolith, MCP Adapter, Space Model, Widget, Resource, Event, Progressive |
| [roadmap.md](./roadmap.md) | 四階段路線圖：個人 → 知識 → 團隊 → 商業 |

## 翻譯

繁體中文翻譯版本可在 [`zh-TW/`](./zh-TW/) 中找到，以便快速閱讀。
英文版本為單一事實來源 — Claude Code 讀取這些版本。

## 快速參考

### 三層分類法
- **Core Modules**: 以資料庫為後盾的業務領域 (auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin)
- **Stations**: 獨立的本地工具 (disk analyzer, LLM usage, legal advisor, church music)
- **Bridges**: 外部連接器 (LINE, Telegram, Discord, Firebase, external APIs)

### 架構模式
```
Claude Code → MCP Server (adapter) → FastAPI Core (monolith) → PostgreSQL
                                          ↕
Web Dashboard (widgets) ──────────► FastAPI Core
                                          ↕
Social Bridges (LINE/TG/DC) ─────► FastAPI Core
```

### 階段摘要
1. **第一階段**: auth + finance + quest + muse + LINE bot + Widget Dashboard
2. **第二階段**: memory v2 + skill + intel + church music
3. **第三階段**: workforce + task dispatch + 多平台社群
4. **第四階段**: 商業 (ERP/POS/legal/virtual CS)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
