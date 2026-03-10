#!/Users/joneshong/.local/bin/python3
"""macOS Accessibility API worker — reads AX Tree via pyobjc.

Subprocess worker for ax_bridge.py. Reads JSON-line commands from stdin,
writes JSON-line responses to stdout. All logging goes to stderr.

Requires: pyobjc-framework-ApplicationServices, pyobjc-framework-Cocoa
(installed in system or a dedicated venv with AX entitlements).

Commands:
    get_tree      — full AX tree for an application
    find_element  — search elements by role/title/identifier
    get_focused   — currently focused UI element
    perform_action — perform AX action on an element
    list_apps     — list running apps with AX access
"""

import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ax_worker")

try:
    from AppKit import NSWorkspace
    from ApplicationServices import (
        AXIsProcessTrusted,
        AXUIElementCopyAttributeNames,
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        AXUIElementCreateSystemWide,
        AXUIElementPerformAction,
    )

    PYOBJC_AVAILABLE = True
except ImportError:
    PYOBJC_AVAILABLE = False
    logger.warning("pyobjc not available — AX worker will return errors")


# ─── AX Tree Helpers ──────────────────────────────────────────────────


def _ax_get_attr(element, attr: str):
    """Get a single AX attribute value, or None on failure."""
    try:
        err, value = AXUIElementCopyAttributeValue(element, attr, None)
        if err == 0:  # kAXErrorSuccess
            return value
    except Exception:  # noqa: S110 — pyobjc attr access fails unpredictably
        pass
    return None


def _ax_get_attrs(element) -> list[str]:
    """Get all attribute names for an element."""
    try:
        err, names = AXUIElementCopyAttributeNames(element, None)
        if err == 0 and names:
            return list(names)
    except Exception:  # noqa: S110 — pyobjc attr access fails unpredictably
        pass
    return []


def _serialize_element(element, depth: int, max_depth: int) -> dict:
    """Recursively serialize an AX element into a dict."""
    node = {}

    role = _ax_get_attr(element, "AXRole")
    if role:
        node["role"] = str(role)

    title = _ax_get_attr(element, "AXTitle")
    if title:
        node["title"] = str(title)

    description = _ax_get_attr(element, "AXDescription")
    if description:
        node["description"] = str(description)

    identifier = _ax_get_attr(element, "AXIdentifier")
    if identifier:
        node["identifier"] = str(identifier)

    value = _ax_get_attr(element, "AXValue")
    if value is not None:
        try:
            node["value"] = str(value)[:500]  # truncate large values
        except Exception:  # noqa: S110 — pyobjc value conversion
            pass

    role_desc = _ax_get_attr(element, "AXRoleDescription")
    if role_desc:
        node["roleDescription"] = str(role_desc)

    enabled = _ax_get_attr(element, "AXEnabled")
    if enabled is not None:
        node["enabled"] = bool(enabled)

    focused = _ax_get_attr(element, "AXFocused")
    if focused:
        node["focused"] = True

    # Position and size
    pos = _ax_get_attr(element, "AXPosition")
    if pos:
        try:
            node["position"] = {"x": pos.x, "y": pos.y}
        except Exception:  # noqa: S110 — pyobjc struct access
            pass

    size = _ax_get_attr(element, "AXSize")
    if size:
        try:
            node["size"] = {"width": size.width, "height": size.height}
        except Exception:  # noqa: S110 — pyobjc struct access
            pass

    # Recurse into children
    if depth < max_depth:
        children_ref = _ax_get_attr(element, "AXChildren")
        if children_ref:
            children = []
            try:
                for child in children_ref:
                    children.append(_serialize_element(child, depth + 1, max_depth))
            except Exception:  # noqa: S110 — pyobjc children iteration
                pass
            if children:
                node["children"] = children

    return node


def _find_app_element(app_name: str):
    """Find the AX element for a running application by name."""
    workspace = NSWorkspace.sharedWorkspace()
    for app in workspace.runningApplications():
        name = app.localizedName()
        if name and name.lower() == app_name.lower():
            pid = app.processIdentifier()
            return AXUIElementCreateApplication(pid), name
    return None, None


def _walk_and_match(element, criteria: dict, path: str, depth: int, max_depth: int, results: list):
    """Walk tree and collect elements matching criteria."""
    if depth > max_depth:
        return

    node = _serialize_element(element, depth=depth, max_depth=depth)  # no recursion here
    match = True

    if "role" in criteria and node.get("role") != criteria["role"]:
        match = False
    if "title" in criteria and criteria["title"].lower() not in (node.get("title") or "").lower():
        match = False
    if "identifier" in criteria and node.get("identifier") != criteria["identifier"]:
        match = False

    if match and criteria:  # don't match if no criteria given
        node["path"] = path
        results.append(node)

    children_ref = _ax_get_attr(element, "AXChildren")
    if children_ref:
        try:
            for i, child in enumerate(children_ref):
                child_path = f"{path}/{i}"
                _walk_and_match(child, criteria, child_path, depth + 1, max_depth, results)
        except Exception:  # noqa: S110 — pyobjc children iteration
            pass


def _resolve_element_by_path(app_element, path: str):
    """Resolve an AX element by its numeric path (e.g., '0/2/1')."""
    current = app_element
    if not path or path == "/":
        return current

    parts = [p for p in path.strip("/").split("/") if p]
    for part in parts:
        try:
            idx = int(part)
        except ValueError:
            return None
        children = _ax_get_attr(current, "AXChildren")
        if not children or idx >= len(children):
            return None
        current = children[idx]
    return current


# ─── Command Handlers ────────────────────────────────────────────────


def handle_get_tree(cmd: dict) -> dict:
    """Get AX tree for a named application."""
    app_name = cmd.get("app_name")
    max_depth = cmd.get("max_depth", 5)

    if not app_name:
        return {"error": "app_name required"}

    element, resolved_name = _find_app_element(app_name)
    if element is None:
        return {"error": f"Application '{app_name}' not found or not running"}

    tree = _serialize_element(element, depth=0, max_depth=max_depth)
    tree["app"] = resolved_name
    return {"result": tree}


def handle_find_element(cmd: dict) -> dict:
    """Find elements matching criteria."""
    app_name = cmd.get("app_name")
    if not app_name:
        return {"error": "app_name required"}

    element, resolved_name = _find_app_element(app_name)
    if element is None:
        return {"error": f"Application '{app_name}' not found or not running"}

    criteria = {}
    if cmd.get("role"):
        criteria["role"] = cmd["role"]
    if cmd.get("title"):
        criteria["title"] = cmd["title"]
    if cmd.get("identifier"):
        criteria["identifier"] = cmd["identifier"]

    if not criteria:
        return {"error": "At least one search criterion required (role, title, identifier)"}

    max_depth = cmd.get("max_depth", 10)
    results: list[dict] = []
    _walk_and_match(element, criteria, "", 0, max_depth, results)

    return {"result": results, "count": len(results), "app": resolved_name}


def handle_get_focused(cmd: dict) -> dict:
    """Get the currently focused element."""
    app_name = cmd.get("app_name")

    if app_name:
        element, resolved_name = _find_app_element(app_name)
        if element is None:
            return {"error": f"Application '{app_name}' not found or not running"}
    else:
        element = AXUIElementCreateSystemWide()
        resolved_name = None

    focused = _ax_get_attr(element, "AXFocusedUIElement")
    if focused is None:
        return {"error": "No focused element found"}

    node = _serialize_element(focused, depth=0, max_depth=2)
    if resolved_name:
        node["app"] = resolved_name
    return {"result": node}


def handle_perform_action(cmd: dict) -> dict:
    """Perform an AX action on an element at a given path."""
    app_name = cmd.get("app_name")
    element_path = cmd.get("element_path", "")
    action = cmd.get("action", "AXPress")

    if not app_name:
        return {"error": "app_name required"}

    app_element, resolved_name = _find_app_element(app_name)
    if app_element is None:
        return {"error": f"Application '{app_name}' not found or not running"}

    target = _resolve_element_by_path(app_element, element_path)
    if target is None:
        return {"error": f"Element not found at path '{element_path}'"}

    try:
        err = AXUIElementPerformAction(target, action)
        if err == 0:  # kAXErrorSuccess
            return {"result": True, "action": action, "app": resolved_name}
        return {"error": f"AX action failed with error code {err}"}
    except Exception as e:
        return {"error": f"Action failed: {e}"}


def handle_list_apps(_cmd: dict) -> dict:
    """List running applications accessible via AX."""
    workspace = NSWorkspace.sharedWorkspace()
    apps = []
    for app in workspace.runningApplications():
        name = app.localizedName()
        if name and not app.isHidden():
            apps.append(
                {
                    "name": name,
                    "pid": app.processIdentifier(),
                    "bundleId": str(app.bundleIdentifier() or ""),
                    "active": bool(app.isActive()),
                }
            )
    # Sort by name for stable output
    apps.sort(key=lambda a: a["name"].lower())
    return {"result": apps, "count": len(apps)}


# ─── Command Dispatch ────────────────────────────────────────────────

HANDLERS = {
    "get_tree": handle_get_tree,
    "find_element": handle_find_element,
    "get_focused": handle_get_focused,
    "perform_action": handle_perform_action,
    "list_apps": handle_list_apps,
}


def main():
    """Main loop: read JSON commands from stdin, write JSON responses to stdout."""
    if not PYOBJC_AVAILABLE:
        _respond({"status": "error", "error": "pyobjc not installed"})
        return

    if not AXIsProcessTrusted():
        _respond(
            {
                "status": "error",
                "error": "Accessibility permission not granted. "
                "Enable in System Settings → Privacy & Security → Accessibility.",
            }
        )
        return

    _respond({"status": "ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as e:
            _respond({"error": f"Invalid JSON: {e}"})
            continue

        command = cmd.get("command")
        handler = HANDLERS.get(command)
        if handler is None:
            _respond({"error": f"Unknown command: {command}"})
            continue

        try:
            result = handler(cmd)
            _respond(result)
        except Exception as e:
            logger.exception("Handler error for command '%s'", command)
            _respond({"error": f"Internal error: {e}"})


def _respond(data: dict):
    """Write a JSON line to stdout and flush."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
