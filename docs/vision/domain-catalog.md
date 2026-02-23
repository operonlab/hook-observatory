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

> 關於 LEGO 組合模型與組合配方，請參閱 [architecture/composition-model.md](../architecture/composition-model.md)

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
| **MCP 伺服器** | `pulso-finance` (現有，待更名為 → `workshop-finance`) |
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
| **依賴項目** | auth, skill (用於量化模式) |
| **雙向連接** | finance (任務 ↔ 訂單) |
| **MCP 伺服器** | `pulso-quest` (現有，待更名為 → `workshop-quest`) |
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
| **MCP 伺服器** | `pulso-muse` (現有，待更名為 → `workshop-muse`) |
| **V1 狀態** | MCP 伺服器運作中 (8 個工具) |

**功能能力**:
- Spark (靈感筆記)：快速捕捉想法
- Link (連結)：Spark 之間的分向連結
- Graph (知識圖譜)：想法的可視化網絡
- Inbox (收件匣)：待處理的靈感
- Search (語義搜索)：跨所有 Spark 進行搜索

---

#### intel — 每日情報

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, memory (用於個人化) |
| **MCP 伺服器** | `workshop-intel` (待建置) |
| **V1 狀態** | 不存在 |

**功能能力**:
- RSS / 社群媒體來源管理
- 自動摘要生成 (LLM 驅動)
- 每日簡報推送
- 關鍵字 / 主題追蹤
- 與 muse 整合 (情報 → 靈感)

---

#### memory — LLM 記憶持久化

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth |
| **被依賴於** | skill, intel |
| **MCP 伺服器** | `kas-memory` (現有，8 個工具) |
| **V1 狀態** | MCP 伺服器 v0.2.0 (語義搜索 + 個人檔案) |

**功能能力**:
- 會話結束 → 自動記憶提取
- 使用者提交提示 → 自動召回相關記憶
- 語義搜索 (OpenAI embedding，可切換至 Ollama)
- 記憶晉升 / 編輯 / 標籤
- KAS 個人檔案 (使用者特徵摘要)
- **V2 方向**: 更好的遺忘機制、跨空間隔離、多代理支持

---

#### skill — 技能樹與學習路徑

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, memory |
| **被依賴於** | matching, workforce |
| **MCP 伺服器** | `workshop-skill` (待建置) |
| **V1 狀態** | 不存在 |

**功能能力**:
- 技能定義與分類 (科技樹結構)
- 學習路徑規劃 (先修鏈)
- 課程/資源媒合 (技能落差 → 學習資源)
- 能力驗證 (評估、認證追蹤)
- 技能等級 (初學者 → 中級 → 高級 → 專家)

---

#### workforce — 資源管理

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, skill |
| **被依賴於** | matching |
| **MCP 伺服器** | `workshop-workforce` (待建置) |
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

#### matching — 媒合引擎

| 屬性 | 數值 |
|----------|-------|
| **依賴項目** | auth, skill, workforce |
| **MCP 伺服器** | `workshop-matching` (待建置) |
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

> 關於完整的組合配方，請參閱 [architecture/composition-model.md](../architecture/composition-model.md)

計劃中的組合：
- **法律顧問 (Legal Advisor)** = memory + intel + muse + media
- **教會音樂 (Church Music)** = media + memory + muse
- **虛擬客服 (Virtual CS)** = matching + social-hooks + quest + finance
- **ERP/POS** = finance + quest + workforce + matching

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
     │  admin  │ ← 從所有服務讀取，不寫入任何服務
     └─────────┘
```

**依賴鏈解讀**:
1. `auth` 是所有事物的基礎
2. `finance ↔ quest` 雙向連結 (任務可以是訂單，訂單也是一種任務類型)
3. `memory → skill → matching → workforce` 是從知識到執行的鏈條
4. `intel` 依賴 `memory` 進行個人化
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
| intel | 領域服務 | 未開始 | `workshop-intel` | 待定 |
| memory | 領域服務 | MCP v0.2.0 | `kas-memory` | 8 |
| skill | 領域服務 | 未開始 | `workshop-skill` | 待定 |
| workforce | 領域服務 | 未開始 | `workshop-workforce` | 待定 |
| matching | 領域服務 | 未開始 | `workshop-matching` | 待定 |
| social-hooks | 橋接層 | 未開始 | — | — |
| notification | 橋接層 | 未開始 | — | — |
| media | 熱路徑 | 位於 core/services/ | — | — |

---

## 分類摘要 (Classification Summary)

| 類型 | 項目 | 資料存放地 |
|------|-------|---------------|
| **基礎層 (Foundation)** | auth, admin | PostgreSQL |
| **領域服務 (Domain Service)** | finance, quest, muse, intel, memory, skill, workforce, matching | PostgreSQL (每個模組一個 schema) |
| **橋接層 (Bridge)** | social-hooks, notification | 外部 + 事件總線 (Event Bus) |
| **熱路徑服務 (Hot-path Service)** | media (STT/TTS/影像), 即時通訊 (LiveKit) | 無狀態處理 |
| **工作站 (Station)** | 磁碟分析, LLM 使用量, 本地工具, Claude Code 技能 | 本地 / 可選資料庫 |
| **組合 (Composition)** | 法律顧問, 教會音樂, 虛擬客服, ERP/POS | 上述服務的組合 |
--- 引用文件內容 ---
Content from @.cache/uv/simple-v20/pypi/pycryptodomex.rkyv:
無法顯示二進位檔案內容：.cache/uv/simple-v20/pypi/pycryptodomex.rkyv
Content from @.tmux/logs/memory-guardian.log:
[02/21 17:00:32] PRESSURE: level=35 (WARN<40 CRIT<15)
  --- P1: 可刪減應用程式 ---
  KILL Chrome 分頁 PID 989 (302MB)
  KILL Chrome 分頁 PID 90058 (226MB)
  KILL Chrome 分頁 PID 60600 (210MB)
  KILL Chrome 分頁 PID 5368 (192MB)
  KILL Chrome 分頁 PID 2166 (182MB)
  KILL Chrome 分頁 PID 10965 (174MB)
  KILL Chrome 分頁 PID 5883 (162MB)
  KILL Chrome 分頁 PID 44685 (158MB)
  KILL Chrome 分頁 PID 1874 (148MB)
  KILL Chrome 分頁 PID 6024 (140MB)
  KILL Chrome 分頁 PID 6251 (140MB)
  KILL Chrome 分頁 PID 34150 (126MB)
  KILL Chrome 分頁 PID 5887 (116MB)
  KILL Chrome 分頁 PID 50737 (112MB)
  KILL Chrome 分頁 PID 6439 (112MB)
  KILL Chrome 分頁 PID 32051 (112MB)
  KILL Chrome 分頁 PID 6523 (110MB)
  KILL Chrome 分頁 PID 5269 (104MB)
  KILL Chrome 分頁 PID 1294 (95MB)
  KILL Chrome 分頁 PID 13711 (74MB)
  KILL Chrome 分頁 PID 45506 (70MB)
  KILL LINE PID 413 (67MB)
  KILL AltServer PID 1884 (50MB)
  P1 結果：已刪除=23 釋放空間=3182MB
  P2+P3：已跳過 (僅 WARN 級別，Claude Code 受保護)
[02/21 17:00:32] 完成：總刪除=23 釋放空間≈3182MB
---
[02/22 01:12:54] PRESSURE: level=35 (WARN<40 CRIT<15)
  --- P1: 可刪減應用程式 ---
  KILL Chrome 分頁 PID 71759 (124MB)
  P1 結果：已刪除=1 釋放空間=124MB
  P2+P3：已跳過 (僅 WARN 級別，Claude Code 受保護)
[02/22 01:12:54] 完成：總刪除=1 釋放空間≈124MB
---
[02/22 11:36:23] PRESSURE: level=36 (WARN<40 CRIT<15)
  --- P1: 可刪減應用程式 ---
  KILL Chrome 分頁 PID 51400 (102MB)
  P1 結果：已刪除=1 釋放空間=102MB
  P2+P3：已跳過 (僅 WARN 級別，Claude Code 受保護)
[02/22 11:36:23] 完成：總刪除=1 釋放空間≈102MB
---
[02/22 11:37:23] PRESSURE: level=35 (WARN<40 CRIT<15)
  --- P1: 可刪減應用程式 ---
  KILL Chrome 分頁 PID 54259 (103MB)
  P1 結果：已刪除=1 釋放空間=103MB
  P2+P3：已跳過 (僅 WARN 級別，Claude Code 受保護)
[02/22 11:37:23] 完成：總刪除=1 釋放空間≈103MB
---
[02/23 18:12:44] PRESSURE: level=36 (WARN<40 CRIT<15)
  --- P1: 可刪減應用程式 ---
  KILL Chrome 分頁 PID 73668 (104MB)
  P1 結果：已刪除=1 釋放空間=104MB
  P2+P3：已跳過 (僅 WARN 級別，Claude Code 受保護)
[02/23 18:12:44] 完成：總刪除=1 釋放空間≈104MB
---
Content from @Library/Developer/Xcode/iOS DeviceSupport/iPhone16,2 26.2.1 (23C71)/Symbols/System/Library/PrivateFrameworks/MemoryAccounting.framework/MemoryAccounting:
無法顯示二進位檔案內容：Library/Developer/Xcode/iOS DeviceSupport/iPhone16,2 26.2.1 (23C71)/Symbols/System/Library/PrivateFrameworks/MemoryAccounting.framework/MemoryAccounting
---
