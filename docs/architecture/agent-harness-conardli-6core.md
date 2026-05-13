# Agent Harness 六核心（ConardLi）↔ Workshop 對照表

## 背景

「Harness 六核心」是 [ConardLi](https://github.com/ConardLi) 在 [easy-agent](https://github.com/ConardLi/easy-agent) 開源 Claude Code 重建項目所提出的扁平化心智框架，把一個成熟的 agent harness 拆成六個職責切片：

```
┌────────────────────────────────────────────────────────────┐
│        一個成熟的 Harness 包含六個核心                       │
├──────────────┬──────────────┬──────────────────────────────┤
│ 01 上下文管理 │ 02 工具系統   │ 03 執行編排                   │
│  模型看到了   │  模型能做     │  模型下一步                   │
│  什麼         │  什麼         │  該做什麼                     │
├──────────────┼──────────────┼──────────────────────────────┤
│ 04 狀態與記憶 │ 05 評估與觀測 │ 06 約束與恢復                 │
│  跨步驟連續性 │  做得對不對   │  出錯怎麼辦                   │
│               │               │  怎麼避免跑偏                  │
└──────────────┴──────────────┴──────────────────────────────┘
```

> 📌 **這跟 [12 元素對照表](./agent-harness-comparison.md)（Avi Chawla 框架）是不同切法**。
> 12 元素是「結構切片」（內圈 Runtime / 中圈 Capabilities / 外圈 Safety），ConardLi 6 核心是「職責切片」（看到什麼 / 能做什麼 / 下一步做什麼 / 跨步連續性 / 對不對 / 出錯怎麼辦）。兩者互補，不互斥。

來源：ConardLi YouTube 影片「Easy Agent — 從零復刻 Claude Code 的 Harness」+ easy-agent README 五層架構。

## 與其它框架的軸向對應

| ConardLi 6 核心 | Avi Chawla 12 元素 | Anthropic 三層虛擬化 |
|---|---|---|
| 01 上下文管理 | Context Management | （隸屬 Harness） |
| 02 工具系統 | Tools | （隸屬 Harness） |
| 03 執行編排 | Orchestration Loop + Subagent Orch | **Harness** |
| 04 狀態與記憶 | Memory + State Management | **Session** |
| 05 評估與觀測 | Verification Loops + (新軸: Observability) | （隸屬 Harness） |
| 06 約束與恢復 | Guardrails & Safety + Error Handling | **Sandbox** |

## 六核心 ↔ Workshop 對照

### 01 · 上下文管理（模型看到了什麼）

| Workshop 元件 | 角色 | 說明 |
|---|---|---|
| `~/.claude/CLAUDE.md` + `~/workshop/CLAUDE.md` | 系統指引 | 全域 + 專案級規則 |
| `~/.claude/rules/*.md` | 行為規範 | 17 條規則，含 context-optimization / bash-safety / agents / model-policy |
| `memvault` cascade recall | 語意檢索 | PPR + triples + blocks 三層 |
| `context-supervisor` | 監控 | 三層 context 健康度監控 |
| micro-compact hook | 自動清理 | 每輪自動把 >3 輪前的 tool_result 壓縮成 placeholder |
| `MEMORY.md` 索引 | 入口 | <200 行 index 指向 topic files |

**評等**：🟢 強。

### 02 · 工具系統（模型能做什麼）

| Workshop 元件 | 角色 | 說明 |
|---|---|---|
| `mcp/` 23 servers | MCP 標準工具 | finance, intelflow, memvault, capture, paper, sentinel, fleet, ocr, tts, stt, vision, video-edit... |
| `libs/sdk-client/` 38 clients | Python SDK | 統一 API 客戶端 |
| `core/cli/` | CLI wrappers | 17 個 core 模組 CLI |
| `stations/` 19 stations | 獨立工具站 | hook-observatory, session-channel, anvil, agent-metrics... |
| `cli-rosetta` | 跨 CLI 差異字典 | 聲明式 CLI 差異，Board 自動消費 |
| `mcpproxy-go` | 工具路由 | retrieve_tools 動態發現 |

**評等**：🔵 招牌。

### 03 · 執行編排（模型下一步該做什麼）

| Workshop 元件 | 角色 | 說明 |
|---|---|---|
| `~/.claude/agents/*.md` 15 個 agents | 特化 sub-agent | explorer / worker / reviewer / writer / designer / media / researcher / browser / foreman / tracer / chaos-engineer / dispatchers |
| `forge` skill | 全流程編排 | brainstorming → spec → blueprint → execute → verify |
| `maestro` skill | 多 CLI 編排 | Claude / Codex / Gemini 智慧分派 |
| `team-tasks` skill | DAG / Pipeline / Debate | 多 agent 編排 |
| `tmux-relay` (Tier 3) | pane pool + signal | 完整 skill/MCP/tool 繼承 |
| `Fleet` 跨機 dispatch | HTTP callback + poll fallback | 跨機器 |
| `nodeflow` (已 shelved) | DAG runtime | 待重啟方案 |

**評等**：🟢 強，但 **Workshop 不擁有自己的 agent loop**（借自 Claude Code / Codex / Gemini）。詳見 [12 元素 doc § 缺口診斷 § Orchestration Loop](./agent-harness-comparison.md#1-orchestration-loop-🟡)。

### 04 · 狀態與記憶（跨步驟連續性）

| Workshop 元件 | 角色 | 說明 |
|---|---|---|
| `memvault` | 長期記憶 | bitemporal KG + auto_evolve + dream loop (每日 4AM) |
| `session-archiver` | session 持久化 | 完整對話保存 |
| `session-channel` | 跨 pane state | pub/sub bus on localhost:10101，broadcasts/handoffs/tasks 三 topic |
| `capture` module | 短期捕獲 | 自然語言 universal intake |
| `intelflow` | 中期報告 | 主題索引情報 |
| `handoff` skill | context 接力 | 萃取 5 大欄位寫 HANDOFF-{ts}.md → publish handoffs topic |
| Frontend: TanStack Query + zundo + ActionJournal | 前端 state | Reactive Protocol 七概念統一合約 |

**評等**：🔵 招牌。memvault 的雙時態 + dream loop + AttnRes intent-dependent scoring 是業界級。

### 05 · 評估與觀測（做得對不對）

**驗證 (Verification)**：

| Workshop 元件 | 角色 |
|---|---|
| `sentinel` station | light check (HTTP) + deep check (Playwright) |
| `verification-before-completion` skill | 完成前硬性檢查 |
| `skill-tester` + `eval` skill (archived) | pass@k 評估 |
| `auto-survey` | 測驗答案策略 |
| `code-review-interceptor` | 邊寫邊審 |
| `ultrareview` | 多 agent cloud review |

**觀測 (Observability)**：

| Workshop 元件 | 角色 |
|---|---|
| `hook-observatory` | hook 事件追蹤 + bash safety |
| `agent-metrics` | agent 行為 metrics |
| `agent-vista` | 視覺化 |
| OpenTelemetry + LGTM (dev) / SigNoz (prod) | infra observability |
| `session-intelligence` | session 分析 |

**評等**：🟢 強。觀測軸是 Workshop 完整的；驗證軸有多工具但無統一閘門。

### 06 · 約束與恢復（出錯怎麼辦 + 怎麼避免跑偏）

**約束 (Constraints / Safety)**：

| Workshop 元件 | 角色 |
|---|---|
| `hook-dispatcher` (Go) | 唯一真相源，所有 hook 邏輯 |
| `permissions.deny` (substring，main agent) | Layer 1 |
| `hook-observatory/bash_safety.py` (regex，含 sub-agents) | Layer 2 |
| Backend RBAC + ABAC | `require_permission` + `enforce_policy` |
| SSRF guard / OAuth redirect 驗證 | 系統邊界 |
| `sandbox-executor` station | 沙盒執行 |
| `session-redactor` | 敏感資訊脫敏 |

**恢復 (Recovery / Resilience)**：

| Workshop 元件 | 角色 |
|---|---|
| `WorkshopError` 階層 | NotFoundError / ForbiddenError / ConflictError / BadRequestError |
| `resilience-patterns` (7 模式) | retry / timeout / fallback / circuit / bulkhead / cache / degrade |
| Middleware degrade | Redis/DB 失敗時優雅降級 |
| `chaos-engineer` agent | 故障注入測試 |
| Fleet 30s poll fallback | push 失敗時兜底 |
| `session-channel` at-least-once + 冪等 | 消息可靠性 |

**評等**：🔵 招牌。雙層防禦 + 7 resilience pattern + 故障注入是業界級。

## 缺口診斷（與 12 元素 doc 互補）

12 元素 doc 已指出：**Orchestration Loop / Prompt Construction / Prompt Loops 是 🟡 中**。ConardLi 6 核心切法下，缺口主要在：

### A · 03 執行編排（Loop 自治權）

承襲 12 元素 doc 結論：Workshop 內部不擁有 agent loop，借自 CLI。要做 24/7 守人模式需補。

### B · 05 評估與觀測（驗證與觀測沒收斂在同一面板）

- **驗證工具**散在 sentinel / verification-before-completion / skill-tester / ultrareview，沒有統一儀表板回答「這個 agent 任務做完了沒、做得對不對」
- **觀測工具**hook-observatory + agent-metrics + agent-vista 已強，但與**驗證結果**沒有自動聯動
- 機會：把「verification pass/fail 事件」publish 到 hook-observatory，讓觀測層能繪出「驗證通過率隨時間變化」

### C · 06 約束與恢復（恢復策略沒有全局視圖）

- 個別模組有 resilience（Redis 降級、Fleet poll fallback...）
- 沒有「全局健康度 → 自動切換降級策略」的決策層
- 機會：讓 sentinel 不只 detect + alert，加上 auto-remediation 決策 loop

## 設計取捨對照

| 維度 | ConardLi easy-agent | Workshop |
|---|---|---|
| **自有 agent loop？** | ✅ 有（agenticLoop.ts + queryEngine.ts） | ❌ 借 CLI（Claude Code / Codex / Gemini） |
| **單一語言？** | TypeScript only | Python 主 + TS frontend + Go infra |
| **目標** | 從零復刻 Claude Code | 個人 Modular Monolith + 多 CLI 整合 |
| **核心引擎** | 自己寫 | 不蠶食引擎（cannibalize 原則） |

Workshop 的取捨明確：**不蓋自己的 loop**，把 loop 外包給 CLI；workshop 只當 Memory + Tools + Guardrails 的供應商。

## 何時參考 ConardLi 6 核心 vs Avi Chawla 12 元素

| 場景 | 用哪個 |
|---|---|
| 入門對齊「agent 系統長什麼樣」 | **ConardLi 6 核心**（更扁平、更直覺） |
| 評估 Workshop 哪些元件已收斂、哪些缺 | **Avi Chawla 12 元素**（更細，已有評等） |
| 跟用戶/同事解釋系統職責 | **ConardLi 6 核心** |
| 內部架構審查 / refactor 規劃 | **Avi Chawla 12 元素** |

## 參考連結

- [ConardLi/easy-agent](https://github.com/ConardLi/easy-agent) — 從零復刻 Claude Code 的 TypeScript 開源項目（已完成 stage 1-18）
- [Workshop: 12 元素對照表 (Avi Chawla)](./agent-harness-comparison.md) — 配套文檔
- [Anthropic — Harness Design for Long-running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic — Managed Agents](https://www.anthropic.com/engineering/managed-agents)

## Cannibalization Note

蠶食自 ConardLi 的概念框架（非 code）。執行原則：**只取設計模式不取引擎**。easy-agent 本身是 Claude Code 重建（核心引擎），Workshop 已用 Claude Code，所以**不蠶食 code**；蠶食的是「六核心職責切片」這個更扁平化的心智模型，補位 Workshop 既有的 12 元素文檔。
