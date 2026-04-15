"""Browser automation — camoufox-cli (primary) + Playwright CLI (fallback).

Camoufox CLI runs JS directly in page context (no page. prefix).
Playwright CLI uses async (page) => { page.xxx() } format.

This module provides a unified interface and auto-converts JS between formats.
"""

import os
import shutil
import subprocess
import tempfile
import time
import uuid

from .config import settings


class BrowserSession:
    """Base class — defines the interface both backends implement."""

    backend: str = "unknown"

    def open(self, url: str) -> str:
        raise NotImplementedError

    def navigate(self, url: str) -> str:
        raise NotImplementedError

    def run_code(self, js_code: str, timeout: int = 60) -> str:
        raise NotImplementedError

    def snapshot(self, interactive: bool = True) -> str:
        raise NotImplementedError

    def click(self, ref: str) -> str:
        raise NotImplementedError

    def fill(self, ref: str, text: str) -> str:
        raise NotImplementedError

    def screenshot(self, full_page: bool = False) -> str:
        raise NotImplementedError

    def close(self) -> str:
        raise NotImplementedError


class CamoufoxSession(BrowserSession):
    """Camoufox CLI — JS runs directly in page context."""

    backend = "camoufox"

    def __init__(self, session_id: str | None = None):
        self.sid = session_id or uuid.uuid4().hex[:8]

    def _run(self, *args: str, timeout: int = 30) -> str:
        cmd = [settings.camoufox_cli, "--session", self.sid, *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"camoufox-cli error: {result.stderr or result.stdout}")
        return result.stdout

    def open(self, url: str) -> str:
        profile = os.path.expanduser(settings.camoufox_profile)
        result = self._run("--persistent", profile, "open", url, timeout=30)
        time.sleep(2)  # Wait for page to initialize
        return result

    def navigate(self, url: str) -> str:
        result = self._run("open", url, timeout=30)
        time.sleep(2)
        return result

    def run_code(self, js_code: str, timeout: int = 60) -> str:
        """Run JS in page context — no page. prefix needed."""
        return self._run("eval", js_code, timeout=timeout)

    def snapshot(self, interactive: bool = True) -> str:
        args = ["snapshot"]
        if interactive:
            args.append("-i")
        return self._run(*args, timeout=15)

    def click(self, ref: str) -> str:
        return self._run("click", ref if ref.startswith("@") else f"@{ref}", timeout=15)

    def fill(self, ref: str, text: str) -> str:
        ref_str = ref if ref.startswith("@") else f"@{ref}"
        return self._run("fill", ref_str, text, timeout=15)

    def screenshot(self, full_page: bool = False) -> str:
        args = ["screenshot"]
        if full_page:
            args.append("--full")
        return self._run(*args, timeout=15)

    def close(self) -> str:
        try:
            return self._run("close", timeout=10)
        except Exception:
            return ""


class PlaywrightSession(BrowserSession):
    """Playwright CLI — JS wrapped in async (page) => { page.xxx() }."""

    backend = "playwright"

    def __init__(self, session_id: str | None = None):
        self.sid = session_id or uuid.uuid4().hex[:8]
        self.profile_dir: str | None = None
        self._cli = settings.playwright_cli

    def _run(self, *args: str, timeout: int = 30) -> str:
        cmd_parts = [*self._cli.split(), f"-s={self.sid}", *args]
        if self.profile_dir:
            idx = next(
                (
                    i
                    for i, a in enumerate(cmd_parts)
                    if a in ("open", "run-code", "screenshot", "close")
                ),
                len(cmd_parts),
            )
            cmd_parts.insert(idx, f"--profile={self.profile_dir}")

        result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"Playwright CLI error: {result.stderr or result.stdout}")
        if result.stdout.lstrip().startswith("### Error"):
            raise RuntimeError(f"Playwright CLI error: {result.stdout[:500]}")
        return result.stdout

    def open(self, url: str) -> str:
        return self._run("open", url, timeout=30)

    def navigate(self, url: str) -> str:
        return self.open(url)

    def run_code(self, js_code: str, timeout: int = 60) -> str:
        """Run JS via Playwright CLI run-code — expects async (page) => format."""
        return self._run("run-code", js_code, timeout=timeout)

    def snapshot(self, interactive: bool = True) -> str:
        args = ["snapshot"]
        if interactive:
            args.append("-i")
        return self._run(*args, timeout=15)

    def click(self, ref: str) -> str:
        return self._run("click", ref if ref.startswith("@") else f"@{ref}", timeout=15)

    def fill(self, ref: str, text: str) -> str:
        ref_str = ref if ref.startswith("@") else f"@{ref}"
        return self._run("fill", ref_str, text, timeout=15)

    def screenshot(self, full_page: bool = False) -> str:
        args = ["screenshot"]
        if full_page:
            args.append("--full-page")
        return self._run(*args, timeout=15)

    def close(self) -> str:
        try:
            return self._run("close", timeout=10)
        except Exception:
            return ""


# ── JS Conversion Utilities ─────────────────────────────────────────────────


def to_camoufox_js(script: str) -> str:
    """Convert Playwright-style async (page) => script to camoufox page-context format.

    Transforms:
    - async (page) => { ... }  →  (async () => { ... })()
    - page.locator(...).click()  →  DOM click via querySelector
    - page.locator(...).fill()  →  DOM input value set
    - page.waitForTimeout(ms)  →  await wait(ms)
    - page.evaluate(fn)  →  fn()  (already in page context)
    - page.url()  →  window.location.href
    - page.waitForFunction(fn)  →  custom poller
    - page.waitForLoadState()  →  wait()
    """
    # Strip async (page) => wrapper if present
    import re

    inner = re.sub(r"^async\s*\(page\)\s*=>\s*\{", "", script.strip())
    if inner != script.strip():
        # Remove trailing }
        inner = inner.rstrip()
        if inner.endswith("}"):
            inner = inner[:-1]

    # Convert page.waitForTimeout(ms) → await wait(ms)
    inner = re.sub(r"await\s+page\.waitForTimeout\((\w+)\)", r"await wait(\1)", inner)
    inner = re.sub(r"await\s+page\.waitForTimeout\((\d+)\)", r"await wait(\1)", inner)

    # Convert page.url() → window.location.href
    inner = inner.replace("page.url()", "window.location.href")

    # Convert page.evaluate(() => expr) → expr  (single-line only)
    # For multi-line evaluate, convert to IIFE
    def replace_eval_single(match):
        """Replace single-line page.evaluate(() => expr)"""
        expr = match.group(1)
        return expr

    def replace_eval_multiline(match):
        """Replace multi-line page.evaluate(() => { ... }) with IIFE"""
        body = match.group(1)
        return f"(() => {{{body}}})()"

    # Handle multi-line page.evaluate(() => { ... }) first
    inner = re.sub(
        r"await\s+page\.evaluate\(\(\)\s*=>\s*\{([\s\S]*?)\}\)",
        replace_eval_multiline,
        inner,
    )

    # Then handle single-line page.evaluate(() => expr)
    inner = re.sub(
        r"await\s+page\.evaluate\(\(\)\s*=>\s*([^;\n]+)\)",
        replace_eval_single,
        inner,
    )

    # Convert page.locator(selector).first().click() → clickEl(selector)
    inner = re.sub(
        r"await\s+page\.locator\(([^)]+)\)\.first\(\)\.click\(\)",
        r"await clickEl(\1)",
        inner,
    )

    # Convert page.locator(selector).click() → clickEl(selector)
    inner = re.sub(
        r"await\s+page\.locator\(([^)]+)\)\.click\(\)",
        r"await clickEl(\1)",
        inner,
    )

    # Convert page.locator(selector).fill(text) → fillEl(selector, text)
    inner = re.sub(
        r"await\s+page\.locator\(([^)]+)\)\.fill\(([^)]+)\)",
        r"await fillEl(\1, \2)",
        inner,
    )

    # Convert const x = page.locator(sel) → const x = queryEl(sel)
    # Also handle .first() chaining — querySelector already returns first match
    inner = re.sub(
        r"(const|let|var)\s+(\w+)\s*=\s*page\.locator\(([^)]+)\)\.first\(\)",
        r"\1 \2 = queryEl(\3)",
        inner,
    )
    inner = re.sub(
        r"(const|let|var)\s+(\w+)\s*=\s*page\.locator\(([^)]+)\)",
        r"\1 \2 = queryEl(\3)",
        inner,
    )

    # Convert await x.count() → (x ? 1 : 0)  (for single elements)
    inner = re.sub(
        r"await\s+(\w+)\.count\(\)",
        r"(\1 ? 1 : 0)",
        inner,
    )

    # Convert await x.fill(text) → fillEl(x, text) — but x is now DOM element
    # Actually after above conversion, x is a DOM element, so:
    # x.fill(text) → fillElDirect(x, text)
    inner = re.sub(
        r"await\s+(\w+)\.fill\(([^)]+)\)",
        r"await fillElDirect(\1, \2)",
        inner,
    )

    # Convert await x.isVisible() → (x && x.offsetParent !== null)
    inner = re.sub(
        r"await\s+(\w+)\.isVisible\(\)",
        r"(\1 && \1.offsetParent !== null)",
        inner,
    )

    # Convert x.click() → x.click() (already DOM element, just add await if needed)
    # For DOM elements, click is synchronous
    inner = re.sub(
        r"await\s+(\w+)\.click\(\)",
        r"\1.click()",
        inner,
    )

    # Convert page.locator(selector).nth(i) → getNth(selector, i)
    inner = re.sub(
        r"page\.locator\(([^)]+)\)\.nth\(([^)]+)\)",
        r"getNth(\1, \2)",
        inner,
    )

    # Convert page.waitForFunction(fn, arg, opts) → waitForFn(fn, arg, opts)
    # Handle multi-line format
    inner = re.sub(
        r"await\s+page\.waitForFunction\(\s*([^,]+),\s*([^,]*),?\s*(\{[^}]*\})?\s*\)",
        r"await waitForFn(\1, \2, \3)",
        inner,
        flags=re.DOTALL,
    )

    # Convert page.waitForLoadState(...) → wait(3000)
    inner = re.sub(r"await\s+page\.waitForLoadState\([^)]*\)", "await wait(3000)", inner)

    # Wrap in IIFE with helpers
    wrapper = (
        """(async () => {
  const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

  const clickEl = (selector) => {
    // Handle Playwright text= selector
    if (selector.startsWith('text=')) {
      const text = selector.slice(5);
      // Prioritize button elements over divs/spans
      const allEls = document.querySelectorAll('button, [role="button"], a, input[type="submit"], span, div');
      let fallback = null;
      for (const el of allEls) {
        if (el.textContent.trim().includes(text) && el.offsetParent !== null) {
          if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.type === 'submit') {
            el.click(); return true;
          }
          if (!fallback) fallback = el;
        }
      }
      if (fallback) { fallback.click(); return true; }
      return false;
    }
    const el = document.querySelector(selector);
    if (el) { el.click(); return true; }
    return false;
  };

  // React-compatible fill using native setter + InputEvent (works with SurveyCake)
  const _nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const _nativeSetTA = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  const _reactFill = (el, text) => {
    const setter = el.tagName === 'TEXTAREA' ? _nativeSetTA : _nativeSet;
    el.focus();
    setter.call(el, '');
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
    setter.call(el, text);
    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.blur();
  };

  const fillEl = (selector, text) => {
    const el = document.querySelector(selector);
    if (el) { _reactFill(el, text); return true; }
    return false;
  };

  const fillElDirect = (el, text) => {
    if (el) { _reactFill(el, text); return true; }
    return false;
  };

  const queryEl = (selector) => {
    // Handle Playwright text= selector
    if (selector.startsWith('text=')) {
      const text = selector.slice(5);
      const allEls = document.querySelectorAll('button, [role="button"], a');
      for (const el of allEls) {
        if (el.textContent.trim().includes(text) && el.offsetParent !== null) {
          return el;
        }
      }
      return null;
    }
    return document.querySelector(selector);
  };

  const countEl = (selector) => document.querySelectorAll(selector).length;

  const isVisible = (selector) => {
    const el = document.querySelector(selector);
    return el && el.offsetParent !== null;
  };

  const getNth = (selector, n) => document.querySelectorAll(selector)[n];

  const waitForFn = async (fn, arg, opts) => {
    const timeout = opts?.timeout || 30000;
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (fn(arg)) return true;
      await wait(100);
    }
    return false;
  };

"""
        + inner
        + """
})()"""
    )
    return wrapper


def to_playwright_js(script: str) -> str:
    """Ensure script is in Playwright async (page) => format.

    If already wrapped, return as-is. Otherwise wrap it.
    """
    import re

    stripped = script.strip()
    if stripped.startswith("async (page) =>"):
        return stripped

    # It's already in page-context format — wrap it
    # Replace DOM APIs with Playwright equivalents
    inner = stripped

    # Replace wait(ms) → await page.waitForTimeout(ms)
    inner = re.sub(r"await wait\((\d+)\)", r"await page.waitForTimeout(\1)", inner)

    # Replace clickEl(sel) → await page.locator(sel).first().click()
    inner = re.sub(r"await clickEl\(([^)]+)\)", r"await page.locator(\1).first().click()", inner)

    # Replace fillEl(sel, text) → await page.locator(sel).first().fill(text)
    inner = re.sub(
        r"await fillEl\(([^,]+),\s*([^)]+)\)", r"await page.locator(\1).first().fill(\2)", inner
    )

    # Replace countEl(sel) → await page.locator(sel).count()
    inner = re.sub(r"countEl\(([^)]+)\)", r"await page.locator(\1).count()", inner)

    # Replace isVisible(sel) → await page.locator(sel).first().isVisible()
    inner = re.sub(r"isVisible\(([^)]+)\)", r"await page.locator(\1).first().isVisible()", inner)

    # Replace window.location.href → page.url()
    inner = inner.replace("window.location.href", "page.url()")

    # Replace document.body.innerText → await page.evaluate(() => document.body.innerText)
    inner = re.sub(
        r"document\.body\.innerText",
        r"await page.evaluate(() => document.body.innerText)",
        inner,
    )

    return f"async (page) => {{\n{inner}\n}}"


def adapt_js_for_backend(js_code: str, backend: str) -> str:
    """Adapt JS code for the target backend."""
    if backend == "camoufox":
        return to_camoufox_js(js_code)
    elif backend == "playwright":
        return to_playwright_js(js_code)
    return js_code


# ── Factory ─────────────────────────────────────────────────────────────────


def create_session() -> CamoufoxSession | PlaywrightSession:
    """Create a browser session — camoufox-cli primary, playwright-cli fallback."""
    try:
        subprocess.run(
            ["camoufox-cli", "--help"],
            capture_output=True,
            timeout=5,
        )
        return CamoufoxSession()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback to playwright
    sess = PlaywrightSession()
    profile_src = settings.pw_profile_dir
    if not profile_src:
        profile_src = "~/.playwright-profiles/master"

    profile_src = os.path.expanduser(profile_src)
    if os.path.isdir(profile_src):
        tmp = tempfile.mkdtemp(prefix="pw-")
        subprocess.run(
            ["cp", "-c", "-R", profile_src + "/.", tmp],
            check=False,
            capture_output=True,
        )
        sess.profile_dir = tmp
    return sess


def cleanup_session(sess: BrowserSession) -> None:
    """Clean up session resources."""
    if isinstance(sess, PlaywrightSession) and sess.profile_dir:
        if sess.profile_dir.startswith("/tmp/pw-"):
            shutil.rmtree(sess.profile_dir, ignore_errors=True)
