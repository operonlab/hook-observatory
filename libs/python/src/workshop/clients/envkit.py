"""Envkit SDK -- wraps the envkit CLI via subprocess (no HTTP server).

Envkit is a CLI-first station for macOS environment snapshot, backup,
verify, diff, list, and bootstrap operations.

Usage:
    from workshop.clients.envkit import EnvkitClient

    client = EnvkitClient()

    # Snapshot
    yaml_output = client.snapshot()

    # List by category
    items = client.list_items("brew")

    # Verify against snapshot
    diff_output = client.verify("/path/to/snapshot.yaml")
"""

import os
import subprocess


class EnvkitError(Exception):
    """Raised when the envkit CLI returns a non-zero exit code."""

    def __init__(self, message: str, returncode: int = 1):
        self.returncode = returncode
        super().__init__(message)


class EnvkitClient:
    """Envkit SDK -- wraps the envkit CLI via subprocess.

    Unlike other Workshop SDK clients that wrap HTTP APIs, Envkit has no
    server. The CLI (envkit.py) IS the primary interface, and this SDK
    wraps it via subprocess for programmatic access.

    Args:
        cli_path: Path to envkit.py. Defaults to ENVKIT_CLI env or standard location.
        python: Python interpreter path. Defaults to PYTHON_PATH env or uv-managed python.
        default_timeout: Default subprocess timeout in seconds.
    """

    def __init__(
        self,
        cli_path: str | None = None,
        python: str | None = None,
        default_timeout: int = 60,
    ):
        self.cli_path = cli_path or os.environ.get(
            "ENVKIT_CLI",
            os.path.expanduser("~/workshop/stations/envkit/envkit.py"),
        )
        self._python = python or os.environ.get(
            "PYTHON_PATH", "/Users/joneshong/.local/bin/python3"
        )
        self._default_timeout = default_timeout

    def _run(self, *args: str, timeout: int | None = None) -> str:
        """Run envkit CLI and return stdout."""
        t = timeout or self._default_timeout
        try:
            result = subprocess.run(
                [self._python, self.cli_path, *args],
                capture_output=True,
                text=True,
                timeout=t,
            )
        except subprocess.TimeoutExpired as e:
            raise EnvkitError(f"Timeout after {t}s: envkit {' '.join(args)}", returncode=-1) from e
        except FileNotFoundError as e:
            raise EnvkitError(
                f"CLI not found: {self.cli_path} (python: {self._python})",
                returncode=-1,
            ) from e

        if result.returncode != 0:
            msg = result.stderr.strip() or f"Exit code {result.returncode}"
            raise EnvkitError(msg, result.returncode)
        return result.stdout

    # ======================== Commands ========================

    def snapshot(self, output_file: str | None = None) -> str:
        """Take a full environment snapshot. Returns YAML content.

        Args:
            output_file: Optional path to save the snapshot. If None, returns stdout.
        """
        if output_file:
            self._run("snapshot", "--output", output_file)
            with open(output_file, encoding="utf-8") as f:
                return f.read()
        return self._run("snapshot")

    def verify(self, snapshot_path: str) -> str:
        """Verify current environment against a snapshot.

        Args:
            snapshot_path: Path to the reference snapshot YAML file.

        Returns:
            Diff output (empty string if environment matches).
        """
        try:
            return self._run("verify", snapshot_path)
        except EnvkitError as e:
            # exit code 1 = diffs found (not a real error)
            if e.returncode == 1:
                return str(e)
            raise

    def diff(self, file_a: str, file_b: str) -> str:
        """Compare two snapshot files.

        Args:
            file_a: Path to first snapshot YAML file.
            file_b: Path to second snapshot YAML file.
        """
        return self._run("diff", file_a, file_b)

    def list_items(self, category: str = "all") -> str:
        """List installed items by category.

        Args:
            category: One of: all, brew, cask, python, node, shell, docker, apps, cli.
        """
        return self._run("list", category)

    def backup(self, output_dir: str = "configs/") -> str:
        """Backup Tier 1-2 config files.

        Args:
            output_dir: Directory to write backups to.
        """
        return self._run("backup", "--output-dir", output_dir)

    def bootstrap(
        self,
        snapshot_path: str,
        from_phase: int | None = None,
        to_phase: int | None = None,
        dry_run: bool = False,
    ) -> str:
        """Restore environment from a snapshot.

        Args:
            snapshot_path: Path to the snapshot YAML file to restore from.
            from_phase: Start from phase N (default: 2).
            to_phase: Stop at phase N (default: 9).
            dry_run: Preview without making changes.
        """
        args: list[str] = ["bootstrap", snapshot_path]
        if from_phase is not None:
            args.extend(["--from", str(from_phase)])
        if to_phase is not None:
            args.extend(["--to", str(to_phase)])
        if dry_run:
            args.append("--dry-run")
        return self._run(*args, timeout=300)

    # ======================== Convenience ========================

    def is_available(self) -> bool:
        """Check if the envkit CLI is accessible."""
        try:
            self._run("list", "all", timeout=15)
            return True
        except (EnvkitError, Exception):
            return False

    def __repr__(self) -> str:
        return f"EnvkitClient(cli_path={self.cli_path!r})"
