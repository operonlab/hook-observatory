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
    // Reserved for local-only HTTP (Redis is via redis crate, LiteLLM via
    // litellm.rs). Quota fetches go through `curl` (see `curl_get/_post`)
    // because LuLu firewall blocks unsigned new agent-metrics-rs binaries
    // from arbitrary outbound HTTPS, while `curl` is permanently approved.
    reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .context("build reqwest client")
}

/// Shell out to system `curl` for HTTPS GET — bypasses LuLu binary signing
/// per-build prompts. Returns parsed JSON body or Value::Null on any error.
async fn curl_get(url: &str, headers: &[(&str, &str)]) -> Value {
    let mut cmd = Command::new("curl");
    cmd.arg("-sSf").arg("--max-time").arg("15");
    for (k, v) in headers {
        cmd.arg("-H").arg(format!("{k}: {v}"));
    }
    cmd.arg(url);
    let out = match cmd.output().await {
        Ok(o) => o,
        Err(e) => {
            tracing::warn!(url, error = %e, "curl_get_spawn_failed");
            return Value::Null;
        }
    };
    if !out.status.success() {
        tracing::warn!(
            url,
            rc = ?out.status.code(),
            stderr = %String::from_utf8_lossy(&out.stderr),
            "curl_get_failed"
        );
        return Value::Null;
    }
    serde_json::from_slice(&out.stdout).unwrap_or(Value::Null)
}

/// Shell out to system `curl` for HTTPS POST with JSON body.
async fn curl_post_json(url: &str, headers: &[(&str, &str)], body: &Value) -> Value {
    let body_str = body.to_string();
    let mut cmd = Command::new("curl");
    cmd.arg("-sSf").arg("--max-time").arg("15").arg("-X").arg("POST");
    cmd.arg("-H").arg("Content-Type: application/json");
    for (k, v) in headers {
        cmd.arg("-H").arg(format!("{k}: {v}"));
    }
    cmd.arg("-d").arg(body_str).arg(url);
    let out = match cmd.output().await {
        Ok(o) => o,
        Err(e) => {
            tracing::warn!(url, error = %e, "curl_post_spawn_failed");
            return Value::Null;
        }
    };
    if !out.status.success() {
        tracing::warn!(
            url,
            rc = ?out.status.code(),
            stderr = %String::from_utf8_lossy(&out.stderr),
            "curl_post_failed"
        );
        return Value::Null;
    }
    serde_json::from_slice(&out.stdout).unwrap_or(Value::Null)
}

async fn open_redis(cfg: &Settings) -> Option<redis::aio::ConnectionManager> {
    let c = redis::Client::open(cfg.redis_url.clone()).ok()?;
    redis::aio::ConnectionManager::new(c).await.ok()
}

// ── Anthropic / Claude Code ─────────────────────────────────────

async fn read_cc_token() -> Option<String> {
    let out = match Command::new("security")
        .args(["find-generic-password", "-s", "Claude Code-credentials", "-w"])
        .output()
        .await
    {
        Ok(o) => o,
        Err(e) => {
            tracing::debug!(error = %e, "cc_security_spawn_failed");
            return None;
        }
    };
    if !out.status.success() {
        tracing::debug!(rc = ?out.status.code(), stderr = %String::from_utf8_lossy(&out.stderr), "cc_security_nonzero");
        return None;
    }
    let raw = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let creds: Value = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            tracing::debug!(error = %e, raw_prefix = %&raw.chars().take(60).collect::<String>(), "cc_security_json_parse_failed");
            return None;
        }
    };
    let token = creds
        .get("claudeAiOauth")
        .and_then(|v| v.get("accessToken"))
        .and_then(|v| v.as_str())
        .map(String::from);
    if token.is_none() {
        tracing::debug!(top_keys = ?creds.as_object().map(|m| m.keys().collect::<Vec<_>>()), "cc_no_access_token_in_creds");
    }
    token
}

async fn fetch_cc(_client: &reqwest::Client) -> Value {
    {
        let state = CC_STATE.lock().unwrap();
        if let Some(b) = state.backoff_until {
            if Instant::now() < b {
                if let Some(last) = &state.last_success {
                    return last.clone();
                }
                return Value::Null;
            }
        }
    }

    let token = match read_cc_token().await {
        Some(t) => t,
        None => return Value::Null,
    };

    let auth = format!("Bearer {token}");
    let data = curl_get(
        "https://api.anthropic.com/api/oauth/usage",
        &[("Authorization", &auth), ("anthropic-beta", "oauth-2025-04-20")],
    )
    .await;

    if data == Value::Null {
        let mut state = CC_STATE.lock().unwrap();
        state.last_fetch_mode = "error_fallback".into();
        return state.last_success.clone().unwrap_or(Value::Null);
    }

    let mut state = CC_STATE.lock().unwrap();
    state.last_success = Some(data.clone());
    state.last_success_ts = Some(Instant::now());
    state.backoff_until = None;
    state.consecutive_failures = 0;
    state.last_fetch_mode = "live".into();
    data
}

// ── Codex / ChatGPT ─────────────────────────────────────────────

async fn fetch_cx(_client: &reqwest::Client) -> Value {
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
    let bearer = format!("Bearer {token}");
    curl_get(
        "https://chatgpt.com/backend-api/wham/usage",
        &[("Authorization", &bearer), ("ChatGPT-Account-Id", &acct)],
    )
    .await
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

    // Shell out to curl with form-encoded body — same LuLu story as fetch_cx.
    let body = format!(
        "grant_type=refresh_token&refresh_token={}&client_id={}&client_secret={}",
        urlencoding(&refresh),
        urlencoding(&client_id),
        urlencoding(&client_secret),
    );
    let out = match Command::new("curl")
        .args(["-sSf", "--max-time", "10", "-X", "POST"])
        .arg("-H").arg("Content-Type: application/x-www-form-urlencoded")
        .arg("-d").arg(&body)
        .arg("https://oauth2.googleapis.com/token")
        .output()
        .await
    {
        Ok(o) if o.status.success() => o,
        _ => return if token.is_empty() { None } else { Some(token) },
    };
    let new: Value = serde_json::from_slice(&out.stdout).ok()?;
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

async fn get_gm_project(_client: &reqwest::Client, token: &str) -> String {
    {
        let state = GM_STATE.lock().unwrap();
        if let Some(p) = &state.project {
            if elapsed_since(state.project_ts) < Duration::from_secs(GM_PROJECT_TTL_S) {
                return p.clone();
            }
        }
    }
    let bearer = format!("Bearer {token}");
    let data = curl_post_json(
        "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
        &[("Authorization", &bearer)],
        &json!({}),
    )
    .await;
    if let Some(pid) = data.get("cloudaicompanionProject").and_then(|v| v.as_str()) {
        let mut state = GM_STATE.lock().unwrap();
        state.project = Some(pid.into());
        state.project_ts = Some(Instant::now());
        return pid.to_string();
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
    let bearer = format!("Bearer {token}");
    curl_post_json(
        "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota",
        &[("Authorization", &bearer)],
        &json!({"project": format!("projects/{project}")}),
    )
    .await
}

fn urlencoding(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}

// ── format_quota — ports Python `format_quota` byte-for-byte ────

fn parse_cc(data: &Value) -> serde_json::Map<String, Value> {
    let mut out = serde_json::Map::new();
    if let Some(fh) = data.get("five_hour") {
        let pct = fh.get("utilization").and_then(|v| v.as_f64()).unwrap_or(0.0);
        out.insert("5h".into(), Value::String(format!("{}%", round_pct(pct))));
    }
    if let Some(sd) = data.get("seven_day") {
        let pct = sd.get("utilization").and_then(|v| v.as_f64()).unwrap_or(0.0);
        out.insert("7d".into(), Value::String(format!("{}%", round_pct(pct))));
    }
    if let Some(ex) = data.get("extra_usage") {
        if ex.get("is_enabled").and_then(|v| v.as_bool()).unwrap_or(false) {
            let used = ex.get("used_credits").and_then(|v| v.as_f64()).unwrap_or(0.0) / 100.0;
            let limit = ex.get("monthly_limit").and_then(|v| v.as_f64()).unwrap_or(0.0) / 100.0;
            let pct = round_pct(ex.get("utilization").and_then(|v| v.as_f64()).unwrap_or(0.0));
            let balance = ex.get("balance_cents").and_then(|v| v.as_f64()).unwrap_or(0.0) / 100.0;
            let s = if balance <= 0.0 {
                "off".to_string()
            } else {
                format!("${:.2}/${:.0} {}% 余${:.2}", used, limit, pct, balance)
            };
            out.insert("ex".into(), Value::String(s));
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
    }
    if let Some(sw) = rl.get("secondary_window") {
        let v = sw.get("used_percent").and_then(|x| x.as_i64()).unwrap_or(0);
        out.insert("7d".into(), Value::String(format!("{}%", v)));
    }
    out
}

fn parse_gm(data: &Value) -> serde_json::Map<String, Value> {
    let mut out = serde_json::Map::new();
    let buckets = data.get("buckets").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    for bucket in buckets {
        if bucket.get("tokenType").and_then(|v| v.as_str()) != Some("REQUESTS") {
            continue;
        }
        let model = bucket.get("modelId").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let frac = bucket.get("remainingFraction").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let used_pct = round_pct((1.0 - frac) * 100.0);
        let val = format!("{}%", used_pct);
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
