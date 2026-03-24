#!/usr/bin/env python3
"""
Port Security Audit: verify Workshop services bind to 127.0.0.1,
detect unexpected listeners, and report missing services.

Usage:
    python3 port_audit.py              # human-readable (default)
    python3 port_audit.py --check      # PASS/FAIL for Sentinel
    python3 port_audit.py --json       # JSON report
    python3 port_audit.py --verbose    # detailed table
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# ── Expected ports from port_registry (single source of truth) ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "libs" / "python" / "src"))
from workshop.port_registry import all_ports

EXPECTED_PORTS: dict[int, str] = all_ports()

# System ports to ignore (not Workshop-managed)
SYSTEM_PORTS = {22, 5000, 7000, 3025}
EPHEMERAL_START = 49152


def _scan_listeners() -> list[dict]:
    """Get all TCP listeners via lsof."""
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    listeners: list[dict] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        cmd = parts[0]
        pid = parts[1]
        name_col = parts[8]
        if ":" not in name_col:
            continue
        host, port_str = name_col.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            continue
        listeners.append({
            "command": cmd,
            "pid": pid,
            "host": host,
            "port": port,
        })
    return listeners


def audit() -> dict:
    """Run audit and return structured report."""
    listeners = _scan_listeners()
    listener_by_port: dict[int, list[dict]] = {}
    for entry in listeners:
        listener_by_port.setdefault(entry["port"], []).append(entry)

    critical: list[str] = []
    warnings: list[str] = []
    info: list[str] = []

    # Check 1: Workshop services bound to 0.0.0.0
    for port, svc_name in EXPECTED_PORTS.items():
        entries = listener_by_port.get(port, [])
        for entry in entries:
            if entry["host"] == "*":
                critical.append(
                    f"{svc_name} (:{port}) bound to 0.0.0.0 — LAN exposed "
                    f"[{entry['command']} PID {entry['pid']}]"
                )

    # Check 2: Unknown ports listening
    known_ports = set(EXPECTED_PORTS.keys()) | SYSTEM_PORTS
    for port, entries in listener_by_port.items():
        if port in known_ports or port >= EPHEMERAL_START:
            continue
        for entry in entries:
            # Skip Docker-internal and common system processes
            if entry["command"] in ("com.docke", "docker", "Tailscale", "LogiMgrDa", "OrbStack"):
                continue
            warnings.append(
                f"Unknown listener :{port} [{entry['command']} PID {entry['pid']} "
                f"bind={entry['host']}]"
            )

    # Check 3: Expected services not listening
    for port, svc_name in EXPECTED_PORTS.items():
        if port not in listener_by_port:
            info.append(f"{svc_name} (:{port}) not listening")

    return {
        "critical": critical,
        "warnings": warnings,
        "info": info,
        "total_listeners": len(listeners),
    }


def main() -> None:
    report = audit()

    if "--check" in sys.argv:
        # Sentinel-compatible output
        if report["critical"]:
            print(f"FAIL: {'; '.join(report['critical'])}")
            sys.exit(1)
        print("PASS")
        sys.exit(0)

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        sys.exit(1 if report["critical"] else 0)

    # Human-readable output
    print(f"\nPort Security Audit ({report['total_listeners']} listeners)")
    print("=" * 60)

    if report["critical"]:
        print("\n🔴 CRITICAL:")
        for msg in report["critical"]:
            print(f"  • {msg}")
    else:
        print("\n✅ No critical issues (all Workshop services on 127.0.0.1)")

    if report["warnings"]:
        print("\n🟡 WARNINGS:")
        for msg in report["warnings"]:
            print(f"  • {msg}")

    if "--verbose" in sys.argv and report["info"]:
        print("\nINFO:")
        for msg in report["info"]:
            print(f"  • {msg}")

    print()
    sys.exit(1 if report["critical"] else 0)


if __name__ == "__main__":
    main()
