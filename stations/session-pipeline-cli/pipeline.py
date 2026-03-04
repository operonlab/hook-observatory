#!/Users/joneshong/.local/bin/python3
"""pipeline -- Workshop Session Pipeline CLI.

Usage:
    pipeline run <session_id> [--transcript PATH]   Run full SessionEnd pipeline
    pipeline stages                                  List pipeline stages
    pipeline config                                  Show current configuration
    pipeline status                                  Show last pipeline run status

Options:
    --json   Output as JSON

Symlink: ln -sf ~/workshop/stations/session-pipeline-cli/pipeline.py ~/.local/bin/pipeline
"""

import argparse
import json
import os
import sys

# Ensure workshop libs are importable
_LIBS = os.path.expanduser("~/workshop/libs/python/src")
if _LIBS not in sys.path:
    sys.path.insert(0, _LIBS)

from workshop.clients.session_pipeline import SessionPipelineClient

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _out(data: dict | list, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        _pretty(data)


def _pretty(data: dict | list, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(data, list):
        for item in data:
            _pretty(item, indent)
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                _pretty(v, indent + 1)
            else:
                print(f"{pad}{k}: {v}")
    else:
        print(f"{pad}{data}")


def _err(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> None:
    client = SessionPipelineClient()
    result = client.run_pipeline(
        session_id=args.session_id,
        transcript_path=args.transcript,
    )
    data = result.to_dict()
    if args.json:
        _out(data, True)
    else:
        print(f"Pipeline: session={result.session_id}")
        print(f"  transcript: {result.transcript_path or '(auto-detect)'}")
        for stage in result.stages:
            icon = "ok " if stage["success"] else "FAIL"
            err = f"  [{stage['error']}]" if stage.get("error") else ""
            print(f"  [{icon}] {stage['name']:10s}  {stage['duration_ms']:>5}ms{err}")
        print(f"  total: {result.total_duration_ms}ms")


def cmd_stages(args: argparse.Namespace) -> None:
    client = SessionPipelineClient()
    stages = client.list_stages()
    if args.json:
        _out(stages, True)
    else:
        print("Pipeline stages:")
        for s in stages:
            print(f"  {s['order']}. {s['name']:10s}  {s['description']}")
            print(f"             fail_behavior: {s['fail_behavior']}")


def cmd_config(args: argparse.Namespace) -> None:
    client = SessionPipelineClient()
    config = client.get_pipeline_config()
    if args.json:
        _out(config, True)
    else:
        print("Pipeline configuration:")
        for k, v in config.items():
            print(f"  {k}: {v}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show status of the last pipeline run (from observatory if available)."""
    client = SessionPipelineClient()
    try:
        import httpx

        resp = httpx.get(
            f"{client.observatory_url}/api/events",
            params={"event_type": "SessionPipeline", "limit": 1},
            headers={"x-local-key": os.environ.get("HOOK_OBS_SECRET_KEY", "workshop-v2-dev-key")},
            timeout=5,
        )
        if resp.status_code == 200:
            events = resp.json()
            if isinstance(events, list) and events:
                latest = events[0]
                if args.json:
                    _out(latest, True)
                else:
                    print("Last pipeline run:")
                    _pretty(latest, indent=1)
                return
        print("No pipeline run history found in observatory.")
    except Exception as exc:
        if args.json:
            _out({"error": str(exc), "note": "observatory may be offline"}, True)
        else:
            print(f"Observatory unavailable ({exc}). No status to display.")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Workshop Session Pipeline — orchestrate SessionEnd lifecycle stages",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # run
    run_p = sub.add_parser("run", help="Run full SessionEnd pipeline")
    run_p.add_argument("session_id", help="Claude session ID")
    run_p.add_argument("--transcript", metavar="PATH", help="Path to transcript JSONL")

    # stages
    sub.add_parser("stages", help="List pipeline stages")

    # config
    sub.add_parser("config", help="Show current pipeline configuration")

    # status
    sub.add_parser("status", help="Show last pipeline run status from observatory")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "run": cmd_run,
        "stages": cmd_stages,
        "config": cmd_config,
        "status": cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
