"""Bark push notification helper."""

import logging
import subprocess
from urllib.parse import quote

from .config import settings

log = logging.getLogger("auto_survey")


def send_bark(title: str, body: str):
    """Send Bark push notification. Non-fatal on failure."""
    try:
        encoded_title = quote(title, safe="")
        encoded_body = quote(body, safe="")
        url = f"{settings.bark_server}/{settings.bark_device_key}/{encoded_title}/{encoded_body}"
        result = subprocess.run(["curl", "-sf", url], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            log.warning("[bark] curl failed (exit %d): %s", result.returncode, url[:100])
    except Exception as e:
        log.warning("[bark] send failed: %s", e)
