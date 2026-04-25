# Cross-CLI Dispatch — tmux-relay × session-channel 整合指南

## 一、架構速覽

```
Supervisor (TmuxRelayClient.dispatch_via_board)
   │
   ├─ XADD ws:channel:board:{id}     ← publish
   ▼
Session-Channel Board (consumer group)
   │
   ▼ XREADGROUP（atomic claim + caps + assignment + DAG check）
┌──────────┬────────────┬────────────┐
│ CC pane  │ Codex pane │ Gemini pane│
│ memvault │  docvault  │ paper-skill│
│ intelflow│            │            │
└──────────┴────────────┴────────────┘
   │
   ├─ heartbeat (XCLAIM JUSTID)
   ├─ progress (XADD tag=progress)
   ├─ complete (XACK + XADD tag=done)
   └─ on exit: DELETE /api/panes/{id}
```

## 二、三種 pane 接入方式

### 1. CC pane（有 SessionStart hook）
spawn 後**自動** advertise——`TmuxRelayClient.spawn()` 結尾呼 `advertise_pane()`，
hook handler `~/.claude/hooks/...session_channel.py` 也獨立 advertise。

### 2. Codex / Gemini / 其他 CLI（無 hook）
用 `pane-wrapper.sh` 包：

```bash
~/workshop/stations/session-channel/scripts/pane-wrapper.sh \
  --cli-type codex --pane-id pane-codex-1 -- codex
```

或結合 `board-worker.sh` 跑 claim loop：

```bash
pane-wrapper.sh --cli-type codex --pane-id pane-codex-1 -- \
  board-worker.sh --board my-board --pane pane-codex-1
```

wrapper 行為：
- spawn 前 POST `/api/panes/advertise`（讀 `~/.mcpproxy/mcp_config.json` mcps + `~/.claude/skills/` skills）
- 失敗不擋啟動（warn to stderr 即可）
- `trap EXIT INT TERM → DELETE /api/panes/{id}`

### 3. SDK 自寫 worker（Python）
```python
from sdk_client.session_channel import SessionChannelClient, PaneAdvertise

c = SessionChannelClient()
c.advertise(PaneAdvertise(
    pane_id="my-worker", cli_type="claude-code",
    mcps=["memvault"], skills=["forge"],
    started_at=int(time.time()), last_seen=int(time.time()),
))
# claim loop ...
```

## 三、開 3 pane tmux 跑

```bash
# 啟動 station（若還沒啟）
launchctl kickstart -k gui/$(id -u)/com.workshop.session-channel

# 開 tmux session
tmux new-session -d -s relay-demo

# 三個 pane 分別跑不同 CLI（每個用 wrapper 包）
tmux send-keys -t relay-demo \
  "pane-wrapper.sh --cli-type claude-code --pane-id demo-cc -- claude" Enter
tmux split-window -t relay-demo
tmux send-keys -t relay-demo \
  "pane-wrapper.sh --cli-type codex --pane-id demo-codex -- codex" Enter
tmux split-window -t relay-demo
tmux send-keys -t relay-demo \
  "pane-wrapper.sh --cli-type gemini --pane-id demo-gem -- gemini" Enter

# attach 看
tmux attach -t relay-demo
```

## 四、Supervisor 派工

```python
from sdk_client.tmux_relay import TmuxRelayClient

relay = TmuxRelayClient()
result = relay.dispatch_via_board("my-board", [
    {"id": "t1", "desc": "memvault recall", "task_class": "short",
     "required_caps": ["memvault"]},
    {"id": "t2", "desc": "docvault QA", "task_class": "short",
     "required_caps": ["docvault"]},
    {"id": "t3", "desc": "any pane works", "task_class": "short"},
], sender="my-supervisor")

# Capability-aware claim 由 server 自動完成：
# - t1 只 CC pane (memvault) 能拿
# - t2 只 Codex pane (docvault) 能拿
# - t3 任意 pane 能拿
```

## 五、清理

```bash
# DELETE pane registry entries
for p in demo-cc demo-codex demo-gem; do
  curl -X DELETE "http://localhost:10101/api/panes/$p" \
    -H "x-local-key: $(cat /opt/homebrew/etc/session-channel.env | grep KEY | cut -d= -f2)"
done

# Kill tmux session
tmux kill-session -t relay-demo

# Redis 清掉測試 board（optional）
redis-cli --scan --pattern 'ws:channel:board:my-board*' | xargs redis-cli DEL
redis-cli DEL ws:board:logical:my-board ws:board:deps:my-board:*
```

## 六、驗收檢查

```bash
# 1. capability registry
curl -s http://localhost:10101/api/panes -H "x-local-key: $KEY" | jq

# 2. board projection (capability routing 結果)
curl -s http://localhost:10101/api/board/my-board -H "x-local-key: $KEY" | jq .summary

# 3. metrics
curl -s http://localhost:10101/metrics | grep -E '^session_channel_'
```

## 七、性能參考（真 Redis 壓測）

| 場景 | Panes | Tasks | 完成 | 吞吐 | P50 | P95 | P99 |
|------|-------|-------|------|------|-----|-----|-----|
| Light | 5 | 50 | 46/50 | 1.5/s | 3 ms | 4 ms | 4 ms |
| Production | 10 | 200 | 195/200 | 6.5/s | 6 ms | 20 ms | **42 ms** |
| Heavy | 50 | 1000 | 1000/1000 | 89/s | 116 ms | 547 ms | 1011 ms |

Latency 是「claim→complete」處理延遲。**Production-like (5-10 panes) P99 < 50ms**。
50 panes 同時打單 process FastAPI station 時 P99 退化是預期；
正式部署若需更高並行，可開 `uvicorn --workers N`（注意 prometheus_client 多 process 需 `prometheus_multiproc_dir`）。

## 八、Known Limitations

### 1. Cap-restricted task 在 cap-poor pool 會 stall
**情境**：task 帶 `required_caps=["docvault"]`，但所有 docvault pane 已被佔用，
其他 pane 拿到後走 reject + republish 路徑——hot-loop 反覆。

**緩解**：
- worker 端 reject 收到 `caps_mismatch` 後 sleep ≥ 0.5s（已寫進 `board-worker.sh` 與 `stress_real_redis.py`）
- 不要設 cap-restricted 比例 > 30%
- 確保至少 2 個 pane 含對應 cap

**根因修補（未做）**：server 端 cap reject 改 `XCLAIM __cap_holder` 保留 PEL（與 W4-B blocked 同模式），
配合定期釋放 routing。工程量大，留給 v3。

### 2. `max_stream_len` 預設 500 — 大批量 publish 會被 trim
1000 task 一次 publish 會被 trim 到 500，後 500 失去。

**緩解**：`config.yaml` 改 `max_stream_len: 20000`，或分批 publish ≤ 500 + 等消化。

### 3. `prometheus_client` 單 process 模式
station 用單 uvicorn worker 跑時 OK；多 worker 模式需另設 `prometheus_multiproc_dir`。

### 4. SIGKILL pane 靠 reaper lease 釋放
hook trap EXIT 在正常結束跑得到；mosh 斷線、`kill -9`、jetsam 被殺等情境，
靠 server 端 reaper（lease=30s for short / 5min for llm / 30min for video）兜底。

## 九、故障排除

| 症狀 | 檢查 |
|------|------|
| `pane not found` | pane TTL 5 min；advertise 後超時 → 重新 advertise |
| 所有 claim 回 `caps_mismatch` | `/api/panes/{pane_id}` 看 mcps/skills 是否正確 |
| Task 永遠 stuck claimed | 看 `lease_expired_total`；可能 worker 卡死沒 heartbeat |
| Dead-letter 累積 | `/api/board/{id}/failed` 看 retry_count；`board:{id}:failed` stream 可手動清 |
| dispatch_via_board 回 `board_unreachable` | `SESSION_CHANNEL_URL` env / station 健康檢查 |

## 十、相關檔案

- `libs/sdk-client/sdk_client/tmux_relay.py` — `TmuxRelayClient.dispatch_via_board / advertise_pane / release_pane`
- `libs/sdk-client/sdk_client/session_channel.py` — `SessionChannelClient` 16 method
- `stations/session-channel/scripts/pane-wrapper.sh` — universal advertise wrapper
- `stations/session-channel/scripts/board-worker.sh` — claim/heartbeat/progress/complete loop
- `stations/session-channel/scripts/stress_real_redis.py` — 性能壓測
- `stations/session-channel/examples/cross_cli_dispatch.py` — 完整 demo
- `docs/runbooks/session-channel-rollback.md` — rollback 程序
