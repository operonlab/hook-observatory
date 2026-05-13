//! Browser automation — CamoufoxSession (primary) + PlaywrightSession stub.
//!
//! Mirrors Python `pw.py`:
//!   - BrowserSession trait = abstract base class
//!   - CamoufoxSession  = camoufox-cli subprocess wrapper
//!   - PlaywrightSession = TODO (Playwright CLI fallback, Phase follow-up)

use crate::config::Settings;
use anyhow::{bail, Result};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Mutex;
use tokio::process::Command;
use uuid::Uuid;

// ── Trait ────────────────────────────────────────────────────────────────────

/// Unified browser session interface. All methods correspond 1-to-1 with
/// the Python `BrowserSession` abstract class in `pw.py`.
#[async_trait::async_trait]
pub trait BrowserSession: Send + Sync {
    fn backend(&self) -> &str;
    async fn open(&self, url: &str) -> Result<String>;
    async fn navigate(&self, url: &str) -> Result<String>;
    async fn run_code(&self, js: &str, timeout_secs: u64) -> Result<String>;
    async fn snapshot(&self, interactive: bool) -> Result<String>;
    async fn click(&self, ref_id: &str) -> Result<String>;
    async fn fill(&self, ref_id: &str, text: &str) -> Result<String>;
    async fn screenshot(&self, full_page: bool) -> Result<Vec<u8>>;
    async fn close(&self) -> Result<String>;
}

// ── CamoufoxSession ──────────────────────────────────────────────────────────

/// Primary browser backend — delegates every action to `camoufox-cli` subprocess.
/// Session ID matches Python pattern: `uuid.uuid4().hex[:8]`
pub struct CamoufoxSession {
    pub sid: String,
    pub cfg: Settings,
    /// Cloned profile directory for this session. Populated lazily on first
    /// `open()` and removed on `close()` so parallel / back-to-back survey
    /// runs never compete for the shared master profile lock.
    cloned_profile: Mutex<Option<PathBuf>>,
}

impl CamoufoxSession {
    /// Create a new session with a random 8-hex SID.
    pub fn new(cfg: Settings) -> Self {
        let sid = Uuid::new_v4().simple().to_string()[..8].to_string();
        Self {
            sid,
            cfg,
            cloned_profile: Mutex::new(None),
        }
    }

    /// Create with explicit session id (for tests / resumption).
    pub fn with_sid(sid: impl Into<String>, cfg: Settings) -> Self {
        Self {
            sid: sid.into(),
            cfg,
            cloned_profile: Mutex::new(None),
        }
    }

    fn expand_home(raw: &str) -> PathBuf {
        if let Some(stripped) = raw.strip_prefix("~/") {
            let home = std::env::var("HOME").unwrap_or_else(|_| String::from("/"));
            PathBuf::from(home).join(stripped)
        } else if raw == "~" {
            PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| String::from("/")))
        } else {
            PathBuf::from(raw)
        }
    }

    /// Clone the master profile into a fresh tmpdir (idempotent). Returns the
    /// clone path. Uses `cp -Rp` so symlinks/permissions are preserved and
    /// removes any stale Firefox lock files inside the clone.
    async fn ensure_cloned_profile(&self) -> Result<PathBuf> {
        if let Some(p) = self.cloned_profile.lock().unwrap().clone() {
            if p.exists() {
                return Ok(p);
            }
        }

        let source = Self::expand_home(&self.cfg.camoufox_profile);
        if !source.exists() {
            bail!("camoufox profile not found: {}", source.display());
        }

        let target = std::env::temp_dir().join(format!("camoufox-{}", self.sid));
        // If a previous run left something behind, wipe it before cloning.
        if target.exists() {
            let _ = tokio::fs::remove_dir_all(&target).await;
        }

        let status = Command::new("cp")
            .arg("-Rp")
            .arg(&source)
            .arg(&target)
            .status()
            .await?;
        if !status.success() {
            bail!("cp -Rp failed cloning {} -> {}", source.display(), target.display());
        }

        // Strip Firefox lock files so the clone starts unlocked even if the
        // source was in use at clone time.
        for name in [".parentlock", "lock", "parent.lock"] {
            let _ = tokio::fs::remove_file(target.join(name)).await;
        }

        *self.cloned_profile.lock().unwrap() = Some(target.clone());
        tracing::debug!(sid = %self.sid, clone = %target.display(), "camoufox profile cloned");
        Ok(target)
    }

    /// Remove the cloned profile directory. Safe to call multiple times.
    async fn discard_cloned_profile(&self) {
        let maybe = self.cloned_profile.lock().unwrap().take();
        if let Some(path) = maybe {
            if let Err(e) = tokio::fs::remove_dir_all(&path).await {
                tracing::debug!(
                    sid = %self.sid,
                    path = %path.display(),
                    error = %e,
                    "cleanup of cloned profile failed"
                );
            }
        }
    }

    /// Low-level subprocess runner — mirrors `CamoufoxSession._run()`.
    async fn run_cmd(&self, extra_args: &[&str], timeout_secs: u64) -> Result<String> {
        let mut cmd = Command::new(&self.cfg.camoufox_cli);
        cmd.args(["--session", &self.sid]);
        for a in extra_args {
            cmd.arg(a);
        }
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        let child = cmd.spawn()?;
        let output = tokio::time::timeout(
            std::time::Duration::from_secs(timeout_secs),
            child.wait_with_output(),
        )
        .await
        .map_err(|_| anyhow::anyhow!("camoufox-cli timeout after {}s", timeout_secs))??;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stdout = String::from_utf8_lossy(&output.stdout);
            let msg = if !stderr.is_empty() { &stderr } else { &stdout };
            bail!("camoufox-cli error: {}", msg);
        }
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    }
}

impl Drop for CamoufoxSession {
    fn drop(&mut self) {
        // Safety net for paths that never reach close() (e.g. `?` early-exit
        // in the orchestrator). std::fs is sync but acceptable in Drop.
        let path: Option<PathBuf> = self.cloned_profile.lock().unwrap().take();
        if let Some(p) = path {
            let _ = std::fs::remove_dir_all(&p);
        }
    }
}

#[async_trait::async_trait]
impl BrowserSession for CamoufoxSession {
    fn backend(&self) -> &str {
        "camoufox"
    }

    /// Open URL with persistent profile. Mirrors `open()` in Python (with 2s sleep).
    ///
    /// The master profile is cloned into `/tmp/camoufox-<sid>/` on first open
    /// so concurrent or back-to-back runs never collide on the Firefox
    /// parent-lock. The clone is discarded in `close()`.
    async fn open(&self, url: &str) -> Result<String> {
        let profile = self.ensure_cloned_profile().await?;
        let profile_str = profile.to_string_lossy().into_owned();
        let result = self
            .run_cmd(&["--persistent", &profile_str, "open", url], 30)
            .await?;
        // Python does time.sleep(2) here; we use tokio::time::sleep
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        Ok(result)
    }

    /// Navigate to URL in same session (no persistent flag needed).
    async fn navigate(&self, url: &str) -> Result<String> {
        let result = self.run_cmd(&["open", url], 30).await?;
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        Ok(result)
    }

    /// Eval JS directly in page context (camoufox runs without `page.` prefix).
    async fn run_code(&self, js: &str, timeout_secs: u64) -> Result<String> {
        self.run_cmd(&["eval", js], timeout_secs).await
    }

    /// Snapshot the current page. `-i` = interactive elements only.
    async fn snapshot(&self, interactive: bool) -> Result<String> {
        let args: &[&str] = if interactive {
            &["snapshot", "-i"]
        } else {
            &["snapshot"]
        };
        self.run_cmd(args, 15).await
    }

    /// Click an element by ref id (`@elN` format).
    async fn click(&self, ref_id: &str) -> Result<String> {
        let ref_str = ensure_at_prefix(ref_id);
        self.run_cmd(&["click", &ref_str], 15).await
    }

    /// Fill an element by ref id.
    async fn fill(&self, ref_id: &str, text: &str) -> Result<String> {
        let ref_str = ensure_at_prefix(ref_id);
        self.run_cmd(&["fill", &ref_str, text], 15).await
    }

    /// Screenshot. Returns raw bytes.
    /// Note: Python returns `str` (stdout), but we return bytes for richer handling.
    /// Callers that only need stdout can call `screenshot_str`.
    async fn screenshot(&self, full_page: bool) -> Result<Vec<u8>> {
        let args: &[&str] = if full_page {
            &["screenshot", "--full"]
        } else {
            &["screenshot"]
        };
        let out = self.run_cmd(args, 15).await?;
        Ok(out.into_bytes())
    }

    /// Close the session — mirrors Python `close()` (swallows errors).
    async fn close(&self) -> Result<String> {
        let out = match self.run_cmd(&["close"], 10).await {
            Ok(out) => out,
            Err(_) => String::new(), // Python: except Exception: return ""
        };
        self.discard_cloned_profile().await;
        Ok(out)
    }
}

// ── PlaywrightSession stub ───────────────────────────────────────────────────

/// Playwright CLI fallback — NOT YET IMPLEMENTED.
///
/// TODO (Phase follow-up):
///   - Implement `_run()` with `playwright-cli --profile $PW_PROFILE -s=<sid>-001`
///   - JS must be in `async (page) => { ... }` format (differs from camoufox)
///   - `open()` uses plain `open <url>` (no --persistent flag)
///   - `screenshot()` flag is `--full-page` (not `--full`)
///   - Result text may be prefixed with `### Result\n` — strip before returning
#[allow(dead_code)]
pub struct PlaywrightSession {
    pub sid: String,
    pub cfg: Settings,
    pub profile_dir: Option<String>,
}

#[allow(dead_code)]
impl PlaywrightSession {
    pub fn new(cfg: Settings) -> Self {
        let sid = Uuid::new_v4().simple().to_string()[..8].to_string();
        Self {
            sid,
            cfg,
            profile_dir: None,
        }
    }
}

// ── JS Conversion Utilities ──────────────────────────────────────────────────

/// Ensure ref_id starts with '@'. Mirrors Python `ref if ref.startswith("@") else f"@{ref}"`.
fn ensure_at_prefix(r: &str) -> String {
    if r.starts_with('@') {
        r.to_owned()
    } else {
        format!("@{r}")
    }
}

/// Convert Playwright-style `async (page) => { ... }` JS into Camoufox page-context
/// IIFE with DOM helpers.
///
/// This is a **best-effort** translation of `pw.py::to_camoufox_js()`.
/// The JS wrapper (wait, clickEl, fillEl, etc.) is reproduced verbatim.
pub fn to_camoufox_js(script: &str) -> String {
    // Strip `async (page) => { ... }` wrapper if present
    let stripped = script.trim();
    let inner = if let Some(inner_raw) = strip_pw_wrapper(stripped) {
        inner_raw
    } else {
        stripped.to_owned()
    };

    // Apply regex transformations matching Python's to_camoufox_js
    let inner = apply_pw_to_camoufox_transforms(&inner);

    // Wrap with helpers (identical to Python version)
    format!(
        r#"(async () => {{
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  const clickEl = (selector) => {{
    // Handle Playwright text= selector
    if (selector.startsWith('text=')) {{
      const text = selector.slice(5);
      const allEls = document.querySelectorAll('button, [role="button"], a, input[type="submit"], span, div');
      let fallback = null;
      for (const el of allEls) {{
        if (el.textContent.trim().includes(text) && el.offsetParent !== null) {{
          if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.type === 'submit') {{
            el.click(); return true;
          }}
          if (!fallback) fallback = el;
        }}
      }}
      if (fallback) {{ fallback.click(); return true; }}
      return false;
    }}
    const el = document.querySelector(selector);
    if (el) {{ el.click(); return true; }}
    return false;
  }};

  const _nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const _nativeSetTA = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  const _reactFill = (el, text) => {{
    const setter = el.tagName === 'TEXTAREA' ? _nativeSetTA : _nativeSet;
    el.focus();
    setter.call(el, '');
    el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'deleteContentBackward' }}));
    setter.call(el, text);
    el.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: text, inputType: 'insertText' }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    el.blur();
  }};

  const fillEl = (selector, text) => {{
    const el = document.querySelector(selector);
    if (el) {{ _reactFill(el, text); return true; }}
    return false;
  }};

  const fillElDirect = (el, text) => {{
    if (el) {{ _reactFill(el, text); return true; }}
    return false;
  }};

  const queryEl = (selector) => {{
    if (selector.startsWith('text=')) {{
      const text = selector.slice(5);
      const allEls = document.querySelectorAll('button, [role="button"], a');
      for (const el of allEls) {{
        if (el.textContent.trim().includes(text) && el.offsetParent !== null) {{
          return el;
        }}
      }}
      return null;
    }}
    return document.querySelector(selector);
  }};

  const countEl = (selector) => document.querySelectorAll(selector).length;

  const isVisible = (selector) => {{
    const el = document.querySelector(selector);
    return el && el.offsetParent !== null;
  }};

  const getNth = (selector, n) => document.querySelectorAll(selector)[n];

  const waitForFn = async (fn, arg, opts) => {{
    const timeout = opts?.timeout || 30000;
    const start = Date.now();
    while (Date.now() - start < timeout) {{
      if (fn(arg)) return true;
      await wait(100);
    }}
    return false;
  }};

{inner}
}})()
"#
    )
}

/// Strip `async (page) => { ... }` wrapper, returning the body.
fn strip_pw_wrapper(s: &str) -> Option<String> {
    // Match `async (page) => {`
    let re = regex::Regex::new(r"^async\s*\(page\)\s*=>\s*\{").unwrap();
    if !re.is_match(s) {
        return None;
    }
    let inner = re.replace(s, "").to_string();
    // Remove trailing `}`
    let inner = inner.trim_end();
    if inner.ends_with('}') {
        Some(inner[..inner.len() - 1].to_string())
    } else {
        Some(inner.to_string())
    }
}

/// Apply the regex substitutions from Python `to_camoufox_js`.
fn apply_pw_to_camoufox_transforms(inner: &str) -> String {
    use regex::Regex;

    let mut s = inner.to_string();

    // page.waitForTimeout(ms) → await wait(ms)
    let re = Regex::new(r"await\s+page\.waitForTimeout\((\d+)\)").unwrap();
    s = re.replace_all(&s, "await wait($1)").into_owned();
    let re = Regex::new(r"await\s+page\.waitForTimeout\((\w+)\)").unwrap();
    s = re.replace_all(&s, "await wait($1)").into_owned();

    // page.url() → window.location.href
    s = s.replace("page.url()", "window.location.href");

    // Multi-line `await page.evaluate(() => { ...body... })` → `(() => {body})()`
    // We're already inside a page context in camoufox-cli, so the wrapping
    // promise indirection just has to disappear. Handle multi-line first so
    // the single-line rule below doesn't accidentally match on `}` char.
    // NOTE: require a newline before the closing `})` so that a `})` literal
    // appearing inside a string (e.g. an LLM-generated answer containing
    // "V(S_{t+1})") is not misinterpreted as the end of the evaluate body.
    let re_eval_multi =
        Regex::new(r"await\s+page\.evaluate\(\(\)\s*=>\s*\{([\s\S]*?)\n\s*\}\s*\)").unwrap();
    s = re_eval_multi
        .replace_all(&s, "(() => {$1})()")
        .into_owned();
    // Single-line `await page.evaluate(() => expr)` → `expr`
    let re_eval_single =
        Regex::new(r"await\s+page\.evaluate\(\(\)\s*=>\s*([^;\n]+)\)").unwrap();
    s = re_eval_single.replace_all(&s, "$1").into_owned();

    // page.locator(sel).first().click() → clickEl(sel)
    let re = Regex::new(r"await\s+page\.locator\(([^)]+)\)\.first\(\)\.click\(\)").unwrap();
    s = re.replace_all(&s, "await clickEl($1)").into_owned();
    // page.locator(sel).click() → clickEl(sel)
    let re = Regex::new(r"await\s+page\.locator\(([^)]+)\)\.click\(\)").unwrap();
    s = re.replace_all(&s, "await clickEl($1)").into_owned();

    // page.locator(sel).fill(text) → fillEl(sel, text)
    let re = Regex::new(r"await\s+page\.locator\(([^)]+)\)\.fill\(([^)]+)\)").unwrap();
    s = re.replace_all(&s, "await fillEl($1, $2)").into_owned();

    // const x = page.locator(sel).first() → const x = queryEl(sel)
    let re = Regex::new(r"(const|let|var)\s+(\w+)\s*=\s*page\.locator\(([^)]+)\)\.first\(\)")
        .unwrap();
    s = re.replace_all(&s, "$1 $2 = queryEl($3)").into_owned();
    let re =
        Regex::new(r"(const|let|var)\s+(\w+)\s*=\s*page\.locator\(([^)]+)\)").unwrap();
    s = re.replace_all(&s, "$1 $2 = queryEl($3)").into_owned();

    // await x.count() → (x ? 1 : 0)
    let re = Regex::new(r"await\s+(\w+)\.count\(\)").unwrap();
    s = re.replace_all(&s, "($1 ? 1 : 0)").into_owned();

    // await x.fill(text) → await fillElDirect(x, text)
    let re = Regex::new(r"await\s+(\w+)\.fill\(([^)]+)\)").unwrap();
    s = re.replace_all(&s, "await fillElDirect($1, $2)").into_owned();

    // await x.isVisible() → (x && x.offsetParent !== null)
    let re = Regex::new(r"await\s+(\w+)\.isVisible\(\)").unwrap();
    s = re
        .replace_all(&s, "($1 && $1.offsetParent !== null)")
        .into_owned();

    // await x.click() → x.click()
    let re = Regex::new(r"await\s+(\w+)\.click\(\)").unwrap();
    s = re.replace_all(&s, "$1.click()").into_owned();

    // page.locator(sel).nth(i) → getNth(sel, i)
    let re = Regex::new(r"page\.locator\(([^)]+)\)\.nth\(([^)]+)\)").unwrap();
    s = re.replace_all(&s, "getNth($1, $2)").into_owned();

    // page.waitForLoadState(...) → wait(3000)
    let re = Regex::new(r"await\s+page\.waitForLoadState\([^)]*\)").unwrap();
    s = re.replace_all(&s, "await wait(3000)").into_owned();

    // page.waitForFunction(fn, arg, opts) → waitForFn(fn, arg, opts)
    let re = Regex::new(r"await\s+page\.waitForFunction\(\s*([^,]+),\s*([^,]*),?\s*(\{[^}]*\})?\s*\)").unwrap();
    s = re.replace_all(&s, "await waitForFn($1, $2, $3)").into_owned();

    s
}

// ── Factory ──────────────────────────────────────────────────────────────────

/// Create a browser session. Tries camoufox-cli first; falls back to Playwright.
/// Mirrors Python's `create_session()`.
pub async fn create_session(cfg: Settings) -> Box<dyn BrowserSession> {
    // Check if camoufox-cli is available
    let probe = Command::new(&cfg.camoufox_cli)
        .arg("--help")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .await;

    if probe.is_ok() {
        return Box::new(CamoufoxSession::new(cfg));
    }

    // TODO: Playwright fallback (Phase follow-up)
    // For now fall through to Camoufox regardless (will fail at runtime if not installed)
    tracing::warn!("camoufox-cli not found; no fallback implemented — proceeding anyway");
    Box::new(CamoufoxSession::new(cfg))
}

/// Cleanup resources after a session. For Playwright this would remove temp profile dir.
pub fn cleanup_session(_sess: &dyn BrowserSession) {
    // Camoufox: nothing to clean up (server-managed)
    // Playwright: would remove /tmp/pw-* clone — TODO when PlaywrightSession is implemented
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ensure_at_prefix() {
        assert_eq!(ensure_at_prefix("el3"), "@el3");
        assert_eq!(ensure_at_prefix("@el3"), "@el3");
        assert_eq!(ensure_at_prefix("@el10"), "@el10");
    }

    #[test]
    fn test_sid_length() {
        let cfg = Settings::from_env();
        let sess = CamoufoxSession::new(cfg);
        assert_eq!(sess.sid.len(), 8);
        // Must be hex chars
        assert!(sess.sid.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_strip_pw_wrapper() {
        let script = r#"async (page) => {
  await page.waitForTimeout(1000);
}"#;
        let inner = strip_pw_wrapper(script).unwrap();
        assert!(inner.contains("await page.waitForTimeout(1000)"));
        assert!(!inner.starts_with("async (page) =>"));
    }

    #[test]
    fn test_to_camoufox_js_wraps_iife() {
        let script = r#"async (page) => {
  await page.waitForTimeout(3000);
  return document.title;
}"#;
        let result = to_camoufox_js(script);
        assert!(result.contains("(async () => {"));
        assert!(result.contains("const wait ="));
        assert!(result.contains("await wait(3000)"));
        assert!(!result.contains("page.waitForTimeout"));
    }

    #[test]
    fn test_to_camoufox_js_click_conversion() {
        let script =
            r#"async (page) => { await page.locator('[data-qa="btn"]').first().click(); }"#;
        let result = to_camoufox_js(script);
        assert!(result.contains(r#"await clickEl('[data-qa="btn"]')"#));
    }

    #[test]
    fn test_to_camoufox_js_fill_conversion() {
        let script =
            r#"async (page) => { await page.locator('[data-qa="input"]').first().fill('hello'); }"#;
        let result = to_camoufox_js(script);
        assert!(result.contains("await fillEl("));
    }
}
