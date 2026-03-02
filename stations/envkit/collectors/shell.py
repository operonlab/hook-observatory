"""Shell collector — Zsh config, Oh My Zsh plugins/theme."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def collect() -> dict:
    home = Path.home()
    result: dict = {
        "shell": os.environ.get("SHELL", ""),
    }

    # Zsh version
    zsh_ver = _run("zsh --version 2>/dev/null")
    if zsh_ver:
        result["zsh_version"] = zsh_ver.split()[1] if len(zsh_ver.split()) > 1 else zsh_ver

    # Config files existence
    configs = {}
    for name, path in [
        ("zshrc", home / ".zshrc"),
        ("zshenv", home / ".zshenv"),
        ("zprofile", home / ".zprofile"),
        ("tmux_conf", home / ".tmux.conf"),
    ]:
        configs[name] = path.exists()
    result["configs"] = configs

    # Oh My Zsh
    omz_dir = home / ".oh-my-zsh"
    if omz_dir.is_dir():
        result["oh_my_zsh"] = True

        # Parse theme from .zshrc
        zshrc = home / ".zshrc"
        theme = ""
        plugins = []
        if zshrc.exists():
            try:
                content = zshrc.read_text()
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("ZSH_THEME="):
                        theme = line.split("=", 1)[1].strip('"').strip("'")
                    if line.startswith("plugins=("):
                        # May span multiple lines, grab single-line case
                        inner = line.replace("plugins=(", "").replace(")", "")
                        plugins = inner.split()
            except OSError:
                pass

        result["zsh_theme"] = theme
        result["zsh_plugins"] = plugins

        # Custom plugins
        custom_dir = omz_dir / "custom" / "plugins"
        if custom_dir.is_dir():
            custom_plugins = [d.name for d in custom_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
            result["custom_plugins"] = sorted(custom_plugins)
    else:
        result["oh_my_zsh"] = False

    # tmux plugins (tpm)
    tpm_dir = home / ".tmux" / "plugins"
    if tpm_dir.is_dir():
        tmux_plugins = [d.name for d in tpm_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        result["tmux_plugins"] = sorted(tmux_plugins)

    return result
