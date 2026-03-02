# P10 — Agent Organization：動態虛擬人力體系

> **Status**: RFC（Request for Comments）
> **Author**: 少爺 + 四輪十六路 AI 辯論
> **Date**: 2026-03-02
> **Depends on**: P1-memvault（KAS）, P6-taskflow（Quest）, tmux-relay, Agent Vista
> **Nature**: Usage Pattern（使用模式），非獨立 Core Module

---

## 1. 願景

將 LLM CLI 的**專案配置層**（CLAUDE.md / MEMORY.md / rules / skills）當作**輕量人格容器**，
建立一個可動態雇用、解雇、擴縮的虛擬人力組織。

**核心命題**：不是提升 LLM 能力，而是透過**行為約束 + 記憶累積 + 精準派工**，
讓 solo developer 擁有一支可組合的專家團隊。

---

## 2. 架構決策紀錄（ADR）

### ADR-1: 角色 = 行為約束，非能力提升

模型權重不會改變。CLAUDE.md 的規則改變的是：
1. **注意力分配**（rules 限縮關注範圍）
2. **知識累積**（KAS memory 等效於工作筆記本）
3. **行為一致性**（persona 確保跨 session 風格穩定）

**決策**：角色定義聚焦「不做什麼」（邊界約束）而非「知道什麼」（能力宣告）。

### ADR-2: Self-Managed KAS（N ≤ 4 時自管，N > 4 時加中央稽核）

每個 agent 透過獨立 `space_id` 擁有自己的 KAS 記憶空間，自行決定記什麼、刪什麼。

**依據**：經濟學分析顯示 N ≤ 4 時自管 KAS 的風險溢價可接受（~500 tokens/月 節省 vs ~5,000 tokens/月 風險成本）；
N > 4 時引入 Venn 月度巡檢（邊際成本 2,000 tokens，壓腐化風險至 2%）。

### ADR-3: 3 核心 + 彈性池的混合人力模型

| 類型 | 角色 | 存續期 |
|------|------|--------|
| 核心（永久） | backend, frontend, reviewer | 永不解雇 |
| 彈性（按需） | legal, accountant, designer, PM... | 依專案雇用/解雇 |

**依據**：經濟學分析 — 核心角色閒置門檻 26 個月，保留比重雇便宜；
彈性角色閒置 4 週後考慮解雇。

### ADR-4: Venn 是 Optional 層

Venn（orchestrator）是調度層，不是強制瓶頸。Specialists 可直接被呼叫。
當任務路由不複雜時，少爺可跳過 Venn 直接指派。

### ADR-5: 職業不寫死，動態配置

角色不是固定的軟體團隊。任何職業都是 Knowledge × Skills × Attitude 的組合：
- 會計師 = 財稅知識 + 報表 skill + 謹慎態度
- 法律顧問 = 法規知識 + 合約審查 skill + 引用判例態度
- 客服 = 產品知識 + 溝通 skill + 耐心態度

可以有多個同職業 agent（如 2 個 frontend），各自累積不同的領域記憶。

---

## 3. 系統架構

### 3.1 整體拓撲

```
少爺
  ↓ 交代需求
維恩 (Venn) — Orchestrator [Opus, optional layer]
  ├── 拆解任務 → Quest Board（taskflow）
  ├── 派工 → Agent（tmux-relay pane 或 headless sub-agent）
  ├── 收結果 → 彙整回報
  └── Knowledge Relay → Bulletin Board

Agent Pool
  ├── 核心：backend:alpha, frontend:alpha, reviewer:alpha
  ├── 彈性：legal:temp-001, designer:alpha, ...
  └── 每個 agent 擁有獨立 KAS space_id

Quest Board（taskflow 擴充）
  ├── 所有 agent 可見任務列表
  ├── assigned_agent + weight + capacity
  └── 被動指派 + 主動認領

Meeting Mode（tmux-relay Tier 3）
  ├── Venn 主持，拉相關 agents 進入共享 context
  ├── 限時 15 分鐘，token 預算 ~6,000
  └── 結果寫入各 agent KAS + bulletin
```

### 3.2 目錄結構

```
~/workshop/
  experts/                          # 新增頂層目錄
    _templates/                     # Role Template YAML + CLAUDE.md
      software-backend.yaml
      software-frontend.yaml
      legal-advisor.yaml
      accountant.yaml
      customer-service.yaml
      _schema.yaml
    _scripts/
      agent-hire.py                 # 入職：seed KAS from template
      agent-archive.py              # 離職：匯出 + 更名 space_id
      agent-audit.sh                # 稽核：掃描 memory health
    README.md

~/.claude/agents/                   # Agent persona 定義
  venn.md                           # Orchestrator
  workshop-backend.md               # Backend specialist
  workshop-frontend.md              # Frontend specialist
  workshop-reviewer.md              # Code reviewer
  # 彈性角色按需建立

~/.claude/data/agent-memory/        # 輕量 file-based memory（補充 KAS）
  venn/context.md
  backend/context.md
  frontend/context.md
```

### 3.3 KAS Memory 命名空間

```
space_id 命名規範：
  agent:{role}:{instance}           # 在職 agent
  archived:{role}:{instance}        # 已解雇 agent（保留 90 天）
  bulletin:shared                   # 公告欄（Venn 寫，所有人讀）

範例：
  agent:backend:alpha               # 主力後端
  agent:frontend:alpha              # 前端 #1
  agent:frontend:beta               # 前端 #2（擴編）
  agent:legal:temp-001              # 臨時法務
  archived:legal:temp-001           # 已解雇法務
```

每個 agent 的 tmux pane 啟動時：
```bash
export MEMVAULT_SPACE_ID="agent:backend:alpha"
```
現有 `mcp/memvault/server.py` 已讀取此 env var，**零程式碼改動**。

---

## 4. Self-Managed KAS Protocol

### 4.1 Session Start

```
1. memvault_recall(query="今日工作背景", mode="cascade", max_results=5)
2. memvault_profile() — 確認 KAS/Attitude/Skill 狀態
3. 結果放入 working memory，不輸出給 user
```

### 4.2 After Each Task — 選擇性記憶

判斷標準（任一符合即記憶）：
- 遇到未預料的技術問題且找到解法
- 系統行為與自己的 Triple 記憶不符
- 產生新的 pattern 或決策原則
- 某工具或指令有非預期副作用

寫入流程：
```
1. memvault_recall(query=<即將記的主題>) — Contradiction Check
2. 若矛盾：舊記憶 confidence < 0.6 → 刪舊寫新；否則兩者並存，各降 0.1 confidence
3. memvault_extract(content=<摘要>, block_type=knowledge|skill|attitude)
4. memvault_kg_upsert_triple(subject, predicate, object)
5. 若涉及偏好改變 → memvault_attitude_evolve(...)
```

### 4.3 Anti-Entrenchment Safeguard（最關鍵護欄）

- **寫入前必須先 recall**（防止自我強化錯誤）
- 任務成功 → 不直接歸因，先排除運氣成分
- 連續 3 次相同 Triple → 合併為單一高 confidence 記憶
- 同一 category 超過 2 個 CONFLICTED → 觸發人工確認

### 4.4 Weekly Self-Audit

```
recall(all, max=50) →
  - 30 天未引用 + confidence < 0.5 → 刪除
  - subject="self" 且描述過時技術 → 更新或刪除
  - 某 predicate 有 10+ objects → 只留 top-5 by confidence
  - 寫入 ("self", "last_audited", "YYYY-MM-DD")
```

### 4.5 Cross-Agent Knowledge Relay（公告欄機制）

```
Agent A 發現跨域知識 → 自己 KAS 加 tag relay:pending
→ Venn 定期 search relay:pending tags
→ 評估相關性 → 寫入 bulletin:shared
→ 各 agent session start 時 recall bulletin:shared
```

---

## 5. 人力生命週期

### 5.1 入職（Hiring）

```bash
# 1. 從 template 建立 KAS 種子記憶
uv run python3 experts/_scripts/agent-hire.py software-backend alpha

# 2. 建立 agent persona 定義
cp experts/_templates/software-backend.CLAUDE.md ~/.claude/agents/workshop-backend.md
# 手動調整 persona 細節

# 3. 設定 tmux pane 環境
export MEMVAULT_SPACE_ID="agent:backend:alpha"
```

雇用成本：~13,000 tokens + ~55 分鐘人工。2 個任務即回本。

### 5.2 在職（Working）

- Self-Managed KAS Protocol（§4）
- Quest Board 被動指派 + 主動認領
- Meeting Mode 參與（被 Venn 召集時）

### 5.3 離職（Firing）

```bash
# 1. 匯出 KAS 快照
uv run python3 experts/_scripts/agent-archive.py backend alpha

# 2. space_id 重命名：agent:backend:alpha → archived:backend:alpha
# 3. 90 天後自動清理
```

三級歸檔制：
| 等級 | 內容 | 去處 |
|------|------|------|
| L1 Hot | 進行中任務上下文 | 移交繼任者 |
| L2 Warm | 近 90 天高頻記憶 | 壓縮後存 Team Space |
| L3 Cold | 歷史決策軌跡 | archive 表，可召回 |

### 5.4 繼承（Rehiring with Inheritance）

```bash
# 從前任記憶繼承（只繼承 confidence ≥ 0.7 且非 CONFLICTED）
uv run python3 experts/_scripts/agent-hire.py backend beta --inherit=alpha
```

---

## 6. Quest Board 整合（taskflow 擴充）

### 6.1 Schema 擴充

```python
class Quest(SpaceScopedModel):
    # 現有欄位...
    assigned_agent: str | None        # agent:backend:alpha
    weight: float = 1.0               # 任務複雜度（1-10）
    token_budget: int | None          # Token 上限
    token_used: int | None            # 實際消耗
    claimed_at: datetime | None       # 主動認領時間
    parent_quest_id: str | None       # 動態拆分的父子關係
```

### 6.2 動態任務分配

```
Venn 派工邏輯：
  routing_score = skill_match * 0.6 + available_capacity_ratio * 0.4
  若 skill_match < 0.5 → 觸發 Meeting Mode
  若 weight > 7 → 自動拆分為子任務
  若 dispatch_timeout > 30min → escalate to 少爺
```

### 6.3 Reward 定義（效能追蹤，非遊戲化）

```python
reward = base_xp(100) + time_bonus + budget_bonus - quality_penalty
# 用途：追蹤哪個 agent 最省 token、最快完成、品質最高
# 顯示在 Agent Vista 的 Team Panel
```

---

## 7. 跨 CLI 支援現況

| 能力 | Claude Code | Codex CLI | Gemini CLI |
|------|:-----------:|:---------:|:----------:|
| 結構化持久記憶 | ✅ 原生 | ❌ 需 MCP | ⚠️ 手動 |
| Hooks 生命週期 | ✅ 17 事件 | ❌ 無原生 | ✅ 10 事件 |
| Agent Persona | ✅ agents/*.md | ⚠️ 有限 | ⚠️ 預覽中 |
| Skills 系統 | ✅ 完整 | ✅ 近等效 | ✅ via Extension |
| Self-Managed KAS | ✅ space_id | ❌ | ❌ |

**結論**：Claude Code 是唯一全面支援此體系的 CLI。Gemini CLI ~70%，Codex CLI ~50%。

---

## 8. 成本模型

| 場景 | 每任務 Tokens | vs 通才 |
|------|:------------:|:-------:|
| 通才 Agent | ~18,000 | baseline |
| 專才 Agent（dispatch） | ~8,000 | -55% |
| 專才 Agent（meeting） | ~25,000 | +39% |

- **損益平衡**：每 agent ≥ 2 任務即回本雇用成本
- **最優規模**：3 核心 + 2 彈性 = 5 常駐上限
- **Meeting 頻率**：每週 3-5 次（保持稀有，Dispatch 是日常路徑）
- **月節省估算**（15 tasks/day）：~150,000 tokens/day = ~4.5M tokens/month

---

## 9. 風險矩陣

| 風險 | 嚴重度 | 緩解措施 | 觸發點 |
|------|:------:|---------|--------|
| Memory Rot | 🔴 | Weekly Self-Audit + Anti-Entrenchment | Day 1 內建 |
| 知識孤島 | 🔴 | Bulletin Board + cross-cutting reviewer | 設計原則 |
| Venn 瓶頸 | 🟡 | Venn = optional；specialists 可直接呼叫 | 設計原則 |
| 配置幻覺 | 🟡 | 角色約束「不做什麼」而非宣告「知道什麼」 | ADR-1 |
| 複雜度爬升 | 🔴 | Phase 0 驗證 Δ > 10% 才進 Phase 1 | Gate |
| Token 失控 | 🟡 | token_budget per quest + 超出 50% 自動停止 | Phase 1 |
| N×M 維護 | 🟡 | Template system + sync-config 自動化 | Phase 1 |

---

## 10. 實施路線圖

### Phase 0：Proof of Concept（零程式碼，今天開始）

**目標**：驗證 Venn + 1 Specialist > 單 agent

- [ ] 建 `~/.claude/agents/venn.md` + `workshop-backend.md`
- [ ] 建 `~/.claude/data/agent-memory/{venn,backend}/`
- [ ] 選一個真實小任務，用 Venn + Backend 跑一次
- [ ] 量化：wall time、token count、output quality vs 單 agent

**Gate**：Δ < 10% → 停止；Δ > 30% → 進 Phase 1

### Phase 1：Core Team（2-3 週）

**目標**：3 核心 agent + Quest Board 整合

- [ ] 建 `workshop-frontend.md` + `workshop-reviewer.md`
- [ ] taskflow schema 擴充（assigned_agent, weight, token_budget）
- [ ] Alembic migration
- [ ] `experts/_templates/` 建 2 個 YAML template
- [ ] `experts/_scripts/agent-hire.py`
- [ ] Token budget enforcement

### Phase 2：Dynamic Workforce（4-6 週）

**目標**：動態雇用/解雇 + Meeting Mode

- [ ] `agent-archive.py`（離職 + 繼承）
- [ ] Meeting Mode protocol（tmux-relay based）
- [ ] Bulletin Board（`bulletin:shared` space_id）
- [ ] `space_id_override` MCP 參數（~3 行改動）
- [ ] Agent Vista Team Panel
- [ ] Reward tracking（效能指標，非遊戲化）

### Phase 3：Self-Improving（8 週+）

**目標**：agents 自動精煉記憶 + 角色演化

- [ ] `agent-audit.sh` 自動化（cron 每週日）
- [ ] Team Performance Report（Venn 月產出）
- [ ] Agent 升遷機制（junior → senior by KAS 累積）
- [ ] 新 Specialist 孵化流程

---

## 11. 辯論紀錄摘要

本文件基於三輪並行辯論（12 個 AI agents，6 種立場）的結論。

**Round 1**（Project = Expert）：
- Advocate 最強論點：記憶複利效應 + Git 版本化知識
- Skeptic 最強論點：約束 ≠ 能力提升 + Memory Rot

**Round 2**（Virtual Team + Venn）：
- 組織理論最強洞察：Constrained Autonomy + Conway's Law 可為我用
- 魔鬼最強攻擊：同模型開會 = 劇場（反駁：不同 context = 不同輸出）

**Round 3**（Dynamic Workforce + Self-Managed KAS）：
- HR 最強洞察：角色即不可變設定，記憶才是可變資產
- 經濟學最強數據：專才每任務省 ~10,000 tokens，混合模型最優
- 魔鬼最強攻擊：複雜度爬升 — 用 Phase Gate 控制
- KAS 架構師最強洞察：Anti-Entrenchment Safeguard 是最關鍵護欄

**Round 4**（Hierarchy + Multi-Corp + Integration）：
- 組織架構師洞察：P10 不是第 11 個模組，是 OS kernel（routing + orchestration logic）
- 整合分析師關鍵發現：taskflow V2 schema 應提前鎖定（assigned_agent, weight, token_budget）
- 魔鬼最強攻擊：Second System Effect — 四輪膨脹後觸頂反彈
- 戰略顧問最強結論：P10 是使用模式（Usage Pattern），不是獨立模組

**最終判決**：值得建設，但須嚴格控制範圍。Phase 0 驗證是不可跳過的門檻。

---

## 12. 明確排除項（Round 4 決議）

以下概念經四輪辯論後**明確排除**，除非未來出現明確觸發條件：

| 排除項 | 理由 | 重新考慮的觸發條件 |
|--------|------|-------------------|
| 部門階層（組長/VP） | 5 agents 不需要 org chart，每層加 ~2,000 tokens 路由稅 | 常駐 agent > 10 個 |
| 多公司/集團結構 | 命名慣例偽裝成架構，零附加價值 | 真正需要跨組織隔離 |
| XP/Reward 遊戲化 | Agent 無動機，用簡單 token 追蹤替代 | 需要向第三方展示 agent 績效 |
| P10 作為 Core Module | 不需要新 DB schema、新 API endpoint | 超過 3 個模組需要 agent routing 事件 |
| 自動任務拆分 | 需要元智慧，LLM 無可靠的自我容量感知 | 有了穩定的 weight scoring 模型 |

## 13. 先行鎖定項（供其他模組實作時參考）

以下設計在 P10 實作前就應納入其他模組的 schema 規劃：

### taskflow V2 預留欄位

```python
# core/src/modules/taskflow/models.py — V2 migration 時一起加
assigned_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
weight: Mapped[float] = mapped_column(Float, server_default=text("1.0"))
token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
token_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
parent_quest_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

### 事件預留

```python
# core/src/events/types.py — 預留命名空間
class AgentOrgEvents:
    AGENT_HIRED      = "agentorg.agent.hired"
    AGENT_FIRED      = "agentorg.agent.fired"
    QUEST_DISPATCHED = "agentorg.quest.dispatched"
    MEETING_STARTED  = "agentorg.meeting.started"
    BULLETIN_POSTED  = "agentorg.bulletin.posted"
```

### space_id 長度驗證

`SpaceScopedModel.space_id` 為 `String(32)`。最長預期值 `archived:frontend:beta` = 23 chars，安全。
命名規範限制：`{prefix}:{role}:{instance}` 總長 ≤ 32。

## 14. 與現有模組的整合介面

P10 是 Usage Pattern，但其他模組建設時應預留這些介面：

| 模組 | 整合介面 | 實作時機 |
|------|---------|---------|
| **memvault** | `MEMVAULT_SPACE_ID` env var → 已原生支援 | ✅ 今天可用 |
| **taskflow** | `assigned_agent` + `weight` + `token_budget` 欄位 | V2 migration 時 |
| **auth** | 短期不需要改動；中期可加 `user_type = "agent"` | Phase 2+ |
| **Agent Vista** | `AgentTracker` 接收 `agentorg.*` 事件 | Phase 1 |
| **notification** | 訂閱 `taskflow.task.completed` 推送 | P8 建好後 |
| **finance** | Quest token_used → `finance.transaction` | Phase 2 |
| **intelflow** | 研究任務委派 agent | 自然整合，無需改動 |
| **session-archiver** | 加 `agent_space_id` 欄位索引 | Phase 2 |
