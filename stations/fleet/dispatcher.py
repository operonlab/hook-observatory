"""Task dispatcher: warm pool management, git branch workflow, task monitoring."""

from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
import time
from uuid import uuid4

from node_registry import NodeRegistry, NodeState
from task_store import Task, TaskStatus, TaskStore

logger = logging.getLogger(__name__)


class Dispatcher:
    """Core dispatcher: routes tasks to nodes, manages warm pool, monitors progress."""

    def __init__(self, registry: NodeRegistry, store: TaskStore, config: dict):
        self.registry = registry
        self.store = store
        self.config = config
        self._monitor_tasks: dict[str, asyncio.Task] = {}

    # ── Warm Pool ──

    async def ensure_warm_pool(self, node: NodeState):
        """Maintain pre-started Claude Code interactive sessions on a node."""
        target = node.config.get("warm_pool_size", 0)
        if target <= 0:
            return

        rt = node.remote_tmux
        prefix = node.config.get("tmux_prefix", "fleet")

        loop = asyncio.get_event_loop()
        existing = await loop.run_in_executor(None, rt.list_sessions, prefix)

        while len(existing) < target:
            name = f"{prefix}-{uuid4().hex[:8]}"
            ok = await loop.run_in_executor(None, rt.new_session, name)
            if not ok:
                logger.error("Failed to create warm session %s on %s", name, node.name)
                break
            claude_path = node.config.get("claude_path", "claude")
            claude_flags = node.config.get("claude_flags", "")
            work_dir = node.config.get("work_dir", "~")
            claude_cmd = f"{claude_path} {claude_flags}".strip()
            await loop.run_in_executor(None, rt.send_keys, name, f"cd {work_dir} && {claude_cmd}")
            await loop.run_in_executor(None, rt.send_enter, name)
            existing.append(name)
            logger.info("Warm session %s created on %s", name, node.name)

    # ── Session Acquisition ──

    def _acquire_session(self, node: NodeState, mode: str = "code") -> str:
        """Get an idle session from the warm pool, or create a new one.

        For code mode: reuse warm pool sessions (pre-started Claude Code).
        For gpu mode: always create a fresh raw shell session.
        """
        rt = node.remote_tmux
        prefix = node.config.get("tmux_prefix", "fleet")
        work_dir = node.config.get("work_dir", "~")

        # GPU mode: always create a raw shell session (no Claude Code)
        if mode == "gpu":
            name = f"{prefix}-gpu-{uuid4().hex[:8]}"
            rt.new_session(name)
            rt.send_keys(name, f"cd {work_dir}")
            rt.send_enter(name)
            return name

        # Code mode: try warm pool first
        sessions = rt.list_sessions(prefix=prefix)
        active_sessions = {
            t.tmux_session
            for t in self.store.list_tasks(status="running", node=node.name)
            if t.tmux_session
        }

        for s in sessions:
            if s not in active_sessions:
                return s

        # No idle session — create a new one with Claude Code
        name = f"{prefix}-{uuid4().hex[:8]}"
        rt.new_session(name)
        claude_path = node.config.get("claude_path", "claude")
        claude_flags = node.config.get("claude_flags", "")
        claude_cmd = f"{claude_path} {claude_flags}".strip()
        rt.send_keys(name, f"cd {work_dir} && {claude_cmd}")
        rt.send_enter(name)
        return name

    # ── Dispatch ──

    async def dispatch(
        self,
        command: str,
        mode: str = "code",
        node_name: str | None = None,
        timeout: int = 600,
    ) -> Task:
        """Submit a task: select node → acquire session → send command → monitor."""
        # 1. Select node
        if node_name:
            node = self.registry.get(node_name)
            if not node:
                raise ValueError(f"Node not found: {node_name}")
            if not node.healthy:
                raise ValueError(f"Node unhealthy: {node_name}")
        else:
            caps = ["gpu"] if mode == "gpu" else None
            node = self.registry.select_node(capabilities=caps)
            if not node:
                raise ValueError("No healthy node available for requested capabilities")

        # 1.5 Conflict detection: warn if node already has a running task
        running = self.store.list_tasks(status="running", node=node.name)
        for t in running:
            logger.warning("Node %s already has running task %s", node.name, t.id)

        # 2. Create task
        task = self.store.create(command=command, mode=mode, node=node.name, timeout=timeout)
        self.store.update_status(task.id, TaskStatus.PREPARING)

        # 3. Code mode: prepare git branch
        if mode == "code":
            code_cfg = self.config.get("code", {})
            branch_prefix = code_cfg.get("branch_prefix", "fleet/task-")
            branch = f"{branch_prefix}{task.id[:8]}"
            task.branch = branch
            try:
                await self._prepare_git_branch(branch, node, code_cfg)
            except Exception as e:
                logger.error("Git branch prep failed: %s", e)
                self.store.update_status(task.id, TaskStatus.FAILED, error=str(e))
                return task

        # 4. Acquire session + send command
        loop = asyncio.get_event_loop()
        session = await loop.run_in_executor(None, self._acquire_session, node, mode)
        task.tmux_session = session
        self.store.update_status(
            task.id,
            TaskStatus.RUNNING,
            tmux_session=session,
            started_at=time.time(),
        )

        await loop.run_in_executor(None, node.remote_tmux.send_keys, session, command)
        await loop.run_in_executor(None, node.remote_tmux.send_enter, session)

        # 5. Background monitoring
        monitor = asyncio.create_task(self._monitor_task(task, node, timeout))
        self._monitor_tasks[task.id] = monitor
        node.active_tasks += 1

        logger.info(
            "Dispatched task %s (%s) to %s session %s",
            task.id[:8],
            mode,
            node.name,
            session,
        )
        return task

    # ── Git Branch ──

    async def _prepare_git_branch(self, branch: str, node: NodeState, code_cfg: dict):
        """Create git branch on Mac, push, then fetch+checkout on remote."""
        mac_dir = code_cfg.get("workshop_dir_mac", "/Users/joneshong/workshop")
        loop = asyncio.get_event_loop()

        def _git(*args, cwd: str = mac_dir):
            return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)

        # Mac: create branch + push
        await loop.run_in_executor(None, lambda: _git("checkout", "-b", branch))
        await loop.run_in_executor(None, lambda: _git("push", "-u", "origin", branch))
        await loop.run_in_executor(None, lambda: _git("checkout", "-"))

        # Remote: fetch + checkout (only for remote nodes)
        if node.config.get("ssh_command"):
            rt = node.remote_tmux
            work_dir = node.config.get("work_dir", "~/workshop")
            uv_sync = code_cfg.get("uv_sync_before", True)
            fetch_cmd = f"cd {work_dir} && git fetch origin && git checkout {branch}"
            if uv_sync:
                fetch_cmd += " && uv sync"
            await loop.run_in_executor(None, rt._run, fetch_cmd, 60)

    # ── Monitoring ──

    async def _monitor_task(self, task: Task, node: NodeState, timeout: int):
        """Background coroutine: capture pane periodically, detect completion."""
        start = time.time()
        rt = node.remote_tmux
        loop = asyncio.get_event_loop()
        idle_count = 0

        try:
            while True:
                await asyncio.sleep(5)
                elapsed = time.time() - start

                # Timeout check
                if elapsed > timeout:
                    self.store.update_status(task.id, TaskStatus.TIMEOUT, completed_at=time.time())
                    node.active_tasks = max(0, node.active_tasks - 1)
                    logger.warning("Task %s timed out after %ds", task.id[:8], timeout)
                    return

                # Capture pane
                output = await loop.run_in_executor(None, rt.capture_pane, task.tmux_session, 50)
                task.output = output

                # Detect idle prompt (Claude Code shows > or ❯ when waiting)
                lines = output.strip().split("\n")
                if lines:
                    last = lines[-1].strip()
                    if last.endswith(">") or "❯" in last or last.endswith("$"):
                        idle_count += 1
                        if idle_count >= 2:
                            # Confirmed idle — task completed
                            if task.mode == "code" and task.branch:
                                await loop.run_in_executor(None, self._auto_commit_push, task, node)
                            self.store.update_status(
                                task.id,
                                TaskStatus.COMPLETED,
                                completed_at=time.time(),
                            )
                            node.active_tasks = max(0, node.active_tasks - 1)
                            logger.info("Task %s completed", task.id[:8])
                            return
                    else:
                        idle_count = 0
        except asyncio.CancelledError:
            logger.info("Monitor for task %s cancelled", task.id[:8])
        except Exception as e:
            logger.error("Monitor error for task %s: %s", task.id[:8], e)
            self.store.update_status(
                task.id,
                TaskStatus.FAILED,
                error=str(e),
                completed_at=time.time(),
            )
            node.active_tasks = max(0, node.active_tasks - 1)

    def _auto_commit_push(self, task: Task, node: NodeState):
        """Auto commit + push after code task completion."""
        rt = node.remote_tmux
        work_dir = node.config.get("work_dir", "~/workshop")
        msg = f"fleet/{task.id[:8]}: {task.command[:50]}"
        rt._run(
            f"cd {work_dir} && git add -A && "
            f"git diff --cached --quiet || git commit -m {shlex.quote(msg)}",
            timeout=30,
        )
        if task.branch:
            rt._run(f"cd {work_dir} && git push origin {task.branch}", timeout=30)

    # ── Cancel ──

    async def cancel(self, task_id: str) -> Task | None:
        task = self.store.get(task_id)
        if not task or task.status not in (
            TaskStatus.PENDING,
            TaskStatus.PREPARING,
            TaskStatus.RUNNING,
        ):
            return None

        # Cancel monitor
        monitor = self._monitor_tasks.pop(task_id, None)
        if monitor:
            monitor.cancel()

        # Send Ctrl-C to session
        node = self.registry.get(task.node)
        if task.tmux_session and node:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, node.remote_tmux.send_keys, task.tmux_session, "C-c")

        self.store.update_status(task_id, TaskStatus.CANCELLED, completed_at=time.time())
        if node:
            node.active_tasks = max(0, node.active_tasks - 1)
        return self.store.get(task_id)

    # ── Output ──

    async def get_output(self, task_id: str, lines: int = 200) -> str:
        task = self.store.get(task_id)
        if not task:
            return ""
        if task.status == TaskStatus.RUNNING and task.tmux_session:
            node = self.registry.get(task.node)
            if node:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    node.remote_tmux.capture_pane,
                    task.tmux_session,
                    lines,
                )
        return task.output
