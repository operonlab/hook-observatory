"""Pane history via tmux pipe-pane + pyte virtual terminal emulation.

Captures ALL pane output (including alternate screen) by tapping into
the raw byte stream before it reaches the terminal buffer. Uses pyte
to emulate the terminal and extract scrolled-off lines into a ring buffer.
"""

import asyncio
import logging
from collections import deque
from pathlib import Path

import pyte

logger = logging.getLogger("tmux-webui")

# Max lines to keep in the history ring buffer per pane
_DEFAULT_HISTORY_SIZE = 5000


def _chars_to_text(char_dict: dict) -> str:
    """Convert a pyte history line (dict of Char) to plain text."""
    if not char_dict:
        return ""
    max_col = max(char_dict.keys())
    return "".join(
        char_dict.get(i, pyte.screens.Char(" ")).data for i in range(max_col + 1)
    ).rstrip()


class PaneHistory:
    """Manages scrollback history for a single tmux pane using pipe-pane + pyte."""

    def __init__(self, pane_target: str, cols: int = 80, rows: int = 24):
        self.pane_target = pane_target
        self.cols = cols
        self.rows = rows

        # pyte virtual terminal
        self.screen = pyte.HistoryScreen(cols, rows, history=_DEFAULT_HISTORY_SIZE)
        self.screen.set_mode(pyte.modes.LNM)  # auto line feed
        self.stream = pyte.Stream(self.screen)

        # Accumulated history lines (plain text)
        self.history: deque[str] = deque(maxlen=_DEFAULT_HISTORY_SIZE)
        self._prev_history_len = 0

        # Snapshot-based history: captures in-place repainting (TUI apps)
        self._last_snapshot: list[str] = []
        self._snapshot_interval = 1.0  # seconds

        # pipe-pane state
        self._pipe_proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._snapshot_task: asyncio.Task | None = None
        self._active = False

    async def start(self) -> bool:
        """Start pipe-pane and begin reading output."""
        if self._active:
            return True

        # pipe-pane sends pane output to a raw log file
        safe_name = self.pane_target.replace(":", "-").replace(".", "-")
        raw_path = f"/tmp/tmux-webui-pipe-{safe_name}.raw"  # noqa: S108
        proc = await asyncio.create_subprocess_exec(
            "tmux", "pipe-pane", "-t", self.pane_target,
            "-o", f"cat >> {raw_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Tail the raw file and feed into pyte
        Path(raw_path).touch()  # noqa: ASYNC240
        self._pipe_proc = await asyncio.create_subprocess_exec(
            "tail", "-f", raw_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        self._active = True
        self._reader_task = asyncio.create_task(self._read_loop())
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        logger.info("PaneHistory started for %s", self.pane_target)
        return True

    async def _read_loop(self) -> None:
        """Continuously read pipe-pane output and feed into pyte."""
        assert self._pipe_proc and self._pipe_proc.stdout
        try:
            while self._active:
                data = await self._pipe_proc.stdout.read(4096)
                if not data:
                    await asyncio.sleep(0.1)
                    continue

                # Feed raw bytes into pyte
                try:
                    self.stream.feed(data.decode("utf-8", errors="replace"))
                except Exception as e:
                    logger.debug("pyte feed error (non-fatal): %s", e)

                # Extract any new history lines from pyte
                self._flush_history()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("PaneHistory read loop error: %s", e)

    def _flush_history(self) -> None:
        """Move new lines from pyte's history into our ring buffer."""
        current_len = len(self.screen.history.top)
        if current_len > self._prev_history_len:
            new_lines = list(self.screen.history.top)[self._prev_history_len :]
            for char_dict in new_lines:
                text = _chars_to_text(char_dict)
                self.history.append(text)
            self._prev_history_len = current_len

    async def _snapshot_loop(self) -> None:
        """Periodically snapshot the pane via tmux capture-pane.

        This captures the CURRENT visible content regardless of alternate screen
        state. By diffing against the previous snapshot, we accumulate lines that
        appeared on screen over time — building a scrollable history.
        """
        try:
            while self._active:
                await asyncio.sleep(self._snapshot_interval)
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "tmux",
                        "capture-pane",
                        "-t",
                        self.pane_target,
                        "-p",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                    if not stdout:
                        continue
                    current = [
                        line.rstrip()
                        for line in stdout.decode("utf-8", errors="replace").splitlines()
                    ]
                except (TimeoutError, Exception):  # noqa: S112
                    continue

                if current == self._last_snapshot:
                    continue

                # Append lines that are NEW (not in previous snapshot)
                prev_set = set(self._last_snapshot)
                new_lines = [ln for ln in current if ln and ln not in prev_set]
                for line in new_lines:
                    self.history.append(line)
                self._last_snapshot = current
        except asyncio.CancelledError:
            pass

    def get_history(self, offset: int = 0, limit: int = 50) -> list[str]:
        """Get history lines. offset=0 is the most recent scrolled-off line.

        Returns lines in chronological order (oldest first).
        """
        total = len(self.history)
        if total == 0 or offset >= total:
            return []
        # offset from the END (most recent)
        start = max(0, total - offset - limit)
        end = total - offset
        return list(self.history)[start:end]

    def get_total_lines(self) -> int:
        """Total number of history lines available."""
        return len(self.history)

    async def stop(self) -> None:
        """Stop pipe-pane and cleanup."""
        self._active = False

        for task in (self._reader_task, self._snapshot_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reader_task = None
        self._snapshot_task = None

        if self._pipe_proc:
            self._pipe_proc.kill()
            await self._pipe_proc.communicate()
            self._pipe_proc = None

        # Stop tmux pipe-pane
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "pipe-pane",
            "-t",
            self.pane_target,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

        logger.info(
            "PaneHistory stopped for %s (captured %d lines)",
            self.pane_target,
            len(self.history),
        )


class PaneHistoryManager:
    """Manages PaneHistory instances for all active panes in a session."""

    def __init__(self) -> None:
        self._histories: dict[str, PaneHistory] = {}

    async def ensure_started(self, pane_target: str, cols: int = 80, rows: int = 24) -> PaneHistory:
        """Get or create a PaneHistory for the given pane target."""
        if pane_target not in self._histories:
            ph = PaneHistory(pane_target, cols, rows)
            await ph.start()
            self._histories[pane_target] = ph
        return self._histories[pane_target]

    def get(self, pane_target: str) -> PaneHistory | None:
        """Get existing PaneHistory, or None."""
        return self._histories.get(pane_target)

    async def stop(self, pane_target: str) -> None:
        """Stop and remove a PaneHistory."""
        ph = self._histories.pop(pane_target, None)
        if ph:
            await ph.stop()

    async def stop_all(self) -> None:
        """Stop all PaneHistory instances."""
        for ph in self._histories.values():
            await ph.stop()
        self._histories.clear()
