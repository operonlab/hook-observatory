#!/usr/bin/env python3
"""Check Rust/Go source code for hardcoded ports that drift from shared/schemas/port_registry.yaml.

Detects 127.0.0.1:PORT or localhost:PORT literals in station source files
and validates them against the cross-language port registry YAML.

Usage:
    python3 scripts/check_schema_drift.py              # human-readable table
    python3 scripts/check_schema_drift.py --check      # PASS/FAIL for CI (exit 0/1)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:
    # Fallback: minimal YAML parser for this specific schema (list of dicts under `services`)
    yaml = None  # type: ignore[assignment]

# ── Paths ──────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_YAML_PATH = _REPO_ROOT / "shared" / "schemas" / "port_registry.yaml"

# Rust station source directories to scan
RUST_DIRS: list[str] = [
    "stations/sentinel-rs/src",
    "stations/agent-metrics/src",
    "stations/system-monitor-rs/src",
    "stations/auto-survey-rs/src",
    "stations/remote-node/src",
]

# Go station source directories to scan
GO_DIRS: list[str] = [
    "stations/hook-dispatcher/internal",
    "stations/agent-vista/internal",
]

# ── Regex ──────────────────────────────────────────────────────

# Match 127.0.0.1:PORT or localhost:PORT (4-5 digit port)
_PORT_RE = re.compile(r"(?:127\.0\.0\.1|localhost):(\d{4,5})\b")

# Sentinel-rs registry.rs special rule: 127.0.0.1:1XXXX (10000-19999) except 8080
_SENTINEL_HARDCODE_RE = re.compile(r"127\.0\.0\.1:1[0-9]{4}\b")

# Comment line patterns (skip these — no false positives from docs)
_RUST_COMMENT_RE = re.compile(r"^\s*//")
_GO_COMMENT_RE = re.compile(r"^\s*//")


# ── Types ──────────────────────────────────────────────────────


class Hit(NamedTuple):
    rel_path: str
    line_no: int
    port: int
    status: str  # "OK" or "UNKNOWN"
    service_name: str  # name from YAML if known, else ""


# ── YAML loader ────────────────────────────────────────────────


def _load_yaml_minimal(path: Path) -> dict:
    """Minimal YAML parser that only handles this specific schema (no deps)."""
    import re as _re

    text = path.read_text()
    services = []
    in_services = False
    current: dict | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped == "services:":
            in_services = True
            continue
        if not in_services:
            continue
        # New service block
        if stripped.startswith("- name:"):
            if current is not None:
                services.append(current)
            current = {"name": stripped.split(":", 1)[1].strip()}
        elif current is not None and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "port":
                try:
                    current["port"] = int(val)
                except ValueError:
                    pass
            else:
                current[key] = val

    if current is not None:
        services.append(current)

    return {"services": services}


def load_known_ports(yaml_path: Path) -> dict[int, str]:
    """Return {port: service_name} from port_registry.yaml."""
    if not yaml_path.exists():
        return {}

    if yaml is not None:
        data = yaml.safe_load(yaml_path.read_text())
    else:
        data = _load_yaml_minimal(yaml_path)

    known: dict[int, str] = {}
    for svc in data.get("services", []):
        port = svc.get("port")
        name = svc.get("name", "?")
        if isinstance(port, int):
            known[port] = name
    return known


# ── Scanner ────────────────────────────────────────────────────


def scan_file(
    path: Path,
    rel_path: str,
    known_ports: dict[int, str],
    comment_re: re.Pattern,
) -> list[Hit]:
    """Scan one source file for port literals. Returns list of Hit."""
    hits: list[Hit] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return hits

    for line_no, line in enumerate(lines, 1):
        # Skip comment lines
        if comment_re.match(line):
            continue
        for m in _PORT_RE.finditer(line):
            port = int(m.group(1))
            if port in known_ports:
                status = "OK"
                service_name = known_ports[port]
            else:
                status = "UNKNOWN"
                service_name = ""
            hits.append(Hit(rel_path, line_no, port, status, service_name))

    return hits


def scan_dirs(known_ports: dict[int, str]) -> list[Hit]:
    """Scan all Rust and Go source directories."""
    all_hits: list[Hit] = []

    for dir_str in RUST_DIRS:
        d = _REPO_ROOT / dir_str
        if not d.exists():
            continue
        for rs_file in d.rglob("*.rs"):
            rel = str(rs_file.relative_to(_REPO_ROOT))
            all_hits.extend(scan_file(rs_file, rel, known_ports, _RUST_COMMENT_RE))

    for dir_str in GO_DIRS:
        d = _REPO_ROOT / dir_str
        if not d.exists():
            continue
        for go_file in d.rglob("*.go"):
            rel = str(go_file.relative_to(_REPO_ROOT))
            all_hits.extend(scan_file(go_file, rel, known_ports, _GO_COMMENT_RE))

    return all_hits


# ── Special rule: sentinel-rs registry.rs ─────────────────────


def check_sentinel_registry_hardcodes() -> tuple[int, list[str]]:
    """
    sentinel-rs/src/checker/registry.rs must NOT contain 127.0.0.1:1XXXX literals
    (after Phase 3 migration). Returns (count, list_of_matching_lines).
    Port 8080 (nginx frontend) is exempt.
    """
    registry_path = (
        _REPO_ROOT / "stations" / "sentinel-rs" / "src" / "checker" / "registry.rs"
    )
    if not registry_path.exists():
        return 0, []

    violations: list[str] = []
    lines = registry_path.read_text(errors="replace").splitlines()
    for line_no, line in enumerate(lines, 1):
        if _RUST_COMMENT_RE.match(line):
            continue
        for m in _SENTINEL_HARDCODE_RE.finditer(line):
            matched_port = int(m.group(0).split(":")[1])
            # 8080 (nginx frontend route) is explicitly allowed
            if matched_port == 8080:
                continue
            violations.append(
                f"  line {line_no:4d}: {line.strip()[:120]}"
            )

    return len(violations), violations


# ── Output formatters ──────────────────────────────────────────


def group_hits_by_station(hits: list[Hit]) -> dict[str, list[Hit]]:
    """Group hits by top-level station directory."""
    grouped: dict[str, list[Hit]] = {}
    for h in hits:
        parts = h.rel_path.split("/")
        key = parts[1] if len(parts) > 1 else parts[0]
        grouped.setdefault(key, []).append(h)
    return grouped


def print_human(hits: list[Hit], sentinel_fail: int, sentinel_lines: list[str]) -> None:
    known_count = sum(1 for h in hits if h.status == "OK")
    unknown_count = sum(1 for h in hits if h.status == "UNKNOWN")

    print(f"Port registry: {_YAML_PATH.relative_to(_REPO_ROOT)}")
    print(f"Total hits: {len(hits)}  (OK: {known_count}, UNKNOWN: {unknown_count})")
    print()

    grouped = group_hits_by_station(hits)

    if not hits:
        print("  No 127.0.0.1/localhost port literals found in scan scope.")
    else:
        col_file = 55
        col_line = 6
        col_port = 7
        col_svc = 25
        col_stat = 8
        header = (
            f"{'File':<{col_file}}  {'Line':>{col_line}}  {'Port':>{col_port}}"
            f"  {'Service':<{col_svc}}  {'Status':<{col_stat}}"
        )
        sep = "-" * len(header)

        for station, station_hits in sorted(grouped.items()):
            print(f"[{station}]")
            print(header)
            print(sep)
            for h in sorted(station_hits, key=lambda x: (x.rel_path, x.line_no)):
                fname = h.rel_path
                if len(fname) > col_file:
                    fname = "..." + fname[-(col_file - 3):]
                print(
                    f"{fname:<{col_file}}  {h.line_no:>{col_line}}  {h.port:>{col_port}}"
                    f"  {h.service_name:<{col_svc}}  {h.status:<{col_stat}}"
                )
            print()

    # Sentinel special rule result
    sentinel_path = "stations/sentinel-rs/src/checker/registry.rs"
    print(f"[Sentinel-rs registry hardcode check]")
    print(f"  File: {sentinel_path}")
    if sentinel_fail == 0:
        print("  PASS: No hardcoded 127.0.0.1:1XXXX literals (8080 exempt).")
    else:
        print(f"  FAIL: {sentinel_fail} hardcoded port(s) found — Phase 3 migration incomplete:")
        for ln in sentinel_lines[:20]:
            print(ln)
        if len(sentinel_lines) > 20:
            print(f"  ... ({len(sentinel_lines) - 20} more)")
    print()


def print_check(
    hits: list[Hit], sentinel_fail: int, sentinel_lines: list[str]
) -> bool:
    """Print PASS/FAIL summary line. Returns True if overall OK."""
    unknown_count = sum(1 for h in hits if h.status == "UNKNOWN")
    ok = sentinel_fail == 0
    # Unknown ports are warnings, not failures (may be non-workshop services)
    if ok:
        print(f"PASS: schema drift check OK (sentinel registry hardcodes: 0)")
    else:
        print(
            f"FAIL: sentinel-rs/checker/registry.rs has {sentinel_fail}"
            f" hardcoded port(s) — Phase 3 migration incomplete"
        )
        for ln in sentinel_lines[:10]:
            print(ln)
    if unknown_count > 0:
        print(f"WARN: {unknown_count} UNKNOWN port hit(s) (not in registry — may be non-workshop)")
    return ok


# ── Main ───────────────────────────────────────────────────────


def main() -> None:
    is_check = "--check" in sys.argv

    known_ports = load_known_ports(_YAML_PATH)
    if not known_ports:
        if is_check:
            print(f"FAIL: Could not load {_YAML_PATH}")
            sys.exit(1)
        else:
            print(f"ERROR: Could not load {_YAML_PATH}")
            return

    hits = scan_dirs(known_ports)
    sentinel_fail, sentinel_lines = check_sentinel_registry_hardcodes()

    if is_check:
        ok = print_check(hits, sentinel_fail, sentinel_lines)
        sys.exit(0 if ok else 1)
    else:
        print_human(hits, sentinel_fail, sentinel_lines)


if __name__ == "__main__":
    main()
