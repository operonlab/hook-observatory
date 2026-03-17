"""G-R-C Runner Template — eliminates boilerplate for scheduled G-R-C jobs.

Usage:
    # schedules/runners/ws_capture_grc.py
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.grc_runner import grc_runner_main

    if __name__ == "__main__":
        grc_runner_main(module="capture", stages=["reflect"])
"""

from __future__ import annotations

import fcntl
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()


def _log(module: str, msg: str, log_file: Path | None = None) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{module}-grc] {ts} {msg}"
    print(line, flush=True)
    if log_file:
        with open(log_file, "a") as f:
            f.write(line + "\n")


def _api_post(url: str) -> tuple[int | None, dict | None]:
    """POST to Core API. Returns (status_code, response_json)."""
    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            status = resp.status
            body = json.loads(resp.read())
            return status, body
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return None, {"error": str(e)}


def grc_runner_main(
    module: str,
    stages: list[str],
    space_id: str = "default",
    core_api: str = "http://localhost:8801",
    curate_dry_run: bool = False,
    extra_params: dict[str, str] | None = None,
) -> None:
    """Template runner for scheduled G-R-C jobs.

    Args:
        module: Module name (e.g. "capture", "memvault").
        stages: List of stages to run (e.g. ["reflect", "curate"]).
        space_id: Space ID for the API call.
        core_api: Core API base URL.
        curate_dry_run: If True, curate runs in dry_run mode.
        extra_params: Additional query parameters.
    """
    log_dir = HOME / f"workshop/outputs/{module}/logs"
    log_file = log_dir / "grc.log"
    lock_path = f"/tmp/ws_{module}_grc.lock"  # noqa: S108

    # Single-instance lock
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another {module} GRC instance running")
        sys.exit(0)

    log_dir.mkdir(parents=True, exist_ok=True)
    log = lambda msg: _log(module, msg, log_file)  # noqa: E731

    log(f"========== {module} G-R-C started (stages={stages}) ==========")

    for stage in stages:
        params = {"space_id": space_id}
        if stage == "curate" and curate_dry_run:
            params["dry_run"] = "true"
        if extra_params:
            params.update(extra_params)

        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{core_api}/api/{module}/{stage}?{query}"

        log(f"POST {url}")
        status, body = _api_post(url)

        if status and 200 <= status < 300:
            log(f"  {stage} OK: {json.dumps(body, ensure_ascii=False)[:200]}")
        else:
            log(f"  {stage} FAILED: status={status}")

    log(f"========== {module} G-R-C complete ==========")
