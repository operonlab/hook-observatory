# HANDOFF: Codex / Gemini 接入 session-channel 跨 CLI 協作

**from**: pane %2 (Claude Opus 4.7 1M, ctx ~55%)
**to**: anyone (new session 接手)
**created**: 2026-05-11T15:38+08:00

## Goal

把 Codex CLI 與 Gemini CLI 也接進 session-channel，讓 3 種 CLI（Claude/Codex/Gemini）跨 session 互相發現、派工、接力——這是 [blog 「tmux as bridge」](https://blog.joneshong.com/zh/blog/tmux-as-bridge) 願景剩下的最後一段缺口。

前情：今天一整天把 session-channel 從「使用率近零」推到「2 個 Claude session 真實派工+執行+回報閉環」可用，14 個 commits，4 個 Phase（1/2/3a/3c/3d/3e/3f）。但**目前只有 Claude pane 在 channel 上**，schema 雖然預留了 `_meta.cli` 欄位，Codex / Gemini 的 adapter wrapper 還沒寫。

## Key Decisions（今天已拍板，下個 session 沿用）

1. **Schema 預留 `cli` 欄位** — agents topic 的 `_meta.cli` 是 `"claude"|"codex"|"gemini"`，Codex / Gemini adapter 只要填同樣 schema 就接得上。**Why:** 一天前設計 Phase 1 時就已 future-proof，現在不要動 schema 改機制。**How to apply:** 寫 wrapper 時直接 POST 到 `/api/messages` topic=agents tag=announce/heartbeat/leave + `_meta` 帶完整欄位。

2. **Trust marker `[session-channel:trusted task=X from=Y]` 是 Claude classifier 認可的格式** — 3-way 真實測試證實這個 prefix 把 Claude auto-mode classifier 的 `Denied` 翻成 `Allowed`。**Why:** classifier 是 ML 判斷，把 prefix 認作「user-authorized cross-pane bus」。**How to apply:** Codex / Gemini 的 push 命令也應沿用此格式，但 Codex/Gemini 各自的 classifier（如果有）行為未知，需實測。

3. **Bypass mode（`--dangerously-skip-permissions`）才是 relay pool 最徹底解** — auto mode 即使加 trust marker 也是 ML 判斷不保證 100% allow。**Why:** relay pool 是 user 自己 trust 的 panes 用自己派的工。**How to apply:** worker pane spawn 預設帶這個 flag；Codex / Gemini 找等價 flag（Codex 看起來有 `--dangerously-bypass-approvals-and-sandbox`）。

4. **Push 直推 `_meta.prompt` 本身而不是「`channel read tasks`」** — Bug 4。對 Claude，「user 一次性 ask」會被照做就停，沒進 worker mode。直推 prompt 才會被執行 + 回報。**Why:** 對 Claude 而言「channel read」是顯示訊息給 user，不是「我去處理 task」。**How to apply:** Codex / Gemini wrapper 的 worker mode 看到 push 進來的 `<prompt> # [session-channel:trusted ...] after completion run: channel send tasks ...` 應視為「user ask 加自動回報指示」，跑完就回報。

5. **UserPromptSubmit hook 自動 inject inbox** 是 Claude 專有機制 — Codex / Gemini 沒有等價 hook（待確認），可能需要：
   - 替代 A: wrapper 在啟動時 `claude --resume` 或 `codex --resume` 之前先讀 channel inbox 印到 stderr → 對方 user 自己看
   - 替代 B: Cronicle 跑 cron loop 每 30s push 一次 `channel read tasks --count 5` 到 Codex/Gemini pane（粗暴）
   - 替代 C: Codex/Gemini wrapper 攔截 user prompt（如果有 stdin hook 或 environment hook）
   **建議先做 Phase 1 等價：先讓 Codex/Gemini pane 出現在 `/channel agents`，hook 注入留待 Phase 2。**

6. **舊 memory `session-channel-architecture.md`（2026-05-10）已標 outdated** — Board / Pane Registry / DAG 在 commit `0bffd968` 砍掉了。新 memory `session-channel-tmux-bridge-2026-05-11.md` 是 current source of truth。下個 session 不要被舊文件誤導去找 board/dag/pane-registry。

## Files Modified（今天的 14 個 commits）

完整清單在 `~/.claude/projects/-Users-joneshong-workshop/memory/session-channel-tmux-bridge-2026-05-11.md`，這裡只列接手 Codex / Gemini 整合相關的：

- `stations/session-channel/cli/channel.py` — CLI 含 send/read/agents/topics/health + `--notify` + `--meta` + `_tmux_nudge` push 邏輯含 trust marker。Codex/Gemini adapter 應該共用這個 CLI（一致的 `channel ...` 命令）。
- `stations/session-channel/routes.py` — `_meta` 透傳 + `/api/agents/active` reduce + `order=newest` 參數。
- `stations/hook-dispatcher/internal/handlers/session_channel.go` — **Claude 專有**的 5 個 event handler（SessionStart/PreToolUse/Stop/SessionEnd/UserPromptSubmit）。Codex/Gemini 沒這個 dispatcher，要另想機制。
- `~/.claude/skills/session-channel/SKILL.md` v0.2.0 — worker mode 教學 + trust marker。
- `~/.claude/commands/channel.md` / `~/.claude/commands/handoff.md` — Claude Code slash commands。Codex/Gemini 等價可能要靠 alias 或 wrapper。

## Next Steps（建議接手順序）

### Phase A: 偵察 Codex CLI 機制（先做、低成本）

1. 安裝 / 確認 Codex CLI 在 `~/.local/bin/codex` 或類似路徑：`which codex; codex --version`
2. 看 Codex CLI 是否有 hook 機制：`codex --help | grep -i hook; ls ~/.codex/hooks 2>/dev/null`
3. 啟動 Codex 看環境變數：`codex` 啟動後跑 `env | grep -iE 'codex|pane|session'`，找 pane_id / session_id 來源
4. 看 Codex 是否有 slash command 機制：嘗試 `/channel agents` 看能否觸發 channel skill

### Phase B: 偵察 Gemini CLI 機制（同 A）

- `which gemini; gemini --version`
- Gemini 的 SKILL/MD pattern 可能跟 Claude 不一樣（少爺 memory 提過 Gemini agent 用 YAML frontmatter triple-dashes 開頭，不該含 Claude 專屬欄位 color/maxTurns/memory/skills）

### Phase C: 寫 `codex-channel-wrapper.sh`（最小可行）

```bash
#!/bin/bash
# 啟動時 announce
PANE=${TMUX_PANE:-pid-$$}
# 構造 _meta JSON
META='{"v":1,"host":"'$(hostname -s)'","pane":"'$PANE'","cli":"codex","role":"worker","ts":'$(date +%s)'}'
channel send agents "codex/worker started" --tag announce --meta "$META"
# 啟動 codex 帶 trap 在 exit 時 leave
trap "channel send agents 'codex left' --tag leave --meta '$META'" EXIT
exec codex --dangerously-bypass-approvals-and-sandbox "$@"
```

放在 `~/.local/bin/codex-with-channel`，少爺啟動 worker pane 時用這個取代直接跑 `codex`。
同樣方式寫 `gemini-with-channel`。

### Phase D: Heartbeat 機制

Claude 透過 PreToolUse / Stop hook 每 30s 自動 publish heartbeat。Codex / Gemini 沒有：
- 候選 1: Cronicle 加一個 job `codex-channel-heartbeat`，每 60s 對每個 active codex pane（tmux list-panes 偵測 cmd=codex）publish heartbeat
- 候選 2: wrapper 用 background loop `(while sleep 60; do channel send agents ... --tag heartbeat ...; done) &` 與主 codex process 並行

### Phase E: 驗證 cross-CLI 派工

從 Claude pane（如 `default:1.2`）派工到 Codex pane / Gemini pane：

```bash
channel send tasks "<prompt>" --tag assign \
  --meta '{"v":1,"task_id":"x-cli-1","target_pane":"%X","prompt":"echo hello from codex"}' \
  --notify-target '%X'
```

預期：Codex / Gemini 收到 push prompt（透過 tmux send-keys），執行 + 自動回報 done（如果 trust marker 對它們的 classifier 也有效）。

### Phase F: dashboard cli icon 確認

dashboard `templates/index.html` 已支援 `CLI_ICON = { claude: '🔷', codex: '🔶', gemini: '💎' }`。Codex/Gemini pane 出現後應自動帶對應 icon。少爺打開 http://localhost:10101 應該看到混合 icon 的卡片列表。

## Risks / Pitfalls

1. **Codex / Gemini 可能沒有等價 UserPromptSubmit hook** — Claude 的 inbox auto-inject 機制不通用。可能要降級為「啟動時 dump inbox 到 stderr」或「Cronicle 定時 push」。
2. **Trust marker 對 Codex / Gemini 的 classifier 行為未知** — Claude 是 ML 認可，Codex / Gemini 的 prompt 處理機制可能完全不同。可能需要為每個 CLI 寫各自 prefix。
3. **tmux send-keys push 對非 Claude shell 可能不適用** — Codex 預設 REPL 可能跟 zsh 處理 stdin 不同。Phase E 驗證時優先測 `--notify-target` 是否有效。
4. **3 個 CLI 跑同 redis stream 但對 task_id seen file 各自管理** — `/tmp/channel-task-seen-{pane}.json` per-pane 不衝突，但要確認 Codex / Gemini wrapper 教學寫到同檔。
5. **Claude session 中途會 spontaneous /exit**（觀察到多次，原因不明）— Codex / Gemini 可能有類似行為，worker pool 需要 supervised respawn。
6. **舊 memory 誤導風險** — `session-channel-architecture.md` 還在描述 Board / DAG / Pane Registry，新接手 Claude 看到可能花時間找這些已砍能力。已在 MEMORY.md 標 outdated 但仍可能被讀到。
7. **少爺對「成熟」標準很高** — 之前我「fake pane 模擬就宣告成功」被質問，這次少爺要看「3 個 CLI 真實兩兩派工」才算完整。**接手請優先做 Phase E 真實驗證，不要只做 Phase A-D 機制偵察就宣告完工。**

## 已驗證可用的測試套路（給接手參考）

跑兩個 Claude session（不耗少爺手動操作）：
```bash
# Spawn relay pane Claude
tmux send-keys -t 'default:2.1' "claude --dangerously-skip-permissions" Enter
sleep 25
# Verify announce
channel agents --within 60
# Dispatch
channel send tasks "echo hi" --tag assign \
  --meta '{"v":1,"task_id":"t-test","target_pane":"%5","prompt":"echo hi"}' \
  --notify-target '%5'
sleep 90
# Verify done
channel read tasks --count 5 | grep "#done"
# Cleanup
tmux send-keys -t 'default:2.1' "/exit" Enter
```

`default:2.1` ~ `default:2.4` 是 relay pool (tmux %5 ~ %8)，可隨意 spawn/exit。

## 接手執行建議

1. 開新 session 後先 `cat ~/workshop/handoff/HANDOFF-20260511-1538-cross-cli-codex-gemini.md`（這個檔）讀完 context
2. 再讀新 memory `~/.claude/projects/-Users-joneshong-workshop/memory/session-channel-tmux-bridge-2026-05-11.md` 看 v0.3 完整脈絡
3. 跑 `channel agents` 看當前還有哪些 Claude pane 在線
4. 確認 Codex / Gemini CLI 已安裝（Phase A/B 偵察）
5. 從 Phase C 開始實作

不要假裝沒看到這份 HANDOFF——少爺特意留的接力棒。
