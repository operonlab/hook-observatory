"""Configuration management for tmux-webui V2."""

import logging
from pathlib import Path

from sdk_client.station_bootstrap import load_yaml_config

logger = logging.getLogger("tmux-webui")

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

_DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 9527,
    "poll_interval": 0.4,
    "metrics_interval": 5.0,
    "capture_lines": 150,
    "theme": "catppuccin-mocha",
    "extra_keys": [
        "Ctrl",
        "Alt",
        "Cmd",
        "|",
        "Tab",
        "Esc",
        "|",
        "/",
        ".",
        ":",
        ";",
        "|",
        "-",
        "_",
        "~",
        "|",
        "BSpace",
    ],
    "quick_actions": [
        {"label": "y", "key": "y"},
        {"label": "n", "key": "n"},
        {"label": "Ctrl+C", "key": "C-c"},
        {"label": "Enter", "key": "Enter"},
        {"label": "Esc", "key": "Escape"},
    ],
}

_config: dict = {}


def load_config(config_path: Path | None = None) -> dict:
    """Load config from YAML file, falling back to defaults."""
    global _config
    path = config_path or _CONFIG_PATH
    _config = load_yaml_config(path, defaults=_DEFAULT_CONFIG)
    return _config


def get_config() -> dict:
    """Return current config (call load_config first)."""
    if not _config:
        return load_config()
    return _config
