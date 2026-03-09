"""PlaywrightBackend — Playwright CLI-based browser automation.

Uses `npx @playwright/cli` subprocess for Chromium automation.
Requires a Playwright CLI session (profile + session ID).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

_CHILD_ENV = {
    **os.environ,
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
    + os.environ.get("PATH", ""),
}


class PlaywrightBackend:
    """Browser automation via Playwright CLI subprocess.

    Unlike SafariBackend, this requires a session_id and profile_path
    for each operation. These are passed via the run_js/navigate methods.

    The `return` keyword is REQUIRED for JS code — Playwright's page.evaluate
    runs code as a function body.
    """

    def __init__(
        self,
        session_id: str = "",
        profile_path: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.session_id = session_id
        self.profile_path = profile_path
        self.timeout = timeout
        # Track win/tab for interface compat with SafariBackend (unused)
        self._win: int = 0
        self._tab: int = 0

    async def run_js(self, js_code: str) -> str:
        """Execute JavaScript via Playwright CLI run-code.

        JS code should use `return` statements — Playwright's page.evaluate
        runs it as a function body. Unlike SafariBackend, we do NOT strip `return`.
        """
        code = js_code.strip()
        # Ensure code has return for page.evaluate (add if missing)
        if not code.startswith("return "):
            code = f"return {code}"

        cmd = [
            "npx",
            "@playwright/cli",
            "--profile",
            self.profile_path,
            f"-s={self.session_id}",
            "run-code",
            f"async (page) => {{ return await page.evaluate(() => {{ {code} }}); }}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CHILD_ENV,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            proc.kill()
            raise RuntimeError(f"Playwright CLI timeout ({self.timeout}s)") from exc

        if proc.returncode != 0:
            raise RuntimeError(f"JS execution failed: {stderr.decode()[:200]}")

        # Parse Playwright CLI output format:
        #   ### Result\n"actual value"\n### Ran Playwright code\n...
        raw = stdout.decode()
        if "### Result" in raw:
            start = raw.index("### Result") + len("### Result")
            end = (
                raw.index("### Ran Playwright code")
                if "### Ran Playwright code" in raw
                else len(raw)
            )
            raw = raw[start:end]
        elif "### Ran Playwright code" in raw:
            raw = raw[: raw.index("### Ran Playwright code")]

        raw = raw.strip()
        # Playwright CLI wraps string results in JSON-encoded quotes.
        # Use json.loads to properly unescape \n, \t, Unicode, etc.
        if raw.startswith('"') and raw.endswith('"'):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return raw.strip('"')
        return raw

    async def navigate(self, url: str) -> None:
        """Navigate via Playwright CLI open command."""
        cmd = [
            "npx",
            "@playwright/cli",
            "--profile",
            self.profile_path,
            f"-s={self.session_id}",
            "open",
            "--headed",
            url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CHILD_ENV,
        )
        await asyncio.wait_for(proc.communicate(), timeout=self.timeout)

    async def get_title(self) -> str:
        """Get current page title."""
        return await self.run_js("return document.title")

    async def get_url(self) -> str:
        """Get current page URL."""
        return await self.run_js("return window.location.href")
