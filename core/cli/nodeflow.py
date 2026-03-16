#!/Users/joneshong/.local/bin/python3
"""Nodeflow CLI — DAG flow orchestration & execution.

Usage:
    nodeflow flows list [--limit N]
    nodeflow flows get <id>
    nodeflow flows create <name> [--trigger-type manual|event|schedule]
    nodeflow flows activate <id>
    nodeflow flows pause <id>
    nodeflow flows trigger <id> [--input '{}']
    nodeflow nodes list <flow_id>
    nodeflow nodes create <flow_id> <type> <label>
    nodeflow edges list <flow_id>
    nodeflow runs list <flow_id> [--limit N]
    nodeflow runs get <run_id>
    nodeflow actions
    nodeflow status

Symlink: ln -sf ~/workshop/core/cli/nodeflow.py ~/.local/bin/nodeflow
"""

import argparse
import json
import sys

from cli.cli_utils import resolve_text_arg
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.nodeflow import NodeflowClient


def _json_out(data, as_json=False):
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


# ======================== Flows ========================


def cmd_flows_list(args):
    client = NodeflowClient()
    try:
        result = client.list_flows(page=args.page, page_size=args.limit)
        if args.json:
            _json_out(result, True)
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Flows ({len(items)} of {total}):\n")
        for f in items:
            status = f.get("status", "?")
            trigger = f.get("trigger_type", "?")
            print(f"  [{status:8s}] {f.get('name', '?')[:50]}  trigger={trigger}")
            print(f"             id={f.get('id', '?')[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_flows_get(args):
    client = NodeflowClient()
    try:
        f = client.get_flow(args.id)
        if args.json:
            _json_out(f, True)
            return
        print(f"Name: {f.get('name', '?')}")
        print(f"Status: {f.get('status', '?')}")
        print(f"Trigger: {f.get('trigger_type', '?')}")
        desc = f.get("description", "")
        if desc:
            print(f"Description: {desc[:200]}")
        nodes = f.get("nodes", [])
        edges = f.get("edges", [])
        print(f"Nodes: {len(nodes)}  Edges: {len(edges)}")
        for n in nodes:
            print(
                f"  node: {n.get('label', '?')} ({n.get('node_type', '?')})  id={n.get('id', '?')[:12]}"
            )
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_flows_create(args):
    client = NodeflowClient()
    try:
        data = {
            "name": args.name,
            "trigger_type": args.trigger_type,
            "status": "draft",
        }
        description = resolve_text_arg(args.description)
        if description:
            data["description"] = description
        result = client.create_flow(data)
        if args.json:
            _json_out(result, True)
            return
        print(f"Created flow: {result.get('name', '?')} (id={result.get('id', '?')[:12]})")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_flows_activate(args):
    client = NodeflowClient()
    try:
        result = client.activate_flow(args.id)
        if args.json:
            _json_out(result, True)
            return
        print(f"Flow activated: {result.get('name', result.get('id', '?'))}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_flows_pause(args):
    client = NodeflowClient()
    try:
        result = client.pause_flow(args.id)
        if args.json:
            _json_out(result, True)
            return
        print(f"Flow paused: {result.get('name', result.get('id', '?'))}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_flows_trigger(args):
    client = NodeflowClient()
    try:
        input_raw = resolve_text_arg(args.input)
        input_data = json.loads(input_raw) if input_raw else {}
        result = client.trigger_flow(args.id, input_data)
        if args.json:
            _json_out(result, True)
            return
        run_id = result.get("id", result.get("flow_run_id", "?"))
        print(f"Flow triggered. Run ID: {run_id}")
    except json.JSONDecodeError:
        print("Error: --input must be valid JSON", file=sys.stderr)
        sys.exit(1)
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Nodes ========================


def cmd_nodes_list(args):
    client = NodeflowClient()
    try:
        result = client.list_nodes(args.flow_id)
        if args.json:
            _json_out(result, True)
            return
        items = result if isinstance(result, list) else result.get("items", [])
        print(f"Nodes ({len(items)}):\n")
        for n in items:
            print(f"  [{n.get('node_type', '?'):15s}] {n.get('label', '?')[:40]}")
            print(
                f"                    pos=({n.get('position_x', 0)}, {n.get('position_y', 0)})  id={n.get('id', '?')[:12]}"
            )
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_nodes_create(args):
    client = NodeflowClient()
    try:
        data = {
            "flow_id": args.flow_id,
            "node_type": args.type,
            "label": args.label,
            "config": json.loads(args.config) if args.config else {},
            "position_x": args.x,
            "position_y": args.y,
        }
        result = client.create_node(data)
        if args.json:
            _json_out(result, True)
            return
        print(f"Created node: {result.get('label', '?')} (id={result.get('id', '?')[:12]})")
    except json.JSONDecodeError:
        print("Error: --config must be valid JSON", file=sys.stderr)
        sys.exit(1)
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Edges ========================


def cmd_edges_list(args):
    client = NodeflowClient()
    try:
        result = client.list_edges(args.flow_id)
        if args.json:
            _json_out(result, True)
            return
        items = result if isinstance(result, list) else result.get("items", [])
        print(f"Edges ({len(items)}):\n")
        for e in items:
            src = e.get("source_node_id", "?")[:12]
            tgt = e.get("target_node_id", "?")[:12]
            port = e.get("source_port", "output")
            print(f"  {src} --[{port}]--> {tgt}  id={e.get('id', '?')[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Runs ========================


def cmd_runs_list(args):
    client = NodeflowClient()
    try:
        result = client.list_runs(args.flow_id, page_size=args.limit)
        if args.json:
            _json_out(result, True)
            return
        items = result.get("items", [])
        total = result.get("total", 0)
        print(f"Runs ({len(items)} of {total}):\n")
        for r in items:
            status = r.get("status", "?")
            started = str(r.get("started_at", ""))[:19]
            print(f"  [{status:10s}] started={started}  id={r.get('id', '?')[:12]}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_runs_get(args):
    client = NodeflowClient()
    try:
        r = client.get_run(args.id)
        if args.json:
            _json_out(r, True)
            return
        print(f"Run ID: {r.get('id', '?')}")
        print(f"Flow ID: {r.get('flow_id', '?')}")
        print(f"Status: {r.get('status', '?')}")
        print(f"Started: {str(r.get('started_at', ''))[:19]}")
        print(f"Finished: {str(r.get('finished_at', ''))[:19]}")
        node_runs = r.get("node_runs", [])
        if node_runs:
            print(f"\nNode Runs ({len(node_runs)}):")
            for nr in node_runs:
                print(
                    f"  [{nr.get('status', '?'):10s}] {nr.get('node_label', nr.get('node_id', '?')[:12])}"
                )
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Actions ========================


def cmd_actions(args):
    client = NodeflowClient()
    try:
        result = client.list_actions()
        if args.json:
            _json_out(result, True)
            return
        items = result if isinstance(result, list) else result.get("items", [])
        print(f"Available Actions ({len(items)}):\n")
        for a in items:
            name = a.get("name", a.get("type", "?"))
            desc = a.get("description", "")[:60]
            print(f"  {name:25s}  {desc}")
    except (APIError, APIConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Status ========================


def cmd_status(args):
    client = NodeflowClient()
    try:
        # Try health endpoint or just list flows to verify connectivity
        result = client.list_flows(page_size=1)
        if args.json:
            _json_out({"status": "ok", "flows": result.get("total", 0)}, True)
            return
        print(f"Nodeflow: OK (total flows: {result.get('total', 0)})")
    except APIConnectionError as e:
        if args.json:
            _json_out({"status": "unreachable", "error": str(e)}, True)
        else:
            print(f"Nodeflow: UNREACHABLE - {e}", file=sys.stderr)
        sys.exit(1)
    except APIError as e:
        if args.json:
            _json_out({"status": "error", "code": e.status_code, "detail": e.detail}, True)
        else:
            print(f"Nodeflow: ERROR - {e}", file=sys.stderr)
        sys.exit(1)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="nodeflow",
        description="Nodeflow — DAG flow orchestration CLI",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    # flows
    p_flows = sub.add_parser("flows", help="Flow management")
    fsub = p_flows.add_subparsers(dest="flows_cmd", required=True)

    p_flist = fsub.add_parser("list", help="List flows")
    p_flist.add_argument("--limit", type=int, default=20)
    p_flist.add_argument("--page", type=int, default=1)
    p_flist.set_defaults(func=cmd_flows_list)

    p_fget = fsub.add_parser("get", help="Get flow detail")
    p_fget.add_argument("id", help="Flow ID")
    p_fget.set_defaults(func=cmd_flows_get)

    p_fcreate = fsub.add_parser("create", help="Create a flow")
    p_fcreate.add_argument("name", help="Flow name")
    p_fcreate.add_argument(
        "--trigger-type", default="manual", choices=["manual", "event", "schedule"]
    )
    p_fcreate.add_argument("--description", help="Flow description")
    p_fcreate.set_defaults(func=cmd_flows_create)

    p_factivate = fsub.add_parser("activate", help="Activate a flow")
    p_factivate.add_argument("id", help="Flow ID")
    p_factivate.set_defaults(func=cmd_flows_activate)

    p_fpause = fsub.add_parser("pause", help="Pause a flow")
    p_fpause.add_argument("id", help="Flow ID")
    p_fpause.set_defaults(func=cmd_flows_pause)

    p_ftrigger = fsub.add_parser("trigger", help="Manually trigger a flow")
    p_ftrigger.add_argument("id", help="Flow ID")
    p_ftrigger.add_argument("--input", help="Input data as JSON string")
    p_ftrigger.set_defaults(func=cmd_flows_trigger)

    # nodes
    p_nodes = sub.add_parser("nodes", help="Node management")
    nsub = p_nodes.add_subparsers(dest="nodes_cmd", required=True)

    p_nlist = nsub.add_parser("list", help="List nodes in a flow")
    p_nlist.add_argument("flow_id", help="Flow ID")
    p_nlist.set_defaults(func=cmd_nodes_list)

    p_ncreate = nsub.add_parser("create", help="Create a node")
    p_ncreate.add_argument("flow_id", help="Flow ID")
    p_ncreate.add_argument("type", help="Node type")
    p_ncreate.add_argument("label", help="Node label")
    p_ncreate.add_argument("--config", help="Node config as JSON string")
    p_ncreate.add_argument("--x", type=float, default=0, help="Position X")
    p_ncreate.add_argument("--y", type=float, default=0, help="Position Y")
    p_ncreate.set_defaults(func=cmd_nodes_create)

    # edges
    p_edges = sub.add_parser("edges", help="Edge management")
    esub = p_edges.add_subparsers(dest="edges_cmd", required=True)

    p_elist = esub.add_parser("list", help="List edges in a flow")
    p_elist.add_argument("flow_id", help="Flow ID")
    p_elist.set_defaults(func=cmd_edges_list)

    # runs
    p_runs = sub.add_parser("runs", help="Flow run management")
    rsub = p_runs.add_subparsers(dest="runs_cmd", required=True)

    p_rlist = rsub.add_parser("list", help="List flow runs")
    p_rlist.add_argument("flow_id", help="Flow ID")
    p_rlist.add_argument("--limit", type=int, default=20)
    p_rlist.set_defaults(func=cmd_runs_list)

    p_rget = rsub.add_parser("get", help="Get run detail")
    p_rget.add_argument("id", help="Run ID")
    p_rget.set_defaults(func=cmd_runs_get)

    # actions
    p_actions = sub.add_parser("actions", help="List available action types")
    p_actions.set_defaults(func=cmd_actions)

    # status
    p_status = sub.add_parser("status", help="Check Nodeflow module status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
