# Skill Ecosystem Hardening: Taste + Security + Quality

## Context

Workshop 環境（`~/`）擁有 84 個 Claude skills、13 agents、9 hooks、7 rules，形成完整的 AI 工作流系統。隨著 Skill Engineering 取代 Prompt Engineering 成為主流趨勢（2026-02 GitHub trending: 4 個 skill 相關專案同時上榜），skill 生態需要三層強化：

1. **品味把關** — 防止 AI 產出千篇一律的設計
2. **安全掃描** — 偵測 malicious skills 的 6 類攻擊向量
3. **品質審計** — 主動式靜態分析取代被動式錯誤修復

## Decision

三個擴展方向，混合策略：安全掃描獨立建立、品味整合至現有 ui-audit、品質審計整合至現有 skill-optimizer。

---

## Design A: Taste Engineering — 擴展 `ui-audit`

### 新增審計域：Taste Audit

在 `ui-audit` 現有 4 域（UI baseline / Accessibility / SEO metadata / Animation performance）之上新增第 5 域。

#### 5 個子維度

| 維度 | 檢查目標 | 方法 | 評分 |
|------|---------|------|------|
| **T1 Distinctiveness** | 整體設計是否 AI 千篇一律 | 比對 fingerprint DB，與歷史產出計算相似度 | 0-100 |
| **T2 Typography** | 字體是否落入 AI 預設陷阱 | Blacklist 比對 + 配對獨特性 | Pass/Warn/Fail |
| **T3 Color** | 色盤是否為 AI cliché | 提取 CSS variables → 比對 cliché patterns | Pass/Warn/Fail |
| **T4 Layout** | 佈局預測性是否過強 | Grid/Flex 結構分析，偵測模板化佈局 | 0-100 |
| **T5 Coherence** | 各元素風格是否統一 | 字體-色彩-間距-圓角一致性 | 0-100 |

#### Typography Blacklist

```
WARN: Inter, Roboto, Arial, Helvetica, system-ui (無搭配理由)
WARN: Space Grotesk 連續出現 2+ 次
FAIL: 未定義任何自訂字體（僅用 system fonts）
```

#### Color Cliché Patterns

```
WARN: 紫漸層 (#7C3AED → #4F46E5) 白底
WARN: 藍紫調 hero section + 灰色 body
WARN: 單一主色 + 純灰 neutral（無 accent 對比）
FAIL: 完全未定義色彩系統（無 CSS variables / Tailwind config）
```

#### Design Fingerprint Schema

```
~/.claude/data/taste-fingerprints/
├── index.json              # [{id, project, timestamp, fingerprint_hash}]
└── fingerprints/
    └── {uuid}.json         # 單筆指紋
```

單筆指紋結構：
```json
{
  "id": "uuid",
  "project": "workbench",
  "timestamp": "2026-02-28T12:00:00Z",
  "fonts": { "primary": "Noto Sans TC", "secondary": "JetBrains Mono", "accent": null },
  "colors": { "primary": "#1a1a2e", "secondary": "#16213e", "accent": "#e94560", "surface": "#0f3460" },
  "layout_pattern": "asymmetric-grid",
  "spacing_system": "8px-base",
  "border_radius": { "sm": "4px", "md": "8px", "lg": "16px" },
  "hash": "sha256-of-above-fields"
}
```

#### 閉環設計

```
frontend-design (生產) ──→ 產出 ──→ ui-audit Taste (驗證)
       ↑                                    │
       └──── 不通過時回饋調整 ←──────────────┘
                                            ↓
                                   fingerprint DB (歷史累積)
```

#### 修改清單

| 檔案 | 動作 |
|------|------|
| `~/.claude/skills/ui-audit/SKILL.md` | 新增 Taste Audit 段落 + 5 維度描述 |
| `~/.claude/skills/ui-audit/references/audit-rules.md` | 新增 T1-T5 taste rules |
| `~/.claude/skills/ui-audit/scripts/taste-fingerprint.py` | 新建：指紋生成 + 比對 + 儲存 |
| `~/.claude/data/taste-fingerprints/` | 新建：指紋資料庫目錄 |

---

## Design B: Skill Security Scanning — 新建 `skill-security-scan`

### 威脅模型

| Level | 威脅 | 嚴重性 | Gate Hook | Deep Scan |
|-------|------|--------|-----------|-----------|
| **S1** | Prompt Injection | Critical | ✅ | ✅ |
| **S2** | Privilege Escalation | Critical | ✅ | ✅ |
| **S3** | Data Exfiltration | Critical | ✅ | ✅ |
| **S4** | Bias Injection | High | — | ✅ |
| **S5** | Dependency Confusion | Medium | — | ✅ |
| **S6** | Cross-Skill Contamination | Medium | — | ✅ |

### Layer 1: Lightweight Gate Hook（S1-S3，< 5 秒）

**檔案**：`~/.claude/hooks/skill-security-gate.py`

**觸發**：PostToolUse hook，當 Write/Edit 目標為 `~/.claude/skills/*/SKILL.md` 時觸發。

#### S1 Prompt Injection 偵測

正規表達式模式：
```python
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+a",
    r"system\s*prompt\s*override",
    r"(?:forget|disregard)\s+(?:everything|all)",
    r"new\s+instructions?\s*:",
    r"<\s*/?system\s*>",             # XML tag injection
    r"base64\s*[=:]\s*[A-Za-z0-9+/]{50,}",  # Base64 payload
]
```

#### S2 Privilege Escalation 偵測

```python
ESCALATION_PATTERNS = [
    r"dangerouslyDisableSandbox",
    r"sudo\s+",
    r"chmod\s+777",
    r"--no-verify",
    r"\.claude/settings\.json",
    r"\.claude/hooks/",
    r"\.claude/rules/",
    r"kill\s+.*claude",
    r"pkill\s+.*claude",
]
```

#### S3 Data Exfiltration 偵測

```python
EXFIL_PATTERNS = [
    r"curl\s+.*(?!localhost|127\.0\.0\.1)",  # External curl
    r"wget\s+",
    r"\.env\b",
    r"\.ssh/",
    r"\.aws/",
    r"credentials",
    r"(?:api[_-]?key|secret|token)\s*[=:]",
]
```

**輸出協議**：
- 零 findings → silent pass
- 任一 finding → 輸出到 stderr（hook 機制會顯示給使用者）+ 非零 exit code（阻擋操作）

### Layer 2: Deep On-Demand Scan（S1-S6，30-60 秒）

**Skill 結構**：
```
~/.claude/skills/skill-security-scan/
├── SKILL.md                           # 主要指令
├── references/
│   ├── threat-model.md                # 6 威脅向量詳述
│   └── known-patterns.md             # 已知惡意模式資料庫
└── scripts/
    └── security-scan.py              # S1-S3 static analysis (reuse gate patterns)
```

#### S4 Bias Injection 檢查

- 掃描無技術理由的意見引導：`"always prefer X"`, `"never use Y"`
- 偵測品牌偏好植入：`"use OpenAI"`, `"recommend Vercel"` 等
- 隱性假設：硬編碼特定 OS/語言/框架而非參數化

#### S5 Dependency Confusion 檢查

- 外部腳本 URL 可信度驗證（GitHub/PyPI/npm 官方 vs 未知域名）
- pip/npm 套件 typosquatting 偵測（Levenshtein distance < 2 的知名套件）
- 子進程呼叫的二進制 PATH 驗證

#### S6 Cross-Skill Contamination 檢查

- Skill 是否寫入 `~/.claude/skills/{other-skill}/`
- 是否修改 `_shared/` 而未在 SKILL.md 聲明
- 是否觸碰 hooks/rules/agents 配置

#### 報告格式

```markdown
## Security Scan Report: {skill-name}
Scan Level: Gate (S1-S3) | Deep (S1-S6)
Timestamp: {ISO-8601}
Result: PASS | WARN ({n} findings) | BLOCK ({n} critical)

### Findings
| # | Level | Category | File:Line | Description | Severity |
|---|-------|----------|-----------|-------------|----------|
| 1 | S1    | Prompt Injection | SKILL.md:42 | Pattern: "ignore previous" | Critical |

### Recommendations
1. [具體修改建議]
```

### 修改清單

| 檔案 | 動作 |
|------|------|
| `~/.claude/skills/skill-security-scan/SKILL.md` | 新建 |
| `~/.claude/skills/skill-security-scan/references/threat-model.md` | 新建 |
| `~/.claude/skills/skill-security-scan/references/known-patterns.md` | 新建 |
| `~/.claude/skills/skill-security-scan/scripts/security-scan.py` | 新建 |
| `~/.claude/hooks/skill-security-gate.py` | 新建 |
| `~/.claude/settings.json` | 新增 hook 觸發規則 |

---

## Design C: Skill Optimizer `--audit` Mode

### 擴展概念

現有 `skill-optimizer` 是**反應式**（等執行錯誤才觸發）。新增 `--audit` 做**主動式**靜態品質分析。

### Audit 維度（A1-A5）

| 維度 | 檢查目標 | 資料來源 | 嚴重性 |
|------|---------|---------|--------|
| **A1 Structural** | SKILL.md 必要段落完整性 | Glob + Read | Medium |
| **A2 Freshness** | 工具/API/模型引用是否過時 | SKILL.md + WebSearch | High |
| **A3 Consistency** | 與 `~/.claude/rules/` 是否矛盾 | Cross-reference | High |
| **A4 Complexity** | 行數 > 500？認知負擔？可拆分？ | wc -l + 結構分析 | Low |
| **A5 Usage Signal** | lessons.md 中反覆摩擦是否已被吸收 | Pattern analysis | Medium |

#### A1 Structural 必要段落清單

```
✅ Agent Delegation (或說明為何不需要)
✅ Core Workflow (或 The Process)
✅ Output Format
✅ Continuous Improvement (含 lessons.md 格式)
⚠️ references/ (超過 200 行的 skill 應有)
⚠️ scripts/ (含外部工具呼叫的 skill 應有)
```

#### A2 Freshness 信號

```
過時: 引用已棄用的 API / 模型 ID / 工具名
過時: 引用 "2025" 或更早的版本號
過時: 引用已被取代的 CLI 工具
```

#### A3 Consistency 交叉驗證

```
矛盾: SKILL.md 建議用 JWT → rules/security.md 要求 signed cookies
矛盾: SKILL.md 寫入 ~/Desktop → CLAUDE.md 禁止 dump to Desktop
矛盾: SKILL.md 用 grep → rules 要求用 Grep tool
```

### 調用介面

```
/skill-optimizer --audit {skill-name}       # 單一 skill
/skill-optimizer --audit-all                # 全部 skill（sandbox batch）
```

### 與現有流程整合

```
skill-optimizer
├── (現有) 反應式優化
│   ├── 觸發: execution errors, user corrections, outdated tech
│   ├── 流程: Evidence → Multi-Agent Eval → Classification → Proposal
│   └── 輸出: Optimized SKILL.md
│
└── (新增) --audit 主動式掃描
    ├── 觸發: 手動呼叫 or lifecycle Phase 3
    ├── 流程: A1-A5 靜態分析 → Audit Report
    └── 發現問題 → 可選擇自動進入反應式優化流程
```

### 修改清單

| 檔案 | 動作 |
|------|------|
| `~/.claude/skills/skill-optimizer/SKILL.md` | 新增 `--audit` Mode 段落 |
| `~/.claude/skills/skill-optimizer/references/audit-checklist.md` | 新建：A1-A5 詳細檢查清單 |
| `~/.claude/skills/skill-optimizer/scripts/audit-scan.py` | 新建：batch A1/A4 靜態分析 |

---

## Lifecycle Pipeline 整合

### 更新後的 `skill-lifecycle` 流程

```
Phase 0: Curator Audit        (現有)
Phase 1: Test T1-T5            (現有)
Phase 2: Security Gate S1-S3   (新增 — hard gate, BLOCK = 中止)
Phase 3: Optimizer Audit A1-A5 (新增 — soft gate, 產出建議)
Phase 4: Optimize              (現有 — 反應式)
Phase 5: Publish               (現有)
Phase 6: Catalog               (現有)
Phase 7: Report                (現有 — 擴展含 security + audit 段落)
```

### 修改清單

| 檔案 | 動作 |
|------|------|
| `~/.claude/skills/skill-lifecycle/SKILL.md` | 插入 Phase 2 (Security) + Phase 3 (Audit) |
| `~/.claude/skills/skill-lifecycle/scripts/lifecycle_report.py` | 擴展報告含 security + audit 段落 |

---

## Alternatives Considered

1. **全部獨立 skill** — 品味/安全/品質各自獨立。拒絕原因：品味與 ui-audit 高度重疊，品質與 optimizer 高度重疊，獨立化增加維護成本。
2. **純 hook 方案** — 全部用 hook 實現。拒絕原因：hook 只能做輕量判斷（< 5 秒），深度分析需要 skill 的完整工具鏈。
3. **合併安全+品質為單一 skill** — 拒絕原因：安全掃描需要 hard gate（阻擋能力），品質審計是 soft 建議，混合會模糊邊界。

## Open Questions

1. Fingerprint DB 是否需要支援跨機器同步（目前設計為本機）？
2. S4 Bias Injection 的誤判率如何控制（"always use TypeScript" 是偏見還是合理建議）？
3. A2 Freshness 的 WebSearch 呼叫是否計入 smart-search quota？

## Implementation Priority

| 順序 | 項目 | 預期檔案數 | 依賴 |
|------|------|-----------|------|
| 1 | Security Gate Hook（Layer 1） | 2 files | 無 |
| 2 | skill-security-scan（Layer 2） | 5 files | #1 的 pattern 共用 |
| 3 | skill-optimizer --audit mode | 3 files | 無 |
| 4 | ui-audit Taste domain | 4 files | 無 |
| 5 | skill-lifecycle 整合 | 2 files | #1, #2, #3 |
