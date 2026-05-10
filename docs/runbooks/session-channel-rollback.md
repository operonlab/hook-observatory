# Session Channel — Rollback Runbook

> 適用版本：session-channel v0.2 (Wave 1-5, Streams 原生 consumer group)
> 對應計畫：`docs/plans/session-channel-team-parity-v2.md` § 五 風險與 Rollback
> 最後更新：2026-05-10

> ⚠️ **Tier 1 已失效（2026-05-10）**：`BOARD_V2` feature flag 已從 `config.py` 移除，`board_lua.py` v1 路徑亦已刪除。下方 Tier 1 章節保留供歷史參考，**實務上請直接從 Tier 2（Git Revert）開始**。原因：v1 Lua CAS 早在 v2 穩定後即進入 placeholder 狀態，flag 切換實際無 v1 程式碼可運行，留著是「假的安全網」。要 rollback 就 `git revert` 整段 v2 commits 然後重啟。

本 runbook 提供分層 rollback 策略，從快（git revert，~5 分鐘）到最徹底（Redis state restore，~20 分鐘）。

---

## 何時需要 Rollback

任一情況觸發即考慮 rollback：

- v2 board 出現 stuck task：`XPENDING` 顯示有 entry 卻沒人 reap，`/api/board/{id}` 顯示 task 卡 claimed 超過 lease 上限
- Projection 異常：dashboard 顯示 progress / result 與實際 stream 內容不符
- Reaper 失控：`reaper_loop` 一直 XAUTOCLAIM 同一筆，`orphan_recovered_total` 暴衝
- 現場 pane 大量 claim 被誤判 caps mismatch（W3-B 校驗 bug）
- launchctl 無法重啟 station：卡循環啟停（`launchctl print` 看 `last exit code`）
- background task supervisor 健康度持續 unhealthy

---

## 快速判斷（10 秒 triage）

```bash
# 1. 看 health
curl -s http://localhost:10101/health | jq

# 2. 看 redis 主 stream
BOARD_ID=<your-board-id>
redis-cli XINFO STREAM "ws:channel:board:$BOARD_ID"
redis-cli XPENDING "ws:channel:board:$BOARD_ID" "board-$BOARD_ID"

# 3. 看 station log（最近 100 行）
tail -100 ~/Library/Logs/workshop/session-channel.log

# 4. 看 metrics 是否露指標
curl -s http://localhost:10101/metrics | grep -E 'lease_expired|claim_conflict|orphan_recovered' | head
```

判讀：
- `XPENDING` 看到 `min-idle-time` 巨大、但 `delivery_count` 還在累加 → reaper 失控
- `/health` 回 redis=false 或 200 但 topics=空 → 連線層問題，先看 redis-server
- log 反覆出現同一 `task_id` 的 `XCLAIM error` → 進 Tier 2

---

## Rollback Tier 1 — Feature Flag 切換（30 秒）⚠️ DEPRECATED（2026-05-10）

> ❌ **本章節已失效**：`BOARD_V2` flag 已從 `config.py` 移除，`board_lua.py` v1 實作亦已刪除。下方指令執行後 station 不會切回 v1，只會抱怨找不到 env var 或直接無變化。**請改用 Tier 2 — Git Revert。** 以下原始流程僅供歷史參考。

**前提**（已不成立）：`config.py` 已加 `BOARD_V2` flag（W5-C 已完成），且 v1 路徑在 `board_routes.py` 仍保留分支（過渡期）。

**用途**：v2 路徑 bug 但 v1 程式碼還在 → 不需 git revert，直接切舊邏輯。

```bash
# 1. 確認 launchd 環境檔位置
ENVFILE=/opt/homebrew/etc/session-channel.env
test -f "$ENVFILE" || sudo touch "$ENVFILE"

# 2. 寫入 flag（移除既存的 BOARD_V2 行）
sudo sed -i '' '/^BOARD_V2=/d' "$ENVFILE"
echo 'BOARD_V2=0' | sudo tee -a "$ENVFILE" >/dev/null

# 3. 重啟 station（kickstart 不會卡循環）
launchctl kickstart -k "gui/$(id -u)/com.workshop.session-channel"

# 4. 等 3 秒確認
sleep 3 && curl -s http://localhost:10101/health | jq
```

**驗證**：

```bash
# Station log 應該顯示 "BOARD_V2=False" 或類似訊息
grep -i "board_v2" ~/Library/Logs/workshop/session-channel.log | tail -5
```

**回滾本次切換**：把 `BOARD_V2=0` 改回 `BOARD_V2=1` 重啟即可。

---

## Rollback Tier 2 — Git Revert（5 分鐘）

**前提**：feature flag 也壞掉（v1 分支也踩到雷）或 v1 程式碼已被刪除。

```bash
WT=~/workshop/.claude/worktrees/feature+session-channel-team-parity-v2

# 1. 找 Wave 1/2/3 commits（從新到舊 revert）
git -C "$WT" log --oneline --all | grep -E "Wave [123]|W[123]-[A-Z]" | head -20

# 2. Revert 全部 v2 commit（順序：最新 → 最舊，避免 conflict）
# 假設找到的 SHA 是 <w3-sha> <w2-sha> <w1-sha>
git -C "$WT" revert --no-edit <w3-sha>
git -C "$WT" revert --no-edit <w2-sha>
git -C "$WT" revert --no-edit <w1-sha>

# 3. 若有衝突，手動解後 commit
# git -C "$WT" revert --continue

# 4. 重啟 station
launchctl kickstart -k "gui/$(id -u)/com.workshop.session-channel"
sleep 3 && curl -s http://localhost:10101/health | jq
```

**注意**：v1 沒有 consumer group，重啟後若 v2 已建立的 group 還在 redis，v1 不會清掉，但也不會用（v1 只看 claims hash）。建議搭配 Tier 3 第 2 步清掉 group。

---

## Rollback Tier 3 — Redis State Restore（20 分鐘）

**前提**：v2 已寫入大量 stream/group state，且 schema 對 v1 不相容（例如 v2 entry 欄位名變了）；或要回到 backup snapshot。

```bash
# 0. 停服務
launchctl unload ~/Library/LaunchAgents/com.workshop.session-channel.plist

# 1. 備份當前 redis（必做，rollback 失敗要能再前進）
redis-cli BGSAVE
sleep 2
cp /opt/homebrew/var/db/redis/dump.rdb \
   /tmp/redis-pre-rollback-$(date +%Y%m%d-%H%M).rdb

# 2. 移除 v2 consumer groups（恢復 v1 claims hash 邏輯前必做）
for stream in $(redis-cli --scan --pattern 'ws:channel:board:*' | grep -v ':failed'); do
  board_id="${stream#ws:channel:board:}"
  echo "Destroying group board-$board_id on $stream"
  redis-cli XGROUP DESTROY "$stream" "board-$board_id" || true
done

# 3. 移除 v2 dead-letter streams（v1 沒這個概念）
for failed in $(redis-cli --scan --pattern 'ws:channel:board:*:failed'); do
  redis-cli DEL "$failed"
done

# 4. Git revert v2 路徑 + 重啟（取代舊的 BOARD_V2=0 流程，2026-05-10 後）
# git revert <v2 commits>          # 在另一視窗執行
# 或從 backup 分支 hard reset

launchctl load ~/Library/LaunchAgents/com.workshop.session-channel.plist
sleep 3 && curl -s http://localhost:10101/health | jq
```

**最壞情況**：直接還原 RDB
```bash
launchctl unload ~/Library/LaunchAgents/com.workshop.session-channel.plist
brew services stop redis
cp /tmp/redis-pre-w2-YYYYMMDD-HHMM.rdb /opt/homebrew/var/db/redis/dump.rdb
brew services start redis
launchctl load ~/Library/LaunchAgents/com.workshop.session-channel.plist
```

---

## Migration v1 → v2（前向遷移）

若舊版 v1 的 board 還在運轉，要切到 v2，使用：

**腳本**：`stations/session-channel/scripts/migrate_v1_to_v2.py`

```bash
~/.local/bin/python3 \
  ~/workshop/stations/session-channel/scripts/migrate_v1_to_v2.py
```

腳本動作：
1. 掃 `ws:board:claims:*` 所有 v1 claim hash
2. 對每個 board：
   - `XGROUP CREATE board-{id} 0 MKSTREAM`（idempotent，吞 BUSYGROUP）
   - 對 claims hash 中每個 `(task_id, pane)` → `XCLAIM` 把該 entry 給 consumer=pane
3. **不自動 DEL** `ws:board:claims:{id}`，等手動驗證

驗證：

```bash
BOARD=<id>
redis-cli XPENDING "ws:channel:board:$BOARD" "board-$BOARD"
# 應看到 v1 claims 中的 task_id 變成 group pending entries

# OK 後手動清 v1 hash
redis-cli DEL "ws:board:claims:$BOARD"
```

---

## 健康檢查清單（Post-Rollback）

切完任何 tier 都要跑完整檢查：

- [ ] `curl -s http://localhost:10101/health | jq` 回 `redis=true` + `status=ok`
- [ ] `curl -s http://localhost:10101/api/topics | jq '.topics | length'` 大於 0
- [ ] 任意 pane 跑 `channel send sessions "test"` 回 200
- [ ] `redis-cli XLEN ws:channel:sessions` 比上一行 +1
- [ ] dashboard `http://localhost:10101/` 載入正常（無 JS error）
- [ ] launchctl 狀態：`launchctl print gui/$(id -u)/com.workshop.session-channel | grep state` 顯示 `running`
- [ ] 過 5 分鐘觀察：log 沒有 traceback，metrics counters 持平或正常增長

---

## 緊急停機

```bash
launchctl unload ~/Library/LaunchAgents/com.workshop.session-channel.plist

# 確認 process 已停
pgrep -f "stations.session-channel.main" || echo "stopped"
```

恢復：

```bash
launchctl load ~/Library/LaunchAgents/com.workshop.session-channel.plist
```

---

## 聯絡 / 升級路徑

- 站點 owner：少爺（latte831104@gmail.com）
- workshop ops 頻道（如有）：Slack `#workshop-ops`
- Issue tracker：GitHub `JonesHong/workshop` issue 區
- 升級路徑：Tier 1 → Tier 2 → Tier 3，每層失敗才往下一層
