"""Grok provider — automates grok.com chat interface."""

from __future__ import annotations

import asyncio
import logging

from ..extractor import ResultExtractor
from ..models import BridgeResponse
from ..poller import StabilityPoller
from ..provider import BrowserProvider, ProviderMeta
from ..selectors import InputResolver, SubmitResolver

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
            'div[contenteditable="true"]',
            ".ProseMirror",
            '[role="textbox"]',
            '[data-testid="text-input"]',
        ],
        submit_selectors=[
            'button[aria-label="提交"]',
            'button[aria-label="Submit"]',
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
        self._poller = StabilityPoller(interval=2.0, threshold=3)
        self._extractor = ResultExtractor(provider="grok")

    async def ensure_ready(self, session_id: str, pw_profile: str) -> bool:
        """Navigate to grok.com, handle Cloudflare, then confirm input.

        Cloudflare challenge strategy:
        1. Open page, wait 8s for auto-resolve
        2. Check if still on challenge page → reload + wait (up to 2 retries)
        3. Poll for input element with generous timeout
        """
        run_js = lambda js: self._run_js(session_id, pw_profile, js)

        try:
            await self._navigate(session_id, pw_profile, self.meta.base_url)
            await asyncio.sleep(8)

            # Retry loop for Cloudflare challenge
            for attempt in range(3):
                try:
                    title = await run_js("return document.title")
                except Exception:
                    title = ""

                if "請稍候" in title or "Just a moment" in title:
                    logger.info(
                        f"Cloudflare challenge active (attempt {attempt + 1}), reloading..."
                    )
                    await run_js(
                        "return await (async () => { location.reload(); return 'reloading'; })()"
                    )
                    await asyncio.sleep(8)
                else:
                    break

            # Wait for input element (TipTap ProseMirror contenteditable)
            resolved = await self._input_resolver.resolve(run_js, timeout=30)
            if resolved:
                logger.info(f"Grok ready: input found via {resolved.selector}")
            return resolved is not None

        except Exception as e:
            logger.error(f"Grok ensure_ready failed: {e}")
            return False

    async def send_prompt(self, session_id: str, pw_profile: str, prompt: str) -> None:
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
        clicked = await self._submit_resolver.click(run_js, input_selector=resolved.selector)
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

        # Get baseline content (first 8000 chars to avoid dynamic footer noise)
        baseline = await run_js("return document.body.innerText.substring(0,8000)")

        # Poll for stability — normalize extracts just the response (strips sidebar + UI noise)
        result = await self._poller.poll(
            fetch_content=lambda: run_js("return document.body.innerText.substring(0,8000)"),
            timeout=timeout,
            baseline=baseline,
            normalize=lambda text: self._extractor.extract(text, prompt),
        )

        # Fetch full body for extraction (poller used substring for stability)
        full_body = await run_js("return document.body.innerText")

        # Extract response from full body
        response_text = self._extractor.extract(full_body, prompt)

        return BridgeResponse(
            status="ok" if result.stable else "timeout",
            provider="grok",
            response=response_text,
            elapsed=result.elapsed,
        )
