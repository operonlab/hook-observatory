"""Configuration management for tmux-webui V2."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("tmux-webui")

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 9527,
    "poll_interval": 0.4,
    "metrics_interval": 5.0,
    "capture_lines": 150,
    "theme": "catppuccin-mocha",
    "extra_keys": [
        "Ctrl", "Alt", "Cmd", "|",
        "Tab", "Esc", "|",
        "/", ".", ":", ";", "|", "-", "_", "~", "|",
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
    """Load config from JSON file, falling back to defaults."""
    global _config
    _config = dict(DEFAULT_CONFIG)

    if config_path is None:
        config_path = Path(__file__).parent / "config.json"

    if config_path.exists():
        try:
            with open(config_path) as f:
                user_cfg = json.load(f)
            _config.update(user_cfg)
            logger.info("Loaded config from %s", config_path)
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", config_path, e)
    else:
        logger.info("No config file found, using defaults")

    return _config


def get_config() -> dict:
    """Return current config (call load_config first)."""
    if not _config:
        return load_config()
    return _config
