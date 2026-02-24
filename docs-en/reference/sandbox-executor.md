---
doc_version: 2
content_hash: 40ef2e7d
source_version: 2
target_lang: en
translated_at: 2026-02-24
source_hash: 1b2241f0
source_lang: zh-TW
---

# Sandbox Executor — Reference Document

## Origin

Inspired by the concept of **Cloudflare Workers**: instead of executing N separate tool calls (reading files, Bash commands, HTTP requests), it's better to bundle deterministic operations into a single code execution, accompanied by pre-injected SDK helper functions.

### Problem (Before Sandbox)

```
Claude Code wants to: read 5 files + make 3 API calls + write 2 files
= 10 separate tool calls
= 10 round trips (approx. 2-3 seconds each)
= Total time 20-30 seconds
```

### Solution (After Sandbox)

```
Claude Code writes a Python script using SDK helper functions
= 1 tool call (sandbox_execute)
= All operations run in a single subprocess
= Total time 1-5 seconds
```

### Cloudflare Workers Analogy

| Cloudflare Workers | Sandbox Executor |
|-------------------|-----------------|
| V8 isolate at the edge | Python/Node.js subprocess |
| fetch() API | http_get(), http_post() |
| KV bindings | read_file(), write_file() |
| Response object | output() structured result |
| Runs close to the user | Runs on the local machine |

## Architecture

```
LLM CLI (Claude Code / Gemini / Codex)
    │
    │ MCP stdio protocol
    ▼
┌──────────────────────┐
│  sandbox-executor    │ (Node.js MCP server)
│  ├── index.ts        │ MCP server + tool registration
│  ├── tools/          │ Tool handlers (execute, info)
│  ├── sandbox/        │
│  │   ├── prelude.ts  │ SDK helper function injection (Python/JS)
│  │   ├── runner.ts   │ Subprocess execution engine
│  │   └── validator.ts│ Basic security checks
│  └── schemas/        │ Zod input validation
└──────────┬───────────┘
           │
           │ child_process.spawn()
           ▼
    ┌──────────────┐
    │  Python 3.12 │  or  Node.js
    │  subprocess  │
    │              │
    │  SDK Helpers:  │
    │  http_get()  │
    │  http_post() │
    │  read_file() │
    │  write_file()│
    │  output()    │
    └──────────────┘
```

## Tools

### `sandbox_execute`

Executes Python or JavaScript code with automatically injected SDK helper functions.

**Input**:
```json
{
  "language": "python" | "javascript",
  "code": "...",
  "timeout": 30,
  "description": "What this code does"
}
```

**Output**: Markdown-formatted result, including status, execution time, stdout/stderr, and structured output.

### `sandbox_info`

Returns the SDK documentation for the specified language.

**Input**:
```json
{
  "language": "python" | "javascript"
}
```

## SDK Helpers

All helper functions are automatically injected as a prelude before the user's code executes, without needing manual imports.

### Python

```python
# HTTP
response = http_get(url, headers=None)          # Returns: {"status": int, "body": str, "headers": dict}
response = http_post(url, data=None, headers=None)

# File I/O
content = read_file(path)                       # Returns: str (file content)
write_file(path, content)                       # Automatically creates parent directories

# Output
output(data, label=None)                        # Register structured output (dict, list, str)
```

### JavaScript

```javascript
const response = await http_get(url, headers);
const response = await http_post(url, data, headers);
const content = read_file(path);
write_file(path, content);
output(data, label);
```

## Constraints

| Constraint | Value |
|-----------|-------|
| Timeout | 1-60 seconds (default 30) |
| Stdout Limit | 50KB |
| HTTP Timeout | 15 seconds per request |
| Validation | Only checks for Path Traversal |
| Isolation | None — shares host filesystem and network |

## When to Use

| Scenario | Use Sandbox? |
|----------|-------------|
| 3+ API calls (any URL) | Yes — single tool call replaces multiple calls |
| Batch file read → transform → write | Yes — for an efficient workflow |
| Multi-service health checks | Yes — for parallel requests |
| Single file read | No — simpler to use a direct read tool |
| Exploratory operations / reasoning needed between steps | No — use sequential tool calls |
| Need MCP tools (Playwright, etc.) | No — sandbox cannot access MCP |

## Configuration

### Location

```
~/workshop/stations/sandbox-executor/
├── src/           # TypeScript source code
├── dist/          # Compiled JavaScript (execute this directory)
├── package.json
└── tsconfig.json
```

### MCP Server Registration

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

## Development

```bash
cd ~/workshop/stations/sandbox-executor
npm install
npm run build     # TypeScript → dist/
npm run dev       # Watch mode
```

After modifying the source code, please recompile and restart the LLM CLI to apply changes.
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3181ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 3762ms
