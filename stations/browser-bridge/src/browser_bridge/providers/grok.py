"""Grok provider — automates grok.com chat interface."""
from __future__ import annotations

import asyncio
import logging

from ..provider import BrowserProvider, ProviderMeta
from ..poller import StabilityPoller
from ..selectors import InputResolver, SubmitResolver
from ..extractor import ResultExtractor
from ..models import BridgeResponse

logger = logging.getLogger(__name__)


class GrokProvider(BrowserProvider):
    """Automate Grok (grok.com) web chat.

    Supports both free and SuperGrok accounts.
    Uses Safari/Chrome via Playwright CLI.
    """

    meta = ProviderMeta(
        name="grok",
        base_url="https://grok.com",
        description="xAI Grok chat — text generation via web UI",
        supports_conversation=True,
        input_selectors=[
            "textarea",
            'div[contenteditable="true"]',
            '[data-testid="text-input"]',
            '[role="textbox"]',
        ],
        submit_selectors=[
            'button[aria-label="Send"]',
            'button[data-testid="send-button"]',
        ],
    )

    def __init__(self) -> None:
        self._input_resolver = InputResolver(self.meta.input_selectors)
        self._submit_resolver = SubmitResolver(
            self.meta.submit_selectors,
            text_fallback=["send", "submit", "發送"],
        )
        self._poller = StabilityPoller(interval=2.0, threshold=3, min_change=100)
        self._extractor = ResultExtractor(provider="grok")

    async def ensure_ready(self, session_id: str, pw_profile: str) -> bool:
        """Navigate to grok.com and wait for input to appear."""
        try:
            # Check if already on grok.com
            current_url = await self._run_js(
                session_id, pw_profile,
                "return window.location.href"
            )

            if "grok.com" not in current_url:
                await self._navigate(session_id, pw_profile, self.meta.base_url)
                await asyncio.sleep(4)

            # Wait for input element
            resolved = await self._input_resolver.resolve(
                lambda js: self._run_js(session_id, pw_profile, js),
                timeout=20,
            )
            return resolved is not None

        except Exception as e:
            logger.error(f"Grok ensure_ready failed: {e}")
            return False

    async def send_prompt(
        self, session_id: str, pw_profile: str, prompt: str
    ) -> None:
        """Type prompt and click send."""
        run_js = lambda js: self._run_js(session_id, pw_profile, js)

        # Resolve and type into input
        resolved = await self._input_resolver.resolve(run_js, timeout=10)
        if not resolved:
            raise RuntimeError("Could not find Grok input element")

        success = await self._input_resolver.type_text(run_js, prompt, resolved)
        if not success:
            raise RuntimeError("Failed to type text into Grok input")

        await asyncio.sleep(0.5)

        # Click send
        clicked = await self._submit_resolver.click(
            run_js, input_selector=resolved.selector
        )
        if not clicked:
            logger.warning("Submit click may have failed, continuing anyway")

    async def wait_and_extract(
        self,
        session_id: str,
        pw_profile: str,
        prompt: str,
        timeout: int = 120,
    ) -> BridgeResponse:
        """Poll DOM until Grok's response stabilizes, then extract."""
        run_js = lambda js: self._run_js(session_id, pw_profile, js)

        # Get baseline content before response
        baseline = await run_js("return document.body.innerText")

        # Poll for stability
        result = await self._poller.poll(
            fetch_content=lambda: run_js("return document.body.innerText"),
            timeout=timeout,
            baseline=baseline,
        )

        # Extract response
        response_text = self._extractor.extract(result.content, prompt)

        return BridgeResponse(
            status="ok" if result.stable else "timeout",
            provider="grok",
            response=response_text,
            elapsed=result.elapsed,
        )
