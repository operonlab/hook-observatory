#!/usr/bin/env python3
"""
System Monitor V2 Collector — macOS disk + hardware metrics → JSON

Usage:
    python3 collector.py                    # Full collection (disk + hardware)
    python3 collector.py --hardware-only    # Hardware snapshot only (fast, ~1s)
    python3 collector.py --disk-only        # Disk scan only (slow, ~30s)
    python3 collector.py --output FILE      # Write to file instead of stdout
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------


def run(cmd: str, timeout: int = 30) -> str:
    """Run a shell command, return stdout. Empty string on failure."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def parse_float(s: str, default: float = 0.0) -> float:
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Pressure level
# ---------------------------------------------------------------------------


def classify_pressure(
    value: float,
    thresholds: dict,
    *,
    invert: bool = False,
) -> str:
    """Classify value into green/yellow/red/danger.

    Args:
        value: the metric value
        thresholds: {"warning": N, "critical": N, "danger": N}
        invert: True for battery (lower = worse)
    """
    w = thresholds.get("warning", 70)
    c = thresholds.get("critical", 85)
    d = thresholds.get("danger", 95)

    if invert:
        if value <= d:
            return "danger"
        if value <= c:
            return "critical"
        if value <= w:
            return "warning"
        return "normal"
    else:
        if value >= d:
            return "danger"
        if value >= c:
            return "critical"
        if value >= w:
            return "warning"
        return "normal"


# ---------------------------------------------------------------------------
# Disk metrics
# ---------------------------------------------------------------------------


def collect_disk_fast(config: dict) -> dict:
    """Fast disk metrics — df-based (accurate for actual usable disk space)."""
    thresholds = config.get("thresholds", {}).get(
        "disk_usage_pct", {"warning": 75, "critical": 85, "danger": 95}
    )

    total_bytes = 0
    free_bytes = 0

    # Primary: df on Data volume (most accurate on APFS)
    df_out = run("df -k /System/Volumes/Data 2>/dev/null | tail -1")
    parts = df_out.split()
    if len(parts) >= 4:
        total_bytes = int(parts[1]) * 1024
        free_bytes = int(parts[3]) * 1024

    # Fallback: APFS container (pick the largest one)
    if total_bytes == 0:
        container_raw = run("diskutil apfs list 2>/dev/null", timeout=10)
        max_total = 0
        cur_total = 0
        cur_free = 0
        for line in container_raw.splitlines():
            if "Size (Capacity Ceiling)" in line:
                m = re.search(r"(\d+)\s*B\b", line)
                if m:
                    cur_total = int(m.group(1))
            elif "Capacity Not Allocated" in line:
                m = re.search(r"(\d+)\s*B\b", line)
                if m:
                    cur_free = int(m.group(1))
                    if cur_total > max_total:
                        max_total = cur_total
                        total_bytes = cur_total
                        free_bytes = cur_free

    used_bytes = total_bytes - free_bytes
    usage_pct = round(used_bytes * 100 / total_bytes, 1) if total_bytes else 0
    pressure = classify_pressure(usage_pct, thresholds)

    return {
        "usage_pct": usage_pct,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "pressure_level": pressure,
    }


def collect_disk(config: dict) -> dict:
    thresholds = config.get("thresholds", {}).get(
        "disk_usage_pct", {"warning": 75, "critical": 85, "danger": 95}
    )
    scan_cfg = config.get("disk_scan", {})

    # -- Disk space (df-based, accurate on APFS) --
    total_bytes = 0
    free_bytes = 0

    df_out = run("df -k /System/Volumes/Data 2>/dev/null | tail -1")
    parts = df_out.split()
    if len(parts) >= 4:
        total_bytes = int(parts[1]) * 1024
        free_bytes = int(parts[3]) * 1024

    # Fallback: APFS container (pick the largest one)
    if total_bytes == 0:
        container_raw = run("diskutil apfs list 2>/dev/null")
        max_total = 0
        cur_total = 0
        cur_free = 0
        for line in container_raw.splitlines():
            if "Size (Capacity Ceiling)" in line:
                m = re.search(r"(\d+)\s*B\b", line)
                if m:
                    cur_total = int(m.group(1))
            elif "Capacity Not Allocated" in line:
                m = re.search(r"(\d+)\s*B\b", line)
                if m:
                    cur_free = int(m.group(1))
                    if cur_total > max_total:
                        max_total = cur_total
                        total_bytes = cur_total
                        free_bytes = cur_free

    used_bytes = total_bytes - free_bytes
    total_gb = round(total_bytes / (1024**3), 1)
    used_gb = round(used_bytes / (1024**3), 1)
    free_gb = round(free_bytes / (1024**3), 1)
    usage_pct = round(used_bytes * 100 / total_bytes, 1) if total_bytes else 0

    # -- APFS volume distribution --
    container_raw = run("diskutil apfs list 2>/dev/null")
    volumes = []
    vol_name = ""
    for line in container_raw.splitlines():
        name_match = re.search(r"Name:\s+(.+?)(?:\s+\(Case|$)", line)
        if name_match:
            vol_name = name_match.group(1).strip()
        cap_match = re.search(r"Capacity Consumed:\s+(\d+)\s*B\b", line)
        if cap_match and vol_name:
            cap_bytes = int(cap_match.group(1))
            volumes.append(
                {"name": vol_name, "used_gb": round(cap_bytes / (1024**3), 1)}
            )
            vol_name = ""

    volumes.sort(key=lambda v: v["used_gb"], reverse=True)

    # -- Top consumers (home dir) --
    home = Path.home()
    top_consumers = _scan_top_dirs(home, top_n=10)

    # -- Large files + stale files (single-pass find) --
    large_files, stale_files = _scan_files(
        home,
        min_mb=scan_cfg.get("large_file_min_mb", 10),
        stale_days=scan_cfg.get("stale_days", 90),
        top_n=scan_cfg.get("top_n", 30),
        excludes=scan_cfg.get(
            "exclude_paths",
            [".Trash", ".git", "node_modules"],
        ),
    )

    # -- Cache sizes --
    caches = _scan_caches(home)

    pressure = classify_pressure(usage_pct, thresholds)

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "usage_pct": usage_pct,
        "pressure": pressure,
        "volumes": volumes[:10],
        "top_consumers": top_consumers,
        "large_files": large_files,
        "stale_files": stale_files,
        "caches": caches,
        "scan_complete": len(large_files) > 0 or len(top_consumers) > 0,
    }


def _scan_top_dirs(home: Path, top_n: int = 10) -> list[dict]:
    """Get top N largest direct children of home dir.

    Uses APFS volume-level data for fast totals, then scans top-level dirs
    with individual timeouts so one slow dir doesn't block everything.
    """
    entries = []
    # List immediate children
    q_home = shlex.quote(str(home))
    children_out = run(f'ls -1d {q_home}/* {q_home}/.[!.]* 2>/dev/null')
    children = [p for p in children_out.splitlines() if p.strip()]

    # Run du on each child with a tight per-dir timeout (10s each)
    # Using subprocess directly for better timeout control
    for child in children:
        try:
            r = subprocess.run(
                ["du", "-sk", child],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split("\t", 1)
                if len(parts) == 2 and parts[0].strip().isdigit():
                    size_kb = int(parts[0].strip())
                    name = parts[1].replace(str(home) + "/", "~/")
                    entries.append({"path": name, "size_gb": round(size_kb / (1024**2), 2)})
        except subprocess.TimeoutExpired:
            # Directory too large to scan quickly; estimate from APFS if possible
            name = child.replace(str(home) + "/", "~/")
            entries.append({"path": name, "size_gb": -1, "note": "scan_timeout"})

    entries.sort(key=lambda x: x["size_gb"], reverse=True)
    return entries[:top_n]


def _scan_files(
    home: Path,
    min_mb: int,
    stale_days: int,
    top_n: int,
    excludes: list[str],
) -> tuple[list[dict], list[dict]]:
    """Single-pass find for large + stale files."""
    exclude_args = " ".join(f'-not -path "*/{shlex.quote(e)}/*"' for e in excludes)
    q_home = shlex.quote(str(home))
    cmd = (
        f'find {q_home} {exclude_args} '
        f"-type f -size +{min_mb}M -print0 "
        f"2>/dev/null | awk 'BEGIN{{RS=\"\\0\"; ORS=\"\\0\"}} NR<=500' "
        f'| xargs -0 stat -f "%z %Sm %Sa %N" -t "%Y-%m-%d" 2>/dev/null'
    )
    # Allow up to 5 minutes for deep file scan (home dir can be huge)
    out = run(cmd, timeout=300)

    large = []
    stale = []
    cutoff_date = (datetime.now() - timedelta(days=stale_days)).strftime("%Y-%m-%d")

    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        size_b, mdate, adate, path = int(parts[0]), parts[1], parts[2], parts[3]
        size_mb = round(size_b / (1024**2), 1)
        rel_path = path.replace(str(home), "~")

        large.append(
            {"path": rel_path, "size_mb": size_mb, "modified": mdate}
        )
        if adate < cutoff_date:
            stale.append(
                {
                    "path": rel_path,
                    "size_mb": size_mb,
                    "last_accessed": adate,
                }
            )

    large.sort(key=lambda x: x["size_mb"], reverse=True)
    stale.sort(key=lambda x: x["size_mb"], reverse=True)
    return large[:top_n], stale[:top_n]


def _scan_caches(home: Path) -> list[dict]:
    """Scan common cache directories."""
    dirs = [
        home / "Library" / "Caches",
        home / "Library" / "Logs",
        home / ".npm" / "_cacache",
        home / ".cache",
    ]
    result = []
    for d in dirs:
        if d.is_dir():
            out = run(f'du -sk "{d}" 2>/dev/null')
            parts = out.split("\t", 1)
            if parts and parts[0].isdigit():
                size_gb = round(int(parts[0]) / (1024**2), 2)
                result.append(
                    {"path": str(d).replace(str(home), "~"), "size_gb": size_gb}
                )

    # Homebrew cache
    brew_cache = run("brew --cache 2>/dev/null")
    if brew_cache and Path(brew_cache).is_dir():
        out = run(f'du -sk "{brew_cache}" 2>/dev/null')
        parts = out.split("\t", 1)
        if parts and parts[0].isdigit():
            result.append(
                {
                    "path": brew_cache,
                    "size_gb": round(int(parts[0]) / (1024**2), 2),
                }
            )

    # Trash
    trash = home / ".Trash"
    if trash.is_dir():
        out = run(f'du -sk "{trash}" 2>/dev/null')
        parts = out.split("\t", 1)
        if parts and parts[0].isdigit():
            result.append(
                {"path": "~/.Trash", "size_gb": round(int(parts[0]) / (1024**2), 2)}
            )

    result.sort(key=lambda x: x["size_gb"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Hardware metrics
# ---------------------------------------------------------------------------


def collect_hardware(config: dict) -> dict:
    thresholds = config.get("thresholds", {})
    return {
        "cpu": _collect_cpu(
            thresholds.get(
                "cpu_avg_pct", {"warning": 70, "critical": 85, "danger": 95}
            )
        ),
        "memory": _collect_memory(
            thresholds.get(
                "memory_pct", {"warning": 75, "critical": 85, "danger": 95}
            )
        ),
        "swap": _collect_swap(
            thresholds.get(
                "swap_gb", {"warning": 2.0, "critical": 4.0, "danger": 8.0}
            )
        ),
        "temperature": _collect_temperature(
            thresholds.get(
                "temperature_c", {"warning": 80, "critical": 95, "danger": 105}
            )
        ),
        "battery": _collect_battery(
            thresholds.get(
                "battery_pct", {"warning": 30, "critical": 20, "danger": 10}
            )
        ),
    }


def _collect_cpu(thresholds: dict) -> dict:
    # Method 1: top (gives load averages + CPU usage)
    top_out = run("top -l 1 -n 0 2>/dev/null")

    user_pct = 0.0
    sys_pct = 0.0
    idle_pct = 0.0
    load_avg = [0.0, 0.0, 0.0]

    for line in top_out.splitlines():
        if "CPU usage" in line:
            m_user = re.search(r"([\d.]+)%\s*user", line)
            m_sys = re.search(r"([\d.]+)%\s*sys", line)
            m_idle = re.search(r"([\d.]+)%\s*idle", line)
            if m_user:
                user_pct = parse_float(m_user.group(1))
            if m_sys:
                sys_pct = parse_float(m_sys.group(1))
            if m_idle:
                idle_pct = parse_float(m_idle.group(1))
        if "Load Avg" in line:
            nums = re.findall(r"[\d.]+", line)
            load_avg = [parse_float(n) for n in nums[:3]]

    usage_pct = round(user_pct + sys_pct, 1)

    # Core count
    core_count_str = run("sysctl -n hw.logicalcpu 2>/dev/null")
    core_count = int(core_count_str) if core_count_str.isdigit() else 0

    # CPU model
    cpu_brand = run("sysctl -n machdep.cpu.brand_string 2>/dev/null")

    pressure = classify_pressure(usage_pct, thresholds)

    return {
        "brand": cpu_brand,
        "cores": core_count,
        "usage_pct": usage_pct,
        "user_pct": user_pct,
        "sys_pct": sys_pct,
        "idle_pct": idle_pct,
        "load_avg_1m": load_avg[0] if len(load_avg) > 0 else 0.0,
        "load_avg_5m": load_avg[1] if len(load_avg) > 1 else 0.0,
        "load_avg_15m": load_avg[2] if len(load_avg) > 2 else 0.0,
        "pressure": pressure,
    }


def _collect_memory(thresholds: dict) -> dict:
    # Total physical memory
    mem_str = run("sysctl -n hw.memsize 2>/dev/null")
    total_bytes = int(mem_str) if mem_str.isdigit() else 0
    total_gb = round(total_bytes / (1024**3), 1)

    # vm_stat for detailed breakdown
    vm_out = run("vm_stat 2>/dev/null")
    page_size = 16384  # Apple Silicon default
    m_ps = re.search(r"page size of (\d+) bytes", vm_out)
    if m_ps:
        page_size = int(m_ps.group(1))

    def get_pages(label: str) -> int:
        m = re.search(rf"{label}:\s+(\d+)", vm_out)
        return int(m.group(1)) if m else 0

    active_pages = get_pages("Pages active")
    inactive_pages = get_pages("Pages inactive")
    speculative_pages = get_pages("Pages speculative")
    wired_pages = get_pages("Pages wired down")
    compressed_pages = get_pages("Pages occupied by compressor")

    # App memory ≈ active + wired + compressed (matches Activity Monitor)
    app_bytes = (active_pages + wired_pages + compressed_pages) * page_size
    app_gb = round(app_bytes / (1024**3), 1)
    # used_gb reflects app memory (what Activity Monitor shows as "Memory Used")
    used_gb = app_gb

    # Percentage based on app memory, not including inactive/speculative cache
    usage_pct = round(app_bytes * 100 / total_bytes, 1) if total_bytes else 0

    # memory_pressure utility
    pressure_out = run("memory_pressure 2>/dev/null | head -1")
    sys_pressure = "normal"
    if "critical" in pressure_out.lower():
        sys_pressure = "critical"
    elif "warn" in pressure_out.lower():
        sys_pressure = "warning"

    pressure = classify_pressure(usage_pct, thresholds)

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "app_gb": app_gb,
        "wired_gb": round(wired_pages * page_size / (1024**3), 1),
        "compressed_gb": round(compressed_pages * page_size / (1024**3), 1),
        "usage_pct": usage_pct,
        "system_pressure": sys_pressure,
        "pressure": pressure,
    }


def _collect_swap(thresholds: dict) -> dict:
    swap_out = run("sysctl vm.swapusage 2>/dev/null")
    total_mb = 0.0
    used_mb = 0.0

    m_total = re.search(r"total\s*=\s*([\d.]+)M", swap_out)
    m_used = re.search(r"used\s*=\s*([\d.]+)M", swap_out)
    if m_total:
        total_mb = parse_float(m_total.group(1))
    if m_used:
        used_mb = parse_float(m_used.group(1))

    used_gb = round(used_mb / 1024, 2)
    total_gb = round(total_mb / 1024, 2)

    pressure = classify_pressure(used_gb, thresholds)

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "pressure": pressure,
    }


def _collect_temperature(thresholds: dict) -> dict:
    # Try osx-cpu-temp first (no sudo required)
    temp_out = run("osx-cpu-temp 2>/dev/null")
    temp_c = 0.0

    if temp_out:
        m = re.search(r"([\d.]+)\s*°?C", temp_out)
        if m:
            temp_c = parse_float(m.group(1))

    # Fallback: try reading from IOKit via system_profiler (limited)
    if temp_c == 0:
        # On Apple Silicon, thermal data may not be available without sudo
        # We'll mark it as unavailable
        return {
            "cpu_temp_c": None,
            "available": False,
            "pressure": "unknown",
            "note": "Install osx-cpu-temp (brew install osx-cpu-temp) for temperature monitoring",
        }

    pressure = classify_pressure(temp_c, thresholds)

    return {
        "cpu_temp_c": temp_c,
        "available": True,
        "pressure": pressure,
    }


def _collect_battery(thresholds: dict) -> dict:
    batt_out = run("pmset -g batt 2>/dev/null")

    if "InternalBattery" not in batt_out and "Battery" not in batt_out:
        return {
            "available": False,
            "note": "No battery detected (desktop Mac)",
        }

    pct = 0
    charging = False
    cycle_count = None
    condition = None

    m_pct = re.search(r"(\d+)%", batt_out)
    if m_pct:
        pct = int(m_pct.group(1))

    charging = "charging" in batt_out.lower() and "not charging" not in batt_out.lower()

    # Battery condition from system_profiler
    sp_out = run(
        'system_profiler SPPowerDataType 2>/dev/null | grep -E "Cycle Count|Condition"'
    )
    for line in sp_out.splitlines():
        if "Cycle Count" in line:
            m = re.search(r"(\d+)", line)
            if m:
                cycle_count = int(m.group(1))
        if "Condition" in line:
            condition = line.split(":")[-1].strip()

    pressure = classify_pressure(pct, thresholds, invert=True)

    return {
        "available": True,
        "percent": pct,
        "charging": charging,
        "cycle_count": cycle_count,
        "condition": condition,
        "pressure": pressure,
    }


# ---------------------------------------------------------------------------
# Overall pressure
# ---------------------------------------------------------------------------


def overall_pressure(disk: dict, hardware: dict) -> str:
    """Return the worst pressure across all metrics."""
    levels = {"normal": 0, "unknown": 0, "warning": 1, "critical": 2, "danger": 3}
    worst = 0

    # Disk
    worst = max(worst, levels.get(disk.get("pressure", "normal"), 0))

    # Hardware sub-metrics
    for key in ("cpu", "memory", "swap", "temperature", "battery"):
        sub = hardware.get(key, {})
        p = sub.get("pressure", "normal")
        worst = max(worst, levels.get(p, 0))

    reverse_map = {0: "normal", 1: "warning", 2: "critical", 3: "danger"}
    return reverse_map.get(worst, "normal")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def collect_all(config: dict, *, disk: bool = True, hardware: bool = True) -> dict:
    result: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "hostname": run("hostname -s"),
        "os_version": run("sw_vers -productVersion 2>/dev/null"),
        "chip": run("sysctl -n machdep.cpu.brand_string 2>/dev/null"),
    }

    disk_data = {}
    hw_data = {}

    if disk:
        disk_data = collect_disk(config)
        result["disk"] = disk_data

    if hardware:
        hw_data = collect_hardware(config)
        result["hardware"] = hw_data

    result["pressure_level"] = overall_pressure(disk_data, hw_data)
    result["top_processes"] = collect_top_processes()
    return result


def collect_top_processes(top_n: int = 3) -> list[dict]:
    """Get top processes by CPU + memory usage."""
    # ps sorted by CPU, grab top entries
    out = run(
        "ps -eo pid,pcpu,pmem,rss,comm -r 2>/dev/null | head -30"
    )
    seen_names: dict[str, dict] = {}
    for line in out.splitlines()[1:]:  # skip header
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid = int(parts[0])
        cpu = parse_float(parts[1])
        mem_pct = parse_float(parts[2])
        rss_kb = int(parts[3]) if parts[3].isdigit() else 0
        name = parts[4].rsplit("/", 1)[-1]  # basename
        # Aggregate by process name (combine multiple instances)
        if name in seen_names:
            seen_names[name]["cpu_pct"] += cpu
            seen_names[name]["mem_pct"] += mem_pct
            seen_names[name]["mem_mb"] += rss_kb / 1024
            seen_names[name]["count"] += 1
        else:
            seen_names[name] = {
                "name": name,
                "pid": pid,
                "cpu_pct": cpu,
                "mem_pct": round(mem_pct, 1),
                "mem_mb": rss_kb / 1024,
                "count": 1,
            }
    procs = list(seen_names.values())
    # Sort by combined resource weight (CPU% + mem%)
    procs.sort(key=lambda p: p["cpu_pct"] + p["mem_pct"], reverse=True)
    for p in procs:
        p["cpu_pct"] = round(p["cpu_pct"], 1)
        p["mem_pct"] = round(p["mem_pct"], 1)
        p["mem_mb"] = round(p["mem_mb"], 1)
    return procs[:top_n]


def collect_services() -> list[dict]:
    """Enumerate launchd services from ~/Library/LaunchAgents/."""
    import plistlib

    agents_dir = Path.home() / "Library" / "LaunchAgents"
    if not agents_dir.is_dir():
        return []

    # Get running services from launchctl
    launchctl_out = run("launchctl list 2>/dev/null")
    running: dict[str, dict] = {}
    for line in launchctl_out.splitlines()[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) >= 3:
            pid_str, status_str, label = parts[0], parts[1], parts[2]
            running[label] = {
                "pid": int(pid_str) if pid_str != "-" else None,
                "exit_status": int(status_str) if status_str.lstrip("-").isdigit() else 0,
            }

    services = []
    for plist_path in sorted(agents_dir.glob("*.plist")):
        try:
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
        except Exception:
            continue

        label = plist.get("Label", plist_path.stem)
        # Determine category
        if "pulso" in label:
            category = "pulso"
        elif "joneshong" in label:
            category = "jonathan"
        elif "workshop" in label:
            category = "workshop"
        elif "homebrew" in label or "nginx" in label:
            category = "infra"
        else:
            category = "third-party"

        # Determine type + schedule
        has_keepalive = bool(plist.get("KeepAlive"))
        start_interval = plist.get("StartInterval")
        start_cal = plist.get("StartCalendarInterval")

        if start_interval:
            svc_type = "periodic"
            if start_interval < 60:
                schedule = f"每 {start_interval} 秒"
            elif start_interval < 3600:
                schedule = f"每 {start_interval // 60} 分鐘"
            elif start_interval < 86400:
                schedule = f"每 {start_interval // 3600} 小時"
            else:
                schedule = f"每 {start_interval // 86400} 天"
        elif start_cal:
            svc_type = "periodic"
            cal = start_cal if isinstance(start_cal, dict) else (start_cal[0] if isinstance(start_cal, list) and start_cal else {})
            parts_cal = []
            if "Weekday" in cal:
                days = ["日", "一", "二", "三", "四", "五", "六"]
                parts_cal.append(f"週{days[cal['Weekday'] % 7]}")
            if "Hour" in cal:
                parts_cal.append(f"{cal['Hour']:02d}:{cal.get('Minute', 0):02d}")
            schedule = " ".join(parts_cal) if parts_cal else "排程"
        elif has_keepalive or plist.get("RunAtLoad"):
            svc_type = "service"
            schedule = "常駐"
        else:
            svc_type = "oneshot"
            schedule = "手動"

        # Determine status
        run_info = running.get(label, {})
        pid = run_info.get("pid")
        is_disabled = plist_path.name.endswith(".disabled")

        if is_disabled:
            status = "disabled"
        elif pid is not None:
            status = "running"
        elif label in running:
            exit_s = run_info.get("exit_status", 0)
            status = "idle" if exit_s == 0 else f"error({exit_s})"
        else:
            status = "unloaded"

        # Short name
        name = label.replace("com.joneshong.", "").replace("com.pulso.", "").replace("com.workshop.", "").replace("homebrew.mxcl.", "")

        services.append({
            "label": label,
            "name": name,
            "category": category,
            "type": svc_type,
            "schedule": schedule,
            "status": status,
            "pid": pid,
        })

    # Also add disabled plists
    for plist_path in sorted(agents_dir.glob("*.plist.disabled")):
        try:
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
        except Exception:
            continue

        label = plist.get("Label", plist_path.stem.replace(".plist", ""))
        # Skip if already processed
        if any(s["label"] == label for s in services):
            continue

        if "pulso" in label:
            category = "pulso"
        elif "joneshong" in label:
            category = "jonathan"
        elif "workshop" in label:
            category = "workshop"
        else:
            category = "third-party"

        name = label.replace("com.joneshong.", "").replace("com.pulso.", "").replace("com.workshop.", "").replace("homebrew.mxcl.", "")
        services.append({
            "label": label,
            "name": name,
            "category": category,
            "type": "service",
            "schedule": "—",
            "status": "disabled",
            "pid": None,
        })

    # Sort by category then name
    cat_order = {"workshop": 0, "jonathan": 1, "pulso": 2, "infra": 3, "third-party": 4}
    services.sort(key=lambda s: (cat_order.get(s["category"], 9), s["name"]))
    return services


def collect_guardian_log(max_entries: int = 50) -> list[dict]:
    """Parse memory-guardian log into structured entries."""
    log_path = Path.home() / ".tmux" / "logs" / "memory-guardian.log"
    if not log_path.exists():
        return []

    entries = []
    current_entry = None

    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line or line == "---":
            if current_entry:
                entries.append(current_entry)
                current_entry = None
            continue

        # New pressure event: [02/21 17:00:32] PRESSURE: level=35 ...
        m = re.match(r"\[(\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+(PRESSURE|DONE):\s+(.*)", line)
        if m:
            ts_str, event_type, detail = m.group(1), m.group(2), m.group(3)
            if event_type == "PRESSURE":
                level_m = re.search(r"level=(\d+)", detail)
                level_val = int(level_m.group(1)) if level_m else 0
                if level_val < 15:
                    severity = "KILL"
                elif level_val < 40:
                    severity = "WARN"
                else:
                    severity = "SWEEP"
                current_entry = {
                    "timestamp": ts_str,
                    "level": severity,
                    "pressure_level": level_val,
                    "kills": [],
                    "total_killed": 0,
                    "freed_mb": 0,
                }
            elif event_type == "DONE" and current_entry:
                total_m = re.search(r"total_killed=(\d+)", detail)
                freed_m = re.search(r"freed≈(\d+)MB", detail)
                current_entry["total_killed"] = int(total_m.group(1)) if total_m else 0
                current_entry["freed_mb"] = int(freed_m.group(1)) if freed_m else 0
            continue

        # Kill line: KILL Chrome 分頁 PID 989 (302MB)
        kill_m = re.match(r"KILL\s+(.+?)\s+PID\s+(\d+)\s+\((\d+)MB\)", line)
        if kill_m and current_entry:
            current_entry["kills"].append({
                "process": kill_m.group(1),
                "pid": int(kill_m.group(2)),
                "mem_mb": int(kill_m.group(3)),
            })

    if current_entry:
        entries.append(current_entry)

    # Return most recent first
    entries.reverse()
    return entries[:max_entries]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="System Monitor V2 Collector")
    parser.add_argument(
        "--hardware-only", action="store_true",
        help="Collect hardware metrics only (fast)",
    )
    parser.add_argument(
        "--disk-only", action="store_true",
        help="Collect disk metrics only",
    )
    parser.add_argument(
        "--output", "-o", type=str,
        help="Output file path (default: stdout)",
    )
    parser.add_argument("--config", type=str, help="Config file path")
    parser.add_argument(
        "--compact", action="store_true",
        help="Compact JSON output (no indentation)",
    )
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    config = load_config(config_path)

    do_disk = not args.hardware_only
    do_hw = not args.disk_only

    result = collect_all(config, disk=do_disk, hardware=do_hw)

    indent = None if args.compact else 2
    output = json.dumps(result, indent=indent, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n")
        print(f"Report saved to {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
