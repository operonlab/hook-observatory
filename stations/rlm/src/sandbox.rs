use std::collections::HashMap;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};

const SANDBOX_PRELUDE: &str = r#"
import sys, io, json, traceback

# Safe builtins — block eval/exec/compile/input
_BLOCKED = {'eval', 'exec', 'compile', 'input', 'globals', 'locals'}

def _run_code(code, env):
    """Execute code in sandbox, return (stdout, stderr, new_vars)."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf
    try:
        exec(code, env, env)
    except Exception:
        stderr_buf.write(traceback.format_exc())
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    # Collect user vars (non-internal, non-callable-builtins)
    user_vars = {}
    for k, v in env.items():
        if not k.startswith('_') and k not in ('__builtins__',):
            try:
                json.dumps(v)  # only serializable
                user_vars[k] = repr(v)[:200]
            except (TypeError, ValueError):
                user_vars[k] = type(v).__name__
    return stdout_buf.getvalue(), stderr_buf.getvalue(), user_vars

# Initialize sandbox environment
_env = {'__builtins__': {k: v for k, v in __builtins__.__dict__.items() if k not in _BLOCKED}}
_env['__builtins__']['True'] = True
_env['__builtins__']['False'] = False
_env['__builtins__']['None'] = None

# Signal ready
print("__RLM_SANDBOX_READY__", flush=True)

# Main loop: read JSON commands, execute, return results
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError:
        print(json.dumps({"error": "invalid JSON"}), flush=True)
        continue

    action = cmd.get("action", "")

    if action == "exec":
        code = cmd.get("code", "")
        stdout, stderr, user_vars = _run_code(code, _env)
        print(json.dumps({
            "stdout": stdout[:50000],
            "stderr": stderr[:5000],
            "vars": user_vars,
        }), flush=True)

    elif action == "inject":
        name = cmd["name"]
        value = cmd["value"]
        _env[name] = value
        print(json.dumps({"ok": True}), flush=True)

    elif action == "inject_code":
        # Inject by executing code (for functions, complex objects)
        code = cmd["code"]
        _run_code(code, _env)
        print(json.dumps({"ok": True}), flush=True)

    elif action == "get_var":
        name = cmd["name"]
        val = _env.get(name)
        if val is not None:
            print(json.dumps({"value": str(val)}), flush=True)
        else:
            print(json.dumps({"value": None}), flush=True)

    elif action == "list_vars":
        user_vars = {k: type(v).__name__ for k, v in _env.items()
                     if not k.startswith('_') and k != '__builtins__'}
        print(json.dumps({"vars": user_vars}), flush=True)

    elif action == "quit":
        break

    else:
        print(json.dumps({"error": f"unknown action: {action}"}), flush=True)
"#;

/// Persistent Python REPL sandbox.
/// Keeps one Python process alive for the entire RLM session.
pub struct PersistentRepl {
    child: Child,
    stdin: tokio::process::ChildStdin,
    reader: BufReader<tokio::process::ChildStdout>,
    pub final_answer: Option<String>,
}

impl PersistentRepl {
    /// Spawn a persistent Python sandbox process.
    pub async fn new() -> Result<Self, String> {
        let mut child = Command::new("python3")
            .arg("-u") // unbuffered
            .arg("-c")
            .arg(SANDBOX_PRELUDE)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .map_err(|e| format!("Failed to spawn Python sandbox: {e}"))?;

        let stdin = child.stdin.take().ok_or("No stdin")?;
        let stdout = child.stdout.take().ok_or("No stdout")?;
        let mut reader = BufReader::new(stdout);

        // Wait for ready signal
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .await
            .map_err(|e| format!("Sandbox startup error: {e}"))?;

        if !line.contains("__RLM_SANDBOX_READY__") {
            return Err(format!("Sandbox not ready: {line}"));
        }

        Ok(Self {
            child,
            stdin,
            reader,
            final_answer: None,
        })
    }

    /// Execute Python code in the sandbox. Returns (stdout, stderr).
    pub async fn execute(&mut self, code: &str) -> (String, String) {
        let cmd = serde_json::json!({
            "action": "exec",
            "code": code,
        });

        if let Err(e) = self.send_cmd(&cmd).await {
            return (String::new(), format!("sandbox send error: {e}"));
        }

        match self.read_response().await {
            Ok(resp) => {
                let stdout = resp
                    .get("stdout")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let stderr = resp
                    .get("stderr")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                (stdout, stderr)
            }
            Err(e) => (String::new(), format!("sandbox read error: {e}")),
        }
    }

    /// Inject a string variable into the sandbox.
    pub async fn inject_str(&mut self, name: &str, value: &str) -> Result<(), String> {
        // Use inject_code to handle arbitrary strings safely
        let escaped = value.replace('\\', "\\\\").replace('\'', "\\'");
        let code = format!("{name} = '''{escaped}'''");
        let cmd = serde_json::json!({
            "action": "inject_code",
            "code": code,
        });
        self.send_cmd(&cmd).await?;
        let _ = self.read_response().await;
        Ok(())
    }

    /// Inject a list of strings into the sandbox.
    pub async fn inject_str_list(&mut self, name: &str, values: &[String]) -> Result<(), String> {
        // Serialize as JSON array, then parse in Python
        let json_arr = serde_json::to_string(values).map_err(|e| e.to_string())?;
        let code = format!(
            "import json as _json; {name} = _json.loads('''{}''')",
            json_arr.replace('\'', "\\'")
        );
        let cmd = serde_json::json!({
            "action": "inject_code",
            "code": code,
        });
        self.send_cmd(&cmd).await?;
        let _ = self.read_response().await;
        Ok(())
    }

    /// Get a variable's string value from the sandbox.
    pub async fn get_var(&mut self, name: &str) -> Option<String> {
        let cmd = serde_json::json!({
            "action": "get_var",
            "name": name,
        });
        self.send_cmd(&cmd).await.ok()?;
        let resp = self.read_response().await.ok()?;
        resp.get("value")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
    }

    /// List user variables.
    pub async fn list_vars(&mut self) -> HashMap<String, String> {
        let cmd = serde_json::json!({"action": "list_vars"});
        if self.send_cmd(&cmd).await.is_err() {
            return HashMap::new();
        }
        match self.read_response().await {
            Ok(resp) => {
                if let Some(vars) = resp.get("vars").and_then(|v| v.as_object()) {
                    vars.iter()
                        .map(|(k, v)| (k.clone(), v.as_str().unwrap_or("?").to_string()))
                        .collect()
                } else {
                    HashMap::new()
                }
            }
            Err(_) => HashMap::new(),
        }
    }

    async fn send_cmd(&mut self, cmd: &serde_json::Value) -> Result<(), String> {
        let mut line = serde_json::to_string(cmd).map_err(|e| e.to_string())?;
        line.push('\n');
        self.stdin
            .write_all(line.as_bytes())
            .await
            .map_err(|e| format!("stdin write: {e}"))
    }

    async fn read_response(&mut self) -> Result<serde_json::Value, String> {
        let mut line = String::new();
        let timeout = tokio::time::timeout(
            std::time::Duration::from_secs(30),
            self.reader.read_line(&mut line),
        )
        .await
        .map_err(|_| "sandbox response timeout".to_string())?
        .map_err(|e| format!("read error: {e}"))?;

        if timeout == 0 {
            return Err("sandbox EOF".into());
        }

        serde_json::from_str(line.trim()).map_err(|e| format!("JSON parse: {e}: {line}"))
    }
}

impl Drop for PersistentRepl {
    fn drop(&mut self) {
        // Best-effort cleanup
        let _ = self.child.start_kill();
    }
}
