"""Sandbox execution engine — run Python/JS code with auto-injected SDK helpers.

Unlike other Workshop clients (which wrap HTTP APIs), SandboxClient is a local
execution engine that spawns subprocesses. It does NOT inherit from BaseClient.

Usage:
    from workshop.clients.sandbox import SandboxClient

    client = SandboxClient()
    result = client.execute('print("hello")')
    result = client.execute_file("/tmp/script.py")
    print(result.to_dict())
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field

OUTPUT_CAP = 50 * 1024  # 50KB
RESULT_MARKER = "__SANDBOX_RESULT__"


@dataclass
class RunResult:
    """Result of a sandbox execution."""

    success: bool
    stdout: str
    stderr: str
    outputs: list = field(default_factory=list)
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "outputs": self.outputs,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
        }


# ======================== Preludes ========================


def get_python_prelude() -> str:
    return """import json as _json
import urllib.request as _urllib_request
import urllib.parse as _urllib_parse
import urllib.error as _urllib_error
import sys as _sys
import os as _os

_SANDBOX_RESULTS = []

def http_get(url, headers=None):
    \"\"\"GET request. Returns parsed JSON or text.\"\"\"
    req = _urllib_request.Request(url, headers=headers or {})
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            try:
                return _json.loads(body)
            except _json.JSONDecodeError:
                return body
    except _urllib_error.HTTPError as e:
        return {"error": e.code, "reason": e.reason, "body": e.read().decode("utf-8", errors="replace")}
    except _urllib_error.URLError as e:
        return {"error": "URLError", "reason": str(e.reason)}

def http_post(url, data=None, headers=None):
    \"\"\"POST request. Returns parsed JSON or text.\"\"\"
    h = headers or {}
    if "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    body = _json.dumps(data).encode("utf-8") if data else None
    req = _urllib_request.Request(url, data=body, headers=h, method="POST")
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return _json.loads(raw)
            except _json.JSONDecodeError:
                return raw
    except _urllib_error.HTTPError as e:
        return {"error": e.code, "reason": e.reason, "body": e.read().decode("utf-8", errors="replace")}
    except _urllib_error.URLError as e:
        return {"error": "URLError", "reason": str(e.reason)}

def read_file(path):
    \"\"\"Read a file. Returns string content.\"\"\"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_file(path, content):
    \"\"\"Write content to a file. Creates parent dirs automatically.\"\"\"
    _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"

def output(data, label=None):
    \"\"\"Register structured output. Will be returned in sandbox result.\"\"\"
    entry = {"label": label, "data": data} if label else {"data": data}
    _SANDBOX_RESULTS.append(entry)

# End of prelude — user code begins below
"""


def get_javascript_prelude() -> str:
    return """const _SANDBOX_RESULTS = [];
const _fs = require("fs");
const _path = require("path");

async function http_get(url, headers = {}) {
  const resp = await fetch(url, { headers, signal: AbortSignal.timeout(15000) });
  const text = await resp.text();
  try { return JSON.parse(text); } catch { return text; }
}

async function http_post(url, data = null, headers = {}) {
  if (!headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const resp = await fetch(url, {
    method: "POST",
    headers,
    body: data ? JSON.stringify(data) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  const text = await resp.text();
  try { return JSON.parse(text); } catch { return text; }
}

function read_file(filePath) {
  return _fs.readFileSync(filePath, "utf-8");
}

function write_file(filePath, content) {
  _fs.mkdirSync(_path.dirname(filePath), { recursive: true });
  _fs.writeFileSync(filePath, content, "utf-8");
  return `Written ${content.length} bytes to ${filePath}`;
}

function output(data, label = null) {
  const entry = label ? { label, data } : { data };
  _SANDBOX_RESULTS.push(entry);
}

// End of prelude — user code begins below
"""


def get_prelude(language: str) -> str:
    if language == "python":
        return get_python_prelude()
    elif language == "javascript":
        return get_javascript_prelude()
    raise ValueError(f"Unsupported language: {language}")


# ======================== Epilogues ========================


def _build_python_epilogue() -> str:
    return f"""
# Epilogue: emit structured results
if _SANDBOX_RESULTS:
    print("{RESULT_MARKER}")
    print(_json.dumps(_SANDBOX_RESULTS, ensure_ascii=False, default=str))
"""


def _build_js_epilogue() -> str:
    return f"""
// Epilogue: emit structured results
;(async () => {{
  if (_SANDBOX_RESULTS.length > 0) {{
    console.log("{RESULT_MARKER}");
    console.log(JSON.stringify(_SANDBOX_RESULTS));
  }}
}})().catch(e => {{ console.error(e.message); process.exit(1); }});"""


def _build_js_wrapper(prelude: str, user_code: str, epilogue: str) -> str:
    return f"""{prelude}
(async () => {{
{user_code}
}})().then(() => {{
{epilogue}
}}).catch(e => {{ console.error(e.message); process.exit(1); }});
"""


# ======================== Output Parsing ========================


def _parse_outputs(stdout: str) -> tuple[str, list]:
    """Extract structured outputs from stdout via RESULT_MARKER."""
    marker_idx = stdout.find(RESULT_MARKER)
    if marker_idx == -1:
        return stdout, []

    clean_stdout = stdout[:marker_idx].rstrip()
    json_str = stdout[marker_idx + len(RESULT_MARKER) :].strip()
    try:
        outputs = json.loads(json_str)
    except json.JSONDecodeError:
        return clean_stdout, []
    return clean_stdout, outputs


# ======================== Client ========================


class SandboxClient:
    """Local code execution engine with auto-injected SDK helpers.

    Args:
        python_path: Path to Python interpreter. Defaults to PYTHON_PATH env or "python3".
        default_timeout: Default execution timeout in seconds.
    """

    def __init__(
        self,
        python_path: str | None = None,
        default_timeout: int = 30,
    ):
        self.python_path = python_path or os.environ.get("PYTHON_PATH", "python3")
        self.default_timeout = default_timeout

    def execute(
        self,
        code: str,
        language: str = "python",
        timeout: int | None = None,
    ) -> RunResult:
        """Execute code with auto-injected SDK helpers.

        Args:
            code: Source code to execute.
            language: "python" or "javascript".
            timeout: Execution timeout in seconds (1-60).
        """
        timeout = min(max(timeout or self.default_timeout, 1), 60)
        prelude = get_prelude(language)
        start = time.monotonic()

        if language == "python":
            full_code = prelude + "\n" + code + "\n" + _build_python_epilogue()
            cmd = [self.python_path, "-u", "-c", full_code]
        elif language == "javascript":
            epilogue = _build_js_epilogue()
            full_code = _build_js_wrapper(prelude, code, epilogue)
            cmd = ["node", "-e", full_code]
        else:
            raise ValueError(f"Unsupported language: {language}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "NODE_NO_WARNINGS": "1",
                },
            )
            stdout = (proc.stdout or "")[:OUTPUT_CAP]
            stderr = (proc.stderr or "")[:OUTPUT_CAP]
            clean_stdout, outputs = _parse_outputs(stdout)

            return RunResult(
                success=proc.returncode == 0,
                stdout=clean_stdout[:OUTPUT_CAP],
                stderr=stderr,
                outputs=outputs,
                exit_code=proc.returncode,
                timed_out=False,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except subprocess.TimeoutExpired as e:
            stdout = ""
            stderr = ""
            if e.stdout:
                stdout = (
                    e.stdout
                    if isinstance(e.stdout, str)
                    else e.stdout.decode("utf-8", errors="replace")
                )[:OUTPUT_CAP]
            if e.stderr:
                stderr = (
                    e.stderr
                    if isinstance(e.stderr, str)
                    else e.stderr.decode("utf-8", errors="replace")
                )[:OUTPUT_CAP]

            return RunResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                outputs=[],
                exit_code=None,
                timed_out=True,
                duration_ms=int((time.monotonic() - start) * 1000),
            )

    def execute_file(
        self,
        file_path: str,
        language: str | None = None,
        timeout: int | None = None,
    ) -> RunResult:
        """Execute code from a file.

        Args:
            file_path: Path to the source file.
            language: Override language detection. Auto-detected from extension if None.
            timeout: Execution timeout in seconds.
        """
        if not language:
            ext = os.path.splitext(file_path)[1].lower().lstrip(".")
            language = {"py": "python", "js": "javascript", "mjs": "javascript"}.get(ext, "python")

        with open(file_path, encoding="utf-8") as f:
            code = f.read()

        return self.execute(code, language=language, timeout=timeout)

    def info(self, language: str = "python") -> str:
        """Return SDK documentation for the specified language."""
        if language == "python":
            return """# Sandbox SDK — Python

## Available Functions

### http_get(url, headers=None)
GET request to any URL. Returns parsed JSON or raw text.

### http_post(url, data=None, headers=None)
POST request to any URL. Auto-sets Content-Type: application/json.

### read_file(path)
Read any file. Returns string content.

### write_file(path, content)
Write to any file. Creates parent dirs automatically.

### output(data, label=None)
Register structured output — returned in sandbox result as JSON.

## Constraints
- Timeout: Default 30s, max 60s
- Output cap: 50KB stdout
- All stdlib modules available (subprocess, os, etc.)
- External libs: Pillow, openpyxl, pypdf, pdfplumber, python-pptx, python-docx"""
        else:
            return """# Sandbox SDK — JavaScript

## Available Functions

### await http_get(url, headers={})
GET request to any URL. Returns parsed JSON or raw text.

### await http_post(url, data=null, headers={})
POST request to any URL.

### read_file(path)
Synchronous file read from any path.

### write_file(path, content)
Write to any file. Creates parent dirs automatically.

### output(data, label=null)
Register structured output.

## Constraints
- Timeout: Default 30s, max 60s
- Output cap: 50KB stdout
- Top-level await: Supported (code runs inside async IIFE)"""

    def __repr__(self) -> str:
        return f"SandboxClient(python_path={self.python_path!r})"
