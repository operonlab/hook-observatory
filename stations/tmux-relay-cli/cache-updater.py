#!/Users/joneshong/.local/bin/python3
"""tmux hook target — update relay pane state in Redis.

Called by tmux set-hook run-shell:
    cache-updater.py pane-exited [pane_id]
    cache-updater.py activity <pane_id>
    cache-updater.py idle <pane_id>
"""

import json
import os
import sys
import time

import redis

REDIS_URL = os.getenv("WORKSHOP_REDIS_URL", "redis://localhost:6379/0")
PANES_KEY = "relay:panes"
CACHE_TS_KEY = "relay:cache_ts"
CACHE_TS_TTL = 60


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    event = sys.argv[1]
    pane_id = sys.argv[2] if len(sys.argv) > 2 else ""
    pane_safe = pane_id.replace("%", "")

    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        sys.exit(0)

    try:
        if event == "pane-exited":
            # Remove all panes that no longer exist — if pane_id given, remove that one
            if pane_safe:
                r.hdel(PANES_KEY, pane_safe)
            r.set(CACHE_TS_KEY, str(time.time()), ex=CACHE_TS_TTL)

        elif event == "activity" and pane_safe:
            raw = r.hget(PANES_KEY, pane_safe)
            if raw:
                data = json.loads(raw)
                # Only update if currently idle (don't override busy:relay)
                if data.get("status") == "idle":
                    data["status"] = "busy:active"
                    data["updated_at"] = time.time()
                    r.hset(PANES_KEY, pane_safe, json.dumps(data))
                    r.set(CACHE_TS_KEY, str(time.time()), ex=CACHE_TS_TTL)

        elif event == "idle" and pane_safe:
            raw = r.hget(PANES_KEY, pane_safe)
            if raw:
                data = json.loads(raw)
                data["status"] = "idle"
                data["updated_at"] = time.time()
                r.hset(PANES_KEY, pane_safe, json.dumps(data))
                r.set(CACHE_TS_KEY, str(time.time()), ex=CACHE_TS_TTL)

    except Exception:
        pass  # Cache is advisory — never block tmux


if __name__ == "__main__":
    main()
