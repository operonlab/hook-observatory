"""Bark push notification helper."""

import json as _json
import logging
import subprocess
from urllib.parse import quote

from .config import settings

log = logging.getLogger("auto_survey")


def send_bark(title: str, body: str) -> bool:
    """Send Bark push notification. Returns True on success."""
    try:
        encoded_title = quote(title, safe="")
        encoded_body = quote(body, safe="")
        url = f"{settings.bark_server}/{settings.bark_device_key}/{encoded_title}/{encoded_body}"
        result = subprocess.run(["curl", "-sf", url], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            log.warning("[bark] curl failed (exit %d)", result.returncode)
            print(f"[bark] FAILED: curl exit {result.returncode}", flush=True)
            return False
        resp = _json.loads(result.stdout)
        if resp.get("code") != 200:
            log.warning("[bark] server error: %s", result.stdout[:200])
            print(f"[bark] FAILED: server code {resp.get('code')}", flush=True)
            return False
        return True
    except Exception as e:
        log.warning("[bark] send failed: %s", e)
        print(f"[bark] FAILED: {e}", flush=True)
        return False
