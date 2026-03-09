"""SafariBackend — macOS osascript-based Safari browser automation.

Uses AppleScript to control Safari via `do JavaScript` command.
Requires: Safari > Settings > Developer > Allow JavaScript from Apple Events

Design: Swappable backend — can be replaced with PlaywrightBackend later.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_CHILD_ENV = {
    **os.environ,
    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + os.environ.get("PATH", ""),
}


class SafariBackend:
    """Browser automation via Safari osascript.

    All JS execution goes through Safari's `do JavaScript` AppleScript command.
    Complex JS is written to temp files to avoid shell/AppleScript escaping issues.

    Tab targeting: navigate() finds or creates a tab for the URL's domain.
    Subsequent run_js() calls operate on the last targeted tab.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        # Track which window/tab we're operating on (1-indexed AppleScript)
        self._win: int = 0
        self._tab: int = 0

    def _tab_ref(self) -> str:
        """AppleScript reference to the targeted tab."""
        if self._win and self._tab:
            return f"tab {self._tab} of window {self._win}"
        return "current tab of front window"

    async def run_js(self, js_code: str) -> str:
        """Execute JavaScript in the targeted Safari tab.

        Automatically strips leading ``return`` / ``return await`` keywords
        because Safari's ``do JavaScript`` evaluates expressions, not function
        bodies (unlike Playwright's ``page.evaluate``).
        """
        code = js_code.strip()
        # Safari do JavaScript evaluates expressions — strip return keywords
        if code.startswith("return await "):
            code = code[len("return await ") :]
        elif code.startswith("return "):
            code = code[len("return ") :]

        # Write JS to temp file to avoid escaping hell
        fd, js_file = tempfile.mkstemp(suffix=".js", prefix="bridge-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(code)

            ref = self._tab_ref()
            applescript = (
                f'tell application "Safari" to do JavaScript (read POSIX file "{js_file}") in {ref}'
            )
            return await self._osa(applescript)
        finally:
            try:
                os.unlink(js_file)
            except OSError:
                pass

    async def navigate(self, url: str) -> None:
        """Navigate to URL, finding or creating a tab for the URL's domain."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc  # e.g. "grok.com"

        # Search all windows/tabs for a matching domain
        find_script = f'''
tell application "Safari"
    set winCount to count of windows
    repeat with w from 1 to winCount
        set tabCount to count of tabs of window w
        repeat with t from 1 to tabCount
            set tabURL to URL of tab t of window w
            if tabURL contains "{domain}" then
                return (w as text) & "," & (t as text)
            end if
        end repeat
    end repeat
    return "0,0"
end tell
'''
        result = await self._osa(find_script)
        parts = result.split(",")
        if len(parts) == 2 and parts[0] != "0":
            self._win = int(parts[0])
            self._tab = int(parts[1])
            logger.info(f"Found existing tab: window {self._win}, tab {self._tab}")
            # Navigate existing tab to exact URL
            ref = self._tab_ref()
            await self._osa(f'tell application "Safari" to set URL of {ref} to "{url}"')
        else:
            # No matching tab — create new one in front window
            logger.info(f"Creating new tab for {url}")
            await self._osa(
                f'tell application "Safari" to make new document with properties {{URL:"{url}"}}'
            )
            # New document becomes window 1
            self._win = 1
            self._tab = 1

    async def get_title(self) -> str:
        """Get page title of the targeted tab."""
        ref = self._tab_ref()
        return await self._osa(f'tell application "Safari" to get name of {ref}')

    async def get_url(self) -> str:
        """Get page URL of the targeted tab."""
        ref = self._tab_ref()
        return await self._osa(f'tell application "Safari" to get URL of {ref}')

    async def _osa(self, script: str) -> str:
        """Execute AppleScript via osascript subprocess."""
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CHILD_ENV,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except TimeoutError as exc:
            proc.kill()
            raise RuntimeError(f"osascript timeout ({self.timeout}s)") from exc

        if proc.returncode != 0:
            err = stderr.decode()[:200]
            raise RuntimeError(f"osascript failed (rc={proc.returncode}): {err}")

        return stdout.decode().rstrip("\n")
