---
doc_version: 1
content_hash: ace23419
source_version: 1
translated_at: 2026-02-23
---

# Domain Catalog (領域目錄)

> Workshop 所有領域的完整目錄：10 個核心模組 + 5 個專案構想 + 分類索引。

---

## 核心模組 (10)

### 1. auth — 身份驗證與授權

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | None (所有模組的前置條件) |
| **Depended by** | All |
| **MCP Server** | `workshop-auth` |
| **V1 Status** | 已存在 (GitHub OAuth, Google OAuth, email/password) |

**範圍**:
- 多供應商登入 (GitHub, Google, Email, 未來包含：LINE Login)
- Session 管理 (基於 cookie，`workshop_session`)
- 空間 (Space) 管理 (建立/邀請/權限)
- 模組級存取控制 (按空間、按使用者、按模組)
- API Key 管理 (用於 MCP / 外部整合)

**空間模型核心資料表**:
```
spaces: id, name, type(personal/family/friends/org), owner_id
space_members: space_id, user_id, role(owner/admin/member/guest), modules[]
```

---

### 2. finance — 會計與財務

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **MCP Server** | `pulso-finance` (現有，待更名) |
| **V1 Status** | MCP Server 運作中 |

**範圍**:
- 個人/家庭會計 (收入/支出追蹤)
- 訂閱管理 (訂閱生命週期)
- 財務洞察 (月度摘要、類別分析)
- 預算規劃 (按類別設定預算)
- **成長路徑**: 個人記帳 → 家庭共享帳本 → 庫存管理 → POS

**小工具概念**:
- 月度摘要卡片 (小)
- 最近交易列表 (中)
- 類別圓餅圖 (中)
- 完整會計介面 (大)

---

### 3. quest — 任務與派遣

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, skill (用於量化模式) |
| **Bidirectional** | finance (任務 ↔ 訂單) |
| **MCP Server** | `pulso-quest` (現有，待更名) |
| **V1 Status** | MCP Server 運作中 |

**範圍**:
- **簡單模式**: 待辦清單 (核取方塊、截止日期)
- **量化模式**: 故事點數、技能需求、複雜度評估
- **派遣模式**: 任務池 + 被動指派 + 主動領取
- **商業模式**: 任務 = 訂單，包含報價與驗收

**RPG 比喻** (源自 Quest 設計文件):
- 裝備 = 知識，技能 = 職能，屬性 = 核心能力
- 成就 = 實績，連續紀錄/達成率 = 態度 (從行為推論)

**成長路徑**: 核取方塊 → 故事點數 → 技能需求 → 任務池 → 訂單

---

### 4. muse — 靈感與知識圖譜

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **MCP Server** | `pulso-muse` (現有，待更名) |
| **V1 Status** | MCP Server 運作中 |

**範圍**:
- Spark (靈感筆記): 快速捕捉想法
- Link (關聯): Spark 之間的有向連結
- Graph (知識圖譜): 想法的可視化網路
- Inbox: 待處理的待定想法
- Search (語義搜尋): 跨所有 Sparks 搜尋

**小工具概念**:
- 快速筆記輸入 (小)
- 收件匣列表 (中)
- 知識圖譜縮圖 (大)

---

### 5. intel — 每日情報

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, memory (用於個性化) |
| **MCP Server** | `workshop-intel` (待建置) |
| **V1 Status** | 不存在 |

**範圍**:
- RSS / 社群媒體來源管理
- 自動摘要生成 (由 LLM 驅動)
- 每日簡報推送
- 關鍵字 / 主題追蹤
- 與 muse 整合 (情報 → 靈感)

---

### 6. memory — LLM 記憶持久化

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **Depended by** | skill, intel |
| **MCP Server** | `kas-memory` (現有) |
| **V1 Status** | MCP Server v0.2.0 (語義搜尋 + 個人檔案) |

**範圍**:
- SessionEnd → 自動記憶提取
- UserPromptSubmit → 自動回想相關記憶
- 語義搜尋 (OpenAI embedding，可切換至 Ollama)
- 記憶提升 / 編輯 / 標記
- KAS Profile (使用者特徵摘要)
- **V2 方向**: 更好的遺忘機制、跨空間記憶隔離、多 Agent 支援

---

### 7. skill — 技能樹與學習路徑

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, memory |
| **Depended by** | matching, workforce |
| **MCP Server** | `workshop-skill` (待建置) |
| **V1 Status** | 不存在 |

**範圍**:
- 技能定義與分類 (科技樹結構)
- 學習路徑規劃 (前置要求鏈)
- 課程/資源媒合 (將學習資源與技能差距進行媒合)
- 能力驗證 (評估、證照追蹤)
- 技能等級 (初學者 → 中級 → 高級 → 專家)

---

### 8. workforce — 資源管理

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, skill |
| **Depended by** | matching |
| **MCP Server** | `workshop-workforce` (待建置) |
| **V1 Status** | 不存在 |

**範圍**:
- **資源抽象** (統一模型): 人員 = 機器 = 服務 = AI Agent
- 共同屬性: capabilities[], capacity, availability, cost_rate, status
- 工作量追蹤 (當前負載 vs 最大容量)
- 排程 / 可用性管理
- **成長路徑**: 個人任務追蹤 → 團隊工時 → 機器/服務資源池 → 完整 ERP

**統一資源模型**:
```
resources:
  id, type(human/machine/service/agent),
  name, capabilities[], capacity,
  availability_schedule, cost_rate, status
```

---

### 9. matching — 媒合引擎

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth, skill, workforce |
| **MCP Server** | `workshop-matching` (待建置) |
| **V1 Status** | 不存在 |

**範圍**:
- 人才 × 職缺媒合
- 能力 × 任務配對 (quest 派遣背後的引擎)
- 學習資源推薦 (技能差距 → 課程建議)
- 多維度評分 (技能符合度、可用性、成本、歷史紀錄)
- **三種案例**: 媒合、指派、學習路徑推薦 — 全部基於相同的數據模型

---

### 10. admin — 平台管理

| Property | Value |
|----------|-------|
| **Classification** | Core Module |
| **Dependencies** | auth |
| **MCP Server** | `workshop-admin` (待建置) |
| **V1 Status** | V1 擁有 sysmon + agent-metrics (已合併至 gateway) |

**範圍**:
- 系統健康監測 (由 sysmon 演進)
- 使用者管理
- 模組啟用/停用控制
- 系統配置
- 稽核日誌

---

## 專案構想 (5 個獨立專案)

以下是較大規模的專案，未來可能成為獨立的 Station 或核心模組。

### P1. 法律顧問

| Property | Value |
|----------|-------|
| **Classification** | Station → 可升級為 Core Module |
| **Core Function** | 判例搜尋 + 法規查詢 + 庭審模擬 |
| **Technical Focus** | 針對法律文件的 RAG，LLM 推理 |

**預想功能**:
1. **判例搜尋**: 輸入案件細節，尋找相關判例與引用條文
2. **法律文件生成**: 根據案件細節起草法律文書
3. **庭審模擬**: 模擬法官立場 + 對造律師論點 (基於公開數據)
4. **策略彙整**: 根據模擬結果彙整我方策略

**數據來源**: 司法院法學資料檢索系統、全國法規資料庫 (台灣)

---

### P2. 教會音樂數位化

| Property | Value |
|----------|-------|
| **Classification** | Station |
| **Core Function** | 樂譜 OCR → 數位存檔 → 自動伴奏/人聲合成 |
| **Technical Focus** | Music OCR, 音訊合成 |

**預想功能**:
1. **樂譜掃描 + OCR**: 紙本分數 → 數位格式 (MusicXML / MIDI)
2. **曲庫管理**: 按筆劃索引、元數據 (調性、拍號、原始來源)
3. **伴奏生成**: MIDI → 伴奏軌道 (鋼琴/吉他/弦樂)
4. **電子人聲合成**: 旋律 + 歌詞 → 合成人聲
5. **人工校對流程**: 自動生成 → 人工校對/編輯 → 發佈

---

### P3. 虛擬客服

| Property | Value |
|----------|-------|
| **Classification** | Bridge + Core Module |
| **Core Function** | 需求理解 → 產品媒合 → 報價單生成 |
| **Technical Focus** | NLU, 產品型錄 OCR, LINE Bot |

**預想功能**:
1. **產品數位化**: 實體產品型錄透過 OCR → 結構化資料庫
2. **需求理解**: 客戶描述需求 → 關鍵字提取 → 條件媒合
3. **產品推薦**: 需求 × 產品型錄 → 排名建議
4. **報價單生成**: 選定產品 → 自動生成報價單 (PDF/HTML)
5. **LINE Bot 前端**: 客戶透過 LINE 對話完成整個流程

**與 Workshop 整合**:
- 產品型錄 → 核心模組 (類似 muse 的知識庫)
- 報價單 → finance 模組
- 客服對話 → quest (自動建立任務追蹤)

---

### P4. 社群平台 Hook

| Property | Value |
|----------|-------|
| **Classification** | Bridge |
| **Priority Order** | LINE > Telegram > Discord > Facebook > X |
| **Technical Focus** | Webhook, Bot API, 事件路由 |

**預想功能**:
1. **統一通訊**: 所有平台訊息流入統一收件匣
2. **事件路由**: 根據規則將訊息路由至對應模組
   - ` @accounting lunch 120` → finance
   - ` @docs/zh-TW/blueprint/v2-worktree-todos.zh-TW.md buy milk` → quest
   - ` @memo maybe we could...` → muse
3. **雙向同步**: 模組事件 → 推送至指定平台
4. **Bot 指令**: 每個模組暴露 Bot 指令

**整合架構**:
```
LINE/Telegram/Discord → Social Bridge → Event Bus → Core Modules
Core Modules → Event Bus → Social Bridge → LINE/Telegram/Discord
```

---

### P5. 通知平台

| Property | Value |
|----------|-------|
| **Classification** | Bridge |
| **Technology Options** | Firebase Cloud Messaging / Web Push API / ntfy |
| **Prerequisite** | PWA 已設計進 Workshop Web (sw.js + manifest.json) |

**預想功能**:
1. **推送通知**: PWA 推送 (桌面 + 行動瀏覽器)
2. **通知偏好**: 按模組、按事件類型開關
3. **通知聚合**: 防止通知轟炸，智慧批次處理
4. **多通路發送**: 推送 + Email + Social Hook (P4)
5. **通知歷史**: 可追蹤的通知日誌

**技術評估**:
- **Firebase Cloud Messaging**: 最成熟，但有供應商鎖定
- **Web Push API + VAPID**: 基於標準，自我控制
- **ntfy**: 開源、自託管、輕量化
- **建議**: 從 Web Push API (PWA 原生) 開始，以 ntfy 作為備援

---

## 領域依賴圖譜

```
                    ┌─────────┐
                    │  auth   │ ← 所有模組的前置條件
                    └────┬────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
     │ finance │◄──►  quest  │   │  muse   │
     └─────────┘   └────┬────┘   └─────────┘
                        │
                   ┌────▼────┐
                   │  intel  │
                   └─────────┘

     ┌─────────┐   ┌─────────┐   ┌───────────┐
     │ memory  │──►│  skill  │──►│ workforce │
     └─────────┘   └────┬────┘   └─────┬─────┘
                        │              │
                        └──────┬───────┘
                          ┌────▼────┐
                          │matching │
                          └─────────┘

     ┌─────────┐
     │  admin  │ ← 從所有模組讀取，不寫入任何模組
     └─────────┘
```

**依賴鏈解讀**:
1. `auth` 是所有事物的基礎
2. `finance ↔ quest` 雙向 (任務可以是訂單，訂單是一種任務類型)
3. `memory → skill → matching → workforce` 是從知識到執行的鏈條
4. `intel` 依賴 `memory` 進行個性化
5. `admin` 是一個唯讀的觀察者

---

## 分類體系摘要

| Type | Items | Data Residency |
|------|-------|---------------|
| **Core Module** | auth, finance, quest, muse, intel, memory, skill, workforce, matching, admin | PostgreSQL |
| **Station** | 磁碟分析, LLM 用量, 本地工具, 法律顧問, 教會音樂 | Local / Optional DB |
| **Bridge** | Social Hooks, 通知, 外部 API, OCR 服務, 虛擬客服 | External + Event Bus |
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
