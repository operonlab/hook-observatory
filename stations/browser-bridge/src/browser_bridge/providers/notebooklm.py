"""NotebookLM provider — automates Google NotebookLM web interface."""

from __future__ import annotations

import asyncio
import logging

from ..extractor import ResultExtractor
from ..models import BridgeResponse
from ..poller import StabilityPoller
from ..provider import BrowserProvider, ProviderMeta
from ..selectors import InputResolver, SubmitResolver

logger = logging.getLogger(__name__)


class NotebookLMProvider(BrowserProvider):
    """Automate Google NotebookLM (notebooklm.google.com).

    Supports chat within an existing notebook.
    Requires user to be logged into Google account.
    """

    meta = ProviderMeta(
        name="notebooklm",
        base_url="https://notebooklm.google.com",
        description="Google NotebookLM — RAG-powered chat with your sources",
        supports_conversation=True,
        input_selectors=[
            'textarea[aria-label*="query"]',
            'textarea[placeholder*="Ask"]',
            "textarea",
            'div[contenteditable="true"]',
            '[role="textbox"]',
        ],
        submit_selectors=[
            'button[aria-label="Send"]',
            'button[aria-label*="submit"]',
            'button[data-testid="send-button"]',
        ],
    )

    def __init__(self) -> None:
        self._input_resolver = InputResolver(self.meta.input_selectors)
        self._submit_resolver = SubmitResolver(
            self.meta.submit_selectors,
            text_fallback=["send", "submit", "ask"],
        )
        self._poller = StabilityPoller(interval=2.5, threshold=3)
        self._extractor = ResultExtractor(provider="notebooklm")

    async def ensure_ready(self, session_id: str, pw_profile: str) -> bool:
        """Check that NotebookLM is loaded and a notebook is open."""
        try:
            current_url = await self._run_js(session_id, pw_profile, "return window.location.href")

            if "notebooklm.google.com" not in current_url:
                await self._navigate(session_id, pw_profile, self.meta.base_url)
                await asyncio.sleep(5)

            # Wait for input to appear (indicates notebook is open)
            resolved = await self._input_resolver.resolve(
                lambda js: self._run_js(session_id, pw_profile, js),
                timeout=15,
            )

            if not resolved:
                logger.warning(
                    "NotebookLM input not found — user may need to open a notebook first"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"NotebookLM ensure_ready failed: {e}")
            return False

    async def send_prompt(self, session_id: str, pw_profile: str, prompt: str) -> None:
        """Type prompt and submit in NotebookLM chat."""
        run_js = lambda js: self._run_js(session_id, pw_profile, js)

        resolved = await self._input_resolver.resolve(run_js, timeout=10)
        if not resolved:
            raise RuntimeError("Could not find NotebookLM input element")

        success = await self._input_resolver.type_text(run_js, prompt, resolved)
        if not success:
            raise RuntimeError("Failed to type text into NotebookLM input")

        await asyncio.sleep(0.5)

        clicked = await self._submit_resolver.click(run_js, input_selector=resolved.selector)
        if not clicked:
            logger.warning("Submit click may have failed")

    async def wait_and_extract(
        self,
        session_id: str,
        pw_profile: str,
        prompt: str,
        timeout: int = 120,
    ) -> BridgeResponse:
        """Poll DOM until NotebookLM response stabilizes."""
        run_js = lambda js: self._run_js(session_id, pw_profile, js)

        baseline = await run_js("return document.body.innerText")

        result = await self._poller.poll(
            fetch_content=lambda: run_js("return document.body.innerText"),
            timeout=timeout,
            baseline=baseline,
        )

        response_text = self._extractor.extract(result.content, prompt)

        return BridgeResponse(
            status="ok" if result.stable else "timeout",
            provider="notebooklm",
            response=response_text,
            elapsed=result.elapsed,
        )
