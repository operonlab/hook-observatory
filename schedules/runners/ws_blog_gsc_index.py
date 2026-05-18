#!/usr/bin/env python3
"""
ws_blog_gsc_index.py — Daily blog change detection → GSC re-index submission

Pipeline:
  1. Fetch sitemap-posts.xml, compare lastmod against state.json
  2. For changed URLs, use camoufox-cli / Playwright CLI (fallback)
     to submit "Request Indexing" in GSC
  3. Update state.json for successfully submitted URLs

Logs: ~/workshop/outputs/scheduler/logs/ws-blog-gsc-index.log
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
PW_SESSION = HOME / ".claude/scripts/pw_session.py"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-blog-gsc-index.log"
STATE_DIR = HOME / "workshop/outputs/blog-gsc"
STATE_FILE = STATE_DIR / "state.json"
CFX_SESSION = "gsc-index"

SITEMAP_URL = "http://127.0.0.1:10302/sitemap-posts.xml"
GSC_BASE = "https://search.google.com/search-console"
GSC_PROPERTY = "https://blog.joneshong.com/"
MAX_SUBMISSIONS = 10
POLL_INTERVAL = 10  # seconds between snapshot polls
POLL_TIMEOUT = 120  # max seconds to wait for indexing confirmation

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

os.environ["PATH"] = (
    f"/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:"
    f"/usr/sbin:/sbin:{HOME}/.local/bin:{os.environ.get('PATH', '')}"
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def bark_notify(title: str, body: str) -> None:
    bark_url = os.environ.get("BARK_URL", "http://127.0.0.1:8090")
    bark_key = os.environ.get("BARK_KEY", "")
    if not bark_key:
        return
    try:
        url = f"{bark_url}/{bark_key}/{title}/{body}"
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


# ── Phase 2a: GSC Submission via camoufox-cli (primary) ──────


def _cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a camoufox-cli command with the GSC session."""
    cmd = ["camoufox-cli", "--session", CFX_SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def cfx_snapshot() -> str:
    """Take snapshot and return aria tree text."""
    r = _cfx("snapshot", "-i", timeout=15)
    return r.stdout if r.returncode == 0 else ""


def submit_single_url_cfx(url: str) -> str:
    """Submit one URL to GSC via camoufox-cli. Returns 'ok', 'quota', or error."""
    # GSC is a heavy SPA — the URL Inspection combobox can take 10-20s to
    # render after navigation, especially in cron/headless mode. The fixed
    # 5s sleep in submit_urls_to_gsc_cfx is not enough; on 2026-05-17 10:02
    # all 10 URLs failed with search_box_not_found in the same second
    # because the first snapshot was taken before the SPA hydrated. Poll
    # for the combobox here so the first URL pays the warmup cost and the
    # rest get the ref in one shot.
    search_ref = None
    snap = ""
    for _ in range(6):  # up to ~30s on cold open; ~0s once hydrated
        snap = cfx_snapshot()
        health = check_session_health(snap)
        if health:
            return health
        search_ref = find_ref(snap, r"combobox.*檢查") or find_ref(
            snap, r"combobox.*Inspect"
        )
        if search_ref:
            break
        time.sleep(5)
    if not search_ref:
        log("  WARN: Cannot find search box in snapshot")
        return "search_box_not_found"

    _cfx("click", f"@{search_ref}")
    _cfx("fill", f"@{search_ref}", url)
    _cfx("press", "Enter")

    time.sleep(8)

    snap = cfx_snapshot()
    health = check_session_health(snap)
    if health:
        return health

    btn_ref = find_ref(snap, r"要求建立索引")
    if not btn_ref:
        btn_ref = find_ref(snap, r"Request [Ii]ndexing")
    if not btn_ref:
        time.sleep(5)
        snap = cfx_snapshot()
        btn_ref = find_ref(snap, r"要求建立索引")
    if not btn_ref:
        log("  WARN: Cannot find 'Request Indexing' button")
        return "button_not_found"

    _cfx("click", f"@{btn_ref}")

    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        snap = cfx_snapshot()

        if "已要求建立索引" in snap or "Indexing requested" in snap:
            close_ref = find_ref(snap, r"button.*關閉") or find_ref(snap, r"button.*[Cc]lose")
            if close_ref:
                _cfx("click", f"@{close_ref}")
                time.sleep(1)
            return "ok"

        if "配額" in snap or "quota" in snap.lower():
            return "quota"

        if "正在測試" in snap or "Testing" in snap:
            continue

        log(f"  Poll {elapsed}s: waiting...")

    return "timeout"


def submit_urls_to_gsc_cfx(urls: list[str]) -> dict[str, str]:
    """Submit URLs to GSC via camoufox-cli. Returns {url: status}."""
    results: dict[str, str] = {}

    try:
        gsc_url = f"{GSC_BASE}?resource_id={urllib.request.quote(GSC_PROPERTY, safe='')}"
        open_r = _cfx("--persistent", "open", gsc_url)
        if open_r.returncode != 0:
            log(f"ERROR: camoufox open failed: {open_r.stderr[:200]}")
            return {u: "cfx_open_failed" for u in urls}

        time.sleep(5)

        snap = cfx_snapshot()
        health = check_session_health(snap)
        if health:
            log(f"ERROR: Session issue on GSC open: {health}")
            bark_notify("Blog GSC Alert", health)
            return {u: health for u in urls}

        for url in urls:
            log(f"  Submitting: {url}")
            status = submit_single_url_cfx(url)
            results[url] = status
            log(f"  Result: {status}")

            if status == "quota":
                log("WARN: Quota exhausted, stopping further submissions")
                bark_notify("Blog GSC Alert", f"Quota exhausted after {len(results)} URLs")
                for remaining in urls[len(results):]:
                    results[remaining] = "skipped_quota"
                break
            elif status in ("CAPTCHA detected", "Login required"):
                log(f"ERROR: {status}, aborting")
                bark_notify("Blog GSC Alert", status)
                for remaining in urls[len(results):]:
                    results[remaining] = "skipped_session"
                break

    except subprocess.TimeoutExpired:
        log("ERROR: camoufox timeout")
    except FileNotFoundError:
        log("WARN: camoufox-cli not found")
        return {}  # Return empty so caller knows to try fallback
    except Exception as e:
        log(f"ERROR: camoufox unexpected: {e}")
    finally:
        try:
            close_r = _cfx("close", timeout=10)
            if close_r.returncode != 0:
                msg = f"camoufox close failed (rc={close_r.returncode}): {close_r.stderr[:200]}"
                log(f"ERROR: {msg}")
                bark_notify("Browser Cleanup Alert", msg)
        except Exception as e:
            msg = f"camoufox close raised: {e}"
            log(f"ERROR: {msg}")
            bark_notify("Browser Cleanup Alert", msg)

    return results


# ── Phase 1: Change Detection ─────────────────────────────────


def fetch_sitemap() -> dict[str, str]:
    """Fetch sitemap-posts.xml, return {url: lastmod} dict."""
    try:
        with urllib.request.urlopen(SITEMAP_URL, timeout=10) as resp:
            xml_bytes = resp.read()
    except Exception as e:
        log(f"WARN: Sitemap fetch failed: {e}")
        return {}

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log(f"WARN: Sitemap XML parse failed: {e}")
        return {}

    entries = {}
    for url_el in root.findall(f"{SITEMAP_NS}url"):
        loc = url_el.findtext(f"{SITEMAP_NS}loc", "")
        lastmod = url_el.findtext(f"{SITEMAP_NS}lastmod", "")
        if loc:
            entries[loc] = lastmod
    return entries


def load_state() -> dict:
    """Load state.json, return empty dict on missing/corrupt file."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        log("WARN: state.json corrupt, treating as empty")
        return {}


def detect_changes() -> tuple[dict[str, str], list[str]]:
    """Compare sitemap against state, return (sitemap_entries, changed_urls)."""
    sitemap = fetch_sitemap()
    if not sitemap:
        return {}, []

    state = load_state()
    stored = state.get("urls", {})

    changed = []
    for url, lastmod in sitemap.items():
        prev = stored.get(url, {})
        if not prev or prev.get("lastmod") != lastmod:
            changed.append(url)

    return sitemap, changed[:MAX_SUBMISSIONS]


# ── Phase 2b: GSC Submission via Playwright CLI (fallback) ──


def pw_init() -> tuple[str | None, str | None]:
    """Init Playwright session, return (profile_dir, sid)."""
    result = subprocess.run(
        [str(PYTHON), str(PW_SESSION), "init"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    profile_dir = sid = None
    for line in result.stdout.splitlines():
        if line.startswith("export PW_PROFILE="):
            profile_dir = line.split("=", 1)[1].strip().strip("'\"")
        elif line.startswith("export SID="):
            sid = line.split("=", 1)[1].strip().strip("'\"")
    # Truncate SID to 8 chars — longer IDs cause EINVAL on macOS
    # (Unix socket path limit is 104 bytes)
    if sid and len(sid) > 8:
        sid = sid[:8]
    return profile_dir, sid


def pw_cmd(session_id: str, *args: str, timeout: int = 15) -> str:
    """Run a playwright-cli command and return stdout.

    For 'snapshot' commands, the actual accessibility tree is written to a
    YAML file — stdout only contains a summary. We detect this and read
    the YAML file to get the full tree with element refs.
    """
    cmd = ["playwright-cli", f"-s={session_id}", *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(HOME / "workshop"),
    )
    stdout = result.stdout

    # For snapshot commands, read the YAML file referenced in output
    if args and args[0] == "snapshot":
        yml_match = re.search(r"\[Snapshot\]\(([^)]+\.yml)\)", stdout)
        if yml_match:
            rel = yml_match.group(1)
            # Try CWD first, then HOME/workshop (Cronicle may use different CWD)
            for base in [Path.cwd(), HOME / "workshop"]:
                yml_path = base / rel
                if yml_path.exists():
                    try:
                        return yml_path.read_text()
                    except OSError:
                        pass
    return stdout


def pw_open(profile_dir: str, session_id: str, url: str) -> str:
    """Open browser with profile."""
    cmd = [
        "playwright-cli",
        "--profile",
        profile_dir,
        f"-s={session_id}",
        "open",
        url,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(HOME / "workshop"),
    )
    return result.stdout


def pw_close(session_id: str, profile_dir: str) -> None:
    """Close browser and cleanup profile.

    Fail-loud: surface close failures so leaked headless Chrome instances
    are detected (see 19h-leak incident, /tmp/pw-5201e67a3964, 2026-05-17).
    """
    try:
        close_r = subprocess.run(
            ["playwright-cli", f"-s={session_id}", "close"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if close_r.returncode != 0:
            msg = f"playwright close failed (rc={close_r.returncode}): {close_r.stderr[:200]}"
            log(f"ERROR: {msg}")
            bark_notify("Browser Cleanup Alert", msg)
    except Exception as e:
        msg = f"playwright close raised: {e}"
        log(f"ERROR: {msg}")
        bark_notify("Browser Cleanup Alert", msg)
    try:
        cleanup_r = subprocess.run(
            [str(PYTHON), str(PW_SESSION), "cleanup", profile_dir],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if cleanup_r.returncode != 0:
            msg = f"pw_session cleanup failed (rc={cleanup_r.returncode}): {cleanup_r.stderr[:200]}"
            log(f"ERROR: {msg}")
            bark_notify("Browser Cleanup Alert", msg)
    except Exception as e:
        msg = f"pw_session cleanup raised: {e}"
        log(f"ERROR: {msg}")
        bark_notify("Browser Cleanup Alert", msg)


def find_ref(snapshot: str, pattern: str) -> str | None:
    """Find element ref in snapshot by matching accessible name pattern."""
    for match in re.finditer(r"\[ref=(e\d+)\]", snapshot):
        # Get context around this ref (the line it's on)
        pos = match.start()
        line_start = snapshot.rfind("\n", 0, pos) + 1
        line_end = snapshot.find("\n", pos)
        line = snapshot[line_start : line_end if line_end != -1 else len(snapshot)]
        if re.search(pattern, line, re.IGNORECASE):
            return match.group(1)
    return None


def check_session_health(snapshot: str) -> str | None:
    """Check snapshot for session issues. Returns error string or None.

    Note: Google pages commonly include invisible reCAPTCHA v3 scripts,
    so we only flag actual visible CAPTCHA challenges, not script references.
    """
    # Visible CAPTCHA challenge (not just hidden recaptcha iframe/script)
    if "i'm not a robot" in snapshot.lower():
        return "CAPTCHA detected"
    # Login page — only when GSC is NOT loaded (GSC pages contain "Search Console")
    if "Search Console" not in snapshot and "search-console" not in snapshot:
        lower = snapshot.lower()
        if ("sign in" in lower or "登入" in snapshot) and "google" in lower:
            return "Login required"
    return None


def submit_single_url(session_id: str, url: str) -> str:
    """Submit one URL to GSC. Returns 'ok', 'quota', or error string."""
    # Take snapshot to find search box
    snap = pw_cmd(session_id, "snapshot")
    health = check_session_health(snap)
    if health:
        return health

    # Find the URL inspection combobox
    search_ref = find_ref(snap, r"combobox.*檢查")
    if not search_ref:
        search_ref = find_ref(snap, r"combobox.*Inspect")
    if not search_ref:
        log("  WARN: Cannot find search box in snapshot")
        return "search_box_not_found"

    # Fill URL and submit
    pw_cmd(session_id, "click", search_ref)
    pw_cmd(session_id, "fill", search_ref, url)
    pw_cmd(session_id, "press", "Enter")

    # Wait for inspection result to load
    time.sleep(8)

    # Take new snapshot to find "Request Indexing" button
    snap = pw_cmd(session_id, "snapshot")
    health = check_session_health(snap)
    if health:
        return health

    # Look for the request indexing button
    btn_ref = find_ref(snap, r"要求建立索引")
    if not btn_ref:
        btn_ref = find_ref(snap, r"Request [Ii]ndexing")
    if not btn_ref:
        # Maybe page is still loading, wait and retry
        time.sleep(5)
        snap = pw_cmd(session_id, "snapshot")
        btn_ref = find_ref(snap, r"要求建立索引")
    if not btn_ref:
        log("  WARN: Cannot find 'Request Indexing' button")
        return "button_not_found"

    # Click the button
    pw_cmd(session_id, "click", btn_ref)

    # Poll for result
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        snap = pw_cmd(session_id, "snapshot")

        # Success
        if "已要求建立索引" in snap or "Indexing requested" in snap:
            # Dismiss dialog
            close_ref = find_ref(snap, r"button.*關閉") or find_ref(snap, r"button.*[Cc]lose")
            if close_ref:
                pw_cmd(session_id, "click", close_ref)
                time.sleep(1)
            return "ok"

        # Quota exhausted
        if "配額" in snap or "quota" in snap.lower():
            return "quota"

        # Still testing
        if "正在測試" in snap or "Testing" in snap:
            continue

        log(f"  Poll {elapsed}s: waiting...")

    return "timeout"


def submit_urls_to_gsc_pw(urls: list[str]) -> dict[str, str]:
    """Submit URLs to GSC via Playwright. Returns {url: status}."""
    profile_dir, sid = pw_init()
    if not profile_dir or not sid:
        log("ERROR: pw_session init failed")
        return {u: "init_failed" for u in urls}

    session_id = f"{sid}-gsc"
    results: dict[str, str] = {}

    try:
        # Open GSC
        gsc_url = f"{GSC_BASE}?resource_id={urllib.request.quote(GSC_PROPERTY, safe='')}"
        pw_open(profile_dir, session_id, gsc_url)
        time.sleep(5)

        # Verify we're on GSC
        snap = pw_cmd(session_id, "snapshot")
        health = check_session_health(snap)
        if health:
            log(f"ERROR: Session issue on GSC open: {health}")
            bark_notify("Blog GSC Alert", health)
            return {u: health for u in urls}

        for url in urls:
            log(f"  Submitting: {url}")
            status = submit_single_url(session_id, url)
            results[url] = status
            log(f"  Result: {status}")

            if status == "quota":
                log("WARN: Quota exhausted, stopping further submissions")
                bark_notify("Blog GSC Alert", f"Quota exhausted after {len(results)} URLs")
                for remaining in urls[len(results) :]:
                    results[remaining] = "skipped_quota"
                break
            elif status in ("CAPTCHA detected", "Login required", "Login required (zh)"):
                log(f"ERROR: {status}, aborting")
                bark_notify("Blog GSC Alert", status)
                for remaining in urls[len(results) :]:
                    results[remaining] = "skipped_session"
                break

    except subprocess.TimeoutExpired:
        log("ERROR: Playwright timeout")
    except Exception as e:
        log(f"ERROR: Unexpected: {e}")
    finally:
        pw_close(session_id, profile_dir)

    return results


# ── Phase 3: State Update ──────────────────────────────────────


def update_state(sitemap: dict[str, str], results: dict[str, str]) -> None:
    """Update state.json — only persist URLs that were successfully submitted."""
    state = load_state()
    urls = state.get("urls", {})

    for url, status in results.items():
        if status == "ok":
            urls[url] = {
                "lastmod": sitemap.get(url, ""),
                "last_submitted": datetime.now().isoformat(),
                "status": "ok",
            }
        # Failed URLs: keep old state (will retry next run)

    state["urls"] = urls
    state["last_run"] = datetime.now().isoformat()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── Main ───────────────────────────────────────────────────────


def main() -> int:
    log("=== Blog GSC Index Start ===")

    # Phase 1
    sitemap, changed = detect_changes()
    if not changed:
        log("No changes detected")
        log("=== Blog GSC Index Done (no-op) ===")
        return 0

    log(f"Detected {len(changed)} changed URL(s):")
    for u in changed:
        log(f"  - {u}")

    # Phase 2: Submit via camoufox (primary), playwright (fallback)
    results = submit_urls_to_gsc_cfx(changed)
    if not results:
        log("Camoufox failed, trying Playwright CLI fallback...")
        results = submit_urls_to_gsc_pw(changed)

    # Phase 3
    update_state(sitemap, results)

    ok = sum(1 for v in results.values() if v == "ok")
    failed = len(results) - ok
    log(f"Results: {ok} submitted, {failed} failed")

    if ok > 0:
        bark_notify("Blog GSC Index", f"Submitted {ok} URL(s)")

    log("=== Blog GSC Index Done ===")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    sys.exit(main())
