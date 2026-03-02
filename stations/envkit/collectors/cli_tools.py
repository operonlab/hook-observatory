"""CLI tools collector — detect installed command-line tools."""

from __future__ import annotations

import shutil
import subprocess


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# Tools to detect, grouped by category
TOOL_REGISTRY: dict[str, list[dict]] = {
    "ai": [
        {"name": "claude", "version_cmd": ["claude", "--version"]},
        {"name": "gemini", "version_cmd": ["gemini", "--version"]},
        {"name": "codex", "version_cmd": ["codex", "--version"]},
        {"name": "ollama", "version_cmd": ["ollama", "--version"]},
        {"name": "litellm", "version_cmd": ["litellm", "--version"]},
        {"name": "claude-squad", "version_cmd": ["claude-squad", "version"]},
        {"name": "recall", "version_cmd": ["recall", "--version"]},
    ],
    "dev": [
        {"name": "git", "version_cmd": ["git", "--version"]},
        {"name": "gh", "version_cmd": ["gh", "--version"]},
        {"name": "uv", "version_cmd": ["uv", "--version"]},
        {"name": "node", "version_cmd": ["node", "--version"]},
        {"name": "pnpm", "version_cmd": ["pnpm", "--version"]},
        {"name": "bun", "version_cmd": ["bun", "--version"]},
        {"name": "go", "version_cmd": ["go", "version"]},
        {"name": "make", "version_cmd": ["make", "--version"]},
    ],
    "search": [
        {"name": "rg", "version_cmd": ["rg", "--version"]},
        {"name": "fzf", "version_cmd": ["fzf", "--version"]},
        {"name": "bat", "version_cmd": ["bat", "--version"]},
        {"name": "fd", "version_cmd": ["fd", "--version"]},
        {"name": "zoxide", "version_cmd": ["zoxide", "--version"]},
        {"name": "sd", "version_cmd": ["sd", "--version"]},
        {"name": "delta", "version_cmd": ["delta", "--version"]},
        {"name": "difft", "version_cmd": ["difft", "--version"]},
        {"name": "ast-grep", "version_cmd": ["ast-grep", "--version"]},
        {"name": "tokei", "version_cmd": ["tokei", "--version"]},
    ],
    "media": [
        {"name": "ffmpeg", "version_cmd": ["ffmpeg", "-version"]},
        {"name": "sox", "version_cmd": ["sox", "--version"]},
        {"name": "magick", "version_cmd": ["magick", "--version"]},
        {"name": "pandoc", "version_cmd": ["pandoc", "--version"]},
        {"name": "tesseract", "version_cmd": ["tesseract", "--version"]},
        {"name": "mmdc", "version_cmd": ["mmdc", "--version"]},
    ],
    "network": [
        {"name": "mosh", "version_cmd": ["mosh", "--version"]},
        {"name": "cloudflared", "version_cmd": ["cloudflared", "--version"]},
        {"name": "ttyd", "version_cmd": ["ttyd", "--version"]},
        {"name": "curl", "version_cmd": ["curl", "--version"]},
        {"name": "wget", "version_cmd": ["wget", "--version"]},
    ],
    "system": [
        {"name": "tmux", "version_cmd": ["tmux", "-V"]},
        {"name": "mc", "version_cmd": ["mc", "--version"]},
        {"name": "glow", "version_cmd": ["glow", "--version"]},
        {"name": "hyperfine", "version_cmd": ["hyperfine", "--version"]},
        {"name": "gum", "version_cmd": ["gum", "--version"]},
        {"name": "yq", "version_cmd": ["yq", "--version"]},
        {"name": "jq", "version_cmd": ["jq", "--version"]},
        {"name": "git-cliff", "version_cmd": ["git-cliff", "--version"]},
    ],
}


def _get_version(tool: dict) -> str:
    """Get first line of version output, cleaned up."""
    out = _run(tool["version_cmd"])
    if not out:
        return ""
    first_line = out.splitlines()[0].strip()
    if not first_line:
        return ""

    import re
    # Extract version number pattern (e.g., 1.2.3, 0.41.0, 22.22.0)
    m = re.search(r'(\d+\.\d+(?:\.\d+)?(?:[._-]\w+)?)', first_line)
    return m.group(1) if m else first_line


def collect() -> dict:
    result: dict = {}
    all_tools: list[dict] = []

    for category, tools in TOOL_REGISTRY.items():
        cat_tools = []
        for tool in tools:
            path = shutil.which(tool["name"])
            if path:
                version = _get_version(tool)
                entry = {"name": tool["name"], "path": path, "version": version}
                cat_tools.append(entry)
                all_tools.append(entry)
        result[category] = cat_tools

    result["total_count"] = len(all_tools)
    return result
