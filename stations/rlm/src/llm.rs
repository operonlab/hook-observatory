use std::time::Instant;
use tokio::process::Command;

/// Call Claude via headless CLI (claude -p).
/// Runs from /tmp to avoid loading project CLAUDE.md.
pub async fn call_claude(
    prompt: &str,
    system: &str,
    model: &str,
    timeout_secs: f64,
) -> Result<String, String> {
    let mut cmd = Command::new("claude");
    cmd.arg("-p")
        .arg("--model")
        .arg(model)
        .arg("--output-format")
        .arg("text")
        .current_dir("/tmp");

    if !system.is_empty() {
        cmd.arg("--system-prompt").arg(system);
    }

    let start = Instant::now();

    let child = cmd
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn claude: {e}"))?;

    // Write prompt to stdin
    let mut child = child;
    if let Some(mut stdin) = child.stdin.take() {
        use tokio::io::AsyncWriteExt;
        stdin
            .write_all(prompt.as_bytes())
            .await
            .map_err(|e| format!("stdin write error: {e}"))?;
        drop(stdin);
    }

    // Wait with timeout
    let timeout = std::time::Duration::from_secs_f64(timeout_secs);
    let output = tokio::time::timeout(timeout, child.wait_with_output())
        .await
        .map_err(|_| format!("claude -p timed out after {:.0}s", timeout_secs))?
        .map_err(|e| format!("claude -p error: {e}"))?;

    let elapsed = start.elapsed().as_secs_f64();

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "claude -p failed (rc={}) after {elapsed:.1}s: {}",
            output.status.code().unwrap_or(-1),
            &stderr[..stderr.len().min(500)]
        ));
    }

    let response = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(response)
}

/// Call claude concurrently for batched queries.
pub async fn call_claude_batched(
    prompts: &[String],
    model: &str,
    timeout_secs: f64,
) -> Vec<Result<String, String>> {
    let futures: Vec<_> = prompts
        .iter()
        .map(|p| call_claude(p, "", model, timeout_secs))
        .collect();

    futures::future::join_all(futures).await
}

/// Call LLM via OpenAI-compatible API (LiteLLM, xAI, etc) using curl.
pub async fn call_openai_compat(
    prompt: &str,
    system: &str,
    model: &str,
    api_base: &str,
    api_key: &str,
    timeout_secs: f64,
) -> Result<String, String> {
    let mut messages = Vec::new();
    if !system.is_empty() {
        messages.push(serde_json::json!({"role": "system", "content": system}));
    }
    messages.push(serde_json::json!({"role": "user", "content": prompt}));

    let body = serde_json::json!({
        "model": model,
        "messages": messages,
    });

    let url = format!("{api_base}/chat/completions");
    let mut cmd = Command::new("curl");
    cmd.arg("-s")
        .arg("--max-time")
        .arg(format!("{}", timeout_secs as u64))
        .arg("-X").arg("POST")
        .arg(&url)
        .arg("-H").arg("Content-Type: application/json")
        .arg("-H").arg(format!("Authorization: Bearer {api_key}"))
        .arg("-d").arg(body.to_string());

    let output = tokio::time::timeout(
        std::time::Duration::from_secs_f64(timeout_secs + 5.0),
        cmd.output(),
    )
    .await
    .map_err(|_| "API call timed out".to_string())?
    .map_err(|e| format!("curl error: {e}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("curl failed: {stderr}"));
    }

    let resp: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("JSON parse error: {e}"))?;

    resp.get("choices")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("message"))
        .and_then(|m| m.get("content"))
        .and_then(|c| c.as_str())
        .map(|s| s.trim().to_string())
        .ok_or_else(|| format!("Unexpected API response: {resp}"))
}
