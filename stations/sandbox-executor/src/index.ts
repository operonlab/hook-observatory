#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SandboxExecuteInput, SandboxInfoInput } from "./schemas/index.js";
import { handleExecute, handleInfo } from "./tools/execute.js";

const server = new McpServer({
  name: "sandbox-executor",
  version: "1.0.0",
});

// Tool 1: sandbox_execute — run code in sandbox with SDK helpers
server.tool(
  "sandbox_execute",
  "Execute Python/JS code with auto-injected SDK helpers: http_get(), http_post(), read_file(), write_file(), output(). Use this to batch multiple operations into a single execution — read/write any file, call any HTTP endpoint, process data. Returns structured results via output(). Timeout: 30s default, 60s max.",
  SandboxExecuteInput.shape,
  async (args) => handleExecute(args)
);

// Tool 2: sandbox_info — show SDK documentation
server.tool(
  "sandbox_info",
  "Show documentation for the sandbox SDK helpers (available functions, constraints, examples).",
  SandboxInfoInput.shape,
  async (args) => handleInfo(args)
);

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("sandbox-executor MCP server running on stdio");
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
