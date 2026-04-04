"""
PM Auto-Pilot — unified handler for SessionStart, PostToolUse/Bash, Stop.

Replaces manual /pm:* workflow with automatic:
  - SessionStart: inject open issues summary + current branch context
  - PostToolUse/Bash: enhanced commit sync, merge close suggestion, worktree orphan detection
  - Stop: suggest next task if nothing in-progress

Non-blocking design:
  - SessionStart: sync (must return message) but tight timeouts (max ~13s)
  - PostToolUse: git reads sync (fast), gh writes fire-and-forget background
  - Stop: local file read only (<1ms)
"""

from __future__ import annotations

import json
import re

from .base import ALLOW, HookResult, message, run_background, run_cmd
from .hook_config import cfg

REPO = cfg.get("github", {}).get("repo", "")
STATE_FILE = "/tmp/pm-autopilot-state.json"  # noqa: S108
MAX_SYNC_ISSUES = 3


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if not REPO:
        return ALLOW
    if event_type == "SessionStart":
        return _session_start()
    if event_type == "PostToolUse" and tool_name == "Bash":
        return _post_bash(tool_input)
    if event_type == "Stop":
        return _on_stop()
    return ALLOW


# ---------------------------------------------------------------------------
# A. SessionStart — environment awareness injection (sync, tight timeouts)
# ---------------------------------------------------------------------------


def _session_start() -> HookResult:
    # 1. Fetch open issues (must be sync for message injection)
    result = run_cmd(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--json",
            "number,title,labels",
            "--limit",
            "20",
            "--repo",
            REPO,
        ],
        timeout=5,
    )
    if result is None or result.returncode != 0:
        _save_pm_state({"issues": [], "in_progress": [], "ready": []})
        return ALLOW

    try:
        issues = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        _save_pm_state({"issues": [], "in_progress": [], "ready": []})
        return ALLOW

    if not issues:
        _save_pm_state({"issues": [], "in_progress": [], "ready": []})
        return ALLOW

    # 2. Categorize by label
    in_progress = []
    blocked = []
    ready = []
    for issue in issues:
        label_names = [lb["name"] for lb in issue.get("labels", [])]
        if "in-progress" in label_names:
            in_progress.append(issue)
        elif "blocked" in label_names:
            blocked.append(issue)
        else:
            ready.append(issue)

    # Save state for Stop handler
    _save_pm_state(
        {
            "issues": issues,
            "in_progress": [i["number"] for i in in_progress],
            "ready": [i["number"] for i in ready],
            "blocked": [i["number"] for i in blocked],
        }
    )

    # 3. Build markdown summary
    parts = ["## GitHub PM Status"]

    if in_progress:
        parts.append("### In Progress")
        for i in in_progress:
            labels = ", ".join(
                lb["name"] for lb in i.get("labels", []) if lb["name"] != "in-progress"
            )
            suffix = f" ({labels})" if labels else ""
            parts.append(f"- #{i['number']} {i['title']}{suffix}")

    if blocked:
        parts.append("### Blocked")
        for i in blocked:
            parts.append(f"- #{i['number']} {i['title']}")

    if ready:
        parts.append("### Ready")
        for i in ready[:5]:
            labels = ", ".join(lb["name"] for lb in i.get("labels", []))
            suffix = f" ({labels})" if labels else ""
            parts.append(f"- #{i['number']} {i['title']}{suffix}")
        if len(ready) > 5:
            parts.append(f"  ... and {len(ready) - 5} more")

    parts.append(
        f"**Total**: {len(issues)} open"
        f" ({len(in_progress)} in-progress, {len(blocked)} blocked, {len(ready)} ready)"
    )

    # 4. Current branch context
    branch_ctx = _get_branch_context()
    if branch_ctx:
        parts.append("")
        parts.append(branch_ctx)

    return message("\n".join(parts))


def _get_branch_context() -> str:
    """If current branch contains #N, fetch issue details."""
    branch_result = run_cmd(["git", "branch", "--show-current"], timeout=3)
    if not branch_result or branch_result.returncode != 0:
        return ""

    branch = branch_result.stdout.strip()
    if not branch:
        return ""

    match = re.search(r"#(\d+)", branch)
    if not match:
        return ""

    issue_num = match.group(1)

    # Fetch issue body for acceptance criteria
    view_result = run_cmd(
        ["gh", "issue", "view", issue_num, "--repo", REPO, "--json", "title,body,state"],
        timeout=5,
    )
    if not view_result or view_result.returncode != 0:
        return (
            f"### Current: #{issue_num}\nOn branch `{branch}`, commits auto-sync to #{issue_num}."
        )

    try:
        data = json.loads(view_result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return (
            f"### Current: #{issue_num}\nOn branch `{branch}`, commits auto-sync to #{issue_num}."
        )

    title = data.get("title", "")
    body = data.get("body", "") or ""

    # Extract acceptance criteria (lines starting with - [ ] or - [x])
    criteria = [line.strip() for line in body.splitlines() if re.match(r"^\s*-\s*\[[ xX]\]", line)]

    lines = [f"### Current: #{issue_num} {title}"]
    lines.append(f"On branch `{branch}`, commits auto-sync to #{issue_num}.")
    if criteria:
        lines.append("Acceptance criteria:")
        lines.extend(criteria[:10])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# B. PostToolUse/Bash — commit sync + merge detection + worktree orphan
#    gh writes are fire-and-forget (run_background), git reads are sync (fast)
# ---------------------------------------------------------------------------


def _post_bash(tool_input: dict) -> HookResult:
    command = tool_input.get("command", "")

    if "git commit" in command:
        return _handle_commit()
    if "git merge" in command:
        return _handle_merge(command)
    if "git worktree remove" in command:
        return _handle_worktree_remove(command)

    return ALLOW


def _handle_commit() -> HookResult:
    """Enhanced commit sync: post comment with diff stat to referenced issues.

    Git reads are sync (< 100ms each). gh issue comment is fire-and-forget.
    """
    # Get latest commit info
    log_result = run_cmd(["git", "log", "-1", "--format=%h%n%s"], timeout=3)
    if log_result is None or log_result.returncode != 0:
        return ALLOW

    log_lines = log_result.stdout.strip().split("\n", 1)
    if len(log_lines) < 2:
        return ALLOW

    commit_hash = log_lines[0]
    commit_subject = log_lines[1]

    # Get full commit message for issue extraction
    full_msg_result = run_cmd(["git", "log", "-1", "--format=%s%n%b"], timeout=3)
    full_msg = full_msg_result.stdout.strip() if full_msg_result else commit_subject

    # Extract issue numbers from commit message + branch
    branch_result = run_cmd(["git", "branch", "--show-current"], timeout=3)
    branch = branch_result.stdout.strip() if branch_result and branch_result.returncode == 0 else ""

    issue_numbers = _extract_issues(full_msg, branch)
    if not issue_numbers:
        return ALLOW

    # Cap to avoid runaway background processes
    capped = sorted(issue_numbers)[:MAX_SYNC_ISSUES]

    # Get diff stat for enhanced comment
    diff_result = run_cmd(["git", "diff", "--stat", "HEAD~1..HEAD"], timeout=3)
    diff_stat = ""
    if diff_result and diff_result.returncode == 0:
        stat_lines = diff_result.stdout.strip().splitlines()
        if stat_lines:
            file_lines = stat_lines[:-1][:8]
            summary_line = stat_lines[-1] if stat_lines else ""
            if file_lines:
                diff_stat = "\n```\n" + "\n".join(file_lines)
                if len(stat_lines) - 1 > 8:
                    diff_stat += f"\n  ... and {len(stat_lines) - 1 - 8} more files"
                if summary_line:
                    diff_stat += f"\n{summary_line}"
                diff_stat += "\n```"

    # Fire-and-forget: post comment on each referenced issue (background)
    for num in capped:
        comment_body = f"Commit `{commit_hash}`: {commit_subject}"
        if diff_stat:
            comment_body += f"\n{diff_stat}"
        run_background(
            ["gh", "issue", "comment", num, "--repo", REPO, "--body", comment_body],
        )

    labels = ", ".join(f"#{n}" for n in capped)
    extra = (
        f" (+{len(issue_numbers) - MAX_SYNC_ISSUES} skipped)"
        if len(issue_numbers) > MAX_SYNC_ISSUES
        else ""
    )
    return message(f"Syncing commit {commit_hash} to {labels}{extra}")


def _handle_merge(command: str) -> HookResult:
    """After git merge, suggest closing the issue if branch contains #N.

    gh issue view is fire-and-forget — writes suggestion to tmp for display.
    """
    parts = command.split()
    branch_name = ""
    for i, p in enumerate(parts):
        if p == "merge":
            for j in range(i + 1, len(parts)):
                if not parts[j].startswith("-"):
                    branch_name = parts[j]
                    break
            break

    if not branch_name:
        return ALLOW

    match = re.search(r"#(\d+)", branch_name)
    if not match:
        return ALLOW

    issue_num = match.group(1)

    # Check if issue is still open (sync but tight timeout)
    view_result = run_cmd(
        ["gh", "issue", "view", issue_num, "--repo", REPO, "--json", "state,title"],
        timeout=3,
    )
    if not view_result or view_result.returncode != 0:
        return ALLOW

    try:
        data = json.loads(view_result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return ALLOW

    if data.get("state") == "OPEN":
        title = data.get("title", "")
        return message(
            f"Merge detected for #{issue_num} ({title}). "
            f"Issue is still OPEN — consider closing it with: "
            f"`gh issue close {issue_num} --repo {REPO}`"
        )

    return ALLOW


def _handle_worktree_remove(command: str) -> HookResult:
    """Warn if removing a worktree tied to an open issue."""
    match = re.search(r"#(\d+)", command)
    if not match:
        return ALLOW

    issue_num = match.group(1)

    view_result = run_cmd(
        ["gh", "issue", "view", issue_num, "--repo", REPO, "--json", "state"],
        timeout=3,
    )
    if not view_result or view_result.returncode != 0:
        return ALLOW

    try:
        data = json.loads(view_result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return ALLOW

    if data.get("state") == "OPEN":
        return message(f"Worktree removed but #{issue_num} is still OPEN. Forgot to close it?")

    return ALLOW


# ---------------------------------------------------------------------------
# C. Stop — suggest next task (local file read only, <1ms)
# ---------------------------------------------------------------------------


def _on_stop() -> HookResult:
    state = _load_pm_state()
    if not state:
        return ALLOW

    in_progress = state.get("in_progress", [])
    ready = state.get("ready", [])

    if not in_progress and ready:
        issues = state.get("issues", [])
        issue_map = {i["number"]: i for i in issues}
        next_num = ready[0]
        next_issue = issue_map.get(next_num)
        if next_issue:
            title = next_issue.get("title", "")
            return message(f"No in-progress issues. Next candidate: #{next_num} {title}")

    return ALLOW


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _extract_issues(text: str, branch: str) -> set[str]:
    """Extract issue numbers from commit message text and branch name."""
    nums: set[str] = set()

    # Match: Closes #N, Fixes #N, Refs #N, Part of #N
    for m in re.finditer(r"(?:Closes|Fixes|Refs|Part of)\s+#(\d+)", text):
        nums.add(m.group(1))
    # Match standalone #N (not preceded by word char — avoids color hex)
    for m in re.finditer(r"(?<!\w)#(\d+)\b", text):
        nums.add(m.group(1))

    # Branch name: feature/slug-#42
    if branch:
        branch_match = re.search(r"#(\d+)", branch)
        if branch_match:
            nums.add(branch_match.group(1))

    return nums


def _load_pm_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_pm_state(data: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass
