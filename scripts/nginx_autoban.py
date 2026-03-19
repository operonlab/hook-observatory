#!/usr/bin/env python3
"""
Nginx Auto-Ban: analyse access log for 429 rate-limit hits,
auto-add offending IPs to blocklist.conf, and reload Nginx.

Usage:
    python3 nginx_autoban.py             # normal run
    python3 nginx_autoban.py --dry-run   # preview only, no writes
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
WINDOW_MINUTES = 5
BAN_THRESHOLD = 10          # 429 count within window
BAN_DURATION_HOURS = 24
LOG_PATH = Path("/opt/homebrew/var/log/nginx/workshop.access.log")
BLOCKLIST_PATH = Path("/opt/homebrew/etc/nginx/conf.d/blocklist.conf")
AUTOBAN_LOG = Path("/opt/homebrew/var/log/nginx/auto-ban.log")
REDIS_PUSH_CHANNEL = "workshop:push"

# IPs / networks that must never be banned
WHITELIST_NETS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),   # Tailscale
    ipaddress.ip_network("::1/128"),
]

# Nginx log format: IP [timestamp] "request" status ...
_LOG_RE = re.compile(
    r'^(?P<ip>\S+)\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"[^"]*"\s+'
    r'(?P<status>\d+)\s+'
)
_TIME_FMT = "%d/%b/%Y:%H:%M:%S %z"


def _is_whitelisted(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # can't parse → don't ban
    return any(addr in net for net in WHITELIST_NETS)


def _parse_recent_429s(window_start: datetime) -> dict[str, int]:
    """Count 429 responses per IP since window_start."""
    counts: dict[str, int] = {}
    if not LOG_PATH.exists():
        return counts

    # Read last ~50K lines (sufficient for 5-minute window at high traffic)
    with open(LOG_PATH, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        seek_back = min(size, 5 * 1024 * 1024)  # last 5MB
        f.seek(size - seek_back)
        if seek_back < size:
            f.readline()  # discard partial line
        lines = f.readlines()

    for raw in lines:
        line = raw.decode("utf-8", errors="replace")
        m = _LOG_RE.match(line)
        if not m:
            continue
        if m.group("status") != "429":
            continue
        try:
            ts = datetime.strptime(m.group("time"), _TIME_FMT)
        except ValueError:
            continue
        if ts < window_start:
            continue
        ip = m.group("ip")
        if not _is_whitelisted(ip):
            counts[ip] = counts.get(ip, 0) + 1
    return counts


def _load_blocklist() -> tuple[str, set[str]]:
    """Return (raw content, set of currently banned IPs)."""
    if not BLOCKLIST_PATH.exists():
        return "", set()
    content = BLOCKLIST_PATH.read_text()
    banned: set[str] = set()
    for line in content.splitlines():
        m = re.match(r"^deny\s+(\S+);", line)
        if m:
            banned.add(m.group(1))
    return content, banned


def _expire_old_bans(content: str) -> str:
    """Remove expired auto-ban entries."""
    now = int(time.time())
    lines = content.splitlines()
    kept: list[str] = []
    for line in lines:
        m = re.search(r"expires=(\d+)", line)
        if m and int(m.group(1)) < now:
            continue  # expired
        kept.append(line)
    return "\n".join(kept) + "\n" if kept else ""


def _notify(message: str) -> None:
    """Publish ban alert via Redis → Core fan-out pipeline."""
    try:
        import json
        import socket

        payload = json.dumps({
            "category": "system",
            "title": "Nginx Auto-Ban",
            "body": message,
            "tag": "nginx-autoban",
            "severity": "warning",
        })
        # Inline RESP PUBLISH (no redis-py dependency)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("127.0.0.1", 6379))
        ch = REDIS_PUSH_CHANNEL
        parts = f"*3\r\n$7\r\nPUBLISH\r\n${len(ch)}\r\n{ch}\r\n"
        parts += f"${len(payload)}\r\n{payload}\r\n"
        sock.sendall(parts.encode())
        sock.recv(256)
        sock.close()
    except Exception:  # noqa: S110
        pass


def _log_action(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(AUTOBAN_LOG, "a") as f:
        f.write(f"[{ts}] {message}\n")


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    now = datetime.now().astimezone()
    window_start = now - timedelta(minutes=WINDOW_MINUTES)
    expires_epoch = int(time.time()) + BAN_DURATION_HOURS * 3600

    # 1. Count 429s per IP
    counts = _parse_recent_429s(window_start)

    # 2. Load & clean blocklist
    content, banned = _load_blocklist()
    content = _expire_old_bans(content)

    # 3. Find new offenders
    new_bans: list[str] = []
    for ip, count in counts.items():
        if count >= BAN_THRESHOLD and ip not in banned:
            new_bans.append(ip)

    if not new_bans and not dry_run:
        # Still write cleaned blocklist (expired entries removed)
        if content != BLOCKLIST_PATH.read_text() if BLOCKLIST_PATH.exists() else "":
            BLOCKLIST_PATH.write_text(content)
            subprocess.run(
                ["/opt/homebrew/bin/nginx", "-s", "reload"],
                capture_output=True,
                timeout=10,
            )
        return

    if dry_run:
        print(f"Window: last {WINDOW_MINUTES} min | Threshold: {BAN_THRESHOLD}")
        print(f"429 counts: {counts}")
        print(f"New bans would be: {new_bans}")
        return

    # 4. Add new bans
    for ip in new_bans:
        count = counts[ip]
        ts_str = now.strftime("%Y-%m-%d %H:%M")
        content += f"deny {ip};  # auto-ban {ts_str} 429x{count} expires={expires_epoch}\n"
        _log_action(f"BANNED {ip} (429x{count}/{WINDOW_MINUTES}min, expires={expires_epoch})")
        _notify(f"Banned {ip} — {count}x 429 in {WINDOW_MINUTES}min ({BAN_DURATION_HOURS}h)")

    # 5. Write & reload
    BLOCKLIST_PATH.write_text(content)
    result = subprocess.run(
        ["/opt/homebrew/bin/nginx", "-s", "reload"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        _log_action(f"ERROR: nginx reload failed: {result.stderr}")
    else:
        _log_action(f"Nginx reloaded — {len(new_bans)} new ban(s)")


if __name__ == "__main__":
    main()
