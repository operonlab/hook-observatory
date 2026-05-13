"""
PostToolUse/Bash: auto-detect issue refs in git commits and sync to GitHub.

When a Bash command contains 'git commit', checks the latest commit for
issue references (#N, Fixes #N, Closes #N, Part of #N) and posts a
progress comment on the referenced GitHub Issue.

Also checks the current branch name for issue references (feature/foo-#42).
"""

from __future__ import annotations

import re

from .base import ALLOW, HookResult, message, run_cmd

REPO = "JonesHong/workshop"


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Post commit info to referenced GitHub Issues."""
    command = tool_input.get("command", "")

    # Only trigger on git commit commands
    if "git commit" not in command:
        return ALLOW

    # Get the latest commit message + hash
    log_result = run_cmd(["git", "log", "-1", "--format=%h%n%s"], timeout=5)
    if log_result is None or log_result.returncode != 0:
        return ALLOW

    lines = log_result.stdout.strip().split("\n", 1)
    if len(lines) < 2:
        return ALLOW

    commit_hash = lines[0]
    commit_subject = lines[1]

    # Extract issue references from commit message
    full_msg_result = run_cmd(["git", "log", "-1", "--format=%s%n%b"], timeout=5)
    full_msg = full_msg_result.stdout.strip() if full_msg_result else commit_subject

    issue_numbers: set[str] = set()

    # Match: #N, Closes #N, Fixes #N, Refs #N, Part of #N
    for m in re.finditer(r"(?:Closes|Fixes|Refs|Part of)\s+#(\d+)", full_msg):
        issue_numbers.add(m.group(1))
    # Match standalone #N (not preceded by color hex like #FFFFFF)
    for m in re.finditer(r"(?<!\w)#(\d+)\b", full_msg):
        issue_numbers.add(m.group(1))

    # Also check branch name for issue reference (feature/slug-#42)
    branch_result = run_cmd(["git", "branch", "--show-current"], timeout=5)
    if branch_result and branch_result.returncode == 0:
        branch = branch_result.stdout.strip()
        branch_match = re.search(r"#(\d+)", branch)
        if branch_match:
            issue_numbers.add(branch_match.group(1))

    if not issue_numbers:
        return ALLOW

    # Post comment on each referenced issue (fire-and-forget, don't block)
    synced = []
    for num in issue_numbers:
        comment = f"Commit `{commit_hash}`: {commit_subject}"
        result = run_cmd(
            ["gh", "issue", "comment", num, "--repo", REPO, "--body", comment],
            timeout=10,
        )
        if result and result.returncode == 0:
            synced.append(f"#{num}")

    if synced:
        return message(f"Synced commit {commit_hash} to {', '.join(synced)}")

    return ALLOW
