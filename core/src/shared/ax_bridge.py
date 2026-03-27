"""macOS Accessibility API bridge — subprocess JSON protocol.

Uses pyobjc via subprocess to avoid polluting the main venv.
Ghost OS pattern: structured perception > pixel guessing.

Architecture:
    ax_bridge.get_app_tree("Safari")  ──stdin──►  _ax_worker.py (pyobjc)
                                      ◄──stdout──  {JSON AX Tree}
"""

import sys

if not sys.platform.startswith("darwin"):
    # Non-macOS: stub all public functions so imports succeed on Linux/WSL2

    async def get_app_tree(app_name: str = "", **kwargs) -> dict:  # type: ignore[misc]
        return {"error": "AX bridge not available on non-macOS"}

    async def find_element(app_name: str = "", **kwargs) -> list:  # type: ignore[misc]
        return []

    async def get_focused_element(app_name: str | None = None, **kwargs) -> dict:  # type: ignore[misc]
        return {"error": "AX bridge not available on non-macOS"}

    async def perform_action(
        app_name: str = "", element_path: str = "", action: str = "AXPress", **kwargs
    ) -> bool:  # type: ignore[misc]
        return False

    def list_running_apps() -> list:  # type: ignore[misc]
        return []

    async def shutdown() -> None:  # type: ignore[misc]
        pass

else:
    import asyncio
    import json
    import logging
    import subprocess
    from pathlib import Path

logger = logging.getLogger(__name__)

_WORKER_SCRIPT = Path(__file__).parent / "_ax_worker.py"
_PYTHON = Path.home() / ".local" / "bin" / "python3"
_REQUEST_TIMEOUT = 10.0  # seconds

_process: subprocess.Popen | None = None
_lock = asyncio.Lock()
_ready = False


async def _ensure_worker() -> bool:
    """Start the AX worker process if not running."""
    global _process, _ready

    async with _lock:
        if _process is not None and _process.poll() is None and _ready:
            return True

        if not _PYTHON.exists():
            logger.warning("Python not found at %s", _PYTHON)
            return False

        if not _WORKER_SCRIPT.exists():
            logger.warning("AX worker script not found at %s", _WORKER_SCRIPT)
            return False

        try:
            _process = subprocess.Popen(  # noqa: ASYNC220, S603
                [str(_PYTHON), str(_WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            loop = asyncio.get_event_loop()
            line = await asyncio.wait_for(
                loop.run_in_executor(None, _process.stdout.readline),
                timeout=_REQUEST_TIMEOUT,
            )
            if not line:
                logger.warning("AX worker produced no output")
                _process.kill()
                _process = None
                return False

            status = json.loads(line.strip())
            if status.get("status") == "ready":
                _ready = True
                logger.info("AX bridge worker ready")
                return True

            error_msg = status.get("error", "unknown")
            logger.warning("AX worker not ready: %s", error_msg)
            _process.kill()
            _process = None
            return False
        except Exception as e:
            logger.warning("Failed to start AX worker: %s", e)
            if _process:
                try:
                    _process.kill()
                except ProcessLookupError:
                    pass
            _process = None
            _ready = False
            return False


async def _send_command(command: str, **kwargs) -> dict | None:
    """Send a command to the worker and return the response."""
    global _process, _ready

    if not await _ensure_worker():
        return None

    try:
        request = {"command": command, **kwargs}
        line = json.dumps(request, ensure_ascii=False) + "\n"
        _process.stdin.write(line)
        _process.stdin.flush()

        loop = asyncio.get_event_loop()
        response_line = await asyncio.wait_for(
            loop.run_in_executor(None, _process.stdout.readline),
            timeout=_REQUEST_TIMEOUT,
        )
        if not response_line:
            logger.warning("AX worker returned empty response")
            _ready = False
            return None

        return json.loads(response_line.strip())
    except TimeoutError:
        logger.warning("AX worker request timed out")
        _ready = False
        if _process:
            try:
                _process.kill()
            except ProcessLookupError:
                pass
        _process = None
        return None
    except Exception as e:
        logger.warning("AX bridge error: %s", e)
        _ready = False
        if _process:
            try:
                _process.kill()
            except ProcessLookupError:
                pass
        _process = None
        return None


# ─── Public API ──────────────────────────────────────────────────────


async def get_app_tree(app_name: str, max_depth: int = 5) -> dict:
    """Get AX Tree for a running application.

    Returns:
        {"app": "Safari", "role": "AXApplication", "children": [...]}
        or {"error": "..."} on failure.
    """
    response = await _send_command("get_tree", app_name=app_name, max_depth=max_depth)
    if response is None:
        return {"error": "AX worker unavailable"}
    if "error" in response:
        return {"error": response["error"]}
    return response.get("result", {})


async def find_element(
    app_name: str,
    role: str | None = None,
    title: str | None = None,
    identifier: str | None = None,
    max_depth: int = 10,
) -> list[dict]:
    """Find elements matching criteria in an app's AX Tree.

    Returns list of matching elements with their paths.
    """
    kwargs: dict = {"app_name": app_name, "max_depth": max_depth}
    if role:
        kwargs["role"] = role
    if title:
        kwargs["title"] = title
    if identifier:
        kwargs["identifier"] = identifier

    response = await _send_command("find_element", **kwargs)
    if response is None:
        return []
    if "error" in response:
        logger.warning("find_element error: %s", response["error"])
        return []
    return response.get("result", [])


async def get_focused_element(app_name: str | None = None) -> dict:
    """Get the currently focused UI element.

    Returns element dict or {"error": "..."} on failure.
    """
    kwargs: dict = {}
    if app_name:
        kwargs["app_name"] = app_name

    response = await _send_command("get_focused", **kwargs)
    if response is None:
        return {"error": "AX worker unavailable"}
    if "error" in response:
        return {"error": response["error"]}
    return response.get("result", {})


async def perform_action(
    app_name: str,
    element_path: str,
    action: str = "AXPress",
) -> bool:
    """Perform an accessibility action on an element.

    Args:
        app_name: Target application name.
        element_path: Numeric path to the element (e.g., "0/2/1").
        action: AX action name (default: "AXPress").

    Returns True on success, False on failure.
    """
    response = await _send_command(
        "perform_action",
        app_name=app_name,
        element_path=element_path,
        action=action,
    )
    if response is None:
        return False
    if "error" in response:
        logger.warning("perform_action error: %s", response["error"])
        return False
    return response.get("result", False)


def list_running_apps() -> list[str]:
    """List all running applications with AX access.

    Synchronous convenience method — spawns a one-shot worker process.
    """
    if not _PYTHON.exists() or not _WORKER_SCRIPT.exists():
        return []

    try:
        result = subprocess.run(  # noqa: S603
            [str(_PYTHON), "-c", _LIST_APPS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            logger.warning("list_running_apps failed: %s", result.stderr.strip())
            return []
        data = json.loads(result.stdout.strip())
        return [app["name"] for app in data if "name" in app]
    except Exception as e:
        logger.warning("list_running_apps error: %s", e)
        return []


# Inline script for one-shot app listing (avoids starting the full worker)
_LIST_APPS_SCRIPT = """\
import json, sys
try:
    from AppKit import NSWorkspace
    ws = NSWorkspace.sharedWorkspace()
    apps = []
    for a in ws.runningApplications():
        n = a.localizedName()
        if n and not a.isHidden():
            apps.append({"name": n, "pid": a.processIdentifier()})
    apps.sort(key=lambda x: x["name"].lower())
    print(json.dumps(apps))
except Exception as e:
    print(json.dumps([]), file=sys.stdout)
    print(str(e), file=sys.stderr)
"""


async def shutdown():
    """Gracefully shutdown the worker process."""
    global _process, _ready
    if _process and _process.poll() is None:
        try:
            _process.stdin.close()
            _process.wait(timeout=5)
        except Exception:
            _process.kill()
    _process = None
    _ready = False
