"""Dual-layer health check engine: light (httpx) + deep (Playwright CLI)."""

from __future__ import annotations

import asyncio
import json
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
    group: str = ""
    url: str | None = None
    command: str | None = None  # shell command alternative
    expect_json: dict | None = None  # key-value pairs to verify in JSON
    expect_contains: str | None = None  # substring in body
    timeout: float = 10.0


@dataclass
class DeepCheck:
    name: str
    group: str = ""
    url: str = ""
    playwright_code: str = ""  # JS code for run-code
    timeout: float = 45.0  # increased: Chrome startup can be slow under memory pressure


LIGHT_CHECKS: list[LightCheck] = [
    # ── system ──
    LightCheck(
        name="nginx",
        group="system",
        url="http://127.0.0.1:8080/health",
    ),
    LightCheck(
        name="orbstack",
        group="system",
        command="docker info --format '{{.ServerVersion}}' 2>/dev/null",
    ),
    # ── infra ──
    LightCheck(
        name="postgres",
        group="infra",
        command="docker exec ws-infra-postgres-1 pg_isready -q",
    ),
    LightCheck(
        name="redis",
        group="infra",
        command="docker exec ws-infra-redis-1 redis-cli ping",
        expect_contains="PONG",
    ),
    LightCheck(
        name="rustfs",
        group="infra",
        url="http://127.0.0.1:9000/",
        timeout=5.0,
    ),
    LightCheck(
        name="lgtm",
        group="infra",
        url="http://127.0.0.1:3100/",
    ),
    LightCheck(
        name="qdrant",
        group="infra",
        url="http://127.0.0.1:6333/healthz",
    ),
    LightCheck(
        name="litellm",
        group="infra",
        url="http://127.0.0.1:4000/health/liveliness",
        expect_contains="I'm alive!",
    ),
    # oMLX removed — embed_worker is a stdin/stdout subprocess, not an HTTP service
    LightCheck(
        name="bark",
        group="infra",
        url="http://127.0.0.1:8090/ping",
    ),
    # ntfy disabled — Bark + Web Push only
    LightCheck(
        name="mcpproxy",
        group="infra",
        url="http://127.0.0.1:8808/health",
        expect_json={"status": "ok"},
    ),
    # ── internal ──
    LightCheck(
        name="core",
        group="internal",
        url="http://127.0.0.1:8801/health",
        expect_json={"status": "healthy"},
    ),
    # V1 gateway retired (2026-03-08)
    LightCheck(
        name="frontend",
        group="internal",
        url="http://127.0.0.1:8080/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-finance",
        group="internal",
        url="http://127.0.0.1:8080/finance/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-memvault",
        group="internal",
        url="http://127.0.0.1:8080/memvault/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-intelflow",
        group="internal",
        url="http://127.0.0.1:8080/intelflow/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-briefing",
        group="internal",
        url="http://127.0.0.1:8080/briefing/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-dailyos",
        group="internal",
        url="http://127.0.0.1:8080/dailyos/",
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-paper",
        group="internal",
        url="http://127.0.0.1:8080/paper/",
        expect_contains='<div id="root">',
    ),
    # ── external (stations) ──
    LightCheck(
        name="hook-observatory",
        group="external",
        url="http://127.0.0.1:4100/",
    ),
    LightCheck(
        name="session-channel",
        group="external",
        url="http://127.0.0.1:4106/health",
    ),
    LightCheck(
        name="agent-vista",
        group="external",
        url="http://127.0.0.1:8840/",
    ),
    LightCheck(
        name="system-monitor",
        group="external",
        url="http://127.0.0.1:9526/",
    ),
    LightCheck(
        name="tmux-webui",
        group="external",
        url="http://127.0.0.1:8765/",
    ),
    LightCheck(
        name="agent-metrics",
        group="external",
        url="http://127.0.0.1:8795/health",
    ),
    LightCheck(
        name="sentinel",
        group="external",
        url="http://127.0.0.1:4101/health",
    ),
    LightCheck(
        name="file-manager",
        group="external",
        url="http://127.0.0.1:8850/",
    ),
    LightCheck(
        name="auto-survey",
        group="external",
        url="http://127.0.0.1:4102/api/people",
    ),
    LightCheck(
        name="capture-console",
        group="external",
        url="http://127.0.0.1:4104/health",
    ),
    LightCheck(
        name="anvil",
        group="external",
        url="http://127.0.0.1:4103/docs",
    ),
    LightCheck(
        name="cronicle",
        group="external",
        url="http://127.0.0.1:4105/api/app/ping",
        expect_json={"code": 0},
    ),
    LightCheck(
        name="stt",
        group="external",
        url="http://127.0.0.1:4108/health",
    ),
    LightCheck(
        name="ocr",
        group="external",
        url="http://127.0.0.1:4109/health",
    ),
    # ── security ──
    LightCheck(
        name="port-security",
        group="system",
        command="/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/port_audit.py --check",
        expect_contains="PASS",
        timeout=15.0,
    ),
]


_PW_ROOT_CHECK = (
    'async (page) => { await page.waitForSelector("#root > *", {timeout:10000}); return "ok"; }'
)
_PW_BODY_CHECK = (
    'async (page) => { await page.waitForSelector("body > *", {timeout:10000}); return "ok"; }'
)
# Canvas/WebGL apps: JS bundle must load + create <canvas> element.
# Headless Chromium may fail WebGL init, so we check in 3 tiers:
#   1. <canvas> created with dimensions → fully healthy
#   2. <canvas> exists but zero-size → JS loaded, WebGL degraded (still ok)
#   3. No <canvas> at all → JS failed to execute (unhealthy)
_PW_CANVAS_CHECK = (
    "async (page) => {"
    "  const errors = [];"
    '  page.on("pageerror", e => errors.push(e.message));'
    "  try {"
    "    await page.waitForFunction("
    '      () => !!document.querySelector("canvas"),'
    "      {timeout: 12000}"
    "    );"
    "  } catch {"
    '    const scripts = await page.evaluate(() => document.querySelectorAll("script[type=module]").length);'
    '    if (scripts > 0 && errors.length === 0) return "ok";'
    '    return "NO_CANVAS: " + (errors[0] || "JS bundle did not create canvas");'
    "  }"
    '  return "ok";'
    "}"
)


def _pw_module_check(css_class: str) -> str:
    """Generate deep check that verifies: render + no 404 + module content exists.

    Catches two failure modes that _PW_ROOT_CHECK misses:
    1. Missing route → NotFound page renders (h1 with "404")
    2. JS runtime error → module layout never mounts (no .{css_class} element)
    """
    return (
        "async (page) => {"
        '  await page.waitForSelector("#root > *", {timeout:10000});'
        "  const is404 = await page.evaluate(() => {"
        '    const h = document.querySelector("h1");'
        '    return h && h.textContent.trim() === "404";'
        "  });"
        '  if (is404) return "NOT_FOUND: route renders 404 page";'
        f'  const m = await page.$(".{css_class}");'
        '  if (!m) return "MODULE_MISSING: .' + css_class + ' not found";'
        '  return "ok";'
        "}"
    )


DEEP_CHECKS: list[DeepCheck] = [
    # ── internal (React #root) ──
    DeepCheck(
        name="frontend-render",
        group="internal",
        url="http://127.0.0.1:8080/",
        playwright_code=_PW_ROOT_CHECK,
    ),
    DeepCheck(
        name="frontend-finance-render",
        group="internal",
        url="http://127.0.0.1:8080/finance/",
        playwright_code=_pw_module_check("finance"),
    ),
    DeepCheck(
        name="frontend-memvault-render",
        group="internal",
        url="http://127.0.0.1:8080/memvault/",
        playwright_code=_pw_module_check("memvault"),
    ),
    DeepCheck(
        name="frontend-intelflow-render",
        group="internal",
        url="http://127.0.0.1:8080/intelflow/",
        playwright_code=_pw_module_check("intelflow"),
    ),
    DeepCheck(
        name="frontend-briefing-render",
        group="internal",
        url="http://127.0.0.1:8080/briefing/",
        playwright_code=_pw_module_check("briefing"),
    ),
    DeepCheck(
        name="frontend-dailyos-render",
        group="internal",
        url="http://127.0.0.1:8080/dailyos/",
        playwright_code=_pw_module_check("dailyos"),
    ),
    DeepCheck(
        name="frontend-paper-render",
        group="internal",
        url="http://127.0.0.1:8080/paper/",
        playwright_code=_pw_module_check("paper"),
    ),
    # ── external (station HTML — body > *) ──
    DeepCheck(
        name="hook-observatory-render",
        group="external",
        url="http://127.0.0.1:8080/apps/hook/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="session-channel-render",
        group="external",
        url="http://127.0.0.1:8080/apps/channel/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="agent-vista-render",
        group="external",
        url="http://127.0.0.1:8080/apps/vista/",
        playwright_code=_PW_CANVAS_CHECK,
    ),
    DeepCheck(
        name="system-monitor-render",
        group="external",
        url="http://127.0.0.1:8080/apps/sysmon/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="tmux-webui-render",
        group="external",
        url="http://127.0.0.1:8080/apps/tmux/?readonly=1",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="agent-metrics-render",
        group="external",
        url="http://127.0.0.1:8080/apps/agent-metrics/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="sentinel-render",
        group="external",
        url="http://127.0.0.1:8080/apps/sentinel/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="auto-survey-render",
        group="external",
        url="http://127.0.0.1:8080/apps/survey/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="anvil-render",
        group="external",
        url="http://127.0.0.1:8080/apps/anvil/",
        playwright_code=_PW_BODY_CHECK,
    ),
    DeepCheck(
        name="capture-console-render",
        group="external",
        url="http://127.0.0.1:8080/capture",
        playwright_code=_PW_ROOT_CHECK,
    ),
    DeepCheck(
        name="cronicle-render",
        group="external",
        url="http://127.0.0.1:8080/apps/scheduler/",
        playwright_code=_PW_BODY_CHECK,
    ),
]

# ── Group lookup for state.py ──

GROUP_MAP: dict[str, str] = {}
for _c in LIGHT_CHECKS:
    GROUP_MAP[_c.name] = _c.group
for _c in DEEP_CHECKS:
    GROUP_MAP[_c.name] = _c.group


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
                    try:
                        data = resp.json()
                    except (ValueError, json.JSONDecodeError):
                        return CheckResult(
                            check.name,
                            "light",
                            "unhealthy",
                            elapsed,
                            "json_parse_error",
                        )
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
        # Kill lingering subprocess if it exists
        try:
            if proc.returncode is None:  # type: ignore[possibly-undefined]
                proc.kill()
                await proc.communicate()
        except (NameError, ProcessLookupError):
            pass
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
    # Keep session ID short — macOS Unix socket path limit is 104 chars.
    # Playwright stores sockets in /var/folders/…/playwright-cli/<hash>/<session>.sock
    # which is ~85 chars base, so session ID must be ≤18 chars.
    _short_names = {
        "frontend-render": "fe",
        "frontend-finance-render": "fin",
        "frontend-memvault-render": "mv",
        "frontend-intelflow-render": "if",
        "frontend-briefing-render": "bf",
        "frontend-dailyos-render": "dos",
        "frontend-paper-render": "paper",
        "hook-observatory-render": "hook",
        "session-channel-render": "ch",
        "agent-vista-render": "vista",
        "system-monitor-render": "sysm",
        "tmux-webui-render": "tmux",
        "agent-metrics-render": "am",
        "sentinel-render": "sntl",
        "auto-survey-render": "asrv",
        "anvil-render": "anvl",
        "capture-console-render": "cap",
        "cronicle-render": "cron",
    }
    session_id = f"sn-{_short_names.get(check.name, check.name[:8])}"
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
        except Exception:  # noqa: S110
            pass


async def run_all_light_checks() -> list[CheckResult]:
    """Run all light checks concurrently."""
    tasks = [run_light_check(c) for c in LIGHT_CHECKS]
    return list(await asyncio.gather(*tasks))


_BUILD_COOLDOWN_FILE = "/tmp/sentinel-build-cooldown"
_BUILD_COOLDOWN_SECS = 180  # 3 minutes


async def run_all_deep_checks() -> list[CheckResult]:
    """Run deep checks sequentially (shared browser).

    Skips all checks during build cooldown period to avoid
    false-positive timeouts while SW cache propagates.
    """
    import os
    import time

    if os.path.exists(_BUILD_COOLDOWN_FILE):
        try:
            mtime = os.path.getmtime(_BUILD_COOLDOWN_FILE)
            if time.time() - mtime < _BUILD_COOLDOWN_SECS:
                return []  # skip during cooldown
            os.unlink(_BUILD_COOLDOWN_FILE)  # expired, remove
        except OSError:
            pass

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
    if (light is None or light == "healthy") and (deep is None or deep == "healthy"):
        return "operational"
    return "partial_outage"
