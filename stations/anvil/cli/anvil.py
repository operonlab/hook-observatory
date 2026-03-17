#!/Users/joneshong/.local/bin/python3
"""
Anvil -- Unified skill lifecycle management CLI.

Usage:
    anvil create <name>                     # Create skill scaffold
    anvil test <name>                       # Test skill structure (T1-T5)
    anvil scan <name>                       # Security scan skill (S1-S3)
    anvil eval <name> [--regression] [--runs N]
    anvil optimize <name>                   # Optimization guidance
    anvil curate                            # Analyze skills for overlap
    anvil catalog [--status S]              # List all skills
    anvil graph                             # Show skill I/O graph
    anvil publish <name>                    # Publish skill to GitHub
    anvil lifecycle <name>                  # Run full lifecycle
    anvil stats [--skill S] [--period P]    # Show usage statistics
    anvil history <name>                    # Show evaluation history
    anvil correct <name> [--level N]        # Self-correction
    anvil sync                              # Sync skills from filesystem

Symlink: ln -sf ~/workshop/stations/anvil/cli/anvil.py ~/.local/bin/anvil
"""

import argparse
import json
import sys

from workshop.clients.anvil import AnvilClient, AnvilError


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


# ======================== Command Handlers ========================


def cmd_create(args):
    """Create a new skill scaffold."""
    with AnvilClient() as client:
        result = client.create_skill_scaffold(args.name)
        if args.json:
            _json_out(result, True)
        else:
            if result.get("created"):
                print(f"Created skill: {args.name}")
                print(f"  Path: {result['path']}")
                print(f"  Files: {', '.join(result.get('created_files', []))}")
            else:
                print(f"Failed: {result.get('error', 'Unknown error')}")
                sys.exit(1)


def cmd_test(args):
    """Test skill structure (T1-T5)."""
    with AnvilClient() as client:
        result = client.test_skill_structure(args.name)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Skill: {result['name']}")
            print(f"Result: {result['passed']}/{result['passed'] + result['failed']} passed")
            print()
            for t in result.get("tests", []):
                icon = "PASS" if t["passed"] else "FAIL"
                print(f"  [{icon}] {t['id']}: {t['name']}")
                print(f"         {t['detail']}")
            print()
            if result["failed"] > 0:
                print(f"  {result['failed']} test(s) failed.")
                sys.exit(1)
            else:
                print("  All tests passed.")


def cmd_scan(args):
    """Security scan skill (S1-S3)."""
    with AnvilClient() as client:
        result = client.scan_skill_security(args.name)
        if args.json:
            _json_out(result, True)
        else:
            print(f"Skill: {result['name']}")
            print(f"Files scanned: {result['scanned_files']}")
            print()
            findings = result.get("findings", [])
            if not findings:
                print("  No security issues found.")
            else:
                print(f"  {len(findings)} finding(s):")
                print()
                print(f"  {'ID':<5} {'Severity':<10} {'Pattern':<35} {'File':<20} Line")
                print("  " + "-" * 80)
                for f in findings:
                    print(
                        f"  {f['id']:<5} {f['severity']:<10} {f['pattern']:<35} "
                        f"{f['file']:<20} {f['line']}"
                    )
                    print(f"         {f['context']}")
                print()
                sys.exit(1)


def cmd_eval(args):
    """Evaluate skill quality."""
    try:
        with AnvilClient() as client:
            results = []
            for run_num in range(1, args.runs + 1):
                result = client.trigger_eval(args.name)
                results.append(result)
                if args.runs > 1 and not args.json:
                    eval_id = result.get("eval_id", result.get("id", "?"))
                    status = result.get("status", "?")
                    print(f"  Run {run_num}/{args.runs}: {eval_id} ({status})")

            if args.json:
                if args.runs == 1:
                    _json_out(results[0], True)
                else:
                    _json_out(results, True)
            else:
                if args.runs == 1:
                    r = results[0]
                    eval_id = r.get("eval_id", r.get("id", "?"))
                    print(f"Evaluation triggered: {eval_id}")
                    print(f"  Skill: {args.name}")
                    print(f"  Status: {r.get('status', '?')}")
                    if r.get("score") is not None:
                        print(f"  Score: {r['score']}")
                else:
                    print(f"\n{args.runs} evaluation runs completed for {args.name}.")

                if args.regression:
                    print(
                        "\n  Regression mode: compare with previous baseline via 'anvil history'."
                    )
    except AnvilError as e:
        _err(e)


def cmd_optimize(args):
    """Print optimization guidance."""
    if args.json:
        _json_out(
            {
                "skill": args.name,
                "message": "Run /skill-optimizer or use 'anvil eval' first to identify optimization targets.",
                "suggestions": [
                    "anvil eval {name} --runs 3",
                    "anvil test {name}",
                    "anvil scan {name}",
                    "/skill-optimizer {name}",
                ],
            },
            True,
        )
    else:
        print(f"Optimization guidance for: {args.name}")
        print()
        print("  Anvil does not perform automatic optimization. Use these tools:")
        print()
        print(
            f"  1. anvil eval {args.name} --runs 3    Evaluate quality (multiple runs for stability)"
        )
        print(f"  2. anvil test {args.name}              Check structural compliance")
        print(f"  3. anvil scan {args.name}              Security audit")
        print(f"  4. /skill-optimizer {args.name}        Interactive optimization (in Claude Code)")
        print()
        print("  After evaluation, review results and apply corrections:")
        print(f"  5. anvil correct {args.name} --level 1")


def cmd_curate(args):
    """Analyze skills for overlap and redundancy."""
    try:
        with AnvilClient() as client:
            result = client.list_skills(limit=200)
            skills = result.get("skills", result.get("items", []))

            if args.json:
                # Build overlap analysis
                tag_groups: dict[str, list[str]] = {}
                for s in skills:
                    for tag in s.get("tags", []):
                        tag_groups.setdefault(tag, []).append(s.get("name", "?"))
                overlaps = {tag: names for tag, names in tag_groups.items() if len(names) > 1}
                _json_out(
                    {
                        "total_skills": len(skills),
                        "tag_overlaps": overlaps,
                        "orphan_skills": [s.get("name", "?") for s in skills if not s.get("tags")],
                    },
                    True,
                )
            else:
                print(f"Skill Curation Report ({len(skills)} skills)")
                print("=" * 50)

                # Group by tags
                tag_groups: dict[str, list[str]] = {}
                orphans: list[str] = []
                for s in skills:
                    tags = s.get("tags", [])
                    if not tags:
                        orphans.append(s.get("name", "?"))
                    for tag in tags:
                        tag_groups.setdefault(tag, []).append(s.get("name", "?"))

                # Find overlapping tag groups (potential redundancy)
                overlaps = {tag: names for tag, names in tag_groups.items() if len(names) > 1}
                if overlaps:
                    print("\nPotential Overlap (shared tags):")
                    for tag, names in sorted(overlaps.items(), key=lambda x: -len(x[1])):
                        print(f"  [{tag}] ({len(names)} skills): {', '.join(names[:5])}")
                        if len(names) > 5:
                            print(f"         ... and {len(names) - 5} more")

                if orphans:
                    print(f"\nOrphan Skills (no tags): {len(orphans)}")
                    for name in orphans[:10]:
                        print(f"  - {name}")
                    if len(orphans) > 10:
                        print(f"  ... and {len(orphans) - 10} more")

                if not overlaps and not orphans:
                    print("\n  No overlap or orphan issues detected.")
    except AnvilError as e:
        _err(e)


def cmd_catalog(args):
    """List all skills."""
    try:
        with AnvilClient() as client:
            result = client.list_skills(status=args.status, limit=200)
            skills = result.get("skills", result.get("items", []))

            if args.json:
                _json_out(result, True)
            else:
                if not skills:
                    print("No skills found.")
                    return
                print(f"{'Name':<30} {'Version':<10} {'Status':<10} {'Tags':<30} Description")
                print("-" * 100)
                for s in skills:
                    tags_str = ", ".join(s.get("tags", []))[:28]
                    desc = (s.get("description") or "")[:30]
                    print(
                        f"{s.get('name', '?'):<30} "
                        f"{s.get('version', '-'):<10} "
                        f"{s.get('status', '-'):<10} "
                        f"{tags_str:<30} "
                        f"{desc}"
                    )
                print(f"\nTotal: {len(skills)} skill(s)")
    except AnvilError as e:
        _err(e)


def cmd_graph(args):
    """Show skill I/O dependency graph."""
    try:
        with AnvilClient() as client:
            result = client.list_skills(limit=200)
            skills = result.get("skills", result.get("items", []))

            if args.json:
                # Build edges from io_schema
                edges: list[dict[str, str]] = []
                producers: dict[str, list[str]] = {}
                consumers: dict[str, list[str]] = {}

                for s in skills:
                    name = s.get("name", "?")
                    io = s.get("io_schema", {})
                    if not io:
                        continue
                    outputs = io.get("output", [])
                    inputs = io.get("input", [])
                    for out in outputs:
                        mime = out.get("mime", "")
                        if mime:
                            producers.setdefault(mime, []).append(name)
                    for inp in inputs:
                        mime = inp.get("mime", "")
                        if mime:
                            consumers.setdefault(mime, []).append(name)

                # Build edges: producer -> consumer via shared MIME type
                for mime, prods in producers.items():
                    cons = consumers.get(mime, [])
                    for p in prods:
                        for c in cons:
                            if p != c:
                                edges.append({"from": p, "to": c, "via": mime})

                _json_out({"edges": edges, "skills": len(skills)}, True)
            else:
                # Build ASCII graph
                producers: dict[str, list[str]] = {}
                consumers: dict[str, list[str]] = {}
                skill_io: dict[str, dict] = {}

                for s in skills:
                    name = s.get("name", "?")
                    io = s.get("io_schema", {})
                    if not io:
                        continue
                    skill_io[name] = io
                    for out in io.get("output", []):
                        mime = out.get("mime", "")
                        if mime:
                            producers.setdefault(mime, []).append(name)
                    for inp in io.get("input", []):
                        mime = inp.get("mime", "")
                        if mime:
                            consumers.setdefault(mime, []).append(name)

                print(f"Skill I/O Graph ({len(skills)} skills)")
                print("=" * 60)

                if not producers and not consumers:
                    print("\n  No skills with io_schema found.")
                    print("  Register skills with io_schema to see the dependency graph.")
                    return

                # Print edges grouped by MIME type
                printed_any = False
                for mime in sorted(set(list(producers.keys()) + list(consumers.keys()))):
                    prods = producers.get(mime, [])
                    cons = consumers.get(mime, [])
                    if prods and cons:
                        printed_any = True
                        print(f"\n  [{mime}]")
                        for p in prods:
                            for c in cons:
                                if p != c:
                                    print(f"    {p} --> {c}")

                if not printed_any:
                    print("\n  No edges found (no matching producer/consumer pairs).")
    except AnvilError as e:
        _err(e)


def cmd_publish(args):
    """Publish skill to GitHub."""
    if args.json:
        _json_out(
            {
                "skill": args.name,
                "status": "not_implemented",
                "message": "Use /skill-publisher for GitHub publishing.",
            },
            True,
        )
    else:
        print(f"Publishing: {args.name}")
        print()
        print("  Not yet implemented in CLI.")
        print("  Use /skill-publisher in Claude Code for GitHub publishing.")


def cmd_lifecycle(args):
    """Run full skill lifecycle."""
    if args.json:
        _json_out(
            {
                "skill": args.name,
                "status": "not_implemented",
                "message": "Use /skill-lifecycle for full lifecycle management.",
            },
            True,
        )
    else:
        print(f"Lifecycle: {args.name}")
        print()
        print("  Not yet implemented in CLI.")
        print("  Use /skill-lifecycle in Claude Code for full lifecycle management.")
        print()
        print("  Manual lifecycle steps:")
        print(f"    1. anvil create {args.name}")
        print(f"    2. anvil test {args.name}")
        print(f"    3. anvil scan {args.name}")
        print(f"    4. anvil eval {args.name}")
        print(f"    5. anvil correct {args.name}")
        print(f"    6. anvil publish {args.name}")


def cmd_stats(args):
    """Show usage statistics."""
    try:
        with AnvilClient() as client:
            if args.skill:
                result = client.get_skill_stats(args.skill)
                if args.json:
                    _json_out(result, True)
                else:
                    print(f"Stats for: {args.skill}")
                    print(f"  Total invocations: {result.get('total_invocations', 0)}")
                    success_rate = 100.0 - result.get("failure_rate", 0.0)
                    print(f"  Success rate: {success_rate:.1f}%")
                    print(f"  Avg duration: {result.get('avg_duration_ms', 0):.0f}ms")
                    print(f"  Last invoked: {result.get('last_invoked', '-')}")
                    if result.get("trend"):
                        print(f"  7d trend: {result['trend']}")
            else:
                result = client.get_stats()
                if args.json:
                    _json_out(result, True)
                else:
                    print("Anvil Usage Statistics")
                    print("=" * 50)

                    top_skills = result.get("top_skills", [])
                    if top_skills:
                        print("\nTop Skills:")
                        print(f"  {'Skill':<30} {'Invocations':>12} {'Success':>8}")
                        print("  " + "-" * 55)
                        for s in top_skills:
                            rate = f"{s.get('success_rate', 0):.1f}%"
                            print(
                                f"  {s.get('skill_name', s.get('name', '?')):<30} "
                                f"{s.get('count', s.get('invocations', 0)):>12} "
                                f"{rate:>8}"
                            )

                    avg_success = result.get("avg_success_rate")
                    if avg_success is not None:
                        print(f"\nOverall success rate: {avg_success:.1f}%")

                    total = result.get("total_invocations")
                    if total is not None:
                        print(f"Total invocations: {total}")

                    trend = result.get("trend_7d", result.get("trend"))
                    if trend:
                        print(f"7-day trend: {trend}")
    except AnvilError as e:
        _err(e)


def cmd_time_saved(args):
    """Show time-saved ROI summary."""
    try:
        with AnvilClient() as client:
            result = client.get_time_saved_stats(period=args.period)
            if args.json:
                _json_out(result, True)
            else:
                tasks = result.get("tasks_with_estimates", 0)
                total_min = result.get("total_saved_minutes", 0.0)
                avg_min = result.get("avg_saved_per_task")
                total_hours = total_min / 60.0

                print(f"Time-Saved ROI ({args.period})")
                print("=" * 50)
                print(f"  Tasks with estimates : {tasks}")
                print(f"  Total time saved     : {total_hours:.1f} hours ({total_min:.0f} min)")
                if avg_min is not None:
                    print(f"  Avg saved per task   : {avg_min:.1f} min")

                monthly = result.get("monthly_breakdown", [])
                if monthly:
                    print()
                    print("  Monthly Breakdown:")
                    print(f"    {'Month':<10} {'Saved (min)':>12} {'Tasks':>6}")
                    print("    " + "-" * 32)
                    for m in monthly:
                        print(
                            f"    {m['month']:<10} "
                            f"{m['total_saved_minutes']:>12.0f} "
                            f"{m['tasks_count']:>6}"
                        )
    except AnvilError as e:
        _err(e)


def cmd_history(args):
    """Show evaluation history for a skill."""
    try:
        with AnvilClient() as client:
            result = client.list_evaluations(skill_name=args.name, limit=20)
            evaluations = result.get("evaluations", result.get("items", []))

            if args.json:
                _json_out(result, True)
            else:
                if not evaluations:
                    print(f"No evaluations found for: {args.name}")
                    return
                print(f"Evaluation History: {args.name}")
                print(f"{'ID':<20} {'Status':<12} {'Score':>6} {'Date':<22}")
                print("-" * 65)
                for ev in evaluations:
                    score = ev.get("score")
                    score_str = f"{score:.1f}" if score is not None else "-"
                    print(
                        f"{ev.get('id', ev.get('eval_id', '?')):<20} "
                        f"{ev.get('status', '?'):<12} "
                        f"{score_str:>6} "
                        f"{ev.get('created_at', ev.get('triggered_at', '-')):<22}"
                    )
    except AnvilError as e:
        _err(e)


def cmd_correct(args):
    """Propose a self-correction for a skill."""
    try:
        with AnvilClient() as client:
            result = client.propose_correction(args.name, level=args.level)
            if args.json:
                _json_out(result, True)
            else:
                corr_id = result.get("id", result.get("correction_id", "?"))
                print(f"Correction proposed: {corr_id}")
                print(f"  Skill: {args.name}")
                print(f"  Level: {args.level}")
                print(f"  Status: {result.get('status', '?')}")
                if result.get("diff_content"):
                    print(f"  Diff preview: {result['diff_content'][:200]}")
    except AnvilError as e:
        _err(e)


def cmd_sync(args):
    """Sync skills from filesystem to Anvil registry."""
    with AnvilClient() as client:
        # Step 1: Scan local filesystem
        skills = client.scan_skills_dir()

        if not skills:
            if args.json:
                _json_out({"synced": 0, "skills": []}, True)
            else:
                print("No skills found in ~/.claude/skills/")
            return

        if not args.json:
            print(f"Found {len(skills)} skill(s) on filesystem.")
            print("Syncing to Anvil registry...")
            print()

        # Step 2: Register each skill
        synced = []
        errors = []
        for skill in skills:
            try:
                result = client.register_skill(
                    name=skill["name"],
                    version=skill.get("version") or None,
                    description=skill.get("description") or None,
                    tags=skill.get("tags") or None,
                    io_schema=skill.get("io_schema") or None,
                )
                synced.append({"name": skill["name"], "result": result})
                if not args.json:
                    print(f"  [OK] {skill['name']}")
            except AnvilError as e:
                errors.append({"name": skill["name"], "error": str(e)})
                if not args.json:
                    print(f"  [ERR] {skill['name']}: {e}")

        if args.json:
            _json_out(
                {
                    "synced": len(synced),
                    "errors": len(errors),
                    "skills": synced,
                    "failed": errors,
                },
                True,
            )
        else:
            print()
            print(f"Synced: {len(synced)}, Errors: {len(errors)}")


# ======================== Main ========================


common_parser = argparse.ArgumentParser(add_help=False)
common_parser.add_argument("--json", action="store_true", help="JSON output")


def main():
    parser = argparse.ArgumentParser(
        prog="anvil",
        description="Anvil -- skill forge CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # create
    p = sub.add_parser("create", parents=[common_parser], help="Create skill scaffold")
    p.add_argument("name", help="Skill name")

    # test
    p = sub.add_parser("test", parents=[common_parser], help="Test skill structure (T1-T5)")
    p.add_argument("name", help="Skill name")

    # scan
    p = sub.add_parser("scan", parents=[common_parser], help="Security scan skill (S1-S3)")
    p.add_argument("name", help="Skill name")

    # eval
    p = sub.add_parser("eval", parents=[common_parser], help="Evaluate skill quality")
    p.add_argument("name", help="Skill name")
    p.add_argument("--regression", action="store_true", help="Compare with baseline")
    p.add_argument("--runs", type=int, default=1, help="Number of runs for stability")

    # optimize
    p = sub.add_parser("optimize", parents=[common_parser], help="Optimize skill")
    p.add_argument("name", help="Skill name")

    # curate
    p = sub.add_parser("curate", parents=[common_parser], help="Curate skills for overlap")

    # catalog
    p = sub.add_parser("catalog", parents=[common_parser], help="List all skills")
    p.add_argument("--status", default="active", help="Filter by status")

    # graph
    p = sub.add_parser("graph", parents=[common_parser], help="Show skill I/O graph")

    # publish
    p = sub.add_parser("publish", parents=[common_parser], help="Publish skill to GitHub")
    p.add_argument("name", help="Skill name")

    # lifecycle
    p = sub.add_parser("lifecycle", parents=[common_parser], help="Run full lifecycle")
    p.add_argument("name", help="Skill name")

    # stats
    p = sub.add_parser("stats", parents=[common_parser], help="Show usage statistics")
    p.add_argument("--skill", help="Specific skill name")
    p.add_argument("--period", default="7d", help="Time period")

    # time-saved
    p = sub.add_parser("time-saved", parents=[common_parser], help="Show time-saved ROI summary")
    p.add_argument("--period", default="30d", help="Time period, e.g. 7d, 30d, 90d")

    # history
    p = sub.add_parser("history", parents=[common_parser], help="Show evaluation history")
    p.add_argument("name", help="Skill name")

    # correct
    p = sub.add_parser("correct", parents=[common_parser], help="Self-correction")
    p.add_argument("name", help="Skill name")
    p.add_argument("--level", type=int, default=1, help="Correction level (0-3)")

    # sync
    p = sub.add_parser("sync", parents=[common_parser], help="Sync skills from filesystem")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to handler (normalize hyphens to underscores for function lookup)
    handler = globals().get(f"cmd_{args.command.replace('-', '_')}")
    if handler:
        try:
            handler(args)
        except AnvilError as e:
            if hasattr(args, "json") and args.json:
                print(
                    json.dumps(
                        {"error": True, "status_code": e.status_code, "detail": e.detail},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    file=sys.stderr,
                )
            else:
                print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            if hasattr(args, "json") and args.json:
                print(
                    json.dumps(
                        {"error": True, "detail": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    file=sys.stderr,
                )
            else:
                print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
