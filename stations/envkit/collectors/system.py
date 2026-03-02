"""System collector — macOS version, chip, hostname, disk."""

from __future__ import annotations

import platform
import subprocess


def _run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def collect() -> dict:
    hostname = platform.node() or _run("hostname -s")
    os_version = _run("sw_vers -productVersion")
    build = _run("sw_vers -buildVersion")
    chip = _run("sysctl -n machdep.cpu.brand_string")
    cores = _run("sysctl -n hw.logicalcpu")
    mem_bytes = _run("sysctl -n hw.memsize")
    mem_gb = round(int(mem_bytes) / (1024 ** 3), 1) if mem_bytes.isdigit() else 0

    # Disk summary (df /)
    df_out = _run("df -h / | tail -1")
    disk = {}
    parts = df_out.split()
    if len(parts) >= 5:
        disk = {
            "total": parts[1],
            "used": parts[2],
            "available": parts[3],
            "usage_pct": parts[4],
        }

    # Uptime
    uptime = _run("uptime | sed 's/.*up //' | sed 's/,.*//'")

    return {
        "hostname": hostname,
        "os_version": os_version,
        "build": build,
        "chip": chip,
        "logical_cores": int(cores) if cores.isdigit() else 0,
        "memory_gb": mem_gb,
        "disk": disk,
        "uptime": uptime,
    }
