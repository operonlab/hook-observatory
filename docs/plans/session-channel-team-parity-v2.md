# Session-Channel ↔ Team Agent Parity 補強計畫 v2

> v2 修訂於 2026-04-25（v1 經 4 路 review 後重寫）
>
> 五個方向性決策：
> 1. **核心架構改用 Redis Streams 原生 consumer group**（XREADGROUP / XCLAIM / XAUTOCLAIM / XACK），丟棄自寫 Lua CAS
> 2. **Lease 分級**（short/llm/video），不再一刀切
> 3. **新增 SDK Client**（`SessionChannelClient`）統一介面
> 4. **新增 Frontend Board Panel**（驗收標準需要）
> 5. **新增 Test/Metrics/Rollback 章節**

---

## 一、戰略原則

1. **單一 worktree**：`feature/session-channel-team-parity-v2` 分支，避免 merge 地獄
2. **波次序列、波內並行**：每 wave 結束 → commit + 驗證 → 下一波
3. **Streams 原生優先**：能用 XREADGROUP/XCLAIM/XAUTOCLAIM/XACK 就不寫 Lua
4. **Schema-first**：先定 schema 再實作；schema 帶 `task_class` 決定 lease 行為
5. **YAGNI**：P2 視實際工作流再做

---

## 二、Wave 分配

### Wave 1 — 基礎建設（並行 3 worker，全新檔零衝突）

| ID | 工作 | 檔案 | Owner |
|----|------|------|-------|
| W1-A | **Capability Registry** — cli-rosetta + mcpproxy.json 整合，advertise pane 能力 | 新增 `pane_routes.py`、改 `hook-observatory/handlers/session_channel.py` | worker-A |
| W1-B | **Schema 契約 + Lease 分級** | 新增 `schemas.py`，含 TaskClass enum, lease config | worker-B |
| W1-C | **SDK SessionChannelClient** — 從 tmux_relay 抽出 + 補 heartbeat/progress 介面 | 新增 `libs/sdk-client/sdk_client/session_channel.py` | worker-C |

**驗證閘**：unit test schema；CLI 寫一筆 advertise + read；SDK client 跑 publish/claim/complete。

---

### Wave 2 — Streams 原生 Board v2（序列，動同檔）

| ID | 工作 | 檔案 |
|----|------|------|
| W2-A | **Board v2 — XREADGROUP claim + XACK complete + lease class**：建立 consumer group、claim 改 XREADGROUP+XAUTOCLAIM 一刀、complete 改 XACK | 改 `board_routes.py`，**移除 board_lua.py**（保留檔案做向後 import safe，內容清空+棄用警告） |
| W2-B | **XAUTOCLAIM Reaper + Heartbeat**：背景 task 5s 一次 XAUTOCLAIM 把 idle > lease 的 pending 轉到 `__reaper` consumer + SSE 廣播 release；heartbeat endpoint 走 XCLAIM 重置 idle |
| W2-C | **Stop Hook 自動 release**：擴充 hook handler，pane 結束時把該 pane 所有 pending 用 XCLAIM 給 reaper |
| W2-D | **tmux_relay SDK 對齊**：改 `libs/sdk-client/sdk_client/tmux_relay.py:1666-1720` 五個 helper 對應新 API（task_class、heartbeat、progress） |

**驗證閘**：殺 pane 進程 → lease 過期 → XAUTOCLAIM 自動釋放；lease 分級正確（short/llm/video）；既有 tmux_relay caller 不破。

---

### Wave 3 — 觀測性 + Capability Routing（並行 4 worker）

| ID | 工作 | 檔案 | Owner |
|----|------|------|-------|
| W3-A | **Progress Events** — XADD tag=progress 訊息 + projection 補 progress/stage/last_seen | 新增 `projections/progress.py`、改 `board_routes.py` | worker-E |
| W3-B | **Capability-aware Claim** — API 層校驗（**不放 Lua，避免 Cluster CROSSSLOT**）；不符 caps 拒絕 + 回傳 missing_caps | 改 `board_routes.py` claim path、`pane_routes.py` 提供 caps lookup | worker-F |
| W3-C | **Result Schema 強制 + projection 摘要** — done payload 結構化（status/payload/tokens/duration），projection 顯示 result | 新增 `projections/result.py`、改 `cli/channel.py` | worker-G |
| W3-D | **Frontend Board Panel + Progress UI** — `templates/index.html` 加 board view + progress bar + capability badge + lease 倒數 | 改 `templates/index.html` + 內嵌 JS | worker-H |

**注意**：W3-A/B/C 都會碰 `_build_projection`——透過 projections/ 子模組拆檔避免衝突，**主檔只 import + compose**。

**驗證閘**：dashboard 即時 progress；不符 caps pane claim 被拒；result 摘要正確顯示；前端視覺化正確。

---

### Wave 4 — 進階工作流（視需求並行/序列）

| ID | 工作 | 檔案 | Owner |
|----|------|------|-------|
| W4-A | **Task Assignment** — publish 時帶 `assigned_to`，consumer group 用 hash slot 路由（一個 pane = 一個 consumer name） | 改 `board_routes.py`、`schemas.py` | worker-I |
| W4-B | **Dependency DAG** — `deps:{task_id}` set，前置 done 時 `SREM` 並在歸零時 XADD 釋放下游 | 改 `board_routes.py`、新增 `dag.py` | worker-J |
| W4-C | **Retry / Failed + Dead-letter Stream** — XAUTOCLAIM 累積 delivery_count，超閾值轉 `board:{id}:failed` stream | 改 `board_routes.py`，補 schema | worker-K |
| W4-D | **P2P + Ack**（可選，視需求） — `mailbox:{pane}` topic + ack endpoint | 改 `routes.py`、`cli/channel.py` | worker-L |

**驗證閘**：DAG 解鎖；retry 三次落 dead-letter；assignment 校驗。

---

### Wave 5 — 品質保證（並行 3 worker，可與 Wave 4 並行）

| ID | 工作 | 檔案 | Owner |
|----|------|------|-------|
| W5-A | **Test Suite** — 100 併發 XREADGROUP 競搶；fake clock 測 lease；SIGKILL chaos；50 pane × 1k task 壓測 | 新增 `tests/test_board_v2.py`、`tests/test_concurrency.py`、`tests/test_chaos.py` | worker-M |
| W5-B | **Metrics + Observability** — Prometheus counters: lease_expired_total / claim_conflict_total / orphan_recovered_total / projection_ms / xread_lag_ms / heartbeat_latency_ms; structured log 帶 board_id/task_id/pane/attempt | 新增 `metrics.py`、改 `main.py` 註冊 `/metrics` endpoint | worker-N |
| W5-C | **Rollback Runbook + Backup 命令** — 寫具體 redis-cli 命令清單；feature flag `BOARD_V2=1` 切換新舊路徑（過渡期保留） | 新增 `docs/runbooks/session-channel-rollback.md`、改 `config.py` | worker-O |

---

## 三、並行作戰圖

```
時序  ─────────────────────────────────────────────────────►

Wave 1  [W1-A capability]  [W1-B schema]  [W1-C sdk]
        ─ A 並行 ────── ─ B 並行 ────── ─ C 並行 ────┐
                                                       │
                            commit + 驗證 ◄───────────┘
                                                       │
Wave 2  [W2-A streams]  →  [W2-B reaper]  →  [W2-C hook]  →  [W2-D tmux_relay]
        序列（動同檔 board_routes.py）─────────────────────┐
                                                            │
                            commit + 驗證 ◄───────────────┘
                                                            │
Wave 3  [W3-A progress] [W3-B caps] [W3-C result] [W3-D fe]│
        ─ E ── F ── G ── H 並行（projections/ 子模組隔離）─┐│
                                                          ││
                            commit + 驗證 ◄───────────────┘│
                                                            │
Wave 4  [W4-A] [W4-B] [W4-C] [W4-D-optional] ──┐           │
        並行（schemas.py 已分離）              │           │
                                                ▼           │
Wave 5  [W5-A test]  [W5-B metrics]  [W5-C runbook]        │
        並行 ──── 可與 Wave 4 同時推進 ─────────────────────┘
```

---

## 四、關鍵實作決策（v2 版）

### 4.1 Streams 原生 board

```python
# 取代 board_lua.py CLAIM_TASK_LUA
async def claim_task(redis, board_id: str, pane: str, count: int = 1):
    """Atomic claim via XREADGROUP — Redis 原生 exactly-once."""
    group = f"board-{board_id}"
    stream = f"ws:channel:board:{board_id}"

    # 確保 consumer group 存在（idempotent）
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    # 嘗試先撈 idle pending（自動 reassign）
    autoclaim = await redis.xautoclaim(
        stream, group, pane,
        min_idle_time=lease_ms_for_class(...),  # 依 task_class
        start_id="0-0", count=count,
    )
    if autoclaim[1]:  # claimed messages
        return autoclaim[1]

    # 否則撈新訊息
    new = await redis.xreadgroup(group, pane, {stream: ">"}, count=count, block=0)
    return new
```

### 4.2 Lease 分級（schemas.py）

```python
class TaskClass(str, Enum):
    SHORT = "short"   # 一般 CRUD、簡單腳本
    LLM = "llm"       # LLM 推理、長 RAG
    VIDEO = "video"   # 影片處理、長批次

LEASE_CONFIG = {
    TaskClass.SHORT: {"lease_seconds": 30, "heartbeat_seconds": 10},
    TaskClass.LLM:   {"lease_seconds": 300, "heartbeat_seconds": 90},
    TaskClass.VIDEO: {"lease_seconds": 1800, "heartbeat_seconds": 600},
}
```

### 4.3 Capability Registry（W1-A）

```python
# Redis Hash: ws:panes:{pane_id} → JSON({cli_type, mcps, skills, started_at, last_seen})
# TTL: 5 min;  HEXPIRE 7.4+ per-field 不用，整 key 用 EXPIRE
# Source of truth:
#   - cli_type ← cli-rosetta detect_from_command(pane_current_command)
#   - mcps ← read ~/.mcpproxy/mcp_config.json
#   - skills ← scan ~/.claude/skills/ (cached)
```

### 4.4 SDK SessionChannelClient（W1-C）

```python
# libs/sdk-client/sdk_client/session_channel.py
class SessionChannelClient:
    def publish_board(self, board_id: str, tasks: list[TaskPublish]) -> None: ...
    def claim_task(self, board_id: str, pane: str, count: int = 1) -> list[Task]: ...
    def heartbeat(self, board_id: str, task_id: str) -> None: ...
    def progress(self, board_id: str, task_id: str, percent: int, stage: str) -> None: ...
    def complete(self, board_id: str, task_id: str, result: TaskResult) -> None: ...
    def advertise(self, pane: PaneAdvertise) -> None: ...
    def get_board(self, board_id: str) -> BoardProjection: ...
```

### 4.5 Reaper（W2-B）

```python
async def _reaper_loop(redis):
    """XAUTOCLAIM idle pending → __reaper consumer → SSE 廣播 release."""
    while True:
        await asyncio.sleep(5)
        for board_id in active_boards:
            stream = f"ws:channel:board:{board_id}"
            group = f"board-{board_id}"
            for task_class, cfg in LEASE_CONFIG.items():
                claimed = await redis.xautoclaim(
                    stream, group, "__reaper",
                    min_idle_time=cfg["lease_seconds"] * 1000,
                    start_id="0-0", count=100,
                )
                # 廣播 release（dedup：只廣播 delta）
                for msg_id, fields in claimed[1]:
                    if fields.get("task_class") == task_class.value:
                        sse_broadcast({"topic": f"board:{board_id}", "tag": "release", "task_id": msg_id})
```

### 4.6 Stop Hook 自動 release（W2-C）

```python
# hook-observatory/handlers/session_channel.py Stop handler
def _release_pane_pending(pane_id: str):
    """Pane 結束時，把該 pane 所有 pending 用 XCLAIM 給 __reaper consumer。"""
    # XPENDING ws:channel:board:* (use SCAN active boards)
    # 對每個 board 做 XCLAIM <stream> <group> __reaper 0 <ids>
    # 不被 SessionStop debounce 影響（獨立 path）
```

---

## 五、風險與 Rollback（v2 補強）

### 風險表

| 風險 | 緩解 |
|------|------|
| Streams 原生路徑 bug 比自寫 Lua 多踩坑 | feature flag `BOARD_V2=1` 過渡期保留舊路徑；W5-A 100 併發測試 |
| 既有 board v1 資料 migration | v1 是 Redis Streams + claims hash，v2 直接拋棄 claims hash 用 consumer group；migration 寫腳本掃 v1 stream → 重建 group + XCLAIM 給對應 pane |
| Cluster mode 跨 slot | v2 全部資料在 `ws:channel:board:{id}` 單 key family（一個 stream + 一個 group），無 CROSSSLOT |
| 4 個背景 task failure cascade | W5-B 加 `BackgroundTaskSupervisor` 含指數退避 + health gauge |

### Rollback 命令清單（W5-C 詳寫）

```bash
# Wave 2 commit 前
redis-cli BGSAVE
cp /opt/homebrew/var/db/redis/dump.rdb /tmp/redis-pre-w2-$(date +%Y%m%d-%H%M).rdb

# Rollback Wave 2
git revert <w2-commit-sha>
redis-cli BGREWRITEAOF
launchctl kickstart -k gui/$(id -u)/com.workshop.session-channel

# 緊急 rollback（保留資料但切回 v1 邏輯）
echo 'BOARD_V2=0' >> /opt/homebrew/etc/session-channel.env
launchctl kickstart -k gui/$(id -u)/com.workshop.session-channel
```

---

## 六、驗收標準（v2 強化）

完成後必須能：
1. 開 3 個 pane（CC + Codex + Gemini），各自 SessionStart 自動 advertise capabilities
2. publish 一個 board，含 5 個 task，混合 task_class（2 short / 2 llm / 1 video），其中 2 個有 `required_caps: ["memvault"]`
3. 只有具 memvault MCP 的 pane 能 claim 那 2 個
4. 殺其中一個 pane（kill -9）：
   - 4a. 若 claim 的是 short class，30s 內 task 自動回到 open
   - 4b. 若 claim 多個 task，逐個依各自 lease 釋放，不一次清空
5. 另一 pane 主動發送 progress：dashboard board panel 即時更新進度條 + 倒數 lease
6. complete task 時帶 `{status: ok, payload: {...}, tokens_used: 1234, duration_ms: 8765}`，board projection 顯示 result 摘要
7. publish 含 DAG，A 完成才解鎖 B；retry 3 次後 task 落 `board:{id}:failed` stream
8. Frontend 顯示：board panel + 每 task 的 progress / capability badge / lease 倒數
9. `/metrics` endpoint 暴露 6 個指標：lease_expired_total, claim_conflict_total, orphan_recovered_total, projection_ms, xread_lag_ms, heartbeat_latency_ms
10. Test 通過：100 併發 XREADGROUP 不重複交付；fake clock SIGKILL chaos；50 pane × 1k task 壓測 P99 < 200ms

---

## 七、移除/取代 v1 內容

| v1 章節 | v2 處理 |
|---------|---------|
| Lua CAS CLAIM_TASK_LUA / DROP_TASK_LUA | 棄用，board_lua.py 留檔棄用警告 |
| 自寫 reaper loop with HDEL | 改 XAUTOCLAIM |
| 自寫 lease_until 欄位 | 改 idle time（XPENDING 自帶） |
| ws:board:claims:{id} hash | 改 consumer group pending entries |
| 全域 90s lease | 分級（30/300/1800） |
| ws:panes 加進 Lua KEYS[2] | 移除，caps 校驗放 API 層 |
