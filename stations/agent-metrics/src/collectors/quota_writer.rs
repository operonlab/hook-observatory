//! Quota writer — fetches Anthropic / Codex / Gemini quotas, writes Redis.
//!
//! Replaces the Python `quota_sidecar.py` after Phase 5b-2. The Rust binary
//! runs this in a background tokio task alongside sysmon_loop + aggregator,
//! so the deployment shrinks back to a single binary (no Python sidecar).
//!
//! Camoufox-based scraping fallback for CC (when Anthropic returns 429) is
//! NOT ported in this phase — it's a rare edge case, and the existing Python
//! sidecar can be re-introduced for that path if needed.

use crate::config::Settings;
use anyhow::{Context, Result};
use chrono::Utc;
use once_cell::sync::Lazy;
use redis::AsyncCommands;
use serde_json::{json, Value};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tokio::process::Command;

const RKEY_FORMATTED: &str = "agent-metrics:quota:formatted";
const RKEY_RAW: &str = "agent-metrics:quota:raw";
const RKEY_CC_RAW: &str = "agent-metrics:quota:cc_raw";

const CC_QUOTA_FETCH_INTERVAL_S: u64 = 1800; // 30 min
const CC_QUOTA_BACKOFF_BASE_S: u64 = 1800;
const CC_QUOTA_STALE_MAX_S: u64 = 86400;
const QUOTA_CACHE_TTL_S: u64 = 120;
const GM_PROJECT_TTL_S: u64 = 3600;

#[derive(Debug, Default, Clone)]
struct CcState {
    last_success: Option<Value>,
    last_success_ts: Option<Instant>,
    backoff_until: Option<Instant>,
    consecutive_failures: u32,
    last_fetch_mode: String,
}

#[derive(Debug, Default, Clone)]
struct GmState {
    project: Option<String>,
    project_ts: Option<Instant>,
}

static CC_STATE: Lazy<Mutex<CcState>> = Lazy::new(|| Mutex::new(CcState::default()));
static GM_STATE: Lazy<Mutex<GmState>> = Lazy::new(|| Mutex::new(GmState::default()));

fn elapsed_since(t: Option<Instant>) -> Duration {
    t.map(|i| i.elapsed()).unwrap_or(Duration::MAX)
}

fn round_pct(v: f64) -> i64 {
    v.round() as i64
}

fn http_client() -> Result<reqwest::Client> {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .context("build reqwest client")
}

async fn open_redis(cfg: &Settings) -> Option<redis::aio::ConnectionManager> {
    let c = redis::Client::open(cfg.redis_url.clone()).ok()?;
    redis::aio::ConnectionManager::new(c).await.ok()
}

/// Read the persisted CC raw payload from Redis. Used as a fallback when
/// the Anthropic API is rate-limited and we have no in-process state.
async fn read_cc_raw_redis() -> Value {
    let url = std::env::var("AGENT_METRICS_REDIS_URL")
        .unwrap_or_else(|_| "redis://localhost:6379/0".into());
    let client = match redis::Client::open(url) {
        Ok(c) => c,
        Err(_) => return Value::Null,
    };
    let mut conn = match redis::aio::ConnectionManager::new(client).await {
        Ok(c) => c,
        Err(_) => return Value::Null,
    };
    let raw: Option<String> = conn.get(RKEY_CC_RAW).await.ok();
    raw.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null)
}

// ── Anthropic / Claude Code ─────────────────────────────────────

fn token_from_creds_json(raw: &str, source: &str) -> Option<String> {
    let creds: Value = match serde_json::from_str(raw) {
        Ok(v) => v,
        Err(e) => {
            tracing::debug!(error = %e, source, raw_prefix = %&raw.chars().take(60).collect::<String>(), "cc_creds_json_parse_failed");
            return None;
        }
    };
    let token = creds
        .get("claudeAiOauth")
        .and_then(|v| v.get("accessToken"))
        .and_then(|v| v.as_str())
        .map(String::from);
    if token.is_none() {
        tracing::debug!(source, top_keys = ?creds.as_object().map(|m| m.keys().collect::<Vec<_>>()), "cc_no_access_token_in_creds");
    }
    token
}

/// Claude Code v2 stores the OAuth credentials in `~/.claude/.credentials.json`.
/// Older builds (and Claude Desktop) stash them in the macOS Keychain under
/// `Claude Code-credentials`. Try the file first; fall back to the Keychain.
///
/// Self-heal: when the Keychain path succeeds but the file is missing, mirror
/// the raw credentials JSON to disk (mode 0o600) so subsequent calls hit the
/// fast path. This protects against launchd-spawned processes (PPID=1) whose
/// Keychain ACL is unpredictable across reboots.
async fn read_cc_token() -> Option<String> {
    let creds_path = std::env::var("HOME")
        .ok()
        .map(|h| format!("{h}/.claude/.credentials.json"));

    if let Some(path) = creds_path.as_deref() {
        match tokio::fs::read_to_string(path).await {
            Ok(body) => {
                if let Some(t) = token_from_creds_json(&body, "credentials_json") {
                    return Some(t);
                }
            }
            Err(e) => {
                tracing::debug!(path, error = %e, "cc_credentials_json_read_failed");
            }
        }
    }

    let out = match Command::new("security")
        .args(["find-generic-password", "-s", "Claude Code-credentials", "-w"])
        .output()
        .await
    {
        Ok(o) => o,
        Err(e) => {
            tracing::warn!(error = %e, "cc_security_spawn_failed (no token source available)");
            return None;
        }
    };
    if !out.status.success() {
        tracing::warn!(rc = ?out.status.code(), stderr = %String::from_utf8_lossy(&out.stderr), "cc_security_nonzero (no token source available)");
        return None;
    }
    let raw = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let token = token_from_creds_json(&raw, "keychain");

    if token.is_some() {
        if let Some(path) = creds_path.as_deref() {
            match persist_cc_creds_file(path, &raw).await {
                Ok(()) => tracing::warn!(path, "cc_creds_self_healed_from_keychain"),
                Err(e) => tracing::warn!(path, error = %e, "cc_creds_self_heal_write_failed"),
            }
        }
    }

    token
}

/// Write `body` to `path` atomically with mode 0o600 (parent dir created if missing).
/// Tmp-file + rename keeps readers from seeing a partial write.
async fn persist_cc_creds_file(path: &str, body: &str) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let p = std::path::Path::new(path);
    if let Some(parent) = p.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let tmp = format!("{path}.tmp");
    tokio::fs::write(&tmp, body).await?;
    let mut perms = tokio::fs::metadata(&tmp).await?.permissions();
    perms.set_mode(0o600);
    tokio::fs::set_permissions(&tmp, perms).await?;
    tokio::fs::rename(&tmp, path).await?;
    Ok(())
}

async fn fetch_cc(client: &reqwest::Client) -> Value {
    // Backoff path: skip the API entirely while rate-limited. Compute the
    // decision in a non-async block so the MutexGuard is fully released
    // before any `.await`.
    enum BackoffDecision {
        Proceed,
        UseLast(Value),
        UseRedisFallback,
    }
    let decision = {
        let state = CC_STATE.lock().unwrap();
        if let Some(b) = state.backoff_until {
            if Instant::now() < b {
                if let Some(last) = state.last_success.clone() {
                    BackoffDecision::UseLast(last)
                } else {
                    BackoffDecision::UseRedisFallback
                }
            } else {
                BackoffDecision::Proceed
            }
        } else {
            BackoffDecision::Proceed
        }
    };
    match decision {
        BackoffDecision::UseLast(v) => return v,
        BackoffDecision::UseRedisFallback => return read_cc_raw_redis().await,
        BackoffDecision::Proceed => {}
    }

    let token = match read_cc_token().await {
        Some(t) => t,
        None => return Value::Null,
    };

    let resp = client
        .get("https://api.anthropic.com/api/oauth/usage")
        .header("Authorization", format!("Bearer {token}"))
        .header("anthropic-beta", "oauth-2025-04-20")
        .send()
        .await;

    let resp = match resp {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!(error = %e, "cc_quota_send_failed");
            let mut state = CC_STATE.lock().unwrap();
            state.last_fetch_mode = "error_fallback".into();
            return state.last_success.clone().unwrap_or(Value::Null);
        }
    };

    if resp.status() == 429 {
        let retry_after_hdr = resp
            .headers()
            .get("retry-after")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse::<u64>().ok())
            .unwrap_or(0);
        let last_success_age = {
            let mut state = CC_STATE.lock().unwrap();
            state.consecutive_failures = state.consecutive_failures.saturating_add(1);
            let exp = state.consecutive_failures.saturating_sub(1).min(4);
            let base = CC_QUOTA_BACKOFF_BASE_S * 2_u64.pow(exp);
            let backoff = base.max(retry_after_hdr);
            state.backoff_until = Some(Instant::now() + Duration::from_secs(backoff));
            state.last_fetch_mode = "rate_limited".into();
            tracing::warn!(
                backoff_s = backoff,
                consecutive = state.consecutive_failures,
                "quota_cc_rate_limited"
            );
            elapsed_since(state.last_success_ts)
        };
        if last_success_age <= Duration::from_secs(CC_QUOTA_STALE_MAX_S) {
            return CC_STATE
                .lock()
                .unwrap()
                .last_success
                .clone()
                .unwrap_or(Value::Null);
        }
        // No in-process state — fall back to last value Python or earlier
        // Rust runs left in Redis. Fresh `agent-metrics:quota:cc_raw` survives
        // restarts and is the closest analog to the Python `_persist_cc_quota`
        // disk fallback.
        return read_cc_raw_redis().await;
    }

    if !resp.status().is_success() {
        let mut state = CC_STATE.lock().unwrap();
        state.last_fetch_mode = format!("http_status_{}", resp.status().as_u16());
        if elapsed_since(state.last_success_ts) <= Duration::from_secs(CC_QUOTA_STALE_MAX_S) {
            return state.last_success.clone().unwrap_or(Value::Null);
        }
        return Value::Null;
    }

    match resp.json::<Value>().await {
        Ok(data) => {
            let mut state = CC_STATE.lock().unwrap();
            state.last_success = Some(data.clone());
            state.last_success_ts = Some(Instant::now());
            state.backoff_until = None;
            state.consecutive_failures = 0;
            state.last_fetch_mode = "live".into();
            data
        }
        Err(_) => {
            let state = CC_STATE.lock().unwrap();
            state.last_success.clone().unwrap_or(Value::Null)
        }
    }
}

// ── Codex / ChatGPT ─────────────────────────────────────────────

async fn fetch_cx(client: &reqwest::Client) -> Value {
    let path = std::env::var("HOME")
        .map(|h| format!("{h}/.codex/auth.json"))
        .unwrap_or_default();
    let body = match tokio::fs::read_to_string(&path).await {
        Ok(s) => s,
        Err(e) => {
            tracing::debug!(path, error = %e, "cx_auth_read_failed");
            return Value::Null;
        }
    };
    let auth: Value = match serde_json::from_str(&body) {
        Ok(v) => v,
        Err(e) => {
            tracing::debug!(error = %e, "cx_auth_json_parse_failed");
            return Value::Null;
        }
    };
    let token = auth.pointer("/tokens/access_token").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let acct = auth.pointer("/tokens/account_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if token.is_empty() || acct.is_empty() {
        return Value::Null;
    }
    let resp = client
        .get("https://chatgpt.com/backend-api/wham/usage")
        .header("Authorization", format!("Bearer {token}"))
        .header("ChatGPT-Account-Id", acct)
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => r.json().await.unwrap_or(Value::Null),
        Ok(r) => {
            tracing::warn!(status = %r.status(), "cx_quota_http_non_success");
            Value::Null
        }
        Err(e) => {
            tracing::warn!(error = %e, "cx_quota_send_failed");
            Value::Null
        }
    }
}

// ── Gemini / Google ─────────────────────────────────────────────

async fn ensure_gm_token() -> Option<String> {
    let path = std::env::var("HOME")
        .map(|h| format!("{h}/.gemini/oauth_creds.json"))
        .unwrap_or_default();
    let body = tokio::fs::read_to_string(&path).await.ok()?;
    let mut creds: Value = serde_json::from_str(&body).ok()?;
    let token = creds.get("access_token").and_then(|v| v.as_str()).unwrap_or("").to_string();
    let expiry = creds.get("expiry_date").and_then(|v| v.as_i64()).unwrap_or(0);
    let now_ms = chrono::Utc::now().timestamp_millis();
    if expiry > now_ms + 300_000 {
        return Some(token);
    }
    let refresh = creds.get("refresh_token").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if refresh.is_empty() {
        return if token.is_empty() { None } else { Some(token) };
    }
    let client_id = std::env::var("AGENT_METRICS_GM_CLIENT_ID")
        .unwrap_or_else(|_| "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com".into());
    let client_secret = std::env::var("AGENT_METRICS_GM_CLIENT_SECRET")
        .unwrap_or_else(|_| "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".into());

    let client = http_client().ok()?;
    let params = [
        ("grant_type", "refresh_token"),
        ("refresh_token", refresh.as_str()),
        ("client_id", client_id.as_str()),
        ("client_secret", client_secret.as_str()),
    ];
    let resp = client
        .post("https://oauth2.googleapis.com/token")
        .form(&params)
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return if token.is_empty() { None } else { Some(token) };
    }
    let new: Value = resp.json().await.ok()?;
    let new_token = new.get("access_token").and_then(|v| v.as_str()).unwrap_or("").to_string();
    if !new_token.is_empty() {
        creds["access_token"] = Value::String(new_token.clone());
        let expires_in = new.get("expires_in").and_then(|v| v.as_i64()).unwrap_or(3600);
        creds["expiry_date"] = json!(now_ms + expires_in * 1000);
        let _ = tokio::fs::write(&path, serde_json::to_string(&creds).unwrap_or_default()).await;
        return Some(new_token);
    }
    if token.is_empty() {
        None
    } else {
        Some(token)
    }
}

async fn get_gm_project(client: &reqwest::Client, token: &str) -> String {
    {
        let state = GM_STATE.lock().unwrap();
        if let Some(p) = &state.project {
            if elapsed_since(state.project_ts) < Duration::from_secs(GM_PROJECT_TTL_S) {
                return p.clone();
            }
        }
    }
    let resp = client
        .post("https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist")
        .bearer_auth(token)
        .json(&json!({}))
        .send()
        .await;
    if let Ok(r) = resp {
        if r.status().is_success() {
            if let Ok(data) = r.json::<Value>().await {
                if let Some(pid) = data.get("cloudaicompanionProject").and_then(|v| v.as_str()) {
                    let mut state = GM_STATE.lock().unwrap();
                    state.project = Some(pid.into());
                    state.project_ts = Some(Instant::now());
                    return pid.to_string();
                }
            }
        }
    }
    GM_STATE.lock().unwrap().project.clone().unwrap_or_default()
}

async fn fetch_gm(client: &reqwest::Client) -> Value {
    let token = match ensure_gm_token().await {
        Some(t) => t,
        None => return Value::Null,
    };
    let project = get_gm_project(client, &token).await;
    if project.is_empty() {
        return Value::Null;
    }
    let resp = client
        .post("https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota")
        .bearer_auth(&token)
        .json(&json!({"project": format!("projects/{project}")}))
        .send()
        .await;
    match resp {
        Ok(r) if r.status().is_success() => r.json().await.unwrap_or(Value::Null),
        Ok(r) => {
            tracing::warn!(status = %r.status(), "gm_quota_http_non_success");
            Value::Null
        }
        Err(e) => {
            tracing::warn!(error = %e, "gm_quota_send_failed");
            Value::Null
        }
    }
}

// ── format_quota — ports Python `format_quota` byte-for-byte ────

fn parse_cc(data: &Value) -> serde_json::Map<String, Value> {
    let mut out = serde_json::Map::new();
    if let Some(fh) = data.get("five_hour") {
        let pct = fh.get("utilization").and_then(|v| v.as_f64()).unwrap_or(0.0);
        out.insert("5h".into(), Value::String(format!("{}%", round_pct(pct))));
        if let Some(ra) = fh.get("resets_at").and_then(|v| v.as_str()) {
            out.insert("5h_resets_at".into(), Value::String(ra.to_string()));
        }
    }
    if let Some(sd) = data.get("seven_day") {
        let pct = sd.get("utilization").and_then(|v| v.as_f64()).unwrap_or(0.0);
        out.insert("7d".into(), Value::String(format!("{}%", round_pct(pct))));
        if let Some(ra) = sd.get("resets_at").and_then(|v| v.as_str()) {
            out.insert("7d_resets_at".into(), Value::String(ra.to_string()));
        }
    }
    if let Some(ex) = data.get("extra_usage") {
        let enabled = ex.get("is_enabled").and_then(|v| v.as_bool()).unwrap_or(false);
        out.insert("ex_enabled".into(), Value::Bool(enabled));
        if enabled {
            let used = ex.get("used_credits").and_then(|v| v.as_f64()).unwrap_or(0.0) / 100.0;
            let limit = ex.get("monthly_limit").and_then(|v| v.as_f64()).unwrap_or(0.0) / 100.0;
            let util = ex.get("utilization").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let pct = round_pct(util);
            // API omits balance_cents when it can be derived; fall back to limit - used.
            let balance = match ex.get("balance_cents").and_then(|v| v.as_f64()) {
                Some(v) => v / 100.0,
                None => (limit - used).max(0.0),
            };
            let s = if balance <= 0.0 {
                "off".to_string()
            } else {
                format!("${:.2}/${:.0} {}% 余${:.2}", used, limit, pct, balance)
            };
            out.insert("ex".into(), Value::String(s));
            if let Some(n) = serde_json::Number::from_f64(used) { out.insert("ex_used_usd".into(), Value::Number(n)); }
            if let Some(n) = serde_json::Number::from_f64(limit) { out.insert("ex_limit_usd".into(), Value::Number(n)); }
            if let Some(n) = serde_json::Number::from_f64(balance) { out.insert("ex_balance_usd".into(), Value::Number(n)); }
            if let Some(n) = serde_json::Number::from_f64(util) { out.insert("ex_utilization".into(), Value::Number(n)); }
        } else {
            out.insert("ex".into(), Value::String("off".into()));
        }
    }
    out
}

fn parse_cx(data: &Value) -> serde_json::Map<String, Value> {
    let mut out = serde_json::Map::new();
    let rl = data.get("rate_limit").cloned().unwrap_or(Value::Null);
    if let Some(pw) = rl.get("primary_window") {
        let v = pw.get("used_percent").and_then(|x| x.as_i64()).unwrap_or(0);
        out.insert("5h".into(), Value::String(format!("{}%", v)));
        if let Some(iso) = unix_reset_to_iso(pw.get("reset_at")) {
            out.insert("5h_resets_at".into(), Value::String(iso));
        }
    }
    if let Some(sw) = rl.get("secondary_window") {
        let v = sw.get("used_percent").and_then(|x| x.as_i64()).unwrap_or(0);
        out.insert("7d".into(), Value::String(format!("{}%", v)));
        if let Some(iso) = unix_reset_to_iso(sw.get("reset_at")) {
            out.insert("7d_resets_at".into(), Value::String(iso));
        }
    }
    out
}

fn unix_reset_to_iso(v: Option<&Value>) -> Option<String> {
    let ts = v.and_then(|x| x.as_i64()).or_else(|| v.and_then(|x| x.as_f64()).map(|f| f as i64))?;
    if ts <= 0 { return None; }
    chrono::DateTime::from_timestamp(ts, 0).map(|dt| dt.to_rfc3339())
}

fn parse_gm(data: &Value) -> serde_json::Map<String, Value> {
    let mut out = serde_json::Map::new();
    let buckets = data.get("buckets").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let mut earliest_reset: Option<String> = None;
    for bucket in buckets {
        if bucket.get("tokenType").and_then(|v| v.as_str()) != Some("REQUESTS") {
            continue;
        }
        let model = bucket.get("modelId").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let frac = bucket.get("remainingFraction").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let used_pct = round_pct((1.0 - frac) * 100.0);
        let val = format!("{}%", used_pct);
        if let Some(rt) = bucket.get("resetTime").and_then(|v| v.as_str()) {
            if earliest_reset.as_ref().map_or(true, |e| rt < e.as_str()) {
                earliest_reset = Some(rt.to_string());
            }
        }
        if model.contains("pro") && !model.ends_with("_vertex") {
            out.insert("pro".into(), Value::String(val.clone()));
        }
        if model.contains("flash") && !model.contains("lite") && !model.ends_with("_vertex") {
            let prev = out.get("flash").and_then(|v| v.as_str()).map(|s| {
                s.trim_end_matches('%').parse::<i64>().unwrap_or(0)
            });
            if prev.map_or(true, |p| used_pct > p) {
                out.insert("flash".into(), Value::String(val));
            }
        }
    }
    if let Some(rt) = earliest_reset {
        out.insert("daily_resets_at".into(), Value::String(rt));
    }
    out
}

fn format_quota(cc: &Value, cx: &Value, gm: &Value) -> Value {
    let cc_p = parse_cc(cc);
    let cx_p = parse_cx(cx);
    let gm_p = parse_gm(gm);
    let mut parts = Vec::new();
    if !cc_p.is_empty() {
        let f5 = cc_p.get("5h").and_then(|v| v.as_str()).unwrap_or("?");
        let f7 = cc_p.get("7d").and_then(|v| v.as_str()).unwrap_or("?");
        parts.push(format!("CC:{}/{}", f5, f7));
    }
    if !cx_p.is_empty() {
        let f5 = cx_p.get("5h").and_then(|v| v.as_str()).unwrap_or("?");
        let f7 = cx_p.get("7d").and_then(|v| v.as_str()).unwrap_or("?");
        parts.push(format!("CX:{}/{}", f5, f7));
    }
    if !gm_p.is_empty() {
        let pro = gm_p.get("pro").and_then(|v| v.as_str()).unwrap_or("?");
        parts.push(format!("GM:{}", pro));
    }
    let display = if parts.is_empty() { "?".into() } else { parts.join(" ") };
    json!({
        "llm_cc_5h": cc_p.get("5h").cloned().unwrap_or(Value::String("?".into())),
        "llm_cc_7d": cc_p.get("7d").cloned().unwrap_or(Value::String("?".into())),
        "llm_cc_ex": cc_p.get("ex").cloned().unwrap_or(Value::String("?".into())),
        "llm_cx_5h": cx_p.get("5h").cloned().unwrap_or(Value::String("?".into())),
        "llm_cx_7d": cx_p.get("7d").cloned().unwrap_or(Value::String("?".into())),
        "llm_gm_pro": gm_p.get("pro").cloned().unwrap_or(Value::String("?".into())),
        "llm_gm_flash": gm_p.get("flash").cloned().unwrap_or(Value::String("?".into())),
        "llm_display": display,
        "llm_cc_5h_resets_at": cc_p.get("5h_resets_at").cloned().unwrap_or(Value::Null),
        "llm_cc_7d_resets_at": cc_p.get("7d_resets_at").cloned().unwrap_or(Value::Null),
        "llm_cx_5h_resets_at": cx_p.get("5h_resets_at").cloned().unwrap_or(Value::Null),
        "llm_cx_7d_resets_at": cx_p.get("7d_resets_at").cloned().unwrap_or(Value::Null),
        "llm_gm_daily_resets_at": gm_p.get("daily_resets_at").cloned().unwrap_or(Value::Null),
        "llm_cc_ex_enabled": cc_p.get("ex_enabled").cloned().unwrap_or(Value::Null),
        "llm_cc_ex_used_usd": cc_p.get("ex_used_usd").cloned().unwrap_or(Value::Null),
        "llm_cc_ex_limit_usd": cc_p.get("ex_limit_usd").cloned().unwrap_or(Value::Null),
        "llm_cc_ex_balance_usd": cc_p.get("ex_balance_usd").cloned().unwrap_or(Value::Null),
        "llm_cc_ex_utilization": cc_p.get("ex_utilization").cloned().unwrap_or(Value::Null),
        "cc_parsed": cc_p,
        "cx_parsed": cx_p,
        "gm_parsed": gm_p,
    })
}

// ── Public driver ───────────────────────────────────────────────

/// Debug helper: bypass cache + Redis writes, return raw bundles.
pub async fn raw_dump(_cfg: &Settings) -> (Value, Value, Value) {
    let client = match http_client() {
        Ok(c) => c,
        Err(_) => return (Value::Null, Value::Null, Value::Null),
    };
    tokio::join!(fetch_cc(&client), fetch_cx(&client), fetch_gm(&client))
}

pub async fn refresh_once(cfg: &Settings) -> Result<Value> {
    let client = http_client()?;
    // Run all 3 fetches concurrently
    let (cc, cx, gm) = tokio::join!(fetch_cc(&client), fetch_cx(&client), fetch_gm(&client));
    let formatted = format_quota(&cc, &cx, &gm);
    let raw = json!({"cc": cc, "cx": cx, "gm": gm});

    if let Some(mut conn) = open_redis(cfg).await {
        let _: Result<(), _> = conn
            .set_ex::<_, _, ()>(RKEY_FORMATTED, formatted.to_string(), QUOTA_CACHE_TTL_S)
            .await;
        let _: Result<(), _> = conn
            .set_ex::<_, _, ()>(RKEY_RAW, raw.to_string(), QUOTA_CACHE_TTL_S)
            .await;
        let _: Result<(), _> = conn
            .set_ex::<_, _, ()>(RKEY_CC_RAW, cc.to_string(), CC_QUOTA_FETCH_INTERVAL_S)
            .await;
    }

    Ok(formatted)
}

pub async fn run_quota_loop(cfg: Settings, interval_s: u64) -> Result<()> {
    let interval = Duration::from_secs(interval_s.max(10));
    tracing::info!(interval_s, "quota_loop_started");
    loop {
        let started = Utc::now();
        match refresh_once(&cfg).await {
            Ok(formatted) => tracing::info!(
                started = %started.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, false),
                display = %formatted.get("llm_display").and_then(|v| v.as_str()).unwrap_or("?"),
                "quota_refreshed"
            ),
            Err(e) => tracing::warn!(error = %e, "quota_refresh_failed"),
        }
        tokio::time::sleep(interval).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_cc_full() {
        let raw = json!({
            "five_hour": {"utilization": 18.0},
            "seven_day": {"utilization": 34.0},
            "extra_usage": {"is_enabled": true, "used_credits": 250, "monthly_limit": 5000, "utilization": 5, "balance_cents": 4750}
        });
        let p = parse_cc(&raw);
        assert_eq!(p.get("5h").and_then(|v| v.as_str()), Some("18%"));
        assert_eq!(p.get("7d").and_then(|v| v.as_str()), Some("34%"));
        // 250/100=2.5, 5000/100=50, balance 4750/100=47.5
        let ex = p.get("ex").and_then(|v| v.as_str()).unwrap();
        assert!(ex.contains("$2.50"), "ex={ex}");
        assert!(ex.contains("$50"), "ex={ex}");
    }

    #[test]
    fn parse_cc_extra_off_when_balance_zero() {
        let raw = json!({"extra_usage": {"is_enabled": true, "balance_cents": 0}});
        let p = parse_cc(&raw);
        assert_eq!(p.get("ex").and_then(|v| v.as_str()), Some("off"));
    }

    #[test]
    fn parse_cx_uses_used_percent() {
        let raw = json!({"rate_limit": {"primary_window": {"used_percent": 21}, "secondary_window": {"used_percent": 12}}});
        let p = parse_cx(&raw);
        assert_eq!(p.get("5h").and_then(|v| v.as_str()), Some("21%"));
        assert_eq!(p.get("7d").and_then(|v| v.as_str()), Some("12%"));
    }

    #[test]
    fn parse_gm_skips_lite_and_vertex() {
        let raw = json!({"buckets": [
            {"tokenType": "REQUESTS", "modelId": "gemini-2.5-pro",        "remainingFraction": 1.0},
            {"tokenType": "REQUESTS", "modelId": "gemini-2.5-flash",      "remainingFraction": 0.85},
            {"tokenType": "REQUESTS", "modelId": "gemini-2.5-flash-lite", "remainingFraction": 0.0},
            {"tokenType": "REQUESTS", "modelId": "gemini-2.5-pro_vertex", "remainingFraction": 0.0},
        ]});
        let p = parse_gm(&raw);
        assert_eq!(p.get("pro").and_then(|v| v.as_str()), Some("0%"));
        assert_eq!(p.get("flash").and_then(|v| v.as_str()), Some("15%"));
    }

    #[test]
    fn format_quota_display_combines_all_three() {
        let cc = json!({"five_hour": {"utilization": 18}, "seven_day": {"utilization": 34}});
        let cx = json!({"rate_limit": {"primary_window": {"used_percent": 21}, "secondary_window": {"used_percent": 12}}});
        let gm = json!({"buckets": [{"tokenType": "REQUESTS", "modelId": "gemini-2.5-pro", "remainingFraction": 1.0}]});
        let f = format_quota(&cc, &cx, &gm);
        assert_eq!(f.get("llm_display").and_then(|v| v.as_str()), Some("CC:18%/34% CX:21%/12% GM:0%"));
    }
}
