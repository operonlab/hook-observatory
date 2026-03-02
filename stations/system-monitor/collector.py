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
    return result


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
