# Blueprint: FSM 顯式狀態管理導入

## Goal
將 Workshop 中 10 個隱式狀態機轉為顯式 FSM，使用 `python-statemachine` 3.0.0，整合 BaseCRUDService + EventBus。

## Architecture Decision

### 選型：python-statemachine 3.0.0
- 最新 release 2026-02-24，活躍維護
- 原生 async 自動偵測（配 FastAPI）
- 宣告式 API + Guard 條件 + Statechart 支援
- 內建圖形輸出

### 整合策略：FSMMixin + BaseCRUDService hook

```
before_update() → FSM.validate_transition(old, new)
    ├── 合法 → 繼續 update → after_update() → EventBus.publish(state_changed)
    └── 非法 → raise InvalidTransitionError (abort update)
```

### 設計原則
- Auth pending → active 需管理員審核（刻意設計，非 bug）
- 向後相容：DB 欄位保持 String，FSM 在服務層驗證
- 漸進導入：每個模組獨立，不影響其他模組

## Phases

### Phase 0: 基礎設施 (shared/fsm.py)
- T0.1: `uv add python-statemachine==3.0.0`
- T0.2: 建立 `core/src/shared/fsm.py`
  - `StatusEnum` base（str Enum，Pydantic 相容）
  - `FSMMixin` for BaseCRUDService（before_update guard + after_update event）
  - `InvalidTransitionError` 加入 WorkshopError 體系
  - `state_changed` event helper
- T0.3: 單元測試 `core/tests/shared/test_fsm.py`

### Phase 1: 高風險 FSM (Wave 1)
- T1.1: Auth — UserLifecycle
  - States: pending | active | suspended | banned
  - Transitions: approve(pending→active), suspend(active→suspended), ban(active|suspended→banned), reactivate(suspended→active)
  - Guard: approve 需 admin 權限
  - 注意：OAuth 用戶直接 active 是合法路徑（initial=active）
- T1.2: Briefing — BriefingLifecycle
  - States: searching | analyzing | debating | synthesizing | completed | failed
  - 線性流水線 + 任意態→failed
- T1.3: Nodeflow — FlowLifecycle
  - States: draft | active | paused | archived
  - Transitions: activate(draft→active), pause(active→paused), resume(paused→active), archive(active|paused→archived)
- T1.4: Nodeflow — FlowRunLifecycle
  - States: pending | running | completed | failed | cancelled
- T1.5: Nodeflow — NodeRunLifecycle
  - States: pending | running | completed | failed | skipped

### Phase 2: 中風險 FSM (Wave 2)
- T2.1: Finance — TransactionLifecycle (pending | completed | cancelled | scheduled)
- T2.2: Finance — SubscriptionLifecycle (active | paused | cancelled)
- T2.3: Finance — InstallmentLifecycle (active | completed | cancelled)
- T2.4: Briefing — EntryPhase (raw | analysis | debate | conclusion)
- T2.5: Briefing — FollowUpLifecycle (pending | answered)

### Phase 3: 整合與文件
- T3.1: EventBus 整合 — 每個 state_changed 自動 publish domain event
- T3.2: Audit 整合 — transition 記錄進 AuditLog
- T3.3: 圖形輸出 — 生成每個 FSM 的狀態轉移圖 (SVG/PNG)
- T3.4: 前端 — StatusBadge 元件依 FSM 定義顯示合法操作

## Parallel Execution Plan

```
Phase 0 (sequential — foundation)
  └── T0.1 → T0.2 → T0.3

Phase 1 (parallel — independent modules)
  ├── Agent A: T1.1 (Auth)
  ├── Agent B: T1.2 (Briefing)
  └── Agent C: T1.3 + T1.4 + T1.5 (Nodeflow)

Phase 2 (parallel — after Phase 1 verified)
  ├── Agent A: T2.1 + T2.2 + T2.3 (Finance)
  └── Agent B: T2.4 + T2.5 (Briefing extras)

Phase 3 (sequential — integration)
  └── T3.1 → T3.2 → T3.3 → T3.4
```

## Files to Create/Modify

### New Files
- `core/src/shared/fsm.py` — FSM infrastructure
- `core/src/modules/auth/lifecycle.py` — UserLifecycle
- `core/src/modules/briefing/lifecycle.py` — BriefingLifecycle + EntryPhase
- `core/src/modules/nodeflow/lifecycle.py` — Flow/FlowRun/NodeRun
- `core/src/modules/finance/lifecycle.py` — Transaction/Subscription/Installment
- `core/tests/shared/test_fsm.py`
- `core/tests/modules/*/test_lifecycle.py`

### Modified Files
- `pyproject.toml` — add dependency
- `core/src/shared/errors.py` — add InvalidTransitionError
- `core/src/modules/auth/services.py` — integrate FSMMixin
- `core/src/modules/briefing/services.py` — integrate FSMMixin
- `core/src/modules/nodeflow/services.py` — integrate FSMMixin
- `core/src/modules/nodeflow/engine.py` — use lifecycle for state transitions
- `core/src/modules/finance/services.py` — integrate FSMMixin

## Success Criteria
- [ ] 所有 10 個隱式狀態機轉為顯式 FSM
- [ ] 非法轉移（如 banned→active）被 FSM 攔截並回傳 400
- [ ] 每次狀態變更自動 publish EventBus domain event
- [ ] 每次狀態變更記錄 AuditLog
- [ ] 既有 API 行為不變（向後相容）
- [ ] 可生成狀態轉移圖
