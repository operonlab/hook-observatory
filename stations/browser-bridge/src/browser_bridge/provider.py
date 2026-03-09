"""BrowserProvider — abstract base for web service automation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .safari import SafariBackend

if TYPE_CHECKING:
    from .models import BridgeResponse


@dataclass
class ProviderMeta:
    """Static metadata about a provider."""

    name: str
    base_url: str
    description: str = ""
    supports_conversation: bool = True
    headed: bool = True  # Most sites need headed mode for anti-bot
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
    _backend: SafariBackend = SafariBackend()

    @abstractmethod
    async def ensure_ready(self, session_id: str, pw_profile: str) -> bool:
        """Ensure the page is ready (logged in, loaded).

        Args:
            session_id: session identifier (unused for Safari backend)
            pw_profile: profile path (unused for Safari backend)

        Returns:
            True if ready, False if setup failed
        """

    @abstractmethod
    async def send_prompt(self, session_id: str, pw_profile: str, prompt: str) -> None:
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

    async def _run_js(self, session_id: str, pw_profile: str, js_code: str) -> str:
        """Execute JavaScript in Safari's current tab and return result as string.

        session_id and pw_profile are kept for interface compatibility but unused.
        Safari's do JavaScript returns raw strings — no JSON parsing needed.
        """
        return await self._backend.run_js(js_code)

    async def _navigate(self, session_id: str, pw_profile: str, url: str) -> None:
        """Navigate Safari's current tab to URL.

        session_id, pw_profile, and meta.headed are unused — Safari is always headed.
        """
        await self._backend.navigate(url)

    async def _snapshot(self, session_id: str, pw_profile: str) -> str:
        """Return page body text as a simple snapshot alternative."""
        return await self._backend.run_js("return document.body.innerText.substring(0, 2000)")
