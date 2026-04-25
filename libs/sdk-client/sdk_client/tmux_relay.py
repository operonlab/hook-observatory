"""tmux-relay SDK — pure Python pane pool management + relay execution.

All tmux interactions are direct subprocess calls. No shell script dependency.
Redis cache for pane state and results (via RelayCacheManager).

Usage:
    from sdk_client.tmux_relay import TmuxRelayClient

    client = TmuxRelayClient()
    panes = client.list_panes()
    result = client.run("summarize this codebase", timeout=300)
"""

from __future__ import annotations

import fcntl
import glob
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sdk_client._relay_cache import RelayCacheManager
from tmux_lib.cli_session import (
    is_process_running,
    wait_for_prompt,
)
from tmux_lib.patterns import CLAUDE_CODE

try:
    from cli_dic.registry import detect_from_command as _detect_cli
except ImportError:
    _detect_cli = None  # cli-dic not installed; fall back to /exit
from tmux_lib.primitives import (
    capture,
    display,
    send_enter,
    send_text,
    tmux_check,
    tmux_ok,
)

_SHELLS = {"bash", "zsh", "sh", "fish", "dash"}

# ======================== Errors ========================


class TmuxRelayError(Exception):
    """Raised when a tmux-relay operation fails."""

    def __init__(self, operation: str, detail: str):
        self.operation = operation
        self.detail = detail
        super().__init__(f"tmux-relay [{operation}]: {detail}")


# ======================== Data Classes ========================


@dataclass
class RelayResult:
    """Result from a relay run/dispatch."""

    pane: str = ""
    signal_file: str = ""
    result_file: str = ""
    output: str = ""
    elapsed: str = ""
    status: str = ""  # success | timeout | error
    meta: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pane": self.pane,
            "signal_file": self.signal_file,
            "result_file": self.result_file,
            "output": self.output,
            "elapsed": self.elapsed,
            "status": self.status,
        }


@dataclass
class PaneInfo:
    """A relay pane with its status."""

    pane_ref: str
    status: str  # idle | busy:relay | busy:active | busy:unknown | not-claude
    pane_id: str = ""
    role: str = ""
    task: str = ""

    def to_dict(self) -> dict[str, str]:
        d = {"pane_ref": self.pane_ref, "status": self.status, "pane_id": self.pane_id}
        if self.role:
            d["role"] = self.role
        if self.task:
            d["task"] = self.task
        return d


# ======================== Client ========================


class TmuxRelayClient:
    """Pure Python tmux-relay client. No shell script dependency.

    Args:
        claude_bin: Claude Code binary name. Defaults to CLAUDE_BIN env or "claude".
        spawn_flags: Flags for spawning Claude Code. Defaults to "--dangerously-skip-permissions".
        default_timeout: Default relay timeout in seconds.
    """

    # Pool config
    RELAY_WINDOW_PREFIX = "⚡relay"
    MAX_PANES_PER_WINDOW = 4
    MAX_TOTAL_PANES = 8
    IDLE_STANDBY_TIMEOUT = 600
    AUTO_STANDBY_IDLE_TIMEOUT = 300  # 5 min idle → exit Claude Code, keep pane
    RECYCLE_EXIT_TIMEOUT = 15
    STALE_PENDING_THRESHOLD = 1800
    INIT_TIMEOUT = 30
    INIT_POLL_INTERVAL = 2
    CONTEXT_DIR = Path("/tmp/relay-context")

    IDLE_TIMESTAMPS_DIR = Path("/tmp/relay-idle-ts")

    def __init__(
        self,
        claude_bin: str | None = None,
        spawn_flags: str = "--dangerously-skip-permissions",
        default_timeout: int = 600,
        model: str | None = None,
        silent: bool | None = None,
    ):
        self.claude_bin = claude_bin or os.environ.get("CLAUDE_BIN", "claude")
        self.spawn_flags = spawn_flags
        self.default_timeout = default_timeout
        self.model = model or os.environ.get("RELAY_MODEL")
        self.silent = silent if silent is not None else os.environ.get("RELAY_SILENT", "") == "1"
        self.IDLE_TIMESTAMPS_DIR.mkdir(parents=True, exist_ok=True)
        self._cache = RelayCacheManager()

    def _claude_cmd(self) -> str:
        """Build the full Claude Code launch command."""
        cmd = f"{self.claude_bin} {self.spawn_flags}"
        if self.model:
            cmd += f" --model {self.model}"
        if self.silent:
            cmd = f"CLAUDE_VOICE=0 {cmd}"
        return cmd

    def _exit_cli(self, pane: str) -> None:
        """Exit whatever CLI is running in the pane, using cli-dic for detection."""
        if _detect_cli is not None:
            cmd = display(pane, "#{pane_current_command}")
            entry = _detect_cli(cmd or "")
            if entry:
                eb = entry.exit_behavior
                if eb.command:
                    send_text(pane, eb.command, buf_name="_relay_paste")
                    if eb.needs_enter:
                        send_enter(pane)
                elif eb.key_sequence:
                    from tmux_lib.primitives import tmux_run

                    for _ in range(eb.repeat):
                        tmux_run("send-keys", "-t", pane, eb.key_sequence)
                        time.sleep(0.5)
                return
        # Fallback: assume Claude Code
        send_text(pane, "/exit", buf_name="_relay_paste")
        send_enter(pane)

    # Session-channel fire-and-forget notification (team coordination)
    # Read env at class load so SESSION_CHANNEL_URL/KEY override default port.
    _CHANNEL_URL = os.environ.get("SESSION_CHANNEL_URL", "http://localhost:10101")
    _CHANNEL_KEY = os.environ.get("SESSION_CHANNEL_KEY", "change-me-in-production")

    def _notify_channel(
        self, topic: str, text: str, tag: str = "", priority: str = "normal"
    ) -> None:
        """Fire-and-forget POST to session-channel. Never blocks, never fails."""
        try:
            body = json.dumps(
                {
                    "topic": topic,
                    "text": text,
                    "sender": f"relay:{os.environ.get('TMUX_PANE', 'sdk')}",
                    "priority": priority,
                    **({"tag": tag} if tag else {}),
                }
            )
            subprocess.Popen(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-m",
                    "2",
                    "-X",
                    "POST",
                    f"{self._CHANNEL_URL}/api/messages",
                    "-H",
                    "Content-Type: application/json",
                    "-H",
                    f"x-local-key: {self._CHANNEL_KEY}",
                    "-d",
                    body,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            pass  # Advisory — never block relay operations

    # ================================================================
    # Pane detection helpers
    # ================================================================

    def _pane_status(self, pane: str) -> str:
        """Determine idle/busy status — reads from Redis cache first.

        Staleness guard: if cached status is busy but updated_at is older
        than STALE_PENDING_THRESHOLD, fall through to live check to self-heal.
        """
        pane_id = display(pane, "#{pane_id}")
        if pane_id is None:
            return "not-claude"
        pane_safe = pane_id.replace("%", "")

        # Try Redis cache first
        try:
            cached = self._cache.get_pane(pane_safe)
            if cached:
                status = cached["status"]
                if status.startswith("busy"):
                    age = time.time() - cached.get("updated_at", 0)
                    if age > self.STALE_PENDING_THRESHOLD:
                        pass  # fall through to live check
                    else:
                        return status
                else:
                    return status
        except Exception:
            pass

        # Cache miss or stale busy → live check + backfill
        status = self._pane_status_live(pane, pane_safe)
        try:
            self._cache.set_pane(pane_safe, pane, status, pane_id)
        except Exception:
            pass
        return status

    def _pane_status_live(self, pane: str, pane_safe: str = "") -> str:
        """Live pane status detection via tmux subprocess (original logic)."""
        if not pane_safe:
            pane_id = display(pane, "#{pane_id}")
            if pane_id is None:
                return "not-claude"
            pane_safe = pane_id.replace("%", "")

        # Check 1: pending relay file → busy:relay (with staleness guard)
        pending_file = Path(f"/tmp/relay-pending-{pane_safe}.channel")
        if pending_file.exists():
            try:
                file_age = time.time() - pending_file.stat().st_mtime
            except OSError:
                file_age = 0
            if file_age > self.STALE_PENDING_THRESHOLD:
                pending_file.unlink(missing_ok=True)
            else:
                return "busy:relay"

        # Capture bottom 8 lines
        bottom = capture(pane, start_line=-8)
        if bottom is None:
            return "busy:unknown"

        # Check 2: prompt visible → idle
        if CLAUDE_CODE.prompt_pattern.search(bottom):
            return "idle"

        # Check 3: processing indicators → busy:active
        if CLAUDE_CODE.processing_indicators.search(bottom):
            return "busy:active"

        return "busy:unknown"

    # ================================================================
    # Window management helpers
    # ================================================================

    def _resolve_relay_session(self) -> str:
        """Find the tmux session containing relay infrastructure.

        Resolution order:
        1. RELAY_SESSION env var (explicit override)
        2. Scan all sessions for existing ⚡relay windows (prefer most panes)
        3. Fall back to current session
        """
        env_session = os.environ.get("RELAY_SESSION")
        if env_session:
            return env_session

        sessions_raw = tmux_ok("list-sessions", "-F", "#{session_name}")
        if sessions_raw:
            best_session = None
            best_count = 0
            for sess in sessions_raw.splitlines():
                sess = sess.strip()
                if not sess:
                    continue
                relay_windows = self._list_relay_windows(sess)
                if relay_windows:
                    count = sum(self._count_panes_in_window(f"{sess}:{w}") for w in relay_windows)
                    if count > best_count:
                        best_count = count
                        best_session = sess
            if best_session:
                return best_session

        return tmux_ok("display-message", "-p", "#{session_name}") or "default"

    def _list_relay_windows(self, session: str) -> list[str]:
        """List all ⚡relay window names in a session."""
        raw = tmux_ok("list-windows", "-t", session, "-F", "#{window_name}")
        if not raw:
            return []
        return [w for w in raw.splitlines() if w.startswith(self.RELAY_WINDOW_PREFIX)]

    def _count_panes_in_window(self, target: str) -> int:
        """Count panes in a specific window."""
        raw = tmux_ok("list-panes", "-t", target, "-F", "#{pane_index}")
        return len(raw.splitlines()) if raw else 0

    def _count_total_relay_panes(self, session: str) -> int:
        """Count total relay panes across all relay windows."""
        total = 0
        for wname in self._list_relay_windows(session):
            total += self._count_panes_in_window(f"{session}:{wname}")
        return total

    def _next_relay_window_name(self, session: str) -> str:
        """Get the next relay window name (⚡relay, ⚡relay-2, ...)."""
        existing = self._list_relay_windows(session)
        if not existing:
            return self.RELAY_WINDOW_PREFIX

        max_n = 1
        for wname in existing:
            if wname == self.RELAY_WINDOW_PREFIX:
                max_n = max(max_n, 1)
            else:
                m = re.match(rf"^{re.escape(self.RELAY_WINDOW_PREFIX)}-(\d+)$", wname)
                if m:
                    max_n = max(max_n, int(m.group(1)))
        return f"{self.RELAY_WINDOW_PREFIX}-{max_n + 1}"

    def _find_window_with_room(self, session: str) -> str | None:
        """Find a relay window with room (< MAX_PANES_PER_WINDOW)."""
        for wname in self._list_relay_windows(session):
            target = f"{session}:{wname}"
            if self._count_panes_in_window(target) < self.MAX_PANES_PER_WINDOW:
                return target
        return None

    def _is_primary_window(self, window_name: str) -> bool:
        """Check if window is the primary ⚡relay (never kill)."""
        return window_name == self.RELAY_WINDOW_PREFIX

    def _list_all_relay_panes(self, session: str) -> list[dict]:
        """List ALL panes in relay windows (including bare shells).

        Unlike list_panes(), this does NOT filter by _is_claude_pane().
        Returns list of {pane_ref, pane_id, is_claude, window_name}.
        """
        result = []
        for wname in self._list_relay_windows(session):
            raw = tmux_ok(
                "list-panes",
                "-t",
                f"{session}:{wname}",
                "-F",
                "#{pane_index} #{pane_id}",
            )
            if not raw:
                continue
            for line in raw.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                idx, pane_id = parts[0], parts[1]
                pane_ref = f"{session}:{wname}.{idx}"
                result.append(
                    {
                        "pane_ref": pane_ref,
                        "pane_id": pane_id,
                        "is_claude": is_process_running(pane_ref, CLAUDE_CODE),
                        "window_name": wname,
                    }
                )
        return result

    def _find_reusable_pane(self, session: str) -> str | None:
        """Find a non-Claude pane in relay windows that can be reused."""
        for wname in self._list_relay_windows(session):
            raw = tmux_ok(
                "list-panes",
                "-t",
                f"{session}:{wname}",
                "-F",
                "#{pane_index}",
            )
            if not raw:
                continue
            for idx in raw.splitlines():
                idx = idx.strip()
                pane_ref = f"{session}:{wname}.{idx}"
                if not is_process_running(pane_ref, CLAUDE_CODE):
                    return pane_ref
        return None

    # ================================================================
    # Idle timestamps
    # ================================================================

    def _touch_idle_ts(self, pane_id: str) -> None:
        pane_safe = pane_id.replace("%", "")
        (self.IDLE_TIMESTAMPS_DIR / pane_safe).write_text(str(int(time.time())))

    def _get_idle_ts(self, pane_id: str) -> int:
        pane_safe = pane_id.replace("%", "")
        f = self.IDLE_TIMESTAMPS_DIR / pane_safe
        if f.exists():
            try:
                return int(f.read_text().strip())
            except (ValueError, OSError):
                return 0
        return 0

    def _clear_idle_ts(self, pane_id: str) -> None:
        pane_safe = pane_id.replace("%", "")
        (self.IDLE_TIMESTAMPS_DIR / pane_safe).unlink(missing_ok=True)

    # ================================================================
    # tmux hooks registration
    # ================================================================

    def _ensure_hooks_registered(self, session: str) -> None:
        """Register tmux hooks for cache-updater on relay windows."""
        updater = "/Users/joneshong/workshop/stations/tmux-relay/cli/cache-updater.py"
        python = "/Users/joneshong/.local/bin/python3"
        for wname in self._list_relay_windows(session):
            target = f"{session}:{wname}"
            tmux_ok(
                "set-hook",
                "-t",
                target,
                "pane-exited",
                f"run-shell '{python} {updater} pane-exited'",
            )
            tmux_ok(
                "set-hook",
                "-t",
                target,
                "alert-activity",
                f"run-shell '{python} {updater} activity #{{pane_id}}'",
            )

    # ================================================================
    # Pool operations
    # ================================================================

    def list_panes(self, session: str | None = None) -> list[PaneInfo]:
        """List all relay panes with status — reads from Redis cache."""
        session = session or self._resolve_relay_session()

        # Check cache freshness
        try:
            if not self._cache.is_fresh():
                self.refresh_cache(session)

            panes_data = self._cache.get_all_panes()
            if panes_data:
                return [
                    PaneInfo(
                        pane_ref=d["ref"],
                        status=d["status"],
                        pane_id=d.get("pane_id", ""),
                        role=d.get("role", ""),
                        task=d.get("task", ""),
                    )
                    for d in panes_data.values()
                ]
        except Exception:
            pass

        # Fallback to live if Redis unavailable
        return self._list_panes_live(session)

    def _list_panes_live(self, session: str | None = None) -> list[PaneInfo]:
        """List all relay panes via tmux subprocess — includes standby (bare shell) panes."""
        session = session or self._resolve_relay_session()
        panes = []
        for wname in self._list_relay_windows(session):
            raw = tmux_ok(
                "list-panes",
                "-t",
                f"{session}:{wname}",
                "-F",
                "#{pane_index} #{pane_current_command}",
            )
            if not raw:
                continue
            for line in raw.splitlines():
                parts = line.split(None, 1)
                idx = parts[0]
                pane_ref = f"{session}:{wname}.{idx}"
                if is_process_running(pane_ref, CLAUDE_CODE):
                    status = self._pane_status_live(pane_ref)
                    pane_id = display(pane_ref, "#{pane_id}") or "?"
                    panes.append(PaneInfo(pane_ref=pane_ref, status=status, pane_id=pane_id))
                else:
                    # Bare shell in relay window → standby (warm pool, reusable)
                    cmd = parts[1] if len(parts) > 1 else ""
                    if cmd and cmd.split("/")[-1] in _SHELLS:
                        pane_id = display(pane_ref, "#{pane_id}") or "?"
                        panes.append(PaneInfo(pane_ref=pane_ref, status="standby", pane_id=pane_id))
        return panes

    def refresh_cache(self, session: str | None = None) -> dict:
        """Full cache rebuild from live tmux state -> Redis."""
        session = session or self._resolve_relay_session()

        # Preserve semantic fields from existing cache before clearing
        old_meta: dict[str, dict] = {}
        try:
            for k, v in self._cache.get_all_panes().items():
                preserved = {}
                for field in ("last_command", "role", "task"):
                    if v.get(field):
                        preserved[field] = v[field]
                if preserved:
                    old_meta[k] = preserved
        except Exception:
            pass

        panes = self._list_panes_live(session)
        self._cache.clear_panes()
        for p in panes:
            pane_safe = p.pane_id.replace("%", "")
            meta = old_meta.get(pane_safe, {})
            self._cache.set_pane(
                pane_safe,
                p.pane_ref,
                p.status,
                p.pane_id,
                last_command=meta.get("last_command", ""),
                role=meta.get("role", ""),
                task=meta.get("task", ""),
            )
        self._cache.touch()
        return {"panes": len(panes)}

    def status(self, pane: str) -> str:
        """Check a single pane's status."""
        if not is_process_running(pane, CLAUDE_CODE):
            return "not-claude"
        return self._pane_status(pane)

    def spawn(self, session: str | None = None) -> str:
        """Spawn a new relay pane. Returns pane ref."""
        session = session or self._resolve_relay_session()

        # Verify session exists
        try:
            tmux_check("has-session", "-t", session)
        except RuntimeError:
            raise TmuxRelayError("spawn", f"tmux session '{session}' not found")

        # Check soft limit
        total = self._count_total_relay_panes(session)
        if total >= self.MAX_TOTAL_PANES:
            pass  # Warning only — don't block

        # Priority 1: Reuse existing non-Claude pane in relay windows
        reusable = self._find_reusable_pane(session)
        if reusable:
            target = reusable
            # Only start Claude Code if the pane is a bare shell
            cmd = display(target, "#{pane_current_command}")
            already_claude = cmd and "claude" in cmd
        else:
            already_claude = False
            # Priority 2: Split-pane in existing window with room
            target_window = self._find_window_with_room(session)

            if target_window:
                tmux_check("split-window", "-t", target_window, "-v")
                new_pane_idx = display(target_window, "#{pane_index}")
                wname = display(target_window, "#{window_name}")
                target = f"{session}:{wname}.{new_pane_idx}"
            else:
                # Priority 3: Create new relay window
                new_wname = self._next_relay_window_name(session)
                tmux_check("new-window", "-t", f"{session}:", "-n", new_wname)
                raw = tmux_check(
                    "list-panes", "-t", f"{session}:{new_wname}", "-F", "#{pane_index}"
                )
                first_idx = raw.splitlines()[0].strip()
                target = f"{session}:{new_wname}.{first_idx}"

        # Ensure even layout
        wname_layout = display(target, "#{window_name}")
        if wname_layout:
            tmux_ok("select-layout", "-t", f"{session}:{wname_layout}", "even-horizontal")

        # Start Claude Code (skip if pane already has it running)
        if not already_claude:
            # Ensure pane is in workshop directory (new panes may inherit / or ~)
            send_text(target, "cd ~/workshop", buf_name="_relay_paste")
            send_enter(target)
            time.sleep(0.3)
            send_text(target, self._claude_cmd(), buf_name="_relay_paste")
            send_enter(target)

        # Wait for ❯ prompt
        if already_claude or wait_for_prompt(
            target, CLAUDE_CODE, timeout=self.INIT_TIMEOUT, poll_interval=2.0
        ):
            # Cache: register new pane as idle
            pane_id = display(target, "#{pane_id}")
            if pane_id:
                try:
                    self._cache.set_pane(pane_id.replace("%", ""), target, "idle", pane_id)
                except Exception:
                    pass
            # Register tmux hooks
            self._ensure_hooks_registered(session)
            # Advertise pane to capability registry so cross-CLI board
            # dispatch can route tasks by mcps/skills. Best-effort.
            if pane_id:
                self.advertise_pane(
                    pane_id=pane_id,
                    cli_type="claude-code",
                    mcps=self._read_mcp_servers(),
                    skills=self._read_skill_names(),
                )
            return target

        self._notify_channel(
            "relay-activity",
            f"❌ spawn timeout: {target} after {self.INIT_TIMEOUT}s",
            tag="error",
            priority="high",
        )
        raise TmuxRelayError(
            "spawn", f"Claude Code init timeout after {self.INIT_TIMEOUT}s in {target}"
        )

    _ACQUIRE_LOCK = Path("/tmp/relay-acquire.lock")

    def acquire(self, count: int = 1, session: str | None = None, cwd: str = "") -> list[str]:
        """Acquire N panes (auto-spawn if needed). Returns pane refs.

        Uses file lock to prevent race conditions when multiple processes
        call acquire() concurrently.

        Args:
            cwd: Working directory for CC. Standby panes will start CC in this dir.
                 Idle panes with a different cwd will be recycled first.
        """
        if count < 1:
            raise TmuxRelayError("acquire", "count must be >= 1")

        session = session or self._resolve_relay_session()
        start_dir = cwd or "/Users/joneshong/workshop"

        # Cross-process lock — prevents parallel acquire() from grabbing the same pane
        with open(self._ACQUIRE_LOCK, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            idle = [p for p in self.list_panes(session) if p.status in ("idle", "standby")]
            acquired = []

            # When cwd is specified, prefer standby panes (can start CC in the right dir)
            if cwd:
                idle.sort(key=lambda p: 0 if p.status == "standby" else 1)

            # Take from idle/standby pool first
            for p in idle[:count]:
                # Bug fix: live-check pane status to prevent race condition
                # (cache can be stale by 0.5-1s, allowing two acquires to grab same pane)
                if p.pane_id:
                    live = self._pane_status_live(
                        p.pane_id or p.pane_ref, p.pane_id.replace("%", "")
                    )
                    if live not in ("idle", "standby"):
                        continue  # already taken by another process

                if p.status == "idle" and cwd:
                    # CC already running but we need a different cwd →
                    # standby it first, then restart in the right directory
                    self.standby(p.pane_ref)
                    p.status = "standby"

                if p.status == "standby":
                    # Bare shell → cd to target dir + start Claude Code
                    send_text(
                        p.pane_ref,
                        f"cd {start_dir} && " + self._claude_cmd(),
                        buf_name="_relay_paste",
                    )
                    send_enter(p.pane_ref)
                    if not wait_for_prompt(
                        p.pane_ref, CLAUDE_CODE, timeout=self.INIT_TIMEOUT, poll_interval=2.0
                    ):
                        continue  # failed to start → skip, deficit spawning handles it

                # Bug fix: mark busy BEFORE appending (fail = skip this pane)
                if p.pane_id:
                    self._clear_idle_ts(p.pane_id)
                    try:
                        self._cache.set_pane(
                            p.pane_id.replace("%", ""), p.pane_ref, "busy:acquired", p.pane_id
                        )
                    except Exception:
                        continue  # cache update failed → don't acquire this pane

                acquired.append(p.pane_ref)

            # Spawn more if needed
            deficit = count - len(acquired)
            for _ in range(deficit):
                new_pane = self.spawn(session=session)
                acquired.append(new_pane)
                # Mark spawned pane as busy (spawn marks it idle, we override)
                pane_id = display(new_pane, "#{pane_id}")
                if pane_id:
                    try:
                        self._cache.set_pane(
                            pane_id.replace("%", ""), new_pane, "busy:acquired", pane_id
                        )
                    except Exception:
                        pass

        return acquired

    def context(self, pane: str, lines: int = 30) -> str:
        """Capture recent conversation context from a pane."""
        result = capture(pane, start_line=-lines)
        if result is None:
            raise TmuxRelayError("context", f"Cannot capture pane {pane}")
        return result

    def _save_context(self, pane: str, pane_safe: str, reason: str = "") -> str | None:
        """Capture pane context before shutdown, save to /tmp/relay-context/{pane_safe}.json."""
        content = capture(pane, start_line=-30)
        if not content:
            return None
        self.CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
        cached = self._cache.get_pane(pane_safe)
        data = {
            "pane_safe": pane_safe,
            "role": cached.get("role", "") if cached else "",
            "task": cached.get("task", "") if cached else "",
            "last_command": cached.get("last_command", "") if cached else "",
            "context": content,
            "reason": reason,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        path = self.CONTEXT_DIR / f"{pane_safe}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return str(path)

    def standby(self, pane: str) -> str:
        """Put a pane into standby: /exit Claude Code, keep pane as bare shell."""
        cmd = display(pane, "#{pane_current_command}")
        if cmd and cmd.split("/")[-1] in _SHELLS:
            return "already-standby"

        # Save context before exit
        pane_id_pre = display(pane, "#{pane_id}")
        if pane_id_pre:
            try:
                self._save_context(pane, pane_id_pre.replace("%", ""), "standby")
            except Exception:
                pass

        self._exit_cli(pane)

        for _ in range(self.RECYCLE_EXIT_TIMEOUT):
            time.sleep(1)
            cmd = display(pane, "#{pane_current_command}")
            if cmd and cmd.split("/")[-1] in _SHELLS:
                break

        pane_id = display(pane, "#{pane_id}")
        if pane_id:
            self._clear_idle_ts(pane_id)
            try:
                self._cache.remove_pane(pane_id.replace("%", ""))
            except Exception:
                pass

        return "standby"

    def _window_name_from_pane_ref(self, pane_ref: str) -> str:
        """Extract window name from pane_ref (e.g. 'default:⚡relay-2.3' → '⚡relay-2')."""
        if ":" not in pane_ref:
            return ""
        return pane_ref.split(":")[1].rsplit(".", 1)[0]

    def auto_standby(self, session: str | None = None) -> str:
        """One-shot sweep: standby panes idle longer than AUTO_STANDBY_IDLE_TIMEOUT.

        Primary window (⚡relay): /exit Claude → keep bare shell (reusable).
        Non-primary windows: /exit Claude → kill pane → kill window if empty.
        """
        session = session or self._resolve_relay_session()
        now = int(time.time())
        standby_count = 0
        killed_count = 0

        for p in self.list_panes(session):
            if p.status != "idle":
                continue
            ts = self._get_idle_ts(p.pane_id)
            if ts == 0:
                # Bug fix: stamp idle time but DON'T skip — check duration on same pass
                # (previously required two auto_standby calls to trigger, letting panes sit idle)
                self._touch_idle_ts(p.pane_id)
                ts = int(time.time())
            idle_secs = now - ts
            if idle_secs < self.AUTO_STANDBY_IDLE_TIMEOUT:
                continue

            # Live confirmation before acting (cache might be stale)
            live_status = self._pane_status_live(
                p.pane_id or p.pane_ref, p.pane_id.replace("%", "")
            )
            if live_status != "idle":
                # Actually busy — reset idle countdown
                self._clear_idle_ts(p.pane_id)
                continue

            wname = self._window_name_from_pane_ref(p.pane_ref)

            if self._is_primary_window(wname):
                # Primary: just standby (keep bare shell for reuse)
                self.standby(p.pane_ref)
                self._clear_idle_ts(p.pane_id)
                standby_count += 1
            else:
                # Non-primary: /exit then kill pane entirely
                # Use pane_id (%XX) instead of pane_ref to avoid stale index after kills
                target = p.pane_id or p.pane_ref
                try:
                    self._save_context(target, p.pane_id.replace("%", ""), "auto_standby")
                except Exception:
                    pass
                self._exit_cli(target)
                time.sleep(3)
                tmux_ok("kill-pane", "-t", target)
                self._clear_idle_ts(p.pane_id)
                try:
                    self._cache.remove_pane(p.pane_id.replace("%", ""))
                except Exception:
                    pass
                killed_count += 1

        # Clean up empty non-primary windows
        if killed_count > 0:
            for wname in self._list_relay_windows(session):
                if self._is_primary_window(wname):
                    continue
                n = self._count_panes_in_window(f"{session}:{wname}")
                if n == 0:
                    tmux_ok("kill-window", "-t", f"{session}:{wname}")

        # Bug fix: pool maintenance — restore primary window pane count to MAX_PANES_PER_WINDOW
        spawned = 0
        for wname in self._list_relay_windows(session):
            if not self._is_primary_window(wname):
                continue
            current = self._count_panes_in_window(f"{session}:{wname}")
            deficit = self.MAX_PANES_PER_WINDOW - current
            for _ in range(deficit):
                try:
                    self.spawn(session=session)
                    spawned += 1
                except Exception:
                    break

        return f"Standby: {standby_count}, Killed: {killed_count}, Spawned: {spawned}"

    def recycle(self, pane: str) -> str:
        """Recycle a pane: exit CLI -> restart Claude Code."""
        # Step 1: Exit current CLI (auto-detects CLI type via cli-dic)
        self._exit_cli(pane)

        # Step 2: Wait for Claude to exit (pane_current_command returns to shell)
        for _ in range(self.RECYCLE_EXIT_TIMEOUT):
            time.sleep(1)
            cmd = display(pane, "#{pane_current_command}")
            if cmd is None:
                raise TmuxRelayError("recycle", f"Pane {pane} disappeared during recycle")
            if cmd in _SHELLS:
                break

        # Step 3: Ensure workshop directory + start fresh Claude Code
        send_text(pane, "cd ~/workshop", buf_name="_relay_paste")
        send_enter(pane)
        time.sleep(0.3)
        send_text(pane, self._claude_cmd(), buf_name="_relay_paste")
        send_enter(pane)

        # Step 4: Wait for ❯ prompt
        if wait_for_prompt(pane, CLAUDE_CODE, timeout=self.INIT_TIMEOUT, poll_interval=2.0):
            pane_id = display(pane, "#{pane_id}")
            if pane_id:
                self._clear_idle_ts(pane_id)
                # Cache: mark as idle after recycle
                try:
                    self._cache.set_pane(pane_id.replace("%", ""), pane, "idle", pane_id)
                except Exception:
                    pass
            return pane

        raise TmuxRelayError("recycle", f"Claude Code restart timeout after recycle in {pane}")

    def reaper(self, session: str | None = None) -> str:
        """One-shot sweep: reap excess idle Claude panes + zombie bare shells.

        Phase 1: Kill excess idle Claude panes (existing logic).
        Phase 2: Kill bare shell panes in non-primary windows.
        Phase 3: Kill empty non-primary windows.
        """
        session = session or self._resolve_relay_session()

        # Non-blocking acquire lock to prevent race with spawn/acquire
        lock_fd = open(self._ACQUIRE_LOCK, "w")
        lock_acquired = False
        for _ in range(5):
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
                break
            except BlockingIOError:
                time.sleep(2)
        if not lock_acquired:
            lock_fd.close()
            return "Skipped: acquire lock held (spawn/acquire in progress)"

        try:
            return self._reaper_locked(session)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def _reaper_locked(self, session: str) -> str:
        """Reaper logic (must be called with acquire lock held)."""
        now = int(time.time())
        messages = []

        # === Phase 1: Reap excess idle Claude panes ===
        all_panes = self.list_panes(session)
        total = len(all_panes)
        idle_panes: list[tuple[str, str, int]] = []

        for p in all_panes:
            if p.status == "idle":
                ts = self._get_idle_ts(p.pane_id)
                if ts == 0:
                    self._touch_idle_ts(p.pane_id)
                    ts = now
                idle_secs = now - ts
                idle_panes.append((p.pane_ref, p.pane_id, idle_secs))

        idle_panes.sort(key=lambda x: x[2], reverse=True)

        reaped = 0
        for pane_ref, pane_id, idle_secs in idle_panes:
            should_reap = False
            if (total - reaped) > self.MAX_TOTAL_PANES:
                should_reap = True
            if idle_secs >= self.IDLE_STANDBY_TIMEOUT and (total - reaped) > (
                self.MAX_TOTAL_PANES // 2
            ):
                should_reap = True

            if should_reap:
                # Live confirmation before reaping (cache might be stale)
                live_status = self._pane_status_live(pane_id or pane_ref, pane_id.replace("%", ""))
                if live_status != "idle":
                    self._clear_idle_ts(pane_id)
                    continue
                # Use pane_id (%XX) for stable targeting after prior kills
                target = pane_id or pane_ref
                try:
                    self._save_context(target, pane_id.replace("%", ""), "reaper")
                except Exception:
                    pass
                messages.append(f"Reaping Claude pane {target} (idle {idle_secs}s)")
                self._exit_cli(target)
                time.sleep(3)
                tmux_ok("kill-pane", "-t", target)
                self._clear_idle_ts(pane_id)
                try:
                    self._cache.remove_pane(pane_id.replace("%", ""))
                except Exception:
                    pass
                reaped += 1

        # === Phase 2: Kill bare shell panes in non-primary windows ===
        bare_killed = 0
        for p in self._list_all_relay_panes(session):
            if self._is_primary_window(p["window_name"]):
                continue
            if not p["is_claude"]:
                # Use pane_id for stable targeting
                target = p["pane_id"] or p["pane_ref"]
                messages.append(f"Killing bare shell {target}")
                tmux_ok("kill-pane", "-t", target)
                pane_safe = p["pane_id"].replace("%", "")
                self._clear_idle_ts(p["pane_id"])
                try:
                    self._cache.remove_pane(pane_safe)
                except Exception:
                    pass
                bare_killed += 1

        # === Phase 3: Kill empty non-primary windows ===
        for wname in self._list_relay_windows(session):
            if self._is_primary_window(wname):
                continue
            n = self._count_panes_in_window(f"{session}:{wname}")
            if n == 0:
                tmux_ok("kill-window", "-t", f"{session}:{wname}")
                messages.append(f"Killed empty window {wname}")

        messages.append(
            f"Summary: reaped {reaped} Claude, killed {bare_killed} bare shell. "
            f"Remaining Claude: {total - reaped}"
        )
        return "\n".join(messages)

    def cleanup(self, threshold: int | None = None) -> str:
        """Remove stale pending files (auto-heal)."""
        threshold = threshold or self.STALE_PENDING_THRESHOLD
        now = time.time()
        cleaned = 0
        messages = []

        for f in glob.glob("/tmp/relay-pending-*.channel"):
            fp = Path(f)
            if not fp.is_file():
                continue
            try:
                file_age = now - fp.stat().st_mtime
            except OSError:
                continue
            if file_age > threshold:
                channel = ""
                try:
                    channel = fp.read_text().strip()
                except OSError:
                    pass
                fp.unlink(missing_ok=True)
                cleaned += 1
                messages.append(
                    f"Cleaned stale: {fp.name} (age: {int(file_age)}s, channel: {channel or 'unknown'})"
                )

        if cleaned == 0:
            return "No stale pending files found."
        messages.append(f"Cleaned {cleaned} stale pending file(s).")
        return "\n".join(messages)

    # ================================================================
    # Pre-dispatch context check
    # ================================================================

    def _should_clear_context(self, pane: str, new_command: str) -> bool:
        """Check if pane's prior context is unrelated to new task.

        Uses headless Claude (haiku) to compare last_command vs new_command.
        Only called for relay panes (automated, no human in the loop).
        """
        pane_id = display(pane, "#{pane_id}")
        if not pane_id:
            return False
        pane_safe = pane_id.replace("%", "")

        try:
            pane_data = self._cache.get_pane(pane_safe)
            last_cmd = pane_data.get("last_command", "") if pane_data else ""
        except Exception:
            last_cmd = ""

        if not last_cmd:
            return False

        prompt = (
            f"Previous task: {last_cmd[:200]}\n"
            f"New task: {new_command[:200]}\n\n"
            "Are these two tasks related enough to share conversation context? "
            "Reply ONLY 'yes' or 'no'."
        )
        try:
            env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "relay-context-check"}
            if self.silent:
                env["CLAUDE_VOICE"] = "0"
            env.pop("CLAUDECODE", None)  # Remove nesting protection
            result = subprocess.run(
                ["claude", "-p", prompt, "--model", "haiku"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            answer = result.stdout.strip().lower()
            return "no" in answer
        except Exception:
            return False  # Safe default: don't clear on error

    # ================================================================
    # Idle watchdog — fallback for prompts that don't trigger Stop hook
    # ================================================================

    def _idle_watchdog(
        self,
        pane: str,
        channel: str,
        wait_proc: subprocess.Popen,
        interval: float = 5.0,
        min_wait: float = 15.0,
    ) -> None:
        """Detect prompt idle when Stop hook doesn't fire (e.g., simple prompts).

        Runs as daemon thread. Uses has_prompt() + not is_busy() from cli_session.
        Two consecutive prompt-idle detections = task complete.
        Also detects CC exit (pane returned to shell) as completion.
        Signals the wait-for channel to unblock _relay_execute.
        """
        from tmux_lib.cli_session import has_prompt, is_busy, is_shell

        time.sleep(min_wait)  # Don't check too early — give Claude time to process
        idle_count = 0
        exit_count = 0
        while wait_proc.poll() is None:
            try:
                # Check if CC has exited — pane returned to shell prompt
                if is_shell(pane):
                    exit_count += 1
                    if exit_count >= 2:
                        # CC exited: pane shows shell for 2 consecutive checks
                        tmux_ok("wait-for", "-S", channel)
                        break
                else:
                    exit_count = 0

                prompt_visible = has_prompt(pane, CLAUDE_CODE, lines=5)
                busy = is_busy(pane, CLAUDE_CODE, lines=8)
                if prompt_visible and not busy:
                    idle_count += 1
                    if idle_count >= 2:
                        # Stable idle: prompt visible + not busy for 2 consecutive checks
                        tmux_ok("wait-for", "-S", channel)
                        break
                else:
                    idle_count = 0  # Reset — still processing
            except Exception:
                pass
            time.sleep(interval)

    # ================================================================
    # Relay execution (was relay.sh)
    # ================================================================

    def _relay_execute(
        self,
        source: str,
        target: str = "",
        command: str = "",
        timeout: int = 600,
        extract_lines: int = 200,
        signal_file: str | None = None,
        no_forward: bool = True,
        summary_mode: bool = False,
        color: str = "",
        role: str = "",
        cwd: str = "",
    ) -> RelayResult:
        """Core relay execution — pure Python equivalent of relay.sh."""
        if not signal_file:
            signal_file = f"/tmp/relay-py-{int(time.time() * 1000)}-{os.getpid()}.done"
        result_file = signal_file.replace(".done", ".txt")

        # Resolve pane_id
        pane_id = display(source, "#{pane_id}")
        if not pane_id:
            raise TmuxRelayError("relay", f"Cannot resolve pane ID for {source}")
        pane_safe = pane_id.replace("%", "")

        # Pre-dispatch: check if prior context is stale for this task
        if command and self._should_clear_context(source, command):
            send_text(source, "/clear", buf_name="_relay_paste")
            send_enter(source)
            time.sleep(2)

        # Ensure CC is ready before sending any commands.
        # CC may show ❯ in the welcome screen before its input handler is fully
        # initialized. An extra delay prevents text from being lost or merged.
        wait_for_prompt(source, CLAUDE_CODE, timeout=15, poll_interval=1.0)
        time.sleep(3.0)

        # Set session name if role is provided (/rename is a local CLI command, instant)
        if role:
            send_text(source, f"/rename {role}", buf_name="_relay_paste")
            send_enter(source)
            time.sleep(2.0)

        # Set input bar color if requested (/color is a local CLI command, instant)
        if color:
            send_text(source, f"/color {color}", buf_name="_relay_paste")
            send_enter(source)
            time.sleep(1.0)

        # Cache: mark pane as busy:relay + store command
        try:
            self._cache.set_pane(
                pane_safe,
                source,
                "busy:relay",
                pane_id,
                signal_file=signal_file,
                last_command=command,
            )
        except Exception:
            pass

        # Channel + pending file
        channel = f"relay-{os.getpid()}-{int(time.time())}"
        pending_file = Path(f"/tmp/relay-pending-{pane_safe}.channel")

        # Cleanup on any exit path
        def _cleanup():
            pending_file.unlink(missing_ok=True)

        try:
            # Phase 1: Register wait-for channel BEFORE sending command
            pending_file.write_text(channel)

            # Start tmux wait-for in background (blocks until signaled)
            wait_proc = subprocess.Popen(
                ["tmux", "wait-for", channel],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Phase 1.1: Set tmux pane-exited hook as RELIABLE fallback
            # This fires when the CC process exits (normal /exit, crash, or context exhaustion)
            # regardless of whether Stop hook triggers. This is the ultimate safety net.
            _exit_hook_cmd = (
                f"run-shell 'tmux wait-for -S {channel} 2>/dev/null; "
                f"rm -f {pending_file} 2>/dev/null'"
            )
            try:
                tmux_ok("set-hook", "-t", pane_id, "pane-exited", _exit_hook_cmd)
            except Exception:
                pass  # Best effort — idle watchdog is secondary fallback

            # Timeout watchdog — kills wait-for if it takes too long
            timed_out = False

            def _timeout_kill():
                nonlocal timed_out
                timed_out = True
                wait_proc.kill()

            timer = threading.Timer(timeout, _timeout_kill)
            timer.start()

            # Phase 1.5: Record cursor position before sending command
            bh = int(display(source, "#{history_size}") or "0")
            bc = int(display(source, "#{cursor_y}") or "0")
            before_pos = bh + bc

            # Phase 2: Send command — verify prompt ready first
            time.sleep(0.5)  # ensure wait-for is registered
            if not wait_for_prompt(source, CLAUDE_CODE, timeout=10, poll_interval=1.0):
                pass  # Best effort — send anyway even if prompt not detected
            send_text(source, command, buf_name="_relay_paste")
            time.sleep(0.3)
            send_enter(source)
            send_time = int(time.time())

            self._notify_channel(
                "relay-activity",
                f"⚡ dispatched → {source}: {command[:80]}",
                tag="dispatched",
            )

            # Phase 3: Wait for completion signal (ZERO CPU)
            # Also start idle watchdog as fallback for prompts that don't trigger Stop hook
            idle_watchdog = threading.Thread(
                target=self._idle_watchdog,
                args=(source, channel, wait_proc),
                daemon=True,
            )
            idle_watchdog.start()

            wait_proc.wait()
            timer.cancel()

            done_time = int(time.time())
            elapsed = done_time - send_time

            # Eagerly remove pending file + clean up pane-exited hook
            pending_file.unlink(missing_ok=True)
            try:
                tmux_ok("set-hook", "-u", "-t", pane_id, "pane-exited")
            except Exception:
                pass

            # Check timeout
            if timed_out or wait_proc.returncode != 0:
                Path(signal_file).write_text(
                    f"TIMEOUT after {timeout}s waiting for command completion in {source}"
                )
                # Cache: mark pane as idle + result as timeout + start idle countdown
                try:
                    self._cache.set_pane(pane_safe, source, "idle", pane_id)
                    self._cache.set_result(
                        signal_file, status="timeout", elapsed=f"{elapsed}s", pane=source
                    )
                except Exception:
                    pass
                self._touch_idle_ts(pane_id)
                self._notify_channel(
                    "relay-activity",
                    f"⏰ timeout ← {source}: {command[:60]} ({timeout}s)",
                    tag="timeout",
                    priority="high",
                )
                return RelayResult(
                    pane=source,
                    signal_file=signal_file,
                    result_file=result_file,
                    status="timeout",
                    elapsed=f"{elapsed}s",
                )

            # Small delay to ensure Claude Code has fully rendered
            time.sleep(1)

            # Phase 4: Capture output — only NEW lines since command was sent
            ah = int(display(source, "#{history_size}") or "0")
            ac = int(display(source, "#{cursor_y}") or "0")
            after_pos = ah + ac
            new_lines = after_pos - before_pos

            # Clamp: at least 1, at most extract_lines
            new_lines = max(1, min(new_lines, extract_lines))

            start_line = before_pos - ah
            captured = tmux_ok("capture-pane", "-t", source, "-p", "-S", str(start_line)) or ""
            Path(result_file).write_text(captured)

            # Phase 5: Forward to target pane (skipped in no_forward mode)
            if not no_forward and target:
                if summary_mode:
                    lines = captured.splitlines()
                    summary_lines = lines[:40] if len(lines) > 40 else lines
                    summary_text = "\n".join(summary_lines[:38])
                    send_text(target, f"[Relay from {source}] 結果摘要：", buf_name="_relay_paste")
                    send_enter(target)
                    for line in summary_text.splitlines():
                        if line.strip():
                            send_text(target, line, buf_name="_relay_paste")
                            send_enter(target)
                else:
                    send_text(
                        target,
                        f"[Relay from {source}] 完整結果已存至 {result_file}",
                        buf_name="_relay_paste",
                    )
                    send_enter(target)
                    send_text(target, f"可用 cat {result_file} 查看", buf_name="_relay_paste")
                    send_enter(target)

            # Phase 6: Write signal file
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            Path(signal_file).write_text(
                f"status=success\n"
                f"source={source}\n"
                f"target={target}\n"
                f"command={command}\n"
                f"result_file={result_file}\n"
                f"elapsed={elapsed}s\n"
                f"timestamp={ts}\n"
            )

            # Cache: mark pane idle + cache result + start idle countdown
            try:
                self._cache.set_pane(pane_safe, source, "idle", pane_id)
                self._cache.set_result(
                    signal_file,
                    status="success",
                    elapsed=f"{elapsed}s",
                    result_file=result_file,
                    pane=source,
                )
            except Exception:
                pass
            # Start idle countdown immediately (don't wait for auto_standby to discover)
            self._touch_idle_ts(pane_id)

            self._notify_channel(
                "relay-activity",
                f"✅ completed ← {source}: {command[:60]} ({elapsed}s)",
                tag="completed",
            )

            return RelayResult(
                pane=source,
                signal_file=signal_file,
                result_file=result_file,
                output=captured,
                elapsed=f"{elapsed}s",
                status="success",
            )

        except Exception:
            _cleanup()
            raise
        finally:
            # Ensure pending file is always removed + clean pane-exited hook
            pending_file.unlink(missing_ok=True)
            try:
                tmux_ok("set-hook", "-u", "-t", pane_id, "pane-exited")
            except Exception:
                pass

    # ================================================================
    # Public relay operations
    # ================================================================

    def run(
        self,
        command: str,
        timeout: int | None = None,
        max_lines: int = 200,
        role: str = "",
        task: str = "",
        color: str = "",
        cwd: str = "",
    ) -> RelayResult:
        """Blocking relay: acquire pane -> send command -> wait -> return result."""
        timeout = timeout or self.default_timeout

        # 1. Acquire a pane (with cwd if specified — CC starts in the right dir)
        panes = self.acquire(1, cwd=cwd)
        if not panes:
            raise TmuxRelayError("run", "Failed to acquire relay pane. Is tmux running?")
        pane = panes[0]

        # 2. Write role/task metadata (preserve busy:acquired status from acquire())
        if role or task:
            pane_id = display(pane, "#{pane_id}")
            if pane_id:
                try:
                    self._cache.update_pane_meta(
                        pane_id.replace("%", ""),
                        role=role,
                        task=task,
                    )
                except Exception:
                    pass

        # 3. Recycle if busy from a PREVIOUS task (not our own acquire)
        st = self._pane_status(pane)
        if st.startswith("busy") and st != "busy:acquired":
            self.recycle(pane)

        # 4. Execute relay
        result = self._relay_execute(
            source=pane,
            command=command,
            timeout=timeout,
            extract_lines=max_lines,
            no_forward=True,
            color=color,
            role=role,
            cwd=cwd,
        )

        # Truncate output if needed
        if result.output:
            lines = result.output.splitlines()
            if len(lines) > max_lines:
                result.output = "\n".join(lines[:max_lines])
                result.output += f"\n\n... ({len(lines) - max_lines} more lines truncated)"

        return result

    def dispatch(
        self,
        command: str,
        timeout: int | None = None,
        count: int = 1,
        role: str = "",
        task: str = "",
        color: str = "",
        cwd: str = "",
    ) -> list[dict[str, str]]:
        """Fire-and-forget dispatch. Returns list of {pane, signal_file, pid}.

        Uses os.fork() so each relay execution runs in an independent child
        process that survives the parent exiting (critical for CLI usage).
        """
        timeout = timeout or self.default_timeout
        panes = self.acquire(count, cwd=cwd)
        dispatched = []

        for pane in panes:
            # Recycle if busy
            st = self._pane_status(pane)
            if st.startswith("busy"):
                try:
                    self.recycle(pane)
                except TmuxRelayError:
                    continue

            signal_file = f"/tmp/relay-py-{int(time.time() * 1000)}-{os.getpid()}.done"

            # Cache: pre-mark as busy:relay + role/task metadata
            pane_id_raw = display(pane, "#{pane_id}")
            if pane_id_raw:
                try:
                    self._cache.set_pane(
                        pane_id_raw.replace("%", ""),
                        pane,
                        "busy:relay",
                        pane_id_raw,
                        signal_file=signal_file,
                        role=role,
                        task=task,
                    )
                except Exception:
                    pass

            # Fork child process for relay execution (survives parent exit)
            child_pid = os.fork()
            if child_pid == 0:
                # Child: detach from parent session, reconnect Redis, run relay
                try:
                    os.setsid()
                except OSError:
                    pass
                # Reconnect Redis in child (shared socket after fork = corruption)
                self._cache = RelayCacheManager()
                try:
                    self._relay_execute(
                        source=pane,
                        command=command,
                        timeout=timeout,
                        signal_file=signal_file,
                        no_forward=True,
                        color=color,
                        role=role,
                        cwd=cwd,
                    )
                except Exception as exc:
                    # Ensure signal file is ALWAYS written, even on crash
                    try:
                        Path(signal_file).write_text(f"status=error\nerror={exc!r}\npane={pane}\n")
                    except Exception:
                        pass
                os._exit(0)

            # Parent: record child PID and continue
            dispatched.append(
                {
                    "pane": pane,
                    "signal_file": signal_file,
                    "pid": str(child_pid),
                }
            )

        return dispatched

    def check(self, signal_file: str) -> dict[str, str]:
        """Check if a dispatched command has completed — reads Redis first."""
        # Try Redis cache first
        try:
            cached = self._cache.get_result(signal_file)
            if cached and cached.get("status") != "running":
                return {
                    "status": "completed",
                    "signal_file": signal_file,
                    "meta": json.dumps(cached),
                }
        except Exception:
            pass

        # Fallback: file check
        if os.path.exists(signal_file):
            try:
                content = Path(signal_file).read_text().strip()
            except OSError:
                content = "(unreadable)"
            return {"status": "completed", "signal_file": signal_file, "meta": content}
        return {"status": "running", "signal_file": signal_file}

    def result(self, signal_file: str, max_lines: int = 200) -> RelayResult:
        """Read the result of a completed relay command."""
        res = RelayResult(signal_file=signal_file)

        if not os.path.exists(signal_file):
            res.status = "running"
            return res

        res.meta = Path(signal_file).read_text().strip()
        for line in res.meta.splitlines():
            if line.startswith("status="):
                res.status = line.split("=", 1)[1]
            elif line.startswith("elapsed="):
                res.elapsed = line.split("=", 1)[1]
            elif line.startswith("source="):
                res.pane = line.split("=", 1)[1]

        result_file = signal_file.replace(".done", ".txt")
        res.result_file = result_file
        if os.path.exists(result_file):
            lines = Path(result_file).read_text().splitlines()
            total = len(lines)
            truncated = lines[:max_lines]
            res.output = "\n".join(truncated)
            if total > max_lines:
                res.output += f"\n\n... ({total - max_lines} more lines truncated)"

        return res

    # ================================================================
    # Convenience
    # ================================================================

    def is_available(self) -> bool:
        """Check if tmux is running."""
        try:
            subprocess.run(
                ["tmux", "list-sessions"],
                capture_output=True,
                timeout=5,
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    # ================================================================
    # Board API — task bulletin board via session-channel
    # ================================================================
    # All board helpers delegate to SessionChannelClient (Wave 1 SoT).
    # Signatures are kept backward-compatible: only added optional params,
    # never removed or renamed. v1 callers (positional task_id on claim)
    # are still accepted via a deprecated path that emits a warning.

    def _get_session_channel_client(self):
        """Lazy-construct a SessionChannelClient bound to this relay's URL/key.

        Cached on the instance to reuse the underlying httpx.Client connection.
        """
        client = getattr(self, "_session_channel_client", None)
        if client is None:
            from sdk_client.session_channel import SessionChannelClient

            client = SessionChannelClient(
                base_url=self._CHANNEL_URL,
                local_key=self._CHANNEL_KEY,
            )
            self._session_channel_client = client
        return client

    def publish_board(
        self,
        board_id: str,
        tasks: list[dict | str],
        sender: str = "",
    ) -> dict:
        """Publish tasks to a board (delegates to SessionChannelClient).

        Args:
            board_id: Board identifier.
            tasks: list of task descriptors. Each item may be:
                - dict: full TaskPublish fields (id, desc, task_class, ...).
                - str: shorthand — wrapped as {"id": s, "desc": s,
                  "task_class": "short"}.
            sender: optional sender label (currently informational; the
                station derives ownership from x-local-key + pane on claim).

        Returns:
            Server response dict (e.g. {"ok": True, "published": N}) or {}.
        """
        del sender  # informational only; reserved for future use
        normalized: list[dict] = []
        for t in tasks:
            if isinstance(t, str):
                normalized.append({"id": t, "desc": t, "task_class": "short"})
            elif isinstance(t, dict):
                normalized.append(t)
            else:
                raise TypeError(f"task must be str or dict, got {type(t).__name__}")
        try:
            return self._get_session_channel_client().publish_board(board_id, normalized)
        except Exception as exc:  # advisory: keep relay non-fatal
            return {"ok": False, "error": str(exc)}

    def claim_board_task(
        self,
        board_id: str,
        task_id_or_pane: str = "",
        count: int = 1,
        *,
        pane: str | None = None,
        task_id: str | None = None,
    ) -> dict | list[dict] | None:
        """Claim task(s) from a board (delegates to SessionChannelClient).

        v2 (XREADGROUP-style): pulls up to `count` tasks for the given `pane`.

        Backward-compat for v1 callers `claim_board_task(board_id, task_id)`:
            The 2nd positional arg is treated as a task_id hint when the
            argument looks like one (i.e. caller passed task_id as positional
            without keyword). v2 server doesn't accept task_id-targeted
            claim, so we pull `count=1` and emit a deprecated warning.

        Returns:
            count == 1 : single dict (first claimed task) or None when empty
                         — preserves v1 return shape for legacy callers.
            count > 1  : list[dict] of claimed task descriptors.
        """
        # Resolve pane: explicit kw > env > "sdk"
        effective_pane = pane or os.environ.get("TMUX_PANE", "sdk")

        # Disambiguate the positional 2nd arg:
        #   - v2 usage:   claim_board_task("b1", pane="%42") → no positional
        #   - v2 usage:   claim_board_task("b1", "%42")      → pane positional
        #   - v1 usage:   claim_board_task("b1", "task-1")   → task_id positional
        # Heuristic: tmux pane ids start with "%"; otherwise treat as task_id
        # hint and warn (best-effort fallback to v2 claim).
        if task_id is None and task_id_or_pane:
            if task_id_or_pane.startswith("%"):
                effective_pane = task_id_or_pane
            else:
                # Looks like a task_id → v1 deprecated path
                import warnings

                warnings.warn(
                    "claim_board_task(board_id, task_id) is deprecated; "
                    "v2 board uses consumer-group claim — pass pane= and "
                    "count= instead. Falling back to count=1 claim.",
                    DeprecationWarning,
                    stacklevel=2,
                )

        try:
            tasks = self._get_session_channel_client().claim_task(board_id, effective_pane, count)
        except Exception as exc:
            if count == 1:
                return None
            return [{"ok": False, "error": str(exc)}]

        if count == 1:
            if not tasks:
                return None
            first = tasks[0]
            # Preserve v1 truthiness: ensure {"ok": True, ...} shape
            if isinstance(first, dict) and "ok" not in first:
                first = {"ok": True, **first}
            return first
        return tasks

    def drop_board_task(
        self,
        board_id: str,
        task_id: str,
        pane: str = "",
    ) -> dict | None:
        """Release a claimed task (delegates to SessionChannelClient)."""
        effective_pane = pane or os.environ.get("TMUX_PANE", "sdk")
        try:
            resp = self._get_session_channel_client().drop_task(board_id, task_id, effective_pane)
        except Exception:
            return None
        return resp if resp and resp.get("ok") else None

    def complete_board_task(
        self,
        board_id: str,
        task_id: str,
        result: dict | str = "done",
        *,
        pane: str = "",
    ) -> dict:
        """Report task completion (delegates to SessionChannelClient).

        Args:
            result: TaskResult dict (status/payload/artifacts/...) or a free
                form string. Strings are wrapped as
                {"status": "ok", "payload": {"note": result}} for backward
                compatibility with v1 callers like complete_board_task(b, t).
        """
        del pane  # ownership tracked server-side via x-local-key + claim
        if isinstance(result, str):
            result_payload: dict = {
                "status": "ok",
                "payload": {"note": result} if result else {},
            }
        elif isinstance(result, dict):
            result_payload = result
        else:
            raise TypeError(f"result must be dict or str, got {type(result).__name__}")
        try:
            return self._get_session_channel_client().complete(board_id, task_id, result_payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def heartbeat_board_task(
        self,
        board_id: str,
        task_id: str,
        pane: str = "",
    ) -> dict:
        """Extend lease ownership for a claimed task (W2-B XCLAIM)."""
        del pane  # server derives from claim ownership
        try:
            return self._get_session_channel_client().heartbeat(board_id, task_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def progress_board_task(
        self,
        board_id: str,
        task_id: str,
        percent: int,
        stage: str = "",
        note: str = "",
    ) -> dict:
        """Report mid-task progress event (W3-A)."""
        try:
            return self._get_session_channel_client().progress(
                board_id, task_id, percent, stage=stage, note=note
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _board_http(self, method: str, path: str, body: dict) -> dict | None:
        """Synchronous HTTP to session-channel board API (stdlib, no curl).

        Retained for callers that need raw HTTP access against the
        session-channel station. Internal board helpers no longer use this —
        they delegate to SessionChannelClient — but keeping it preserves
        backward compatibility for any external user/test.

        GET requests must not send a body (data=None).
        """
        import urllib.request

        method_upper = (method or "GET").upper()
        data = (
            json.dumps(body).encode()
            if method_upper not in ("GET", "HEAD") and body is not None
            else None
        )
        req = urllib.request.Request(
            f"{self._CHANNEL_URL}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-local-key": self._CHANNEL_KEY,
            },
            method=method_upper,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Cross-CLI board integration (Step 7)                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_mcp_servers() -> list[str]:
        """Read MCP server names from ~/.mcpproxy/mcp_config.json (best-effort)."""
        try:
            import os

            path = os.path.expanduser("~/.mcpproxy/mcp_config.json")
            with open(path) as f:
                data = json.load(f)
            return list((data.get("mcpServers") or {}).keys())
        except Exception:
            return []

    @staticmethod
    def _read_skill_names() -> list[str]:
        """Scan ~/.claude/skills/ for first-level directory names (best-effort, capped)."""
        try:
            import os

            root = os.path.expanduser("~/.claude/skills")
            if not os.path.isdir(root):
                return []
            return sorted(
                d
                for d in os.listdir(root)
                if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
            )[:200]
        except Exception:
            return []

    def advertise_pane(
        self,
        pane_id: str,
        cli_type: str = "claude-code",
        mcps: list[str] | None = None,
        skills: list[str] | None = None,
    ) -> dict | None:
        """Register a spawned pane in the session-channel capability registry.

        Called after `spawn()` so cross-CLI dispatch can route tasks by
        capability. Returns the advertise response or None on failure.
        Best-effort — any error is swallowed to avoid blocking spawn.
        """
        import time as _time

        try:
            from sdk_client.session_channel import PaneAdvertise

            client = self._get_session_channel_client()
            now = int(_time.time())
            advertise = PaneAdvertise(
                pane_id=pane_id,
                cli_type=cli_type,
                mcps=list(mcps or []),
                skills=list(skills or []),
                started_at=now,
                last_seen=now,
            )
            return client.advertise(advertise)
        except Exception:
            return None

    def release_pane(self, pane_id: str) -> dict | None:
        """Tell the registry this pane is gone. Server-side reaper handles
        any lingering board PEL via lease expiry; this just clears the
        capability hash so future cap-routing skips it."""
        try:
            return self._get_session_channel_client().delete_pane(pane_id)
        except Exception:
            return None

    def dispatch_via_board(
        self,
        board_id: str,
        tasks: list[dict | str],
        sender: str | None = None,
    ) -> dict:
        """Publish tasks to a board instead of send-keys-ing them directly.

        Caller (relay supervisor) hands the work to whichever cross-CLI pane
        is best-suited (capability-aware claim). Pane workers — whether CC
        with /board-claim skill or Codex/Gemini with board-worker.sh —
        independently claim, heartbeat, and complete.

        Falls back to direct dispatch if board API is unreachable.
        """
        sender = sender or "tmux-relay"
        try:
            client = self._get_session_channel_client()
            return client.publish_board(board_id, tasks, sender=sender)
        except Exception as e:
            return {"ok": False, "reason": "board_unreachable", "error": str(e)}

    def __repr__(self) -> str:
        return f"TmuxRelayClient(claude_bin={self.claude_bin!r})"
