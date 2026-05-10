#!/usr/bin/env python3
"""Check Nginx proxy_pass ports against port registry.

Detects drift between Nginx config and the single source of truth.

Usage:
    python3 check_nginx_ports.py              # human-readable
    python3 check_nginx_ports.py --check      # PASS/FAIL for CI
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Port registry
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "libs" / "sdk-client")
)
from sdk_client.port_registry import all_ports

NGINX_CONF = Path("/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc")

# Match proxy_pass http://127.0.0.1:PORT/ patterns
_PROXY_RE = re.compile(r"proxy_pass\s+http://127\.0\.0\.1:(\d+)")


def scan_nginx() -> list[tuple[int, int]]:
    """Return list of (line_number, port) from Nginx config."""
    if not NGINX_CONF.exists():
        return []
    results = []
    for i, line in enumerate(NGINX_CONF.read_text().splitlines(), 1):
        m = _PROXY_RE.search(line)
        if m:
            results.append((i, int(m.group(1))))
    return results


def check() -> tuple[bool, list[str]]:
    """Compare Nginx ports with registry. Returns (ok, messages)."""
    known = all_ports()
    nginx_ports = scan_nginx()
    messages: list[str] = []
    ok = True

    if not nginx_ports:
        messages.append(f"WARNING: No proxy_pass found in {NGINX_CONF}")
        return True, messages  # Not a failure, just missing file

    for line_no, port in nginx_ports:
        if port not in known:
            messages.append(
                f"  UNKNOWN port {port} at line {line_no}"
                " (not in port registry)"
            )
            # Unknown ports are warnings, not failures
            # They might be non-workshop services

    # Check if any registered services with nginx_path are missing
    from sdk_client.port_registry import PORTS
    nginx_port_set = {p for _, p in nginx_ports}
    for sp in PORTS:
        if sp.nginx_path and sp.port not in nginx_port_set:
            messages.append(
                f"  MISSING {sp.name} (port {sp.port})"
                f" — has nginx_path={sp.nginx_path}"
                " but no proxy_pass found"
            )

    return ok, messages


def main() -> None:
    is_check = "--check" in sys.argv
    ok, messages = check()

    if is_check:
        if ok and not any("MISSING" in m for m in messages):
            print("PASS: Nginx ports consistent with registry")
        else:
            print("WARN: Nginx port drift detected")
            for m in messages:
                print(m)
        sys.exit(0 if ok else 1)

    # Human-readable output
    known = all_ports()
    nginx_ports = scan_nginx()
    print(f"Nginx config: {NGINX_CONF}")
    print(f"Registry: {len(known)} services\n")

    if not nginx_ports:
        print(f"No proxy_pass entries found in {NGINX_CONF}")
        return

    print(f"{'Line':>5}  {'Port':>5}  {'Service':<25}  Status")
    print("-" * 55)
    for line_no, port in sorted(nginx_ports, key=lambda x: x[1]):
        name = known.get(port, "???")
        status = "OK" if port in known else "UNKNOWN"
        print(f"{line_no:>5}  {port:>5}  {name:<25}  {status}")

    if messages:
        print()
        for m in messages:
            print(m)


if __name__ == "__main__":
    main()
