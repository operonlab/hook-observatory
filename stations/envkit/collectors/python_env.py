"""Python environment collector — uv, pip, Python versions."""

from __future__ import annotations

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

    # Python version
    python_bin = shutil.which("python3") or ""
    if python_bin:
        result["python_path"] = python_bin
        result["python_version"] = _run([python_bin, "--version"]).replace("Python ", "")

    # uv tools
    uv_bin = shutil.which("uv")
    if uv_bin:
        result["uv_version"] = _run([uv_bin, "--version"]).replace("uv ", "")
        tools_out = _run([uv_bin, "tool", "list"])
        tools = []
        for line in tools_out.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or line.startswith(" "):
                continue
            parts = line.split()
            name = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            # Clean version string (remove 'v' prefix if present)
            version = version.strip("v()")
            tools.append({"name": name, "version": version})
        result["uv_tools"] = tools
        result["uv_tools_count"] = len(tools)
    else:
        result["uv_available"] = False

    # pip packages (global, from uv-managed python)
    pip_out = _run(["pip3", "list", "--format=json"])
    if pip_out:
        import json
        try:
            pkgs = json.loads(pip_out)
            result["pip_packages"] = [{"name": p["name"], "version": p["version"]} for p in pkgs]
            result["pip_packages_count"] = len(pkgs)
        except (json.JSONDecodeError, KeyError):
            result["pip_packages"] = []

    return result
