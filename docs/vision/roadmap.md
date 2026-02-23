---
doc_version: 1
content_hash: f8683532
source_version: 1
target_lang: zh-TW
translated_at: 2026-02-23
---

# 工作坊路線圖

> 四階段開發路線圖：從個人與家庭到商業應用。

---

## 總覽

```
Phase 1              Phase 2              Phase 3              Phase 4
Personal + Family    Knowledge + Growth   Team + Dispatch      Commercial
──────────────────►──────────────────►──────────────────►──────────────────►

auth ✓               memory v2            workforce            matching v3
finance              skill                quest dispatch       quest commercial
quest (simple)       intel                matching v2          legal advisor
muse                 matching v1          resource pool        virtual CS
notification         church music         social hooks v2      ERP/POS
social hooks v1                                                full platform
```

---

## 第一階段：個人與家庭

> 目標：工作坊成為 Jones 與家人的日常工具。

### 核心模組

| 模組 | 目標 | 完成標準 |
|--------|--------|-------------------|
| **auth** | 多登入提供商支持 + 空間模型 | 2 名以上使用者，包含個人與家庭空間 |
| **finance** | 個人/家庭記帳 | 收支追蹤、訂閱管理、月度報表，妻子亦可使用 |
| **quest** | 簡單模式待辦 | 複選框 + 截止日期 + 基礎 Widget |
| **muse** | 想法筆記 | Spark 增刪查改 + 連結 + 圖譜視覺化 |

### 橋接器

| 橋接器 | 目標 | 完成標準 |
|--------|--------|-------------------|
| **Social Hooks v1** | 基礎 LINE 機器人整合 | 透過 LINE 指令進行記帳/待辦事項 |
| **Notification** | PWA 推播 | 基礎推播通知能力 |

### 基礎設施

- [ ] FastAPI Core Monolith + 模組化結構
- [ ] PostgreSQL 每個模組獨立 Schema + 所有資料表皆含 space_id
- [ ] 事件匯流排（進程內）
- [ ] Dashboard Widget 框架 (react-grid-layout + Container Queries) — 模組頁面之外的補充視圖
- [ ] LLM Chat 浮層 — 跨全域的 LLM 對話介面（類似 Gemini in Chrome）
- [ ] 針對 finance, quest, muse 的 MCP Server（對接到核心 API）
- [ ] PWA + Service Worker（基礎已存在）
- [ ] 基礎 CI/CD

### 第一階段交付成果

- 模組頁面功能運作：finance、quest、muse 各有完整路由式 UI
- 儀表板功能運作：首頁 Dashboard 至少 4 個 Widget（財務摘要、最近交易、任務列表、快速筆記）
- LLM Chat 浮層功能運作：在任何頁面可呼叫 LLM 對話
- LINE 機器人功能運作：基礎的 `@accounting`, `@todo` 指令
- 家庭帳號功能運作：妻子可登入並查看共享記帳
- MCP 功能運作：Claude Code 可直接操作所有模組

---

## 第二階段：知識與成長

> 目標：工作坊成為個人知識管理與成長平台。

### 核心模組

| 模組 | 目標 | 完成標準 |
|--------|--------|-------------------|
| **memory** | KAS Memory v2 | 自動提取、語義搜尋、跨階段召回 |
| **skill** | 技能樹 v1 | 技能定義、等級、學習路徑 |
| **intel** | 每日情報 v1 | RSS 訂閱、自動摘要、簡報 |
| **matching v1** | 基礎媒合 | 技能 × 學習資源推薦 |

### 站點

| 站點 | 目標 | 完成標準 |
|---------|--------|-------------------|
| **Church Music** | 樂譜數位化 | OCR → 庫 → 基礎搜尋 |

### 第二階段交付成果

- Memory v2 上線：Claude Code 的記憶更加準確且結構化
- 技能樹視覺化：顯示個人技能地圖的 Widget
- 每日簡報：每天早晨自動接收新聞/社群媒體摘要
- 樂譜庫：教會聖詩可搜尋與瀏覽

---

## 第三階段：團隊與派遣

> 目標：工作坊從個人工具升級為小團隊協作平台。

### 核心模組

| 模組 | 目標 | 完成標準 |
|--------|--------|-------------------|
| **workforce** | 資源管理 v1 | 人類 + AI 代理人能力/負載追蹤 |
| **quest dispatch** | 任務派遣 | 任務池 + 被動分配 + 主動領取 |
| **matching v2** | 進階媒合 | 人才 × 任務多維度評分 |

### 橋接器

| 橋接器 | 目標 | 完成標準 |
|--------|--------|-------------------|
| **Social Hooks v2** | 全平台整合 | LINE + Telegram + Discord |

### 第三階段交付成果

- 任務池功能運作：朋友可以從任務池中領取任務
- 資源儀表板：查看所有資源（人類/AI）的負載狀態
- 多平台通知：任務分配/完成通知推送到所有社群平台

---

## 第四階段：商業化

> 目標：將工作坊的領域知識應用於商業場景。

### 應用程式

| 專案 | 目標 | 建構於 |
|---------|--------|----------|
| **Quest Commercial** | 訂單/報價/驗收 | quest + finance |
| **Legal Advisor** | 法律諮詢服務 | RAG + LLM 推理 |
| **Virtual CS** | 虛擬客服 | matching + social hooks |
| **ERP/POS** | 庫存管理系統 | finance + quest + workforce |
| **Full Platform** | 開放平台 | 所有模組 + 外掛系統 |

### 第四階段交付成果

- 至少落地一個商業案例（虛擬客服或 ERP/POS）
- 外掛系統成熟：第三方可以開發工作坊外掛
- 公開 API 文件
- 多空間組織管理

---

## 橫切關注點（貫穿所有階段）

| 項目 | 描述 |
|------|-------------|
| **文件** | 開始前完成階段規格，完成後更新架構文件 |
| **測試** | 真實場景驗證（無 Mock），每個模組至少一個端到端流程 |
| **安全性** | auth 從第一階段起即達到生產等級 —— 不走捷徑 |
| **可觀測性** | 從第一階段起建立 OpenTelemetry 追蹤 + 結構化日誌 |
| **MCP** | 每個新模組同時產生一個 MCP Server |
| **Widget** | 每個新模組同時產生至少一個儀表板 Widget |

---

## 優先順序（各階段內）

階段內的優先順序如下：

1. **基礎設施** → 基礎先行
2. **auth** → 身份先行
3. **資料模型** → 結構先行
4. **核心 API** → 後端先行
5. **MCP Server** → CLI 介面先行
6. **Widget** → UI 最後
7. **文件** → 貫穿始終

---

## 已知風險

| 風險 | 緩解策略 |
|------|-------------------|
| 範圍過大 | 嚴格的階段界限 —— 在第 N 階段完成前，不開始第 N+1 階段 |
| 技術債 | 文件先行 + 真實驗證 —— 拒絕快速臨時修補 |
| 動力下降 | 每個階段都產生可用產品 —— 日常使用 = 持續動力 |
| 上下文爆炸 | Wayne 的記憶系統 + HANDOFF.md + 特定領域文件 |
| 過度工程 | 漸進式複雜度原則：先建構最簡單的版本 |
