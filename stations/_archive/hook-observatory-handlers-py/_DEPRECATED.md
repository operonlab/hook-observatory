# hook-observatory handlers (Python) — partial archive

本目錄只收 `stations/hook-observatory/handlers/` 內**已正式放棄**或**已被 Go binary 接管且不再回看**的 handler 檔，**不是整個 handlers/ 的搬遷**。

`stations/hook-observatory/handlers/` 內其餘 35 個 .py + `__init__.py` + `tool_registry.json` 目前仍留在原處，因為：

- `stations/hook-observatory/main.py` (FastAPI dashboard) 仍 `from handlers.hook_config import cfg`
- `stations/hook-observatory/install.py` (Homebrew installer 入口) 仍 `from handlers import dispatch`
- `stations/hook-observatory/voice_notify_runner.py` (Go panic fallback) 仍 `from handlers.voice_notify import handle`
- `stations/hook-dispatcher/internal/handlers/{anvil_telemetry,pm_autopilot}.go` 仍讀 `handlers/tool_registry.json`

這三層 (dashboard / installer / fallback / 資料檔) 的命運由後續 cutover phase 決定（見 `handoff/HANDOFF-20260513-0330-hook-observatory-go-cutover.md`），屆時再決定剩 35 個 handler .py 是一併歸檔還是部分留下。

## 已歸檔項目

### `context_supervisor.py` （2026-05-13）

- **原路徑**：`stations/hook-observatory/handlers/context_supervisor.py`（1002 行）
- **功能**：三層 context 健康監控
  - Layer 1：Context pressure（StatusLine bridge JSON window %）
  - Layer 2：Heuristic drift detection（file re-read / tool repetition / edit cycling / empty progress / command retry / scope drift）
  - Layer 3：LLM + Embedding semantic coherence（periodic background `claude -p` + oMLX）
- **訂閱事件**：SessionStart、PostToolUse、Stop、UserPromptSubmit、PreCompact（5 events）
- **狀態歷史**：
  - 自 2026-05-06 起，hook 執行路徑全面切到 Go binary (`hook-dispatcher`)，Python `context_supervisor.py` 不再被觸發
  - Go 端的 `context_relay.go + context_inject.go` 名字撞名但**職責不同**（session 接續 + sub-agent context 注入），**未接管**監控邏輯
  - 早在 Python 端 `handlers/__init__.py` REGISTRY 內也已用 `# context_supervisor: disabled — concept good, scoring inaccurate` 註解停用所有路由
  - 三層監控功能因此 silently 停運 6+ 天
- **歸檔原因**：
  - 少爺 2026-05-13 拍板「不要這個功能」（concept good, scoring inaccurate）
  - 不重寫進 Go、不 shell-out 回 Python；功能放棄
- **同次清理**：
  - `handlers/__init__.py` 刪除 `_try_import("context_supervisor")` 入口
  - `handlers/__init__.py` 刪除 PreToolUse / PostToolUse / Stop / UserPromptSubmit / SessionStart / PreCompact 六處 disabled 註解

## 不在本次範圍 / Flag 待後續處理

- `stations/hook-dispatcher/HANDOFF.md:81` 有「Boss fight: 移植 ctx supervisor (1002 LOC) 進 Go」的舊計畫，應隨拍板更新為「不移植，已歸檔」
- `stations/hook-dispatcher/STAGE3-READY.md:57` 已說「ctx supervisor is disabled in Python registry → not part of parity baseline」，可保留為歷史
- 工作區根目錄的 `QWEN.md / GEMINI.md / AGENTS.md / OPENCODE.md`（multi-CLI 共用 instruction）各兩處引用 `context_supervisor.py` 為「新增 handler 可參考模式」 / 「異動先看 Go path 的列舉項」 — 應在這些檔同步刪除引用
