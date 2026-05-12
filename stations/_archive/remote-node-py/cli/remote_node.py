#!/Users/joneshong/.local/bin/python3
"""remote-node -- CLI for the Remote Node proxy station.

Forwards computer vision tasks to the Windows GPU server via the local proxy.

Usage:
    remote-node status                          # proxy + Windows health
    remote-node segment <path> --prompt <text>  # segment image region
    remote-node detect <path> --prompt <text>   # detect objects
    remote-node caption <path> [--detail detailed]
    remote-node batch-segment <path> --prompts <p1> <p2> ...
    remote-node models                          # list available models
    remote-node models load <name>              # load model on GPU
    remote-node models unload <name>            # unload model from GPU

All commands support --json for machine-readable output.

Symlink: ln -sf ~/workshop/stations/remote-node/cli/remote_node.py ~/.local/bin/remote-node
"""

import argparse
import json
import sys
import time


def _json_out(data, as_json=False):
    """Print data as JSON if --json flag is set."""
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return data


def _err(msg):
    """Print error and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _get_client():
    """Lazy-import and instantiate RemoteNodeClient."""
    try:
        from sdk_client.remote_node import RemoteNodeClient
        return RemoteNodeClient()
    except ImportError:
        _err(
            "workshop SDK not installed. "
            "Run: cd ~/workshop && uv pip install -e libs/python"
        )
    except Exception as e:
        _err(f"Failed to create client: {e}")


# ======================== Commands ========================


def cmd_status(args):
    """Show proxy + Windows GPU server health status."""
    client = _get_client()
    try:
        h = client.health()
        if args.json:
            _json_out(h, True)
            return

        proxy_ok = h.get("status") == "ok"
        remote_ok = h.get("remote_healthy", False)

        print(f"[{'+'if proxy_ok else 'X'}] Proxy:   {'running' if proxy_ok else 'down'}")
        print(f"    Port: {h.get('port', '?')}")
        print()
        win_icon = "+" if remote_ok else "X"
        win_status = "connected" if remote_ok else "unreachable"
        print(f"[{win_icon}] Windows: {win_status}")
        print(f"    URL: {h.get('remote_url', '?')}")

        last_check = h.get("remote_last_check", 0)
        if last_check:
            ago = int(time.time() - last_check)
            print(f"    Last check: {ago}s ago")

        if h.get("remote_last_error"):
            print(f"    Last error: {h['remote_last_error']}")

        # Try to show loaded models if Windows is connected
        if remote_ok:
            try:
                models = client.list_models()
                loaded = models.get("loaded", [])
                available = models.get("available", [])
                if loaded:
                    print(f"\n  Loaded models: {', '.join(loaded)}")
                if available:
                    print(f"  Available: {', '.join(available)}")
                if models.get("vram"):
                    vram = models["vram"]
                    print(f"  VRAM: {vram.get('used', '?')} / {vram.get('total', '?')}")
            except Exception:
                pass  # Non-critical, skip silently

    except Exception as e:
        if args.json:
            _json_out({"status": "error", "detail": str(e)}, True)
        else:
            print(f"[X] Proxy:   unreachable")
            print(f"    {e}")
        sys.exit(1)


def cmd_segment(args):
    """Segment an image region based on text prompt."""
    client = _get_client()
    try:
        result = client.segment(args.path, args.prompt, task=args.task)
        if args.json:
            _json_out(result, True)
        else:
            if result.get("mask_path"):
                print(f"Mask saved: {result['mask_path']}")
            if result.get("labels"):
                print(f"Labels: {', '.join(result['labels'])}")
            if result.get("polygons"):
                print(f"Polygons: {len(result['polygons'])} region(s)")
    except Exception as e:
        _err(e)


def cmd_detect(args):
    """Detect objects in image matching the text prompt."""
    client = _get_client()
    try:
        result = client.detect(args.path, args.prompt)
        if args.json:
            _json_out(result, True)
        else:
            boxes = result.get("boxes", [])
            labels = result.get("labels", [])
            scores = result.get("scores", [])
            if not boxes:
                print("No objects detected.")
                return
            print(f"Detected {len(boxes)} object(s):")
            for i, (box, label, score) in enumerate(
                zip(boxes, labels, scores), 1
            ):
                print(f"  {i}. {label} ({score:.2%}) @ {box}")
    except Exception as e:
        _err(e)


def cmd_caption(args):
    """Generate a text caption for the image."""
    client = _get_client()
    try:
        result = client.caption(args.path, detail=args.detail)
        if args.json:
            _json_out(result, True)
        else:
            print(result.get("caption", "(no caption)"))
    except Exception as e:
        _err(e)


def cmd_batch_segment(args):
    """Segment multiple prompts on one image."""
    client = _get_client()
    try:
        result = client.batch_segment(args.path, args.prompts)
        if args.json:
            _json_out(result, True)
        else:
            results = result.get("results", {})
            for prompt_key, seg in results.items():
                mask = seg.get("mask_path", "-")
                print(f"  [{prompt_key}] mask: {mask}")
            if result.get("composite_mask_path"):
                print(f"\nComposite: {result['composite_mask_path']}")
    except Exception as e:
        _err(e)


def cmd_models(args):
    """List available models on the Windows GPU server."""
    client = _get_client()
    try:
        result = client.list_models()
        if args.json:
            _json_out(result, True)
        else:
            loaded = result.get("loaded", [])
            available = result.get("available", [])
            if loaded:
                print("Loaded:")
                for m in loaded:
                    print(f"  + {m}")
            if available:
                print("Available:")
                for m in available:
                    marker = "*" if m in loaded else " "
                    print(f"  {marker} {m}")
            if result.get("vram"):
                vram = result["vram"]
                print(f"\nVRAM: {vram.get('used', '?')} / {vram.get('total', '?')}")
            if not loaded and not available:
                print("No model information available.")
    except Exception as e:
        _err(e)


def cmd_model_load(args):
    """Load a model on the Windows GPU server."""
    client = _get_client()
    try:
        result = client.load_model(args.name)
        if args.json:
            _json_out(result, True)
        else:
            status = result.get("status", "unknown")
            print(f"Model '{args.name}': {status}")
    except Exception as e:
        _err(e)


def cmd_model_unload(args):
    """Unload a model from the Windows GPU server."""
    client = _get_client()
    try:
        result = client.unload_model(args.name)
        if args.json:
            _json_out(result, True)
        else:
            status = result.get("status", "unknown")
            print(f"Model '{args.name}': {status}")
    except Exception as e:
        _err(e)


# ======================== Main ========================


def main():
    parser = argparse.ArgumentParser(
        prog="remote-node",
        description="Remote Node proxy CLI — forward CV tasks to Windows GPU server",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="subcmd", required=True)

    # status
    p_status = sub.add_parser("status", help="Proxy + Windows health status")
    p_status.set_defaults(func=cmd_status)

    # segment
    p_seg = sub.add_parser("segment", help="Segment image region by prompt")
    p_seg.add_argument("path", help="Path to image file")
    p_seg.add_argument("--prompt", required=True, help="Text prompt for segmentation")
    p_seg.add_argument("--task", default="referring", help="Task type (default: referring)")
    p_seg.set_defaults(func=cmd_segment)

    # detect
    p_det = sub.add_parser("detect", help="Detect objects by prompt")
    p_det.add_argument("path", help="Path to image file")
    p_det.add_argument("--prompt", required=True, help="Text prompt for detection")
    p_det.set_defaults(func=cmd_detect)

    # caption
    p_cap = sub.add_parser("caption", help="Caption image")
    p_cap.add_argument("path", help="Path to image file")
    p_cap.add_argument("--detail", default="brief", choices=["brief", "detailed"],
                        help="Caption detail level (default: brief)")
    p_cap.set_defaults(func=cmd_caption)

    # batch-segment
    p_batch = sub.add_parser("batch-segment", help="Batch segment with multiple prompts")
    p_batch.add_argument("path", help="Path to image file")
    p_batch.add_argument("--prompts", nargs="+", required=True,
                          help="List of text prompts")
    p_batch.set_defaults(func=cmd_batch_segment)

    # models (with subcommands: list / load / unload)
    p_models = sub.add_parser("models", help="Model management")
    models_sub = p_models.add_subparsers(dest="models_cmd")

    # models (no subcommand = list)
    p_models.set_defaults(func=cmd_models)

    # models load
    p_load = models_sub.add_parser("load", help="Load model on GPU")
    p_load.add_argument("name", help="Model name")
    p_load.set_defaults(func=cmd_model_load)

    # models unload
    p_unload = models_sub.add_parser("unload", help="Unload model from GPU")
    p_unload.add_argument("name", help="Model name")
    p_unload.set_defaults(func=cmd_model_unload)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
