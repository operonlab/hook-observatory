"""
EnvKit Collectors — registry of environment scanners.

Each collector module exports a `collect() -> dict` function.
"""

from __future__ import annotations

import sys
import traceback
from typing import Callable

# Collector registry: name -> (module_name, display_name)
COLLECTORS: dict[str, tuple[str, str]] = {
    "system": ("collectors.system", "System Info"),
    "homebrew_formulae": ("collectors.homebrew", "Homebrew Formulae"),
    "homebrew_casks": ("collectors.homebrew", "Homebrew Casks"),
    "python": ("collectors.python_env", "Python Environment"),
    "node": ("collectors.node_env", "Node.js Environment"),
    "shell": ("collectors.shell", "Shell Configuration"),
    "docker": ("collectors.docker", "Docker / OrbStack"),
    "apps": ("collectors.apps", "Applications"),
    "cli_tools": ("collectors.cli_tools", "CLI Tools"),
}

# Map user-facing category aliases to collector keys
CATEGORY_ALIASES: dict[str, list[str]] = {
    "all": list(COLLECTORS.keys()),
    "brew": ["homebrew_formulae"],
    "cask": ["homebrew_casks"],
    "python": ["python"],
    "node": ["node"],
    "shell": ["shell"],
    "docker": ["docker"],
    "apps": ["apps"],
    "cli": ["cli_tools"],
}


def run_all_collectors() -> dict[str, dict]:
    """Run all collectors with graceful degradation."""
    from collectors import system, homebrew, python_env, node_env, shell, docker, apps, cli_tools

    results: dict[str, dict] = {}

    collector_funcs: list[tuple[str, Callable]] = [
        ("system", system.collect),
        ("homebrew_formulae", homebrew.collect_formulae),
        ("homebrew_casks", homebrew.collect_casks),
        ("python", python_env.collect),
        ("node", node_env.collect),
        ("shell", shell.collect),
        ("docker", docker.collect),
        ("apps", apps.collect),
        ("cli_tools", cli_tools.collect),
    ]

    for name, func in collector_funcs:
        try:
            results[name] = func()
        except Exception:
            print(f"Warning: collector '{name}' failed:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            results[name] = {"error": "collector failed"}

    return results


def run_collectors(categories: list[str]) -> dict[str, dict]:
    """Run specific collectors by category name."""
    from collectors import system, homebrew, python_env, node_env, shell, docker, apps, cli_tools

    func_map: dict[str, Callable] = {
        "system": system.collect,
        "homebrew_formulae": homebrew.collect_formulae,
        "homebrew_casks": homebrew.collect_casks,
        "python": python_env.collect,
        "node": node_env.collect,
        "shell": shell.collect,
        "docker": docker.collect,
        "apps": apps.collect,
        "cli_tools": cli_tools.collect,
    }

    results: dict[str, dict] = {}
    for cat in categories:
        func = func_map.get(cat)
        if not func:
            print(f"Warning: unknown category '{cat}'", file=sys.stderr)
            continue
        try:
            results[cat] = func()
        except Exception:
            print(f"Warning: collector '{cat}' failed:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            results[cat] = {"error": "collector failed"}

    return results
