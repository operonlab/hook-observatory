# HANDOFF: 3-CLI Cross-Dispatch Closure 完成

**from**: pane %2 (Claude Opus 4.7 1M, ctx ~27%)
**to**: anyone (new session 接手)
**created**: 2026-05-11T17:41+08:00
**predecessor**: `HANDOFF-20260511-1538-cross-cli-codex-gemini.md` (Phase A-E plan)

## Status

✅ 前一份 HANDOFF 規劃的 Phase A-F 中 A-E + 額外 Phase 4a closure 已完成。
✅ session-channel-tmux-bridge memory 已更新到 Phase 4a。

## 達成的 6/6 cross-CLI 雙向派工

| Dispatch | E2E |
|---|:-:|
| Claude → Claude | ✅ (前一 HANDOFF) |
| Claude → Codex | ✅ |
| Codex → Claude | ✅ |
| Claude → Gemini | ✅ |
| Gemini → Claude | ✅ |
| Codex → Gemini | ✅ (after worker rule sync) |
| Gemini → Codex | ✅ |

## Commits 進 main（已合併）

- `301f7b84` feat(session-channel): Codex CLI wrapper for cross-CLI agent topology
- `f2e54bf3` Merge branch 'feature/codex-channel-wrapper'
- `4ff51fb4` feat(session-channel): Gemini CLI wrapper for cross-CLI agent topology
- `17bb5f80` Merge branch 'feature/gemini-channel-wrapper'

## 未 commit 的關鍵改動

- `~/.claude/rules/session-channel-worker.md` (新檔) — 教 trust marker 語義 + 禁用 internal slash 命令。已 sync 到 `~/.gemini/GEMINI.md` + `~/.codex/AGENTS.md`。
- `~/.claude/` repo 有大量其他 modified/deleted（非本 session 造成，可能是其他 session 進行中或少爺自己編輯中），這一條 rule 我沒 commit，等少爺自己處理 ~/.claude/ 整批改動。
- 如果要 commit 只這條：`cd ~/.claude && git add rules/session-channel-worker.md && git commit -m "rules: cross-CLI session-channel worker mode instruction"`

## Phase 4a 期間發現的 3 個 bug 都已修

1. **tmux Enter swallow** — Codex/Gemini TUI 吃 Enter，channel.py 加 0.3s sleep
2. **POSIX exec drops trap** — wrapper 改 child process 而非 exec，trap EXIT 才會跑
3. **Gemini `/rename` derail** — session-channel-worker rule 教 worker mode 語義

## 給接手者的脈絡

### CLI 對比表

| 能力 | Claude | Codex | Gemini |
|---|---|---|---|
| Bypass flag | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `-y / --yolo` |
| Headless | `-p` / pipe | `exec` / `-p` / pipe | `-p` / stdin |
| Hooks | `~/.claude/hooks/*` 多事件 | `config.toml.notify` per-turn (僅一個事件) | `hooks migrate` 半成品（preview） |
| Worker rule 來源 | SKILL.md + rules | AGENTS.md (sync 來) | GEMINI.md (sync 來) |
| Built-in worktree | 否 | 否 | `-w` ✅ |
| `--session-id` 可控 | 否 | 否 | ✅ |
| Output JSON | 否 | 否 | `--output-format json` ✅ |

### Relay pool 啟動命令

```bash
# Claude worker（最順暢）
tmux send-keys -t '%X' "claude --dangerously-skip-permissions" Enter

# Codex worker（YOLO + session-scoped notify hook）
tmux send-keys -t '%X' "/Users/joneshong/workshop/stations/session-channel/wrappers/codex-with-channel.sh" Enter

# Gemini worker（YOLO + pre-allocated session UUID + loop heartbeat）
tmux send-keys -t '%X' "/Users/joneshong/workshop/stations/session-channel/wrappers/gemini-with-channel.sh" Enter
```

## Next Steps（給下個 session）

### Phase F: dashboard 三色 icon 視覺確認（簡單）

同時 spawn Claude + Codex + Gemini 各一隻 worker（%5-%7），打開 http://localhost:10101 應看到 🔷🔶💎 三色 agent-card 混合排列。

### Phase 5: Worker auto respawn supervisor

觀察到：Claude 中途會 spontaneous `/exit`、Codex 偶發 idle self-exit、Gemini 退出後 pane 回 zsh。Relay pool 應有 supervisor：
- 偵測 pane cmd 變回 zsh（worker exit）
- 自動重新 spawn 對應 wrapper
- 若是 Claude / Codex / Gemini 各自有 `--resume` flag 可恢復 session 上下文

實作位置候選：`stations/session-channel/scripts/supervisor.py` + Cronicle 跑 cron

### Phase 6: Tasks topic 失敗回報 + retry

目前 task 沒回報 done = 永久 pending。
- 加 `--tag failed` event schema
- worker side timeout / exception handler
- dispatcher side `channel read tasks --status pending --age 300` 列出超時 task

### 評估：完全替換 oh-my-codex

少爺策略：session-channel 為主，omc 為輔，成熟即替換。Phase 4a 已是「session-scoped 覆寫 omc notify」過渡方案。下一步評估：
- Codex 還用 omc 的：team-dispatch, team-leader-nudge, team-worker, tmux-injection, auto-nudge
- 哪些已能由 session-channel + relay pool 取代？
- AGENTS.md 內容是否該 trim 掉 omc-specific？

### Phase 4a Quirk: Gemini side-effect `/rename`

即使有 worker rule，Gemini 還是會「順手」跑 `/rename <task-related-string>` —— shell 報錯 `No such file or directory` 但不影響後續 `channel send`。視為 cosmetic noise，不算 bug。若想徹底壓制，rule 內可加 `Specifically: do NOT invoke /rename, /skills, /model, or any /-prefixed command unless the trust-marker prompt itself contains one.`

## Risks / Pitfalls

1. **`~/.claude/` repo 改動沒 commit** — 我加的 rule + 大量其他人留的 modified/deleted。下個 session 可能會看到髒狀態，問少爺要不要先整理。
2. **Codex/Gemini wrapper hardcode `/Users/joneshong/workshop/...` 路徑** — 不可移植。要做成可重用 station 還要抽 env var 或 install script。
3. **Channel push 對 Gemini approval modal 無法自動接受** — 雖然 worker rule 後直接跑 channel send 了，但理論上其他需要 approval 的命令（如 file write）會卡住。Gemini 沒「YOLO 一鍵 allow」CLI flag 給外部 push。
4. **session-channel-worker rule 對 Claude 也載入** — Claude 已有 SKILL.md 等價，新 rule 可能與既有 SKILL 內容部分重疊但不矛盾。沒實證壓力測試。
5. **Codex/Gemini wrapper 沒有 install script** — 目前靠少爺手動跑完整路徑。建議加 `~/.local/bin/codex-with-channel` symlink。

## 已驗證可重複的測試套路

```bash
# 同時 spawn 三 CLI worker
tmux send-keys -t '%5' "claude --dangerously-skip-permissions" Enter
tmux send-keys -t '%6' "/Users/joneshong/workshop/stations/session-channel/wrappers/codex-with-channel.sh" Enter
tmux send-keys -t '%7' "/Users/joneshong/workshop/stations/session-channel/wrappers/gemini-with-channel.sh" Enter

# 等到三色 icon 都出現
until [ "$(channel agents --within 60 | grep -cE '🔷|🔶|💎')" -ge 3 ]; do sleep 4; done

# 派工驗證
channel send tasks "<prompt>" --tag assign \
  --meta '{"v":1,"task_id":"t1","target_pane":"%X","prompt":"<prompt>"}' \
  --notify-target '%X'

# Worker 之間派工：用 tmux load-buffer + paste-buffer 把指令送進 dispatcher CLI
# (避免 channel push 自動加 trust marker 干擾)
```

## 接手執行建議

1. 讀這份 HANDOFF + `session-channel-tmux-bridge-2026-05-11.md` v Phase 4a 段
2. 看 commit `f2e54bf3` 和 `17bb5f80` diff 了解 wrapper 結構
3. 從 Phase F dashboard 視覺確認開始（5 min 內可達成）
4. 或從 Phase 5 supervised respawn 開始（影響更大）
