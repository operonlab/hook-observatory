"""Shared CLI utilities — input helpers for long-text arguments.

Usage in argparse-based CLIs:

    from core.cli.cli_utils import resolve_text_arg

    # After parsing args:
    content = resolve_text_arg(args.content)  # handles "-" (stdin) and "@file"
"""

import sys


def resolve_text_arg(value: str | None) -> str | None:
    """Resolve a text argument that may reference stdin or a file.

    Conventions (Unix-style):
        "-"           → read entire stdin
        "@/path/file" → read file at path
        other         → return as-is

    Returns None if value is None.
    """
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@") and len(value) > 1:
        path = value[1:]
        with open(path) as f:
            return f.read()
    return value
