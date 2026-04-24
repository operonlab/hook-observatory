#!/usr/bin/env python3
"""Quota collector sidecar — runs `get_quota()` in a loop, writes Redis.

Replaces the in-process sysmon_loop quota merge after Phase 6 cutover to
agent-metrics-rs. The Rust binary reads the formatted snapshot from Redis
under `agent-metrics:quota:formatted` (Phase 3 quota.rs shim), so this
process owns the actual OAuth + Playwright fetching that Phase 5b deferred.

Lifecycle: managed by workshop_services.py as a separate service entry,
restarted by the launcher daemon if it dies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

# Make the agent_metrics package importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/src")

from agent_metrics.quota_collector import get_quota  # noqa: E402
from agent_metrics.reset_drift_monitor import check_all_windows  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [quota-sidecar] %(message)s",
)
log = logging.getLogger("quota-sidecar")

_INTERVAL_S = float(os.environ.get("AGENT_METRICS_QUOTA_INTERVAL_S", "60"))
_HEALTH_PORT = int(os.environ.get("AGENT_METRICS_QUOTA_PORT", "10198"))
_running = True
_last_success_ts: float = 0.0


def _stop(_sig, _frame):
    global _running
    _running = False
    log.info("shutdown signal received")


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            payload = {
                "status": "ok",
                "service": "agent-metrics-quota",
                "last_success_age_s": (time.time() - _last_success_ts)
                if _last_success_ts
                else None,
            }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_args):  # silence default access logging
        return


def _start_health_server():
    server = ThreadingHTTPServer(("127.0.0.1", _HEALTH_PORT), _HealthHandler)
    log.info("health endpoint on http://127.0.0.1:%s/health", _HEALTH_PORT)
    Thread(target=server.serve_forever, daemon=True).start()


async def main():
    global _last_success_ts
    log.info("quota sidecar starting (interval=%ss)", _INTERVAL_S)
    _start_health_server()
    while _running:
        try:
            result = await get_quota()
            _last_success_ts = time.time()
            log.info(
                "quota_refreshed display=%s cc=%s/%s",
                result.get("llm_display", "?"),
                result.get("llm_cc_5h", "?"),
                result.get("llm_cc_7d", "?"),
            )
            try:
                drift_reports = check_all_windows(result)
                notified = [r for r in drift_reports if r.get("notified")]
                if notified:
                    log.warning("drift_notified count=%d reports=%s", len(notified), notified)
            except Exception as e:
                log.debug("drift_check_failed: %s", e)
        except Exception as e:
            log.warning("quota_fetch_failed: %s", e)
        slept = 0.0
        while _running and slept < _INTERVAL_S:
            await asyncio.sleep(1.0)
            slept += 1.0
    log.info("quota sidecar stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    asyncio.run(main())
