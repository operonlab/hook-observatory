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
1. Opens a headed camoufox window using the master profile.
2. Auto-clicks ``立即登录 → 使用Google帳號登入 → <your Google account>``
   (refs discovered from the live aria snapshot — selectors are not
   hard-coded).
3. Stops at the Google passkey screen — that step **requires the user
   to authenticate physically** (Touch ID / Face ID / system password).
   The script prints a clear "your turn" message and polls for
   completion every 5 seconds.
4. Once login is detected, calls ``camoufox-cli cookies export`` to
   refresh ``~/.camoufox-profiles/master-login-cookies.json``.
5. Optionally runs ``agent-metrics dashscope-quota-sync`` to verify the
   new cookies work end-to-end.

Usage
-----
    # Interactive (requires user passkey at the Google auth step):
    ~/.local/bin/python3 ~/workshop/schedules/runners/ws_dashscope_oauth_refresh.py

    # Skip the post-export verification (faster, manual verify later):
    ~/.local/bin/python3 ws_dashscope_oauth_refresh.py --no-verify

Not safe to run from cron — the passkey step is interactive. The audit
runner ``ws-account-sync`` will exit non-zero when cookies are stale,
and Cronicle paints the slot red. That's your signal to run this
script manually at the next convenient moment.
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


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: S110
        pass


def cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run camoufox-cli with the OAuth refresh session pinned."""
    cmd = ["camoufox-cli", "--session", SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)


def cfx_headed_open(url: str) -> subprocess.CompletedProcess:
    """First open uses --headed --persistent so a window appears for the user."""
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


def find_ref(needle: str) -> str | None:
    """Return the first aria ``[ref=eNN]`` whose snapshot line contains ``needle``."""
    snap = cfx("snapshot", "-i", timeout=15)
    if snap.returncode != 0:
        return None
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snap.stdout.splitlines():
        if needle in line:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def find_google_login_ref() -> str | None:
    snap = cfx("snapshot", "-i", timeout=15)
    if snap.returncode != 0:
        return None
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snap.stdout.splitlines():
        if "Google" in line and "登入" in line:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def find_google_account_ref(email_hint: str = "@gmail.com") -> str | None:
    snap = cfx("snapshot", "-i", timeout=15)
    if snap.returncode != 0:
        return None
    pat = re.compile(r"\[ref=(e\d+)\]")
    for line in snap.stdout.splitlines():
        if email_hint in line:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def is_logged_in() -> bool:
    """Return True when the DashScope dashboard shows post-login content."""
    js = (
        "document.body.innerText.includes('登录以使用') ? 'no' : "
        "(document.body.innerText.includes('模型用量') || "
        "document.body.innerText.includes('默认业务空间') || "
        "document.body.innerText.includes('模型总数') ? 'yes' : 'pending')"
    )
    r = cfx("eval", js, timeout=10)
    return r.returncode == 0 and "yes" in r.stdout.lower()


def wait_for_login(max_wait_s: int = 180) -> bool:
    """Poll every 5s until the page shows logged-in state or timeout."""
    deadline = time.time() + max_wait_s
    last_url = ""
    while time.time() < deadline:
        if is_logged_in():
            return True
        url_r = cfx("url", timeout=5)
        cur_url = url_r.stdout.strip() if url_r.returncode == 0 else ""
        if cur_url and cur_url != last_url:
            _log(f"  still at: {cur_url[:80]}...")
            last_url = cur_url
        time.sleep(5)
    return False


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
        # Look for parsed metrics in stderr (tracing output).
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the post-export agent-metrics dashscope-quota-sync verification",
    )
    parser.add_argument(
        "--email-hint",
        default="@gmail.com",
        help="substring used to pick your Google account from the chooser (default: '@gmail.com')",
    )
    args = parser.parse_args()

    _log("=== DashScope OAuth refresh start ===")
    _log("This will open a headed camoufox window. You'll be asked to")
    _log("complete the Google passkey step (Touch ID / Face ID / password).")
    _log("")

    # 1. Headed open
    _log("[1/5] Opening DashScope dashboard (headed)…")
    r = cfx_headed_open(DASHSCOPE_URL)
    if r.returncode != 0:
        _log(f"  FATAL: headed open failed: {r.stderr[:200]}")
        return 2
    time.sleep(10)

    if is_logged_in():
        _log("  Already logged in (cookies were still valid). Just refreshing snapshot.")
        rc = export_cookies()
        close_session()
        if rc == 0 and not args.no_verify:
            return run_verification()
        return rc

    # 2. Click 立即登录
    _log("[2/5] Clicking 「立即登录」…")
    ref = find_ref("立即登录")
    if not ref:
        _log("  FATAL: 立即登录 button not found")
        close_session()
        return 3
    cfx("click", f"@{ref}", timeout=10)
    time.sleep(4)

    # 3. Click 使用Google帳號登入
    _log("[3/5] Clicking 「使用Google帳號登入」…")
    ref = find_google_login_ref()
    if not ref:
        _log("  FATAL: Google login button not found")
        close_session()
        return 4
    cfx("click", f"@{ref}", timeout=10)
    time.sleep(5)

    # 4. Click Google account
    _log(f"[4/5] Clicking Google account (looking for '{args.email_hint}')…")
    ref = find_google_account_ref(args.email_hint)
    if ref:
        cfx("click", f"@{ref}", timeout=10)
        time.sleep(4)
    else:
        _log(
            "  (No matching account in chooser — you may need to manually pick one in the window.)"
        )

    # 5. Wait for user passkey + redirect back to Alibaba
    _log("")
    _log("[5/5] ⏳ YOUR TURN: complete the Google passkey in the camoufox window.")
    _log("       (Touch ID / Face ID / system password — then it auto-redirects.)")
    _log("       Polling every 5s up to 3 minutes…")
    _log("")
    ok = wait_for_login(max_wait_s=180)
    if not ok:
        _log("  ✗ Timed out waiting for login. Keep the window open and re-run, or")
        _log("    investigate manually.")
        close_session()
        return 5

    _log("  ✓ DashScope logged in.")

    # 6. Export cookies + verify
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
