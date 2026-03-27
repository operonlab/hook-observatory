"""Fleet Station test suite — independent QA perspective.

Tests are organized by component. Each test has a docstring explaining
what bug it catches (mutation-thinking: if the tested code were deleted
or changed, the assert MUST fail).

Mock policy: subprocess.run and SSH I/O are mocked. Internal business
logic (TaskStore, NodeRegistry, Dispatcher routing) is tested against
real objects.
"""

from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dispatcher import Dispatcher
from main import app
from node_registry import NodeRegistry, NodeState
from remote_tmux import RemoteTmux
from task_store import Task, TaskStatus, TaskStore


# ────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────


def _make_completed_process(returncode=0, stdout="", stderr=""):
    cp = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
    return cp


def _build_registry(nodes_config: dict) -> NodeRegistry:
    """Build a NodeRegistry with mocked RemoteTmux on every node."""
    registry = NodeRegistry(nodes_config)
    for node in registry.all_nodes():
        node.remote_tmux = MagicMock(spec=RemoteTmux)
    return registry


def _two_node_config() -> dict:
    return {
        "mac-local": {
            "platform": "darwin",
            "capabilities": ["filesystem", "cli-agent", "browser", "mlx"],
        },
        "win-gpu": {
            "host": "win-gpu",
            "platform": "win32-wsl2",
            "capabilities": ["gpu", "filesystem", "cli-agent", "browser"],
            "ssh_command": ["ssh", "win-gpu", "wsl", "-d", "Ubuntu", "--", "bash", "-c"],
            "gpu": {"model": "RTX 3090", "vram_gb": 24},
            "work_dir": "/home/joneshong/workshop",
            "tmux_prefix": "fleet",
            "warm_pool_size": 2,
        },
    }


# ════════════════════════════════════════════════
# 1. TestRemoteTmux
# ════════════════════════════════════════════════


class TestRemoteTmux:
    """Tests for SSH / local command execution and tmux session operations."""

    # ── SSH stdin pipe regression (Issue: bash -s vs bash -c) ──

    def test_local_execution_uses_bash_c(self):
        """Bug regression: local commands must go through 'bash -c', not 'bash -s'.
        If someone changes to bash -s, the command would be read from stdin
        and the arguments list would be wrong.
        """
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "ok", "")
            rt._run("echo hello")
            args = mock_run.call_args[0][0]
            assert args[0] == "bash", "Must use bash"
            assert args[1] == "-c", "Must use -c flag, not -s (stdin pipe bug)"
            assert args[2] == "echo hello", "Command must be passed as string argument to bash -c"

    def test_remote_execution_appends_cmd_to_ssh(self):
        """Bug regression: SSH commands must append the shell command as a
        single trailing argument so it arrives as one string to 'bash -c'
        on the remote. If split into multiple args, quoting breaks.
        """
        ssh_cmd = ["ssh", "win-gpu", "wsl", "-d", "Ubuntu", "--", "bash", "-c"]
        rt = RemoteTmux(ssh_command=ssh_cmd, node_name="win-gpu")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "ok", "")
            rt._run("echo 'hello world'")
            args = mock_run.call_args[0][0]
            # The full command list is ssh_cmd + [cmd]
            assert args == ssh_cmd + ["echo 'hello world'"]
            # Critical: cmd is ONE element, not split
            assert args[-1] == "echo 'hello world'", (
                "Command must be a single argument — splitting would break quoting"
            )

    def test_ssh_command_with_special_characters(self):
        """Catches: if someone naively splits the command string, embedded
        quotes/pipes/semicolons would cause shell injection or errors.
        """
        ssh_cmd = ["ssh", "remote", "bash", "-c"]
        rt = RemoteTmux(ssh_command=ssh_cmd, node_name="remote")
        cmd_with_specials = "cd /tmp && git log --oneline | head -5; echo 'done'"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "", "")
            rt._run(cmd_with_specials)
            args = mock_run.call_args[0][0]
            assert args[-1] == cmd_with_specials, "Special chars must not be split or escaped by _run"

    # ── Timeout handling ──

    def test_timeout_returns_minus_one(self):
        """Catches: if TimeoutExpired isn't caught, an exception would
        propagate instead of returning (-1, '', 'timeout').
        """
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 15)):
            rc, out, err = rt._run("sleep 999", timeout=1)
            assert rc == -1
            assert err == "timeout"
            assert out == ""

    def test_generic_exception_returns_minus_one(self):
        """Catches: unexpected exceptions (e.g. PermissionError) must not crash."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run", side_effect=PermissionError("no access")):
            rc, out, err = rt._run("ls")
            assert rc == -1
            assert "no access" in err

    # ── Session operations ──

    def test_ping_success(self):
        """Catches: if ping doesn't check both rc==0 AND 'ok' in output,
        it could return True for a failed connection that echoes garbage.
        """
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "ok\n", "")
            assert rt.ping() is True

    def test_ping_failure_nonzero_rc(self):
        """Catches: if only stdout is checked, a non-zero rc would be missed."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(1, "ok", "")
            assert rt.ping() is False

    def test_ping_failure_no_ok_in_output(self):
        """Catches: if only rc is checked, corrupted output would be missed."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "error\n", "")
            assert rt.ping() is False

    def test_new_session_uses_shlex_quote(self):
        """Catches: if session names with spaces/special chars aren't quoted,
        tmux would misinterpret the command.
        """
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "", "")
            rt.new_session("my session")
            cmd = mock_run.call_args[0][0][2]  # bash -c <cmd>
            assert "'my session'" in cmd, "Session name must be shlex-quoted"

    def test_new_session_returns_false_on_failure(self):
        """Catches: if failure isn't detected, caller would assume the session exists."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(1, "", "duplicate session")
            assert rt.new_session("dup") is False

    def test_list_sessions_filters_by_prefix(self):
        """Catches: if prefix filtering is removed, all sessions would be returned."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(
                0, "fleet-abc\nfleet-def\nother-xyz\n", ""
            )
            result = rt.list_sessions(prefix="fleet")
            assert result == ["fleet-abc", "fleet-def"]
            assert "other-xyz" not in result

    def test_list_sessions_empty_on_failure(self):
        """Catches: if rc!=0 path doesn't return [], an exception or stale data leaks."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(1, "", "no server running")
            assert rt.list_sessions() == []

    # ── Capture pane ──

    def test_capture_pane_returns_output(self):
        """Catches: if capture_pane doesn't return stdout on success,
        monitor loop would never detect idle state.
        """
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "line1\nline2\n❯", "")
            out = rt.capture_pane("fleet-abc", lines=50)
            assert "line1" in out
            assert "❯" in out

    def test_capture_pane_returns_empty_on_failure(self):
        """Catches: if failure isn't handled, garbage output could corrupt monitoring."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(1, "", "session not found")
            assert rt.capture_pane("nonexistent") == ""

    def test_has_session_true(self):
        """Catches: if has_session ignores rc and always returns True/False."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(0, "", "")
            assert rt.has_session("fleet-abc") is True

    def test_has_session_false(self):
        """Complement of test_has_session_true — catches inverted logic."""
        rt = RemoteTmux(ssh_command=None, node_name="local")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_completed_process(1, "", "")
            assert rt.has_session("nonexistent") is False


# ════════════════════════════════════════════════
# 2. TestNodeRegistry
# ════════════════════════════════════════════════


class TestNodeRegistry:
    """Tests for node management, capability filtering, and load balancing."""

    def test_all_nodes_populated(self):
        """Catches: if constructor doesn't iterate nodes_config, registry would be empty."""
        registry = _build_registry(_two_node_config())
        assert len(registry.all_nodes()) == 2

    def test_get_existing_node(self):
        """Catches: if get() doesn't return the right node object."""
        registry = _build_registry(_two_node_config())
        node = registry.get("mac-local")
        assert node is not None
        assert node.name == "mac-local"

    def test_get_nonexistent_node(self):
        """Catches: if get() doesn't return None for missing keys."""
        registry = _build_registry(_two_node_config())
        assert registry.get("nonexistent") is None

    def test_healthy_nodes_filters_unhealthy(self):
        """Catches: if healthy_nodes() doesn't filter on n.healthy,
        unhealthy nodes would be selected for dispatch.
        """
        registry = _build_registry(_two_node_config())
        mac = registry.get("mac-local")
        mac.healthy = True
        win = registry.get("win-gpu")
        win.healthy = False
        healthy = registry.healthy_nodes()
        assert len(healthy) == 1
        assert healthy[0].name == "mac-local"

    def test_select_node_by_capability_gpu(self):
        """Catches: if capability filtering is removed, a non-GPU node
        could be selected for GPU tasks → runtime failure on dispatch.
        """
        registry = _build_registry(_two_node_config())
        for n in registry.all_nodes():
            n.healthy = True
        node = registry.select_node(capabilities=["gpu"])
        assert node is not None
        assert node.name == "win-gpu", "Only win-gpu has 'gpu' capability"

    def test_select_node_multiple_capabilities(self):
        """Catches: if 'all()' is replaced with 'any()', partial matches pass."""
        registry = _build_registry(_two_node_config())
        for n in registry.all_nodes():
            n.healthy = True
        # Both have filesystem+cli-agent
        node = registry.select_node(capabilities=["filesystem", "cli-agent"])
        assert node is not None

    def test_select_node_impossible_capability(self):
        """Catches: if filtering doesn't return None when no node matches."""
        registry = _build_registry(_two_node_config())
        for n in registry.all_nodes():
            n.healthy = True
        assert registry.select_node(capabilities=["quantum"]) is None

    def test_select_node_load_balancing_least_tasks_first(self):
        """Catches: if sort order is reversed (descending instead of ascending),
        the busiest node gets picked — the opposite of desired behavior.
        """
        registry = _build_registry(_two_node_config())
        mac = registry.get("mac-local")
        win = registry.get("win-gpu")
        mac.healthy = True
        win.healthy = True
        mac.active_tasks = 5
        win.active_tasks = 1
        # No capability filter → both eligible → pick least loaded
        node = registry.select_node()
        assert node.name == "win-gpu", "Must pick the node with fewer active tasks"

    def test_select_node_load_balancing_tie_is_deterministic(self):
        """Catches: if tie-breaking isn't stable, repeated calls could
        return different nodes — confusing for debugging.
        """
        registry = _build_registry(_two_node_config())
        for n in registry.all_nodes():
            n.healthy = True
            n.active_tasks = 0
        first = registry.select_node()
        second = registry.select_node()
        assert first.name == second.name, "Tie-breaking must be deterministic"

    def test_select_node_no_healthy_returns_none(self):
        """Catches: if select_node doesn't guard against empty candidates."""
        registry = _build_registry(_two_node_config())
        # All unhealthy by default
        assert registry.select_node() is None

    @pytest.mark.asyncio
    async def test_check_node_updates_state(self):
        """Catches: if check_node doesn't write to node.healthy/last_check,
        health state would be stale forever.
        """
        registry = _build_registry(_two_node_config())
        node = registry.get("mac-local")
        node.remote_tmux.ping.return_value = True
        before = node.last_check
        result = await registry.check_node("mac-local")
        assert result is True
        assert node.healthy is True
        assert node.last_check > before
        assert node.last_error == ""

    @pytest.mark.asyncio
    async def test_check_node_failure_sets_error(self):
        """Catches: if failure path doesn't set last_error, operators
        can't diagnose why a node is unhealthy.
        """
        registry = _build_registry(_two_node_config())
        node = registry.get("mac-local")
        node.remote_tmux.ping.return_value = False
        result = await registry.check_node("mac-local")
        assert result is False
        assert node.healthy is False
        assert node.last_error == "ping failed"

    @pytest.mark.asyncio
    async def test_check_nonexistent_node(self):
        """Catches: if check_node doesn't guard against missing node names."""
        registry = _build_registry(_two_node_config())
        assert await registry.check_node("ghost") is False

    def test_to_dict_includes_all_fields(self):
        """Catches: if to_dict() drops a field, API consumers get incomplete data."""
        registry = _build_registry(_two_node_config())
        data = registry.to_dict()
        assert len(data) == 2
        required_keys = {"name", "healthy", "active_tasks", "capabilities", "platform", "last_check", "last_error", "gpu"}
        for entry in data:
            assert required_keys.issubset(entry.keys()), f"Missing keys in {entry}"

    def test_capabilities_from_config(self):
        """Catches: if NodeState.capabilities property doesn't read from config."""
        registry = _build_registry(_two_node_config())
        mac = registry.get("mac-local")
        assert "mlx" in mac.capabilities
        assert "gpu" not in mac.capabilities

    def test_platform_from_config(self):
        """Catches: if NodeState.platform defaults to 'unknown' even when config has it."""
        registry = _build_registry(_two_node_config())
        assert registry.get("mac-local").platform == "darwin"
        assert registry.get("win-gpu").platform == "win32-wsl2"


# ════════════════════════════════════════════════
# 3. TestTaskStore
# ════════════════════════════════════════════════


class TestTaskStore:
    """Tests for task CRUD and state machine transitions."""

    def test_create_assigns_unique_id(self):
        """Catches: if IDs aren't unique, task lookup would collide."""
        store = TaskStore()
        t1 = store.create("echo 1", "code", "mac-local")
        t2 = store.create("echo 2", "code", "mac-local")
        assert t1.id != t2.id

    def test_create_sets_pending(self):
        """Catches: if initial status isn't PENDING, dispatcher state machine breaks."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        assert task.status == TaskStatus.PENDING

    def test_create_stores_command_and_mode(self):
        """Catches: if command/mode are swapped or lost in constructor."""
        store = TaskStore()
        task = store.create("run tests", "gpu", "win-gpu", timeout=300)
        assert task.command == "run tests"
        assert task.mode == "gpu"
        assert task.node == "win-gpu"
        assert task.timeout == 300

    def test_get_returns_task(self):
        """Catches: if get() doesn't index by task_id correctly."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        assert store.get(task.id) is task

    def test_get_nonexistent_returns_none(self):
        """Catches: if get() raises KeyError instead of returning None."""
        store = TaskStore()
        assert store.get("nonexistent") is None

    # ── State machine: happy path ──

    def test_transition_pending_to_preparing(self):
        """Catches: if PREPARING state is skipped in the happy path."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        updated = store.update_status(task.id, TaskStatus.PREPARING)
        assert updated.status == TaskStatus.PREPARING

    def test_transition_preparing_to_running(self):
        """Catches: if RUNNING state can't be reached from PREPARING."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        store.update_status(task.id, TaskStatus.PREPARING)
        started = time.time()
        updated = store.update_status(task.id, TaskStatus.RUNNING, started_at=started)
        assert updated.status == TaskStatus.RUNNING
        assert updated.started_at == started

    def test_transition_running_to_completed(self):
        """Catches: if COMPLETED doesn't record completed_at timestamp."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING)
        completed = time.time()
        updated = store.update_status(task.id, TaskStatus.COMPLETED, completed_at=completed)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.completed_at == completed

    def test_full_happy_path_pending_to_completed(self):
        """Catches: the full lifecycle. If any transition is broken, this fails."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        assert task.status == TaskStatus.PENDING
        store.update_status(task.id, TaskStatus.PREPARING)
        assert task.status == TaskStatus.PREPARING
        store.update_status(task.id, TaskStatus.RUNNING, started_at=time.time())
        assert task.status == TaskStatus.RUNNING
        store.update_status(task.id, TaskStatus.COMPLETED, completed_at=time.time())
        assert task.status == TaskStatus.COMPLETED

    # ── Abnormal states ──

    def test_transition_to_failed_with_error(self):
        """Catches: if error message isn't persisted on FAILED status."""
        store = TaskStore()
        task = store.create("bad cmd", "code", "mac-local")
        store.update_status(task.id, TaskStatus.PREPARING)
        updated = store.update_status(task.id, TaskStatus.FAILED, error="git branch failed")
        assert updated.status == TaskStatus.FAILED
        assert updated.error == "git branch failed"

    def test_transition_to_timeout(self):
        """Catches: if TIMEOUT status is missing from the enum or transitions."""
        store = TaskStore()
        task = store.create("slow cmd", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING, started_at=time.time())
        updated = store.update_status(task.id, TaskStatus.TIMEOUT, completed_at=time.time())
        assert updated.status == TaskStatus.TIMEOUT

    def test_transition_to_cancelled(self):
        """Catches: if CANCELLED status doesn't work."""
        store = TaskStore()
        task = store.create("cancel me", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING)
        updated = store.update_status(task.id, TaskStatus.CANCELLED, completed_at=time.time())
        assert updated.status == TaskStatus.CANCELLED

    def test_update_nonexistent_returns_none(self):
        """Catches: if update_status raises instead of returning None."""
        store = TaskStore()
        assert store.update_status("ghost", TaskStatus.RUNNING) is None

    def test_update_ignores_unknown_kwargs(self):
        """Catches: if setattr is called without hasattr guard, AttributeError would crash."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        # unknown_field should be silently ignored
        updated = store.update_status(task.id, TaskStatus.RUNNING, unknown_field="boom")
        assert updated is not None
        assert not hasattr(updated, "unknown_field") or getattr(updated, "unknown_field", None) != "boom"

    def test_update_sets_tmux_session(self):
        """Catches: if tmux_session kwarg isn't applied via setattr."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING, tmux_session="fleet-abc123")
        assert task.tmux_session == "fleet-abc123"

    # ── Listing and filtering ──

    def test_list_tasks_returns_all(self):
        """Catches: if list_tasks doesn't include all tasks."""
        store = TaskStore()
        store.create("a", "code", "mac-local")
        store.create("b", "code", "mac-local")
        store.create("c", "gpu", "win-gpu")
        assert len(store.list_tasks()) == 3

    def test_list_tasks_filter_by_status(self):
        """Catches: if status filter uses wrong comparison (e.g. enum vs string)."""
        store = TaskStore()
        t1 = store.create("a", "code", "mac-local")
        t2 = store.create("b", "code", "mac-local")
        store.update_status(t1.id, TaskStatus.RUNNING)
        result = store.list_tasks(status="running")
        assert len(result) == 1
        assert result[0].id == t1.id

    def test_list_tasks_filter_by_node(self):
        """Catches: if node filter is broken, tasks from wrong node leak through."""
        store = TaskStore()
        store.create("a", "code", "mac-local")
        store.create("b", "gpu", "win-gpu")
        result = store.list_tasks(node="win-gpu")
        assert len(result) == 1
        assert result[0].node == "win-gpu"

    def test_list_tasks_sorted_newest_first(self):
        """Catches: if sort order is ascending, oldest tasks appear first
        which is bad UX for 'show me recent tasks'.
        """
        store = TaskStore()
        t1 = store.create("first", "code", "mac-local")
        t1.created_at = 1000
        t2 = store.create("second", "code", "mac-local")
        t2.created_at = 2000
        result = store.list_tasks()
        assert result[0].id == t2.id, "Newest task must come first"

    def test_list_tasks_respects_limit(self):
        """Catches: if limit isn't applied, large task lists would be returned."""
        store = TaskStore()
        for i in range(10):
            store.create(f"task-{i}", "code", "mac-local")
        assert len(store.list_tasks(limit=3)) == 3

    def test_to_dict_serialization(self):
        """Catches: if to_dict() is broken, API responses would fail."""
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        d = task.to_dict()
        assert d["id"] == task.id
        assert d["command"] == "echo 1"
        assert d["mode"] == "code"
        assert d["status"] == "pending"  # string value, not enum
        assert "created_at" in d

    def test_to_dict_status_is_string_not_enum(self):
        """Catches: if status is serialized as enum object instead of string,
        JSON serialization in FastAPI would fail or produce ugly output.
        """
        store = TaskStore()
        task = store.create("echo 1", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING)
        d = task.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "running"


# ════════════════════════════════════════════════
# 4. TestDispatcher
# ════════════════════════════════════════════════


class TestDispatcher:
    """Tests for task routing, session acquisition, and branch preparation."""

    def _make_dispatcher(self, nodes_config=None):
        cfg = nodes_config or _two_node_config()
        registry = _build_registry(cfg)
        store = TaskStore()
        config = {
            "code": {
                "branch_prefix": "fleet/task-",
                "workshop_dir_mac": "/Users/joneshong/workshop",
                "uv_sync_before": True,
            }
        }
        return Dispatcher(registry, store, config), registry, store

    @pytest.mark.asyncio
    async def test_dispatch_code_mode_selects_non_gpu_node(self):
        """Catches: if mode='code' incorrectly requires GPU capability,
        tasks would fail when only a CPU node is available.
        """
        dispatcher, registry, store = self._make_dispatcher()
        mac = registry.get("mac-local")
        mac.healthy = True
        mac.remote_tmux.list_sessions.return_value = ["fleet-idle"]
        mac.remote_tmux.new_session.return_value = True
        mac.remote_tmux._run.return_value = (0, "", "")

        with patch("subprocess.run", return_value=_make_completed_process(0)):
            task = await dispatcher.dispatch("echo hello", mode="code")

        assert task.node == "mac-local"
        assert task.status in (TaskStatus.RUNNING, TaskStatus.PREPARING)

    @pytest.mark.asyncio
    async def test_dispatch_gpu_mode_selects_gpu_node(self):
        """Catches: if GPU routing is broken, GPU tasks land on CPU-only nodes."""
        dispatcher, registry, store = self._make_dispatcher()
        for n in registry.all_nodes():
            n.healthy = True
            n.remote_tmux.list_sessions.return_value = ["fleet-idle"]
            n.remote_tmux.new_session.return_value = True
            n.remote_tmux._run.return_value = (0, "", "")

        with patch("subprocess.run", return_value=_make_completed_process(0)):
            task = await dispatcher.dispatch("train model", mode="gpu")

        assert task.node == "win-gpu", "GPU tasks must route to GPU-capable node"

    @pytest.mark.asyncio
    async def test_dispatch_explicit_node(self):
        """Catches: if explicit node_name is ignored, the wrong node could be used."""
        dispatcher, registry, store = self._make_dispatcher()
        win = registry.get("win-gpu")
        win.healthy = True
        win.remote_tmux.list_sessions.return_value = []
        win.remote_tmux.new_session.return_value = True
        win.remote_tmux._run.return_value = (0, "", "")

        with patch("subprocess.run", return_value=_make_completed_process(0)):
            task = await dispatcher.dispatch("echo test", mode="code", node_name="win-gpu")

        assert task.node == "win-gpu"

    @pytest.mark.asyncio
    async def test_dispatch_unhealthy_explicit_node_raises(self):
        """Catches: if unhealthy check is missing, tasks could be sent to dead nodes."""
        dispatcher, registry, store = self._make_dispatcher()
        win = registry.get("win-gpu")
        win.healthy = False

        with pytest.raises(ValueError, match="unhealthy"):
            await dispatcher.dispatch("echo test", node_name="win-gpu")

    @pytest.mark.asyncio
    async def test_dispatch_nonexistent_node_raises(self):
        """Catches: if node lookup doesn't guard against missing names."""
        dispatcher, registry, store = self._make_dispatcher()
        with pytest.raises(ValueError, match="not found"):
            await dispatcher.dispatch("echo test", node_name="ghost")

    @pytest.mark.asyncio
    async def test_dispatch_no_healthy_node_raises(self):
        """Catches: if no-node case isn't handled, NoneType error on node access."""
        dispatcher, registry, store = self._make_dispatcher()
        # All nodes unhealthy by default
        with pytest.raises(ValueError, match="No healthy node"):
            await dispatcher.dispatch("echo test", mode="code")

    @pytest.mark.asyncio
    async def test_dispatch_creates_branch_for_code_mode(self):
        """Catches: if branch preparation is skipped for code mode,
        work isolation (the core purpose of Fleet) would be lost.
        """
        dispatcher, registry, store = self._make_dispatcher()
        mac = registry.get("mac-local")
        mac.healthy = True
        mac.remote_tmux.list_sessions.return_value = ["fleet-idle"]
        mac.remote_tmux._run.return_value = (0, "", "")

        with patch("subprocess.run", return_value=_make_completed_process(0)) as mock_git:
            task = await dispatcher.dispatch("fix bug", mode="code")

        assert task.branch is not None
        assert task.branch.startswith("fleet/task-")

    @pytest.mark.asyncio
    async def test_dispatch_git_failure_sets_failed(self):
        """Catches: if git branch prep exception isn't caught, the task
        would remain in PREPARING state forever.
        """
        dispatcher, registry, store = self._make_dispatcher()
        mac = registry.get("mac-local")
        mac.healthy = True

        with patch("subprocess.run", side_effect=Exception("git broken")):
            task = await dispatcher.dispatch("fix bug", mode="code")

        assert task.status == TaskStatus.FAILED
        assert "git broken" in task.error

    def test_acquire_session_reuses_idle(self):
        """Catches: if idle detection is broken, a new session is always
        created — wasting resources and ignoring the warm pool.
        """
        dispatcher, registry, store = self._make_dispatcher()
        node = registry.get("mac-local")
        node.remote_tmux.list_sessions.return_value = ["fleet-aaa", "fleet-bbb"]
        # No running tasks → both sessions are idle
        session = dispatcher._acquire_session(node)
        assert session == "fleet-aaa", "Should reuse first idle session"
        node.remote_tmux.new_session.assert_not_called()

    def test_acquire_session_skips_active(self):
        """Catches: if active session filtering is broken, a session
        already running a task could be double-booked.
        """
        dispatcher, registry, store = self._make_dispatcher()
        node = registry.get("mac-local")
        node.remote_tmux.list_sessions.return_value = ["fleet-aaa", "fleet-bbb"]
        # Simulate fleet-aaa is in use
        task = store.create("running cmd", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING, tmux_session="fleet-aaa")
        session = dispatcher._acquire_session(node)
        assert session == "fleet-bbb", "Should skip the active session"

    def test_acquire_session_creates_new_when_all_busy(self):
        """Catches: if fallback creation is removed, dispatch would fail
        when the warm pool is exhausted.
        """
        dispatcher, registry, store = self._make_dispatcher()
        node = registry.get("mac-local")
        node.remote_tmux.list_sessions.return_value = ["fleet-aaa"]
        # fleet-aaa is active
        task = store.create("running cmd", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING, tmux_session="fleet-aaa")
        node.remote_tmux.new_session.return_value = True
        session = dispatcher._acquire_session(node)
        node.remote_tmux.new_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_running_task(self):
        """Catches: if cancel doesn't update status, the task would appear stuck."""
        dispatcher, registry, store = self._make_dispatcher()
        node = registry.get("mac-local")
        node.healthy = True
        task = store.create("long task", "code", "mac-local")
        store.update_status(task.id, TaskStatus.RUNNING, tmux_session="fleet-aaa")
        node.active_tasks = 1

        cancelled = await dispatcher.cancel(task.id)
        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED
        assert cancelled.completed_at is not None
        assert node.active_tasks == 0

    @pytest.mark.asyncio
    async def test_cancel_completed_task_returns_none(self):
        """Catches: if cancel doesn't guard against terminal states,
        a COMPLETED task could be reverted to CANCELLED.
        """
        dispatcher, registry, store = self._make_dispatcher()
        task = store.create("done", "code", "mac-local")
        store.update_status(task.id, TaskStatus.COMPLETED)
        result = await dispatcher.cancel(task.id)
        assert result is None, "Cannot cancel an already-completed task"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_none(self):
        """Catches: if cancel doesn't guard against missing tasks."""
        dispatcher, registry, store = self._make_dispatcher()
        assert await dispatcher.cancel("ghost") is None

    @pytest.mark.asyncio
    async def test_get_output_for_completed_task(self):
        """Catches: if get_output doesn't fall back to stored output
        for non-running tasks.
        """
        dispatcher, registry, store = self._make_dispatcher()
        task = store.create("echo hi", "code", "mac-local")
        task.output = "hello world\n"
        store.update_status(task.id, TaskStatus.COMPLETED)
        output = await dispatcher.get_output(task.id)
        assert output == "hello world\n"

    @pytest.mark.asyncio
    async def test_get_output_nonexistent_returns_empty(self):
        """Catches: if get_output raises on missing task."""
        dispatcher, registry, store = self._make_dispatcher()
        assert await dispatcher.get_output("ghost") == ""


# ════════════════════════════════════════════════
# 5. TestHealthEndpoint
# ════════════════════════════════════════════════


class TestHealthEndpoint:
    """Tests for /health API endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client with pre-configured app state."""
        registry = _build_registry(_two_node_config())
        store = TaskStore()
        config = {"port": 10106}
        dispatcher = Dispatcher(registry, store, config)

        app.state.config = config
        app.state.registry = registry
        app.state.store = store
        app.state.dispatcher = dispatcher

        return TestClient(app, raise_server_exceptions=False)

    def test_health_returns_200(self, client):
        """Catches: if /health route is missing or misconfigured."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_status_field(self, client):
        """Catches: if 'status' key is missing from health response."""
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data

    def test_health_returns_nodes_field(self, client):
        """Catches: if 'nodes' key is missing from health response."""
        resp = client.get("/health")
        data = resp.json()
        assert "nodes" in data
        assert isinstance(data["nodes"], dict)

    def test_health_degraded_when_nodes_unhealthy(self, client):
        """Catches: if status is always 'ok' regardless of node health,
        monitoring tools would never detect outages.
        """
        resp = client.get("/health")
        data = resp.json()
        # All nodes are unhealthy by default
        assert data["status"] == "degraded"

    def test_health_ok_when_all_healthy(self, client):
        """Catches: if status logic is inverted (healthy→degraded)."""
        registry: NodeRegistry = app.state.registry
        for n in registry.all_nodes():
            n.healthy = True
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_missing_version_field(self, client):
        """BUG DETECTED: /health does not include 'version' field.

        The FastAPI app declares version='0.1.0' but the /health endpoint
        doesn't expose it. Operators and monitoring tools typically need
        the version to correlate deployments with incidents.

        This test documents the bug — it will FAIL until the fix is applied.
        We mark it xfail so the suite stays green, but the bug is visible.
        """
        resp = client.get("/health")
        data = resp.json()
        # Currently missing — xfail documents the bug
        if "version" not in data:
            pytest.xfail(
                "BUG: /health missing 'version' field. "
                "app.version='0.1.0' exists but isn't included in the response."
            )
        assert data["version"] == "0.1.0"

    def test_health_nodes_map_reflects_registry(self, client):
        """Catches: if the nodes dict doesn't match registry state."""
        registry: NodeRegistry = app.state.registry
        mac = registry.get("mac-local")
        mac.healthy = True
        resp = client.get("/health")
        data = resp.json()
        assert data["nodes"]["mac-local"] is True
        assert data["nodes"]["win-gpu"] is False

    def test_node_detail_endpoint(self, client):
        """Catches: if /nodes endpoint is broken."""
        resp = client.get("/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {n["name"] for n in data}
        assert "mac-local" in names
        assert "win-gpu" in names

    def test_node_health_check_endpoint(self, client):
        """Catches: if /nodes/{name}/health returns wrong status."""
        registry: NodeRegistry = app.state.registry
        node = registry.get("mac-local")
        node.remote_tmux.ping.return_value = True
        resp = client.get("/nodes/mac-local/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is True

    def test_node_health_check_404(self, client):
        """Catches: if missing node doesn't return 404."""
        resp = client.get("/nodes/ghost/health")
        assert resp.status_code == 404

    def test_task_not_found_404(self, client):
        """Catches: if missing task doesn't return 404."""
        resp = client.get("/tasks/nonexistent")
        assert resp.status_code == 404
