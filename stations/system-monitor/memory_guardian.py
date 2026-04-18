"""
Memory Guardian — 記憶體壓力防護（在場感知 + 優先保護 Claude Code）

分頁保護鐵律（少爺規則）：
  絕不使用 AppleScript `close tab` — 會把分頁從 tab bar 移除，少爺明令禁止。
  只允許 kill Chrome Helper (Renderer) 釋放記憶體 — tab 保留為 unloaded，點回去 reload。
  實作上由 config `browser.try_applescript_first: false` 強制，切勿改回 true。

殺進程優先順序（先殺不重要的，保住工作工具）：
  P0: Stale Playwright headless Chrome (age > 10min, relaxed threshold)
  P1: Chrome Renderer、LINE、VS Code 等可犧牲的 app（受在場狀態門檻控制）
  P2: 閒置的 Claude Code (CPU < 1%) — CRIT 才觸發
  P3: 忙碌的 Claude Code（CRIT 才觸發，最後手段，給 grace period）

在場感知策略（永不關閉分頁本身）：
  在場 (idle < 5min):      只通知，不動瀏覽器，通知冷卻 30min
  短暫離開 (5-15min):      只通知（不動分頁）
  離開 (>15min):           Kill Renderer（tab 保留、記憶體釋放）+ expendables + 通知
  CRIT 緊急:               無論在不在都 kill Renderer（但永不殺主程序、永不 close tab）

可獨立執行：python memory_guardian.py
也可由 system-monitor API 觸發。
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
logger = logging.getLogger("sysmon.guardian")

# ─── 預設設定（可由 config.json guardian 區塊覆蓋）───
DEFAULTS = {
    "warn_threshold": 40,
    "crit_threshold": 15,
    "p0_age_seconds": 600,
    "p0_threshold_offset": 20,
    "idle_cpu": 1.0,
    "min_age_seconds": 300,
    "grace_seconds": 30,
    "log_max_bytes": 1_048_576,
    "log_retain_lines": 200,
    "expendables": [
        {"pattern": "Google Chrome Helper (Renderer)", "label": "Chrome 分頁", "browser": True},
        {"pattern": "Google Chrome Helper (GPU)", "label": "Chrome GPU", "browser": True},
        {"pattern": "LINE", "label": "LINE"},
        {"pattern": "LineCall", "label": "LINE Call"},
        {"pattern": "Visual Studio Code", "label": "VS Code"},
        {"pattern": "Antigravity", "label": "Antigravity"},
        {"pattern": "openclaw-gateway", "label": "OpenClaw"},
        {"pattern": "AltServer", "label": "AltServer"},
    ],
    "browser": {
        "type": "chrome",
        "tab_warn_gb": 2.0,
        "try_applescript_first": True,
        "max_tabs_to_close": 10,
        "never_kill_main": True,
    },
    "presence": {
        "present_idle_sec": 300,
        "away_idle_sec": 900,
        "present_notify_cooldown_min": 30,
        "away_notify_cooldown_min": 5,
    },
    "compressed_memory": {
        "watch_threshold_gb": 3.0,
        "warn_threshold_gb": 5.0,
        "crit_threshold_gb": 8.0,
        "purge_on_warn": True,
        "browser_tab_warn_gb": 2.0,
        "notify_cooldown_minutes": 15,
    },
    "orbstack": {
        "watch_threshold_gb": 3.5,
        "warn_threshold_gb": 5.0,
        "crit_threshold_gb": 7.0,
        "notify_cooldown_minutes": 120,
    },
}


def _load_config() -> dict:
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        full = json.loads(config_path.read_text())
        return full.get("guardian", {})
    return {}


def _get(cfg: dict, key: str):
    return cfg.get(key, DEFAULTS[key])


# ── Timing constants ──────────────────────────────────────────────────────────
_TIMEOUT_SHELL_CMD = 10  # seconds — ps/sysctl/vm_stat shell commands
_TIMEOUT_PURGE = 30  # seconds — sudo purge can be slow on large memory
_TIMEOUT_NOTIFY = 5  # seconds — terminal-notifier / osascript

_ENV = {**os.environ, "PATH": "/usr/sbin:/usr/bin:/bin:/sbin:" + os.environ.get("PATH", "")}


def _run(cmd: str) -> str:
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=_ENV,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _get_mem_level() -> int | None:
    out = _run("/usr/sbin/sysctl -n kern.memorystatus_level")
    if out and out.isdigit():
        return int(out)
    return None


def _get_compressed_memory_gb() -> dict:
    """Read compressed memory stats from vm_stat.

    Returns {occupied_gb, stored_gb} or {occupied_gb: 0, stored_gb: 0} on failure.
    """
    out = _run("vm_stat")
    if not out:
        return {"occupied_gb": 0.0, "stored_gb": 0.0}

    occupied_pages = 0
    stored_pages = 0
    for line in out.splitlines():
        if "occupied by compressor" in line:
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    occupied_pages = int(parts[1].strip().rstrip("."))
                except ValueError:
                    pass
        elif "stored in compressor" in line:
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    stored_pages = int(parts[1].strip().rstrip("."))
                except ValueError:
                    pass

    page_size = 16384  # Apple Silicon default
    ps_out = _run("pagesize")
    if ps_out and ps_out.isdigit():
        page_size = int(ps_out)

    return {
        "occupied_gb": round(occupied_pages * page_size / (1024**3), 2),
        "stored_gb": round(stored_pages * page_size / (1024**3), 2),
    }


def _get_user_idle_seconds() -> int:
    """Get user idle time from macOS HID system (no elevation needed).

    Reads HIDIdleTime from ioreg (value is in nanoseconds).
    Returns idle seconds, or -1 on failure.
    """
    out = _run("ioreg -c IOHIDSystem -r 2>/dev/null | grep HIDIdleTime")
    if not out:
        return -1
    match = re.search(r"=\s*(\d+)", out)
    if match:
        idle_ns = int(match.group(1))
        return idle_ns // 1_000_000_000
    return -1


def _get_browser_memory() -> dict:
    """Detect running browser and aggregate its memory usage.

    Returns {browser, total_gb, tab_count, main_alive}.
    Checks Chrome first, then Safari, then Firefox.
    """
    # Chrome
    chrome_renderers = _find_processes("Google Chrome Helper (Renderer)")
    if chrome_renderers:
        total_kb = sum(p["rss_kb"] for p in chrome_renderers)
        # Also add GPU and other helpers
        for pattern in (
            "Google Chrome Helper (GPU)",
            "Google Chrome Helper (Plugin)",
            "Google Chrome Helper (Utility)",
        ):
            for p in _find_processes(pattern):
                total_kb += p["rss_kb"]
        main_alive = len(_find_processes("/Applications/Google Chrome.app")) > 0
        return {
            "browser": "chrome",
            "total_gb": round(total_kb / (1024 * 1024), 2),
            "tab_count": len(chrome_renderers),
            "main_alive": main_alive,
        }

    # Safari
    safari_procs = _find_processes("com.apple.WebKit.WebContent")
    if safari_procs:
        total_kb = sum(p["rss_kb"] for p in safari_procs)
        for p in _find_processes("Safari"):
            total_kb += p["rss_kb"]
        return {
            "browser": "safari",
            "total_gb": round(total_kb / (1024 * 1024), 2),
            "tab_count": len(safari_procs),
            "main_alive": len(_find_processes("/Applications/Safari.app")) > 0,
        }

    # Firefox / Zen
    firefox_procs = _find_processes("plugin-container")
    if firefox_procs:
        total_kb = sum(p["rss_kb"] for p in firefox_procs)
        return {
            "browser": "firefox",
            "total_gb": round(total_kb / (1024 * 1024), 2),
            "tab_count": len(firefox_procs),
            "main_alive": True,
        }

    return {"browser": "none", "total_gb": 0.0, "tab_count": 0, "main_alive": False}


def _get_orbstack_rss_gb() -> dict:
    """Measure OrbStack Helper RSS (VM overhead + container memory).

    OrbStack VM memory cannot be shrunk without a full restart. This only
    reports; it never touches OrbStack (never_restart=True by design — prior
    incident: session-archiver write blocked when VM mem-limit was set).
    """
    total_kb = 0
    procs = 0
    for p in _find_processes("OrbStack Helper"):
        total_kb += p["rss_kb"]
        procs += 1
    return {
        "running": procs > 0,
        "rss_gb": round(total_kb / (1024 * 1024), 2),
        "helper_count": procs,
    }


def _close_chrome_tabs(max_close: int = 10) -> dict:
    """Use AppleScript to close inactive Chrome tabs (preserve active tab).

    Closes from the last tab backwards, skipping the active tab.
    Returns {closed: int, error: str|None}.
    """
    script = f"""
tell application "Google Chrome"
    set closedCount to 0
    repeat with w in windows
        set activeIdx to active tab index of w
        set tabCount to count of tabs of w
        set maxToClose to {max_close} - closedCount
        if maxToClose <= 0 then exit repeat
        -- Close from end, skip active tab
        repeat with i from tabCount to 1 by -1
            if i is not activeIdx and closedCount < {max_close} then
                close tab i of w
                set closedCount to closedCount + 1
            end if
        end repeat
    end repeat
    return closedCount
end tell
"""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
            env=_ENV,
        )
        if r.returncode == 0:
            closed = 0
            out = r.stdout.strip()
            if out.isdigit():
                closed = int(out)
            return {"closed": closed, "error": None}
        return {"closed": 0, "error": r.stderr.strip()[:200]}
    except subprocess.TimeoutExpired:
        return {"closed": 0, "error": "AppleScript timeout (15s)"}
    except Exception as e:
        return {"closed": 0, "error": str(e)[:200]}


def _get_top_memory_processes(top_n: int = 10) -> list[dict]:
    """Aggregate same-name processes by RSS, return top N."""
    out = _run("ps -eo rss=,comm=")
    if not out:
        return []

    agg: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            rss_kb = int(parts[0])
        except ValueError:
            continue
        name = parts[1].strip()
        base = name.rsplit("/", 1)[-1] if "/" in name else name
        agg[base] = agg.get(base, 0) + rss_kb

    ranked = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"name": name, "rss_mb": rss_kb // 1024} for name, rss_kb in ranked]


def _run_purge() -> bool:
    """Run sudo -n purge (non-interactive). Returns True on success."""
    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/sbin/purge"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_ENV,
        )
        return r.returncode == 0
    except Exception:
        return False


def _send_notification(title: str, message: str, group: str = "memory-guardian") -> bool:
    """Send macOS notification. terminal-notifier preferred, osascript fallback."""
    try:
        r = subprocess.run(
            ["terminal-notifier", "-title", title, "-message", message, "-group", group],
            capture_output=True,
            timeout=5,
        )
        if r.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Fallback: osascript
    try:
        escaped_msg = message.replace('"', '\\"')
        escaped_title = title.replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{escaped_msg}" with title "{escaped_title}"',
            ],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _find_processes(pattern: str) -> list[dict]:
    """Find processes matching pattern in command column, sorted by RSS desc."""
    out = _run("ps -eo pid=,rss=,command=")
    if not out:
        return []

    results = []
    for line in out.splitlines():
        if pattern not in line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            rss_kb = int(parts[1])
        except ValueError:
            continue
        results.append({"pid": pid, "rss_kb": rss_kb})

    results.sort(key=lambda x: x["rss_kb"], reverse=True)
    return results


def _get_process_info(pid: int) -> dict | None:
    """Get CPU%, RSS, command, start time for a process."""
    out = _run(f"ps -o %cpu=,rss=,lstart=,command= -p {pid}")
    if not out:
        return None
    parts = out.split(None, 3)
    if len(parts) < 2:
        return None
    try:
        cpu = float(parts[0])
        rss_kb = int(parts[1])
    except ValueError:
        return None
    return {"cpu": cpu, "rss_kb": rss_kb, "raw": out}


def _get_process_age(pid: int) -> int:
    """Get process age in seconds. Returns 9999 if unknown."""
    out = _run(f"ps -o lstart= -p {pid}")
    if not out:
        return 9999
    try:
        start = datetime.strptime(out.strip(), "%c")
        return int(time.time() - start.timestamp())
    except Exception:
        return 9999


def _kill_term(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def _kill_force(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _check_cooldown(cooldown_path: Path, cooldown_min: int) -> bool:
    """Return True if cooldown has expired (OK to notify). Updates timestamp if expired."""
    if cooldown_path.exists():
        try:
            last_notify = float(cooldown_path.read_text().strip())
            if time.time() - last_notify < cooldown_min * 60:
                return False
        except (ValueError, OSError):
            pass
    try:
        cooldown_path.write_text(str(time.time()))
    except OSError:
        pass
    return True


class MemoryGuardian:
    def __init__(self, config: dict | None = None):
        self.cfg = config if config is not None else _load_config()
        self.log_dir = Path(self.cfg.get("log_dir", "~/.claude/data/system-monitor")).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "memory-guardian.log"
        self.lines: list[str] = []

    def _log(self, msg: str):
        self.lines.append(msg)
        logger.info(msg)

    def _flush_log(self):
        """Append buffered lines to log file, with rotation."""
        max_bytes = _get(self.cfg, "log_max_bytes")
        retain = _get(self.cfg, "log_retain_lines")

        if self.log_path.exists():
            try:
                if self.log_path.stat().st_size > max_bytes:
                    old = self.log_path.read_text().splitlines()
                    self.log_path.write_text("\n".join(old[-retain:]) + "\n")
            except OSError:
                pass

        with self.log_path.open("a") as f:
            for line in self.lines:
                f.write(line + "\n")
            f.write("---\n")

    def _write_status(
        self, mem_level: int, status: str, compressed_gb: float = 0.0, user_idle: int = -1
    ):
        """Always write guardian-status.json so the frontend can show heartbeat."""
        status_path = self.log_dir / "guardian-status.json"
        try:
            status_path.write_text(
                json.dumps(
                    {
                        "last_checked": datetime.now().isoformat(),
                        "mem_level": mem_level,
                        "status": status,
                        "compressed_gb": compressed_gb,
                        "user_idle_sec": user_idle,
                    },
                    ensure_ascii=False,
                )
            )
        except OSError:
            pass

    def _get_presence(self, user_idle: int) -> str:
        """Classify user presence based on idle time."""
        presence_cfg = self.cfg.get("presence", DEFAULTS["presence"])
        present_sec = presence_cfg.get("present_idle_sec", 300)
        away_sec = presence_cfg.get("away_idle_sec", 900)

        if user_idle < 0:
            return "unknown"
        if user_idle < present_sec:
            return "present"
        if user_idle < away_sec:
            return "brief_away"
        return "away"

    def _get_notify_cooldown_min(self, presence: str) -> int:
        """Get notification cooldown based on presence state."""
        presence_cfg = self.cfg.get("presence", DEFAULTS["presence"])
        if presence == "present":
            return presence_cfg.get("present_notify_cooldown_min", 30)
        return presence_cfg.get("away_notify_cooldown_min", 5)

    def _browser_action(self, presence: str, browser_info: dict, is_crit: bool) -> dict:
        """Handle browser memory based on presence state.

        Returns {action, details}.
        """
        browser_cfg = self.cfg.get("browser", DEFAULTS["browser"])
        browser = browser_info["browser"]
        total_gb = browser_info["total_gb"]
        tab_count = browser_info["tab_count"]

        result = {
            "action": "none",
            "browser": browser,
            "total_gb": total_gb,
            "tab_count": tab_count,
        }

        if browser == "none" or total_gb < browser_cfg.get("tab_warn_gb", 2.0):
            return result

        cooldown_min = self._get_notify_cooldown_min(presence)
        cooldown_path = self.log_dir / ".browser_notify_cooldown"

        if is_crit:
            # CRIT: always kill renderers regardless of presence (but never main process)
            result["action"] = "kill_renderers"
            killed, freed = self._kill_browser_renderers(browser)
            result["killed"] = killed
            result["freed_mb"] = freed
            msg = f"記憶體緊急 — 已終止 {killed} 個 {browser} 分頁程序，釋放 ~{freed}MB"
            _send_notification("Memory Guardian ⚠️", msg, group="browser-crit")
            self._log(f"  BROWSER CRIT: killed {killed} renderers, freed {freed}MB")
            return result

        if presence == "present":
            # Only notify, don't kill
            if _check_cooldown(cooldown_path, cooldown_min):
                msg = f"Chrome 佔用 {total_gb}GB ({tab_count} tabs)\n記憶體偏高，建議關閉分頁"
                _send_notification("Memory Guardian", msg, group="browser-memory")
                result["action"] = "notify_only"
                self._log(f"  BROWSER PRESENT: {total_gb}GB, notified (cooldown {cooldown_min}min)")
            else:
                result["action"] = "cooldown_active"
                self._log(f"  BROWSER PRESENT: {total_gb}GB, cooldown active")
            return result

        if presence == "brief_away":
            # Try AppleScript to close inactive tabs
            if browser == "chrome" and browser_cfg.get("try_applescript_first", True):
                max_close = browser_cfg.get("max_tabs_to_close", 10)
                tab_result = _close_chrome_tabs(max_close)
                closed = tab_result["closed"]
                if closed > 0:
                    msg = f"已關閉 {closed} 個 Chrome 背景分頁"
                    _send_notification("Memory Guardian", msg, group="browser-tabs")
                    result["action"] = "close_tabs"
                    result["closed"] = closed
                    self._log(f"  BROWSER BRIEF_AWAY: closed {closed} tabs via AppleScript")
                elif tab_result["error"]:
                    self._log(f"  BROWSER BRIEF_AWAY: AppleScript failed: {tab_result['error']}")
                    result["action"] = "applescript_failed"
                else:
                    self._log("  BROWSER BRIEF_AWAY: no tabs to close")
                    result["action"] = "no_tabs"
            else:
                # Non-Chrome or AppleScript disabled: just notify
                if _check_cooldown(cooldown_path, cooldown_min):
                    msg = f"{browser} 佔用 {total_gb}GB ({tab_count} tabs) — 記憶體偏高"
                    _send_notification("Memory Guardian", msg, group="browser-memory")
                    result["action"] = "notify_only"
            return result

        # presence == "away" or "unknown"
        if browser == "chrome" and browser_cfg.get("try_applescript_first", True):
            # Try closing tabs first, then kill renderers if still high
            max_close = browser_cfg.get("max_tabs_to_close", 10)
            tab_result = _close_chrome_tabs(max_close)
            closed = tab_result["closed"]
            if closed > 0:
                self._log(f"  BROWSER AWAY: closed {closed} tabs via AppleScript")
                result["closed"] = closed
                # Re-check browser memory after closing tabs
                time.sleep(1)
                browser_after = _get_browser_memory()
                if browser_after["total_gb"] < browser_cfg.get("tab_warn_gb", 2.0):
                    after_gb = browser_after["total_gb"]
                    msg = f"已關閉 {closed} 個 Chrome 背景分頁，記憶體已降至 {after_gb}GB"
                    _send_notification("Memory Guardian", msg, group="browser-tabs")
                    result["action"] = "close_tabs"
                    return result

        # Still high or non-Chrome: kill renderers
        killed, freed = self._kill_browser_renderers(browser)
        result["action"] = "kill_renderers"
        result["killed"] = killed
        result["freed_mb"] = freed
        total_closed = result.get("closed", 0)
        msg_parts = []
        if total_closed > 0:
            msg_parts.append(f"關閉 {total_closed} 個分頁")
        if killed > 0:
            msg_parts.append(f"終止 {killed} 個分頁程序，釋放 ~{freed}MB")
        if msg_parts:
            msg = "已" + "、".join(msg_parts)
            _send_notification("Memory Guardian", msg, group="browser-cleanup")
        self._log(f"  BROWSER AWAY: killed {killed} renderers, freed {freed}MB")
        return result

    def _kill_browser_renderers(self, browser: str) -> tuple[int, int]:
        """Kill browser renderer processes (never the main process).

        Returns (killed_count, freed_mb).
        """
        patterns = {
            "chrome": ["Google Chrome Helper (Renderer)", "Google Chrome Helper (GPU)"],
            "safari": ["com.apple.WebKit.WebContent"],
            "firefox": ["plugin-container"],
        }
        killed = 0
        freed_mb = 0
        for pattern in patterns.get(browser, []):
            for proc in _find_processes(pattern):
                pid = proc["pid"]
                mem_mb = proc["rss_kb"] // 1024
                if _kill_term(pid):
                    self._log(f"  KILL {browser} renderer PID {pid} ({mem_mb}MB)")
                    killed += 1
                    freed_mb += mem_mb
        return killed, freed_mb

    def orbstack_check(self, user_idle: int = -1) -> dict:
        """Observe OrbStack Helper RSS — notify only, never restart.

        Why no auto-restart: setting VM mem-limit once broke session-archiver
        writes (Postgres WAL/IO stalls). OrbStack restart must be human-gated
        to avoid colliding with scheduled DB writes. See docs/orb-maintenance.
        """
        orb_cfg = self.cfg.get("orbstack", DEFAULTS.get("orbstack", {}))
        watch_gb = orb_cfg.get("watch_threshold_gb", 3.5)
        warn_gb = orb_cfg.get("warn_threshold_gb", 5.0)
        crit_gb = orb_cfg.get("crit_threshold_gb", 7.0)
        cooldown_min = orb_cfg.get("notify_cooldown_minutes", 120)

        info = _get_orbstack_rss_gb()
        result = {
            "status": "ok",
            "running": info["running"],
            "rss_gb": info["rss_gb"],
            "thresholds": {"watch": watch_gb, "warn": warn_gb, "crit": crit_gb},
        }
        if not info["running"] or info["rss_gb"] < watch_gb:
            return result

        rss = info["rss_gb"]
        level = "crit" if rss >= crit_gb else ("warn" if rss >= warn_gb else "watch")
        result["status"] = level

        ts = datetime.now().strftime("%m/%d %H:%M:%S")
        self._log(
            f"[{ts}] ORBSTACK {level.upper()}: helper_rss={rss}GB "
            f"(watch={watch_gb} warn={warn_gb} crit={crit_gb})"
        )

        if level in ("warn", "crit"):
            cooldown_path = Path(_get(self.cfg, "log_dir")).expanduser() / ".orb_notify_cooldown"
            if _check_cooldown(cooldown_path, cooldown_min):
                hint = "手動執行 ~/workshop/stations/system-monitor/orb-maintenance.sh"
                msg = f"OrbStack Helper {rss}GB ≥ {warn_gb}GB\n建議找安靜時段{hint}"
                _send_notification(f"OrbStack 記憶體{level.upper()}", msg, "orbstack")
                cooldown_path.parent.mkdir(parents=True, exist_ok=True)
                cooldown_path.write_text(str(time.time()))
                result["notified"] = True

        return result

    def compressed_sweep(self, user_idle: int = -1) -> dict:
        """Orthogonal sweep for compressed memory pressure (independent of P0-P3).

        Compressed memory is a separate dimension from kern.memorystatus_level.
        macOS kernel manages it; userspace can only: (1) purge file cache, (2) kill processes.
        """
        cm_cfg = self.cfg.get("compressed_memory", DEFAULTS["compressed_memory"])
        watch_gb = cm_cfg.get("watch_threshold_gb", 3.0)
        warn_gb = cm_cfg.get("warn_threshold_gb", 5.0)
        crit_gb = cm_cfg.get("crit_threshold_gb", 8.0)
        purge_on_warn = cm_cfg.get("purge_on_warn", True)
        browser_warn_gb = cm_cfg.get("browser_tab_warn_gb", 2.0)
        compressed = _get_compressed_memory_gb()
        occupied_gb = compressed["occupied_gb"]

        presence = self._get_presence(user_idle)

        result = {
            "status": "ok",
            "occupied_gb": occupied_gb,
            "stored_gb": compressed["stored_gb"],
            "thresholds": {"watch": watch_gb, "warn": warn_gb, "crit": crit_gb},
            "presence": presence,
            "actions": [],
        }

        if occupied_gb < watch_gb:
            return result

        # ── Watch threshold crossed: gather diagnostics ──
        ts = datetime.now().strftime("%m/%d %H:%M:%S")
        self._log(
            f"[{ts}] COMPRESSED WATCH: occupied={occupied_gb}GB "
            f"(watch={watch_gb} warn={warn_gb} crit={crit_gb}) presence={presence}"
        )
        result["status"] = "watch"

        top_procs = _get_top_memory_processes(10)
        result["top_processes"] = top_procs
        self._log(
            f"  Top memory: {', '.join(f'{p["name"]}({p["rss_mb"]}MB)' for p in top_procs[:5])}"
        )

        # Browser memory check (presence-aware)
        browser_info = _get_browser_memory()
        result["browser_memory"] = browser_info

        if browser_info["total_gb"] >= browser_warn_gb:
            is_crit = occupied_gb >= crit_gb
            browser_result = self._browser_action(presence, browser_info, is_crit)
            result["actions"].append({"action": "browser", **browser_result})

        # ── Warn threshold: purge + expendable fallback ──
        if occupied_gb >= warn_gb:
            result["status"] = "warn"
            self._log(f"  COMPRESSED WARN: {occupied_gb}GB >= {warn_gb}GB")

            if purge_on_warn:
                purge_ok = _run_purge()
                self._log(
                    f"  COMPRESSED PURGE: {'success' if purge_ok else 'failed (check sudoers)'}"
                )
                result["actions"].append({"action": "purge", "success": purge_ok})

                if purge_ok and presence in ("away", "unknown"):
                    # Only kill expendables when user is away
                    mem_level_after = _get_mem_level()
                    warn_th = _get(self.cfg, "warn_threshold")
                    if mem_level_after is not None and mem_level_after < warn_th:
                        self._log(
                            f"  COMPRESSED FALLBACK: mem_level={mem_level_after} still < "
                            f"warn={warn_th}, killing expendables (user away)"
                        )
                        exp_killed, exp_freed = self._kill_expendables(
                            skip_browser=(presence != "away")
                        )
                        result["actions"].append(
                            {
                                "action": "expendable_fallback",
                                "killed": exp_killed,
                                "freed_mb": exp_freed,
                            }
                        )
                        self._log(f"  COMPRESSED FALLBACK: killed={exp_killed} freed={exp_freed}MB")

        # ── Crit threshold: macOS notification ──
        if occupied_gb >= crit_gb:
            result["status"] = "crit"
            msg = (
                f"壓縮記憶體 {occupied_gb}GB 超過臨界值 {crit_gb}GB\n"
                f"系統可能不穩定，建議重啟或手動關閉應用程式"
            )
            _send_notification("Memory Guardian ⚠️", msg, group="compressed-crit")
            self._log(f"  COMPRESSED CRIT: {occupied_gb}GB >= {crit_gb}GB — notified")
            result["actions"].append({"action": "crit_notification", "occupied_gb": occupied_gb})

        return result

    def _kill_expendables(self, skip_browser: bool = False) -> tuple[int, int]:
        """Kill expendable processes. Returns (killed_count, freed_mb).

        If skip_browser=True, skip entries marked with browser=True.
        """
        expendables = _get(self.cfg, "expendables")
        killed = 0
        freed_mb = 0
        for entry in expendables:
            if skip_browser and entry.get("browser"):
                continue
            pattern = entry["pattern"]
            label = entry["label"]
            procs = _find_processes(pattern)
            for proc in procs:
                pid = proc["pid"]
                mem_mb = proc["rss_kb"] // 1024
                if _kill_term(pid):
                    self._log(f"  KILL {label} PID {pid} ({mem_mb}MB)")
                    killed += 1
                    freed_mb += mem_mb
        return killed, freed_mb

    def run(self) -> dict:
        """Execute memory guardian check. Returns summary dict."""
        mem_level = _get_mem_level()
        if mem_level is None:
            return {"status": "skip", "reason": "cannot read memorystatus_level"}

        # ── User presence detection ──
        user_idle = _get_user_idle_seconds()
        presence = self._get_presence(user_idle)

        warn_th = _get(self.cfg, "warn_threshold")
        crit_th = _get(self.cfg, "crit_threshold")

        result = {
            "status": "ok",
            "mem_level": mem_level,
            "warn_threshold": warn_th,
            "crit_threshold": crit_th,
            "user_idle_sec": user_idle,
            "presence": presence,
            "p0_killed": 0,
            "p0_freed_mb": 0,
            "p1_killed": 0,
            "p1_freed_mb": 0,
            "p2_killed": 0,
            "p3_killed": 0,
            "kills": [],
        }

        # ═══ P0: Stale Playwright headless Chrome (relaxed threshold) ═══
        p0_offset = _get(self.cfg, "p0_threshold_offset")
        p0_threshold = warn_th + p0_offset
        stale_age = _get(self.cfg, "p0_age_seconds")

        if mem_level < p0_threshold:
            ts = datetime.now().strftime("%m/%d %H:%M:%S")
            self._log(
                f"[{ts}] P0 CHECK: level={mem_level} (P0<{p0_threshold}) "
                f"idle={user_idle}s presence={presence}"
            )
            self._log("  --- P0: Stale headless Chrome ---")
            headless = _find_processes("--headless")
            for proc in headless:
                pid = proc["pid"]
                age = _get_process_age(pid)
                if age > stale_age:
                    mem_mb = proc["rss_kb"] // 1024
                    if _kill_term(pid):
                        self._log(f"  KILL Headless Chrome PID {pid} (age:{age}s {mem_mb}MB)")
                        result["p0_killed"] += 1
                        result["p0_freed_mb"] += mem_mb
                        result["kills"].append(
                            {
                                "phase": "P0",
                                "process": "Headless Chrome (stale)",
                                "pid": pid,
                                "mem_mb": mem_mb,
                            }
                        )
            self._log(f"  P0 result: killed={result['p0_killed']} freed={result['p0_freed_mb']}MB")

            # Clean stale Playwright temp dirs
            for d in glob.glob("/tmp/pw-*"):
                try:
                    mtime = os.path.getmtime(d)
                    if time.time() - mtime > stale_age:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass

        # OrbStack check runs unconditionally (orthogonal to mem pressure)
        result["orbstack"] = self.orbstack_check(user_idle)

        if mem_level > warn_th:
            # Memory OK — still run compressed sweep (orthogonal dimension)
            cm_result = self.compressed_sweep(user_idle)
            result["compressed_memory"] = cm_result
            compressed_gb = cm_result.get("occupied_gb", 0.0)

            if result["p0_killed"] > 0:
                result["status"] = "acted"
                result["total_killed"] = result["p0_killed"]
                self._write_status(mem_level, "acted", compressed_gb, user_idle)
                self._flush_log()
            else:
                self._write_status(mem_level, "ok", compressed_gb, user_idle)
            return result

        ts = datetime.now().strftime("%m/%d %H:%M:%S")
        self._log(
            f"[{ts}] PRESSURE: level={mem_level} (WARN<{warn_th} CRIT<{crit_th}) "
            f"idle={user_idle}s presence={presence}"
        )

        # ═══ P1: Expendable apps (WARN threshold, presence-aware) ═══
        is_crit = mem_level < crit_th

        if presence == "present" and not is_crit:
            # User is here — only notify about browser, don't kill anything
            self._log("  --- P1: User PRESENT — notify only, skip expendable kills ---")
            browser_info = _get_browser_memory()
            if browser_info["total_gb"] > 0:
                browser_result = self._browser_action(presence, browser_info, False)
                result["kills"].append(
                    {"phase": "P1", "process": "browser_notify", **browser_result}
                )
        elif presence == "brief_away" and not is_crit:
            # User briefly away — try AppleScript tabs, don't kill processes
            self._log("  --- P1: User BRIEF_AWAY — close tabs, skip process kills ---")
            browser_info = _get_browser_memory()
            if browser_info["total_gb"] > 0:
                browser_result = self._browser_action(presence, browser_info, False)
                result["kills"].append({"phase": "P1", "process": "browser_tabs", **browser_result})
        else:
            # User away OR CRIT — full P1 kill logic
            self._log(f"  --- P1: Expendable apps (presence={presence}, crit={is_crit}) ---")

            # Browser action first (respects try_applescript_first)
            browser_info = _get_browser_memory()
            if browser_info["total_gb"] > 0:
                browser_result = self._browser_action(
                    "away" if is_crit else presence, browser_info, is_crit
                )
                result["kills"].append({"phase": "P1", "process": "browser", **browser_result})
                result["p1_killed"] += browser_result.get("killed", 0)
                result["p1_freed_mb"] += browser_result.get("freed_mb", 0)

            # Non-browser expendables
            exp_killed, exp_freed = self._kill_expendables(skip_browser=True)
            result["p1_killed"] += exp_killed
            result["p1_freed_mb"] += exp_freed

        self._log(f"  P1 result: killed={result['p1_killed']} freed={result['p1_freed_mb']}MB")

        # ═══ P2: Idle Claude Code (CRIT threshold) ═══
        idle_cpu = _get(self.cfg, "idle_cpu")
        min_age = _get(self.cfg, "min_age_seconds")
        grace = _get(self.cfg, "grace_seconds")

        claude_pids = _run("pgrep -x claude").splitlines()
        active_pids = []
        idle_pids = []

        for pid_str in claude_pids:
            if not pid_str.strip():
                continue
            pid = int(pid_str.strip())
            info = _get_process_info(pid)
            if not info:
                continue

            mem_mb = info["rss_kb"] // 1024
            cpu = info["cpu"]
            age = _get_process_age(pid)

            if age < min_age:
                continue

            if cpu < idle_cpu:
                idle_pids.append((pid, cpu, mem_mb))
            else:
                active_pids.append((pid, cpu, mem_mb))

        if is_crit:
            self._log("  --- P2: Idle Claude Code (CRIT mode) ---")
            for pid, cpu, mem_mb in idle_pids:
                if _kill_term(pid):
                    self._log(f"  P2 KILL Claude PID {pid} (idle CPU:{cpu}% MEM:{mem_mb}MB)")
                    result["p2_killed"] += 1
                    result["kills"].append(
                        {
                            "phase": "P2",
                            "process": "Claude Code (idle)",
                            "pid": pid,
                            "mem_mb": mem_mb,
                        }
                    )
            self._log(f"  P2 result: idle_killed={result['p2_killed']}")
        else:
            if idle_pids:
                self._log(
                    f"  P2: SKIPPED — {len(idle_pids)} idle Claude protected "
                    f"(level={mem_level} >= CRIT={crit_th})"
                )

        # ═══ P3: Active Claude Code (CRIT only) ═══
        if is_crit:
            self._log("  --- P3: Active Claude Code (CRIT mode) ---")
            for pid, cpu, mem_mb in active_pids:
                if _kill_term(pid):
                    self._log(
                        f"  P3 TERM Claude PID {pid} (active CPU:{cpu}% MEM:{mem_mb}MB) "
                        f"grace={grace}s"
                    )
                    result["p3_killed"] += 1
                    result["kills"].append(
                        {
                            "phase": "P3",
                            "process": "Claude Code (active)",
                            "pid": pid,
                            "mem_mb": mem_mb,
                        }
                    )
                    # Fork a delayed force-kill
                    if os.fork() == 0:
                        time.sleep(grace)
                        if _pid_alive(pid):
                            _kill_force(pid)
                            with self.log_path.open("a") as f:
                                fts = datetime.now().strftime("%m/%d %H:%M:%S")
                                f.write(f"[{fts}] P3 FORCE-KILL Claude PID {pid}\n")
                        os._exit(0)
            self._log(f"  P3 result: active_killed={result['p3_killed']}")
        else:
            if active_pids:
                self._log(
                    f"  P3: SKIPPED — {len(active_pids)} active Claude protected "
                    f"(WARN only, need CRIT<{crit_th})"
                )

        total_killed = (
            result["p0_killed"] + result["p1_killed"] + result["p2_killed"] + result["p3_killed"]
        )
        total_freed = result["p0_freed_mb"] + result["p1_freed_mb"]
        self._log(f"[{ts}] DONE: total_killed={total_killed} freed≈{total_freed}MB")

        result["status"] = "acted"
        result["total_killed"] = total_killed

        # ═══ Compressed memory sweep (orthogonal to P0-P3) ═══
        cm_result = self.compressed_sweep(user_idle)
        result["compressed_memory"] = cm_result
        compressed_gb = cm_result.get("occupied_gb", 0.0)

        self._write_status(mem_level, "acted", compressed_gb, user_idle)
        self._flush_log()
        return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    guardian = MemoryGuardian()
    result = guardian.run()
    if result["status"] == "ok":
        idle = result.get("user_idle_sec", -1)
        presence = result.get("presence", "?")
        print(f"Memory OK (level={result['mem_level']} idle={idle}s presence={presence})")
    elif result["status"] == "acted":
        total_freed = result.get("p0_freed_mb", 0) + result.get("p1_freed_mb", 0)
        print(
            f"Guardian acted: level={result['mem_level']} "
            f"presence={result.get('presence', '?')} "
            f"killed={result.get('total_killed', 0)} "
            f"freed≈{total_freed}MB"
        )
    else:
        print(f"Skip: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    main()
