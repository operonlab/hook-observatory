# Workshop 複合架構推進路線圖

> 四層複合架構的定義請見 [composite-architecture.md](../architecture/composite-architecture.md)。
> 本文件聚焦於**實作推進計劃**：哪些服務在何時完成四層升級。

## 背景與目標

Workshop 已有 **21+ 個服務** 完成 SDK 層，其中 17 個有 MCP server，7 個核心模組有 CLI。
原始黃金標準 5 服務（agent-metrics、sandbox-executor、hook-observatory、tmux-relay、memvault）已擴展至大規模覆蓋。

> **2026-03-07 更新**：Wave 1-3 的 SDK 層已全部完成（20+ clients），大部分 MCP 和 CLI 也已到位。
> 剩餘缺口：invest（缺 CLI+MCP）、taskflow/ideagraph（純骨架，待 V2 建設）、anvil（缺 onboarding）。

**目標**: 讓每個有意義的服務都具備 SDK + CLI + MCP + Skill（視需求），確保 Claude Code、外部腳本、人類終端都能統一操作。

---

## 現狀盤點矩陣

### 核心模組 (~/workshop/core/src/modules/)

| 模組 | HTTP API | SDK | CLI | MCP | Skill | 狀態 |
|------|----------|-----|-----|-----|-------|------|
| **finance** | ✅ | ✅ | ✅ | ✅ (3 伺服器, 27 工具) | ✅ | ✅ 完成 |
| **intelflow** | ✅ | ✅ | ✅ | ✅ (2 工具) | ✅ | ✅ 完成 |
| **memvault** | ✅ | ✅ | ✅ | ✅ (8 工具) | ✅ | ✅ 完成 |
| **nodeflow** | ✅ | ✅ | ✅ | ✅ (6 工具) | ✅ | ✅ 完成 |
| **briefing** | ✅ | — | — | — | — | ✅ 生產（獨立 module） |
| **notification** | ✅ | ✅ | ✅ | — | — | ✅ 完成 |
| **auth** | ✅ | ✅ | ✅ | — | — | ✅ 完成 |
| **admin** | ✅ | ✅ | ✅ | — | — | ✅ 完成 |
| **invest** | ✅ | ✅ | ❌ | ❌ | ❌ | ⚙️ 缺 CLI+MCP |
| **taskflow** | 🏗 骨架 | — | — | — | — | 🏗 待 V2 建設 |
| **ideagraph** | 🏗 骨架 | — | — | — | — | 🏗 待 V2 建設 |

### 工作站 (~/workshop/stations/)

| 工作站 | HTTP API | SDK | CLI | MCP | Skill | 狀態 |
|--------|----------|-----|-----|-----|-------|------|
| **sentinel** (4101) | ✅ | ✅ | ✅ | ✅ (5 工具) | ✅ | ✅ 完成 |
| **system-monitor** (9526) | ✅ | ✅ | ✅ | ✅ (4 工具) | ✅ | ✅ 完成 |
| **envkit** | — | ✅ | ✅ | ✅ (4 工具) | ✅ | ✅ 完成 |
| **anvil** (4102) | ✅ | ✅ | ✅ (18 cmd) | ✅ (8 工具) | ✅ | ⚠️ 缺 onboarding |
| **tmux-webui** (9527) | ✅+WS | ✅ | — | ✅ (3 工具) | ✅ | ✅ 完成 |
| **session-archiver** | — | ✅ | ✅ | — | — | ✅ 完成 |
| **session-redactor** | — | ✅ | ✅ | ✅ (5 工具) | ✅ | ✅ 完成 |
| **session-intelligence** | — | ✅ | ✅ | ✅ (6 工具) | ✅ | ✅ 完成 |

*跳過: agent-vista（Go 語言, 獨立生態）*

### 已完成的黃金標準（參考實作）

| 服務 | SDK | CLI | MCP | Skill |
|------|-----|-----|-----|-------|
| agent-metrics | ✅ agent_metrics.py | ✅ maestro.py | ✅ 10 工具 | ✅ maestro |
| sandbox-executor | ✅ sandbox.py | ✅ sandbox.py | ✅ 2 工具 | ✅ sandbox-patterns |
| hook-observatory | ✅ hook_observatory.py | ✅ cso.py | ✅ 3 工具 | — |
| tmux-relay | ✅ tmux_relay.py | ✅ relay.py | ✅ 6 工具 | ✅ tmux-relay |
| memvault | ✅ memvault.py | ✅ memvault.py | ✅ 8 工具 | ✅ memvault |

---

## 架構模式

### 四層複合架構路徑慣例

```
libs/sdk-client/sdk_client/{name}.py    ← SDK（繼承 BaseClient）
stations/{name}/cli/{cmd}.py                   ← Station CLI（合併在 station 內）
core/cli/{name}.py                             ← Core Module CLI（argparse, 匯入 SDK）
mcp/{name}/server.py                           ← MCP（包裝 SDK, stdio 模式）
~/.claude/skills/{name}/SKILL.md               ← Skill（參照 CLI + MCP）
```

### 兩種 SDK 變體

**A. 核心模組 SDK** — 繼承 `BaseClient`（包裝 `/api/{module}/` 端口 8801）：
```python
class FinanceClient(BaseClient):
    def __init__(self, **kwargs):
        super().__init__(module="finance", **kwargs)
```

**B. 工作站 SDK** — 獨立客戶端（包裝工作站自有端口）：
```python
class SentinelClient:
    def __init__(self, base_url=None):
        self.base_url = base_url or os.environ.get("SENTINEL_URL", "http://localhost:4101")
```

### 現有 MCP 升級路徑

現有 MCP 伺服器（finance ×3, taskflow, intelflow）目前使用**原始 httpx** 呼叫。
應**重構為使用 SDK 客戶端**以保持一致性：
```python
# 重構前: 原始 HTTP
async def api_get(path, params): httpx.AsyncClient().get(...)

# 重構後: SDK
from sdk_client.finance import FinanceClient
client = FinanceClient()
```

---

## 第一波 — 高價值日常使用服務（P1）

### 1.1 Finance（SDK + CLI + Skill + MCP 升級）

**SDK** — `libs/sdk-client/sdk_client/finance.py`

| 方法群組 | 方法 |
|----------|------|
| 交易 | list_transactions, get_transaction, create_transaction, update_transaction, delete_transaction, suggest_category |
| 錢包 | list_wallets, get_wallet, create_wallet, sync_wallet, get_snapshots |
| 預算 | list_budgets, create_budget, get_budget_progress |
| 訂閱 | list_subscriptions, create_subscription, toggle_subscription |
| 分析 | monthly_summary, spending_by_category, wallet_trend |
| 分期 | list_installments, create_installment |

**CLI** — `core/cli/finance.py`
```
finance transactions list [--wallet W] [--category C] [--limit N]
finance transactions create <wallet> <title> <amount> [--category C]
finance wallets list | create | sync
finance budgets list | create
finance subscriptions list [--active-only]
finance analytics monthly [--year Y] [--month M]
finance analytics spending [--from 日期] [--to 日期]
```

**Skill** — `~/.claude/skills/finance/SKILL.md`
- 範圍: 交易 CRUD、預算追蹤、訂閱管理、消費分析
- 介面: CLI + MCP（3 個現有伺服器）

**MCP 升級**: 重構 `mcp/finance/server.py`、`mcp/finance-wallet/server.py`、`mcp/finance-analytics/server.py` 改為匯入 `FinanceClient`

**工作量**: SDK ~200 行, CLI ~350 行, Skill ~150 行, MCP 重構 3 檔

---

### 1.2 Taskflow（SDK + CLI + Skill + MCP 升級）

**SDK** — `libs/sdk-client/sdk_client/taskflow.py`

| 方法群組 | 方法 |
|----------|------|
| 任務集 | list_quests, create_quest, update_quest, complete_quest |
| 子任務 | list_tasks, create_task, update_task |
| 派遣 | dispatch_task |
| 獎勵 | claim_reward |

**CLI** — `core/cli/taskflow.py`
```
taskflow quests list [--status S] [--priority P]
taskflow quests create <title> [--priority P] [--due 日期]
taskflow tasks list <quest_id>
taskflow tasks update <id> <status>
taskflow dispatch <task_id> [--agent A]
```

**工作量**: SDK ~120 行, CLI ~250 行, Skill ~100 行, MCP 重構 1 檔

---

### 1.3 Intelflow（SDK + CLI + Skill + MCP 升級）

**SDK** — `libs/sdk-client/sdk_client/intelflow.py`

| 方法群組 | 方法 |
|----------|------|
| 報告 | list_reports, get_report, create_report, search_reports |
| 主題 | list_topics, get_topic_graph |
| 簡報 | list_briefings, get_briefing, generate_briefing |
| 搜尋 | semantic_search |

**CLI** — `core/cli/intelflow.py`
```
intelflow reports list [--topic T] [--limit N]
intelflow reports search <查詢>
intelflow topics list
intelflow briefings list | generate [--topics T1,T2]
```

**工作量**: SDK ~150 行, CLI ~200 行, Skill ~120 行, MCP 完善 + 重構 1 檔

---

### 1.4 Sentinel（SDK + CLI + MCP + Skill 全新建置）

**SDK** — `libs/sdk-client/sdk_client/sentinel.py`（工作站變體）

| 方法群組 | 方法 |
|----------|------|
| 健康 | health, is_running |
| 檢查 | list_checks, get_check, run_check, run_all_checks |
| 修復 | list_remediations, get_remediation_history |
| 總覽 | get_status_summary |

**CLI** — `stations/sentinel/cli/sentinel.py`
```
sentinel status           # 總覽儀表板
sentinel checks list      # 列出所有註冊的檢查
sentinel checks run [名稱] # 執行單一或全部檢查
sentinel history [--limit N]
```

**MCP** — `mcp/sentinel/server.py`（全新, ~5 工具）
**Skill** — `~/.claude/skills/sentinel/SKILL.md`
**工作量**: SDK ~100 行, CLI ~180 行, MCP ~120 行, Skill ~80 行

---

## 第二波 — 基礎設施與知識服務（P2）

### 2.1 Ideagraph（SDK + CLI + MCP + Skill）

**SDK 方法**: list_sparks, create_spark, refine_spark, list_links, suggest_links, create_link, search, get_graph
**CLI**: `core/cli/ideagraph.py`
**MCP**: `mcp/ideagraph/server.py`（全新或完善現有）
**Skill**: `~/.claude/skills/ideagraph/SKILL.md`
**工作量**: SDK ~120 行, CLI ~200 行, MCP ~150 行, Skill ~100 行

### 2.2 Nodeflow（SDK + CLI + MCP + Skill）

**SDK 方法**: list_flows, create_flow, get_flow, add_node, add_edge, run_flow, get_run, list_runs
**CLI**: `core/cli/nodeflow.py`
**MCP**: `mcp/nodeflow/server.py`（全新）
**Skill**: `~/.claude/skills/nodeflow/SKILL.md`
**工作量**: SDK ~130 行, CLI ~250 行, MCP ~180 行, Skill ~120 行

### 2.3 System Monitor（SDK + CLI + MCP）

**SDK 方法**: health, get_metrics, get_disk_report, generate_report, list_reports, get_report
**CLI**: `stations/system-monitor-cli/sysmon.py`
**MCP**: `mcp/system-monitor/server.py`（全新, ~4 工具）
**Skill**: 已有 `system-map` — 更新加入 CLI + MCP 參照
**工作量**: SDK ~80 行, CLI ~150 行, MCP ~100 行

### 2.4 Envkit（SDK + MCP + Skill）

Envkit 是 **CLI 優先**設計（無 HTTP 服務）。SDK 透過 subprocess 包裝 CLI。

**SDK 方法**: snapshot, list_snapshots, diff, collect, list_collectors
**MCP**: `mcp/envkit/server.py`（全新, ~4 工具）
**Skill**: `~/.claude/skills/envkit/SKILL.md`（全新）
**工作量**: SDK ~80 行, MCP ~100 行, Skill ~80 行

---

## 第三波 — 支援服務（P3）

| 服務 | SDK | CLI | MCP | Skill | 說明 |
|------|-----|-----|-----|-------|------|
| notification | ~80 行 | ~120 行 | 跳過 | 跳過 | 內部基礎設施 |
| auth | ~100 行 | ~150 行 | 跳過 | 跳過 | 安全邊界，不暴露給 LLM |
| admin | ~80 行 | ~120 行 | 跳過 | 跳過 | 內部運維 |
| tmux-webui | ~60 行 | — | ~80 行 | 已有 tmux-expert | 僅 REST，跳過 WebSocket |
| session-archiver | ~60 行 | ~100 行 | 跳過 | 跳過 | 批次作業 |

---

## 執行策略

### 並行工作分配

**第一波（P1 — 4 個 workers 並行）**:
| Worker | 目標 | 交付物 |
|--------|------|--------|
| W1 | finance | SDK + CLI + Skill + MCP 重構（3 檔） |
| W2 | taskflow | SDK + CLI + Skill + MCP 重構（1 檔） |
| W3 | intelflow | SDK + CLI + Skill + MCP 完善 + 重構 |
| W4 | sentinel | SDK + CLI + MCP（全新）+ Skill |

**第二波（P2 — 4 個 workers 並行）**:
| Worker | 目標 | 交付物 |
|--------|------|--------|
| W5 | ideagraph | SDK + CLI + MCP（全新）+ Skill |
| W6 | nodeflow | SDK + CLI + MCP（全新）+ Skill |
| W7 | system-monitor | SDK + CLI + MCP（全新）+ Skill 更新 |
| W8 | envkit | SDK（CLI 包裝）+ MCP（全新）+ Skill |

**第三波（P3 — 2 個 workers 並行）**:
| Worker | 目標 | 交付物 |
|--------|------|--------|
| W9 | notification + auth + admin | 3× SDK + 3× CLI |
| W10 | tmux-webui + session-archiver | 2× SDK + 1× CLI + 1× MCP |

### 每個 Worker 的執行流程

1. **安全提交** — 受影響的 repo 先 `git commit`
2. **建立 SDK** — `libs/sdk-client/sdk_client/{name}.py`
3. **建立 CLI** — `stations/{name}/cli/{name}.py`（Station）或 `core/cli/{name}.py`（Core Module）（argparse + 匯入 SDK + chmod +x）
4. **建立/升級 MCP** — `mcp/{name}/server.py`（使用 SDK，不用原始 httpx）
5. **建立 Skill** — `~/.claude/skills/{name}/SKILL.md`
6. **測試** — 匯入驗證 + CLI `--help` + `py_compile`
7. **建立符號連結** — `ln -sf ~/workshop/stations/{name}/cli/{name}.py ~/.local/bin/{name}`（Station）或 `ln -sf ~/workshop/core/cli/{name}.py ~/.local/bin/{name}`（Core Module）

---

## 風險評估

| 風險 | 影響 | 緩解措施 |
|------|------|----------|
| 核心 API 路由與 SDK 方法名不一致 | SDK 呼叫 404 | 撰寫 SDK 前先讀 routes.py 確認端點 |
| MCP 重構破壞現有功能 | Claude Code 無法使用 finance 等 MCP | Git 安全提交 + 逐檔重構 + 測試 |
| 過多 MCP 伺服器佔用 system prompt | Token 浪費 | 僅啟用日常使用的 MCP，其餘按需載入 |
| Skill 數量膨脹 | system prompt 過長 | P3 服務不建 Skill，保持精簡 |
| CLI 符號連結衝突 | 系統指令被覆蓋 | 檢查 `which {name}` 無衝突再建立符號連結 |

---

## 預估總量

| 類別 | 數量 | 預估行數 |
|------|------|----------|
| SDK 客戶端 | 13 | ~1,400 |
| CLI 工具 | 11 | ~2,200 |
| MCP 伺服器（全新） | 4 | ~550 |
| MCP 重構 | 5 | ~-200（簡化） |
| Skills | 7 | ~750 |
| **新增程式碼總計** | **~30 檔** | **~4,900 行** |

---

*建立日期: 2026-03-04*
*版本: v1.0*
*作者: 維恩（Claude Code Opus）*
