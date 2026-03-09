"""BrowserProvider — abstract base for web service automation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import BridgeResponse


@dataclass
class ProviderMeta:
    """Static metadata about a provider."""
    name: str
    base_url: str
    description: str = ""
    supports_conversation: bool = True
    input_selectors: list[str] = field(default_factory=list)
    submit_selectors: list[str] = field(default_factory=list)


class BrowserProvider(ABC):
    """Each web service's automation knowledge encapsulated as a provider.

    A provider knows:
    - What URL to navigate to
    - How to find the input element (multiple selectors for resilience)
    - How to submit a prompt
    - How to detect response completion
    - How to extract and clean the response
    """

    meta: ProviderMeta

    @abstractmethod
    async def ensure_ready(self, session_id: str, pw_profile: str) -> bool:
        """Ensure the page is ready (logged in, loaded).

        Args:
            session_id: Playwright CLI session ID
            pw_profile: Path to Playwright profile directory

        Returns:
            True if ready, False if setup failed
        """

    @abstractmethod
    async def send_prompt(
        self, session_id: str, pw_profile: str, prompt: str
    ) -> None:
        """Type prompt into input and submit.

        Should use SelectorResolver for resilient element finding
        and execCommand('insertText') for React-compatible input.
        """

    @abstractmethod
    async def wait_and_extract(
        self,
        session_id: str,
        pw_profile: str,
        prompt: str,
        timeout: int = 120,
    ) -> BridgeResponse:
        """Wait for response completion and extract result.

        Should use StabilityPoller for completion detection
        and ResultExtractor for cleaning UI artifacts.
        """

    async def new_conversation(self, session_id: str, pw_profile: str) -> None:
        """Start a new conversation. Default: navigate to base_url."""
        await self._navigate(session_id, pw_profile, self.meta.base_url)

    async def cleanup(self, session_id: str, pw_profile: str) -> None:
        """Provider-specific cleanup. Override if needed."""

    # --- Helpers for subclasses ---

    async def _run_js(
        self, session_id: str, pw_profile: str, js_code: str
    ) -> str:
        """Execute JavaScript in current page via Playwright CLI run-code."""
        import asyncio
        cmd = [
            "npx", "@playwright/cli",
            "--profile", pw_profile,
            f"-s={session_id}",
            "run-code", f'async (page) => {{ return await page.evaluate(() => {{ {js_code} }}); }}'
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"JS execution failed: {stderr.decode()[:200]}")
        return stdout.decode().strip()

    async def _navigate(
        self, session_id: str, pw_profile: str, url: str
    ) -> None:
        """Navigate to URL via Playwright CLI."""
        import asyncio
        cmd = [
            "npx", "@playwright/cli",
            "--profile", pw_profile,
            f"-s={session_id}",
            "open", url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def _snapshot(self, session_id: str, pw_profile: str) -> str:
        """Take accessibility snapshot of current page."""
        import asyncio
        cmd = [
            "npx", "@playwright/cli",
            "--profile", pw_profile,
            f"-s={session_id}",
            "snapshot",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()
