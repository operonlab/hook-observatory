"""Node.js environment collector — node, npm, pnpm, bun, global packages."""

from __future__ import annotations

import json
import shutil
import subprocess


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def collect() -> dict:
    result: dict = {}

    # Node.js
    node_bin = shutil.which("node")
    if node_bin:
        result["node_version"] = _run([node_bin, "--version"]).lstrip("v")
        result["node_path"] = node_bin
    else:
        result["node_available"] = False

    # npm
    npm_bin = shutil.which("npm")
    if npm_bin:
        result["npm_version"] = _run([npm_bin, "--version"])
        # Global packages
        npm_out = _run([npm_bin, "list", "-g", "--json", "--depth=0"])
        if npm_out:
            try:
                data = json.loads(npm_out)
                deps = data.get("dependencies", {})
                result["npm_global"] = [
                    {"name": name, "version": info.get("version", "")}
                    for name, info in deps.items()
                ]
                result["npm_global_count"] = len(result["npm_global"])
            except (json.JSONDecodeError, AttributeError):
                result["npm_global"] = []

    # pnpm
    pnpm_bin = shutil.which("pnpm")
    if pnpm_bin:
        result["pnpm_version"] = _run([pnpm_bin, "--version"])

    # bun
    bun_bin = shutil.which("bun")
    if bun_bin:
        result["bun_version"] = _run([bun_bin, "--version"])

    return result
