# memvault × claude-obsidian 蠶食實作計畫

**狀態**: Phase 1（並行 1-4）規劃中
**蠶食來源**: AgriciDaniel/claude-obsidian (Karpathy LLM Wiki pattern)
**蠶食評估報告**: 見 intelflow + memvault KG（tags: cannibalization, deep, claude-obsidian）
**三 Agent 交叉審查**: reviewer (adversarial) + explorer (memvault 實地驗證) + researcher (Letta/Mem0/Zep 對標) 收斂

---

## 設計原則校準

1. **拿組織原則，不拿引擎** — claude-obsidian 的價值是「把 agent memory 組織成可持續增長的 wiki」這套腳本，不是技術
2. **不照抄 boundary_score 公式** — 用既有 PPR，學界 Entropy Variation / PPR-from-frontier 更成熟
3. **不照抄 4AM cron** — Letta sleeptime 模型更 reactive
4. **驗證機制 > prompt 聲明** — extractive 約束需要 post-hoc verifier，不是寫在 prompt 裡

---

## Phase 1：並行 1-4

### 共同 Boundary（所有 worker 必遵守）
- 只能改 `core/src/modules/memvault/` 內檔案
- 不可改其他 module（auth/admin/intelflow 等）
- 不可改 alembic migration（migration 只在 Mac 主機跑，由 Jones 手動）— **改 schema 必須開 follow-up issue 給 Jones 跑 migration**
- 必跑 `ruff check` + module test
- 必寫單元測試
- 完成後在 worktree commit，**不要 push、不要 merge**，把 worktree path + branch name 回報

---

### Worker 1 — Frontier 信號聚合層

**branch**: `feature/memvault-cann-1-frontier-aggregator`

**目標**：聚合既有三股訊號為單一 frontier score，提供 `top N 該想什麼` 排序。

**檔案**：
- 新建 `core/src/modules/memvault/frontier.py`
- 新增 route `/api/memvault/frontier/top` 在 `routes.py`
- 加 SDK method `frontier_top()` 在 `libs/sdk-client/sdk_client/clients/memvault_client.py`
- 加 CLI `memvault frontier top` 在 `core/cli/memvault.py`

**公式**：
```
score(node) = PPR_centrality(node)          # 來源: dream.py:222-247 hub_entities
            × log(out_degree + 1)            # 避免 hub 暴衝
            × exp(-days_since_updated / 30)  # recency decay
            × knowledge_gap_bonus            # 來源: InterestSnapshot.knowledge_gaps (models.py:183-204)
```

**禁止**：
- 不可改 dream.py
- 不可改 PPR 計算邏輯本身（讀就好）

**Effort**: 半天

**驗收**：
- `curl /api/memvault/frontier/top?n=5` 回 5 個 node + score
- 單元測試覆蓋公式邊界（孤立節點、超 stale、knowledge_gap 為空）

---

### Worker 2 — Verifier-Backed Extractive Fold + Dual-Key

**branch**: `feature/memvault-cann-2-fold-verifier`

**目標**：修 Dream Loop Phase 3 consolidate stage 的真實冪等 gap（explorer 確認 dual-gate 只 coarse）。

**檔案**：
- 改 `core/src/modules/memvault/dream.py` 的 `_consolidate` 方法
- 新建 `core/src/modules/memvault/fold_verifier.py`
- 改 `models.py`：`SynthesisBlock`（或對應表）加 `fold_id` 和 `content_hash` 欄位
  - **注意**：schema 變更需開 follow-up issue 給 Jones 跑 alembic migration
- 加 unit test

**設計**：
```python
fold_id = sha256(sorted(children_block_ids))[:16]   # 子集合穩定性
content_hash = sha256(consolidate_output_text)[:16]  # 內容穩定性

# 冪等規則：
# - fold_id 同 + content_hash 同 → skip
# - fold_id 同 + content_hash 異 → 用最新覆蓋（child 內容漂移）
# - fold_id 異 → 新 fold

# Verifier（post-hoc，不是 prompt 聲明）
for sentence in fold_output.split('.'):
    if not (substring_match(sentence, children) or 
            embedding_match(sentence, children, threshold=0.85)):
        reject(sentence)  # 拒絕無 grounding 的句子
```

**Pre-write conflict detection**（Mem0 風格）：
- consolidate 寫入前對 KG 跑一次 LLM contradiction check（呼叫既有 lint.check_contradictions）
- 有衝突則 quarantine（write-side injection guard 已有的 pattern）

**禁止**：
- 不可改 lint.py（worker 3 的領地）
- 不可改 sleeptime 觸發邏輯（worker 4 的領地）

**Effort**: 2-3 天

**驗收**：
- 同 children + 同 content 重跑 → 0 新增 row
- 同 children + 不同 content（手動觸發 child update）→ 覆蓋舊 fold
- 注入無 grounding 句子 → 被 verifier 拒絕

---

### Worker 3 — Knowledge Lint v2 Task 9（10 checks）

**branch**: `feature/memvault-cann-3-lint-task9`

**目標**：補完 lint.py 的 10 項檢查（目前只見 contradiction 一層）。

**檔案**：
- 擴充 `core/src/modules/memvault/lint.py`
- 新建 `core/src/modules/memvault/lint_checks/` 目錄，每項 check 一個檔
- 加 lint report endpoint `/api/memvault/lint/report`
- CLI: `memvault lint run`

**10 項檢查**（對照 wiki-lint）：
1. Orphan blocks（無入連結的 block）
2. Dead triples（指向不存在 entity 的 triple）
3. Stale claims（date-based：源頭 source 比 newer source 老 N 天且斷言衝突）
4. Missing entities（多 block 提及但無自己的 entity 頁）
5. Missing cross-refs（entity 名出現但無 link）
6. Metadata gaps（frontmatter 缺必填欄）
7. Empty content（block 內容過短或空）
8. Stale index entries（index 指向已刪/改名 block）
9. Stable ID validity（UUID 格式 + 唯一性）
10. Semantic tiling dedup（embedding 相似度跨 block 超閾值）

**禁止**：
- 不可改 dream.py（worker 2 的領地）
- 不可動 sleeptime（worker 4 的領地）
- 不可自動 fix，**只 report**（claude-obsidian wiki-lint 也是只 report）

**Effort**: 2 天

**驗收**：
- 10 個 check 各自單元測試
- `memvault lint run` 出完整 report markdown
- Report 分 critical / warning / suggestion 三檔

---

### Worker 4 — Sleeptime Reflection Agent

**branch**: `feature/memvault-cann-4-sleeptime`

**目標**：每 N capture 觸發背景 reflection，跑 health-check + 更新 hot snapshot 占位（hot snapshot 本體 worker 5 做）。

**檔案**：
- 新建 `core/src/modules/memvault/sleeptime.py`
- 改 `core/src/modules/capture/events.py` 或 memvault 的 capture event handler，加 counter + trigger
- 新增 settings `MEMVAULT_SLEEPTIME_INTERVAL`（預設 5 captures）
- 新建 placeholder `MemoryBlock` table 雛形（persona/human/project，各 ~150 words）— **schema 變更需開 follow-up migration issue**

**設計**：
```python
# 每 N capture event 觸發
async def maybe_trigger_sleeptime(capture_count: int):
    if capture_count % settings.SLEEPTIME_INTERVAL != 0:
        return
    asyncio.ensure_future(_run_sleeptime())

async def _run_sleeptime():
    # 1. 跑 lint health-check（依賴 worker 3 的 lint.run，先用 stub）
    findings = await lint.run_health_check()
    # 2. 更新 multi-block hot snapshot 占位
    await update_block("project", recent_summary())
    # 3. 紀錄 sleeptime_run event
```

**禁止**：
- 不可改 dream.py 的 _consolidate 邏輯（worker 2 的領地）
- 不可實作完整 hot snapshot（worker 5 的範圍），這裡只放 placeholder

**Effort**: 3 天

**驗收**：
- 第 N 個 capture 觸發 sleeptime（用 mock event 驗）
- sleeptime 跑完寫 `sleeptime_run` 紀錄
- multi-block table 有 3 row（persona/human/project）

---

## Phase 2：完成後評估 Worker 5（Multi-Block Hot Snapshot）

**評估要點**：
- 1-4 完成後，看實際 KG 漂移程度 + sleeptime block 更新效果，再決定是否做完整 hot snapshot
- 主要不確定性：snapshot vs PPR cache 衝突、snapshot vs write-side injection guard 重複攔截

---

## 衝突管理

### 已知 dream.py 共用點
- Worker 2 改 `_consolidate`
- Worker 4 在 dream.py 加一個 import 觸發 sleeptime

**緩解**：兩 worker 對 dream.py 的修改採函式級隔離。Merge 時先 merge worker 2，再 rebase worker 4，預期手動 resolve 一處 import 區塊衝突。

### Migration 處理
- Worker 2、4 都會動 schema → **不在 worker 內跑 migration**
- 每個 worker 完成後，把所需 schema 變更寫進 `migrations/manual/<branch-name>.sql` + 開 follow-up issue 給 Jones

---

## 完成後 Merge 順序

1. Worker 1（無依賴）
2. Worker 3（無依賴）
3. Worker 2（修 dream.py）
4. Worker 4（rebase 過 worker 2 後 merge）
5. 評估是否做 Worker 5

---

## Phase 1 驗收門檻
- 4 worker 全綠（ruff + test）
- 4 worker 都產出 worktree path + branch name
- 衝突點手動 resolve 後跑全 module test 全綠
