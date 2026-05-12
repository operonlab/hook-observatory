"""System metrics collector — macOS sysmon data (CPU, MEM, NET, DISK, Claude procs).

Ported from Pulso sysmon metrics/ collectors. All functions are synchronous
(subprocess calls) and intended to run via `run_in_executor` from the async loop.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level state for network delta calculation
# ---------------------------------------------------------------------------
_prev_rx: int = 0
_prev_tx: int = 0
_prev_ts: float = 0.0

# Disk cache (60s TTL)
_disk_cache: dict | None = None
_disk_cache_ts: float = 0.0


@dataclass
class SysmonSnapshot:
    ts: str = ""
    # CPU
    cpu_pct: float = 0.0
    cpu_display: str = "?%"
    # Memory
    mem_used_gb: float = 0.0
    mem_total_gb: float = 0.0
    mem_pct: float = 0.0
    mem_pressure: int = 99
    mem_display: str = "?/?G ?%"
    # Network
    net_rx_bps: int = 0
    net_tx_bps: int = 0
    net_display: str = "\u2193-- \u2191--"
    # Disk
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_pct: float = 0.0
    disk_display: str = "?/?G ?%"
    # Claude Code processes
    cc_active: int = 0
    cc_idle: int = 0
    cc_mem_mb: float = 0.0
    cc_display: str = "0"
    # LLM quota placeholders (filled by quota_collector in Phase 2)
    llm_cc_5h: str = "?"
    llm_cc_7d: str = "?"
    llm_cc_ex: str = "?"
    llm_cx_5h: str = "?"
    llm_cx_7d: str = "?"
    llm_gm_pro: str = "?"
    llm_display: str = "?"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------

def collect_cpu() -> dict:
    """Collect CPU usage from load average / ncpu."""
    try:
        load_raw = subprocess.run(
            ["sysctl", "-n", "vm.loadavg"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        load = float(load_raw.split()[1])

        ncpu = int(subprocess.run(
            ["sysctl", "-n", "hw.ncpu"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())

        pct = min(load / ncpu * 100, 100.0)
        return {"cpu_pct": round(pct, 1), "cpu_display": f"{pct:.0f}%"}
    except Exception:
        log.warning("collect_cpu_failed", exc_info=True)
        return {"cpu_pct": 0.0, "cpu_display": "?%"}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def _parse_vm_stat(output: str, label: str) -> int:
    for line in output.splitlines():
        if label in line:
            parts = line.split(":")
            if len(parts) >= 2:
                return int(parts[1].strip().rstrip("."))
    return 0


def collect_memory() -> dict:
    """Collect memory usage and pressure level."""
    try:
        total_bytes = int(subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())
        total_gb = total_bytes / (1024 ** 3)

        page_size = int(subprocess.run(
            ["sysctl", "-n", "hw.pagesize"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())

        vm_output = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=5,
        ).stdout

        active = _parse_vm_stat(vm_output, "Pages active")
        wired = _parse_vm_stat(vm_output, "Pages wired")
        compressed = _parse_vm_stat(vm_output, "Pages occupied by compressor")

        used_pages = active + wired + compressed
        used_bytes = used_pages * page_size
        used_gb = used_bytes / (1024 ** 3)
        pct = used_bytes * 100 / total_bytes

        pressure = int(subprocess.run(
            ["sysctl", "-n", "kern.memorystatus_level"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip())

        if pressure < 10:
            indicator = " \u2716"
        elif pressure < 20:
            indicator = " \u26a0"
        else:
            indicator = ""

        display = f"{used_gb:.1f}/{total_gb:.0f}G {pct:.0f}%{indicator}"

        return {
            "mem_used_gb": round(used_gb, 1),
            "mem_total_gb": round(total_gb, 0),
            "mem_pct": round(pct, 1),
            "mem_pressure": pressure,
            "mem_display": display,
        }
    except Exception:
        log.warning("collect_memory_failed", exc_info=True)
        return {
            "mem_used_gb": 0.0, "mem_total_gb": 0.0,
            "mem_pct": 0.0, "mem_pressure": 99,
            "mem_display": "?/?G ?%",
        }


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def _format_speed(bps: int) -> str:
    if bps >= 1_048_576:
        return f"{bps / 1_048_576:.1f}M/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f}K/s"
    return f"{bps}B/s"


def collect_network() -> dict:
    """Collect network RX/TX speed via netstat delta."""
    global _prev_rx, _prev_tx, _prev_ts

    try:
        iface_raw = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        iface = ""
        for line in iface_raw.splitlines():
            if "interface:" in line:
                iface = line.split()[-1]
                break

        if not iface:
            return {"net_rx_bps": 0, "net_tx_bps": 0, "net_display": "\u2193-- \u2191--"}

        netstat_out = subprocess.run(
            ["netstat", "-ib", "-I", iface],
            capture_output=True, text=True, timeout=5,
        ).stdout

        rx_now = tx_now = 0
        for line in netstat_out.splitlines():
            if "Link" in line:
                parts = line.split()
                if len(parts) >= 10:
                    rx_now = int(parts[6])
                    tx_now = int(parts[9])
                break

        ts_now = time.time()
        if _prev_ts > 0:
            dt = ts_now - _prev_ts
            if 0 < dt < 30:
                rx_rate = max(0, int((rx_now - _prev_rx) / dt))
                tx_rate = max(0, int((tx_now - _prev_tx) / dt))
            else:
                rx_rate = tx_rate = 0
        else:
            rx_rate = tx_rate = 0

        _prev_rx = rx_now
        _prev_tx = tx_now
        _prev_ts = ts_now

        display = f"\u2193{_format_speed(rx_rate)} \u2191{_format_speed(tx_rate)}"
        return {"net_rx_bps": rx_rate, "net_tx_bps": tx_rate, "net_display": display}
    except Exception:
        log.warning("collect_network_failed", exc_info=True)
        return {"net_rx_bps": 0, "net_tx_bps": 0, "net_display": "\u2193-- \u2191--"}


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------

def _extract_bytes(line: str) -> int:
    match = re.search(r"(\d+)\s*B(?:ytes)?", line)
    return int(match.group(1)) if match else 0


def _collect_apfs() -> dict:
    output = subprocess.run(
        ["diskutil", "apfs", "list"],
        capture_output=True, text=True, timeout=10,
    ).stdout

    total_bytes = 0
    free_bytes = 0
    for line in output.splitlines():
        if "Size (Capacity Ceiling)" in line and total_bytes == 0:
            total_bytes = _extract_bytes(line)
        elif "Capacity Not Allocated" in line and free_bytes == 0:
            free_bytes = _extract_bytes(line)

    if total_bytes <= 0:
        return _collect_df_fallback()

    used_bytes = total_bytes - free_bytes
    total_gb = total_bytes / (1024 ** 3)
    used_gb = used_bytes / (1024 ** 3)
    pct = used_bytes * 100 / total_bytes

    return {
        "disk_used_gb": round(used_gb, 1),
        "disk_total_gb": round(total_gb, 1),
        "disk_pct": round(pct, 1),
        "disk_display": f"{int(used_gb)}/{int(total_gb)}G {pct:.0f}%",
    }


def _collect_df_fallback() -> dict:
    try:
        output = subprocess.run(
            ["df", "-g", "/"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        lines = output.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            total_gb = float(parts[1])
            used_gb = float(parts[2])
            pct = (used_gb / total_gb * 100) if total_gb > 0 else 0
            return {
                "disk_used_gb": used_gb,
                "disk_total_gb": total_gb,
                "disk_pct": round(pct, 1),
                "disk_display": f"{int(used_gb)}/{int(total_gb)}G {pct:.0f}%",
            }
    except Exception:
        log.warning("collect_disk_df_failed", exc_info=True)
    return {"disk_used_gb": 0, "disk_total_gb": 0, "disk_pct": 0, "disk_display": "?/?G ?%"}


def collect_disk() -> dict:
    """Collect disk usage with 60s internal cache."""
    global _disk_cache, _disk_cache_ts

    now = time.time()
    if _disk_cache and (now - _disk_cache_ts) < settings.SYSMON_DISK_CACHE_TTL:
        return _disk_cache

    try:
        result = _collect_apfs()
    except Exception:
        log.warning("collect_disk_apfs_failed", exc_info=True)
        result = _collect_df_fallback()

    _disk_cache = result
    _disk_cache_ts = now
    return result


# ---------------------------------------------------------------------------
# Claude Code Processes
# ---------------------------------------------------------------------------

IDLE_CPU = 1.0


def collect_claude_procs() -> dict:
    """Collect Claude Code process stats (active vs idle)."""
    try:
        output = subprocess.run(
            ["ps", "-eo", "pid=,rss=,%cpu=,comm="],
            capture_output=True, text=True, timeout=5,
        ).stdout

        active_n = active_kb = idle_n = idle_kb = 0

        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            if parts[3] != "claude":
                continue

            rss_kb = int(parts[1])
            cpu = float(parts[2])

            if cpu < IDLE_CPU:
                idle_n += 1
                idle_kb += rss_kb
            else:
                active_n += 1
                active_kb += rss_kb

        total = active_n + idle_n
        total_mb = (active_kb + idle_kb) / 1024

        if total == 0:
            return {"cc_active": 0, "cc_idle": 0, "cc_mem_mb": 0.0, "cc_display": "0"}

        parts_display = []
        if active_n > 0:
            active_gb = active_kb / (1024 * 1024)
            parts_display.append(f"{active_n}>{active_gb:.1f}G")
        if idle_n > 0:
            idle_gb = idle_kb / (1024 * 1024)
            parts_display.append(f"{idle_n}*{idle_gb:.1f}G")

        return {
            "cc_active": active_n,
            "cc_idle": idle_n,
            "cc_mem_mb": round(total_mb, 1),
            "cc_display": " ".join(parts_display),
        }
    except Exception:
        log.warning("collect_claude_procs_failed", exc_info=True)
        return {"cc_active": 0, "cc_idle": 0, "cc_mem_mb": 0.0, "cc_display": "?"}


# ---------------------------------------------------------------------------
# Collect All
# ---------------------------------------------------------------------------

def collect_all() -> SysmonSnapshot:
    """Collect all system metrics and return a SysmonSnapshot."""
    snap = SysmonSnapshot(ts=datetime.now(UTC).isoformat())

    cpu = collect_cpu()
    snap.cpu_pct = cpu["cpu_pct"]
    snap.cpu_display = cpu["cpu_display"]

    mem = collect_memory()
    snap.mem_used_gb = mem["mem_used_gb"]
    snap.mem_total_gb = mem["mem_total_gb"]
    snap.mem_pct = mem["mem_pct"]
    snap.mem_pressure = mem["mem_pressure"]
    snap.mem_display = mem["mem_display"]

    net = collect_network()
    snap.net_rx_bps = net["net_rx_bps"]
    snap.net_tx_bps = net["net_tx_bps"]
    snap.net_display = net["net_display"]

    disk = collect_disk()
    snap.disk_used_gb = disk["disk_used_gb"]
    snap.disk_total_gb = disk["disk_total_gb"]
    snap.disk_pct = disk["disk_pct"]
    snap.disk_display = disk["disk_display"]

    cc = collect_claude_procs()
    snap.cc_active = cc["cc_active"]
    snap.cc_idle = cc["cc_idle"]
    snap.cc_mem_mb = cc["cc_mem_mb"]
    snap.cc_display = cc["cc_display"]

    return snap
