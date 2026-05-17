#!/usr/bin/env python3
"""ws_dashscope_oauth_refresh.py — Refresh DashScope cookies via Google OAuth.

Why this exists
---------------
DashScope (Alibaba Cloud Model Studio) session cookies (login_aliyunid_ticket,
JSESSIONID, login_aliyunid_*) are **session cookies** — they die when the
browser closes. The rust collector `agent-metrics dashscope-quota-sync`
re-imports them from ``~/.camoufox-profiles/master-login-cookies.json``
on every run, but that snapshot itself goes stale after a few days.

When the rust binary returns `Error: dashscope-quota-sync: scrape or parse
failed` and the camoufox snapshot contains `"未登录"`, it's time to re-do
the OAuth flow and re-export the cookies snapshot.

What this script does
---------------------
1. Opens a headed camoufox window using the master profile and
   navigates to the DashScope free-quota dashboard.
2. If Google session is still warm, login is silent and we just refresh
   the cookie snapshot.
3. Otherwise auto-clicks ``立即登录 → 使用Google帳號登入 → <account>``.
4. On the Google passkey screen, tries the **automated password path**:
   - Click "Try another way"
   - Click the "Enter your password" option
   - Read the password from macOS Keychain
     (``service=google-oauth-dashscope account=<email>``)
   - Fill the password input and submit
5. Defensive monitoring after submit detects:
   - Successful login → continue
   - "Wrong password" → log a clear warning, fall back to manual wait
   - Unexpected 2FA challenge → fall back to manual wait
6. Once login is detected, exports cookies and (optionally) runs the
   rust collector to verify end-to-end.

Failure modes are surfaced via exit codes — Cronicle / launchd will
paint the slot accordingly.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
COOKIES_PATH = HOME / ".camoufox-profiles/master-login-cookies.json"
PROFILE_PATH = HOME / ".camoufox-profiles/master"
DASHSCOPE_URL = (
    "https://modelstudio.console.alibabacloud.com/ap-southeast-1/"
    "?tab=dashboard#/model-usage/free-quota"
)
SESSION = "ds-oauth-refresh"

LOG_FILE = HOME / "workshop/outputs/scheduler/logs/ws-dashscope-oauth-refresh.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

AGENT_METRICS_BIN = HOME / ".cargo/shared-target/release/agent-metrics"

DEFAULT_KEYCHAIN_SERVICE = "google-oauth-dashscope"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: S110
        pass


# ────────────────────────── camoufox-cli wrappers ──────────────────────────


def cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["camoufox-cli", "--session", SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)


def cfx_headed_open(url: str) -> subprocess.CompletedProcess:
    cmd = [
        "camoufox-cli",
        "--session",
        SESSION,
        "--headed",
        "--persistent",
        str(PROFILE_PATH),
        "open",
        url,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)


def snapshot_text() -> str:
    snap = cfx("snapshot", "-i", timeout=15)
    return snap.stdout if snap.returncode == 0 else ""


def page_text(max_chars: int = 2000) -> str:
    r = cfx("eval", f"document.body.innerText.substring(0, {max_chars})", timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ""


def find_ref(needle: str) -> str | None:
    """Return the first aria ref whose snapshot line contains ``needle``."""
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snapshot_text().splitlines():
        if needle in line:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def find_ref_any(*needles: str) -> str | None:
    """Like ``find_ref`` but returns the first ref matching ANY needle."""
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snapshot_text().splitlines():
        if any(n in line for n in needles):
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def find_google_login_ref() -> str | None:
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snapshot_text().splitlines():
        if "Google" in line and "登入" in line:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def find_google_account_ref(email_hint: str = "@gmail.com") -> str | None:
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snapshot_text().splitlines():
        if email_hint in line:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


# ────────────────────────── Keychain ──────────────────────────


def read_keychain_password(service: str, account: str | None = None) -> str | None:
    """Read a password from macOS Keychain. Returns None if not found.

    NEVER logs the password value, only success/failure.
    """
    cmd = ["security", "find-generic-password", "-s", service, "-w"]
    if account:
        cmd[2:2] = ["-a", account]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
    except subprocess.TimeoutExpired:
        _log(f"  Keychain lookup timed out for service={service}")
        return None
    if r.returncode != 0:
        return None
    pw = r.stdout.rstrip("\n")
    return pw or None


# ────────────────────────── Page-state detection ──────────────────────────


def page_state() -> str:
    """Return a short tag for the current page state.

    Categories (priority order):
      logged_in  — DashScope dashboard visible
      need_login — DashScope login wall ("登录以使用")
      passkey    — Google passkey prompt
      password   — Google password input visible
      wrong_pw   — Google "Wrong password" error
      twofa      — Google 2FA / 2-step verification
      account_chooser — Google "Choose an account"
      consent    — Google "alibabacloud wants to..."
      unknown    — anything else
    """
    js = """
    (function() {
      const t = document.body.innerText || '';
      if (t.includes('登录以使用')) return 'need_login';
      if (t.includes('模型用量') || t.includes('默认业务空间') || t.includes('模型总数')) return 'logged_in';
      const lower = t.toLowerCase();
      if (lower.includes('wrong password') || lower.includes('couldn’t verify your password') || lower.includes("couldn't verify your password")) return 'wrong_pw';
      if (lower.includes('2-step') || lower.includes('verify it') || lower.includes('verification code')) return 'twofa';
      if (lower.includes('passkey') || lower.includes('your device will ask for your fingerprint')) return 'passkey';
      // Password input present and prominent
      const pw = document.querySelector('input[type=password]');
      if (pw && pw.offsetParent !== null) return 'password';
      if (lower.includes('choose an account') || t.includes('選擇帳戶')) return 'account_chooser';
      if (lower.includes('wants access') || lower.includes('to continue to alibabacloud')) return 'consent';
      return 'unknown';
    })()
    """
    r = cfx("eval", js, timeout=10)
    if r.returncode != 0:
        return "unknown"
    return r.stdout.strip().strip('"').strip("'").lower()


def is_logged_in() -> bool:
    return page_state() == "logged_in"


def find_password_input_ref() -> str | None:
    """Find aria ref of the visible password input via querySelector."""
    js = """
    (function() {
      const inputs = document.querySelectorAll('input[type=password]');
      for (const inp of inputs) {
        if (inp.offsetParent !== null) {
          return inp.getAttribute('aria-label') || inp.name || 'password_input_found';
        }
      }
      return '';
    })()
    """
    r = cfx("eval", js, timeout=8)
    if r.returncode != 0 or not r.stdout.strip().strip('"'):
        return None
    # Walk the aria snapshot to find a textbox whose label matches our hint.
    label_hint = r.stdout.strip().strip('"').strip("'")
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snapshot_text().splitlines():
        if "textbox" in line.lower() and ("password" in line.lower() or label_hint in line):
            m = pat.search(line)
            if m:
                return m.group(1)
    # Fallback: any textbox on a page where state==password.
    for line in snapshot_text().splitlines():
        if "textbox" in line.lower():
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


# ────────────────────────── Login flow helpers ──────────────────────────


def click_try_another_way() -> bool:
    """On the passkey page, click the link/button that opens alternative methods."""
    ref = find_ref_any("Try another way", "Try a different way", "其他方式", "其他方法")
    if not ref:
        return False
    _log(f"  click 'Try another way' (@{ref})")
    cfx("click", f"@{ref}", timeout=10)
    time.sleep(3)
    return True


def click_password_option() -> bool:
    """On the 'Choose how to sign in' page, pick the password option."""
    ref = find_ref_any(
        "Enter your password",
        "Use your password",
        "Password",
        "輸入密碼",
        "使用密碼",
    )
    if not ref:
        return False
    _log(f"  click 'Enter your password' (@{ref})")
    cfx("click", f"@{ref}", timeout=10)
    time.sleep(3)
    return True


def submit_password(pw: str) -> bool:
    """Fill the visible password input and click Next. Password is never logged."""
    ref = find_password_input_ref()
    if not ref:
        _log("  WARN: password input not found")
        return False
    _log(f"  fill password into @{ref} (value redacted)")
    fill_r = cfx("fill", f"@{ref}", pw, timeout=10)
    if fill_r.returncode != 0:
        _log(f"  WARN: fill failed: {fill_r.stderr[:120]}")
        return False
    time.sleep(1)
    # Find Next/繼續 button
    next_ref = find_ref_any("Next", "繼續", "继续", "下一步")
    if not next_ref:
        _log("  WARN: Next button not found — pressing Enter as fallback")
        cfx("press", "Enter", timeout=8)
        return True
    _log(f"  click Next (@{next_ref})")
    cfx("click", f"@{next_ref}", timeout=10)
    return True


def attempt_password_login(pw: str) -> str:
    """End-to-end "passkey page → submit password" attempt.

    Returns a state tag: 'logged_in' | 'wrong_pw' | 'twofa' | 'no_keychain' |
    'unknown' | 'failed'.
    """
    state = page_state()
    _log(f"  current page state: {state}")
    if state == "logged_in":
        return "logged_in"

    # Step over the passkey screen if present
    if state == "passkey":
        if not click_try_another_way():
            _log("  could not find 'Try another way' link on passkey page")
            return "failed"
        time.sleep(2)
        state = page_state()
        _log(f"  after 'Try another way': state={state}")

        # If now on a list of options, pick password
        if state not in ("password", "twofa", "logged_in"):
            if click_password_option():
                time.sleep(2)
                state = page_state()
                _log(f"  after picking password option: state={state}")

    if state != "password":
        _log(f"  not on password page (state={state}); cannot auto-fill")
        return state

    if not submit_password(pw):
        return "failed"

    # Wait up to 15s for the post-submit state to settle
    for _ in range(15):
        time.sleep(1)
        state = page_state()
        if state in ("logged_in", "wrong_pw", "twofa"):
            break
    _log(f"  post-submit state: {state}")
    return state


# ────────────────────────── Waiters ──────────────────────────


def wait_for_login(max_wait_s: int = 180) -> bool:
    """Poll every 5s until the page shows logged-in state or timeout.

    Surfaces intermediate state changes to the log so the user can see
    what's happening.
    """
    deadline = time.time() + max_wait_s
    last_state = ""
    while time.time() < deadline:
        state = page_state()
        if state != last_state:
            _log(f"  page state: {state}")
            last_state = state
        if state == "logged_in":
            return True
        time.sleep(5)
    return False


# ────────────────────────── Cookies + verify ──────────────────────────


def backup_cookies() -> None:
    if not COOKIES_PATH.exists():
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = COOKIES_PATH.with_suffix(f".json.bak-{ts}")
    shutil.copy2(COOKIES_PATH, backup)
    _log(f"  backed up old cookies to {backup.name}")


def export_cookies() -> int:
    backup_cookies()
    r = cfx("cookies", "export", str(COOKIES_PATH), timeout=20)
    if r.returncode != 0:
        _log(f"  cookies export FAILED: {r.stderr[:200]}")
        return r.returncode
    _log(f"  cookies exported to {COOKIES_PATH.name}")
    return 0


def close_session() -> None:
    cfx("close", timeout=10)


def run_verification() -> int:
    if not AGENT_METRICS_BIN.is_file():
        _log(f"  skip verify: {AGENT_METRICS_BIN} not found")
        return 0
    _log("  verifying with: agent-metrics dashscope-quota-sync")
    r = subprocess.run(
        [str(AGENT_METRICS_BIN), "dashscope-quota-sync"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode == 0:
        for line in r.stderr.splitlines():
            if "parsed" in line and "total_models" in line:
                _log(f"  verify OK: {line.split('parsed')[-1].strip()}")
                break
        else:
            _log("  verify OK (no metrics line found, but rc=0)")
    else:
        _log(f"  verify FAILED rc={r.returncode}")
        _log(f"  stderr tail: {r.stderr.strip()[-300:]}")
    return r.returncode


# ────────────────────────── Main flow ──────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-verify", action="store_true", help="skip post-export verify")
    parser.add_argument("--email-hint", default="@gmail.com", help="Google account chooser hint")
    parser.add_argument(
        "--keychain-service",
        default=DEFAULT_KEYCHAIN_SERVICE,
        help=f"macOS Keychain service name (default: {DEFAULT_KEYCHAIN_SERVICE})",
    )
    parser.add_argument(
        "--keychain-account",
        default=None,
        help="macOS Keychain account (default: any account for the service)",
    )
    parser.add_argument(
        "--no-auto-password",
        action="store_true",
        help="skip Keychain password auto-fill, just wait for manual input",
    )
    args = parser.parse_args()

    _log("=== DashScope OAuth refresh start ===")

    # Try to read password up-front
    pw: str | None = None
    if not args.no_auto_password:
        pw = read_keychain_password(args.keychain_service, args.keychain_account)
        if pw:
            _log(
                f"  Keychain entry found (service={args.keychain_service}, "
                f"len={len(pw)}) — will attempt auto password-fill."
            )
        else:
            _log(
                f"  Keychain entry NOT found (service={args.keychain_service}). "
                "Will wait for manual auth."
            )

    # 1. Headed open
    _log("[1/6] Opening DashScope dashboard (headed)…")
    r = cfx_headed_open(DASHSCOPE_URL)
    if r.returncode != 0:
        _log(f"  FATAL: headed open failed: {r.stderr[:200]}")
        return 2
    time.sleep(10)

    if is_logged_in():
        _log("  Already logged in (cookies were still valid). Refreshing snapshot.")
        rc = export_cookies()
        close_session()
        if rc == 0 and not args.no_verify:
            return run_verification()
        return rc

    # 2. Click 立即登录
    _log("[2/6] Clicking 「立即登录」…")
    ref = find_ref("立即登录")
    if not ref:
        _log("  FATAL: 立即登录 button not found")
        close_session()
        return 3
    cfx("click", f"@{ref}", timeout=10)
    time.sleep(4)

    # 3. Click 使用Google帳號登入
    _log("[3/6] Clicking 「使用Google帳號登入」…")
    ref = find_google_login_ref()
    if not ref:
        _log("  FATAL: Google login button not found")
        close_session()
        return 4
    cfx("click", f"@{ref}", timeout=10)
    time.sleep(5)

    # 4. Click Google account (chooser may auto-skip if only one signed-in account)
    _log(f"[4/6] Picking Google account (hint='{args.email_hint}')…")
    ref = find_google_account_ref(args.email_hint)
    if ref:
        cfx("click", f"@{ref}", timeout=10)
        time.sleep(5)
    else:
        _log("  (No matching account in chooser — Google may have skipped it.)")

    # 5. Try auto password-fill, else fall back to manual wait
    if pw:
        _log("[5/6] Attempting auto password login…")
        result = attempt_password_login(pw)
        if result == "logged_in":
            _log("  ✓ Auto password login succeeded.")
        elif result == "wrong_pw":
            _log("")
            _log("  ✗ Google reports WRONG PASSWORD.")
            _log("    Update Keychain via:")
            _log(f"      security add-generic-password -s '{args.keychain_service}' \\")
            _log("          -a '<your-email>' -w '<new-password>' -U")
            _log("    Falling back to manual wait — type the password in the browser window.")
        elif result == "twofa":
            _log("  ⚠ Google triggered a 2FA / verification challenge — please complete it.")
        elif result in ("no_keychain", "failed", "unknown"):
            _log(f"  ⚠ Auto-fill could not complete (state={result}). Falling back to manual.")
    else:
        _log("[5/6] No Keychain password available — manual mode.")

    # 6. Wait for login (catches all fall-back cases)
    if not is_logged_in():
        _log("")
        _log("[6/6] ⏳ Waiting for login. If a browser window is open, finish auth there.")
        _log("       Polling every 5s up to 3 minutes…")
        _log("")
        if not wait_for_login(max_wait_s=180):
            _log("  ✗ Timed out waiting for login.")
            close_session()
            return 5

    _log("  ✓ DashScope logged in.")

    rc = export_cookies()
    close_session()
    if rc != 0:
        return rc

    if args.no_verify:
        _log("=== Skipping verify (--no-verify). Done. ===")
        return 0

    _log("")
    _log("Verifying cookies actually work…")
    vrc = run_verification()
    _log(f"=== DashScope OAuth refresh done rc={vrc} ===")
    return vrc


if __name__ == "__main__":
    sys.exit(main())
