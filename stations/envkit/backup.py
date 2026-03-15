"""
EnvKit Backup — Tier 1-2 config file backup.

Tier 1 (critical): tmux, zsh, Claude Code, git
Tier 2 (important): VS Code, Codex, Gemini, LiteLLM
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()

# Tier 1 — Critical configs
TIER1_FILES: list[dict] = [
    {"src": HOME / ".tmux.conf", "dst": "tmux.conf", "label": "tmux config"},
    {"src": HOME / ".zshrc", "dst": "zshrc", "label": "Zsh config"},
    {"src": HOME / ".zshenv", "dst": "zshenv", "label": "Zsh environment"},
    {"src": HOME / ".gitconfig", "dst": "gitconfig", "label": "Git config"},
    {"src": HOME / ".gitignore_global", "dst": "gitignore_global", "label": "Git global ignore"},
    {
        "src": HOME / ".claude" / "settings.json",
        "dst": "claude-settings.json",
        "label": "Claude Code settings",
    },
    {
        "src": HOME / ".claude" / "CLAUDE.md",
        "dst": "claude-md",
        "label": "Claude Code instructions",
    },
]

# Tier 1 — Critical directories (shallow copy)
TIER1_DIRS: list[dict] = [
    {"src": HOME / ".oh-my-zsh" / "custom", "dst": "oh-my-zsh-custom", "label": "OMZ custom"},
]

# Tier 2 — Important configs
TIER2_FILES: list[dict] = [
    {
        "src": HOME / "Library" / "Application Support" / "Code" / "User" / "settings.json",
        "dst": "vscode-settings.json",
        "label": "VS Code settings",
    },
]

# Tier 2 — Directories
TIER2_DIRS: list[dict] = [
    {"src": HOME / ".codex", "dst": "codex", "label": "Codex CLI config"},
    {"src": HOME / ".gemini", "dst": "gemini", "label": "Gemini CLI config"},
    {"src": HOME / ".config" / "litellm", "dst": "litellm", "label": "LiteLLM config"},
]


_logger = logging.getLogger(__name__)


def _safe_copy2(src: str, dst: str) -> None:
    """shutil.copy2 wrapper that skips broken symlinks and permission errors."""
    try:
        shutil.copy2(src, dst)
    except (OSError, PermissionError) as e:
        _logger.debug("copy failed: %s → %s: %s", src, dst, e)
        pass


def backup_configs(output_dir: Path) -> dict:
    """Backup Tier 1-2 config files to output_dir.

    Returns summary dict with backed_up and skipped lists.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    backed_up: list[str] = []
    skipped: list[str] = []

    # Tier 1 files
    for item in TIER1_FILES:
        src = item["src"]
        dst = output_dir / item["dst"]
        if src.exists():
            shutil.copy2(src, dst)
            backed_up.append(f"[T1] {item['label']}: {src}")
        else:
            skipped.append(f"[T1] {item['label']}: {src} (not found)")

    # Tier 1 directories
    for item in TIER1_DIRS:
        src = item["src"]
        dst = output_dir / item["dst"]
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(
                src,
                dst,
                symlinks=True,
                dirs_exist_ok=True,
                ignore_dangling_symlinks=True,
                copy_function=_safe_copy2,
            )
            backed_up.append(f"[T1] {item['label']}: {src}")
        else:
            skipped.append(f"[T1] {item['label']}: {src} (not found)")

    # Tier 2 files
    for item in TIER2_FILES:
        src = item["src"]
        dst = output_dir / item["dst"]
        if src.exists():
            shutil.copy2(src, dst)
            backed_up.append(f"[T2] {item['label']}: {src}")
        else:
            skipped.append(f"[T2] {item['label']}: {src} (not found)")

    # Tier 2 directories
    for item in TIER2_DIRS:
        src = item["src"]
        dst = output_dir / item["dst"]
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(
                src,
                dst,
                symlinks=True,
                dirs_exist_ok=True,
                ignore_dangling_symlinks=True,
                copy_function=_safe_copy2,
            )
            backed_up.append(f"[T2] {item['label']}: {src}")
        else:
            skipped.append(f"[T2] {item['label']}: {src} (not found)")

    # VS Code extensions list
    code_bin = shutil.which("code")
    if code_bin:
        try:
            r = subprocess.run(
                [code_bin, "--list-extensions"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0 and r.stdout.strip():
                ext_path = output_dir / "vscode-extensions.txt"
                ext_path.write_text(r.stdout)
                backed_up.append("[T2] VS Code extensions list")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            skipped.append("[T2] VS Code extensions: command failed")
    else:
        skipped.append("[T2] VS Code extensions: 'code' not in PATH")

    # Write manifest
    manifest = output_dir / "backup-manifest.txt"
    lines = [
        f"EnvKit Config Backup — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Output: {output_dir}",
        "",
        f"Backed up ({len(backed_up)}):",
    ]
    for item in backed_up:
        lines.append(f"  + {item}")
    lines.append(f"\nSkipped ({len(skipped)}):")
    for item in skipped:
        lines.append(f"  - {item}")
    manifest.write_text("\n".join(lines) + "\n")

    return {
        "output_dir": str(output_dir),
        "backed_up_count": len(backed_up),
        "skipped_count": len(skipped),
        "backed_up": backed_up,
        "skipped": skipped,
    }


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("configs")
    result = backup_configs(out)
    print(f"Backed up: {result['backed_up_count']}")
    print(f"Skipped: {result['skipped_count']}")
    for item in result["backed_up"]:
        print(f"  + {item}")
    for item in result["skipped"]:
        print(f"  - {item}")
