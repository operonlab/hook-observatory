"""tmux-relay SDK — pure Python pane pool management + relay execution.

All tmux interactions are direct subprocess calls. No shell script dependency.
Redis cache for pane state and results (via RelayCacheManager).

Usage:
    from workshop.clients.tmux_relay import TmuxRelayClient

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

from workshop.clients._relay_cache import RelayCacheManager

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

    def to_dict(self) -> dict[str, str]:
        return {"pane_ref": self.pane_ref, "status": self.status, "pane_id": self.pane_id}


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

    # Detection patterns — heuristic text matching on terminal output.
    # These are fragile UX hints, not semantic analysis. May need updating
    # if Claude Code changes its spinner/status text in future versions.
    PROCESSING_INDICATORS = re.compile(r"⏺|✢|✻|Thinking|Processing|Osmosing|Crunching|Deciphering")
    CLAUDE_INDICATORS = re.compile(r"❯|⏺|✢|✻|╭─|💰")
    PROMPT_PATTERN = re.compile(r"❯")
    SHELL_COMMANDS = {"zsh", "bash", "fish"}

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

    # ================================================================
    # tmux primitives — direct subprocess calls
    # ================================================================

    def _tmux(self, *args: str, timeout: int = 10, check: bool = True) -> str:
        """Run a tmux command and return stripped stdout."""
        try:
            proc = subprocess.run(
                ["tmux", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TmuxRelayError("tmux", f"Timed out: tmux {' '.join(args)}") from e
        except FileNotFoundError:
            raise TmuxRelayError("tmux", "tmux binary not found") from None

        if check and proc.returncode != 0:
            raise TmuxRelayError("tmux", f"rc={proc.returncode}: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def _tmux_ok(self, *args: str, timeout: int = 10) -> str | None:
        """Run a tmux command, return stdout or None on failure."""
        try:
            return self._tmux(*args, timeout=timeout)
        except TmuxRelayError:
            return None

    def _display(self, pane: str, fmt: str) -> str | None:
        """tmux display-message for a pane. Returns None on failure."""
        return self._tmux_ok("display-message", "-t", pane, "-p", fmt)

    def _capture(self, pane: str, start_line: int = -8) -> str | None:
        """tmux capture-pane. Returns captured text or None."""
        return self._tmux_ok("capture-pane", "-t", pane, "-p", "-S", str(start_line))

    # Maximum bytes safe for a single send-keys -l argument.
    # macOS ARG_MAX=1MB but tmux input parsing + shell escaping can fail
    # well before that.  512 chars is a safe conservative threshold.
    _SEND_KEYS_LIMIT = 512

    def _send_keys(self, pane: str, text: str, literal: bool = True) -> None:
        """Send text to a tmux pane.

        Short text (<512 chars): direct ``send-keys -l``.
        Long text: ``load-buffer`` from stdin + ``paste-buffer`` to bypass
        command-line length limits that cause silent truncation.
        """
        if literal and len(text) > self._SEND_KEYS_LIMIT:
            self._paste_text(pane, text)
            return
        args = ["send-keys", "-t", pane]
        if literal:
            args.append("-l")
        args.append(text)
        self._tmux(*args)

    def _paste_text(self, pane: str, text: str) -> None:
        """Send long text via load-buffer + paste-buffer (no length limit)."""
        buf_name = "_relay_paste"
        # load-buffer - reads from stdin
        try:
            subprocess.run(
                ["tmux", "load-buffer", "-b", buf_name, "-"],
                input=text,
                text=True,
                capture_output=True,
                timeout=5,
                check=True,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            raise TmuxRelayError("tmux", f"load-buffer failed: {e}") from e
        try:
            # -d deletes the buffer after pasting, -p pastes as literal text
            self._tmux("paste-buffer", "-b", buf_name, "-t", pane, "-d", "-p")
        except TmuxRelayError:
            # Cleanup buffer on failure
            self._tmux_ok("delete-buffer", "-b", buf_name)
            raise

    def _send_enter(self, pane: str) -> None:
        """Send Enter key to a pane."""
        self._tmux("send-keys", "-t", pane, "Enter")

    # ================================================================
    # Pane detection helpers
    # ================================================================

    def _is_claude_pane(self, pane: str) -> bool:
        """Check if a pane is running Claude Code."""
        cmd = self._display(pane, "#{pane_current_command}")
        if cmd:
            if "claude" in cmd:
                return True
            # Bare shell = definitely not Claude Code (❯ prompt overlaps with zsh)
            if cmd.split("/")[-1] in self.SHELL_COMMANDS:
                return False
        content = self._capture(pane, -8)
        if content and self.CLAUDE_INDICATORS.search(content):
            return True
        return False

    def _pane_status(self, pane: str) -> str:
        """Determine idle/busy status — reads from Redis cache first."""
        pane_id = self._display(pane, "#{pane_id}")
        if pane_id is None:
            return "not-claude"
        pane_safe = pane_id.replace("%", "")

        # Try Redis cache first
        try:
            cached = self._cache.get_pane(pane_safe)
            if cached:
                return cached["status"]
        except Exception:
            pass

        # Cache miss → live check + backfill
        status = self._pane_status_live(pane, pane_safe)
        try:
            self._cache.set_pane(pane_safe, pane, status, pane_id)
        except Exception:
            pass
        return status

    def _pane_status_live(self, pane: str, pane_safe: str = "") -> str:
        """Live pane status detection via tmux subprocess (original logic)."""
        if not pane_safe:
            pane_id = self._display(pane, "#{pane_id}")
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
        bottom = self._capture(pane, -8)
        if bottom is None:
            return "busy:unknown"

        # Check 2: prompt visible → idle
        if self.PROMPT_PATTERN.search(bottom):
            return "idle"

        # Check 3: processing indicators → busy:active
        if self.PROCESSING_INDICATORS.search(bottom):
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

        sessions_raw = self._tmux_ok("list-sessions", "-F", "#{session_name}")
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

        return self._tmux_ok("display-message", "-p", "#{session_name}") or "default"

    def _list_relay_windows(self, session: str) -> list[str]:
        """List all ⚡relay window names in a session."""
        raw = self._tmux_ok("list-windows", "-t", session, "-F", "#{window_name}")
        if not raw:
            return []
        return [w for w in raw.splitlines() if w.startswith(self.RELAY_WINDOW_PREFIX)]

    def _count_panes_in_window(self, target: str) -> int:
        """Count panes in a specific window."""
        raw = self._tmux_ok("list-panes", "-t", target, "-F", "#{pane_index}")
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

    def _find_reusable_pane(self, session: str) -> str | None:
        """Find a non-Claude pane in relay windows that can be reused."""
        for wname in self._list_relay_windows(session):
            raw = self._tmux_ok(
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
                if not self._is_claude_pane(pane_ref):
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
    # Prompt wait helper
    # ================================================================

    def _wait_for_prompt(self, pane: str, timeout: int | None = None) -> bool:
        """Wait for Claude Code ❯ prompt to appear."""
        timeout = timeout or self.INIT_TIMEOUT
        max_checks = timeout // self.INIT_POLL_INTERVAL
        for _ in range(max_checks):
            time.sleep(self.INIT_POLL_INTERVAL)
            bottom = self._capture(pane, -5)
            if bottom and self.PROMPT_PATTERN.search(bottom):
                return True
        return False

    # ================================================================
    # tmux hooks registration
    # ================================================================

    def _ensure_hooks_registered(self, session: str) -> None:
        """Register tmux hooks for cache-updater on relay windows."""
        updater = "/Users/joneshong/workshop/stations/tmux-relay/cli/cache-updater.py"
        python = "/Users/joneshong/.local/bin/python3"
        for wname in self._list_relay_windows(session):
            target = f"{session}:{wname}"
            self._tmux_ok(
                "set-hook",
                "-t",
                target,
                "pane-exited",
                f"run-shell '{python} {updater} pane-exited'",
            )
            self._tmux_ok(
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
                    )
                    for d in panes_data.values()
                ]
        except Exception:
            pass

        # Fallback to live if Redis unavailable
        return self._list_panes_live(session)

    def _list_panes_live(self, session: str | None = None) -> list[PaneInfo]:
        """List all relay panes via tmux subprocess (original logic)."""
        session = session or self._resolve_relay_session()
        panes = []
        for wname in self._list_relay_windows(session):
            raw = self._tmux_ok(
                "list-panes",
                "-t",
                f"{session}:{wname}",
                "-F",
                "#{pane_index} #{pane_current_command}",
            )
            if not raw:
                continue
            for line in raw.splitlines():
                idx = line.split()[0]
                pane_ref = f"{session}:{wname}.{idx}"
                if self._is_claude_pane(pane_ref):
                    status = self._pane_status_live(pane_ref)
                    pane_id = self._display(pane_ref, "#{pane_id}") or "?"
                    panes.append(PaneInfo(pane_ref=pane_ref, status=status, pane_id=pane_id))
        return panes

    def refresh_cache(self, session: str | None = None) -> dict:
        """Full cache rebuild from live tmux state -> Redis."""
        session = session or self._resolve_relay_session()

        # Preserve last_command from existing cache before clearing
        old_commands = {}
        try:
            for k, v in self._cache.get_all_panes().items():
                if v.get("last_command"):
                    old_commands[k] = v["last_command"]
        except Exception:
            pass

        panes = self._list_panes_live(session)
        self._cache.clear_panes()
        for p in panes:
            pane_safe = p.pane_id.replace("%", "")
            self._cache.set_pane(
                pane_safe,
                p.pane_ref,
                p.status,
                p.pane_id,
                last_command=old_commands.get(pane_safe, ""),
            )
        self._cache.touch()
        return {"panes": len(panes)}

    def status(self, pane: str) -> str:
        """Check a single pane's status."""
        if not self._is_claude_pane(pane):
            return "not-claude"
        return self._pane_status(pane)

    def spawn(self, session: str | None = None) -> str:
        """Spawn a new relay pane. Returns pane ref."""
        session = session or self._resolve_relay_session()

        # Verify session exists
        try:
            self._tmux("has-session", "-t", session)
        except TmuxRelayError:
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
            cmd = self._display(target, "#{pane_current_command}")
            already_claude = cmd and "claude" in cmd
        else:
            already_claude = False
            # Priority 2: Split-pane in existing window with room
            target_window = self._find_window_with_room(session)

            if target_window:
                self._tmux("split-window", "-t", target_window, "-v")
                new_pane_idx = self._display(target_window, "#{pane_index}")
                wname = self._display(target_window, "#{window_name}")
                target = f"{session}:{wname}.{new_pane_idx}"
            else:
                # Priority 3: Create new relay window
                new_wname = self._next_relay_window_name(session)
                self._tmux("new-window", "-t", f"{session}:", "-n", new_wname)
                raw = self._tmux(
                    "list-panes", "-t", f"{session}:{new_wname}", "-F", "#{pane_index}"
                )
                first_idx = raw.splitlines()[0].strip()
                target = f"{session}:{new_wname}.{first_idx}"

        # Ensure even layout
        wname_layout = self._display(target, "#{window_name}")
        if wname_layout:
            self._tmux_ok("select-layout", "-t", f"{session}:{wname_layout}", "even-horizontal")

        # Start Claude Code (skip if pane already has it running)
        if not already_claude:
            self._send_keys(target, self._claude_cmd())
            self._send_enter(target)

        # Wait for ❯ prompt
        if already_claude or self._wait_for_prompt(target):
            # Cache: register new pane as idle
            pane_id = self._display(target, "#{pane_id}")
            if pane_id:
                try:
                    self._cache.set_pane(pane_id.replace("%", ""), target, "idle", pane_id)
                except Exception:
                    pass
            # Register tmux hooks
            self._ensure_hooks_registered(session)
            return target

        raise TmuxRelayError(
            "spawn", f"Claude Code init timeout after {self.INIT_TIMEOUT}s in {target}"
        )

    _ACQUIRE_LOCK = Path("/tmp/relay-acquire.lock")

    def acquire(self, count: int = 1, session: str | None = None) -> list[str]:
        """Acquire N panes (auto-spawn if needed). Returns pane refs.

        Uses file lock to prevent race conditions when multiple processes
        call acquire() concurrently.
        """
        if count < 1:
            raise TmuxRelayError("acquire", "count must be >= 1")

        session = session or self._resolve_relay_session()

        # Cross-process lock — prevents parallel acquire() from grabbing the same pane
        with open(self._ACQUIRE_LOCK, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            idle = [p for p in self.list_panes(session) if p.status == "idle"]
            acquired = []

            # Take from idle pool first
            for p in idle[:count]:
                acquired.append(p.pane_ref)
                if p.pane_id:
                    self._clear_idle_ts(p.pane_id)
                    # Mark busy immediately so next concurrent acquire sees it as taken
                    try:
                        self._cache.set_pane(
                            p.pane_id.replace("%", ""), p.pane_ref, "busy:acquired", p.pane_id
                        )
                    except Exception:
                        pass

            # Spawn more if needed
            deficit = count - len(acquired)
            for _ in range(deficit):
                new_pane = self.spawn(session=session)
                acquired.append(new_pane)
                # Mark spawned pane as busy (spawn marks it idle, we override)
                pane_id = self._display(new_pane, "#{pane_id}")
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
        result = self._capture(pane, -lines)
        if result is None:
            raise TmuxRelayError("context", f"Cannot capture pane {pane}")
        return result

    def standby(self, pane: str) -> str:
        """Put a pane into standby: /exit Claude Code, keep pane as bare shell."""
        cmd = self._display(pane, "#{pane_current_command}")
        if cmd and cmd.split("/")[-1] in self.SHELL_COMMANDS:
            return "already-standby"

        self._send_keys(pane, "/exit")
        self._send_enter(pane)

        for _ in range(self.RECYCLE_EXIT_TIMEOUT):
            time.sleep(1)
            cmd = self._display(pane, "#{pane_current_command}")
            if cmd and cmd.split("/")[-1] in self.SHELL_COMMANDS:
                break

        pane_id = self._display(pane, "#{pane_id}")
        if pane_id:
            self._clear_idle_ts(pane_id)
            try:
                self._cache.remove_pane(pane_id.replace("%", ""))
            except Exception:
                pass

        return "standby"

    def auto_standby(self, session: str | None = None) -> str:
        """One-shot sweep: standby panes idle longer than AUTO_STANDBY_IDLE_TIMEOUT."""
        session = session or self._resolve_relay_session()
        now = int(time.time())
        standby_count = 0

        for p in self.list_panes(session):
            if p.status != "idle":
                continue
            ts = self._get_idle_ts(p.pane_id)
            if ts == 0:
                self._touch_idle_ts(p.pane_id)
                continue
            idle_secs = now - ts
            if idle_secs >= self.AUTO_STANDBY_IDLE_TIMEOUT:
                self.standby(p.pane_ref)
                self._clear_idle_ts(p.pane_id)
                standby_count += 1

        return f"Standby: {standby_count} pane(s)"

    def recycle(self, pane: str) -> str:
        """Recycle a pane: /exit -> restart Claude Code."""
        # Step 1: Send /exit
        self._send_keys(pane, "/exit")
        self._send_enter(pane)

        # Step 2: Wait for Claude to exit (pane_current_command returns to shell)
        for _ in range(self.RECYCLE_EXIT_TIMEOUT):
            time.sleep(1)
            cmd = self._display(pane, "#{pane_current_command}")
            if cmd is None:
                raise TmuxRelayError("recycle", f"Pane {pane} disappeared during recycle")
            if cmd in self.SHELL_COMMANDS:
                break

        # Step 3: Start fresh Claude Code
        self._send_keys(pane, self._claude_cmd())
        self._send_enter(pane)

        # Step 4: Wait for ❯ prompt
        if self._wait_for_prompt(pane):
            pane_id = self._display(pane, "#{pane_id}")
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
        """One-shot sweep: recycle excess idle panes."""
        session = session or self._resolve_relay_session()
        now = int(time.time())

        all_panes = self.list_panes(session)
        total = len(all_panes)
        idle_panes: list[tuple[str, str, int]] = []  # (pane_ref, pane_id, idle_secs)

        for p in all_panes:
            if p.status == "idle":
                ts = self._get_idle_ts(p.pane_id)
                if ts == 0:
                    self._touch_idle_ts(p.pane_id)
                    ts = now
                idle_secs = now - ts
                idle_panes.append((p.pane_ref, p.pane_id, idle_secs))

        if not idle_panes:
            return f"No idle relay panes to reap. Total: {total}"

        # Sort by idle_secs descending (reap longest-idle first)
        idle_panes.sort(key=lambda x: x[2], reverse=True)

        reaped = 0
        messages = []
        for pane_ref, pane_id, idle_secs in idle_panes:
            should_reap = False

            # Condition 1: Over soft limit
            if (total - reaped) > self.MAX_TOTAL_PANES:
                should_reap = True

            # Condition 2: Idle beyond standby timeout AND total > half capacity
            if idle_secs >= self.IDLE_STANDBY_TIMEOUT and (total - reaped) > (
                self.MAX_TOTAL_PANES // 2
            ):
                should_reap = True

            if should_reap:
                messages.append(f"Reaping {pane_ref} (idle {idle_secs}s)...")
                self._send_keys(pane_ref, "/exit")
                self._send_enter(pane_ref)
                time.sleep(3)
                self._tmux_ok("kill-pane", "-t", pane_ref)
                self._clear_idle_ts(pane_id)
                # Cache: remove reaped pane
                try:
                    self._cache.remove_pane(pane_id.replace("%", ""))
                except Exception:
                    pass
                reaped += 1

        # Clean up empty relay windows
        for wname in self._list_relay_windows(session):
            n = self._count_panes_in_window(f"{session}:{wname}")
            if n == 0:
                self._tmux_ok("kill-window", "-t", f"{session}:{wname}")
                messages.append(f"Killed empty window {wname}")

        messages.append(f"Reaped {reaped} pane(s). Remaining: {total - reaped}")
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
        pane_id = self._display(pane, "#{pane_id}")
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
    ) -> RelayResult:
        """Core relay execution — pure Python equivalent of relay.sh."""
        if not signal_file:
            signal_file = f"/tmp/relay-py-{int(time.time() * 1000)}-{os.getpid()}.done"
        result_file = signal_file.replace(".done", ".txt")

        # Resolve pane_id
        pane_id = self._display(source, "#{pane_id}")
        if not pane_id:
            raise TmuxRelayError("relay", f"Cannot resolve pane ID for {source}")
        pane_safe = pane_id.replace("%", "")

        # Pre-dispatch: check if prior context is stale for this task
        if command and self._should_clear_context(source, command):
            self._send_keys(source, "/clear")
            self._send_enter(source)
            time.sleep(2)

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

            # Timeout watchdog — kills wait-for if it takes too long
            timed_out = False

            def _timeout_kill():
                nonlocal timed_out
                timed_out = True
                wait_proc.kill()

            timer = threading.Timer(timeout, _timeout_kill)
            timer.start()

            # Phase 1.5: Record cursor position before sending command
            bh = int(self._display(source, "#{history_size}") or "0")
            bc = int(self._display(source, "#{cursor_y}") or "0")
            before_pos = bh + bc

            # Phase 2: Send command
            time.sleep(0.5)  # ensure wait-for is registered
            self._send_keys(source, command)
            time.sleep(0.3)
            self._send_enter(source)
            send_time = int(time.time())

            # Phase 3: Wait for completion signal (ZERO CPU)
            wait_proc.wait()
            timer.cancel()

            done_time = int(time.time())
            elapsed = done_time - send_time

            # Eagerly remove pending file
            pending_file.unlink(missing_ok=True)

            # Check timeout
            if timed_out or wait_proc.returncode != 0:
                Path(signal_file).write_text(
                    f"TIMEOUT after {timeout}s waiting for command completion in {source}"
                )
                # Cache: mark pane as idle + result as timeout
                try:
                    self._cache.set_pane(pane_safe, source, "idle", pane_id)
                    self._cache.set_result(
                        signal_file, status="timeout", elapsed=f"{elapsed}s", pane=source
                    )
                except Exception:
                    pass
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
            ah = int(self._display(source, "#{history_size}") or "0")
            ac = int(self._display(source, "#{cursor_y}") or "0")
            after_pos = ah + ac
            new_lines = after_pos - before_pos

            # Clamp: at least 1, at most extract_lines
            new_lines = max(1, min(new_lines, extract_lines))

            start_line = before_pos - ah
            captured = (
                self._tmux_ok("capture-pane", "-t", source, "-p", "-S", str(start_line)) or ""
            )
            Path(result_file).write_text(captured)

            # Phase 5: Forward to target pane (skipped in no_forward mode)
            if not no_forward and target:
                if summary_mode:
                    lines = captured.splitlines()
                    summary_lines = lines[:40] if len(lines) > 40 else lines
                    summary_text = "\n".join(summary_lines[:38])
                    self._send_keys(target, f"[Relay from {source}] 結果摘要：")
                    self._send_enter(target)
                    for line in summary_text.splitlines():
                        if line.strip():
                            self._send_keys(target, line)
                            self._send_enter(target)
                else:
                    self._send_keys(target, f"[Relay from {source}] 完整結果已存至 {result_file}")
                    self._send_enter(target)
                    self._send_keys(target, f"可用 cat {result_file} 查看")
                    self._send_enter(target)

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

            # Cache: mark pane idle + cache result
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
            # Ensure pending file is always removed
            pending_file.unlink(missing_ok=True)

    # ================================================================
    # Public relay operations
    # ================================================================

    def run(
        self,
        command: str,
        timeout: int | None = None,
        max_lines: int = 200,
    ) -> RelayResult:
        """Blocking relay: acquire pane -> send command -> wait -> return result."""
        timeout = timeout or self.default_timeout

        # 1. Acquire a pane
        panes = self.acquire(1)
        if not panes:
            raise TmuxRelayError("run", "Failed to acquire relay pane. Is tmux running?")
        pane = panes[0]

        # 2. Recycle if busy
        st = self._pane_status(pane)
        if st.startswith("busy"):
            self.recycle(pane)

        # 3. Execute relay
        result = self._relay_execute(
            source=pane,
            command=command,
            timeout=timeout,
            extract_lines=max_lines,
            no_forward=True,
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
    ) -> list[dict[str, str]]:
        """Fire-and-forget dispatch. Returns list of {pane, signal_file, pid}."""
        timeout = timeout or self.default_timeout
        panes = self.acquire(count)
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

            # Cache: pre-mark as busy:relay
            pane_id_raw = self._display(pane, "#{pane_id}")
            if pane_id_raw:
                try:
                    self._cache.set_pane(
                        pane_id_raw.replace("%", ""),
                        pane,
                        "busy:relay",
                        pane_id_raw,
                        signal_file=signal_file,
                    )
                except Exception:
                    pass

            # Run relay in background thread
            t = threading.Thread(
                target=self._relay_execute,
                kwargs={
                    "source": pane,
                    "command": command,
                    "timeout": timeout,
                    "signal_file": signal_file,
                    "no_forward": True,
                },
                daemon=True,
            )
            t.start()

            dispatched.append(
                {
                    "pane": pane,
                    "signal_file": signal_file,
                    "pid": str(os.getpid()),
                    "thread": t.name,
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

    def __repr__(self) -> str:
        return f"TmuxRelayClient(claude_bin={self.claude_bin!r})"
