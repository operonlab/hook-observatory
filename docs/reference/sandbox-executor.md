---
doc_version: 2
content_hash: 40ef2e7d
source_version: 2
target_lang: zh-TW
translated_at: 2026-02-23
---

# Sandbox Executor — 參考文件

## 起源 (Origin)

靈感來自 **Cloudflare Workers** 的概念：與其執行 N 個獨立的工具調用（讀取檔案、Bash 命令、HTTP 請求），不如將確定的操作打包到單次程式碼執行中，並搭配預先注入的 SDK 輔助函式。

### 問題（使用 sandbox 之前）

```
Claude Code 想要：讀取 5 個檔案 + 進行 3 次 API 調用 + 寫入 2 個檔案
= 10 次獨立的工具調用
= 10 次往返（每次約 2-3 秒）
= 總共耗時 20-30 秒
```

### 解決方案（使用 sandbox 之後）

```
Claude Code 使用 SDK 輔助函式撰寫 Python 腳本
= 1 次工具調用 (sandbox_execute)
= 所有操作在單個子進程中運行
= 總共耗時 1-5 秒
```

### Cloudflare Workers 類比

| Cloudflare Workers | Sandbox Executor |
|-------------------|-----------------|
| 邊緣端的 V8 isolate | Python/Node.js 子進程 |
| fetch() API | http_get(), http_post() |
| KV 綁定 (bindings) | read_file(), write_file() |
| Response 物件 | output() 結構化結果 |
| 運行位置鄰近使用者 | 運行在本地機器 |

## 架構 (Architecture)

```
LLM CLI (Claude Code / Gemini / Codex)
    │
    │ MCP stdio 協定
    ▼
┌──────────────────────┐
│  sandbox-executor    │ (Node.js MCP 伺服器)
│  ├── index.ts        │ MCP 伺服器 + 工具註冊
│  ├── tools/          │ 工具處理程序 (execute, info)
│  ├── sandbox/        │
│  │   ├── prelude.ts  │ SDK 輔助函式注入 (Python/JS)
│  │   ├── runner.ts   │ 子進程執行引擎
│  │   └── validator.ts│ 基礎安全檢查
│  └── schemas/        │ Zod 輸入驗證
└──────────┬───────────┘
           │
           │ child_process.spawn()
           ▼
    ┌──────────────┐
    │  Python 3.12 │  或  Node.js
    │  subprocess  │
    │              │
    │  SDK 輔助函式: │
    │  http_get()  │
    │  http_post() │
    │  read_file() │
    │  write_file()│
    │  output()    │
    └──────────────┘
```

## 工具 (Tools)

### `sandbox_execute`

執行 Python 或 JavaScript 程式碼，並自動注入 SDK 輔助函式。

**輸入 (Input)**：
```json
{
  "language": "python" | "javascript",
  "code": "...",
  "timeout": 30,
  "description": "這段程式碼的作用"
}
```

**輸出 (Output)**：Markdown 格式的結果，包含狀態、執行時間、stdout/stderr 以及結構化輸出。

### `sandbox_info`

傳回指定語言的 SDK 說明文件。

**輸入 (Input)**：
```json
{
  "language": "python" | "javascript"
}
```

## SDK 輔助函式 (SDK Helpers)

所有輔助函式都會在使用者程式碼執行前作為 prelude 自動注入，無需手動 import。

### Python

```python
# HTTP
response = http_get(url, headers=None)          # 回傳: {"status": int, "body": str, "headers": dict}
response = http_post(url, data=None, headers=None)

# 檔案 I/O
content = read_file(path)                       # 回傳: str (檔案內容)
write_file(path, content)                       # 自動建立父目錄

# 輸出
output(data, label=None)                        # 註冊結構化輸出 (dict, list, str)
```

### JavaScript

```javascript
const response = await http_get(url, headers);
const response = await http_post(url, data, headers);
const content = read_file(path);
write_file(path, content);
output(data, label);
```

## 限制 (Constraints)

| 限制項目 | 數值 |
|-----------|-------|
| Timeout (逾時) | 1-60 秒 (預設 30) |
| Stdout 限制 | 50KB |
| HTTP 逾時 | 每次請求 15 秒 |
| 驗證 | 僅檢查路徑遍歷 (Path traversal) |
| 隔離性 | 無 — 共享主機檔案系統與網路 |

## 使用時機 (When to Use)

| 場景 | 使用 sandbox？ |
|----------|-------------|
| 3 次以上的 API 調用（任何 URL） | 是 — 單次工具調用取代多次調用 |
| 批量檔案讀取 → 轉換 → 寫入 | 是 — 高效率的工作流 |
| 多服務健康檢查 | 是 — 並行請求 |
| 單一檔案讀取 | 否 — 使用直接的讀取工具更簡單 |
| 探索性操作 / 步驟間需要推理 | 否 — 使用序列化的工具調用 |
| 需要 MCP 工具 (Playwright 等) | 否 — sandbox 無法存取 MCP |

## 配置 (Configuration)

### 位置 (Location)

```
~/workshop/stations/sandbox-executor/
├── src/           # TypeScript 源碼
├── dist/          # 編譯後的 JavaScript (執行此目錄)
├── package.json
└── tsconfig.json
```

### MCP 伺服器註冊

**Claude Code** (`~/.claude.json`):
```json
"sandbox-executor": {
  "type": "stdio",
  "command": "node",
  "args": ["/Users/joneshong/workshop/stations/sandbox-executor/dist/index.js"],
  "env": {
    "PYTHON_PATH": "/Users/joneshong/.local/bin/python3"
  }
}
```

**Gemini CLI** (`~/.gemini/settings.json`):
```json
"sandbox-executor": {
  "command": "node",
  "args": ["/Users/joneshong/workshop/stations/sandbox-executor/dist/index.js"],
  "env": {
    "PYTHON_PATH": "/Users/joneshong/.local/bin/python3"
  }
}
```

## 開發 (Development)

```bash
cd ~/workshop/stations/sandbox-executor
npm install
npm run build     # TypeScript → dist/
npm run dev       # 監控模式 (Watch mode)
```

修改源碼後，請重新編譯並重啟 LLM CLI 以套用更改。
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
Created execution plan for SessionEnd: 3 hook(s) to execute in parallel
Expanding hook command: ~/Claude/projects/pulso/services/session_redactor/scripts/redact-session.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/Claude/projects/kas-memory/scripts/extract-async.sh (cwd: /Users/joneshong/workshop)
Expanding hook command: ~/.claude/hooks/observability-bridge.sh SessionEnd (cwd: /Users/joneshong/workshop)
