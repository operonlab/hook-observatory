"""Session Archiver SDK -- wraps the session-archiver CLI via subprocess.

Session Archiver is a CLI-first station for Claude Code session lifecycle
management: scan, score, archive, thaw, status, and semantic search.

Usage:
    from workshop.clients.session_archiver import SessionArchiverClient

    client = SessionArchiverClient()

    # Scan sessions
    result = client.scan()

    # Score sessions
    scores = client.score(top=5)

    # Archive (dry-run)
    result = client.archive()

    # Search archived sessions
    results = client.search("refactoring auth module")
"""

import json
import os
import subprocess


class SessionArchiverError(Exception):
    """Raised when the session-archiver CLI returns a non-zero exit code."""

    def __init__(self, message: str, returncode: int = 1):
        self.returncode = returncode
        super().__init__(message)


class SessionArchiverClient:
    """Session Archiver SDK -- wraps the CLI via subprocess.

    The session-archiver CLI is a uv-managed package with its own venv.
    All commands support --json for machine-readable output.

    Args:
        cli_path: Path to session-archiver entry point directory.
            Defaults to SESSION_ARCHIVER_DIR env or standard location.
        python: Python interpreter path (unused -- runs via uv).
        default_timeout: Default subprocess timeout in seconds.
    """

    def __init__(
        self,
        cli_path: str | None = None,
        default_timeout: int = 120,
    ):
        self.cli_dir = cli_path or os.environ.get(
            "SESSION_ARCHIVER_DIR",
            os.path.expanduser("~/workshop/stations/session-archiver"),
        )
        self._uv = os.environ.get("UV_PATH", "/opt/homebrew/bin/uv")
        self._default_timeout = default_timeout

    def _run(self, *args: str, timeout: int | None = None) -> dict:
        """Run session-archiver CLI with --json and return parsed output."""
        t = timeout or self._default_timeout
        cmd = [self._uv, "run", "--directory", self.cli_dir, "session-archiver", *args, "--json"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t,
            )
        except subprocess.TimeoutExpired as e:
            raise SessionArchiverError(
                f"Timeout after {t}s: session-archiver {' '.join(args)}",
                returncode=-1,
            ) from e
        except FileNotFoundError as e:
            raise SessionArchiverError(
                f"uv not found: {self._uv} (dir: {self.cli_dir})",
                returncode=-1,
            ) from e

        if result.returncode != 0:
            msg = result.stderr.strip() or f"Exit code {result.returncode}"
            raise SessionArchiverError(msg, result.returncode)

        # Parse JSON output
        stdout = result.stdout.strip()
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # Return raw output wrapped in a dict
            return {"raw_output": stdout}

    # ======================== Commands ========================

    def scan(self, session_id: str | None = None) -> dict:
        """Scan sessions and update DB index.

        Args:
            session_id: If provided, scan only this session (fast path).

        Returns:
            Dict with scanned count, upserted count, timestamp.
        """
        args = ["scan"]
        if session_id:
            args.extend(["--session-id", session_id])
        return self._run(*args)

    def score(self, top: int = 0) -> dict:
        """Display session scores.

        Args:
            top: Show only top N sessions. 0 means all.

        Returns:
            List of session score dicts.
        """
        args = ["score"]
        if top > 0:
            args.extend(["--top", str(top)])
        return self._run(*args)

    def archive(
        self,
        execute: bool = False,
        threshold: int | None = None,
        summarize: bool = False,
        embed: bool = False,
    ) -> dict:
        """Archive sessions based on score threshold.

        Args:
            execute: Actually archive (default is dry-run).
            threshold: Score threshold (default from config).
            summarize: Generate LLM summaries before archiving.
            embed: Generate embeddings for summaries.

        Returns:
            Dict with mode, threshold, candidates, archived count, details.
        """
        args = ["archive"]
        if execute:
            args.append("--execute")
        if threshold is not None:
            args.extend(["--threshold", str(threshold)])
        if summarize:
            args.append("--summarize")
        if embed:
            args.append("--embed")
        return self._run(*args, timeout=300)

    def thaw(self, session_id: str) -> dict:
        """Restore an archived session.

        Args:
            session_id: Full or partial session ID (min 8 chars).

        Returns:
            Dict with session_id, restored_to, resume_command.
        """
        # thaw doesn't support --json natively, handle output
        t = self._default_timeout
        cmd = [
            self._uv,
            "run",
            "--directory",
            self.cli_dir,
            "session-archiver",
            "thaw",
            session_id,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
        except subprocess.TimeoutExpired as e:
            raise SessionArchiverError(
                f"Timeout after {t}s: session-archiver thaw {session_id}",
                returncode=-1,
            ) from e

        if result.returncode != 0:
            msg = result.stderr.strip() or f"Exit code {result.returncode}"
            raise SessionArchiverError(msg, result.returncode)

        return {"status": "ok", "output": result.stdout.strip()}

    def status(self) -> dict:
        """Show archive statistics.

        Returns:
            Dict with hot/cold/frozen counts, sizes, compression ratio, DB status.
        """
        return self._run("status")

    def search(self, query: str, limit: int = 10) -> dict:
        """Search archived sessions by summary (semantic + ILIKE fallback).

        Args:
            query: Search query string.
            limit: Max number of results.

        Returns:
            List of matching session dicts.
        """
        return self._run("search", query, "--limit", str(limit))

    # ======================== Convenience ========================

    def is_available(self) -> bool:
        """Check if the session-archiver CLI is accessible."""
        try:
            self.status()
            return True
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("health check failed: %s", e)
            return False

    def __repr__(self) -> str:
        return f"SessionArchiverClient(cli_dir={self.cli_dir!r})"
