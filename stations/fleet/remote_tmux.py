"""SSH-based remote tmux operations for Fleet Station."""

from __future__ import annotations

import logging
import shlex
import subprocess

logger = logging.getLogger(__name__)


class RemoteTmux:
    """Execute tmux commands on a local or remote node via SSH."""

    def __init__(self, ssh_command: list[str] | None, node_name: str):
        self.ssh_command = ssh_command
        self.node_name = node_name

    def _run(self, cmd: str, timeout: int = 15) -> tuple[int, str, str]:
        """Execute a shell command, locally or via SSH."""
        try:
            if self.ssh_command is None:
                proc = subprocess.run(
                    ["bash", "-c", cmd],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            else:
                # Pipe command via stdin to avoid multi-layer SSH quoting issues.
                # ssh_command should end with 'bash -s' (reads from stdin).
                proc = subprocess.run(
                    self.ssh_command,
                    input=cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out on %s: %s", self.node_name, cmd[:80])
            return -1, "", "timeout"
        except Exception as e:
            logger.error("Command failed on %s: %s", self.node_name, e)
            return -1, "", str(e)

    def ping(self) -> bool:
        """Check if the node is reachable."""
        rc, out, _ = self._run("echo ok", timeout=10)
        return rc == 0 and "ok" in out

    def new_session(self, name: str) -> bool:
        """Create a new detached tmux session."""
        rc, _, err = self._run(f"tmux new-session -d -s {shlex.quote(name)}")
        if rc != 0:
            logger.warning("Failed to create session %s on %s: %s", name, self.node_name, err)
            return False
        return True

    def kill_session(self, name: str) -> bool:
        """Kill a tmux session."""
        rc, _, _ = self._run(f"tmux kill-session -t {shlex.quote(name)}")
        return rc == 0

    def list_sessions(self, prefix: str = "") -> list[str]:
        """List tmux sessions, optionally filtered by prefix."""
        rc, out, _ = self._run("tmux list-sessions -F '#{session_name}' 2>/dev/null")
        if rc != 0:
            return []
        sessions = [s.strip() for s in out.strip().split("\n") if s.strip()]
        if prefix:
            sessions = [s for s in sessions if s.startswith(prefix)]
        return sessions

    def send_keys(self, session: str, keys: str) -> None:
        """Send keys to a tmux session."""
        escaped = shlex.quote(keys)
        self._run(f"tmux send-keys -t {shlex.quote(session)} {escaped}")

    def send_enter(self, session: str) -> None:
        """Send Enter key to a tmux session."""
        self._run(f"tmux send-keys -t {shlex.quote(session)} Enter")

    def capture_pane(self, session: str, lines: int = 200) -> str:
        """Capture the current pane content."""
        rc, out, _ = self._run(
            f"tmux capture-pane -t {shlex.quote(session)} -p -S -{lines}",
            timeout=10,
        )
        return out if rc == 0 else ""

    def has_session(self, name: str) -> bool:
        """Check if a specific session exists."""
        rc, _, _ = self._run(f"tmux has-session -t {shlex.quote(name)} 2>/dev/null")
        return rc == 0
