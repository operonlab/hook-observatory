# Agent Harness 12 元素 ↔ Workshop 對照表

## 背景

「Agent Harness」是 Avi Chawla（Daily Dose of Data Science）綜合 Anthropic、OpenAI、LangChain 與業界實踐後提出的視覺化架構，把 agent 系統拆成三圈共 12 個元素：

- **內圈 Runtime**（4）— 引擎本身
- **中圈 Capabilities**（4）— 能做什麼
- **外圈 Safety & Scale**（4）— 怎麼不出事 + 怎麼放大

> ⚠️ 此框架**不是 Anthropic 官方框架**。Anthropic 自己的 harness 論述（`engineering/harness-design-long-running-apps`、`engineering/managed-agents`）是 **session / harness / sandbox** 三層虛擬化，跟這 12 元素是不同切法 — 一個是「結構切片」，一個是「生命週期切片」。

來源：<https://blog.dailydoseofds.com/p/the-anatomy-of-an-agent-harness>

## 對照總覽

| 評等 | 元素 | 數量 |
|---|---|---|
| 🔵 招牌（業界級） | Tools / Memory / Guardrails / Subagent Orch | 4 |
| 🟢 強（完整可用） | Output Parsing / Error Handling / Context Mgmt / State Mgmt / Verification | 5 |
| 🟡 中（有但分散） | Orchestration Loop / Prompt Construction / Prompt Loops | 3 |

## 內圈：Runtime（4）

| 元素 | Workshop 對應 | 評等 |
|---|---|---|
| **Orchestration Loop** | `nodeflow`（DAG，已 shelved）；現用 `forge` / `maestro` skill；本體 loop 借 Claude Code / Codex / Gemini 自己跑 | 🟡 中 |
| **Output Parsing** | 各模組 `schemas.py`（Pydantic）；memvault `PydanticAI` 結構化輸出 | 🟢 強 |
| **Error Handling** | `WorkshopError` 階層（NotFoundError / ForbiddenError / ConflictError / BadRequestError）+ resilience-patterns（7 模式）+ middleware degrade | 🟢 強 |
| **Prompt Construction** | `libs/ai-assistant`（TS）；memvault 2000 char prompt budget + write-side injection guard；cc-llm anti-loop | 🟡 中 |

## 中圈：Capabilities（4）

| 元素 | Workshop 對應 | 評等 |
|---|---|---|
| **Tools** | 23 MCP servers + 19 stations + `libs/sdk-client`（38 API clients）+ `cli-rosetta`（聲明式 CLI 差異字典） | 🔵 招牌 |
| **Memory** | `memvault` — bitemporal KG + auto_evolve + dream loop + AttnRes intent-dependent scoring | 🔵 招牌 |
| **Context Management** | memvault cascade recall（PPR + triples + blocks）+ `context-supervisor`（三層監控）+ context-diet skill | 🟢 強 |
| **State Management** | Backend：`SpaceScopedModel` + soft-delete + bitemporal；Frontend：TanStack Query + ActionJournal + zundo；Reactive Protocol 七概念統一合約 | 🟢 強 |

## 外圈：Safety & Scale（4）

| 元素 | Workshop 對應 | 評等 |
|---|---|---|
| **Guardrails & Safety** | 雙層防禦：(1) `permissions.deny`（substring，main agent）(2) `hook-observatory/bash_safety.py`（regex，含 sub-agents）；Backend RBAC + ABAC + `require_permission`；SSRF guard；OAuth redirect 驗證 | 🔵 招牌 |
| **Verification Loops** | `sentinel`（light + deep check）+ `skill-tester` + `verification-before-completion` skill + `eval` skill（pass@k）+ `auto-survey`（測驗答案策略）+ `code-review-interceptor` | 🟢 強 |
| **Subagent Orchestration** | **三 Tier**：(1) Headless（claude -p / Agent tool）(2) Agent Teams（experimental）(3) `tmux-relay`（pane pool + signal）；外加 `Fleet`（跨機器）+ `maestro` / `forge` skill | 🔵 招牌 |
| **Prompt Loops** | `prompt-router`（/r）+ `blueprint` + `brainstorming` + `forge` + `iterative-optimize` + `code-review-interceptor`（邊寫邊審） | 🟡 中 |

## 缺口診斷

Workshop 真正還沒收斂的是「**Loop 自治權**」這條軸：

### 1. Orchestration Loop（🟡）

- `nodeflow` 已 shelved
- 現在 loop 是「借」Claude Code / Codex / Gemini 的
- **Workshop 自己不擁有 agent loop**

如果要做 24/7 自動化代理（不依附 CLI 互動），這格得補。

### 2. Prompt Construction（🟡）

- 散在 `ai-assistant`（TS）/ memvault prompt budget / 各 skill 自寫
- **沒有統一的 `PromptAssembler`**

### 3. Prompt Loops（🟡）

- `forge` / `iterative-optimize` 是「外掛在 Claude Code 之上」的 skill loop
- 不是 workshop 內生 loop

## 設計哲學

對應的設計選擇是 2026 早期就明確的：

- 「workshop 內部不用 A2A」（[memory: A2A 架構決策](../../memory/a2a_decision.md)）
- 「modular monolith > microservices」（principles.md）
- **刻意不蓋自己的 agent loop**，把 loop 外包給 CLI（CC / Codex / Gemini）
- workshop 只當 **Memory + Tools + Guardrails 的供應商**

## 何時需要補 Orchestration Loop

當下列場景之一成立時，就是該補 Runtime 那三格的時候：

1. **dream loop 全自動化** — memvault 已有 dream loop（每日 4AM），但若要做更複雜的「醒著也跑」場景，需要常駐 loop
2. **sentinel 自動修復** — 目前 sentinel 只 detect + alert，若要做 auto-remediation，需要決策 loop
3. **scheduler 觸發複雜任務** — Cronicle 觸發後若要跑多步推理，需要 agent loop
4. **24/7 守人模式** — 沒有人坐在 CLI 前的長時段任務

候選實作路徑：

- **方案 A**：復活 `nodeflow`，定位為「workshop-native agent runtime」
- **方案 B**：用 `cc-llm` + LiteLLM stack 做極簡 loop（OpenAI Agents SDK / Pydantic AI Agent / LangGraph 三選一）
- **方案 C**：headless Claude Code 透過 `claude -p` + scheduled invocation，不蓋自己的 loop（最便宜，但深度受限）

## 與 Anthropic Managed Agents 的對應

| Anthropic 三層虛擬化 | Workshop 等價 |
|---|---|
| **Session**（append-only event log） | memvault block + intelflow report + capture |
| **Harness**（agent loop） | 借自 Claude Code / Codex / Gemini（缺自己的） |
| **Sandbox**（execution env） | hook-observatory bash_safety + permissions.deny + RBAC + Fleet 隔離 |

Session 與 Sandbox 都已落地；缺的就是 Harness 自有實作。

## 參考連結

- [The Anatomy of an Agent Harness — Avi Chawla](https://blog.dailydoseofds.com/p/the-anatomy-of-an-agent-harness)
- [Anthropic — Harness Design for Long-running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Anthropic — Managed Agents](https://www.anthropic.com/engineering/managed-agents)
- 內部：`docs/architecture/modular-monolith.md`
- 內部：`docs/architecture/event-resilience-patterns.md`
- 內部：`docs/plans/four-tier-data-lifecycle.md`
