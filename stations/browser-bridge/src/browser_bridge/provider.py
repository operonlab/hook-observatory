"""BrowserProvider — abstract base for web service automation."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .playwright_backend import PlaywrightBackend
from .safari import SafariBackend

if TYPE_CHECKING:
    from .models import BridgeResponse

# Environment variable to select backend: "safari" (default) or "playwright"
_BACKEND_TYPE = os.environ.get("BRIDGE_BACKEND", "safari")


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
    _safari: SafariBackend = SafariBackend()

    def _backend(self, session_id: str, pw_profile: str) -> SafariBackend | PlaywrightBackend:
        """Return the configured backend.

        Playwright backend needs session params; Safari ignores them.
        A new PlaywrightBackend instance is created per call (lightweight dataclass).
        """
        if _BACKEND_TYPE == "playwright":
            return PlaywrightBackend(session_id=session_id, profile_path=pw_profile)
        return self._safari

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
        timeout: int = 120,  # noqa: ASYNC109
    ) -> BridgeResponse:
        """Wait for response completion and extract result.

        Should use StabilityPoller for completion detection
        and ResultExtractor for cleaning UI artifacts.
        """

    async def new_conversation(self, session_id: str, pw_profile: str) -> None:
        """Start a new conversation. Default: navigate to base_url."""
        await self._navigate(session_id, pw_profile, self.meta.base_url)

    async def cleanup(self, session_id: str, pw_profile: str) -> None:  # noqa: B027
        """Provider-specific cleanup. Override if needed."""

    # --- Helpers for subclasses ---

    async def _run_js(self, session_id: str, pw_profile: str, js_code: str) -> str:
        """Execute JavaScript via the configured backend and return result as string."""
        return await self._backend(session_id, pw_profile).run_js(js_code)

    async def _navigate(self, session_id: str, pw_profile: str, url: str) -> None:
        """Navigate to URL via the configured backend."""
        await self._backend(session_id, pw_profile).navigate(url)

    async def _snapshot(self, session_id: str, pw_profile: str) -> str:
        """Return page body text as a simple snapshot alternative."""
        js = "return document.body.innerText.substring(0, 2000)"
        if _BACKEND_TYPE != "playwright":
            # Safari: `return` keyword is not required
            js = "document.body.innerText.substring(0, 2000)"
        return await self._backend(session_id, pw_profile).run_js(js)
