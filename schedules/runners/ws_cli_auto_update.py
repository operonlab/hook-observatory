#!/usr/bin/env python3
"""
ws_cli_auto_update.py — Update selected AI CLIs via Homebrew and Hermes.

Pipeline:
  1. brew update
  2. brew upgrade targeted formulae
  3. brew upgrade targeted casks (greedy for auto_updates casks)
  4. hermes update
  5. write a JSON summary for the last run

Logs: ~/workshop/outputs/scheduler/logs/ws-cli-auto-update.log
Summary: ~/workshop/outputs/cli-auto-update/last-run.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
OUTPUT_DIR = HOME / "workshop/outputs/cli-auto-update"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-cli-auto-update.log"
STATE_FILE = OUTPUT_DIR / "last-run.json"

BREW_FORMULAE = {
    "gemini-cli": "gemini-cli",
    "qwen-cli": "qwen-code",
    "opencode": "opencode",
}

BREW_CASKS = {
    "codex-cli": "codex",
    "copilot-cli": "copilot-cli",
}


def configure_path() -> None:
    os.environ["PATH"] = (
        f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    )


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[cli-update] {timestamp} {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run(
    cmd: list[str],
    *,
    step: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    log(f"START {step}: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(result.stdout)
            if not result.stdout.endswith("\n"):
                handle.write("\n")
    if result.stderr:
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(result.stderr)
            if not result.stderr.endswith("\n"):
                handle.write("\n")

    level = "OK" if result.returncode == 0 else "FAIL"
    log(f"{level} {step}: exit={result.returncode}")

    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def brew_installed_version(name: str, *, cask: bool = False) -> str:
    cmd = ["/opt/homebrew/bin/brew", "list", "--versions"]
    if cask:
        cmd.append("--cask")
    cmd.append(name)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return "not-installed"
    line = result.stdout.strip()
    parts = line.split()
    return parts[-1] if len(parts) >= 2 else "unknown"


def hermes_installed_version() -> str:
    hermes = shutil.which("hermes")
    if not hermes:
        return "not-installed"
    result = subprocess.run([hermes, "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        return "unknown"
    first_line = (result.stdout or result.stderr).splitlines()
    if not first_line:
        return "unknown"
    match = re.search(r"v?([0-9]+(?:\.[0-9]+){1,3})", first_line[0])
    return match.group(1) if match else first_line[0].strip()


def collect_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for label, package in BREW_FORMULAE.items():
        versions[label] = brew_installed_version(package)
    for label, package in BREW_CASKS.items():
        versions[label] = brew_installed_version(package, cask=True)
    versions["hermes-agent"] = hermes_installed_version()
    return versions


def write_state(payload: dict) -> None:
    STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update selected AI CLIs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only collect current versions without performing updates",
    )
    args = parser.parse_args()

    configure_path()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now().isoformat()
    before = collect_versions()
    steps: list[dict[str, str | int]] = []
    failures: list[dict[str, str | int]] = []

    log("========== CLI auto update started ==========")
    log(f"Versions before: {json.dumps(before, ensure_ascii=False)}")

    if not args.dry_run:
        commands = [
            ("brew-update", ["/opt/homebrew/bin/brew", "update"], None),
            (
                "brew-upgrade-formulae",
                ["/opt/homebrew/bin/brew", "upgrade", *BREW_FORMULAE.values()],
                None,
            ),
            (
                "brew-upgrade-casks",
                ["/opt/homebrew/bin/brew", "upgrade", "--cask", "--greedy", *BREW_CASKS.values()],
                None,
            ),
        ]

        hermes = shutil.which("hermes")
        if hermes:
            commands.append(("hermes-update", [hermes, "update"], HOME / ".hermes/hermes-agent"))

        for step_name, cmd, cwd in commands:
            try:
                result = run(cmd, step=step_name, cwd=cwd, check=True)
                steps.append({"name": step_name, "exit_code": result.returncode, "status": "ok"})
            except subprocess.CalledProcessError as exc:
                failures.append(
                    {
                        "name": step_name,
                        "exit_code": exc.returncode,
                        "stderr": (exc.stderr or "").strip()[-500:],
                    }
                )
                steps.append({"name": step_name, "exit_code": exc.returncode, "status": "failed"})

    after = collect_versions()
    changed = {
        name: {"before": before.get(name, "unknown"), "after": version}
        for name, version in after.items()
        if before.get(name) != version
    }

    status = "ok" if not failures else "failed"
    payload = {
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
        "status": status,
        "dry_run": args.dry_run,
        "steps": steps,
        "failures": failures,
        "versions_before": before,
        "versions_after": after,
        "changed": changed,
    }
    write_state(payload)

    if changed:
        log(f"Updated versions: {json.dumps(changed, ensure_ascii=False)}")
    else:
        log("No CLI version changes detected")

    if failures:
        log(f"Failures detected: {json.dumps(failures, ensure_ascii=False)}")
    log("========== CLI auto update complete ==========")
    return 0 if not failures else 1


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)

    sys.exit(main())
