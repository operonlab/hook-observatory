"""ModeArbiter — decides which voice path (client/server) is active."""

from __future__ import annotations

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class VoiceMode(str, Enum):
    SERVER = "server"
    CLIENT = "client"
    STANDBY = "standby"


class ModeArbiter:
    """Ensures only one voice path is active at a time.

    Rules:
    1. Client connected → switch to CLIENT, pause server mic
    2. Client disconnected → fallback to SERVER
    3. Manual override takes precedence
    """

    def __init__(self, server_enabled: bool = True) -> None:
        self._server_enabled = server_enabled
        self._client_connected = False
        self._client_last_heartbeat = 0.0
        self._manual_override: VoiceMode | None = None
        self._heartbeat_timeout = 60.0

    @property
    def active_mode(self) -> VoiceMode:
        if self._manual_override:
            return self._manual_override

        # Check heartbeat staleness
        if self._client_connected and self._client_last_heartbeat > 0:
            if (time.monotonic() - self._client_last_heartbeat) > self._heartbeat_timeout:
                self._client_connected = False
                logger.info("client_heartbeat_timeout")

        if self._client_connected:
            return VoiceMode.CLIENT
        if self._server_enabled:
            return VoiceMode.SERVER
        return VoiceMode.STANDBY

    @property
    def server_should_capture(self) -> bool:
        return self.active_mode == VoiceMode.SERVER

    def client_connect(self) -> VoiceMode:
        self._client_connected = True
        self._client_last_heartbeat = time.monotonic()
        mode = self.active_mode
        logger.info("client_connected: mode=%s", mode.value)
        return mode

    def client_disconnect(self, reason: str = "explicit") -> VoiceMode:
        self._client_connected = False
        mode = self.active_mode
        logger.info("client_disconnected: reason=%s mode=%s", reason, mode.value)
        return mode

    def client_heartbeat(self) -> None:
        self._client_last_heartbeat = time.monotonic()

    def set_override(self, mode: VoiceMode | None) -> VoiceMode:
        self._manual_override = mode
        result = self.active_mode
        logger.info("manual_override: %s → active=%s", mode, result.value)
        return result

    def status(self) -> dict:
        return {
            "active_mode": self.active_mode.value,
            "client_connected": self._client_connected,
            "server_enabled": self._server_enabled,
            "manual_override": self._manual_override.value if self._manual_override else None,
        }
