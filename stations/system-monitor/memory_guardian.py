"""
Memory Guardian — 記憶體壓力防護（優先保護 Claude Code）

殺進程優先順序（先殺不重要的，保住工作工具）：
  P0: Stale Playwright headless Chrome (age > 10min, relaxed threshold)
  P1: Chrome 分頁、LINE、VS Code、Antigravity 等可犧牲的 app
  P2: 閒置的 Claude Code (CPU < 1%) — CRIT 才觸發，idle 也有保留 context 的價值
  P3: 忙碌的 Claude Code（CRIT 才觸發，最後手段，給 grace period）

可獨立執行：python memory_guardian.py
也可由 system-monitor API 觸發。
"""

from __future__ import annotations

import json
import logging
import os
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
        {"pattern": "Google Chrome Helper (Renderer)", "label": "Chrome 分頁"},
        {"pattern": "/Applications/Google Chrome.app", "label": "Google Chrome"},
        {"pattern": "plugin-container", "label": "Zen 分頁"},
        {"pattern": "/Applications/Zen Browser.app", "label": "Zen Browser"},
        {"pattern": "LINE", "label": "LINE"},
        {"pattern": "LineCall", "label": "LINE Call"},
        {"pattern": "Visual Studio Code", "label": "VS Code"},
        {"pattern": "Antigravity", "label": "Antigravity"},
        {"pattern": "openclaw-gateway", "label": "OpenClaw"},
        {"pattern": "AltServer", "label": "AltServer"},
    ],
    "compressed_memory": {
        "watch_threshold_gb": 3.0,
        "warn_threshold_gb": 5.0,
        "crit_threshold_gb": 8.0,
        "purge_on_warn": True,
        "safari_tab_warn_gb": 2.0,
        "notify_cooldown_minutes": 15,
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


def _get_safari_memory() -> dict:
    """Aggregate RSS of Safari + WebKit.WebContent processes.

    Returns {total_gb, process_count}.
    """
    total_kb = 0
    count = 0
    for pattern in ("Safari", "com.apple.WebKit.WebContent"):
        for proc in _find_processes(pattern):
            total_kb += proc["rss_kb"]
            count += 1
    return {
        "total_gb": round(total_kb / (1024 * 1024), 2),
        "process_count": count,
    }


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
        # Use basename for readability
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
        # macOS lstart format: "Tue Mar  4 10:23:45 2026"
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

    def _write_status(self, mem_level: int, status: str, compressed_gb: float = 0.0):
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
                    },
                    ensure_ascii=False,
                )
            )
        except OSError:
            pass

    def compressed_sweep(self) -> dict:
        """Orthogonal sweep for compressed memory pressure (independent of P0-P3).

        Compressed memory is a separate dimension from kern.memorystatus_level.
        macOS kernel manages it; userspace can only: (1) purge file cache, (2) kill processes.
        """
        cm_cfg = self.cfg.get("compressed_memory", DEFAULTS["compressed_memory"])
        watch_gb = cm_cfg.get("watch_threshold_gb", 3.0)
        warn_gb = cm_cfg.get("warn_threshold_gb", 5.0)
        crit_gb = cm_cfg.get("crit_threshold_gb", 8.0)
        purge_on_warn = cm_cfg.get("purge_on_warn", True)
        safari_warn_gb = cm_cfg.get("safari_tab_warn_gb", 2.0)
        cooldown_min = cm_cfg.get("notify_cooldown_minutes", 15)

        compressed = _get_compressed_memory_gb()
        occupied_gb = compressed["occupied_gb"]

        result = {
            "status": "ok",
            "occupied_gb": occupied_gb,
            "stored_gb": compressed["stored_gb"],
            "thresholds": {"watch": watch_gb, "warn": warn_gb, "crit": crit_gb},
            "actions": [],
        }

        if occupied_gb < watch_gb:
            return result

        # ── Watch threshold crossed: gather diagnostics ──
        ts = datetime.now().strftime("%m/%d %H:%M:%S")
        self._log(
            f"[{ts}] COMPRESSED WATCH: occupied={occupied_gb}GB "
            f"(watch={watch_gb} warn={warn_gb} crit={crit_gb})"
        )
        result["status"] = "watch"

        top_procs = _get_top_memory_processes(10)
        result["top_processes"] = top_procs
        self._log(
            f"  Top memory: {', '.join(f'{p["name"]}({p["rss_mb"]}MB)' for p in top_procs[:5])}"
        )

        safari = _get_safari_memory()
        result["safari_memory"] = safari

        # Safari high-memory notification (never kill, only notify)
        if safari["total_gb"] >= safari_warn_gb:
            cooldown_path = self.log_dir / ".safari_notify_cooldown"
            should_notify = True
            if cooldown_path.exists():
                try:
                    last_notify = float(cooldown_path.read_text().strip())
                    if time.time() - last_notify < cooldown_min * 60:
                        should_notify = False
                except (ValueError, OSError):
                    pass

            if should_notify:
                msg = (
                    f"Safari 佔用 {safari['total_gb']}GB ({safari['process_count']} processes)\n"
                    f"壓縮記憶體 {occupied_gb}GB — 考慮關閉分頁"
                )
                _send_notification("Memory Guardian", msg, group="safari-memory")
                self._log(f"  COMPRESSED SAFARI WARN: {safari['total_gb']}GB, notified")
                result["actions"].append(
                    {"action": "safari_notification", "safari_gb": safari["total_gb"]}
                )
                try:
                    cooldown_path.write_text(str(time.time()))
                except OSError:
                    pass
            else:
                self._log(
                    f"  COMPRESSED SAFARI: {safari['total_gb']}GB (cooldown active, skipped notify)"
                )

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

                if purge_ok:
                    # Re-check memory level after purge
                    mem_level_after = _get_mem_level()
                    warn_th = _get(self.cfg, "warn_threshold")
                    if mem_level_after is not None and mem_level_after < warn_th:
                        # Memory still tight — fall back to P1 expendable cleanup
                        self._log(
                            f"  COMPRESSED FALLBACK: mem_level={mem_level_after} still < "
                            f"warn={warn_th}, killing expendables"
                        )
                        expendables = _get(self.cfg, "expendables")
                        exp_killed = 0
                        exp_freed_mb = 0
                        for entry in expendables:
                            pattern = entry["pattern"]
                            label = entry["label"]
                            procs = _find_processes(pattern)
                            for proc in procs:
                                pid = proc["pid"]
                                mem_mb = proc["rss_kb"] // 1024
                                if _kill_term(pid):
                                    self._log(f"  COMPRESSED KILL {label} PID {pid} ({mem_mb}MB)")
                                    exp_killed += 1
                                    exp_freed_mb += mem_mb
                        result["actions"].append(
                            {
                                "action": "expendable_fallback",
                                "killed": exp_killed,
                                "freed_mb": exp_freed_mb,
                            }
                        )
                        self._log(
                            f"  COMPRESSED FALLBACK result: killed={exp_killed} freed={exp_freed_mb}MB"
                        )

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

    def run(self) -> dict:
        """Execute memory guardian check. Returns summary dict."""
        mem_level = _get_mem_level()
        if mem_level is None:
            return {"status": "skip", "reason": "cannot read memorystatus_level"}

        warn_th = _get(self.cfg, "warn_threshold")
        crit_th = _get(self.cfg, "crit_threshold")

        result = {
            "status": "ok",
            "mem_level": mem_level,
            "warn_threshold": warn_th,
            "crit_threshold": crit_th,
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
            self._log(f"[{ts}] P0 CHECK: level={mem_level} (P0<{p0_threshold})")
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
            import glob
            import shutil

            for d in glob.glob("/tmp/pw-*"):
                try:
                    mtime = os.path.getmtime(d)
                    if time.time() - mtime > stale_age:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass

        if mem_level > warn_th:
            # P0-only scenario (level between warn_th and p0_threshold)
            # Still run compressed sweep (orthogonal dimension)
            cm_result = self.compressed_sweep()
            result["compressed_memory"] = cm_result
            compressed_gb = cm_result.get("occupied_gb", 0.0)

            if result["p0_killed"] > 0:
                result["status"] = "acted"
                result["total_killed"] = result["p0_killed"]
                self._write_status(mem_level, "acted", compressed_gb)
                self._flush_log()
            else:
                self._write_status(mem_level, "ok", compressed_gb)
            return result

        ts = datetime.now().strftime("%m/%d %H:%M:%S")
        self._log(f"[{ts}] PRESSURE: level={mem_level} (WARN<{warn_th} CRIT<{crit_th})")

        # ═══ P1: Expendable apps (WARN threshold) ═══
        self._log("  --- P1: Expendable apps ---")
        expendables = _get(self.cfg, "expendables")

        for entry in expendables:
            pattern = entry["pattern"]
            label = entry["label"]
            procs = _find_processes(pattern)

            for proc in procs:
                pid = proc["pid"]
                mem_mb = proc["rss_kb"] // 1024
                if _kill_term(pid):
                    self._log(f"  KILL {label} PID {pid} ({mem_mb}MB)")
                    result["p1_killed"] += 1
                    result["p1_freed_mb"] += mem_mb
                    result["kills"].append(
                        {
                            "phase": "P1",
                            "process": label,
                            "pid": pid,
                            "mem_mb": mem_mb,
                        }
                    )

        self._log(f"  P1 result: killed={result['p1_killed']} freed={result['p1_freed_mb']}MB")

        # ═══ P2: Idle Claude Code (CRIT threshold — idle 也有保留 context 的價值) ═══
        idle_cpu = _get(self.cfg, "idle_cpu")
        min_age = _get(self.cfg, "min_age_seconds")
        grace = _get(self.cfg, "grace_seconds")

        claude_pids = _run("pgrep -x claude").splitlines()
        active_pids = []  # collect busy pids for P3
        idle_pids = []  # collect idle pids for P2

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

        # P2 只在 CRIT 時才殺 idle Claude
        if mem_level < crit_th:
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

        # ═══ P3: Active Claude Code (CRIT only — 正在工作的才需要最高保護) ═══
        if mem_level < crit_th:
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
                    f"  P3: SKIPPED — {len(active_pids)} active Claude protected (WARN only, need CRIT<{crit_th})"
                )

        total_killed = (
            result["p0_killed"] + result["p1_killed"] + result["p2_killed"] + result["p3_killed"]
        )
        total_freed = result["p0_freed_mb"] + result["p1_freed_mb"]
        self._log(f"[{ts}] DONE: total_killed={total_killed} freed≈{total_freed}MB")

        result["status"] = "acted"
        result["total_killed"] = total_killed

        # ═══ Compressed memory sweep (orthogonal to P0-P3) ═══
        cm_result = self.compressed_sweep()
        result["compressed_memory"] = cm_result
        compressed_gb = cm_result.get("occupied_gb", 0.0)

        self._write_status(mem_level, "acted", compressed_gb)
        self._flush_log()
        return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    guardian = MemoryGuardian()
    result = guardian.run()
    if result["status"] == "ok":
        print(f"Memory OK (level={result['mem_level']})")
    elif result["status"] == "acted":
        total_freed = result.get("p0_freed_mb", 0) + result.get("p1_freed_mb", 0)
        print(
            f"Guardian acted: level={result['mem_level']} "
            f"killed={result.get('total_killed', 0)} "
            f"freed≈{total_freed}MB"
        )
    else:
        print(f"Skip: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    main()
