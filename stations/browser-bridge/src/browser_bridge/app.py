"""FastAPI application for browser-bridge station.

Endpoints:
  POST /api/bridge/chat     — Send prompt to a provider
  POST /api/bridge/new      — Start new conversation
  GET  /api/bridge/history   — Get conversation messages
  GET  /api/bridge/sessions  — List sessions
  GET  /api/bridge/providers — List available providers
  GET  /health               — Health check
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .core import BridgeCore
from .models import (
    BridgeConfig,
    BridgeResponse,
    ChatRequest,
    HealthResponse,
    NewConversationRequest,
    ProviderInfo,
)
from .providers import PROVIDERS, get_provider, list_providers
from .store import ConversationStore

logger = logging.getLogger(__name__)

# Module-level state (initialized in lifespan)
_core: BridgeCore | None = None
_store: ConversationStore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize BridgeCore and ConversationStore on startup."""
    global _core, _store

    config = BridgeConfig(
        db_path=os.environ.get(
            "BRIDGE_DB_PATH",
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "bridge.db"),
        ),
    )

    _store = ConversationStore(config.db_path)
    _core = BridgeCore(config)

    # Register all available providers
    for name in list_providers():
        provider = get_provider(name)
        if provider:
            _core.register_provider(provider)

    logger.info(
        f"browser-bridge started: {len(_core.provider_names)} providers, "
        f"db={config.db_path}"
    )

    yield

    # Shutdown
    if _core:
        await _core.shutdown()
    if _store:
        _store.close()
    logger.info("browser-bridge stopped")


app = FastAPI(
    title="browser-bridge",
    description="Agent as your hands — browser automation bridge",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version="0.1.0",
        providers=_core.provider_names if _core else [],
        active_sessions=len(_core.session_manager.active_sessions) if _core else 0,
    )


@app.post("/api/bridge/chat")
async def chat(req: ChatRequest) -> BridgeResponse:
    """Send a prompt to a web service provider."""
    if not _core or not _store:
        return BridgeResponse(status="error", provider=req.provider, error="Not initialized")

    # Get or create store session + conversation
    sessions = _store.list_sessions(provider=req.provider, limit=1)
    if sessions and sessions[0].status.value == "active":
        store_session_id = sessions[0].id
    else:
        store_session_id = _store.create_session(req.provider)

    if req.conversation_id:
        conv_id = req.conversation_id
    else:
        convs = _store.list_conversations(session_id=store_session_id, limit=1)
        if convs:
            conv_id = convs[0].id
        else:
            conv_id = _store.create_conversation(
                store_session_id, title=req.prompt[:50]
            )

    # Record user message
    _store.add_message(conv_id, "user", req.prompt)

    # Execute via BridgeCore
    response = await _core.chat(
        req.provider, req.prompt, req.timeout, req.conversation_id
    )

    # Record assistant response
    if response.status in ("ok", "timeout"):
        msg_id = _store.add_message(
            conv_id,
            "assistant",
            response.response,
            artifacts=response.artifacts,
            metadata={"elapsed": response.elapsed, "status": response.status},
        )
        response.conversation_id = conv_id
        response.message_id = msg_id

    return response


@app.post("/api/bridge/new")
async def new_conversation(req: NewConversationRequest) -> BridgeResponse:
    """Start a new conversation with a provider."""
    if not _core:
        return BridgeResponse(status="error", provider=req.provider, error="Not initialized")
    return await _core.new_conversation(req.provider)


@app.get("/api/bridge/history")
async def history(
    conversation_id: str | None = Query(None),
    provider: str | None = Query(None),
    limit: int = Query(50),
):
    """Get conversation messages or list conversations."""
    if not _store:
        return {"status": "error", "error": "Not initialized"}

    if conversation_id:
        messages = _store.get_messages(conversation_id, limit)
        return {
            "status": "ok",
            "conversation_id": conversation_id,
            "messages": [m.model_dump() for m in messages],
        }
    else:
        conversations = _store.list_conversations(limit=limit)
        return {
            "status": "ok",
            "conversations": [c.model_dump() for c in conversations],
        }


@app.get("/api/bridge/sessions")
async def sessions(
    provider: str | None = Query(None),
    limit: int = Query(50),
):
    """List bridge sessions."""
    if not _store:
        return {"status": "error", "error": "Not initialized"}

    session_list = _store.list_sessions(provider=provider, limit=limit)
    stats = _store.stats()
    return {
        "status": "ok",
        "sessions": [s.model_dump() for s in session_list],
        "stats": stats,
    }


@app.get("/api/bridge/providers")
async def providers():
    """List available providers."""
    result = []
    for name, cls in PROVIDERS.items():
        instance = cls()
        result.append(
            ProviderInfo(
                name=instance.meta.name,
                base_url=instance.meta.base_url,
                description=instance.meta.description,
                supports_conversation=instance.meta.supports_conversation,
            ).model_dump()
        )
    return {"status": "ok", "providers": result}


def main():
    """CLI entry point to run the server."""
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "4106"))
    uvicorn.run(
        "browser_bridge.app:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
