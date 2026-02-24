---
doc_version: 2
content_hash: 3525e4c7
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
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

## AD-2: MCP Server 作為 Thin Adapter

**決策**：每個 Domain 擁有獨立的 MCP Server，但 MCP Servers 不直接存取 database ——
它們呼叫 FastAPI Core 的 REST API。MCP Server = HTTP Adapter。

**決策理由**：
- Claude Code 需要 MCP interface 來直接操作每個 Domain
- MCP Servers 若直接存取 DB，將繞過 Core 的 validation、events 以及 Hook logic
- Adapter pattern 保持了 MCP Servers 的 lightweight；business logic 則集中在 Core 中
- MCP Server outage 不會影響 Core；當 Core API 變更時，MCP 僅需更新 HTTP calls

**模式**：
```
Claude Code ──► MCP Server ──► FastAPI Core ──► Database
                (adapter)       (business)       (persistence)
```

**切分規則**：
- 每個 Domain 至少分配 1 個 MCP Server
- 超過 10 個 tools 的 MCP Servers 應進行切分 (例如：`workshop-quest-manage` + `workshop-quest-pool`)
- MCP Server tool 命名規則：`{domain}_{action}` (例如：`finance_add_transaction`)

**現有 MCP Servers**：
| 名稱 | Tool 數量 |
|-------------|------------|
| `workshop-finance` | 9 |
| `workshop-quest` | 10 |
| `workshop-muse` | 8 |
| `kas-memory` | 8 |

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
5. Widgets 透過 EventBus 進行通訊 (例如：點擊 finance transaction → quest 顯示相關任務)

**Widget 尺寸類別 (Size Classes)**：
- **Small** (1×1 ~ 2×1)：單一數據指標、快速操作按鈕
- **Medium** (2×2 ~ 3×2)：列表、簡單圖表、表單
- **Large** (4×2 ~ full width)：完整功能介面、複雜圖表、知識圖譜

---

## AD-5: Resource Abstraction

**決策**：將 human、machine、service 與 AI agent 統一抽象化為單一的 Resource。

**決策理由**：
- quest 的 task dispatch 需要知道「誰能執行此任務」—— 而這個「誰」並不一定是人
- 一個任務可以分配給 human (手動)、machine (cron job) 或 AI agent (Claude/Codex)
- 統一的模型使得無論 resource type 為何，皆可套用相同的 nexus logic
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
- **nexus**：`SELECT * FROM resources WHERE capabilities @> ARRAY['python'] AND current_load < capacity`
- **roster**：Dashboard 顯示所有 resources 的負載狀態
- **quest dispatch**：根據 task requirements × resource capabilities 進行自動配對

---

## AD-6: 事件驅動的跨模組通訊 (Event-Driven Cross-Module Communication)

**決策**：Modules 透過 Event Bus 進行通訊，而非 direct imports。

完整事件格式與規範詳見 [event-driven.md](./event-driven.md)。

**決策理由**：
- 保持清晰的 Module 邊界
- 允許 asynchronous processing (finance 記錄無需等待 quest 更新)
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
| quest | Checkbox to-do | + Story points | + Skill requirements + Task pool | + Orders/quotation/acceptance |
| finance | Personal accounting | + Family shared ledger | + Budget/analysis | + Inventory/POS |
| nexus | Manual pairing | + Conditional filtering | + AI recommendations | + Auto dispatch |
| lore | Manual memory | + Auto extraction | + Semantic search | + Cross-space isolation |

**原則**：
- 每個 Phase 都是可用且完整的產品 —— 而非半成品原型
- Phase N+1 不會破壞 Phase N 的使用者體驗
- 升級是可選的 (Opt-in)，而非強制的 (simple mode 始終可用)

---

## AD-8: Station SDK — 工作站共享層

**決策**：Stations 之間的共通邏輯提取到 `libs/python/station-sdk/`，作為輕量 SDK（非框架）提供。

**決策理由**：
- system-monitor 與 llm-usage 有 4 項重疊邏輯：launchd 排程、Core API 推送、Widget 資料格式、通知整合
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
libs/python/station-sdk/
├── api_client.py       ← Core API 推送（統一 auth + endpoint discovery）
├── scheduler.py        ← launchd plist 生成 / 管理 / 頻率變更
├── widget_schema.py    ← Workbench Widget JSON 標準格式
└── notifier.py         ← 通知管道抽象（notification bridge 對接）
```

**各 Station 與 SDK 的關係**：

| Station | 使用 SDK | 說明 |
|---------|:--------:|------|
| system-monitor | ✅ | 排程 + API + Widget + 通知，全部用到 |
| llm-usage | ✅ | API + Widget + 通知 |
| envkit | ❌ | CLI 工具性質不同，無排程/Widget 需求 |
| sandbox-executor | ❌ | Node.js MCP Server，語言不同 |

**替代方案**：
- ❌ 每個 station 獨立實作 → 重複代碼，格式不一致
- ❌ Station 框架（強制繼承 BaseStation class）→ 過度工程化，限制靈活性
- ✅ **輕量 SDK（可選依賴的工具函數庫）** → 平衡共用與獨立
