"""Dual-layer health check engine: light (httpx) + deep (Playwright CLI)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    service: str
    check_type: str  # light / deep
    status: str  # healthy / unhealthy / timeout / degraded
    response_ms: float = 0.0
    detail: str = ""


# ── Service Definitions ──────────────────────────────────────


@dataclass
class LightCheck:
    name: str
    url: str | None = None
    command: str | None = None  # shell command alternative
    expect_json: dict | None = None  # key-value pairs to verify in JSON
    expect_contains: str | None = None  # substring in body
    timeout: float = 10.0


@dataclass
class DeepCheck:
    name: str
    url: str
    playwright_code: str  # JS code for run-code
    timeout: float = 30.0


LIGHT_CHECKS: list[LightCheck] = [
    LightCheck(
        name="core",
        url="http://127.0.0.1:8801/health",
        expect_json={"status": "healthy"},
    ),
    LightCheck(
        name="frontend",
        url="http://127.0.0.1:8080/v2/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-memvault",
        url="http://127.0.0.1:8080/v2/memvault/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="hook-observatory",
        url="http://127.0.0.1:4100/",
    ),
    LightCheck(
        name="agent-vista",
        url="http://127.0.0.1:8840/",
    ),
    LightCheck(
        name="litellm",
        url="http://127.0.0.1:4000/health",
    ),
    LightCheck(
        name="postgres",
        command="docker exec ws-infra-postgres-1 pg_isready -q",
    ),
    LightCheck(
        name="redis",
        command="docker exec ws-infra-redis-1 redis-cli ping",
        expect_contains="PONG",
    ),
    LightCheck(
        name="rustfs",
        url="http://127.0.0.1:9000/",
        timeout=5.0,
    ),
]


_PW_ROOT_CHECK = (
    "async (page) => { await page.waitForSelector(\"#root > *\", {timeout:10000}); return 'ok'; }"
)

DEEP_CHECKS: list[DeepCheck] = [
    DeepCheck(
        name="frontend-render",
        url="http://127.0.0.1:8080/v2/",
        playwright_code=_PW_ROOT_CHECK,
    ),
    DeepCheck(
        name="frontend-memvault-render",
        url="http://127.0.0.1:8080/v2/memvault/",
        playwright_code=_PW_ROOT_CHECK,
    ),
]


# ── Check Execution ──────────────────────────────────────────


async def run_light_check(check: LightCheck) -> CheckResult:
    """Execute a single light health check."""
    start = time.monotonic()
    try:
        if check.url:
            async with httpx.AsyncClient(timeout=check.timeout, follow_redirects=True) as client:
                resp = await client.get(check.url)
                elapsed = (time.monotonic() - start) * 1000

                if resp.status_code >= 500:
                    return CheckResult(
                        check.name, "light", "unhealthy", elapsed, f"HTTP {resp.status_code}"
                    )

                if check.expect_json:
                    data = resp.json()
                    for k, v in check.expect_json.items():
                        if data.get(k) != v:
                            return CheckResult(
                                check.name,
                                "light",
                                "unhealthy",
                                elapsed,
                                f"JSON mismatch: {k}={data.get(k)}",
                            )

                if check.expect_contains:
                    body = resp.text
                    if check.expect_contains not in body:
                        return CheckResult(
                            check.name,
                            "light",
                            "unhealthy",
                            elapsed,
                            f"Missing: {check.expect_contains[:50]}",
                        )

                return CheckResult(check.name, "light", "healthy", elapsed)

        elif check.command:
            proc = await asyncio.create_subprocess_shell(
                check.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=check.timeout)
            elapsed = (time.monotonic() - start) * 1000

            if proc.returncode != 0:
                return CheckResult(
                    check.name, "light", "unhealthy", elapsed, f"exit={proc.returncode}"
                )

            if check.expect_contains:
                output = stdout.decode()
                if check.expect_contains not in output:
                    return CheckResult(
                        check.name,
                        "light",
                        "unhealthy",
                        elapsed,
                        f"Missing: {check.expect_contains}",
                    )

            return CheckResult(check.name, "light", "healthy", elapsed)

        return CheckResult(check.name, "light", "unhealthy", 0, "No URL or command defined")

    except httpx.ConnectError:
        return CheckResult(
            check.name,
            "light",
            "unhealthy",
            (time.monotonic() - start) * 1000,
            "Connection refused",
        )
    except (TimeoutError, httpx.TimeoutException):
        return CheckResult(
            check.name, "light", "timeout", (time.monotonic() - start) * 1000, "Timeout"
        )
    except Exception as e:
        return CheckResult(
            check.name, "light", "unhealthy", (time.monotonic() - start) * 1000, str(e)[:200]
        )


async def run_deep_check(check: DeepCheck) -> CheckResult:
    """Execute a Playwright CLI deep check.

    Playwright CLI v1.59+ requires session-based usage:
    1. open <url>  — launches headless browser with session ID
    2. run-code    — executes JS check
    3. close       — cleans up session
    """
    session_id = f"sentinel-{check.name}"
    start = time.monotonic()
    try:
        # Open browser session with target URL (headless by default)
        open_proc = await asyncio.create_subprocess_exec(
            "npx",
            "@playwright/cli",
            f"-s={session_id}",
            "open",
            check.url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(open_proc.communicate(), timeout=15)

        if open_proc.returncode != 0:
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult(check.name, "deep", "unhealthy", elapsed, "Browser open failed")

        # Run code check
        code_proc = await asyncio.create_subprocess_exec(
            "npx",
            "@playwright/cli",
            f"-s={session_id}",
            "run-code",
            check.playwright_code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(code_proc.communicate(), timeout=check.timeout)
        elapsed = (time.monotonic() - start) * 1000

        if code_proc.returncode != 0:
            return CheckResult(check.name, "deep", "unhealthy", elapsed, stderr.decode()[:200])

        output = stdout.decode().strip()
        if "ok" in output.lower():
            return CheckResult(check.name, "deep", "healthy", elapsed)
        else:
            return CheckResult(
                check.name, "deep", "unhealthy", elapsed, f"Unexpected: {output[:100]}"
            )

    except TimeoutError:
        return CheckResult(
            check.name, "deep", "timeout", (time.monotonic() - start) * 1000, "Timeout"
        )
    except FileNotFoundError:
        return CheckResult(check.name, "deep", "unhealthy", 0, "Playwright CLI not found")
    except Exception as e:
        return CheckResult(
            check.name, "deep", "unhealthy", (time.monotonic() - start) * 1000, str(e)[:200]
        )
    finally:
        # Always clean up the browser session
        try:
            close_proc = await asyncio.create_subprocess_exec(
                "npx",
                "@playwright/cli",
                f"-s={session_id}",
                "close",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(close_proc.communicate(), timeout=5)
        except Exception:
            pass


async def run_all_light_checks() -> list[CheckResult]:
    """Run all light checks concurrently."""
    tasks = [run_light_check(c) for c in LIGHT_CHECKS]
    return list(await asyncio.gather(*tasks))


async def run_all_deep_checks() -> list[CheckResult]:
    """Run deep checks sequentially (shared browser)."""
    results = []
    for check in DEEP_CHECKS:
        results.append(await run_deep_check(check))
    return results


# ── Status Merging ──────────────────────────────────────────


def merge_status(light: str | None, deep: str | None) -> str:
    """Merge light + deep status into overall service status.

    light healthy + deep healthy → operational
    light healthy + deep unhealthy → degraded
    light unhealthy → major_outage
    """
    if light in ("unhealthy", "timeout"):
        return "major_outage"
    if deep in ("unhealthy", "timeout"):
        return "degraded"
    if light == "healthy" and (deep is None or deep == "healthy"):
        return "operational"
    return "partial_outage"
