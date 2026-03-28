#!/Users/joneshong/.local/bin/python3
"""vedit — Video Edit command-line tool.

Usage:
    vedit new <name> [--resolution WxH] [--fps N]
    vedit list
    vedit add <project_path> <media_file> [--track N]
    vedit cut <project_path> <clip_id> --at <seconds>
    vedit trim <project_path> <clip_id> [--in N] [--out N]
    vedit remove <project_path> <clip_id>
    vedit subtitle <project_path> <text> --start N --end N
    vedit info <project_path>
    vedit preview <project_path> [--start N] [--end N] [-o OUTPUT]
    vedit render <project_path> -o <output>
    vedit open <project_path>

Symlink: ln -sf ~/workshop/stations/video-edit/cli/vedit.py ~/.local/bin/vedit
"""

import argparse
import json
import subprocess
import sys

from sdk_client.video_edit import VideoEditClient, VideoEditError


def _err(e):
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


def _json_out(data):
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ======================== Commands ========================


def cmd_new(args):
    client = VideoEditClient()
    try:
        w, h = args.resolution.split("x")
        result = client.create_project(args.name, width=int(w), height=int(h), fps_num=args.fps)
        print(f"Created: {result['name']}")
        print(f"  Path: {result['path']}")
        print(f"  ID: {result['id']}")
    except VideoEditError as e:
        _err(e)


def cmd_list(args):
    client = VideoEditClient()
    try:
        projects = client.list_projects()
        if not projects:
            print("No projects found.")
            return
        for p in projects:
            print(f"  {p['name']}  →  {p['path']}")
    except VideoEditError as e:
        _err(e)


def cmd_add(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        result = client.add_clip(proj["id"], args.media_file, track=args.track)
        print(f"Added clip: {result['clip_id']}")
        print(f"  Resource: {result['resource']}")
        print(f"  Range: {result['in']} → {result['out']}")
        client.save_project(proj["id"])
    except VideoEditError as e:
        _err(e)


def cmd_cut(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        result = client.cut_clip(proj["id"], args.clip_id, args.at)
        print(f"Cut at {result['cut_at']}")
        print(f"  Part 1: {result['part1']['in']} → {result['part1']['out']}")
        print(f"  Part 2: {result['part2']['in']} → {result['part2']['out']}")
        client.save_project(proj["id"])
    except VideoEditError as e:
        _err(e)


def cmd_trim(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        result = client.trim_clip(proj["id"], args.clip_id, in_point=args.in_point, out_point=args.out_point)
        print(f"Trimmed: {result['in']} → {result['out']}")
        client.save_project(proj["id"])
    except VideoEditError as e:
        _err(e)


def cmd_remove(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        client.remove_clip(proj["id"], args.clip_id)
        print(f"Removed clip: {args.clip_id}")
        client.save_project(proj["id"])
    except VideoEditError as e:
        _err(e)


def cmd_subtitle(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        result = client.add_subtitle(proj["id"], args.text, start=args.start, end=args.end)
        print(f"Added subtitle: {result['subtitle_id']}")
        print(f"  \"{args.text}\" @ {result['start']} → {result['end']}")
        client.save_project(proj["id"])
    except VideoEditError as e:
        _err(e)


def cmd_info(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        info = client.timeline_info(proj["id"])
        _json_out(info)
    except VideoEditError as e:
        _err(e)


def cmd_preview(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        result = client.preview(proj["id"], start=args.start, end=args.end, output_path=args.output)
        print(f"Preview: {result['path']}")
    except VideoEditError as e:
        _err(e)


def cmd_render(args):
    client = VideoEditClient()
    try:
        proj = client.open_project(args.project_path)
        result = client.render(proj["id"], output_path=args.output)
        print(f"Rendered: {result['path']}")
    except VideoEditError as e:
        _err(e)


def cmd_open(args):
    """Open project in Kdenlive GUI."""
    subprocess.run(["open", "-a", "Kdenlive", args.project_path])


# ======================== Parser ========================


def main():
    parser = argparse.ArgumentParser(description="vedit — Video Edit CLI")
    sub = parser.add_subparsers(dest="cmd", help="Command")

    # new
    p = sub.add_parser("new", help="Create new project")
    p.add_argument("name")
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--fps", type=int, default=30)
    p.set_defaults(func=cmd_new)

    # list
    p = sub.add_parser("list", help="List projects")
    p.set_defaults(func=cmd_list)

    # add
    p = sub.add_parser("add", help="Add clip to project")
    p.add_argument("project_path")
    p.add_argument("media_file")
    p.add_argument("--track", type=int, default=0)
    p.set_defaults(func=cmd_add)

    # cut
    p = sub.add_parser("cut", help="Cut clip at time")
    p.add_argument("project_path")
    p.add_argument("clip_id")
    p.add_argument("--at", type=float, required=True)
    p.set_defaults(func=cmd_cut)

    # trim
    p = sub.add_parser("trim", help="Trim clip in/out points")
    p.add_argument("project_path")
    p.add_argument("clip_id")
    p.add_argument("--in-point", type=float, dest="in_point")
    p.add_argument("--out-point", type=float, dest="out_point")
    p.set_defaults(func=cmd_trim)

    # remove
    p = sub.add_parser("remove", help="Remove clip")
    p.add_argument("project_path")
    p.add_argument("clip_id")
    p.set_defaults(func=cmd_remove)

    # subtitle
    p = sub.add_parser("subtitle", help="Add subtitle")
    p.add_argument("project_path")
    p.add_argument("text")
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.set_defaults(func=cmd_subtitle)

    # info
    p = sub.add_parser("info", help="Show timeline info")
    p.add_argument("project_path")
    p.set_defaults(func=cmd_info)

    # preview
    p = sub.add_parser("preview", help="Generate preview")
    p.add_argument("project_path")
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.add_argument("-o", "--output", dest="output")
    p.set_defaults(func=cmd_preview)

    # render
    p = sub.add_parser("render", help="Final render")
    p.add_argument("project_path")
    p.add_argument("-o", "--output", required=True, dest="output")
    p.set_defaults(func=cmd_render)

    # open
    p = sub.add_parser("open", help="Open in Kdenlive")
    p.add_argument("project_path")
    p.set_defaults(func=cmd_open)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
