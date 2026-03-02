---
source_hash: b444f179
source_lang: en
target_lang: en
translated_at: 2026-02-24
---

# Sandbox Executor

MCP server for batch code execution — provides Python/JS sandbox with SDK helpers for LLM CLI tools.

## Concept

Inspired by Cloudflare Workers' "code execution at the edge" model. Instead of making N individual tool calls (Read, Bash, HTTP), bundle deterministic operations into a single code execution with pre-injected SDK helpers.

## Tools

| Tool | Description |
|------|-------------|
| `sandbox_execute` | Execute Python/JS code with SDK helpers |
| `sandbox_info` | View SDK documentation and examples |

## SDK Helpers (auto-injected)

| Function | Description |
|----------|-------------|
| `http_get(url, headers?)` | GET request (15s timeout) |
| `http_post(url, data?, headers?)` | POST request (15s timeout) |
| `read_file(path)` | Read file contents |
| `write_file(path, content)` | Write file (auto-creates parent dirs) |
| `output(data, label?)` | Register structured output |

## Consumers

- **Claude Code** (`~/.claude.json`)
- **Gemini CLI** (`~/.gemini/settings.json`)
- **Codex CLI** (indirect, via dispatcher agents)

## Development

```bash
cd tools/sandbox-executor
npm install
npm run build    # TypeScript → dist/
npm run dev      # Watch mode
```

## Constraints

- Timeout: 1-60 seconds (default 30)
- Stdout limit: 50KB
- Not a security sandbox — it's a batch execution engine
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2632ms
Hook execution for SessionEnd: 2 hooks executed successfully, total duration: 2563ms
