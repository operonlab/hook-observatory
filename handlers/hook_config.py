"""
Centralized configuration for hook handlers.

Load order: config.example.yaml (defaults) → config.yaml (user overrides).
All handlers access config via: `from .hook_config import cfg`

Config is loaded ONCE at import time and cached as a module-level dict.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate config files relative to package root
# ---------------------------------------------------------------------------

_HANDLER_DIR = Path(__file__).resolve().parent  # handlers/
_OBSERVATORY_ROOT = _HANDLER_DIR.parent  # hook-observatory/
_DEFAULT_CONFIG = _OBSERVATORY_ROOT / "config.example.yaml"  # committed defaults
_USER_CONFIG = _OBSERVATORY_ROOT / "config.yaml"  # user overrides (gitignored)

# ---------------------------------------------------------------------------
# Minimal YAML loader (stdlib-only fallback when PyYAML unavailable)
# Handles flat scalars, simple nested dicts, and basic lists.
# For complex configs (anchors, multiline), install PyYAML.
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Load YAML file. Tries PyYAML first, falls back to simple parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        return yaml.safe_load(text) or {}
    except ImportError:
        return _simple_yaml_parse(text)


def _simple_yaml_parse(text: str) -> dict:
    """Parse a subset of YAML: flat/nested dicts, scalars, no anchors."""
    result: dict = {}
    stack: list[tuple[int, dict]] = [(-1, result)]

    for raw_line in text.splitlines():
        # Skip comments and blank lines
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Measure indent
        indent = len(raw_line) - len(raw_line.lstrip())

        # Pop stack to current indent level
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        if ":" not in stripped:
            continue

        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        # Remove inline comments
        for q in ('"', "'"):
            if val.startswith(q) and val.endswith(q) and len(val) > 1:
                val = val[1:-1]
                break
        else:
            if "#" in val:
                val = val[: val.index("#")].strip()

        if not val:
            # Nested dict
            child: dict = {}
            stack[-1][1][key] = child
            stack.append((indent, child))
        else:
            stack[-1][1][key] = _coerce(val)

    return result


def _coerce(val: str) -> str | int | float | bool | None:
    """Convert YAML scalar string to Python type."""
    if val in ("true", "True", "yes"):
        return True
    if val in ("false", "False", "no"):
        return False
    if val in ("null", "None", "~", ""):
        return None
    # Remove surrounding quotes
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


# ---------------------------------------------------------------------------
# Deep merge: local overrides defaults
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins for scalars."""
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


# ---------------------------------------------------------------------------
# Load & cache
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    """Load default config, overlay local config, expand paths."""
    config: dict = {}

    if _DEFAULT_CONFIG.is_file():
        config = _load_yaml(_DEFAULT_CONFIG)

    if _USER_CONFIG.is_file():
        local = _load_yaml(_USER_CONFIG)
        config = _deep_merge(config, local)

    # Expand ~ in path values
    paths = config.get("paths", {})
    for k, v in paths.items():
        if isinstance(v, str) and v != "auto":
            paths[k] = os.path.expanduser(v)

    # Auto-detect observatory root
    if paths.get("observatory_root") == "auto" or not paths.get("observatory_root"):
        paths["observatory_root"] = str(_OBSERVATORY_ROOT)

    config["paths"] = paths
    return config


# Module-level config singleton
cfg: dict = _load_config()


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def is_handler_enabled(handler_name: str) -> bool:
    """Check if a handler is enabled in config. Defaults to True if not listed."""
    handlers = cfg.get("handlers", {})
    for category in handlers.values():
        if isinstance(category, dict) and handler_name in category:
            return bool(category[handler_name])
    return True  # not listed = enabled (backward compat)


def get_tool(name: str) -> str | None:
    """Resolve tool path. 'auto' → shutil.which(), explicit → return as-is."""
    tools = cfg.get("tools", {})
    val = tools.get(name, "auto")
    if val == "auto":
        return shutil.which(name)
    expanded = os.path.expanduser(str(val))
    return expanded if os.path.isfile(expanded) else None


def get_service(name: str) -> str:
    """Get service URL by name."""
    return str(cfg.get("services", {}).get(name, ""))


def get_path(name: str) -> str:
    """Get a named path from config, expanded."""
    raw = cfg.get("paths", {}).get(name, "")
    return os.path.expanduser(str(raw)) if raw else ""


def get_timeout(event_type: str) -> int:
    """Get hook timeout for an event type (seconds)."""
    return int(cfg.get("dispatcher", {}).get("hook_timeouts", {}).get(event_type, 20))


def get_budget_ms() -> int:
    """Get deferrable handler blocking budget in milliseconds."""
    return int(cfg.get("dispatcher", {}).get("blocking_budget_ms", 5000))
