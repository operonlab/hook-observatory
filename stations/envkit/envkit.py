#!/usr/bin/env python3
"""
EnvKit — macOS environment snapshot, backup, verify, and diff tool.

Usage:
    python3 envkit.py snapshot [--output FILE]
    python3 envkit.py backup [--output-dir DIR]
    python3 envkit.py verify <snapshot.yaml>
    python3 envkit.py diff <a.yaml> <b.yaml>
    python3 envkit.py list [category]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


# ---------------------------------------------------------------------------
# Simple YAML serializer / deserializer (no PyYAML dependency)
# ---------------------------------------------------------------------------


def to_yaml(data, indent: int = 0) -> str:
    """Serialize Python dicts/lists/scalars to simple YAML."""
    prefix = "  " * indent
    lines: list[str] = []

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict,)):
                lines.append(f"{prefix}{key}:")
                lines.append(to_yaml(value, indent + 1))
            elif isinstance(value, list):
                lines.append(f"{prefix}{key}:")
                if not value:
                    lines.append(f"{prefix}  []")
                else:
                    for item in value:
                        if isinstance(item, dict):
                            # Inline dict as mapping under list
                            first = True
                            for k, v in item.items():
                                if first:
                                    lines.append(f"{prefix}  - {k}: {_yaml_scalar(v)}")
                                    first = False
                                else:
                                    lines.append(f"{prefix}    {k}: {_yaml_scalar(v)}")
                        else:
                            lines.append(f"{prefix}  - {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                lines.append(to_yaml(item, indent))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
    else:
        lines.append(f"{prefix}{_yaml_scalar(data)}")

    return "\n".join(lines)


def _yaml_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # Quote strings that could be misinterpreted
    if (
        s in ("true", "false", "null", "yes", "no", "")
        or ":" in s
        or "#" in s
        or s.startswith(("'", '"', "[", "{"))
    ):
        return f'"{s}"'
    # Quote strings that look numeric to prevent float precision loss on round-trip
    if s:
        try:
            int(s)
            return f'"{s}"'
        except ValueError:
            pass
        try:
            float(s)
            return f'"{s}"'
        except ValueError:
            pass
    return s


def from_yaml(text: str) -> dict:
    """Parse the simple YAML format we generate.

    Handles:
    - key: value (scalars)
    - key: (nested dict, indented below)
    - list items: - value / - key: value
    """
    lines = text.splitlines()
    return _parse_yaml_block(lines, 0, 0)[0]


def _parse_yaml_block(lines: list[str], start: int, min_indent: int) -> tuple[dict, int]:
    result: dict = {}
    i = start

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = len(line) - len(stripped)
        if indent < min_indent:
            break

        if ":" in stripped and not stripped.startswith("- "):
            key, _, rest = stripped.partition(":")
            key = key.strip()
            rest = rest.strip()

            if rest and rest != "[]":
                result[key] = _parse_scalar(rest)
                i += 1
            elif rest == "[]":
                result[key] = []
                i += 1
            else:
                # Check if next line is a list or nested dict
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    next_stripped = next_line.lstrip()
                    next_indent = len(next_line) - len(next_stripped)

                    if next_indent > indent and next_stripped.startswith("- "):
                        # Parse list
                        items, i = _parse_yaml_list(lines, i + 1, next_indent)
                        result[key] = items
                    elif next_indent > indent:
                        # Parse nested dict
                        nested, i = _parse_yaml_block(lines, i + 1, next_indent)
                        result[key] = nested
                    else:
                        result[key] = ""
                        i += 1
                else:
                    result[key] = ""
                    i += 1
        else:
            i += 1

    return result, i


def _parse_yaml_list(lines: list[str], start: int, min_indent: int) -> tuple[list, int]:
    items: list = []
    i = start

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if indent < min_indent:
            break

        if stripped.startswith("- "):
            content = stripped[2:]
            if ":" in content:
                # Dict item in list
                item: dict = {}
                k, _, v = content.partition(":")
                item[k.strip()] = _parse_scalar(v.strip())
                # Read continuation lines (indented further)
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    ns = next_line.lstrip()
                    ni = len(next_line) - len(ns)
                    if not ns or ns.startswith("#"):
                        i += 1
                        continue
                    if ni <= indent or ns.startswith("- "):
                        break
                    if ":" in ns:
                        k2, _, v2 = ns.partition(":")
                        item[k2.strip()] = _parse_scalar(v2.strip())
                    i += 1
                items.append(item)
            else:
                items.append(_parse_scalar(content))
                i += 1
        else:
            break

    return items, i


def _parse_scalar(s: str):
    s = s.strip()
    if not s or s == "null":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Take a full environment snapshot."""
    from collectors import run_all_collectors

    snapshot = {
        "envkit_version": "2.0.0",
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    snapshot.update(run_all_collectors())

    output = to_yaml(snapshot)

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
        print(f"Snapshot saved to {out_path}", file=sys.stderr)
    else:
        print(output)


def cmd_backup(args: argparse.Namespace) -> None:
    """Backup Tier 1-2 config files."""
    from backup import backup_configs

    output_dir = Path(args.output_dir).expanduser()
    result = backup_configs(output_dir)

    print(f"Backed up: {result['backed_up_count']} items")
    print(f"Skipped:   {result['skipped_count']} items")
    print(f"Output:    {result['output_dir']}")
    print()
    for item in result["backed_up"]:
        print(f"  + {item}")
    for item in result["skipped"]:
        print(f"  - {item}")


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify current environment against a snapshot."""
    from collectors import run_all_collectors

    snap_path = Path(args.snapshot).expanduser()
    if not snap_path.exists():
        print(f"Error: snapshot not found: {snap_path}", file=sys.stderr)
        sys.exit(1)

    snapshot = from_yaml(snap_path.read_text(encoding="utf-8"))
    current = run_all_collectors()

    diffs = _compare_snapshots(snapshot, current)

    if not diffs:
        print("Environment matches snapshot.")
        sys.exit(0)

    print(f"Found {len(diffs)} difference(s):\n")
    for d in diffs:
        print(f"  [{d['category']}] {d['type']}: {d['detail']}")
    sys.exit(1)


def cmd_diff(args: argparse.Namespace) -> None:
    """Compare two snapshots."""
    path_a = Path(args.file_a).expanduser()
    path_b = Path(args.file_b).expanduser()

    for p in (path_a, path_b):
        if not p.exists():
            print(f"Error: file not found: {p}", file=sys.stderr)
            sys.exit(1)

    snap_a = from_yaml(path_a.read_text(encoding="utf-8"))
    snap_b = from_yaml(path_b.read_text(encoding="utf-8"))

    diffs = _compare_snapshots(snap_a, snap_b)

    if not diffs:
        print("Snapshots are identical.")
        return

    print(f"Found {len(diffs)} difference(s):\n")
    for d in diffs:
        print(f"  [{d['category']}] {d['type']}: {d['detail']}")


def cmd_list(args: argparse.Namespace) -> None:
    """List installed items by category."""
    from collectors import CATEGORY_ALIASES, run_collectors

    category = args.category or "all"
    keys = CATEGORY_ALIASES.get(category)
    if not keys:
        print(f"Unknown category: {category}", file=sys.stderr)
        print(f"Available: {', '.join(CATEGORY_ALIASES.keys())}", file=sys.stderr)
        sys.exit(1)

    data = run_collectors(keys)
    output = to_yaml(data)
    print(output)


# ---------------------------------------------------------------------------
# Diff logic
# ---------------------------------------------------------------------------


def _compare_snapshots(a: dict, b: dict) -> list[dict]:
    """Compare two snapshot dicts. Returns list of differences."""
    diffs: list[dict] = []

    # Compare package lists in known categories
    package_categories = {
        "homebrew_formulae": "packages",
        "homebrew_casks": "packages",
    }

    for cat, list_key in package_categories.items():
        a_data = a.get(cat, {})
        b_data = b.get(cat, {})

        a_pkgs = {
            p["name"]: p.get("version", "") for p in a_data.get(list_key, []) if isinstance(p, dict)
        }
        b_pkgs = {
            p["name"]: p.get("version", "") for p in b_data.get(list_key, []) if isinstance(p, dict)
        }

        for name in sorted(set(a_pkgs) - set(b_pkgs)):
            diffs.append({"category": cat, "type": "removed", "detail": f"{name} ({a_pkgs[name]})"})
        for name in sorted(set(b_pkgs) - set(a_pkgs)):
            diffs.append({"category": cat, "type": "added", "detail": f"{name} ({b_pkgs[name]})"})
        for name in sorted(set(a_pkgs) & set(b_pkgs)):
            if a_pkgs[name] != b_pkgs[name]:
                diffs.append(
                    {
                        "category": cat,
                        "type": "version_changed",
                        "detail": f"{name}: {a_pkgs[name]} -> {b_pkgs[name]}",
                    }
                )

    # Compare app lists
    for cat, list_key in [("apps", "applications"), ("node", "npm_global")]:
        a_items = a.get(cat, {})
        b_items = b.get(cat, {})
        a_names = {p["name"] for p in a_items.get(list_key, []) if isinstance(p, dict)}
        b_names = {p["name"] for p in b_items.get(list_key, []) if isinstance(p, dict)}
        for name in sorted(a_names - b_names):
            diffs.append({"category": cat, "type": "removed", "detail": name})
        for name in sorted(b_names - a_names):
            diffs.append({"category": cat, "type": "added", "detail": name})

    # Compare CLI tools (presence check)
    a_cli = a.get("cli_tools", {})
    b_cli = b.get("cli_tools", {})
    for group in set(list(a_cli.keys()) + list(b_cli.keys())):
        if group in ("total_count", "error"):
            continue
        a_tools = {t["name"] for t in a_cli.get(group, []) if isinstance(t, dict)}
        b_tools = {t["name"] for t in b_cli.get(group, []) if isinstance(t, dict)}
        for name in sorted(a_tools - b_tools):
            diffs.append({"category": f"cli_tools/{group}", "type": "removed", "detail": name})
        for name in sorted(b_tools - a_tools):
            diffs.append({"category": f"cli_tools/{group}", "type": "added", "detail": name})

    return diffs


def cmd_bootstrap(args) -> None:
    """Delegate to bootstrap/bootstrap.py."""
    import subprocess as sp

    bootstrap_script = SCRIPT_DIR / "bootstrap" / "bootstrap.py"
    cmd = [sys.executable, str(bootstrap_script), args.snapshot]
    if args.from_phase != 2:
        cmd.extend(["--from", str(args.from_phase)])
    if args.to_phase != 9:
        cmd.extend(["--to", str(args.to_phase)])
    if args.dry_run:
        cmd.append("--dry-run")
    sp.run(cmd)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="envkit",
        description="EnvKit — macOS environment management tool",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # snapshot
    p_snap = sub.add_parser("snapshot", help="Take a full environment snapshot")
    p_snap.add_argument("--output", "-o", help="Output file (default: stdout)")

    # backup
    p_bak = sub.add_parser("backup", help="Backup Tier 1-2 config files")
    p_bak.add_argument("--output-dir", default="configs/", help="Output directory")

    # verify
    p_ver = sub.add_parser("verify", help="Verify environment against a snapshot")
    p_ver.add_argument("snapshot", help="Path to snapshot YAML file")

    # diff
    p_diff = sub.add_parser("diff", help="Compare two snapshots")
    p_diff.add_argument("file_a", help="First snapshot file")
    p_diff.add_argument("file_b", help="Second snapshot file")

    # list
    p_list = sub.add_parser("list", help="List installed items by category")
    p_list.add_argument(
        "category",
        nargs="?",
        default="all",
        help="Category: all, brew, cask, python, node, shell, docker, apps, cli",
    )

    # bootstrap
    p_boot = sub.add_parser("bootstrap", help="Restore environment from snapshot")
    p_boot.add_argument("snapshot", help="Path to snapshot YAML file")
    p_boot.add_argument("--from", dest="from_phase", type=int, default=2, help="Start from phase N")
    p_boot.add_argument("--to", dest="to_phase", type=int, default=9, help="Stop at phase N")
    p_boot.add_argument("--dry-run", action="store_true", help="Preview without changes")

    args = parser.parse_args()
    commands = {
        "snapshot": cmd_snapshot,
        "backup": cmd_backup,
        "verify": cmd_verify,
        "diff": cmd_diff,
        "list": cmd_list,
        "bootstrap": cmd_bootstrap,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
