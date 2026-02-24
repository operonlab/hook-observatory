import { spawn } from "child_process";
import { getPrelude } from "./prelude.js";

const OUTPUT_CAP = 50 * 1024; // 50KB
const RESULT_MARKER = "__SANDBOX_RESULT__";

export interface RunResult {
  success: boolean;
  stdout: string;
  stderr: string;
  outputs: unknown[];
  exitCode: number | null;
  timedOut: boolean;
  durationMs: number;
}

function buildPythonEpilogue(): string {
  return `
# Epilogue: emit structured results
if _SANDBOX_RESULTS:
    print("${RESULT_MARKER}")
    print(_json.dumps(_SANDBOX_RESULTS, ensure_ascii=False, default=str))
`;
}

function buildJsEpilogue(): string {
  return `
// Epilogue: emit structured results
;(async () => {
  if (_SANDBOX_RESULTS.length > 0) {
    console.log("${RESULT_MARKER}");
    console.log(JSON.stringify(_SANDBOX_RESULTS));
  }
})().catch(e => { console.error(e.message); process.exit(1); });
`;
}

function buildJsWrapper(prelude: string, userCode: string, epilogue: string): string {
  // Wrap user code in async IIFE for top-level await support
  return `${prelude}
(async () => {
${userCode}
})().then(() => {
${epilogue}
}).catch(e => { console.error(e.message); process.exit(1); });
`;
}

export async function runCode(
  language: "python" | "javascript",
  code: string,
  timeoutSec: number,
  pythonPath?: string
): Promise<RunResult> {
  const prelude = getPrelude(language);
  const start = Date.now();

  let fullCode: string;
  let cmd: string;
  let args: string[];

  if (language === "python") {
    fullCode = prelude + "\n" + code + "\n" + buildPythonEpilogue();
    cmd = pythonPath || "python3";
    args = ["-u", "-c", fullCode];
  } else {
    const epilogue = buildJsEpilogue();
    fullCode = buildJsWrapper(prelude, code, epilogue);
    cmd = "node";
    args = ["-e", fullCode];
  }

  return new Promise<RunResult>((resolve) => {
    let stdout = "";
    let stderr = "";
    let timedOut = false;

    const proc = spawn(cmd, args, {
      timeout: timeoutSec * 1000,
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: "1",
        NODE_NO_WARNINGS: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    proc.stdout.on("data", (chunk: Buffer) => {
      if (stdout.length < OUTPUT_CAP) {
        stdout += chunk.toString();
      }
    });

    proc.stderr.on("data", (chunk: Buffer) => {
      if (stderr.length < OUTPUT_CAP) {
        stderr += chunk.toString();
      }
    });

    proc.on("error", (err) => {
      resolve({
        success: false,
        stdout: stdout.slice(0, OUTPUT_CAP),
        stderr: err.message,
        outputs: [],
        exitCode: null,
        timedOut: false,
        durationMs: Date.now() - start,
      });
    });

    proc.on("close", (exitCode, signal) => {
      if (signal === "SIGTERM") {
        timedOut = true;
      }

      // Parse structured outputs from marker
      let outputs: unknown[] = [];
      const markerIdx = stdout.indexOf(RESULT_MARKER);
      let cleanStdout = stdout;

      if (markerIdx !== -1) {
        cleanStdout = stdout.slice(0, markerIdx).trimEnd();
        const jsonStr = stdout.slice(markerIdx + RESULT_MARKER.length).trim();
        try {
          outputs = JSON.parse(jsonStr);
        } catch {
          // If parse fails, include raw in stderr
          stderr += `\nFailed to parse sandbox outputs: ${jsonStr.slice(0, 200)}`;
        }
      }

      resolve({
        success: exitCode === 0 && !timedOut,
        stdout: cleanStdout.slice(0, OUTPUT_CAP),
        stderr: stderr.slice(0, OUTPUT_CAP),
        outputs,
        exitCode,
        timedOut,
        durationMs: Date.now() - start,
      });
    });
  });
}
