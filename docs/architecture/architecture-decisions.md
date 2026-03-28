---
doc_version: 3
content_hash: pending
source_version: 2
target_lang: zh-TW
translated_at: 2026-03-04
---

# 架構決策 (Architecture Decisions)

> 紀錄 Workshop 架構的核心設計決策、理由與替代方案。

---

## AD-1: Modular Monolith 優於 Microservices

**決策**：採用 Modular Monolith (single deployment unit + module boundaries)，而非 Microservices。

**決策理由**：
- 單人開發團隊 (+AI) —— Microservices 的 operational overhead 遠超過其帶來的益處
- Modules 間需要頻繁的 data exchange；network hops 會增加不必要的 latency
- 單一 `uv run` 即可啟動 —— 開發體驗遠優於使用 docker-compose 執行 10 個以上的 services
- 若日後某個 Module 確實需要獨立 scaling，可再從 Monolith 中提取出來

**限制條件**：
- 禁止 Modules 間的 direct imports (只能透過 Event Bus 或 Public API)
- 每個 Module 擁有獨立的 DB schema (schema isolation，而非 DB isolation)
- 跨 Module 的 data queries 必須透過 API —— 禁止跨 Module tables 的 JOINs

---

## AD-2: MCP Server 作為 SDK-Based Protocol Adapter

**決策**：每個 Domain / Station 擁有獨立的 MCP Server，MCP Servers 透過 SDK 客戶端存取服務——
不直接存取 database，不使用原始 HTTP 調用。MCP Server = SDK Adapter。

**決策理由**：
- Claude Code 需要 MCP interface 來直接操作每個 Domain 和 Station
- MCP Servers 若直接存取 DB，將繞過 Core 的 validation、events 以及 Hook logic
- SDK 客戶端封裝了 HTTP 調用、錯誤處理、型別安全；MCP 層只負責 tool 定義與參數映射
- MCP Server outage 不會影響 Core；SDK 介面穩定，減少 MCP 層的維護成本

**模式**：
```
Claude Code ──► MCP Server ──► SDK Client ──► FastAPI Core ──► Database
                (tool def)     (typed API)     (business)       (persistence)
```

**切分規則**：
- 每個 Domain / Station 至少分配 1 個 MCP Server
- 超過 10 個 tools 的 MCP Servers 應進行切分 (例如：finance 拆為 finance + finance-wallet + finance-analytics)
- MCP Server tool 命名規則：`{domain}_{action}` (例如：`finance_add_transaction`)

**現有 MCP Servers（16 個）**：
| 名稱 | Tool 數量 | 類型 |
|-------------|------------|------|
| `agent-metrics` | 10 | Station |
| `envkit` | 4 | Station |
| `finance` | 9 | Core |
| `finance-analytics` | 9 | Core |
| `finance-wallet` | 9 | Core |
| `hook-observatory` | 3 | Station |
| `intelflow` | 2 | Core |
| `memvault` | 8 | Core |
| `nodeflow` | 6 | Core |
| `sandbox-executor` | 2 | Station |
| `sentinel` | 5 | Station |
| `session-intelligence` | 3 | Station |
| `session-redactor` | 3 | Station |
| `system-monitor` | 4 | Station |
| `tmux-relay` | 6 | Station |
| `tmux-webui` | 3 | Station |

---

## AD-3: Space-Based Sharing Model

**決策**：採用 Space-based sharing model，而非傳統的 Multi-Tenant。

**決策理由**：
- 傳統的 Multi-Tenant 假設了 organizational hierarchy (org → team → user)，這不符合個人工作站的場景
- Workshop 的共享是靈活的：一筆 ledger entry 可能與 spouse 共享，另一個 task 則與朋友共享
- 一個 Space 是一個「共享範圍 (sharing scope)」—— 可以是 personal / family / friends / org
- 每個 Space 可獨立啟用/停用不同的 Modules

**數據模型**：
```sql
-- Space definition
CREATE TABLE spaces (
    id          UUID PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,  -- personal, family, friends, org
    owner_id    UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Space members
CREATE TABLE space_members (
    space_id    UUID REFERENCES spaces(id),
    user_id     UUID REFERENCES users(id),
    role        TEXT NOT NULL,  -- owner, admin, member, guest
    modules     TEXT[] NOT NULL DEFAULT '{}',  -- authorized module list
    joined_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (space_id, user_id)
);
```

**設計重點**：
- 所有 data tables 皆包含 `space_id` 欄位 (在 Phase 0 加入)
- `modules[]` 控制成員在該 Space 中可存取哪些 Modules
- 使用者可同時屬於多個 Spaces
- 預設：每個新使用者自動獲得一個 personal space

---

## AD-4: Widget-Based Dashboard

**決策**：Dashboard 採用 Widget 系統，而非傳統的 page-routed SPA。

**決策理由**：
- 核心需求：「像 Android home screen widgets 一樣 —— 自由設計我的儀表板」
- 傳統的 SPA 頁面切換 = context switching；Widgets 可同時顯示多個 Module 資訊
- Widgets 是 composable、draggable、resizable 的 —— 比固定頁面更具個人化
- 每個 Module 可提供多個 Widgets (不同尺寸、不同 functional facets)

**技術選擇**：
| 技術 | 選擇 | 決策理由 |
|-----------|--------|-----------|
| Layout | `react-grid-layout` | 成熟的 drag-and-drop grid 解決方案 |
| Widget RWD | CSS Container Queries | Widgets 自適應其自身尺寸，而非螢幕尺寸 |
| Cross-Widget Communication | Custom EventBus | Widget A 發出 event → Widget B 回應 |
| Widget Registry | JSON manifest | 每個 Module 宣告其提供的 Widgets |
| State Persistence | localStorage + Core API | Layout 儲存在 user preferences 中 |

**Widget 生命週期**：
1. Module 透過 manifest 註冊 Widget (type, sizes, default props)
2. 使用者將 Widget 從 Gallery 拖曳到 Dashboard
3. Widget 根據 Container 尺寸調整佈局
4. Widget 透過 Core API 獲取數據
5. Widgets 透過 EventBus 進行通訊 (例如：點擊 finance transaction → taskflow 顯示相關任務)

**Widget 尺寸類別 (Size Classes)**：
- **Small** (1×1 ~ 2×1)：單一數據指標、快速操作按鈕
- **Medium** (2×2 ~ 3×2)：列表、簡單圖表、表單
- **Large** (4×2 ~ full width)：完整功能介面、複雜圖表、知識圖譜

---

## AD-5: Resource Abstraction

**決策**：將 human、machine、service 與 AI agent 統一抽象化為單一的 Resource。

**決策理由**：
- taskflow 的 task dispatch 需要知道「誰能執行此任務」—— 而這個「誰」並不一定是人
- 一個任務可以分配給 human (手動)、machine (cron job) 或 AI agent (Claude/Codex)
- 統一的模型使得無論 resource type 為何，皆可套用相同的 matchcore logic
- 為未來的 ERP 場景 (machine capacity、personnel hours、AI agent parallelism) 奠定基礎

**統一 Resource 模型**：
```
resources:
  id              UUID
  type            ENUM(human, machine, service, agent)
  name            TEXT
  capabilities    TEXT[]        -- what it can do
  capacity        FLOAT         -- maximum capacity
  current_load    FLOAT         -- current load
  availability    JSONB         -- schedule / availability
  cost_rate       DECIMAL       -- unit cost
  status          ENUM(active, busy, offline, maintenance)
  metadata        JSONB         -- type-specific extension fields
```

**使用案例**：
- **matchcore**：`SELECT * FROM resources WHERE capabilities @> ARRAY['python'] AND current_load < capacity`
- **workpool**：Dashboard 顯示所有 resources 的負載狀態
- **taskflow dispatch**：根據 task requirements × resource capabilities 進行自動配對

---

## AD-6: 事件驅動的跨模組通訊 (Event-Driven Cross-Module Communication)

**決策**：Modules 透過 Event Bus 進行通訊，而非 direct imports。

完整事件格式與規範詳見 [event-driven.md](./event-driven.md)。

**決策理由**：
- 保持清晰的 Module 邊界
- 允許 asynchronous processing (finance 記錄無需等待 taskflow 更新)
- 易於新增訂閱者 (新增 Bridge 不需要修改 Core)

**事件格式 (Event Format)**：
```python
{
    "event_type": "finance.transaction.created",
    "space_id": "uuid",
    "payload": { ... },
    "timestamp": "2026-02-23T10:00:00Z",
    "source_module": "finance"
}
```

**實作層級**：
1. **Phase 1**：In-process Event Bus (Python asyncio，在 multi-worker 之前已足夠)
2. **Phase 2**：Redis Streams (multi-process / multi-instance)
3. **Phase 3**：NATS JetStream

---

## AD-7: 漸進式複雜度模式 (Progressive Complexity Pattern)

**決策**：所有 Modules 遵循漸進式複雜度原則 —— 從最簡單的形式開始，然後逐步增加功能。

**範例**：

| Module | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|
| taskflow | Checkbox to-do | + Story points | + Skill requirements + Task pool | + Orders/quotation/acceptance |
| finance | Personal accounting | + Family shared ledger | + Budget/analysis | + Inventory/POS |
| matchcore | Manual pairing | + Conditional filtering | + AI recommendations | + Auto dispatch |
| memvault | Manual memory | + Auto extraction | + Semantic search | + Cross-space isolation |

**原則**：
- 每個 Phase 都是可用且完整的產品 —— 而非半成品原型
- Phase N+1 不會破壞 Phase N 的使用者體驗
- 升級是可選的 (Opt-in)，而非強制的 (simple mode 始終可用)

---

## AD-8: Station SDK — 工作站共享層

**決策**：Stations 之間的共通邏輯提取到 `libs/sdk-client/`，作為輕量 SDK（非框架）提供。

**決策理由**：
- system-monitor 與 agent-metrics 有 4 項重疊邏輯：launchd 排程、Core API 推送、Widget 資料格式、通知整合
- 若每個 station 各寫一套 HTTP client 和 JSON 格式，維護成本隨 station 數量線性增長
- 但 stations 的核心價值是「可獨立運行」，不能強制依賴 SDK

**設計原則**：

| 原則 | 說明 |
|------|------|
| **SDK 是可選依賴** | Station 不用 SDK 也能獨立運行（純 shell / 純 Python） |
| **約定優於配置** | SDK 提供預設值（API 端點、Widget 格式），station 只需填入業務邏輯 |
| **不是框架** | SDK 不控制 station 的生命週期，只提供可呼叫的工具函數 |
| **提取門檻：≥ 2 個使用者** | 只在 2 個以上 station 共用時才提取到 SDK |

**SDK 模組**：
```
libs/sdk-client/
├── api_client.py       ← Core API 推送（統一 auth + endpoint discovery）
├── scheduler.py        ← launchd plist 生成 / 管理 / 頻率變更
├── widget_schema.py    ← Workbench Widget JSON 標準格式
└── notifier.py         ← 通知管道抽象（notification bridge 對接）
```

**各 Station 與 SDK 的關係**：

| Station | 使用 SDK | 說明 |
|---------|:--------:|------|
| system-monitor | ✅ | 排程 + API + Widget + 通知，全部用到 |
| agent-metrics | ✅ | API + Widget + 通知 |
| envkit | ❌ | CLI 工具性質不同，無排程/Widget 需求 |
| sandbox-executor | ❌ | Node.js MCP Server，語言不同 |

**替代方案**：
- ❌ 每個 station 獨立實作 → 重複代碼，格式不一致
- ❌ Station 框架（強制繼承 BaseStation class）→ 過度工程化，限制靈活性
- ✅ **輕量 SDK（可選依賴的工具函數庫）** → 平衡共用與獨立

---

## AD-9: Python-First + Selective Rust

**決策**：Core Monolith 與大部分服務使用 Python。僅在 CPU-bound hot-path 場景選擇性地使用 Rust。

**決策理由**：

| 因素 | Python | Rust | Workshop 判斷 |
|------|--------|------|-------------|
| 開發速度（1人+AI） | 快 3-5x | 慢 | **Python 勝** — 單人團隊的最大瓶頸是開發速度，不是運行速度 |
| AI/ML 生態系 | 原生（LiteLLM, Anthropic SDK, etc.） | 二等公民 | **Python 勝** — Workshop 重度使用 AI 服務 |
| AI 程式碼生成品質 | Claude/Codex 最強語言 | 相對弱 | **Python 勝** — AI 輔助開發是核心生產力 |
| I/O-bound 效能 | async FastAPI ≈ Rust | 微幅領先 | **平手** — Workshop 瓶頸在 DB/網路 I/O |
| CPU-bound 效能 | 弱 | 極強 (10-100x) | Rust 勝 — 但 Workshop 極少 CPU 密集操作 |
| 記憶體使用 | ~150-300MB | ~30-80MB | Rust 勝 — 但 Mac Mini 24GB 完全夠用 |

**分工策略**：
```
Python 負責：                      Rust 負責：
├── Core Monolith (FastAPI)        ├── 物件儲存 (RustFS — 已在用)
├── MCP Servers (薄 HTTP 適配器)    ├── 未來: 媒體轉碼 hot-path
├── Stations (本地工具)             └── 未來: 高吞吐量批處理
├── Event Bus
└── Bridges
```

**何時考慮 Rust**：
- 效能 profiling 證明 Python 是瓶頸（而非 DB/網路）
- 同時併發用戶 > 1000（個人工作站不太可能）
- CPU-bound 的 hot-path 服務（媒體處理、大批量數據運算）

**替代方案**：
- ❌ 全 Rust 重寫 → 開發速度降 3-5x，AI 生態系支援差，收益有限（I/O-bound 場景差異小）
- ❌ Go → 開發速度中等，但 AI/ML 生態系遠不及 Python
- ✅ **Python-First + Selective Rust** → 開發速度最大化，在真正需要效能的地方用 Rust

---

## AD-10: 事件韌性模式 (Event Resilience Patterns)

**決策**：所有需要零遺失保證的事件管線，必須實作 [event-resilience-patterns.md](./event-resilience-patterns.md) 中定義的 6 個韌性模式。

**決策理由**：
- AD-6 定義了事件的格式與傳遞規則，但未涵蓋崩潰恢復、事件時效、冪等處理等「非理想路徑」行為
- Hook Observatory 實戰驗證了 spool-based WAL + checkpoint recovery 的可行性與必要性
- Workshop 各模組對事件遺失的容忍度不同，需要分類策略

**6 個模式**：
1. **P1 事件時效分類** — ephemeral / durable / idempotent，TTL 決定恢復行為
2. **P2 冪等投影** — dedup_hash + ON CONFLICT DO NOTHING，確保 at-least-once = exactly-once
3. **P3 WAL-Projection 分離** — 先寫日誌（source of truth），再投影到 DB（可重建）
4. **P4 Checkpoint Recovery** — cursor + 檔案狀態機，崩潰後從正確位置繼續
5. **P5 非阻塞隔離** — 三層隔離（fire-and-forget → background drain → consumers）
6. **P6 層級式過載保護** — 每層獨立流量控制，入口層永不阻塞

**簡化經驗（2026-02-28 三方辯論結論）**：
Hook Observatory 的實作驗證了一個重要洞察：**當 P2（冪等投影）完整實作時，P4（Checkpoint Recovery）的狀態機是冗餘的**。
dedup_hash + ON CONFLICT DO NOTHING 已提供 crash safety——重播不會產生重複。`.processing → .done` 狀態機和 P2 解決的是同一個問題。
同理，P1（TTL 分類）在低吞吐量個人工作站上是過度設計——定期 SQL DELETE 更簡單有效。

**實際採用**：Hook Observatory 簡化為 4 部件（spool JSONL + drain loop + dedup INSERT + batch size），從 7 部件減少 43%。
6 個模式作為**參考架構**保留，但各場景應依實際需求裁剪，而非全部實作。

**適用範圍**：
- ✅ 所有需要零遺失的場景（hook-observatory、intelflow pipeline、audit log）
- ⚠️ EventBus Phase 2+ (Redis Streams) 後，**標準事件** 的 P3/P4 可免（Redis 持久化足夠，丟 1s 可接受）
- ✅ **關鍵事件**（finance、audit）即使有 Redis 仍需保留 local spool——Redis 本身也會 crash
- ✅ P1、P2、P5、P6 在所有 Phase、所有場景都需要，永不退役

**參考實作**：`stations/hook-observatory/spool.py`

---

## AD-11: FSM 有限狀態機作為 Agent 行為約束層

**決策**：所有需要多步驟流程控制的 Agent 工作流，採用 FSM（有限狀態機）作為確定性骨架，防止 AI Agent 無序且不可控。

**決策理由**：
- LLM 會幻覺、跳步、忘記狀態；FSM 提供確定性的合法路徑約束
- 現代 AI Agent 框架大量採用 FSM 作為編排核心（LangGraph、StateFlow、XState/Stately Agent、Scale AI）
- FSM 可審計：精確記錄 agent 經過的每個狀態與轉換，形成完整的 decision trail
- FSM 防跳步：強制經過必要的中間狀態（如人工審核），不允許 agent 跳過

**Workshop 中的 FSM 應用**：

| 場景 | 狀態機 | 說明 |
|------|--------|------|
| Forge Pipeline | `BRAINSTORM → SPEC → BLUEPRINT → EXECUTE → VERIFY` | 端到端開發流程，Stage 3→4 需人工核准 |
| Session Pipeline | `redact → extract → archive → log` | Session 結束後的處理鏈，fail-safe 設計 |
| 使用者生命週期 | `pending → active → suspended/banned` | 僅 active 可登入 |
| 任務狀態 | `pending → in_progress → completed` | 不可跳過 in_progress |
| 事件處理 | `.processing → .done` | Checkpoint recovery 狀態機 |

**判斷是否需要 FSM（三問法）**：
1. **有狀態記憶嗎？** — 流程需要記住「現在到哪一步了」
2. **有合法路徑約束嗎？** — 不是任意狀態都能跳轉到任意狀態
3. **有審計需求嗎？** — 需要回溯「怎麼走到這一步的」

任一為「是」，即應使用 FSM。

**FSM 在 AI 時代的角色轉變**：
- 舊：手寫業務邏輯的控制流
- 新：AI Agent 的行為約束層（guardrail）—— 確保 AI 不會走歪
- FSM 不是被 AI 取代，而是成為「馴服 AI」的韁繩。越強大的 AI，越需要 FSM 來約束和治理

**參考文獻**：
- [StateFlow: Enhancing LLM Task-Solving through State-Driven Workflows](https://arxiv.org/html/2403.11322v1) — FSM 控制 LLM 不同階段，成本降 3-5x
- [Stately Agent](https://github.com/statelyai/agent) — XState state machine 引導 LLM agent 行為
- [LangGraph State Machines](https://dev.to/jamesli/langgraph-state-machines-managing-complex-agent-task-flows-in-production-36f4) — state + transition 拆解 agent 任務
- [Scale AI State Machines](https://docs.gp.scale.com/docs/agents/state-machines) — 商業級 agent 平台內建 FSM
- [Controlling Agentic AI via Legal-Specific FSMs](https://law.co/blog/controlling-agentic-ai-via-legal-specific-finite-state-machines) — 合規場景的 FSM 治理

**替代方案**：
- ❌ 純 prompt engineering（無 FSM）→ LLM 可能幻覺、跳步、死循環，無法審計
- ❌ 硬編碼 if-else 鏈 → 不可擴展，新增狀態需改大量程式碼
- ✅ **FSM 作為 guardrail** → 確定性骨架 + LLM 在每個狀態內自由發揮，兼顧靈活性與可控性

---

## AD-12: Crawl4AI 整合策略 — Hybrid Pattern Port + Library Bridge

**決策**：採用 Hybrid 策略整合 Crawl4AI。Phase 1 移植三個核心工程模式到現有模組（零依賴），Phase 2 以獨立 venv + bridge script 方式按需引入 crawl4ai library。

**決策理由**：
- crawl4ai 技術棧與 Workshop 高度對齊（Python + Playwright + Pydantic + FastAPI + Ollama）
- 直接安裝有 lxml 版本衝突（Workshop 6.0 vs crawl4ai ~=5.3），需 venv 隔離
- 三個核心模式（Strategy+ABC、Memory-Adaptive Dispatcher、3-Tier Pool）可零依賴移植，立即強化生態系
- crawl4ai 的 LLM extraction pipeline + 反偵測瀏覽器管理，不適合手動重寫，應以 library 使用

**移植的三個模式**：

| 模式 | 來源 | 目標模組 | 效果 |
|------|------|---------|------|
| Strategy+ABC Composition | `ExtractionStrategy` / `ChunkingStrategy` 正交組合 | capture adapters, nodeflow nodes | 可插拔、可測試、可組合 |
| 三閾值 Memory-Adaptive | `MemoryAdaptiveDispatcher` (90/95/85% 水位) | batch tasks (archive, scan, embedding) | 防 OOM、自適應並行度 |
| 3-Tier Pool + Adaptive Janitor | Permanent/Hot/Cold + SHA1 config hash | connection management, resource pool | 資源復用、記憶體感知清理 |

**整合架構**：
```
Workshop Core (主 venv, Python 3.12)
  ├── capture/adapters.py      ← 強化: Plugin Manifest + Enrichment Strategy ABC
  ├── shared/adaptive.py       ← 新增: Memory-Adaptive Batch Runner
  ├── shared/tiered_pool.py    ← 新增: 3-Tier Pool 通用實作
  └── intelflow/webcrawl.py    ← 新增: WebCrawlService (呼叫 bridge)
           │
           ▼ subprocess / JSON bridge
  crawl4ai venv (~/.venvs/crawl4ai)
  └── bridge.py                ← crawl4ai CLI wrapper, JSON stdin/stdout
```

**Phase 1（零依賴，Pattern Port）**：
- T1: Capture Adapter Plugin Manifest — 每個 adapter 自宣告 permissions/resolvers/weights
- T2: Memory-Adaptive Batch Runner — 三閾值水位控制器 + psutil 記憶體監控
- T3: Enrichment Strategy ABC — 在 capture pipeline 中加入可組合的 enrichment 策略層

**Phase 2（獨立 venv，Library Bridge）**：
- T4: `uv venv ~/.venvs/crawl4ai && uv pip install crawl4ai`
- T5: bridge.py — JSON stdin/stdout 協定，Workshop 透過 subprocess 呼叫
- T6: WebCrawlService + Intelflow WebCrawl Source

**Phase 3（深度整合）**：
- T7: Capture WebUrl Adapter（捕獲 URL → 爬取 → 結構化）
- T8: Nodeflow CrawlNode（DAG 工作流中的爬取節點）

**替代方案**：
- ❌ 直接安裝到主 venv → lxml 衝突 + 550MB 依賴膨脹
- ❌ 純 Pattern Port → 錯失 crawl4ai 的 LLM extraction + 反偵測能力，且維護成本高
- ❌ 純 Library 使用 → 未強化現有架構，錯過學習價值
- ✅ **Hybrid** → 立即強化生態系 + 按需使用 library，風險最低

**參考**：
- [Crawl4AI GitHub](https://github.com/unclecode/crawl4ai) — 30k+ stars, Python async web crawler
- Intelflow Report `019cd26599da7d23af1a1a8cf5b655ac` — 完整適用性分析
