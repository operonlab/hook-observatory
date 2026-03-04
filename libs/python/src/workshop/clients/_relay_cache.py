"""Redis-backed state cache for tmux-relay."""

from __future__ import annotations

import json
import os
import time

import redis

REDIS_URL = os.getenv("WORKSHOP_REDIS_URL", "redis://localhost:6379/0")
PANES_KEY = "relay:panes"
RESULT_PREFIX = "relay:result:"
CACHE_TS_KEY = "relay:cache_ts"
RESULT_TTL = 3600  # 1 hour
CACHE_TS_TTL = 60  # 60s freshness window


class RelayCacheManager:
    """Manages relay pane states and results in Redis."""

    def __init__(self, redis_url: str = REDIS_URL):
        self._r = redis.from_url(redis_url, decode_responses=True)

    # --- Pane operations ---

    def get_all_panes(self) -> dict[str, dict]:
        """HGETALL relay:panes -> {pane_safe: {ref, status, ...}}"""
        raw = self._r.hgetall(PANES_KEY)
        result = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    def get_pane(self, pane_safe: str) -> dict | None:
        """HGET relay:panes <pane_safe>"""
        raw = self._r.hget(PANES_KEY, pane_safe)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def set_pane(
        self,
        pane_safe: str,
        ref: str,
        status: str,
        pane_id: str = "",
        signal_file: str = "",
    ) -> None:
        """HSET relay:panes <pane_safe> + update cache_ts"""
        data = {
            "ref": ref,
            "status": status,
            "pane_id": pane_id or f"%{pane_safe}",
            "updated_at": time.time(),
        }
        if signal_file:
            data["signal_file"] = signal_file
        self._r.hset(PANES_KEY, pane_safe, json.dumps(data))
        self.touch()

    def remove_pane(self, pane_safe: str) -> None:
        """HDEL relay:panes <pane_safe>"""
        self._r.hdel(PANES_KEY, pane_safe)
        self.touch()

    # --- Result operations ---

    def set_result(
        self,
        signal_file: str,
        status: str,
        elapsed: str = "",
        result_file: str = "",
        pane: str = "",
    ) -> None:
        """SET relay:result:<basename> with TTL"""
        basename = os.path.basename(signal_file)
        data = {
            "status": status,
            "completed_at": time.time(),
            "pane": pane,
        }
        if elapsed:
            data["elapsed"] = elapsed
        if result_file:
            data["result_file"] = result_file
        self._r.set(f"{RESULT_PREFIX}{basename}", json.dumps(data), ex=RESULT_TTL)
        self.touch()

    def get_result(self, signal_file: str) -> dict | None:
        """GET relay:result:<basename>"""
        basename = os.path.basename(signal_file)
        raw = self._r.get(f"{RESULT_PREFIX}{basename}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    # --- Freshness ---

    def is_fresh(self) -> bool:
        """EXISTS relay:cache_ts"""
        return self._r.exists(CACHE_TS_KEY) > 0

    def touch(self) -> None:
        """SET relay:cache_ts with TTL"""
        self._r.set(CACHE_TS_KEY, str(time.time()), ex=CACHE_TS_TTL)

    # --- Bulk ---

    def clear_panes(self) -> None:
        """DEL relay:panes only."""
        self._r.delete(PANES_KEY)

    def clear(self) -> None:
        """DEL relay:panes + all relay:result:* keys"""
        self._r.delete(PANES_KEY)
        # Scan and delete result keys
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor, match=f"{RESULT_PREFIX}*", count=100)
            if keys:
                self._r.delete(*keys)
            if cursor == 0:
                break
        self._r.delete(CACHE_TS_KEY)

    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return self._r.ping()
        except redis.ConnectionError:
            return False

    def stats(self) -> dict:
        """Return cache statistics."""
        pane_count = self._r.hlen(PANES_KEY)
        # Count result keys
        result_count = 0
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor, match=f"{RESULT_PREFIX}*", count=100)
            result_count += len(keys)
            if cursor == 0:
                break
        return {
            "panes": pane_count,
            "results": result_count,
            "fresh": self.is_fresh(),
        }
