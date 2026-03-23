"""Playwright CLI wrapper — session management + command execution."""

import subprocess
import uuid

from .config import settings


class PlaywrightSession:
    """Manages a Playwright CLI browser session."""

    def __init__(self, session_id: str | None = None):
        self.sid = session_id or uuid.uuid4().hex[:8]
        self.profile_dir: str | None = None
        self._cli = settings.playwright_cli

    def _run(self, *args: str, timeout: int = 30) -> str:
        cmd_parts = [*self._cli.split(), f"-s={self.sid}", *args]
        if self.profile_dir:
            # Insert --profile before the subcommand args
            idx = next(
                (
                    i
                    for i, a in enumerate(cmd_parts)
                    if a in ("open", "run-code", "screenshot", "close")
                ),
                len(cmd_parts),
            )
            cmd_parts.insert(idx, f"--profile={self.profile_dir}")

        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Playwright CLI error: {result.stderr or result.stdout}")
        if result.stdout.lstrip().startswith("### Error"):
            raise RuntimeError(f"Playwright CLI error: {result.stdout[:500]}")
        return result.stdout

    def open(self, url: str) -> str:
        return self._run("open", url, timeout=30)

    def run_code(self, js_code: str, timeout: int = 60) -> str:
        return self._run("run-code", js_code, timeout=timeout)

    def screenshot(self, full_page: bool = False) -> str:
        args = ["screenshot"]
        if full_page:
            args.append("--full-page")
        return self._run(*args, timeout=15)

    def close(self) -> str:
        try:
            return self._run("close", timeout=10)
        except Exception:
            return ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def create_session() -> PlaywrightSession:
    """Create a session with APFS-cloned profile for isolation."""
    sess = PlaywrightSession()

    profile_src = settings.pw_profile_dir
    if not profile_src:
        # Use default master profile
        profile_src = "~/.playwright-profiles/master"

    import os
    import tempfile

    profile_src = os.path.expanduser(profile_src)
    if os.path.isdir(profile_src):
        tmp = tempfile.mkdtemp(prefix="pw-")
        # APFS clone for zero-cost copy
        subprocess.run(
            ["cp", "-c", "-R", profile_src + "/.", tmp],
            check=False,
            capture_output=True,
        )
        sess.profile_dir = tmp
    return sess


def cleanup_session(sess: PlaywrightSession):
    """Remove cloned profile directory."""
    import shutil

    if sess.profile_dir and sess.profile_dir.startswith("/tmp/pw-"):
        shutil.rmtree(sess.profile_dir, ignore_errors=True)
