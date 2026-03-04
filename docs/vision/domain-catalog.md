---
doc_version: 3
content_hash: 2ec4dc04
source_version: 3
target_lang: zh-TW
translated_at: 2026-02-23
---

# 服務目錄 (Service Catalog)

> Workshop 服務的統一目錄。不區分「核心模組」與「專案」——一切皆為可組合的服務積木。

---

> 關於 LEGO 組合模型與組合配方，請參閱 [vision/composition-model.md](./composition-model.md)

---

## 服務 (Services)

### 基礎層 (Foundation)

#### auth — 身分驗證與授權

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | 無 (所有服務的前提) |
| **被依賴於** | 所有服務 |
| **MCP 伺服器** | `workshop-auth` |
| **V1 狀態** | 已存在 (GitHub OAuth, Google OAuth, 電子郵件/密碼) |

**功能能力**:
- 多提供商登入 (GitHub, Google, Email, 未來：LINE Login)
- 會話管理 (基於 cookie, `workshop_session`)
- 空間管理 (建立/邀請/權限)
- 模組級存取控制 (按空間、按使用者、按模組)
- API 金鑰管理 (用於 MCP / 外部整合)

**空間模型 (Space Model)** (共享範圍):
```
spaces: id, name, type(personal/family/friends/org), owner_id
space_members: space_id, user_id, role(owner/admin/member/guest), modules[]
```

---

#### admin — 平台管理

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **MCP 伺服器** | `workshop-admin` (待建置) |
| **V1 狀態** | V1 擁有 sysmon + agent-metrics (已併入 gateway) |

**功能能力**:
- 系統健康監測 (從 sysmon 演進而來)
- 使用者管理
- 模組啟用/停用控制
- 系統配置
- 稽核日誌 (Audit logging)

---

### 領域服務 (Domain Services)

#### finance — 會計與財務

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **MCP 伺服器** | `workshop-finance` + `workshop-finance-analytics` |
| **V1 狀態** | MCP 伺服器運作中 (18 個工具) |

**功能能力**:
- 一次性交易（付款方式：現金/信用卡/簽帳卡/電子支付/轉帳，具體卡片名稱）
- 樹狀分類系統（parent_id 自引用，使用者可自訂）
- 複數自訂標籤（transaction_tags 多對多）
- 照片附件（複數照片存 RustFS，DB 記 storage_key 關聯）
- 訂閱管理（週期性扣款，自動產生 transaction）
- 預算功能（總預算 + 分類預算，即時比對超支警示）
- 消費分析圖表（圓餅圖、柱狀圖、散佈圖、趨勢線、預算進度）
- 月度消費報告（LLM 產生 AI 建議）
- **MCP 拆分**：`workshop-finance`（CRUD ~10 tools）+ `workshop-finance-analytics`（分析+預算 ~8 tools）

**增長路徑** (漸進式複雜度):
```
階段 1: 個人記帳 + 樹狀分類 + 照片附件
階段 2: + 訂閱自動記帳 + 預算
階段 3: + 分析圖表 + AI 月報
階段 4: + 家庭共享帳本 + 庫存管理 / POS
```

詳見 [P5：Finance 記帳系統](../blueprint/p5-finance.md)

---

#### taskflow — 任務與派送

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, skillpath (用於量化模式) |
| **雙向連接** | finance (任務 ↔ 訂單) |
| **MCP 伺服器** | `workshop-taskflow` + `workshop-taskflow-reports` |
| **V1 狀態** | MCP 伺服器運作中 (15 個工具) |

**功能能力**:
- 統一任務模型（personal / family / company 多來源）
- 6 狀態狀態機（todo → in_progress → review → done / blocked / cancelled）
- 子任務（parent_id 自引用）
- 進度追蹤與回報（task_updates 表：progress / blocker / note / status_change）
- 日曆檢視（月/週/日/議程 四種模式）
- 週期性任務（recurrence JSONB：weekly / monthly / custom）
- 自動報告產出（日誌、週報、月報 + LLM 觀察建議）
- **MCP 拆分**：`workshop-taskflow`（CRUD ~10 tools）+ `workshop-taskflow-reports`（報告 ~5 tools）

**RPG 隱喻** (保留自 V1 設計):
- 裝備 = 知識，技能 = 職能，屬性 = 核心特徵
- 成就 = 往績，連勝/完成率 = 態度 (從行為推斷)

**增長路徑**:
```
階段 1: 核取方塊待辦 + 多來源 + 日曆
階段 2: + 進度追蹤 + 自動日誌/週報/月報
階段 3: + 技能需求 + 任務池 + 派送
階段 4: + 訂單 / 報價 / 驗收
```

詳見 [P6：Taskflow 排程與任務管理](../blueprint/p6-taskflow.md)

---

#### ideagraph — 靈感孵化與知識圖譜

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **被依賴於** | intelflow（情報→靈感轉入） |
| **MCP 伺服器** | `workshop-ideagraph` + `workshop-ideagraph-ai` |
| **整合 Skills** | workshop-muse (V1 MCP) |
| **V1 狀態** | MCP 伺服器運作中 (8 個工具，僅 CRUD) |

**功能能力**:
- AI 輔助想法孵化管線（Capture → Refine → Connect → Verify）
- Spark 原始/精煉分層（raw_content 不可變 + refined_content AI 產生）
- Link 驗證狀態（suggested / verified / rejected，AI 建議→人類驗證）
- 精煉歷史追蹤（refinements 表，版本化 diff）
- Galaxy 風格知識圖譜視覺化（D3.js force-directed，星星=Spark、星座線=Link）
- pgvector 語意搜尋（跨所有 Spark 語意比對）
- 跨模組事件轉 Spark（finance/taskflow/memvault 事件可轉入）
- **MCP 拆分**：`workshop-ideagraph`（CRUD ~8 tools）+ `workshop-ideagraph-ai`（AI 輔助 ~5 tools）

**增長路徑**:
```
階段 1: Capture + Refine + 基礎 Graph UI（D3 force-directed）
階段 2: + AI Suggest Links + Verify 流程
階段 3: + Galaxy 3D 視覺化 + 時間軸回放
階段 4: + 跨模組事件轉 Spark + Inbox
階段 5: + 協作（Space 共享）+ 匯出（Markdown / Obsidian）
```

詳見 [P7：ideagraph 靈感孵化與知識圖譜](../blueprint/p7-ideagraph.md)

---

#### intelflow — 搜尋與情報

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, memvault (用於個人化) |
| **MCP 伺服器** | `workshop-intelflow` (待建置) |
| **整合 Skills** | smart-search, daily-briefing, company-intel, competitive-intel, content-writer |
| **V1 狀態** | research_report service (已遷移至 `core/src/modules/intelflow/`) + smart-search skill v0.3.3 |

**功能能力**:
- RSS / 社群媒體來源管理
- 自動摘要生成 (LLM 驅動)
- 每日簡報推送
- 關鍵字 / 主題追蹤
- 與 ideagraph 整合 (情報 → 靈感)

---

#### memvault — LLM 記憶持久化

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **被依賴於** | skillpath, intelflow |
| **MCP 伺服器** | `memvault` (16 個工具) |
| **整合 Skills** | memvault (MCP), meeting-insights |
| **V1 狀態** | MCP 伺服器 v0.2.0 (語義搜索 + 個人檔案) |

**功能能力**:
- 會話結束 → 自動記憶提取
- 使用者提交提示 → 自動召回相關記憶
- 語義搜索 (OpenAI embedding，可切換至 Ollama)
- 記憶晉升 / 編輯 / 標籤
- Profile Score (K/A/S 三維量化)
- **V2 方向**: 更好的遺忘機制、跨空間隔離、多代理支持

---

#### skillpath — 技能樹與學習路徑

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, memvault |
| **被依賴於** | matchcore, workpool |
| **MCP 伺服器** | `workshop-skillpath` (待建置) |
| **整合 Skills** | skill-catalog, skill-graph, skill-optimizer, model-mentor |
| **V1 狀態** | 不存在 |

**功能能力**:
- 技能定義與分類 (科技樹結構)
- 學習路徑規劃 (先修鏈)
- 課程/資源媒合 (技能落差 → 學習資源)
- 能力驗證 (評估、認證追蹤)
- 技能等級 (初學者 → 中級 → 高級 → 專家)

---

#### workpool — 資源管理

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, skillpath |
| **被依賴於** | matchcore |
| **MCP 伺服器** | `workshop-workpool` (待建置) |
| **整合 Skills** | maestro, team-tasks, scheduler |
| **V1 狀態** | 不存在 |

**功能能力**:
- **統一資源抽象**: 人 = 機器 = 服務 = AI 代理
- 通用屬性：capabilities[], capacity, availability, cost_rate, status
- 工作量追蹤 (當前負載 vs 最大容量)
- 排程 / 可用性管理

**統一資源模型**:
```
resources:
  id, type(human/machine/service/agent),
  name, capabilities[], capacity,
  availability_schedule, cost_rate, status
```

**增長路徑**:
```
階段 1: 個人任務追蹤
階段 2: + 團隊工時
階段 3: + 機器/服務資源池
階段 4: + 完整 ERP 資源管理
```

---

#### matchcore — 媒合引擎

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, skillpath, workpool |
| **MCP 伺服器** | `workshop-matchcore` (待建置) |
| **V1 狀態** | 不存在 |

**功能能力**:
- 人才 × 職位媒合
- 能力 × 任務配對 (taskflow 派送背後的引擎)
- 學習資源推薦 (技能落差 → 課程建議)
- 多維度評分 (技能匹配、可用性、成本、歷史紀錄)
- 同一模型的三種使用案例：媒合、分配、學習路徑

---

### 整合服務 (橋接層 Bridges)

#### social-hooks — 社群平台連接器（Bridges）

| 屬性 | 數值 |
|----------|-------|
| **分類** | 橋接層 (Bridge)，位於 `bridges/` |
| **優先順序** | LINE > Telegram > Discord |
| **性質** | 雙向通訊（接收使用者訊息 + 推送模組事件） |
| **設計參考** | OpenClaw ChannelPlugin — Capability-Driven + Adapter 組合式 |

**功能能力**:
- **Inbound 正規化**：所有平台訊息 → `MessageEnvelope`（統一格式）
- **指令路由**：關鍵字自動路由至模組
  - 「記帳 午餐 120」→ finance.transaction.create
  - 「任務 買牛奶」→ taskflow.task.create
  - 「想法 也許可以...」→ ideagraph.spark.capture
- **Outbound 推播**：模組事件 → 格式化推送至平台
- **Bot 指令**：每個模組公開 Bot 指令
- **Capability 宣告**：每個 Bridge 宣告支援能力（rich_text / media / interactive / threading）

**架構**:
```
外部平台 → webhook.py → MessageEnvelope → router.py → Core 模組
Core 模組 → EventBus → Notification Router → adapter.py → 外部平台
```

**增長路徑**:
```
階段 1: LINE Bridge（台灣使用率最高）
階段 2: + Telegram Bridge
階段 3: + Discord Bridge
```

---

#### notification — 通知路由服務

| 屬性 | 數值 |
|----------|-------|
| **分類** | Hot-path 服務，位於 `core/services/notification/` |
| **前提條件** | PWA (sw.js + manifest.json) |
| **技術** | Web Push API + VAPID (主要), ntfy (後備), Firebase (未來) |
| **偏好儲存** | `auth.notification_preferences`（JSONB） |

**功能能力**:
- **事件→通知路由**：EventBus 事件 → 過濾 → 格式化 → 派送
- **Channel Adapter 介面**：統一的 `ChannelAdapter` ABC，每個推播通道獨立實作
- **使用者偏好**：按模組、按事件類型、按 channel 的三維開關
- **聚合防轟炸**：同 group_key 短時間內合併（防 10 筆交易 = 10 條通知）
- **勿擾時段**：quiet_hours 設定
- **通知歷史**：完整派送日誌 + 已讀追蹤 + Badge 未讀數
- **多通道派送**：PWA Push → ntfy → Email → Bridge（fallback chain）

**增長路徑**:
```
階段 1: PWA Push (VAPID) + 偏好管理 + 通知歷史
階段 2: + ntfy 備用 + 聚合 + 勿擾
階段 3: + Email (SMTP/Resend)
階段 4: + Firebase (行動端)
階段 5: + AI 路由（自動選最佳 channel）
```

詳見 [通知與橋接架構](../architecture/notification.md)

---

#### media — 媒體處理

| 屬性 | 數值 |
|----------|-------|
| **分類** | 熱路徑服務 (位於 `core/services/`) |
| **功能能力** | STT, TTS, 影像處理, OCR |

**當前**: 核心熱路徑服務的一部分。
**增長**: 可擴展用於特定領域的處理 (音樂 OCR、法律文件 OCR、產品目錄 OCR)。

---

### 工作站 (獨立工具 Stations)

> 可獨立運行的本地工具。需要推送資料到 Core API 或提供 Widget 的 Station，引用 `libs/python/station-sdk/` 共享排程、API 推送、Widget 格式、通知整合（參見 [AD-8](../architecture/architecture-decisions.md#ad-8-station-sdk--工作站共享層)）。

#### system-monitor — 系統監控

| 屬性 | 數值 |
|----------|-------|
| **分類** | 工作站 (Station) |
| **V1 狀態** | 磁碟分析運作中（`~/.claude/data/disk-report/`，每日 launchd） |
| **V2 變更** | 頻率改為每週 + 新增硬體資源壓力監控 |

**功能能力**：
- 磁碟空間分析（週報 + 月報 + 手動即時掃描）
- 硬體資源監控（CPU、RAM、Swap、溫度、電池）
- 壓力等級判定（normal → warning → critical → danger）
- AI 分析報告（雙層 LLM 路由：API → 離線 fallback）
- Workbench Widget（系統健康狀態卡片）

---

#### envkit — 環境工具組

| 屬性 | 數值 |
|----------|-------|
| **分類** | 工作站 (Station) |
| **V1 狀態** | `~/dotfiles/` 有基礎清單，但缺分類、驗證、一鍵 bootstrap |
| **V2 變更** | 完整分類清冊 + 順序化 bootstrap + 驗證 + diff |

**功能能力**：
- 分類清冊（AI 工具、終端、開發、服務、應用）
- Config 映射表（每個工具的設定檔位置 + 追蹤狀態）
- 8 階段 Bootstrap Pipeline（有依賴順序的安裝流程）
- 環境快照 + 驗證（快照 vs 實際環境對比）
- 雙機 Diff（比較兩台機器的環境差異）

---

#### tmux-webui — tmux 瀏覽器控制

| 屬性 | 數值 |
|----------|-------|
| **分類** | 工作站 (Station) |
| **V1 狀態** | 運作中（`~/workshop/stations/tmux-webui/`，port 8765） |

**功能能力**：
- 瀏覽器管理 tmux sessions / windows / panes
- 從 Web 向 pane 發送指令
- 系統指標即時顯示（CPU、RAM、Disk、Network）
- LLM 用量一覽

---

#### session-redactor — 轉錄檔敏感資料清理

| 屬性 | 數值 |
|----------|-------|
| **分類** | 工作站 (Station) |
| **V1 狀態** | 運作中（SessionEnd hook + Daily 4 AM sweep） |

**功能能力**：
- SessionEnd hook 自動掃描 .jsonl 轉錄檔
- 16 種敏感模式偵測（API key、密碼、token、SSH、DB credentials）
- Atomic write 保證資料完整性
- SQLite 追蹤清理歷史
- SessionEnd pipeline 第一步（redact → memvault extract → observability）

---

#### sandbox-executor — 批次執行引擎

| 屬性 | 數值 |
|----------|-------|
| **分類** | 工作站 (Station) |
| **V1 狀態** | 運作中（MCP Server，2 個工具） |

**功能能力**：
- Python/JS 沙盒執行
- SDK Helpers 自動注入（http_get/post, read_file/write_file, output）
- 批次操作（取代多次個別 tool call）

---

### 第三方工具 (Vendor)

> 不改造成 V2 架構的第三方社群工具。直接使用，upstream 更新靠 `git pull`。

#### observability — Multi-Agent Observability

| 屬性 | 數值 |
|----------|-------|
| **分類** | 第三方 (Vendor) |
| **來源** | [@disler](https://github.com/disler/claude-code-hooks-multi-agent-observability) |
| **技術** | Bun + SQLite + Vue.js |

**功能能力**：
- Claude Code hooks 即時事件追蹤
- 多 agent session 監控
- WebSocket 即時儀表板
- 事件過濾與搜尋

---

## 組合配方 (Composition Recipes)

> 關於完整的組合配方，請參閱 [vision/composition-model.md](./composition-model.md)

計劃中的組合：
- **法律顧問 (Legal Advisor)** = memvault + intelflow + ideagraph + media
- **教會音樂 (Church Music)** = media + memvault + ideagraph
- **虛擬客服 (Virtual CS)** = matchcore + social-hooks + taskflow + finance
- **ERP/POS** = finance + taskflow + workpool + matchcore

---

## 依賴圖 (Dependency Graph)

```
                    ┌─────────┐
                    │  auth   │ ← 所有服務的前提條件
                    └────┬────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
     │ finance │◄──►  taskflow  │   │  ideagraph   │
     └─────────┘   └────┬────┘   └─────────┘
                        │
                   ┌────▼────┐
                   │  intelflow  │
                   └─────────┘

     ┌─────────┐   ┌─────────┐   ┌─────────┐
     │  memvault   │──►│  skillpath   │──►│ workpool  │
     └─────────┘   └────┬────┘   └────┬────┘
                        │              │
                        └──────┬───────┘
                          ┌────▼────┐
                          │  matchcore  │
                          └─────────┘

     ┌─────────┐
     │  admin  │ ← 從所有服務讀取，不寫入任何服務
     └─────────┘
```

**依賴鏈解讀**:
1. `auth` 是所有事物的基礎
2. `finance ↔ taskflow` 雙向連結 (任務可以是訂單，訂單也是一種任務類型)
3. `memvault → skillpath → matchcore → workpool` 是從知識到執行的鏈條
4. `intelflow` 依賴 `memvault` 進行個人化
5. `admin` 是一個唯讀觀察者

---

## 服務索引 (Service Index)

| 服務 | 類型 | 狀態 | MCP 伺服器 | 工具數 |
|---------|------|--------|------------|-------|
| auth | 基礎層 | V1 已存在 | `workshop-auth` | 待定 |
| admin | 基礎層 | 部分 V1 | `workshop-admin` | 待定 |
| finance | 領域服務 | MCP 運作中 | `workshop-finance` + `workshop-finance-analytics` | ~18 |
| taskflow | 領域服務 | MCP 運作中 | `workshop-taskflow` + `workshop-taskflow-reports` | ~15 |
| ideagraph | 領域服務 | MCP 運作中 | `workshop-ideagraph` + `workshop-ideagraph-ai` | ~13 |
| intelflow | 領域服務 | 未開始 | `workshop-intelflow` | 待定 |
| memvault | 領域服務 | Core + MCP | `memvault` | 16 |
| skillpath | 領域服務 | 未開始 | `workshop-skillpath` | 待定 |
| workpool | 領域服務 | 未開始 | `workshop-workpool` | 待定 |
| matchcore | 領域服務 | 未開始 | `workshop-matchcore` | 待定 |
| social-hooks | 橋接層 | 未開始 | — | — |
| notification | 橋接層 | 未開始 | — | — |
| media | 熱路徑 | 位於 core/services/ | — | — |
| system-monitor | 工作站 | V1 運作中 | — | — |
| envkit | 工作站 | 重新設計 | — | — |
| tmux-webui | 工作站 | V1 運作中 | — | — |
| session-redactor | 工作站 | V1 運作中 | — | — |
| sandbox-executor | 工作站 | V1 運作中 | MCP (2 工具) | 2 |
| observability | 第三方 | 運作中 | — | — |

---

## 分類摘要 (Classification Summary)

| 類型 | 項目 | 資料存放地 |
|------|-------|---------------|
| **基礎層 (Foundation)** | auth, admin | PostgreSQL |
| **領域服務 (Domain Service)** | finance, taskflow, ideagraph, intelflow, memvault, skillpath, workpool, matchcore | PostgreSQL (每個模組一個 schema) |
| **橋接層 (Bridge)** | social-hooks, notification | 外部 + 事件總線 (Event Bus) |
| **熱路徑服務 (Hot-path Service)** | media (STT/TTS/影像), 即時通訊 (LiveKit) | 無狀態處理 |
| **工作站 (Station)** | system-monitor, envkit, tmux-webui, session-redactor, sandbox-executor | 本地 / 可選 PostgreSQL |
| **第三方 (Vendor)** | observability (@disler) | 獨立運行 |
| **組合 (Composition)** | 法律顧問, 教會音樂, 虛擬客服, ERP/POS | 上述服務的組合 |
