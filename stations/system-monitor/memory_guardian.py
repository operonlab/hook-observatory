"""
Memory Guardian — 記憶體壓力防護（優先保護 Claude Code）

殺進程優先順序（先殺不重要的，保住工作工具）：
  P1: Chrome 分頁、LINE、VS Code、Antigravity 等可犧牲的 app
  P2: 閒置的 Claude Code (CPU < 1%)
  P3: 忙碌的 Claude Code（最後手段，給 grace period）

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
    "idle_cpu": 1.0,
    "min_age_seconds": 300,
    "grace_seconds": 30,
    "log_max_bytes": 1_048_576,
    "log_retain_lines": 200,
    "expendables": [
        {"pattern": "Google Chrome Helper (Renderer)", "label": "Chrome 分頁"},
        {"pattern": "LINE", "label": "LINE"},
        {"pattern": "LineCall", "label": "LINE Call"},
        {"pattern": "Visual Studio Code", "label": "VS Code"},
        {"pattern": "Antigravity", "label": "Antigravity"},
        {"pattern": "openclaw-gateway", "label": "OpenClaw"},
        {"pattern": "AltServer", "label": "AltServer"},
    ],
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
            cmd, shell=True, capture_output=True, text=True, timeout=10, env=_ENV,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _get_mem_level() -> int | None:
    out = _run("/usr/sbin/sysctl -n kern.memorystatus_level")
    if out and out.isdigit():
        return int(out)
    return None


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
        self.log_dir = Path(
            self.cfg.get("log_dir", "~/.claude/data/system-monitor")
        ).expanduser()
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
            "p1_killed": 0,
            "p1_freed_mb": 0,
            "p2_killed": 0,
            "p3_killed": 0,
            "kills": [],
        }

        if mem_level > warn_th:
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
                    result["kills"].append({
                        "phase": "P1",
                        "process": label,
                        "pid": pid,
                        "mem_mb": mem_mb,
                    })

        self._log(f"  P1 result: killed={result['p1_killed']} freed={result['p1_freed_mb']}MB")

        # ═══ P2+P3: Claude Code (CRIT only) ═══
        if mem_level < crit_th:
            self._log("  --- P2+P3: Claude Code (CRIT mode) ---")
            idle_cpu = _get(self.cfg, "idle_cpu")
            min_age = _get(self.cfg, "min_age_seconds")
            grace = _get(self.cfg, "grace_seconds")

            claude_pids = _run("pgrep -x claude").splitlines()
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
                    self._log(f"  SKIP Claude PID {pid} (age:{age}s < {min_age}s)")
                    continue

                if cpu < idle_cpu:
                    # P2: idle → immediate SIGTERM
                    if _kill_term(pid):
                        self._log(f"  P2 KILL Claude PID {pid} (idle CPU:{cpu}% MEM:{mem_mb}MB)")
                        result["p2_killed"] += 1
                        result["kills"].append({
                            "phase": "P2",
                            "process": "Claude Code (idle)",
                            "pid": pid,
                            "mem_mb": mem_mb,
                        })
                else:
                    # P3: busy → SIGTERM + grace + SIGKILL
                    if _kill_term(pid):
                        self._log(
                            f"  P3 TERM Claude PID {pid} (active CPU:{cpu}% MEM:{mem_mb}MB) "
                            f"grace={grace}s"
                        )
                        result["p3_killed"] += 1
                        result["kills"].append({
                            "phase": "P3",
                            "process": "Claude Code (active)",
                            "pid": pid,
                            "mem_mb": mem_mb,
                        })
                        # Fork a delayed force-kill
                        if os.fork() == 0:
                            time.sleep(grace)
                            if _pid_alive(pid):
                                _kill_force(pid)
                                with self.log_path.open("a") as f:
                                    fts = datetime.now().strftime("%m/%d %H:%M:%S")
                                    f.write(f"[{fts}] P3 FORCE-KILL Claude PID {pid}\n")
                            os._exit(0)

            self._log(f"  P2+P3 result: cc_killed={result['p2_killed'] + result['p3_killed']}")
        else:
            self._log("  P2+P3: SKIPPED (WARN only, Claude Code protected)")

        total_killed = result["p1_killed"] + result["p2_killed"] + result["p3_killed"]
        self._log(f"[{ts}] DONE: total_killed={total_killed} freed≈{result['p1_freed_mb']}MB")

        result["status"] = "acted"
        result["total_killed"] = total_killed

        self._flush_log()
        return result


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    guardian = MemoryGuardian()
    result = guardian.run()
    if result["status"] == "ok":
        print(f"Memory OK (level={result['mem_level']})")
    elif result["status"] == "acted":
        print(
            f"Guardian acted: level={result['mem_level']} "
            f"killed={result.get('total_killed', 0)} "
            f"freed≈{result['p1_freed_mb']}MB"
        )
    else:
        print(f"Skip: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    main()
