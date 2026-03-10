"""Tests for ax_bridge — macOS Accessibility API subprocess bridge.

Uses mocked subprocess to test the bridge logic without pyobjc dependency.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from src.shared import ax_bridge


@pytest.fixture(autouse=True)
def _reset_worker():
    """Reset module-level worker state between tests."""
    ax_bridge._process = None
    ax_bridge._ready = False
    yield
    ax_bridge._process = None
    ax_bridge._ready = False


def _make_mock_process(responses: list[dict]):
    """Create a mock Popen that returns JSON lines from responses."""
    mock = MagicMock()
    mock.poll.return_value = None  # process is running

    lines = [json.dumps(r) + "\n" for r in responses]
    line_iter = iter(lines)
    mock.stdout.readline.side_effect = lambda: next(line_iter, "")

    return mock


def _patch_paths_exist():
    """Patch Path.exists to return True for both _PYTHON and _WORKER_SCRIPT."""
    return patch("pathlib.Path.exists", return_value=True)


class TestEnsureWorker:
    """Tests for _ensure_worker startup logic."""

    @pytest.mark.asyncio
    async def test_worker_starts_successfully(self):
        """Worker process starts and reports ready."""
        mock_proc = _make_mock_process([{"status": "ready"}])

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge._ensure_worker()

        assert result is True
        assert ax_bridge._ready is True

    @pytest.mark.asyncio
    async def test_worker_already_running(self):
        """Re-entering _ensure_worker when process is alive returns True immediately."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        ax_bridge._process = mock_proc
        ax_bridge._ready = True

        result = await ax_bridge._ensure_worker()
        assert result is True

    @pytest.mark.asyncio
    async def test_python_not_found(self):
        """Returns False when Python binary doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = await ax_bridge._ensure_worker()

        assert result is False

    @pytest.mark.asyncio
    async def test_worker_reports_error(self):
        """Worker process starts but reports an error status."""
        mock_proc = _make_mock_process([{"status": "error", "error": "no AX permission"}])

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge._ensure_worker()

        assert result is False
        assert ax_bridge._ready is False


class TestGetAppTree:
    """Tests for get_app_tree public API."""

    @pytest.mark.asyncio
    async def test_returns_tree(self):
        """Successfully retrieves an app tree."""
        tree = {"app": "Safari", "role": "AXApplication", "children": []}
        mock_proc = _make_mock_process(
            [
                {"status": "ready"},
                {"result": tree},
            ]
        )

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge.get_app_tree("Safari")

        assert result["app"] == "Safari"
        assert result["role"] == "AXApplication"

    @pytest.mark.asyncio
    async def test_returns_error_on_missing_app(self):
        """Returns error dict when app is not found."""
        mock_proc = _make_mock_process(
            [
                {"status": "ready"},
                {"error": "Application 'NoSuchApp' not found or not running"},
            ]
        )

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge.get_app_tree("NoSuchApp")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_error_when_worker_unavailable(self):
        """Returns error dict when worker can't start."""
        with patch("pathlib.Path.exists", return_value=False):
            result = await ax_bridge.get_app_tree("Safari")

        assert result == {"error": "AX worker unavailable"}


class TestFindElement:
    """Tests for find_element public API."""

    @pytest.mark.asyncio
    async def test_finds_elements(self):
        """Returns matching elements."""
        elements = [
            {"role": "AXButton", "title": "Submit", "path": "/0/2"},
            {"role": "AXButton", "title": "Submit Form", "path": "/0/3"},
        ]
        mock_proc = _make_mock_process(
            [
                {"status": "ready"},
                {"result": elements, "count": 2, "app": "Safari"},
            ]
        )

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge.find_element("Safari", role="AXButton", title="Submit")

        assert len(result) == 2
        assert result[0]["title"] == "Submit"

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self):
        """Returns empty list when worker is unavailable."""
        with patch("pathlib.Path.exists", return_value=False):
            result = await ax_bridge.find_element("Safari", role="AXButton")

        assert result == []


class TestGetFocusedElement:
    """Tests for get_focused_element."""

    @pytest.mark.asyncio
    async def test_returns_focused(self):
        """Returns the focused element."""
        focused = {"role": "AXTextField", "title": "Search", "focused": True}
        mock_proc = _make_mock_process(
            [
                {"status": "ready"},
                {"result": focused},
            ]
        )

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge.get_focused_element("Safari")

        assert result["role"] == "AXTextField"
        assert result["focused"] is True


class TestPerformAction:
    """Tests for perform_action."""

    @pytest.mark.asyncio
    async def test_action_success(self):
        """Returns True on successful action."""
        mock_proc = _make_mock_process(
            [
                {"status": "ready"},
                {"result": True, "action": "AXPress", "app": "Safari"},
            ]
        )

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge.perform_action("Safari", "0/2/1", "AXPress")

        assert result is True

    @pytest.mark.asyncio
    async def test_action_failure(self):
        """Returns False on failed action."""
        mock_proc = _make_mock_process(
            [
                {"status": "ready"},
                {"error": "Element not found at path '99/99'"},
            ]
        )

        with patch("src.shared.ax_bridge.subprocess.Popen", return_value=mock_proc):
            with _patch_paths_exist():
                result = await ax_bridge.perform_action("Safari", "99/99", "AXPress")

        assert result is False


class TestListRunningApps:
    """Tests for list_running_apps (synchronous)."""

    def test_returns_app_names(self):
        """Returns list of app name strings."""
        apps = [{"name": "Finder", "pid": 123}, {"name": "Safari", "pid": 456}]
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(apps)

        with patch("src.shared.ax_bridge.subprocess.run", return_value=mock_result):
            with _patch_paths_exist():
                result = ax_bridge.list_running_apps()

        assert result == ["Finder", "Safari"]

    def test_returns_empty_on_missing_python(self):
        """Returns empty list when Python binary not found."""
        with patch("pathlib.Path.exists", return_value=False):
            result = ax_bridge.list_running_apps()

        assert result == []


class TestShutdown:
    """Tests for shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_running_process(self):
        """Shutdown closes stdin and waits for process."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        ax_bridge._process = mock_proc
        ax_bridge._ready = True

        await ax_bridge.shutdown()

        mock_proc.stdin.close.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=5)
        assert ax_bridge._process is None
        assert ax_bridge._ready is False

    @pytest.mark.asyncio
    async def test_shutdown_no_process(self):
        """Shutdown with no process is a no-op."""
        await ax_bridge.shutdown()
        assert ax_bridge._process is None
        assert ax_bridge._ready is False
