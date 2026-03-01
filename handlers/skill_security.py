"""
Skill security gate — PreToolUse handler for Write/Edit on skill files.

Scans SKILL.md content for S1-S3 security threats:
  S1: Prompt Injection
  S2: Privilege Escalation
  S3: Data Exfiltration
"""

from __future__ import annotations

import os
import re

from .base import ALLOW, SKILLS_DIR, HookResult, block


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if tool_name not in ("Write", "Edit"):
        return ALLOW

    file_path = tool_input.get("file_path", "")
    if not _is_skill_markdown(file_path):
        return ALLOW

    content = tool_input.get("content", "") if tool_name == "Write" else tool_input.get("new_string", "")
    if not content:
        return ALLOW

    findings = _scan_content(content)
    critical = [f for f in findings if f["category"] in ("S1", "S2", "S3")]
    if not critical:
        return ALLOW

    lines = [f"  Line {f['line']}: {f['description']}" for f in critical[:5]]
    summary = "\n".join(lines)
    dirname = os.path.basename(os.path.dirname(file_path))
    reason = (
        f"Security Gate: {len(critical)} critical finding(s) in skill file "
        f"{dirname}/\n{summary}\n"
        f"Run /skill-security-scan for deep analysis."
    )
    return block(reason)


# ---------------------------------------------------------------------------
# Pattern tables
# ---------------------------------------------------------------------------

_S1 = [
    (r"ignore\s+(all\s+)?previous\s+instructions", "S1: prompt override — 'ignore previous instructions'"),
    (r"you\s+are\s+now\s+a", "S1: identity hijack — 'you are now a'"),
    (r"system\s*prompt\s*override", "S1: explicit system prompt override"),
    (r"(?:forget|disregard)\s+(?:everything|all|your|the)", "S1: memory wipe — 'forget everything'"),
    (r"new\s+instructions?\s*:", "S1: instruction injection — 'new instructions:'"),
    (r"<\s*/?system\s*>", "S1: XML system tag injection"),
    (r"]\s*}\s*}\s*{", "S1: JSON structure escape attempt"),
    (r"(?:^|\n)\s*---\s*\n.*?role\s*:\s*system", "S1: YAML frontmatter role injection"),
]

_S2 = [
    (r"\bdangerouslyDisableSandbox\b", "S2: sandbox disable request"),
    (r"\bsudo\s+", "S2: sudo in skill content"),
    (r"\bchmod\s+777\b", "S2: world-writable permission"),
    (r"--no-verify\b", "S2: git hook bypass"),
    (r"\.claude/settings\.json", "S2: attempt to modify Claude settings"),
    (r"\.claude/hooks/", "S2: attempt to modify hooks directory"),
    (r"\.claude/rules/", "S2: attempt to modify rules directory"),
    (r"\bkill\s+.*claude", "S2: kill Claude process"),
    (r"\bpkill\s+.*claude", "S2: pkill Claude process"),
    (r"\bgit\s+push\s+--force\b", "S2: force push in skill"),
    (r"\bgit\s+reset\s+--hard\b", "S2: hard reset in skill"),
]

_S3 = [
    (r"\bcurl\s+(?!.*(?:localhost|127\.0\.0\.1|0\.0\.0\.0))", "S3: external curl (non-localhost)"),
    (r"\bwget\s+(?!.*(?:localhost|127\.0\.0\.1))", "S3: external wget"),
    (r"\.env\b(?!\.d\.ts)", "S3: .env file access (not .env.d.ts)"),
    (r"\.ssh/", "S3: SSH directory access"),
    (r"\.aws/", "S3: AWS credentials access"),
    (r"\bcredentials\b(?!.*(?:\.md|documentation|example))", "S3: credentials file access"),
    (r"(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"][^'\"]{8,}", "S3: hardcoded secret"),
    (r"base64\s*(?:encode|decode).*(?:curl|wget|http)", "S3: base64 + HTTP exfil pattern"),
]

_ALL_PATTERNS = _S1 + _S2 + _S3

_ALLOWLIST = [
    r"(?:detect|scan|check|pattern|warn|block|deny|example|e\.g\.|blacklist|NEVER|DON'T)",
    r"(?:flag|signal|target|reference|attempt|mention|modify|access|write\s+to)",
    r"\b(?:technique|vector|attack|method|goal|override|hijack|inject|payload|exfil)\b",
    r"```",
    r"`[^`]+`",
    r"#\s+",
    r"^\|",
    r"^\*\*",
    r"^-\s+\*\*",
    r"^\d+\.\s+",
    r'^"[^"]+"\s*$',
]


def _is_skill_markdown(file_path: str) -> bool:
    if not file_path:
        return False
    expanded = os.path.expanduser(file_path)
    return expanded.startswith(SKILLS_DIR + "/") and expanded.endswith(".md")


def _scan_content(content: str) -> list[dict]:
    findings: list[dict] = []
    in_fence = False
    for line_num, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if any(re.search(ctx, stripped, re.IGNORECASE) for ctx in _ALLOWLIST):
            continue
        for pattern, description in _ALL_PATTERNS:
            if re.search(pattern, stripped, re.IGNORECASE):
                findings.append({
                    "line": line_num,
                    "category": description[:2],
                    "description": description,
                    "content": stripped[:120],
                })
    return findings
