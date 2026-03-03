#!/usr/bin/env python3
"""
EnvKit Bootstrap — restore a Mac from an envkit snapshot.

Usage:
    python3 bootstrap/bootstrap.py <snapshot.yaml> [--from N] [--to N] [--dry-run]

Phase 1 (infra) must be run separately as a shell script first.
This script handles phases 2-9.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Add parent dir so we can import envkit's YAML parser
ENVKIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENVKIT_DIR))

from envkit import from_yaml  # noqa: E402

HOME = Path.home()
CONFIGS_DIR = ENVKIT_DIR / "configs"

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
NC = "\033[0m"


def log(phase: int, msg: str) -> None:
    print(f"{GREEN}[phase{phase}]{NC} {msg}")


def warn(phase: int, msg: str) -> None:
    print(f"{YELLOW}[phase{phase}]{NC} {msg}")


def err(phase: int, msg: str) -> None:
    print(f"{RED}[phase{phase}]{NC} {msg}", file=sys.stderr)


def run(
    cmd: list[str] | str, check: bool = True, shell: bool = False, **kwargs
) -> subprocess.CompletedProcess:
    """Run a command, printing it first."""
    display = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(f"  $ {display}")
    return subprocess.run(cmd, check=check, shell=shell, **kwargs)


def brew_install(packages: list[str], cask: bool = False) -> tuple[int, int]:
    """Install brew packages, skipping already-installed ones. Returns (installed, skipped)."""
    if not packages:
        return 0, 0
    installed = 0
    skipped = 0
    flag = ["--cask"] if cask else []
    for pkg in packages:
        result = subprocess.run(
            ["brew", "list", *flag, pkg],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            skipped += 1
            continue
        try:
            run(["brew", "install", *flag, pkg], check=True)
            installed += 1
        except subprocess.CalledProcessError:
            err(0, f"  Failed to install: {pkg}")
    return installed, skipped


# ---------------------------------------------------------------------------
# Phase 2: Language Runtimes
# ---------------------------------------------------------------------------
def phase2_runtime(snapshot: dict, dry_run: bool) -> None:
    """Install language runtimes: Python (uv), Node.js, pnpm, bun, Go."""
    phase = 2
    log(phase, "Installing language runtimes...")

    # Core runtime packages via brew
    runtime_formulae = ["uv", "node", "node@22", "bun", "go"]
    if dry_run:
        log(phase, f"  [dry-run] Would install: {', '.join(runtime_formulae)}")
        return

    inst, skip = brew_install(runtime_formulae)
    log(phase, f"  Formulae: {inst} installed, {skip} already present")

    # pnpm via npm (if not already installed)
    if not shutil.which("pnpm"):
        log(phase, "  Installing pnpm via npm...")
        run(["npm", "install", "-g", "pnpm"], check=False)
    else:
        log(phase, "  pnpm: already installed")

    # uv-managed Python
    log(phase, "  Setting up Python 3.12 via uv...")
    run(["uv", "python", "install", "3.12"], check=False)

    log(phase, "Phase 2 complete.")


# ---------------------------------------------------------------------------
# Phase 3: Shell Environment + Tier 1 Config Restore
# ---------------------------------------------------------------------------
def phase3_shell(snapshot: dict, dry_run: bool) -> None:
    """Install shell tools and restore Tier 1 configs."""
    phase = 3

    shell_formulae = ["tmux", "zoxide", "bat", "fd", "fzf"]
    shell_casks = ["iterm2", "font-meslo-lg-nerd-font"]

    if dry_run:
        log(phase, f"  [dry-run] Formulae: {', '.join(shell_formulae)}")
        log(phase, f"  [dry-run] Casks: {', '.join(shell_casks)}")
        log(phase, "  [dry-run] Would restore Tier 1 configs")
        return

    log(phase, "Installing shell tools...")
    inst, skip = brew_install(shell_formulae)
    log(phase, f"  Formulae: {inst} installed, {skip} already present")
    inst, skip = brew_install(shell_casks, cask=True)
    log(phase, f"  Casks: {inst} installed, {skip} already present")

    # Oh My Zsh
    omz_dir = HOME / ".oh-my-zsh"
    if not omz_dir.exists():
        log(phase, "  Installing Oh My Zsh...")
        run(
            'sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"'
            ' "" --unattended',
            shell=True,
            check=False,
        )
    else:
        log(phase, "  Oh My Zsh: already installed")

    # Custom ZSH plugins
    custom_dir = omz_dir / "custom" / "plugins"
    zsh_plugins = {
        "zsh-autosuggestions": "https://github.com/zsh-users/zsh-autosuggestions",
        "zsh-syntax-highlighting": "https://github.com/zsh-users/zsh-syntax-highlighting",
        "zsh-completions": "https://github.com/zsh-users/zsh-completions",
    }
    for name, url in zsh_plugins.items():
        dest = custom_dir / name
        if not dest.exists():
            log(phase, f"  Cloning {name}...")
            run(["git", "clone", url, str(dest)], check=False)

    # tmux plugin manager
    tpm_dir = HOME / ".tmux" / "plugins" / "tpm"
    if not tpm_dir.exists():
        log(phase, "  Installing TPM...")
        tpm_dir.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "https://github.com/tmux-plugins/tpm", str(tpm_dir)], check=False)

    # Restore Tier 1 configs from envkit/configs/
    _restore_configs(phase)

    log(phase, "Phase 3 complete.")


def _restore_configs(phase: int) -> None:
    """Restore backed-up config files to their home locations."""
    config_map = [
        ("tmux.conf", HOME / ".tmux.conf"),
        ("zshrc", HOME / ".zshrc"),
        ("zshenv", HOME / ".zshenv"),
        ("gitconfig", HOME / ".gitconfig"),
        ("gitignore_global", HOME / ".gitignore_global"),
    ]

    for src_name, dst_path in config_map:
        src_path = CONFIGS_DIR / src_name
        if not src_path.exists():
            warn(phase, f"  Config backup not found: {src_name}")
            continue
        if dst_path.exists():
            # Backup existing before overwrite
            backup = dst_path.with_suffix(dst_path.suffix + ".envkit-bak")
            shutil.copy2(dst_path, backup)
            log(phase, f"  Backed up existing {dst_path.name} → {backup.name}")
        shutil.copy2(src_path, dst_path)
        log(phase, f"  Restored {src_name} → {dst_path}")

    # Restore oh-my-zsh custom dir
    omz_custom_src = CONFIGS_DIR / "oh-my-zsh-custom"
    omz_custom_dst = HOME / ".oh-my-zsh" / "custom"
    if omz_custom_src.exists() and omz_custom_dst.exists():
        # Copy files that exist in backup but not in destination
        for item in omz_custom_src.iterdir():
            target = omz_custom_dst / item.name
            if item.is_file() and not target.exists():
                shutil.copy2(item, target)
                log(phase, f"  Restored OMZ custom: {item.name}")


# ---------------------------------------------------------------------------
# Phase 4: Development Tools
# ---------------------------------------------------------------------------
def phase4_tools(snapshot: dict, dry_run: bool) -> None:
    """Install development tools: git extras, search tools, editors."""
    phase = 4

    dev_formulae = [
        "gh",
        "git-lfs",
        "git-delta",
        "difftastic",
        "git-cliff",
        "ripgrep",
        "ast-grep",
        "pandoc",
        "tesseract",
        "tesseract-lang",
        "sd",
        "tokei",
        "hyperfine",
        "gum",
        "glow",
        "yq",
        "mc",
    ]
    dev_casks = ["zed"]

    if dry_run:
        log(phase, f"  [dry-run] Formulae: {', '.join(dev_formulae)}")
        log(phase, f"  [dry-run] Casks: {', '.join(dev_casks)}")
        return

    log(phase, "Installing development tools...")
    inst, skip = brew_install(dev_formulae)
    log(phase, f"  Formulae: {inst} installed, {skip} already present")
    inst, skip = brew_install(dev_casks, cask=True)
    log(phase, f"  Casks: {inst} installed, {skip} already present")

    # git-lfs setup
    run(["git", "lfs", "install"], check=False)

    log(phase, "Phase 4 complete.")


# ---------------------------------------------------------------------------
# Phase 5: AI Toolchain
# ---------------------------------------------------------------------------
def phase5_ai(snapshot: dict, dry_run: bool) -> None:
    """Install AI tools: Claude Code, Codex, Gemini, Ollama, etc."""
    phase = 5

    ai_formulae = ["ollama", "gemini-cli", "claude-squad", "recall", "summarize", "remindctl"]
    ai_casks = ["codex", "cc-switch"]

    # uv tools from snapshot
    uv_tools = []
    py_data = snapshot.get("python", {})
    for tool in py_data.get("uv_tools", []):
        uv_tools.append(tool["name"])

    # npm global packages from snapshot
    npm_globals = []
    node_data = snapshot.get("node", {})
    for pkg in node_data.get("npm_global", []):
        name = pkg["name"]
        if name != "npm":  # skip npm itself
            npm_globals.append(name)

    if dry_run:
        log(phase, f"  [dry-run] Formulae: {', '.join(ai_formulae)}")
        log(phase, f"  [dry-run] Casks: {', '.join(ai_casks)}")
        log(phase, f"  [dry-run] uv tools: {', '.join(uv_tools)}")
        log(phase, f"  [dry-run] npm globals: {', '.join(npm_globals)}")
        return

    log(phase, "Installing AI tools...")
    inst, skip = brew_install(ai_formulae)
    log(phase, f"  Formulae: {inst} installed, {skip} already present")
    inst, skip = brew_install(ai_casks, cask=True)
    log(phase, f"  Casks: {inst} installed, {skip} already present")

    # Claude Code via npm
    log(phase, "  Installing Claude Code...")
    run(["npm", "install", "-g", "@anthropic-ai/claude-code"], check=False)

    # uv tools
    for tool in uv_tools:
        log(phase, f"  Installing uv tool: {tool}")
        run(["uv", "tool", "install", tool], check=False)

    # npm global packages
    for pkg in npm_globals:
        log(phase, f"  Installing npm global: {pkg}")
        run(["npm", "install", "-g", pkg], check=False)

    # Ollama models
    log(phase, "  Pulling Ollama models...")
    run(["ollama", "pull", "nomic-embed-text"], check=False)

    # Restore AI tool configs
    ai_config_dirs = ["codex", "gemini", "litellm"]
    for dirname in ai_config_dirs:
        src = CONFIGS_DIR / dirname
        if dirname == "codex":
            dst = HOME / ".codex"
        elif dirname == "gemini":
            dst = HOME / ".gemini"
        elif dirname == "litellm":
            dst = HOME / ".config" / "litellm"
        else:
            continue
        if src.exists() and src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = dst / item.name
                if item.is_file():
                    shutil.copy2(item, target)
                    log(phase, f"  Restored {dirname}/{item.name}")

    log(phase, "Phase 5 complete.")


# ---------------------------------------------------------------------------
# Phase 6: Network & Security
# ---------------------------------------------------------------------------
def phase6_network(snapshot: dict, dry_run: bool) -> None:
    """Install network and security tools."""
    phase = 6

    net_formulae = ["mosh", "cloudflared", "ttyd", "gnupg", "lynis"]
    net_casks = ["lulu", "knockknock"]

    if dry_run:
        log(phase, f"  [dry-run] Formulae: {', '.join(net_formulae)}")
        log(phase, f"  [dry-run] Casks: {', '.join(net_casks)}")
        return

    log(phase, "Installing network & security tools...")
    inst, skip = brew_install(net_formulae)
    log(phase, f"  Formulae: {inst} installed, {skip} already present")
    inst, skip = brew_install(net_casks, cask=True)
    log(phase, f"  Casks: {inst} installed, {skip} already present")

    warn(phase, "  Manual steps needed:")
    warn(phase, "    - Tailscale: install from Mac App Store, then login")
    warn(phase, "    - SSH keys: copy from secure backup")
    warn(phase, "    - LuLu: configure firewall rules")

    log(phase, "Phase 6 complete.")


# ---------------------------------------------------------------------------
# Phase 7: Containers & Services
# ---------------------------------------------------------------------------
def phase7_services(snapshot: dict, dry_run: bool) -> None:
    """Install OrbStack and bring up Docker services."""
    phase = 7

    if dry_run:
        log(phase, "  [dry-run] Would install OrbStack and start docker-compose")
        return

    log(phase, "Installing container runtime...")
    inst, _skip = brew_install(["orbstack"], cask=True)
    log(phase, f"  OrbStack: {'installed' if inst else 'already present'}")

    # docker-compose up
    compose_file = HOME / "workshop" / "infra" / "docker" / "docker-compose.yml"
    if compose_file.exists():
        log(phase, "  Starting workshop infrastructure (docker-compose)...")
        run(
            ["docker", "compose", "-f", str(compose_file), "-p", "ws-infra", "up", "-d"],
            check=False,
        )
    else:
        warn(phase, f"  docker-compose.yml not found at {compose_file}")

    log(phase, "Phase 7 complete.")


# ---------------------------------------------------------------------------
# Phase 8: GUI Applications
# ---------------------------------------------------------------------------
def phase8_apps(snapshot: dict, dry_run: bool) -> None:
    """Install GUI applications via brew cask and Mac App Store."""
    phase = 8

    # Additional casks not covered by earlier phases
    gui_casks = ["libreoffice"]

    # Mac App Store apps (from snapshot)
    mas_apps = []
    apps_data = snapshot.get("apps", {})
    for app in apps_data.get("mas_apps", []):
        app_id = app.get("id", "")
        name = app.get("name", "")
        # Skip apps that are built-in or installed via other means
        if name in ("Xcode", "Keynote", "Numbers", "Pages"):
            continue
        if app_id:
            mas_apps.append((app_id, name))

    if dry_run:
        log(phase, f"  [dry-run] Casks: {', '.join(gui_casks)}")
        log(phase, f"  [dry-run] MAS apps: {', '.join(name for _, name in mas_apps)}")
        return

    log(phase, "Installing GUI applications...")
    inst, skip = brew_install(gui_casks, cask=True)
    log(phase, f"  Casks: {inst} installed, {skip} already present")

    # Mac App Store (requires mas CLI)
    if shutil.which("mas"):
        for app_id, name in mas_apps:
            log(phase, f"  Installing MAS: {name} ({app_id})")
            run(["mas", "install", app_id], check=False)
    elif mas_apps:
        warn(phase, "  'mas' CLI not found — install manually:")
        for app_id, name in mas_apps:
            warn(phase, f"    {name}: mas install {app_id}")

    warn(phase, "  Manual installs needed:")
    warn(phase, "    - Chrome: download from google.com/chrome")
    warn(phase, "    - Logi Options+: download from logitech.com")
    warn(phase, "    - AltServer: download from altstore.io")

    log(phase, "Phase 8 complete.")


# ---------------------------------------------------------------------------
# Phase 9: Verification
# ---------------------------------------------------------------------------
def phase9_verify(snapshot: dict, dry_run: bool) -> None:
    """Verify the restored environment against the snapshot."""
    phase = 9

    if dry_run:
        log(phase, "  [dry-run] Would run envkit verify")
        return

    log(phase, "Running environment verification...")

    # Save current snapshot for comparison
    verify_snapshot = Path("/tmp/envkit-verify-current.yaml")
    run(
        [
            sys.executable,
            str(ENVKIT_DIR / "envkit.py"),
            "snapshot",
            "--output",
            str(verify_snapshot),
        ],
        check=False,
    )

    # Run diff against target
    snapshot_path = sys.argv[1] if len(sys.argv) > 1 else ""
    if snapshot_path and verify_snapshot.exists():
        result = run(
            [
                sys.executable,
                str(ENVKIT_DIR / "envkit.py"),
                "diff",
                snapshot_path,
                str(verify_snapshot),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout)
        if result.returncode == 0:
            log(phase, "Verification passed — environment matches snapshot.")
        else:
            warn(phase, "Verification found differences (see above).")
    else:
        warn(phase, "  Could not run diff (missing snapshot path)")

    log(phase, "")
    log(phase, "Bootstrap complete!")
    log(phase, "")
    warn(phase, "Remaining manual steps:")
    warn(phase, "  1. Clone ~/.claude/ from git (Claude Code config)")
    warn(phase, "  2. Clone ~/workshop/ from git")
    warn(phase, "  3. Login to Tailscale, Chrome, LINE, Telegram")
    warn(phase, "  4. Import iTerm2 profile (if backed up)")
    warn(phase, "  5. Install VS Code extensions (code --install-extension ...)")
    warn(phase, "  6. Copy SSH keys from secure backup")
    warn(phase, "  7. Run workshop-services.sh to start all services")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

PHASES = {
    2: ("Runtime", phase2_runtime),
    3: ("Shell & Tier 1 Config", phase3_shell),
    4: ("Dev Tools", phase4_tools),
    5: ("AI Toolchain", phase5_ai),
    6: ("Network & Security", phase6_network),
    7: ("Containers & Services", phase7_services),
    8: ("GUI Applications", phase8_apps),
    9: ("Verification", phase9_verify),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EnvKit Bootstrap — restore environment from snapshot",
    )
    parser.add_argument("snapshot", help="Path to envkit snapshot YAML")
    parser.add_argument(
        "--from", dest="from_phase", type=int, default=2, help="Start from phase N (default: 2)"
    )
    parser.add_argument(
        "--to", dest="to_phase", type=int, default=9, help="Stop at phase N (default: 9)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be done without doing it"
    )
    args = parser.parse_args()

    # Load snapshot
    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        err(0, f"Snapshot file not found: {snapshot_path}")
        sys.exit(1)

    log(0, f"Loading snapshot: {snapshot_path}")
    snapshot = from_yaml(snapshot_path.read_text())
    log(0, f"Snapshot from {snapshot.get('timestamp', 'unknown')}")
    log(
        0,
        f"System: {snapshot.get('system', {}).get('chip', 'unknown')}"
        f" / {snapshot.get('system', {}).get('os_version', 'unknown')}",
    )
    log(0, "")

    if args.dry_run:
        log(0, "=== DRY RUN MODE ===")
        log(0, "")

    # Run phases
    t0 = time.time()
    for phase_num in range(args.from_phase, args.to_phase + 1):
        if phase_num not in PHASES:
            warn(0, f"Unknown phase {phase_num}, skipping")
            continue

        name, func = PHASES[phase_num]
        log(0, f"{'=' * 60}")
        log(0, f"Phase {phase_num}/9: {name}")
        log(0, f"{'=' * 60}")

        try:
            func(snapshot, args.dry_run)
        except Exception as e:
            err(phase_num, f"Phase failed: {e}")
            warn(phase_num, "Continuing to next phase...")

        print()

    elapsed = time.time() - t0
    log(0, f"Bootstrap finished in {elapsed:.0f}s (phases {args.from_phase}-{args.to_phase})")


if __name__ == "__main__":
    main()
