"""Health check routes — self and downstream services."""

import asyncio
import time

import httpx
from fastapi import APIRouter

from gateway.config import settings
from gateway.models.schemas import HealthResponse, ServiceHealth

router = APIRouter(tags=["health"])


# ---------------------------------------------------------------------------
# GET /health — gateway self check
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="healthy")


# ---------------------------------------------------------------------------
# GET /health/all — aggregate downstream health
# ---------------------------------------------------------------------------
@router.get("/health/all", response_model=HealthResponse)
async def health_all():
    results: list[ServiceHealth] = []

    async def _check(name: str, base_url: str) -> ServiceHealth:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/health")
                latency = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    return ServiceHealth(service=name, status="healthy", latency_ms=round(latency, 1))
                else:
                    return ServiceHealth(
                        service=name,
                        status="unhealthy",
                        latency_ms=round(latency, 1),
                        error=f"HTTP {resp.status_code}",
                    )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ServiceHealth(
                service=name,
                status="unreachable",
                latency_ms=round(latency, 1),
                error=str(exc),
            )

    tasks = [_check(name, url) for name, url in settings.service_registry.items()]
    results = await asyncio.gather(*tasks)

    overall = "healthy" if all(r.status == "healthy" for r in results) else "degraded"
    return HealthResponse(status=overall, services=list(results))
