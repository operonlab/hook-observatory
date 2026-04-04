"""
Secret scanning before git push — PreToolUse handler for Bash tool.

CRITICAL handler: always runs (not subject to 5s deferrable budget).
Scans git diff for hardcoded secrets before push. Only fires on `git push`.

Escape hatches:
  - SECRET_SCAN_DISABLE=1 env var disables entirely
  - `# nosec` at end of line skips that line
  - 3s timeout guard: warns instead of blocking on timeout
"""

from __future__ import annotations

import os
import re

from .base import ALLOW, HookResult, block, message, run_cmd

# ---------------------------------------------------------------------------
# Secret patterns — tuned for low false-positive rate
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"gh[ps]_[A-Za-z0-9_]{36,}"), "GitHub Token"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack Token"),
    (re.compile(r"-----BEGIN .* PRIVATE KEY-----"), "Private Key"),  # nosec
    (
        re.compile(
            r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)"
            r"\s*[=:]\s*['\"][^'\"]{12,}",
            re.IGNORECASE,
        ),
        "Generic Secret Assignment",
    ),
]

# Lines containing these tokens are likely examples/placeholders, skip them
_FALSE_POSITIVE_TOKENS = {
    "example",
    "placeholder",
    "changeme",
    "todo",
    "fixme",
    "your-",
    "your_",
    "xxx",
    "dummy",
    "fake",
    "mock",
    "test_",
    "sample",
    "template",
}

# File paths to skip (test fixtures, examples, docs)
_SKIP_PATH_PATTERNS = {
    "test/",
    "tests/",
    "fixtures/",
    "mocks/",
    ".example",
    ".sample",
    ".template",
}


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name != "Bash":
        return ALLOW

    # Escape hatch: env var disable
    if os.environ.get("SECRET_SCAN_DISABLE") == "1":
        return ALLOW

    command = tool_input.get("command", "")
    if not command:
        return ALLOW

    # Only fire on git push (not --dry-run)
    if not re.search(r"\bgit\s+push\b", command):
        return ALLOW
    if "--dry-run" in command:
        return ALLOW

    # Get diff of unpushed commits
    diff_text = _get_unpushed_diff()
    if diff_text is None:
        return message(
            "\u26a0\ufe0f secret scan: \u7121\u6cd5\u53d6\u5f97 diff\uff0c\u6383\u63cf\u8df3\u904e"
        )

    if not diff_text.strip():
        return ALLOW

    # Scan only added lines
    findings = _scan_added_lines(diff_text)
    if findings:
        detail = "\n".join(f"  - {f}" for f in findings[:5])
        if len(findings) > 5:
            detail += f"\n  ... and {len(findings) - 5} more"
        return block(
            f"\u5075\u6e2c\u5230\u7591\u4f3c secret ({len(findings)} \u8655):\n{detail}\n"
            f"\u82e5\u70ba\u8aa4\u5831\uff0c\u5728\u884c\u5c3e\u52a0 # nosec"
            f" \u6216\u8a2d SECRET_SCAN_DISABLE=1"
        )

    return ALLOW


def _get_unpushed_diff() -> str | None:
    """Get diff of commits not yet pushed. Returns None on failure/timeout."""
    # Try upstream tracking branch first
    result = run_cmd(
        ["git", "diff", "@{upstream}..HEAD"],
        timeout=3,
    )
    if result and result.returncode == 0:
        return result.stdout

    # Fallback: diff against origin/main
    result = run_cmd(
        ["git", "diff", "origin/main..HEAD"],
        timeout=3,
    )
    if result and result.returncode == 0:
        return result.stdout

    # Last resort: just the latest commit
    result = run_cmd(
        ["git", "log", "-1", "-p", "--format="],
        timeout=3,
    )
    if result and result.returncode == 0:
        return result.stdout

    return None


def _scan_added_lines(diff_text: str) -> list[str]:
    """Scan added lines in unified diff for secret patterns."""
    findings: list[str] = []
    current_file = ""

    for line in diff_text.splitlines():
        # Track current file from diff headers
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue

        # Skip non-added lines
        if not line.startswith("+") or line.startswith("+++"):
            continue

        added_line = line[1:]  # strip the leading +

        # Skip if file path matches skip patterns
        if any(pat in current_file for pat in _SKIP_PATH_PATTERNS):
            continue

        # Skip comments
        stripped = added_line.strip()
        if stripped.startswith(("#", "//", "/*", "*", "<!--")):
            continue

        # Skip lines with # nosec annotation
        if "# nosec" in added_line or "// nosec" in added_line:
            continue

        # Skip false-positive tokens
        lower = added_line.lower()
        if any(token in lower for token in _FALSE_POSITIVE_TOKENS):
            continue

        # Check against secret patterns
        for pattern, label in _PATTERNS:
            if pattern.search(added_line):
                # Truncate the line for display (don't leak the actual secret)
                preview = added_line.strip()[:40]
                if len(added_line.strip()) > 40:
                    preview += "..."
                findings.append(f"{label} in {current_file}: {preview}")
                break  # one finding per line is enough

    return findings
