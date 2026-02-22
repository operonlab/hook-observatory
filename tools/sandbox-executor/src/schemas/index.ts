import { z } from "zod";

export const SandboxExecuteInput = z.object({
  language: z
    .enum(["python", "javascript"])
    .describe("Programming language to execute"),
  code: z
    .string()
    .min(1)
    .describe("Code to execute in the sandbox. SDK helpers (http_get, http_post, read_file, write_file, output) are auto-injected."),
  timeout: z
    .number()
    .min(1)
    .max(60)
    .default(30)
    .describe("Execution timeout in seconds (default: 30)"),
  description: z
    .string()
    .optional()
    .describe("Brief description of what this code does (for logging)"),
});

export const SandboxInfoInput = z.object({
  language: z
    .enum(["python", "javascript"])
    .default("python")
    .describe("Which language SDK to show docs for"),
});

export type SandboxExecuteArgs = z.infer<typeof SandboxExecuteInput>;
export type SandboxInfoArgs = z.infer<typeof SandboxInfoInput>;
