# Multi-Agent Observability（社群專案）

> Claude Code hooks 即時監控儀表板 — 追蹤多 agent 的 tool call、task handoff、lifecycle 事件。

## 來源

| 屬性 | 數值 |
|------|------|
| **作者** | [@disler](https://github.com/disler) |
| **Repo** | [claude-code-hooks-multi-agent-observability](https://github.com/disler/claude-code-hooks-multi-agent-observability) |
| **授權** | 開源（GitHub） |
| **本地位置** | `~/Claude/projects/claude-code-hooks-multi-agent-observability/` |

## 為什麼放在 vendor/

這是第三方社群專案，我們直接使用但不改造成 V2 架構。`vendor/` 目錄專門存放這類「拿來用」的外部工具。

## 架構

```
Claude Agents → Hook Scripts → HTTP POST → Bun Server → SQLite → WebSocket → Vue Client
```

## 功能

- 即時追蹤多個 Claude Code agent 的 hook 事件
- Session 追蹤（source_app + session_id 識別 agent）
- 事件過濾與搜尋
- WebSocket 即時更新
- Vue.js 儀表板 UI

## 整合方式

透過 Claude Code hooks（`~/.claude/settings.json`）注入，9 個 event types：
- PreToolUse / PostToolUse
- PreBash / PostBash
- Notification
- SessionStart / SessionEnd
- 等

Hook script（`observability-bridge.sh`）將事件 POST 到 Bun server。

## 本地操作

```bash
cd ~/Claude/projects/claude-code-hooks-multi-agent-observability
just server    # 啟動 Bun server
just client    # 啟動 Vue client
just dev       # 同時啟動 server + client
```

## 技術棧

- **Server**：Bun + SQLite
- **Client**：Vue.js
- **通訊**：WebSocket（即時推送）
- **Task Runner**：justfile

## 注意事項

- 此專案不由我們維護，upstream 更新需手動 `git pull`
- 若需要自訂功能，建議 fork 後修改
- 與 `stations/session-redactor` 同屬 SessionEnd pipeline 第三步
