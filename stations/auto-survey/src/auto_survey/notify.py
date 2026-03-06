"""Bark push notification helper."""

import subprocess

from .config import settings


def send_bark(title: str, body: str):
    """Send Bark push notification. Non-fatal on failure."""
    try:
        url = f"{settings.bark_server}/{settings.bark_device_key}/{title}/{body}"
        subprocess.run(["curl", "-sf", url], capture_output=True, timeout=10)
    except Exception:
        pass
