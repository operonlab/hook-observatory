---
doc_version: 4
content_hash: eccf4c8d
source_version: 4
target_lang: zh-TW
translated_at: 2026-02-23
---

# Workshop 設計原則

> Workshop 採用的設計原則 —— 從 SOLID 到 GoF 再到現代實踐，每項原則都註明了其在 Workshop 中的具體應用。
> 分為三個等級：**核心 (Core)**（開發時時刻謹記）、**應用 (Applied)**（設計決策時諮詢）、**參考 (Reference)**（需要時查閱）。

---

## 第一等級：核心 —— 開發時時刻謹記

> 這 10 項原則是 Workshop 日常開發的指導支柱。違反其中任何一項都值得停下來重新考慮。

### 1. SRP — 單一職責原則 (Single Responsibility)

> 一個模組只做一件事，並且只有一個理由去改變。

**Workshop 應用**：每個 Domain Service 管理單一業務領域。finance 僅處理金錢，taskflow 僅處理任務。跨領域邏輯透過 Event Bus 流動 —— 不會被塞進單個模組中。

### 2. DRY — 避免重複原則 (Don't Repeat Yourself) (+ 三次法則)

> 同樣的邏輯只寫一次。但容忍前兩次重複 —— 在第三次出現時進行抽象。

**Workshop 應用**：`BaseCRUDService<M,C,U,R>` 消除了 39 個實體間的 CRUD 重複。前端 `createCrudApi<T,C,U>` 遵循相同的原則。但不要強行對僅出現一次的邏輯建立 helper。

### 3. KISS — 保持簡單原則 (Keep It Simple, Stupid)

> 最簡單的解決方案通常是最好的。

**Workshop 應用**：模組化單體 (Modular Monolith) > 微服務 (Microservices)（單人團隊不需要分佈式複雜度）。處理序內 Event Bus > Redis Pub/Sub（對於 Phase 1 已經足夠）。

### 4. YAGNI — 你不需要它原則 (You Aren't Gonna Need It)

> 不要為假設性的未來需求進行開發。

**Workshop 應用**：漸進式複雜度 (Progressive Complexity) 的技術基礎。Phase 1 的 taskflow 只是一個打勾清單 —— 不需要預先構建任務池調度引擎。每個 Phase 都是一個完整、可用的產品。

### 5. SSOT — 單一真理來源 (Single Source of Truth)

> 每一份數據都有且只有一個權威來源。

**Workshop 應用**：
- Space 模型是共享範圍的唯一真理來源
- Event Bus 是狀態變更的唯一傳播管道
- PostgreSQL 的 schema-per-module 防止數據分散在多個位置

### 6. SoC — 關注點分離 (Separation of Concerns)

> 不同的關注點應嚴格分離 —— 不要將它們混在一起。

**Workshop 應用**：模組邊界 = 關注點邊界。`core/src/shared/` 存放跨模組共享代碼，`core/src/modules/{name}/` 存放模組特定代碼。Route handlers 僅處理 HTTP 協議，Services 僅處理業務邏輯，Models 僅管理數據結構。

### 7. 快速失敗 (Fail Fast)

> 盡早暴露錯誤 —— 絕不默默地吞掉它們。

**Workshop 應用**：`WorkshopError` 層級結構確保所有錯誤立即浮現。`before_create()` 鉤子在寫入數據庫前進行驗證。前端 API client 使用全局錯誤攔截器進行統一處理。

### 8. 組合優於繼承 (Composition > Inheritance)

> 優先使用組合而非繼承來實現行為復用。

**Workshop 應用**：Service = BaseCRUD（繼承） + EventBus（組合） + Permission（組合）。Widget = ModuleLayout（組合） + data hook（組合） + render component（組合）。Composition Recipes 本身就是服務組合的體現。

### 9. 低耦合 + 高內聚 (Loose Coupling + High Cohesion)

> 最小化模組間的依賴；保持模組內部的內容高度相關。

**Workshop 應用**：
- 低耦合：模組僅透過 Event Bus（寫入）或 Public API（讀取）進行通訊 —— 禁止直接 import
- 高內聚：在每個模組內部，models/schemas/service/routes 都緊密地為同一個業務領域服務

### 10. MVP — 最小可行產品 (Minimum Viable Product)

> 能驗證假設的最迷你可以行版本。

**Workshop 應用**：每個 Phase 都是一個 MVP。Phase 1 的 taskflow 只是個核取方塊 —— 如果它能運作，就是成功。不要追求「完美」 —— 追求「驗證核心假設」。

### 11. 善用現有方案 (Prefer Existing Solutions)

> 如果別人已經造好了輪子，直接用。除非它太大、太小、或無法滿足需求，才考慮自己造。

**Workshop 應用**：
- **優先順序**：成熟開源方案 > 輕量包裝 > 自行開發
- RustFS（MinIO 社群分支）用於物件儲存，而非自建 S3 相容層
- LiveKit 用於 WebRTC，而非自建信令伺服器
- react-grid-layout 用於 Widget 拖放，而非自建 grid 系統
- **定期回顧**：每個 Phase 結束時檢視——是否有新的成熟方案可以取代目前的自建元件？
- **反面教訓**：T1/T2 嘗試自建太多東西，導致全面回滾重寫

---

## 第二等級：應用 —— 設計決策時諮詢

> 這些原則在進行架構或設計決策時需要明確考慮。

### 其餘 SOLID 原則

| 原則 | Workshop 應用 |
|-----------|---------------------|
| **OCP** (開閉原則) | 插件系統：添加新 Plugin 不需要修改 Core。新模組掛載到 Event Bus 而不改變現有模組 |
| **LSP** (里氏替換原則) | `BridgeAdapter` ABC：LINE/Telegram/Discord 適配器完全可以互換 |
| **ISP** (介面隔離原則) | 每個 MCP Server 僅暴露其 Domain 的工具 —— 不強迫實現不相關的介面 |
| **DIP** (依賴倒置原則) | Service 依賴於 Repository 介面，而非直接依賴於 PostgreSQL 驅動程式 |

### 架構原則

| 原則 | Workshop 應用 |
|-----------|---------------------|
| **Bounded Context** (DDD) | 每個 Module = 一個擁有自己「語言」和數據模型的界限上下文 |
| **Event-Driven** | 模組間透過事件通訊。`finance.transaction.created` → taskflow 可以訂閱 |
| **Idempotency** (冪等性) | 事件處理程序必須是冪等的 —— 兩次接收相同的事件不會產生重複的影響 |
| **Progressive Disclosure** | MCP 工具按需加載 (via mcpproxy)，而不是塞爆系統提示詞 (system prompt) |
| **12-Factor App** | 配置存放在環境變數 (`.env`)、無狀態服務、埠綁定、開發/生產環境一致性 |
| **CoC** (約定優於配置) | 模組遵循統一的文件結構：`models.py`, `schemas.py`, `service.py`, `routes.py` |
| **PoLA** (最小驚訝原則) | API 行為遵循 REST 約定；事件命名 `{module}.{entity}.{action}` 直觀易讀 |
| **Defensive Programming** | 在 `before_create()` 中進行邊界驗證；外部輸入永遠不可信 |

### Workshop 中的設計模式

| 模式 | 使用位置 |
|---------|-----------|
| **Template Method** (範本方法) | `BaseCRUDService` 鉤子：`before_create()`, `after_create()`, `to_response()` |
| **Adapter** (適配器) | `BridgeAdapter` (LINE/Telegram/Discord), MCP Server (HTTP 適配器連接到 Core API) |
| **Observer / Pub-Sub** | Event Bus —— 模組訂閱來自其他模組的事件 |
| **Strategy** (策略) | LLM 供應商切換 (OpenAI ↔ Ollama), embedding 模型選擇 |
| **Factory** (工廠) | `createCrudApi<T,C,U>(basePath)` —— 一行代碼即可建立前端 API client |
| **Facade** (門面/外觀) | MCP Server = Core API 的簡化門面；Dashboard = Widgets 的統一容器 |
| **State** (狀態) | Quest 狀態機：`pending → active → completed → cancelled` |
| **Registry** (註冊表) | 錯誤代碼註冊表：`ERROR_REGISTRY` 字典 → `GET /api/meta/error-codes` |
| **Singleton** (單例) | DB 連線池, Redis client |
| **Proxy** (代理) | API Gateway —— 在代理層處理 auth/rate-limit |
| **Mediator** (中介者) | 將 Event Bus 作為模組間的中介者 |

---

## 第三等級：參考 —— 需要時查閱

> 這些原則/模式在特定場景下很有用，但不是日常開發的必需品。

### 未來考慮事項

| 原則 | 相關時機 |
|-----------|---------------|
| **CQRS** | Phase 3+ —— 分離讀取/寫入模型或數據庫（如果讀取/寫入壓力顯著分化） |
| **CAP Theorem** | 多實例部署 —— 在一致性 (Consistency)、可用性 (Availability)、分區容忍性 (Partition tolerance) 中三選二 |
| **Eventually Consistent** | 多實例 + 跨服務同步 —— 以即時一致性換取最終收斂 |
| **Strangler Fig** (絞殺者模式) | 從 V1 到 V2 的逐步遷移（我們選擇了重新編寫，所以目前不適用） |
| **Anti-Corruption Layer** | 整合外部遺留 API 時（例如：政府開放數據、舊系統適配器） |

### 其餘 GoF 模式（供參考）

| 類別 | 模式 | 潛在用途 |
|----------|----------|---------------|
| **Creational** (創建型) | Builder, Prototype | Builder: 複雜查詢組裝；Prototype: 配置的深拷貝 |
| **Structural** (結構型) | Composite, Bridge, Flyweight, Decorator | Composite: Widget 樹；Decorator: ` @authenticate` |
| **Behavioral** (行為型) | Command, Chain of Responsibility, Iterator, Visitor, Memento | Command: 復原/重做；CoR: 中間件管道；Memento: 版本回滾 |

### 測試原則

| 原則 | 應用 |
|-----------|-------------|
| **測試金字塔** | 大量單元測試 → 部分集成測試 → 極少端到端測試 |
| **AAA 模式** | Arrange (安排) → Act (執行) → Assert (斷言) |
| **測試隔離** | 每個測試都是獨立的 —— 不依賴於執行順序 |
| **真實驗證** | 相比 mock/smoke 測試，優先選擇真實執行 |

### 現代 / AI 時代 (2024-2026)

| 原則 | 應用 |
|-----------|-------------|
| **AI 增強開發** | Claude Code + Skills 輔助開發；人類審查 AI 生成的代碼 |
| **提示詞即代碼 (Prompt-as-Code)** | SKILL.md / agents/*.md 作為受版本控制的提示詞管理 |
| **最小工具表面** | MCP Server 僅暴露必要的最小工具（每個 server 少於 10 個） |
| **爆炸半徑隔離** | 每個模組的失敗影響都被遏制（schema 隔離、獨立的事件處理程序） |
| **基礎設施即代碼** | Docker Compose, Nginx 配置全部受版本控制 |
| **可觀察性 > 監控** | OpenTelemetry 追蹤 + 結構化日誌（從 Phase 1 開始構建） |

---

## 快速參考卡

```
日常開發的 11 項核心原則：

 1. SRP    — 一個模組只做一件事
 2. DRY    — 同樣的邏輯不寫兩次（第三次時抽象）
 3. KISS   — 最簡單的解決方案通常是最好的
 4. YAGNI  — 不要為假設的需求寫代碼
 5. SSOT   — 每一份數據都有一個權威來源
 6. SoC    — 嚴格分離不同的關注點
 7. Fail Fast — 立即暴露錯誤
 8. Composition > Inheritance — 優先組合，而非繼承
 9. Loose Coupling + High Cohesion — 模組間低耦合，內部高內聚
10. MVP    — 構建能驗證假設的最迷你可以行版本
11. Prefer Existing — 別人造好的輪子直接用，除非不合適
