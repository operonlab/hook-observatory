"""BridgeCore — orchestration engine for browser-bridge.

Coordinates the full lifecycle:
1. SessionManager creates isolated browser session
2. Provider navigates to target web service
3. InputResolver + SubmitResolver inject prompt
4. StabilityPoller waits for response
5. ResultExtractor cleans the output
6. Result returned as BridgeResponse
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .session import SessionManager, PlaywrightSession
from .poller import StabilityPoller
from .extractor import ResultExtractor
from .models import BridgeResponse, BridgeConfig

if TYPE_CHECKING:
    from .provider import BrowserProvider

logger = logging.getLogger(__name__)


class BridgeCore:
    """Main orchestration engine.

    Usage:
        core = BridgeCore(config)
        core.register_provider(grok_provider)
        response = await core.chat("grok", "What is quantum computing?")
    """

    def __init__(self, config: BridgeConfig | None = None) -> None:
        self.config = config or BridgeConfig()
        self.session_manager = SessionManager()
        self._providers: dict[str, BrowserProvider] = {}
        self._active_sessions: dict[str, PlaywrightSession] = {}

    def register_provider(self, provider: BrowserProvider) -> None:
        """Register a provider by its meta.name."""
        self._providers[provider.meta.name] = provider
        logger.info(f"Registered provider: {provider.meta.name}")

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())

    def get_provider(self, name: str) -> BrowserProvider | None:
        return self._providers.get(name)

    async def chat(
        self,
        provider_name: str,
        prompt: str,
        timeout: int | None = None,
        conversation_id: str | None = None,
    ) -> BridgeResponse:
        """Send a prompt to a web service and return the response.

        Full lifecycle:
        1. Get or create browser session for provider
        2. Ensure page is ready
        3. Send prompt via provider
        4. Wait for response via StabilityPoller
        5. Extract and clean response
        6. Return BridgeResponse

        Args:
            provider_name: Registered provider name.
            prompt: User prompt to send.
            timeout: Max seconds to wait (default from config).
            conversation_id: Optional conversation to continue.

        Returns:
            BridgeResponse with status, response text, elapsed time.
        """
        timeout = timeout or self.config.default_timeout
        start = time.monotonic()

        # Validate provider
        provider = self._providers.get(provider_name)
        if not provider:
            available = ", ".join(self._providers.keys()) or "none"
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error=f"Unknown provider '{provider_name}'. Available: {available}",
            )

        # Get or create session
        try:
            session = await self._get_or_create_session(provider_name)
        except Exception as e:
            logger.error(f"Session creation failed: {e}")
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error=f"Session creation failed: {e}",
            )

        sid = session.cli_session_tag()
        pw_profile = session.profile_path

        try:
            # Ensure page is ready
            ready = await provider.ensure_ready(sid, pw_profile)
            if not ready:
                return BridgeResponse(
                    status="error",
                    provider=provider_name,
                    session_id=session.session_id,
                    error="Provider not ready (page load or auth failed)",
                    elapsed=time.monotonic() - start,
                )

            # Send prompt
            await provider.send_prompt(sid, pw_profile, prompt)

            # Wait for response and extract
            response = await provider.wait_and_extract(
                sid, pw_profile, prompt, timeout
            )
            response.session_id = session.session_id
            response.elapsed = round(time.monotonic() - start, 1)

            return response

        except Exception as e:
            logger.error(f"Chat failed for {provider_name}: {e}")
            return BridgeResponse(
                status="error",
                provider=provider_name,
                session_id=session.session_id,
                error=str(e),
                elapsed=round(time.monotonic() - start, 1),
            )

    async def new_conversation(self, provider_name: str) -> BridgeResponse:
        """Start a new conversation with the given provider."""
        provider = self._providers.get(provider_name)
        if not provider:
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error=f"Unknown provider: {provider_name}",
            )

        session = self._active_sessions.get(provider_name)
        if not session:
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error="No active session for this provider",
            )

        try:
            sid = session.cli_session_tag()
            await provider.new_conversation(sid, session.profile_path)
            return BridgeResponse(
                status="ok",
                provider=provider_name,
                session_id=session.session_id,
                response="New conversation started",
            )
        except Exception as e:
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error=str(e),
            )

    async def get_history(self, provider_name: str) -> BridgeResponse:
        """Read current page conversation content."""
        provider = self._providers.get(provider_name)
        if not provider:
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error=f"Unknown provider: {provider_name}",
            )

        session = self._active_sessions.get(provider_name)
        if not session:
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error="No active session",
            )

        try:
            sid = session.cli_session_tag()
            body = await provider._run_js(
                sid, session.profile_path, "return document.body.innerText"
            )
            extractor = ResultExtractor(provider_name)
            cleaned = extractor._apply_rules(body)
            return BridgeResponse(
                status="ok",
                provider=provider_name,
                session_id=session.session_id,
                response=cleaned,
            )
        except Exception as e:
            return BridgeResponse(
                status="error",
                provider=provider_name,
                error=str(e),
            )

    async def _get_or_create_session(
        self, provider_name: str
    ) -> PlaywrightSession:
        """Get existing session for provider or create a new one."""
        existing = self._active_sessions.get(provider_name)
        if existing and not existing._closed:
            return existing

        session = await self.session_manager.create(provider_name)
        self._active_sessions[provider_name] = session
        return session

    async def close_session(self, provider_name: str) -> None:
        """Close the active session for a provider."""
        session = self._active_sessions.pop(provider_name, None)
        if session:
            await self.session_manager.close(session)

    async def shutdown(self) -> None:
        """Close all sessions and cleanup."""
        for provider_name in list(self._active_sessions.keys()):
            await self.close_session(provider_name)
        await self.session_manager.close_all()
