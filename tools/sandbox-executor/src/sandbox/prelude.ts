/**
 * Sandbox Prelude v2.0
 *
 * SDK helpers auto-injected before user code.
 * No path/host restrictions — sandbox is a batch execution engine,
 * not a security boundary.
 */

export function getPythonPrelude(): string {
  return `
import json as _json
import urllib.request as _urllib_request
import urllib.parse as _urllib_parse
import urllib.error as _urllib_error
import sys as _sys
import os as _os

_SANDBOX_RESULTS = []

def http_get(url, headers=None):
    """GET request. Returns parsed JSON or text."""
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
    """POST request. Returns parsed JSON or text."""
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
    """Read a file. Returns string content."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_file(path, content):
    """Write content to a file. Creates parent dirs automatically."""
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"

def output(data, label=None):
    """Register structured output. Will be returned in sandbox result."""
    entry = {"label": label, "data": data} if label else {"data": data}
    _SANDBOX_RESULTS.append(entry)

# End of prelude — user code begins below
`;
}

export function getJavaScriptPrelude(): string {
  return `
const _SANDBOX_RESULTS = [];
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
  return \`Written \${content.length} bytes to \${filePath}\`;
}

function output(data, label = null) {
  const entry = label ? { label, data } : { data };
  _SANDBOX_RESULTS.push(entry);
}

// End of prelude — user code begins below
`;
}

export function getPrelude(language: "python" | "javascript"): string {
  return language === "python" ? getPythonPrelude() : getJavaScriptPrelude();
}
