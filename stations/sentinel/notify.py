"""Webhook notification sender for incident events."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


async def send_webhook(url: str, payload: dict) -> bool:
    """POST payload to webhook URL. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code < 400
    except Exception as e:
        logger.warning("Webhook delivery failed to %s: %s", url, e)
        return False


async def broadcast_incident(subscribers: list[dict], incident: dict) -> None:
    """Send incident notification to all matching subscribers."""
    tasks = []
    for sub in subscribers:
        events = sub.get("events", ["*"])
        if "*" in events or incident.get("severity") in events or incident.get("status") in events:
            tasks.append(
                send_webhook(
                    sub["url"],
                    {
                        "type": "incident",
                        "incident": incident,
                    },
                )
            )

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if r is True)
        logger.info("Incident broadcast: %d/%d delivered", success, len(tasks))
