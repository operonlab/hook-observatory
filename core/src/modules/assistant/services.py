"""Assistant service — LLM streaming chat with context-aware RAG."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import httpx

from src.shared.sse import BlockType, StreamBlock

logger = logging.getLogger(__name__)

LITELLM_BASE = "http://localhost:4000/v1"
LITELLM_KEY = "sk-litellm-local-dev"
CHAT_MODEL = "claude-haiku-4-5-20251001"


async def stream_chat(
    messages: list[dict],
) -> AsyncGenerator[StreamBlock, None]:
    """Stream LLM response as StreamBlock events.

    Calls LiteLLM proxy with OpenAI-compatible streaming API.
    Yields StreamBlock objects for SSE formatting.
    """
    yield StreamBlock(type=BlockType.THINKING, data={"message": "思考中..."})

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            async with client.stream(
                "POST",
                f"{LITELLM_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LITELLM_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": CHAT_MODEL,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 1024,
                },
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error("LiteLLM error %d: %s", response.status_code, body[:200])
                    yield StreamBlock(
                        type=BlockType.ERROR,
                        data={"message": f"LLM 服務錯誤 ({response.status_code})"},
                    )
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield StreamBlock(
                                type=BlockType.CONTENT,
                                data={"text": content, "is_delta": True},
                            )
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

    except httpx.ConnectError:
        logger.error("Cannot connect to LiteLLM at %s", LITELLM_BASE)
        yield StreamBlock(
            type=BlockType.ERROR,
            data={"message": "無法連接到 LLM 服務"},
        )
        return
    except Exception:
        logger.error("Unexpected error in stream_chat", exc_info=True)
        yield StreamBlock(
            type=BlockType.ERROR,
            data={"message": "串流回應時發生錯誤"},
        )
        return

    yield StreamBlock(type=BlockType.DONE, data={})
