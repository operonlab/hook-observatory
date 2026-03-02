---
archived_from: ~/Claude/projects/kas-memory/2026-02-16-kas-growth-loops.md
status: reference (archived)
note: V1 原始設計文件。Growth Loop 1 (Knowledge Flywheel) 和 6.4 (Confidence Decay) 已在 V2 實作。
migrated_at: 2026-02-26
---

# Memvault Growth Loops — 三維成長迴路設計

> 日期：2026-02-16
> 狀態：部分實作完成（V2 已實作 Loop 1 + Confidence Decay）
> 觸發：少爺洞察 — Memvault 不應只提煉對話，Skill 使用應越來越熟練，Knowledge 應累積，Attitude 應校準

---

## 核心問題

Memory 提煉（對話 → 記憶）已完成，但三個維度缺乏成長機制：

| 維度 | 現狀 | 缺口 |
|------|------|------|
| Knowledge | 只從對話提煉 | Skill 產出的知識沒有回流（例如 /smart-search 的研究結果） |
| Skill | SKILL.md 靜態定義 | 沒有使用頻次、成功率、偏好追蹤、熟練度演化 |
| Attitude | CLAUDE.md 固定人設 | 互動偏好沒有動態校準機制 |

---

## Growth Loop 1: Knowledge Flywheel（知識飛輪）✅ V2 已實作

> **V2 實作**：`skill-tracker-v2.sh` 擴展 — 知識 skill 產出自動存為 `skill_knowledge` block，
> 搭配 `ConfidenceDecayService` 實現信心衰減。

### 觸發源
任何產出知識的 skill 調用：
- /smart-search（研究結果）
- /content-writer（寫作中的引用與事實）
- /company-intel, /competitive-intel（商業情報）
- /brainstorming（決策結論）
- /meeting-insights（會議洞見）

### 流程
```
Skill 執行 → 產出結果
                ↓
         抽取關鍵事實（Entity、Relation、Fact）
                ↓
         打 tag + 評估置信度 + 存入 Knowledge Store
                ↓
         所有 Skill 都能透過語義搜尋查詢
```

### 設計考量
- **保鮮期**：技術知識半衰期短，需要 `confidence_decay` 機制
  - 新鮮度 = f(建立時間, 領域衰減率)
  - 技術: 180 天半衰期
  - 偏好: 90 天半衰期
  - 原則: ~100 年（實質永久）
  - workflow: 120 天 / tool_behavior: 150 天 / config: 120 天 / architecture: 365 天
- **去重**：同一個事實可能從多次搜尋中出現，需要合併而非重複
- **溯源**：每條知識連結回原始 skill 調用 + session ID

### 範例
```
第 1 次 /smart-search "MCP protocol"
  → 存入: MCP = Model Context Protocol, by Anthropic, 2024
  → tag: [mcp, protocol, anthropic]

第 5 次 /smart-search "MCP server development"
  → recall 先前知識 → 不必重新解釋 MCP 是什麼
  → 新增: MCP server 用 TypeScript, @modelcontextprotocol/sdk
  → 知識圖譜自動豐富化

第 10 次相關任務
  → 已有 MCP 小型知識庫 → 能做深層交叉參照
```

---

## Growth Loop 2: Skill Proficiency Model（技能熟練度）🔲 待後續迭代

### 三個層次

| 層次 | 名稱 | 內容 | 現狀 |
|------|------|------|------|
| L1 | 程序熟練 | 知道 happy path，不犯已知坑 | ✅ SKILL.md + MEMORY.md |
| L2 | 偏好熟練 | 記住用戶對此 skill 的使用習慣 | ❌ 需要新建 |
| L3 | 創意熟練 | 基於經驗主動建議更好做法 | ❌ 需要 L2 數據 + 推理 |

### 數據結構
```json
{
  "type": "skill_proficiency",
  "skill": "diagram-gen",
  "total_uses": 23,
  "recent_uses": 5,
  "success_rate": 0.83,
  "common_patterns": [
    "architecture diagrams for README",
    "flowcharts for debugging"
  ],
  "learned_preferences": {
    "theme": "github-light --transparent",
    "output_format": "SVG with HTML wrapper",
    "naming": "YYYY-MM-DD-{desc}.svg"
  },
  "pitfalls_encountered": [
    {"issue": "subgraph literal quotes", "times": 2, "resolution": "known limitation, use workaround"},
    {"issue": "bare SVG URL timeout", "times": 1, "resolution": "use HTML wrapper"}
  ],
  "evolution_notes": [
    "2026-02: User prefers transparent background for docs",
    "2026-02: Switched from default to github-light theme"
  ]
}
```

### 成長指標
- **熟練度指數** = f(使用次數, 成功率, 坑回避率, 偏好穩定度)
- **新手** (0-5 次): 照 SKILL.md 走，保守執行
- **熟練** (5-20 次): 開始套用已知偏好，跳過基礎解釋
- **專家** (20+ 次): 主動建議優化，預判需求

---

## Growth Loop 3: Attitude Calibration（態度校準）🔲 待後續迭代

### 哲學立場
人設（阿福 + 賈維斯 + 奇異博士）是**固定的骨架**。
校準是**在骨架內微調肌肉**。

### 可校準維度

| 維度 | 低 ← → 高 | 信號來源 |
|------|-----------|---------|
| proactivity | 等指令 ← → 預判 | 「你自己判斷」vs「先問我」 |
| verbosity | 詳盡 ← → 精簡 | 「太長了」/ 要求展開 |
| risk_tolerance | 保守 ← → 嘗新 | 對新工具/方法的接受度 |
| autonomy | 每步確認 ← → 全權 | deny 頻率、授權模式 |
| challenge | 順從 ← → 推回 | 讚賞推回 vs 拒絕推回 |
| depth | 表面 ← → 深挖 | 追問頻率、「再深入一點」 |

### 校準機制
- **顯性記錄 + 半隱性執行**
  - 校準結果存在 Memvault Profile（`memvault_profile` 工具）
  - 不是每次都報告，自然地表現
  - **重大校準才提報**：「少爺，我注意到您最近偏好 X，已調整」
- **信號收集**：
  - 顯性：用戶明確表達偏好（「以後都這樣做」）
  - 隱性：deny 頻率、重新修改頻率、讚賞信號
  - 元信號：連續 N 次某個維度觸發同方向 → 達到校準閾值

### 態度 vs 情境
重要：態度校準應該是**情境敏感**的：
- 工作模式 → 高自主、高效率、低冗餘
- 學習模式 → 高詳盡、高挑戰、低自主（多問多教）
- 創意模式 → 高冒險、高自主、中詳盡

---

## Flywheel Effect: K × A × S

```
     ┌─── Knowledge ◄──── Skill output feeds back
     │    (what I know)
     │         │
     │    enriches inputs
     │         ▼
     │    Skill Proficiency
     │    (what I can do well)
     │         │
     │    calibrates delivery
     │         ▼
     └─── Attitude
          (how I deliver)
               │
          optimizes what to learn next
               │
               └──── back to Knowledge
```

三者複合 = **Expertise（專精）**

---

## 與 V2 架構的整合

### 可復用的基礎設施
- ✅ Memvault MCP Server（`mcp/memvault/`）
- ✅ 語義搜尋（Ollama nomic-embed-text + pgvector）
- ✅ Tag 系統（已支援任意 tag）
- ✅ Memvault Profile 工具
- ✅ Core API（`/api/memvault/kg/*` 端點）
- ✅ Cascade Recall（L2→L1→L0→blocks 分層檢索）

### V2 實作狀態

| # | 項目 | 狀態 | 說明 |
|---|------|------|------|
| 1 | Knowledge Flywheel | ✅ | `skill-tracker-v2.sh` 自動擷取知識 skill 產出 |
| 2 | Confidence Decay | ✅ | `ConfidenceDecayService` + `/kg/decay` API + pipeline |
| 3 | Skill Proficiency L2 | 🔲 | 待後續迭代（需偏好分析邏輯） |
| 4 | Attitude Calibration | 🔲 | 待後續迭代（需行為數據積累） |
| 5 | Galaxy Widget | 🔲 | 待前端開發 |

### 實作優先級
1. ~~**Knowledge Flywheel**（最高 ROI — 直接讓每個 skill 更聰明）~~ ✅ 已完成
2. **Skill Proficiency L2**（偏好追蹤 — 減少重複溝通）
3. **Attitude Calibration**（最微妙，需要最多數據才有意義）

---

## 開放問題

1. **Knowledge 粒度**：一條知識應該多細？太粗失去精度，太細搜尋噪音大
2. ~~**衰減函數**：線性 vs 指數？領域特定衰減率怎麼設？~~ → ✅ 已實作指數衰減 + 分類半衰期
3. ~~**Skill 使用追蹤的 Hook 點**~~ → ✅ PostToolUse (Skill) hook + `/kg/skills/invoke` API
4. **態度校準的 ground truth**：怎麼知道校準對了？需要定期 checkpoint + 確認嗎？
5. **跨 CLI 一致性**：如果 foreman 用了 Gemini CLI 和 Codex CLI，它們的 skill 使用也該納入嗎？
