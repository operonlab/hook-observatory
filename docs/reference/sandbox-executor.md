---
doc_version: 2
content_hash: 40ef2e7d
---

# Sandbox Executor — Reference

## Origin

Inspired by **Cloudflare Workers** concept: instead of making N individual tool calls (Read file, Bash command, HTTP request), bundle deterministic operations into a single code execution with pre-injected SDK helpers.

### Problem (before sandbox)

```
Claude Code wants to: read 5 files + make 3 API calls + write 2 files
= 10 individual tool calls
= 10 round-trips (each ~2-3 seconds)
= 20-30 seconds total
```

### Solution (with sandbox)

```
Claude Code writes a Python script using SDK helpers
= 1 tool call (sandbox_execute)
= All operations run in a single subprocess
= 1-5 seconds total
```

### Cloudflare Workers analogy

| Cloudflare Workers | Sandbox Executor |
|-------------------|-----------------|
| V8 isolate at the edge | Python/Node.js subprocess |
| fetch() API | http_get(), http_post() |
| KV bindings | read_file(), write_file() |
| Response object | output() structured results |
| Runs close to user | Runs on local machine |

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
│  │   ├── prelude.ts  │ SDK helper injection (Python/JS)
│  │   ├── runner.ts   │ Subprocess execution engine
│  │   └── validator.ts│ Basic safety checks
│  └── schemas/        │ Zod input validation
└──────────┬───────────┘
           │
           │ child_process.spawn()
           ▼
    ┌──────────────┐
    │  Python 3.12 │  or  Node.js
    │  subprocess  │
    │              │
    │  SDK helpers: │
    │  http_get()  │
    │  http_post() │
    │  read_file() │
    │  write_file()│
    │  output()    │
    └──────────────┘
```

## Tools

### `sandbox_execute`

Execute Python or JavaScript code with auto-injected SDK helpers.

**Input**:
```json
{
  "language": "python" | "javascript",
  "code": "...",
  "timeout": 30,
  "description": "What this code does"
}
```

**Output**: Markdown formatted result with status, duration, stdout/stderr, structured outputs.

### `sandbox_info`

Returns SDK documentation for the specified language.

**Input**:
```json
{
  "language": "python" | "javascript"
}
```

## SDK Helpers

All helpers are auto-injected as a prelude before user code. No imports needed.

### Python

```python
# HTTP
response = http_get(url, headers=None)          # Returns: {"status": int, "body": str, "headers": dict}
response = http_post(url, data=None, headers=None)

# File I/O
content = read_file(path)                       # Returns: str (file content)
write_file(path, content)                       # Auto-creates parent directories

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
| Stdout limit | 50KB |
| HTTP timeout | 15 seconds per request |
| Validation | Path traversal check only |
| Isolation | None — shares host filesystem and network |

## When to Use

| Scenario | Use sandbox? |
|----------|-------------|
| 3+ API calls (any URL) | Yes — one tool call replaces many |
| Batch file read → transform → write | Yes — efficient pipeline |
| Multi-service health check | Yes — parallel requests |
| Single file read | No — direct Read tool is simpler |
| Exploratory / need reasoning between steps | No — use sequential tool calls |
| Need MCP tools (Playwright, etc.) | No — sandbox has no MCP access |

## Configuration

### Location

```
~/workshop/stations/sandbox-executor/
├── src/           # TypeScript source
├── dist/          # Built JavaScript (run this)
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

After modifying source, rebuild and restart the LLM CLI to pick up changes.
