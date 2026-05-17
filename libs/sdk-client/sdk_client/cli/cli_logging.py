"""CLI unified logging helper — CLI failure traceback + cross-service request_id origin."""
import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sdk_client.logging_context import JsonFormatterWithContext, set_request_id

LOG_BASE = Path("/opt/homebrew/var/log/workshop")


def init_cli_logging(name: str, *, json: bool = True, level: str = "INFO") -> logging.Logger:
    """Initialize logging for a CLI entry point.

    - Sets a 12-hex request_id (opens a trace for this CLI invocation)
    - Writes JSON to /opt/homebrew/var/log/workshop/{name}/cli.log
    - Also streams short text format to stderr for human reading
    - Installs sys.excepthook to capture uncaught exceptions
    """
    log_dir = LOG_BASE / name
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.handlers.clear()

    fh = RotatingFileHandler(log_dir / "cli.log", maxBytes=10 * 1024 * 1024, backupCount=5)
    if json:
        fh.setFormatter(JsonFormatterWithContext(service=name))
    else:
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s"))
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s"))
    sh.setLevel(level)
    root.addHandler(sh)
    root.setLevel(level)

    # New request_id for this CLI invocation (or honor WORKSHOP_REQUEST_ID env if set)
    rid = os.environ.get("WORKSHOP_REQUEST_ID", "").strip() or uuid.uuid4().hex[:12]
    set_request_id(rid)

    # Catch uncaught exceptions
    def _excepthook(exc_type, exc, tb):
        logging.getLogger("cli.uncaught").exception(
            "uncaught_exception",
            exc_info=(exc_type, exc, tb),
            extra={"error_type": exc_type.__name__},
        )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    return logging.getLogger(name)
