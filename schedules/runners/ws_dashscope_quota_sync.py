#!/usr/bin/env python3
"""ws_dashscope_quota_sync.py — DashScope (Qwen) free-quota sync.

[2026-05-14 重寫] Thin wrapper around ws_credits_sync.run_dashscope_sync().

Why this exists:
  The previous standalone scraper imported `master-login-cookies.json` once
  per run and waited 6 s for the SPA. DashScope's HttpOnly session tokens
  (login_aliyunid_ticket / JSESSIONID) expire faster than the daily cron
  cadence, so by 2026-05-14 the 18:30 job was reliably exit=1.
  `ws_credits_sync.py` already implements `_dashscope_auto_login()` which
  drives a Google-OAuth click-through whenever the page shows "登录以使用".
  The agent-metrics Rust binary (renamed from agent-metrics-rs on
  2026-05-12) does not yet implement camoufox-based DashScope scraping,
  so this Python wrapper remains the active path until the Rust collector
  picks it up.

Original implementation kept at ws_dashscope_quota_sync.py.bak-20260514.
"""

from __future__ import annotations

import fcntl
import sys
import time
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    from ws_credits_sync import (
        CFX_SESSION,
        DASHSCOPE_URL,
        _cfx,
        cfx_close,
        log,
        run_dashscope_sync,
    )

    log("=== Qwen Free Quota Sync (via credits-sync wrapper) ===")

    # run_dashscope_sync assumes the shared camoufox session is already
    # opened with `--persistent` (normally done by run_provider_sync in
    # Section 1). When invoked standalone, warm it up first so master
    # profile cookies are loaded.
    warmup = _cfx(CFX_SESSION, "--persistent", "open", DASHSCOPE_URL, timeout=30)
    if warmup.returncode != 0:
        log(f"WARN: camoufox warmup failed (rc={warmup.returncode}): {warmup.stderr[:200]}")
    else:
        # Give the SPA + any pending OAuth redirect a head start before
        # run_dashscope_sync re-navigates and probes for "登录以使用".
        time.sleep(2)

    try:
        ok = run_dashscope_sync()
    finally:
        cfx_close(CFX_SESSION)

    return 0 if ok else 1


if __name__ == "__main__":
    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    sys.exit(main())
