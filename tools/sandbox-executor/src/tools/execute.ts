import { validateCode } from "../sandbox/validator.js";
import { runCode, type RunResult } from "../sandbox/runner.js";
import type { SandboxExecuteArgs, SandboxInfoArgs } from "../schemas/index.js";
import { getPrelude } from "../sandbox/prelude.js";

function formatResult(result: RunResult, description?: string): string {
  const parts: string[] = [];

  if (description) {
    parts.push(`## Task: ${description}`);
  }

  parts.push(`**Status**: ${result.success ? "✅ Success" : "❌ Failed"}`);
  parts.push(`**Duration**: ${result.durationMs}ms`);

  if (result.timedOut) {
    parts.push("**⚠️ Execution timed out**");
  }

  if (result.stdout.trim()) {
    const stdout = result.stdout.length > 5000
      ? result.stdout.slice(0, 5000) + "\n... (truncated)"
      : result.stdout;
    parts.push(`\n### stdout\n\`\`\`\n${stdout}\n\`\`\``);
  }

  if (result.stderr.trim()) {
    const stderr = result.stderr.length > 2000
      ? result.stderr.slice(0, 2000) + "\n... (truncated)"
      : result.stderr;
    parts.push(`\n### stderr\n\`\`\`\n${stderr}\n\`\`\``);
  }

  if (result.outputs.length > 0) {
    parts.push("\n### Structured Outputs");
    for (const entry of result.outputs) {
      const obj = entry as { label?: string; data: unknown };
      const label = obj.label ? `**${obj.label}**` : "";
      const data = typeof obj.data === "string"
        ? obj.data
        : JSON.stringify(obj.data, null, 2);
      const truncated = data.length > 8000
        ? data.slice(0, 8000) + "\n... (truncated)"
        : data;
      parts.push(`${label}\n\`\`\`json\n${truncated}\n\`\`\``);
    }
  }

  return parts.join("\n");
}

export async function handleExecute(args: SandboxExecuteArgs) {
  const { language, code, timeout, description } = args;

  // Step 1: Validate
  const validation = validateCode(code, language);
  if (!validation.valid) {
    return {
      content: [
        {
          type: "text" as const,
          text: `🚫 **Security Validation Failed**\n\n${validation.reason}`,
        },
      ],
    };
  }

  // Step 2: Execute
  const pythonPath = process.env.PYTHON_PATH;
  const result = await runCode(language, code, timeout, pythonPath);

  // Step 3: Format output
  return {
    content: [
      {
        type: "text" as const,
        text: formatResult(result, description),
      },
    ],
  };
}

export async function handleInfo(args: SandboxInfoArgs) {
  const { language } = args;
  const prelude = getPrelude(language);

  const docs = language === "python"
    ? `# Sandbox SDK — Python

## Available Functions

### http_get(url, headers=None)
GET request to any URL. Returns parsed JSON or raw text.
\`\`\`python
data = http_get("http://localhost:8793/api/finance/summary")
external = http_get("https://api.example.com/data")
\`\`\`

### http_post(url, data=None, headers=None)
POST request to any URL. Auto-sets Content-Type: application/json.
\`\`\`python
result = http_post("http://localhost:8830/api/search", {"query": "test"})
\`\`\`

### read_file(path)
Read any file. Returns string content.
\`\`\`python
content = read_file("/Users/joneshong/.claude/skills/my-skill/SKILL.md")
\`\`\`

### write_file(path, content)
Write to any file. Creates parent dirs automatically.
\`\`\`python
write_file("/tmp/sandbox-executor/output.json", json.dumps(data))
\`\`\`

### output(data, label=None)
Register structured output — returned in sandbox result as JSON.
\`\`\`python
output({"total": 100, "items": [...]}, label="Summary")
\`\`\`

## Constraints
- **Timeout**: Default 30s, max 60s
- **Output cap**: 50KB stdout
- All stdlib modules available (subprocess, os, etc.)
- External libs: Pillow, openpyxl, pypdf, pdfplumber, python-pptx, python-docx`
    : `# Sandbox SDK — JavaScript

## Available Functions

### await http_get(url, headers={})
GET request to any URL. Returns parsed JSON or raw text.
\`\`\`javascript
const data = await http_get("http://localhost:8793/api/finance/summary");
const external = await http_get("https://api.example.com/data");
\`\`\`

### await http_post(url, data=null, headers={})
POST request to any URL.
\`\`\`javascript
const result = await http_post("http://localhost:8830/api/search", { query: "test" });
\`\`\`

### read_file(path)
Synchronous file read from any path.
\`\`\`javascript
const content = read_file("/Users/joneshong/.claude/skills/my-skill/SKILL.md");
\`\`\`

### write_file(path, content)
Write to any file. Creates parent dirs automatically.
\`\`\`javascript
write_file("/tmp/sandbox-executor/output.json", JSON.stringify(data));
\`\`\`

### output(data, label=null)
Register structured output.
\`\`\`javascript
output({ total: 100, items: [...] }, "Summary");
\`\`\`

## Constraints
- **Timeout**: Default 30s, max 60s
- **Output cap**: 50KB stdout
- **Top-level await**: Supported (code runs inside async IIFE)`;

  return {
    content: [
      {
        type: "text" as const,
        text: docs,
      },
    ],
  };
}
