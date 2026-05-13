# HANDOFF: session-channel Phase 1-8 完工 + 開源解耦 plan 待執行

**from**: pane %2 (Claude Opus 4.7 1M, ctx ~70%)
**to**: pane %3 (default:1.3)
**created**: 2026-05-12T10:22+08:00
**predecessor**: `HANDOFF-20260511-1741-3cli-6way-closure.md`

## Goal

session-channel 從 Phase 4a (6/6 cross-CLI 雙向派工) 持續推進到 **Phase 8**（最新 commit `fcd32a86`），blog tmux-as-bridge 願景**核心 100% 達成**。當前任務切換：把 session-channel 從 workshop monorepo 拆出，發布到 `operonlab/session-channel` 作為獨立 OSS repo。Plan 已寫好（`~/workshop/outputs/session-channel-phase-f/open-source-decoupling-plan.md`），等執行。

少爺剛拍板「先 Python 解耦 + 開源，Rust port 留 v2」（業界路徑：Python 穩定流行 → Rust 版承接同 API）。

## Key Decisions

1. **Phase 5 並行 agent 派工教訓寫成 rule** — Agent tool `isolation:"worktree"` 從 `origin/main` 創 worktree（非 local HEAD），加上少爺「不 push to remote」習慣 = agent 永遠落後 N commits 在過時 base 上工作。**Why:** 三個並行 agent 全產出「半成品」（uncommitted + stale base），我接手才發現。**How to apply:** 派並行 agent 前先 `git rev-list --count origin/main..HEAD`；> 0 就**不要用** `isolation:"worktree"`，自己預建 worktree from local HEAD，把絕對路徑寫進 agent prompt。Rule 已加 `~/.claude/rules/agents.md` 並 sync 到 GEMINI.md / AGENTS.md / Copilot / Opencode / Qwen。

2. **Phase 6 streaming observability 是 blog「永遠看得到誰在想什麼」的核心** — `hook-dispatcher` Go `PreToolUse` 加 `sessionChannelPublishTool`，per-tool-call publish `tag=tool` event 到 agents topic；dashboard agent-card 加 `⚙` tool line。**Why:** 之前 dashboard 只能顯示「pane 是否在線」，看不到「在做什麼」。**How to apply:** 每次 PreToolUse 都 publish 一次（不被 heartbeat 30s throttle 影響）；前端 `latestTool`/`latestToolTs` 與 task summary 分開欄位，避免互相覆寫。

3. **Phase 7 `channel race` 不是 niche** — 1-to-N cross-CLI race 是日常工作流（同 task 派 claude/codex/gemini 看誰好），我之前誤標 niche 被少爺指正。**Why:** maestro 也有 Race pattern 但走 headless dispatcher-agent 路線；session-channel 補上「persistent relay-pool + dashboard 觀測」backend。**How to apply:** `channel race "<prompt>" --task-id <base> --workers cli:pane,...` — 每 worker 拿到 `<base>-<cli>` 獨立 task_id 軌跡。

4. **Phase 8 `channel debate` ≠ Synthesis** — Maestro Synthesis 是 1-shot parallel + merge，**真正 debate** 是 N-round 來回 critic/respond（每輪看前一輪完整 result）。**Why:** 第二次被少爺指正同類錯誤（first race，second debate）— 不要用 "niche" 標籤迴避真該做的功能。**How to apply:** `channel debate "<Q>" --participants A:claude:%5,B:codex:%6 --rounds 3 --synthesizer gemini:%7`。Two-tier result capture: `_meta.result` 優先（worker 自願填），`_meta.summary` fallback。

5. **撤回 4 條偽 gap（delegation 邊界 + YAGNI）** — Mobile UX delegated to `tmux-webui`、Resource-aware delegated to `system-monitor-rs guardian-tick`、Typed schema YAGNI（5 cmd 穩定無 silent bug）、Persistence 由設計合理排除（session-channel 是 ephemeral coordination，真持久內容已落 disk）。**Why:** 少爺三次點醒「不要用 niche/gap 標籤迴避或越界」。**How to apply:** session-channel 只做 cross-pane 通訊；mobile/resource/persistence/typed-schema 都不該擠進 scope。

6. **Rust port 留 v2** — 業界路徑：Python 版先穩定+流行+收 issue，再 Rust 版承接同 API（如 ruff/uv 對 pylint/pip 的關係）。當前 RSS 34MB / idle 0% CPU，性能不是瓶頸；Rust 真好處是「單 binary 部署」，但要等 v0.2 開源後 6+ 月實際 user feedback 再啟動 `operonlab/session-channel-rs`。

## Files Modified（本 session 真正動過的，非 git status dump）

### 進入 main 的 commits（13 個）

```
fcd32a86 Merge channel debate (Phase 8)
2a20d8b6 feat: channel debate — multi-round + synthesizer
92d11206 Merge channel race (Phase 7)
61a78871 feat: channel race — 1-prompt N-workers
49d053df Merge streaming observability (Phase 6)
fb52d269 feat: dashboard agent-card shows latest tool call
9e8f3692 feat: publish tool events on PreToolUse
73b4fbad chore: wire supervisor.py into Cronicle + E2E verify
627a9bd7 Merge tasks failure/retry policy (Phase 5b WIP)
fa3b9a53 Merge worker supervised respawn (Phase 5a)
2ce4923e feat: tasks topic failure + timeout policy
21511919 feat: worker supervised respawn (Cronicle-driven)
```

### Files in main

- `stations/session-channel/cli/channel.py` (+490 lines) — `cmd_tasks` (Phase 5b) / `cmd_race` + `_parse_workers` (Phase 7) / `cmd_debate` + `_parse_participants` + `_parse_synthesizer` + `_wait_for_outcome` + `_dispatch_one` (Phase 8) + 0.3s settle delay
- `stations/session-channel/scripts/supervisor.py` (新檔, 310 行) — Cronicle-driven relay-pool respawn
- `stations/session-channel/config.yaml` — 加 `relay_pool` section
- `stations/session-channel/templates/index.html` — `s-tool` line + `latestTool` entry
- `stations/hook-dispatcher/internal/handlers/session_channel.go` — `sessionChannelPublishTool` + `sessionChannelToolPreview`
- `schedules/manifest.json` — `ws-session-channel-supervisor` Cronicle entry (default disabled)

### 未 commit / scope 外 files

- `~/.claude/rules/agents.md` — 加「Parallel Agent Dispatch — Worktree Base Trap (HARD RULE)」section (~54 行)
- `~/.claude/projects/-Users-joneshong-workshop/memory/session-channel-tmux-bridge-2026-05-11.md` — description 升 Phase 1-8 + 整段 Phase 5/6/7/8 + scope-外撤回說明
- `~/.claude/projects/-Users-joneshong-workshop/memory/parallel-agent-worktree-trap.md` (新檔) — 並行 agent 教訓
- `~/.claude/projects/-Users-joneshong-workshop/memory/MEMORY.md` — 加 Agent Dispatch Lessons section pointer
- `~/workshop/outputs/session-channel-phase-f/dashboard-3cli.png` — Phase F 三色 icon 視覺驗證截圖（4 cards: 🔶🔶💎🔷🔷）
- `~/workshop/outputs/session-channel-phase-f/dashboard-tool-line-pre.png` — Phase 6 streaming observability 視覺驗證截圖
- `~/workshop/outputs/session-channel-phase-f/omc-replacement-evaluation.md` (245 行) — explorer agent 寫的 omc 替換評估報告
- `~/workshop/outputs/session-channel-phase-f/open-source-decoupling-plan.md` (新檔) — 10 條硬編碼 / 6 phases / ~13h 完整開源解耦 plan

## Next Steps

### 立即優先：開源解耦 Phase 1（最高 ROI，~2h）

讀 `~/workshop/outputs/session-channel-phase-f/open-source-decoupling-plan.md` Phase 1 段。10 處硬編碼修法明確：

1. 引入 `$SESSION_CHANNEL_HOME` env var（預設 `$HOME/.session-channel`）
2. 改 5 個 wrapper / hook / supervisor files 的 absolute path → env-var 解析
3. 改 2 個 shebang `#!/Users/joneshong/.local/bin/python3` → `#!/usr/bin/env python3`
4. `main.py:118` CORS 寫死 `https://workshop.joneshong.com` → 改讀 `config.yaml.allowed_origins`
5. `tests/conftest.py:4` 移除少爺 worktree path

按新加 rule 走（pre-flight + worktree from local HEAD + incremental commits）：
```bash
git rev-list --count origin/main..HEAD   # 預期 > 0
git worktree add .worktrees/feature/oss-decouple-phase1 -b feature/oss-decouple-phase1
```

### Phase 2-6（後續 sessions）

| Phase | 時間 | 內容 |
|---|---|---|
| 2 | ~4h | README / install.sh / systemd unit / Dockerfile / docker-compose.yml |
| 3 | ~3h | sample hook (`examples/hooks/session_channel.py` ~150 行 Python 版) |
| 4 | ~2h | 三家 CLI integration docs (claude-code / codex / gemini / generic) |
| 5 | ~1h | LICENSE (MIT) / CONTRIBUTING / CHANGELOG / `.github/workflows/test.yml` |
| 6 | ~1h | `git subtree split --prefix=stations/session-channel` → push `operonlab/session-channel` v0.2 |

### 其他可選待辦

- session-channel-worker rule 補 `_meta.result` mandate（提升 debate quality）
- 評估 omc Phase 1 cleanup（清 ~/.codex/config.toml 已不用的 omc team config）
- Cross-host pane 真實驗證

## Risks / Pitfalls

1. **`~/.claude/` 大量未 commit 修改** — 不是本 session 造成，少爺自己流程在動（修改 + deletion 一堆）。接手者**不要**在 ~/.claude/ 跑 `git add -A`；只 add 自己改的 specific files（如 rules/session-channel-worker.md + rules/agents.md + memory/*）。

2. **並行 agent worktree base 落後 origin/main**（HARD RULE）— 派並行 agent 前**先**：
   ```bash
   git rev-list --count origin/main..HEAD   # > 0 就不用 isolation:"worktree"
   ```
   改用預建 worktree from local HEAD。Rule 寫在 `~/.claude/rules/agents.md`。

3. **Agent commit 排最後 = budget exhaustion** — Worker subagent maxTurns=20，長任務「實作 + 驗證 + commit + summary」sequential dependency 會在 turn 19-20 才到 commit，常被擠掉。Prompt 必須 mandate「每完成一個檔案就 `git add + git commit`，最後一個 turn 寫 summary」。

4. **supervisor Cronicle entry 預設 disabled** — `schedules/manifest.json` 的 `ws-session-channel-supervisor` `enabled: false`。少爺要手動 enable + review config.yaml relay_pool.workers 才會生效。

5. **session-channel-worker rule 已 sync 5 CLI** — `~/.claude/rules/session-channel-worker.md` 已 sync 到 GEMINI.md / AGENTS.md / Copilot / Opencode / Qwen。修這 rule 後**要**重跑 `sync_config sync instructions --target all --global`。

6. **trust marker push 內含 on success/failure 雙路徑** — Phase 5b retry agent 改的 `_tmux_nudge` 把 wakeup 訊息改成 `... on success run: channel send ... done ; on failure run: channel send ... failed`。worker 看到 trust marker 後預期執行兩條中對應一條。

7. **scope 邊界（不該由 session-channel 做）**：
   - Mobile UX → `tmux-webui` (operonlab/tmux-webui)
   - 記憶體 / 資源 → `system-monitor-rs guardian-tick`
   - Ephemeral CLI race → `maestro` skill (headless dispatcher agents)
   - Persistent worker pool race → `channel race` (我們)

8. **2 個誤判教訓**（避免重蹈）：
   - 不要把功能標 niche 來迴避實作（race / debate 兩次被打臉）
   - 不要把專業工具該做的事擠進 session-channel scope（mobile / resource）

9. **Codex idle pane 偶發 self-exit** — Phase 4a 觀察到 Codex 處理完 task 偶爾自動 exit，wrapper trap 已處理 leave event。supervisor 會 respawn。Gemini 沒看到此現象。

10. **Gemini 仍會順手跑 `/rename`** — 即使有 worker rule，Gemini 看到 prompt 含字串會嘗試 rename session（cosmetic side-effect，shell 報錯 "No such file or directory"，不影響最終 `channel send done`）。

## 已驗證的可重複測試套路

```bash
# 同時 spawn 三 CLI worker
tmux send-keys -t '%5' "claude --dangerously-skip-permissions" Enter
tmux send-keys -t '%6' "~/workshop/stations/session-channel/wrappers/codex-with-channel.sh" Enter
tmux send-keys -t '%7' "~/workshop/stations/session-channel/wrappers/gemini-with-channel.sh" Enter

# 等三色 icon 都出現
until [ "$(channel agents --within 60 | grep -cE '🔷|🔶|💎')" -ge 3 ]; do sleep 4; done

# 1-to-1 派工（Phase 4a）
channel send tasks "<prompt>" --tag assign \
  --meta '{"v":1,"task_id":"t1","target_pane":"%X","prompt":"<prompt>"}' \
  --notify-target '%X'

# 1-to-N race（Phase 7）
channel race "<prompt>" --task-id <base> \
  --workers claude:%5,codex:%6,gemini:%7 --wait 300

# N-round debate（Phase 8）
channel debate "<question>" --debate-id <base> \
  --participants A:claude:%5,B:codex:%6 \
  --rounds 3 --synthesizer gemini:%7
```

## 接手執行建議

1. 跑 `cat ~/workshop/handoff/HANDOFF-20260512-1022-session-channel-phase8-opensource.md` 看本 HANDOFF
2. 跑 `cat ~/workshop/outputs/session-channel-phase-f/open-source-decoupling-plan.md` 看開源 plan
3. （可選）看 memory `~/.claude/projects/-Users-joneshong-workshop/memory/session-channel-tmux-bridge-2026-05-11.md` 看 Phase 1-8 全紀錄
4. 確認少爺要不要直接從開源 Phase 1 開始（10 處硬編碼解耦，~2h，最高 ROI）
5. 按新加 rule 走：pre-flight `git rev-list --count origin/main..HEAD` → 預建 worktree from local HEAD → incremental commit

不要假裝沒看到——這是少爺特意留的接力棒。
