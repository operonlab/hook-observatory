#!/Users/joneshong/.local/bin/python3
"""Sandbox CLI — execute Python/JS code with SDK helpers.

Usage:
    sandbox exec 'print("hello")'                  # inline code
    sandbox exec -f /tmp/script.py                  # file-based (saves tokens)
    sandbox exec -f /tmp/script.py -o result.json   # output to file
    echo 'print(1+1)' | sandbox exec -              # read from stdin
    sandbox info                                    # show Python SDK docs
    sandbox info -l javascript                      # show JS SDK docs

Symlink: ln -sf ~/workshop/stations/sandbox-executor/cli/sandbox.py ~/.local/bin/sandbox
"""

import argparse
import json
import sys

from workshop.clients.sandbox import SandboxClient


def format_result(result, as_json=False):
    if as_json:
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    parts = []
    parts.append(f"Status: {'Success' if result.success else 'Failed'}")
    parts.append(f"Duration: {result.duration_ms}ms")

    if result.timed_out:
        parts.append("Warning: Execution timed out")

    if result.stdout.strip():
        stdout = (
            result.stdout[:5000] + "\n... (truncated)"
            if len(result.stdout) > 5000
            else result.stdout
        )
        parts.append(f"\n--- stdout ---\n{stdout}")

    if result.stderr.strip():
        stderr = (
            result.stderr[:2000] + "\n... (truncated)"
            if len(result.stderr) > 2000
            else result.stderr
        )
        parts.append(f"\n--- stderr ---\n{stderr}")

    if result.outputs:
        parts.append("\n--- Structured Outputs ---")
        for entry in result.outputs:
            if isinstance(entry, dict):
                label = entry.get("label", "")
                data = entry.get("data")
            else:
                label = ""
                data = entry
            data_str = (
                json.dumps(data, ensure_ascii=False, indent=2)
                if not isinstance(data, str)
                else data
            )
            if label:
                parts.append(f"[{label}]")
            parts.append(data_str)

    return "\n".join(parts)


def cmd_exec(args):
    client = SandboxClient(default_timeout=args.timeout)

    if args.file:
        if args.file == "-":
            code = sys.stdin.read()
        else:
            result = client.execute_file(args.file, language=args.language, timeout=args.timeout)
            output = format_result(result, as_json=args.json)
            print(output)
            if args.output:
                with open(args.output, "w") as f:
                    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            sys.exit(0 if result.success else 1)
            return
    elif args.code:
        if args.code == "-":
            code = sys.stdin.read()
        else:
            code = args.code
    else:
        if not sys.stdin.isatty():
            code = sys.stdin.read()
        else:
            print(
                "Error: provide code as argument, -f FILE, or pipe via stdin",
                file=sys.stderr,
            )
            sys.exit(1)
            return

    result = client.execute(code, language=args.language, timeout=args.timeout)
    output = format_result(result, as_json=args.json)
    print(output)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

    sys.exit(0 if result.success else 1)


def cmd_info(args):
    client = SandboxClient()
    print(client.info(language=args.language))


def main():
    parser = argparse.ArgumentParser(
        prog="sandbox",
        description="Execute Python/JS code with auto-injected SDK helpers",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # exec
    p_exec = sub.add_parser("exec", help="Execute code")
    p_exec.add_argument("code", nargs="?", help="Code to execute (or use -f)")
    p_exec.add_argument("-f", "--file", help="Read code from file (- for stdin)")
    p_exec.add_argument(
        "-l",
        "--language",
        default="python",
        choices=["python", "javascript"],
    )
    p_exec.add_argument("-t", "--timeout", type=int, default=30, help="Timeout in seconds (1-60)")
    p_exec.add_argument("-o", "--output", help="Write result JSON to file")
    p_exec.add_argument("--json", action="store_true", help="Output as JSON")
    p_exec.set_defaults(func=cmd_exec)

    # info
    p_info = sub.add_parser("info", help="Show SDK documentation")
    p_info.add_argument(
        "-l",
        "--language",
        default="python",
        choices=["python", "javascript"],
    )
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
