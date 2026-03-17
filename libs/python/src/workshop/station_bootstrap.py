"""Station Bootstrap — shared setup utilities for Workshop stations.

Provides three standardized helpers:
  - setup_logging   : uniform log format across all stations
  - setup_cors      : CORS middleware with restricted / open / none modes
  - load_yaml_config: YAML config loader with env var override

Usage::

    from workshop.station_bootstrap import setup_logging, setup_cors, load_yaml_config

    logger = setup_logging(__name__)
    setup_cors(app)
    config = load_yaml_config("config.yaml", defaults={"port": 8800})
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from starlette.middleware.cors import CORSMiddleware

__all__ = [
    "STANDARD_LOG_FORMAT",
    "STANDARD_DATE_FORMAT",
    "STANDARD_CORS_ORIGINS",
    "setup_logging",
    "setup_cors",
    "load_yaml_config",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

STANDARD_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
STANDARD_DATE_FORMAT = "%H:%M:%S"


def setup_logging(name: str, level: str = "INFO") -> logging.Logger:
    """Initialize standard Workshop station logging.

    Args:
        name:  Logger name, typically ``__name__`` of the calling module.
        level: Log level string (default ``"INFO"``).

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=STANDARD_LOG_FORMAT,
        datefmt=STANDARD_DATE_FORMAT,
    )
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

STANDARD_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "https://workshop.joneshong.com",
]


def setup_cors(
    app,
    mode: str = "restricted",
    extra_origins: list[str] | None = None,
) -> None:
    """Add CORS middleware to a FastAPI app.

    Modes:
        restricted — localhost:3000 + workshop.joneshong.com + *extra_origins*
        open       — allow all origins (``["*"]``)
        none       — skip CORS entirely

    Args:
        app:           FastAPI (or Starlette) application instance.
        mode:          One of ``"restricted"``, ``"open"``, ``"none"``.
        extra_origins: Additional origins to whitelist in ``restricted`` mode.
    """
    if mode == "none":
        return
    if mode == "open":
        origins: list[str] = ["*"]
    else:
        origins = list(STANDARD_CORS_ORIGINS)
        if extra_origins:
            origins.extend(extra_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# YAML config loader
# ---------------------------------------------------------------------------


def load_yaml_config(config_path: Path | str, defaults: dict | None = None) -> dict:
    """Load YAML config with env var override.

    Priority: env vars > YAML file > *defaults*.

    Env var naming convention:
        ``<env_prefix>_<KEY>`` where ``env_prefix`` is the ``env_prefix`` field
        inside the YAML file (or empty string if absent).

    Type coercion for env var values (in order):
        1. Digit string → ``int``
        2. ``"true"`` / ``"false"`` (case-insensitive) → ``bool``
        3. Otherwise → ``str``

    Args:
        config_path: Path to the YAML configuration file.
        defaults:    Fallback values used when the file is absent or a key
                     is missing.

    Returns:
        Merged configuration dictionary.
    """
    result: dict = dict(defaults or {})
    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            file_config = yaml.safe_load(f) or {}
        result.update(file_config)

    # Env var override: <ENV_PREFIX>_KEY overrides config[key]
    env_prefix = result.get("env_prefix", "").upper()
    if env_prefix and not env_prefix.endswith("_"):
        env_prefix += "_"
    for key in list(result.keys()):
        if key == "env_prefix":
            continue
        env_key = f"{env_prefix}{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if env_val.isdigit():
                result[key] = int(env_val)
            elif env_val.lower() in ("true", "false"):
                result[key] = env_val.lower() == "true"
            else:
                result[key] = env_val
    return result
