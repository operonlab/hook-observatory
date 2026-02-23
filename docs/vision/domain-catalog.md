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
| **MCP 伺服器** | `workshop-finance` |
| **V1 狀態** | MCP 伺服器運作中 (9 個工具) |

**功能能力**:
- 個人/家庭記帳 (收入/支出追蹤)
- 訂閱管理 (訂閱生命週期)
- 財務洞察 (每月摘要、類別分析)
- 預算規劃 (按類別編列預算)

**增長路徑** (漸進式複雜度):
```
階段 1: 個人記帳
階段 2: + 家庭共享帳本
階段 3: + 預算/分析
階段 4: + 庫存管理 / POS
```

---

#### quest — 任務與派送

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, dojo (用於量化模式) |
| **雙向連接** | finance (任務 ↔ 訂單) |
| **MCP 伺服器** | `workshop-quest` |
| **V1 狀態** | MCP 伺服器運作中 (10 個工具) |

**功能能力**:
- **簡單模式**: 待辦清單 (核取方塊、到期日)
- **量化模式**: 故事點數、技能需求、複雜度評估
- **派送模式**: 任務池 + 被動分配 + 主動承接
- **商務模式**: 任務 = 訂單，包含報價與驗收

**RPG 隱喻** (取自 Quest 設計文件):
- 裝備 = 知識，技能 = 職能，屬性 = 核心特徵
- 成就 = 往績，連勝/完成率 = 態度 (從行為推斷)

**增長路徑**:
```
階段 1: 核取方塊待辦事項
階段 2: + 故事點數
階段 3: + 技能需求 + 任務池
階段 4: + 訂單 / 報價 / 驗收
```

---

#### muse — 靈感與知識圖譜

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **MCP 伺服器** | `workshop-muse` |
| **V1 狀態** | MCP 伺服器運作中 (8 個工具) |

**功能能力**:
- Spark (靈感筆記)：快速捕捉想法
- Link (連結)：Spark 之間的分向連結
- Graph (知識圖譜)：想法的可視化網絡
- Inbox (收件匣)：待處理的靈感
- Search (語義搜索)：跨所有 Spark 進行搜索

---

#### scout — 搜尋與情報

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, lore (用於個人化) |
| **MCP 伺服器** | `workshop-scout` (待建置) |
| **整合 Skills** | smart-search, daily-briefing, company-intel, competitive-intel, content-writer |
| **V1 狀態** | research_report service (port 8830) + smart-search skill v0.3.3 |

**功能能力**:
- RSS / 社群媒體來源管理
- 自動摘要生成 (LLM 驅動)
- 每日簡報推送
- 關鍵字 / 主題追蹤
- 與 muse 整合 (情報 → 靈感)

---

#### lore — LLM 記憶持久化

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **被依賴於** | dojo, scout |
| **MCP 伺服器** | `kas-memory` (現有，8 個工具) |
| **整合 Skills** | kas-memory (MCP), meeting-insights |
| **V1 狀態** | MCP 伺服器 v0.2.0 (語義搜索 + 個人檔案) |

**功能能力**:
- 會話結束 → 自動記憶提取
- 使用者提交提示 → 自動召回相關記憶
- 語義搜索 (OpenAI embedding，可切換至 Ollama)
- 記憶晉升 / 編輯 / 標籤
- KAS 個人檔案 (使用者特徵摘要)
- **V2 方向**: 更好的遺忘機制、跨空間隔離、多代理支持

---

#### dojo — 技能樹與學習路徑

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, lore |
| **被依賴於** | nexus, roster |
| **MCP 伺服器** | `workshop-dojo` (待建置) |
| **整合 Skills** | skill-catalog, skill-graph, skill-optimizer, model-mentor |
| **V1 狀態** | 不存在 |

**功能能力**:
- 技能定義與分類 (科技樹結構)
- 學習路徑規劃 (先修鏈)
- 課程/資源媒合 (技能落差 → 學習資源)
- 能力驗證 (評估、認證追蹤)
- 技能等級 (初學者 → 中級 → 高級 → 專家)

---

#### roster — 資源管理

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, dojo |
| **被依賴於** | nexus |
| **MCP 伺服器** | `workshop-roster` (待建置) |
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

#### nexus — 媒合引擎

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, dojo, roster |
| **MCP 伺服器** | `workshop-nexus` (待建置) |
| **V1 狀態** | 不存在 |

**功能能力**:
- 人才 × 職位媒合
- 能力 × 任務配對 (quest 派送背後的引擎)
- 學習資源推薦 (技能落差 → 課程建議)
- 多維度評分 (技能匹配、可用性、成本、歷史紀錄)
- 同一模型的三種使用案例：媒合、分配、學習路徑

---

### 整合服務 (橋接層 Bridges)

#### social-hooks — 社群平台連接器

| 屬性 | 數值 |
|----------|-------|
| **分類** | 橋接層 (Bridge) |
| **優先順序** | LINE > Telegram > Discord > Facebook > X |
| **提供對象** | 透過事件總線 (Event Bus) 路由至所有核心模組 |

**功能能力**:
- 統一訊息：所有平台訊息 → 統一收件匣
- 事件路由：根據規則將訊息路由至各個模組
  - ` @Library/Developer/Xcode/iOS DeviceSupport/iPhone16,2 26.2.1 (23C71)/Symbols/System/Library/PrivateFrameworks/MemoryAccounting.framework/MemoryAccounting lunch 120` → finance
  - ` @.cache/uv/simple-v20/pypi/pycryptodomex.rkyv buy milk` → quest
  - ` @.tmux/logs/memory-guardian.log maybe we could...` → muse
- 雙向同步：模組事件 → 推送至平台
- Bot 指令：每個模組均公開 Bot 指令

**架構**:
```
LINE/Telegram/Discord → Social Bridge → Event Bus → 核心模組
核心模組 → Event Bus → Social Bridge → LINE/Telegram/Discord
```

---

#### notification — 通知平台

| 屬性 | 數值 |
|----------|-------|
| **分類** | 橋接層 (Bridge) |
| **前提條件** | PWA (sw.js + manifest.json) |
| **技術** | Web Push API + VAPID (主要), ntfy (後備) |

**功能能力**:
- 推送通知：PWA 推送 (桌面 + 行動瀏覽器)
- 通知偏好：按模組、按事件類型切換
- 通知聚合：防止訊息轟炸、智能批次處理
- 多通路派送：推送 + 電子郵件 + Social Hooks
- 通知歷史：可追溯日誌

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

> 不需要資料庫的獨立本地工具。可以是 CLI、桌面公用程式或分析腳本。
> 工作站可以獨立於 FastAPI Core 運行，但可以選擇將資料推送到 Core。

- 磁碟分析 / 系統資源監測
- LLM 使用量追蹤
- 本地文件管理工具
- Claude Code 技能 (diagram-gen, pdf, ocr 等)

---

## 組合配方 (Composition Recipes)

> 關於完整的組合配方，請參閱 [vision/composition-model.md](./composition-model.md)

計劃中的組合：
- **法律顧問 (Legal Advisor)** = lore + scout + muse + media
- **教會音樂 (Church Music)** = media + lore + muse
- **虛擬客服 (Virtual CS)** = nexus + social-hooks + quest + finance
- **ERP/POS** = finance + quest + roster + nexus

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
     │ finance │◄──►  quest  │   │  muse   │
     └─────────┘   └────┬────┘   └─────────┘
                        │
                   ┌────▼────┐
                   │  scout  │
                   └─────────┘

     ┌─────────┐   ┌─────────┐   ┌─────────┐
     │  lore   │──►│  dojo   │──►│ roster  │
     └─────────┘   └────┬────┘   └────┬────┘
                        │              │
                        └──────┬───────┘
                          ┌────▼────┐
                          │  nexus  │
                          └─────────┘

     ┌─────────┐
     │  admin  │ ← 從所有服務讀取，不寫入任何服務
     └─────────┘
```

**依賴鏈解讀**:
1. `auth` 是所有事物的基礎
2. `finance ↔ quest` 雙向連結 (任務可以是訂單，訂單也是一種任務類型)
3. `lore → dojo → nexus → roster` 是從知識到執行的鏈條
4. `scout` 依賴 `lore` 進行個人化
5. `admin` 是一個唯讀觀察者

---

## 服務索引 (Service Index)

| 服務 | 類型 | 狀態 | MCP 伺服器 | 工具數 |
|---------|------|--------|------------|-------|
| auth | 基礎層 | V1 已存在 | `workshop-auth` | 待定 |
| admin | 基礎層 | 部分 V1 | `workshop-admin` | 待定 |
| finance | 領域服務 | MCP 運作中 | `workshop-finance` | 9 |
| quest | 領域服務 | MCP 運作中 | `workshop-quest` | 10 |
| muse | 領域服務 | MCP 運作中 | `workshop-muse` | 8 |
| scout | 領域服務 | 未開始 | `workshop-scout` | 待定 |
| lore | 領域服務 | MCP v0.2.0 | `kas-memory` | 8 |
| dojo | 領域服務 | 未開始 | `workshop-dojo` | 待定 |
| roster | 領域服務 | 未開始 | `workshop-roster` | 待定 |
| nexus | 領域服務 | 未開始 | `workshop-nexus` | 待定 |
| social-hooks | 橋接層 | 未開始 | — | — |
| notification | 橋接層 | 未開始 | — | — |
| media | 熱路徑 | 位於 core/services/ | — | — |

---

## 分類摘要 (Classification Summary)

| 類型 | 項目 | 資料存放地 |
|------|-------|---------------|
| **基礎層 (Foundation)** | auth, admin | PostgreSQL |
| **領域服務 (Domain Service)** | finance, quest, muse, scout, lore, dojo, roster, nexus | PostgreSQL (每個模組一個 schema) |
| **橋接層 (Bridge)** | social-hooks, notification | 外部 + 事件總線 (Event Bus) |
| **熱路徑服務 (Hot-path Service)** | media (STT/TTS/影像), 即時通訊 (LiveKit) | 無狀態處理 |
| **工作站 (Station)** | 磁碟分析, LLM 使用量, 本地工具, Claude Code 技能 | 本地 / 可選資料庫 |
| **組合 (Composition)** | 法律顧問, 教會音樂, 虛擬客服, ERP/POS | 上述服務的組合 |
