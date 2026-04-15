#!/usr/bin/env python3
"""CLI dictionary query interface — show, compare, check."""

from __future__ import annotations

import argparse
import sys

from cli_rosetta.health import check_all, check_one
from cli_rosetta.registry import get, list_entries


def _show(args: argparse.Namespace) -> None:
    try:
        entry = get(args.name)
    except KeyError:
        print(f"❌ Unknown CLI: {args.name}", file=sys.stderr)
        sys.exit(1)

    section = args.section

    if not section or section == "all":
        print(f"{entry.display_name} ({entry.vendor})")
        print(f"  binary:       {entry.binary}")
        print(f"  exit:         {entry.exit_description()}")
        h = entry.headless
        headless_str = f"{entry.binary}"
        if h.subcommand:
            headless_str += f" {h.subcommand}"
        if h.prompt_flag:
            headless_str += f' {h.prompt_flag} "prompt"'
        else:
            headless_str += ' "prompt"'
        print(f"  headless:     {headless_str}")
        print(f"  auto-approve: {entry.auto_approve.flag or 'N/A'}")
        print(f"  model:        {entry.model_flag} (default: {entry.default_model or 'N/A'})")
        print(f"  config:       {entry.config_dir or 'N/A'}")

        hr = check_one(entry)
        if hr.installed:
            ver = hr.current_version or "?"
            tag = " ⚠️ outdated" if hr.outdated else ""
            print(f"  installed:    ✅ v{ver}{tag}")
        else:
            print("  installed:    ❌ not found")
        return

    if section == "exit":
        print(f"{entry.display_name}: {entry.exit_description()}")
    elif section == "headless":
        cmd = entry.headless_cmd("YOUR_PROMPT", auto_approve=True)
        print(f"{entry.display_name}: {' '.join(cmd)}")
    elif section == "auto-approve":
        print(f"{entry.display_name}: {entry.auto_approve.flag}")
        if entry.auto_approve.aliases:
            print(f"  aliases: {', '.join(entry.auto_approve.aliases)}")
    elif section == "model":
        print(f"{entry.display_name}: {entry.model_flag} (default: {entry.default_model})")


def _compare(args: argparse.Namespace) -> None:
    aspect = args.aspect
    entries = list_entries()

    title_map = {
        "exit": "Exit Commands",
        "headless": "Headless Mode",
        "auto-approve": "Auto-Approve Flags",
        "model": "Model Selection",
        "mcp": "MCP Configuration",
        "hooks": "Hook Events",
        "skills": "Skill System",
        "instructions": "Instruction Files",
        "agents": "Agent Definitions",
        "config": "Full Config Ecosystem",
    }
    print(f"{title_map.get(aspect, aspect)}:")

    for e in entries:
        if aspect == "exit":
            print(f"  {e.name:>15}:  {e.exit_description()}")
        elif aspect == "headless":
            cmd = e.headless_cmd("PROMPT", auto_approve=True)
            print(f"  {e.name:>15}:  {' '.join(cmd)}")
        elif aspect == "auto-approve":
            print(f"  {e.name:>15}:  {e.auto_approve.flag}")
        elif aspect == "model":
            print(f"  {e.name:>15}:  {e.model_flag} (default: {e.default_model})")
        elif aspect == "mcp":
            m = e.mcp
            print(
                f"  {e.name:>15}:  {m.config_path} ({m.config_format})"
                f"  key={m.config_key}  http={m.supports_http}"
            )
        elif aspect == "hooks":
            h = e.hooks
            print(f"  {e.name:>15}:  {h.config_path} ({h.config_format})")
            print(f"  {'':>15}   events: {', '.join(h.events)}")
        elif aspect == "skills":
            s = e.skills
            print(f"  {e.name:>15}:  {e.config_dir}{s.dir_name}/{s.file_name}")
        elif aspect == "instructions":
            i = e.instructions
            print(
                f"  {e.name:>15}:  global={i.global_file}"
                f"  project={i.project_file}  rules={i.rules_dir or 'N/A'}"
            )
        elif aspect == "agents":
            a = e.agents
            print(f"  {e.name:>15}:  {e.config_dir}{a.dir_name}/*.{a.file_format}")
        elif aspect == "config":
            _print_config_summary(e)


def _print_config_summary(e) -> None:
    """Print full config ecosystem for one CLI."""
    print(f"  {e.name:>15}:")
    m = e.mcp
    print(
        f"    MCP:          {m.config_path} ({m.config_format}) key={m.config_key}"
        f"  http={m.supports_http}"
    )
    h = e.hooks
    print(f"    Hooks:        {h.config_path} ({h.config_format})  {len(h.events)} events")
    s = e.skills
    print(f"    Skills:       {e.config_dir}{s.dir_name}/{s.file_name}")
    i = e.instructions
    print(f"    Instructions: global={i.global_file}  project={i.project_file}")
    a = e.agents
    fmt = f"{e.config_dir}{a.dir_name}/*.{a.file_format}" if a.dir_name else "N/A"
    print(f"    Agents:       {fmt}")


def _versions() -> None:
    from cli_rosetta.probe import check_all_versions

    print("CLI Version Drift Check:")
    versions = check_all_versions()
    for v in versions:
        drift = " ⚡ UPDATE AVAILABLE" if v.has_drift else ""
        stale = " ⚠️ entry stale" if v.entry_stale else ""
        remote = v.remote or "?"
        installed = v.installed or "not installed"
        print(f"  {v.cli_name:>15}  installed={installed}  remote={remote}{drift}{stale}")


def _probe(args: argparse.Namespace) -> None:
    from cli_rosetta.probe import probe_cli

    try:
        entry = get(args.name)
    except KeyError:
        print(f"❌ Unknown CLI: {args.name}", file=sys.stderr)
        sys.exit(1)

    from cli_rosetta.probe import check_remote_version

    remote = check_remote_version(entry)
    report = probe_cli(entry, remote or entry.known_version)

    print(f"Probe: {entry.display_name}")
    print(f"  Known: {entry.known_version}  Remote: {remote or '?'}")

    hd = report.help_diff
    if hd and hd.has_changes:
        if hd.new_flags:
            print(f"  🆕 New flags: {', '.join(sorted(hd.new_flags))}")
        if hd.removed_flags:
            print(f"  🗑️  Removed flags: {', '.join(sorted(hd.removed_flags))}")
    else:
        print("  ✅ No flag changes detected")

    if report.changelog_url:
        print(f"  📋 Changelog: {report.changelog_url}")


def _check(_args: argparse.Namespace) -> None:
    print("CLI Health Check:")
    results = check_all()
    for hr in results:
        if not hr.installed:
            print(f"  ❌ {hr.entry.name:>15}  not installed")
        elif hr.outdated:
            print(
                f"  ⚠️  {hr.entry.name:>15}  v{hr.current_version}"
                f"  (known: v{hr.entry.known_version})"
            )
        else:
            ver = hr.current_version or "?"
            known = f"  (known: v{hr.entry.known_version})" if hr.entry.known_version else ""
            print(f"  ✅ {hr.entry.name:>15}  v{ver}{known}")


def main() -> None:
    p = argparse.ArgumentParser(prog="cli-rosetta", description="CLI tool dictionary")
    sub = p.add_subparsers(dest="cmd")

    sp_show = sub.add_parser("show", help="Show CLI tool info")
    sp_show.add_argument("name", help="CLI name or alias (e.g., claude, codex, gemini)")
    sp_show.add_argument(
        "section",
        nargs="?",
        default="all",
        choices=[
            "all",
            "exit",
            "headless",
            "auto-approve",
            "model",
            "mcp",
            "hooks",
            "skills",
            "instructions",
            "agents",
        ],
    )

    sp_cmp = sub.add_parser("compare", help="Compare CLIs side-by-side")
    sp_cmp.add_argument(
        "aspect",
        choices=[
            "exit",
            "headless",
            "auto-approve",
            "model",
            "mcp",
            "hooks",
            "skills",
            "instructions",
            "agents",
            "config",
        ],
    )

    sub.add_parser("check", help="Health check — version + staleness")

    sub.add_parser("list", help="List all registered CLIs")

    sub.add_parser("versions", help="Check installed vs remote versions (drift detection)")

    sp_probe = sub.add_parser("probe", help="Probe a CLI for --help flag changes")
    sp_probe.add_argument("name", help="CLI name or alias")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)

    if args.cmd == "show":
        _show(args)
    elif args.cmd == "compare":
        _compare(args)
    elif args.cmd == "check":
        _check(args)
    elif args.cmd == "list":
        for e in list_entries():
            print(f"  {e.name:>15}  {e.display_name} ({e.vendor})")
    elif args.cmd == "versions":
        _versions()
    elif args.cmd == "probe":
        _probe(args)


if __name__ == "__main__":
    main()
