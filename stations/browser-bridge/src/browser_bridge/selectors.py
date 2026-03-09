"""SelectorResolver — multi-selector resilience with fallback chain.

Pattern learned from grok-bridge: third-party UIs change their DOM structure
frequently. Using a single CSS selector is fragile. Instead, maintain a
priority list of selectors and try each in order.

Fallback chain:
1. Try each CSS selector in priority order
2. Fallback: match by text content
3. Last resort: dispatch keyboard event
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResolvedElement:
    """A successfully resolved DOM element."""
    selector: str          # The CSS selector that matched
    method: str            # "css" | "text" | "keyboard"
    tag_name: str = ""     # Element tag (if known)


class SelectorResolver:
    """Resolve DOM elements using multi-selector fallback.

    Args:
        selectors: Ordered list of CSS selectors to try (most stable first)
    """

    def __init__(self, selectors: list[str]) -> None:
        self.selectors = selectors

    async def resolve(
        self,
        run_js: callable,
        timeout: float = 10.0,
    ) -> ResolvedElement | None:
        """Try each selector until one matches.

        Args:
            run_js: Async callable(js_code) -> str that executes JS in browser.
            timeout: Max seconds to wait for any selector to appear.

        Returns:
            ResolvedElement if found, None if all selectors failed.
        """
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            for sel in self.selectors:
                try:
                    result = await run_js(
                        f"(() => {{ const el = document.querySelector('{sel}'); "
                        f"return el ? el.tagName : ''; }})()"
                    )
                    if result and result != "null" and result != "undefined":
                        logger.debug(f"Resolved selector: {sel} -> <{result}>")
                        return ResolvedElement(
                            selector=sel, method="css", tag_name=result
                        )
                except Exception:
                    continue

            await asyncio.sleep(0.5)

        return None

    async def resolve_by_text(
        self,
        run_js: callable,
        text_patterns: list[str],
        tag: str = "button",
    ) -> ResolvedElement | None:
        """Fallback: find element by text content match.

        Args:
            run_js: JS executor.
            text_patterns: Regex patterns to match against element text.
            tag: HTML tag to search (default: "button").

        Returns:
            ResolvedElement if found.
        """
        patterns_js = "|".join(text_patterns)
        js_code = (
            f"(() => {{ const els = [...document.querySelectorAll('{tag}')]; "
            f"const el = els.find(x => /{patterns_js}/i.test("
            f"x.textContent || x.ariaLabel || '')); "
            f"return el ? 'FOUND' : ''; }})()"
        )
        try:
            result = await run_js(js_code)
            if result == "FOUND":
                return ResolvedElement(
                    selector=f"{tag}:text-match(/{patterns_js}/i)",
                    method="text",
                    tag_name=tag.upper(),
                )
        except Exception:
            pass
        return None


class InputResolver(SelectorResolver):
    """Specialized resolver for text input elements."""

    async def type_text(
        self,
        run_js: callable,
        text: str,
        resolved: ResolvedElement | None = None,
    ) -> bool:
        """Type text into resolved input using execCommand('insertText').

        This is the only reliable way to inject text into React controlled
        components from outside the browser. Regular value setters,
        synthetic InputEvents, and nativeInputValueSetter all fail.

        Args:
            run_js: JS executor.
            text: Text to type.
            resolved: Previously resolved element (will resolve if None).

        Returns:
            True if text was inserted successfully.
        """
        if resolved is None:
            resolved = await self.resolve(run_js)
        if resolved is None:
            return False

        safe_text = (
            text.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "")
        )

        js_code = (
            f"(() => {{ "
            f"const el = document.querySelector('{resolved.selector}'); "
            f"if (!el) return 'NO'; "
            f"el.focus(); "
            f"if (el.tagName === 'TEXTAREA') {{ el.value = ''; }} "
            f"else {{ el.textContent = ''; }} "
            f"document.execCommand('insertText', false, '{safe_text}'); "
            f"return 'OK'; "
            f"}})()"
        )

        try:
            result = await run_js(js_code)
            return "OK" in str(result)
        except Exception as e:
            logger.error(f"type_text failed: {e}")
            return False


class SubmitResolver(SelectorResolver):
    """Specialized resolver for submit/send buttons."""

    def __init__(
        self,
        selectors: list[str],
        text_fallback: list[str] | None = None,
    ) -> None:
        super().__init__(selectors)
        self.text_fallback = text_fallback or ["send", "submit", "發送", "送出"]

    async def click(
        self,
        run_js: callable,
        input_selector: str = "",
    ) -> bool:
        """Click submit button with multi-layer fallback.

        Fallback chain:
        1. CSS selector click
        2. Text content match click
        3. Dispatch Enter KeyboardEvent on input

        Args:
            run_js: JS executor.
            input_selector: Input element selector for keyboard fallback.

        Returns:
            True if submit was triggered.
        """
        # Layer 1: CSS selector
        for sel in self.selectors:
            js = (
                f"(() => {{ const b = document.querySelector('{sel}'); "
                f"if (b && !b.disabled) {{ b.click(); return 'OK'; }} "
                f"return 'NO'; }})()"
            )
            try:
                result = await run_js(js)
                if "OK" in str(result):
                    return True
            except Exception:
                continue

        # Layer 2: Text content match
        resolved = await self.resolve_by_text(run_js, self.text_fallback)
        if resolved:
            patterns_js = "|".join(self.text_fallback)
            js = (
                f"(() => {{ const els = [...document.querySelectorAll('button')]; "
                f"const b = els.find(x => /{patterns_js}/i.test("
                f"x.textContent || x.ariaLabel || '')); "
                f"if (b && !b.disabled) {{ b.click(); return 'OK'; }} "
                f"return 'NO'; }})()"
            )
            try:
                result = await run_js(js)
                if "OK" in str(result):
                    return True
            except Exception:
                pass

        # Layer 3: Enter key on input
        if input_selector:
            js = (
                f"document.querySelector('{input_selector}')"
                f"?.dispatchEvent(new KeyboardEvent('keydown', "
                f"{{key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true}}))"
            )
            try:
                await run_js(js)
                return True  # Best effort
            except Exception:
                pass

        return False
