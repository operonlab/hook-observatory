"""Dual-layer health check engine: light (httpx) + deep (camoufox-cli / Playwright CLI)."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# Port registry — single source of truth for all Workshop ports
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "libs" / "python" / "src"))
from sdk_client.port_registry import get_port

logger = logging.getLogger(__name__)

# ── Checker timeout presets (seconds) ──

_TIMEOUT_HEALTH_CHECK = 10.0  # HTTP light check (LightCheck default)
_TIMEOUT_SECURITY_SCAN = 15.0  # port-security audit script
_TIMEOUT_DEEP_CHECK = 45.0  # Playwright deep check including Chrome startup
_TIMEOUT_BROWSER_OPEN = 15  # Playwright session open
_TIMEOUT_BROWSER_CLOSE = 5  # Playwright session close / cleanup


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
    timeout: float = _TIMEOUT_HEALTH_CHECK
    optional: bool = False  # optional services report "skipped" instead of "unhealthy" when down


@dataclass
class DeepCheck:
    name: str
    group: str = ""
    url: str = ""
    playwright_code: str = ""  # JS code for Playwright run-code (fallback)
    eval_code: str = ""  # Browser JS for camoufox eval (primary)
    timeout: float = _TIMEOUT_DEEP_CHECK  # Browser startup can be slow under memory pressure


def _url(name: str, path: str = "/") -> str:
    """Build health check URL from port registry."""
    return f"http://127.0.0.1:{get_port(name)}{path}"


LIGHT_CHECKS: list[LightCheck] = [
    # ── system ──
    LightCheck(
        name="nginx",
        group="system",
        url=_url("nginx", "/health"),
    ),
    LightCheck(
        name="orbstack",
        group="system",
        command="docker info --format '{{.ServerVersion}}' 2>/dev/null",
    ),
    LightCheck(
        name="workshop-crash-loop",
        group="system",
        command=(
            "dir=/opt/homebrew/var/run/workshop-crash-loop; "
            'if ls "$dir"/*.marker >/dev/null 2>&1; then '
            'names=$(ls "$dir" | sed "s/\\.marker$//" | tr "\\n" " "); '
            'echo "CRASH-LOOP: $names"; exit 1; '
            "else echo no-crashloop; fi"
        ),
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
        url=_url("rustfs", "/"),
        timeout=5.0,
    ),
    LightCheck(
        name="lgtm",
        group="infra",
        url=_url("lgtm", "/"),
        optional=True,
    ),
    LightCheck(
        name="qdrant",
        group="infra",
        url=_url("qdrant", "/healthz"),
    ),
    LightCheck(
        name="litellm",
        group="infra",
        url=_url("litellm", "/health/liveliness"),
        expect_contains="I'm alive!",
    ),
    LightCheck(
        name="ccr",
        group="infra",
        url=_url("ccr", "/health"),  # claude-code-router reverse proxy → LiteLLM
    ),
    # oMLX removed — embed_worker is a stdin/stdout subprocess, not an HTTP service
    LightCheck(
        name="bark",
        group="infra",
        url=_url("bark", "/ping"),
    ),
    # ntfy disabled — Bark + Web Push only
    LightCheck(
        name="mcpproxy",
        group="infra",
        url=_url("mcpproxy", "/health"),
        expect_json={"status": "ok"},
    ),
    # ── internal ──
    LightCheck(
        name="core",
        group="internal",
        url=_url("core", "/health"),
        expect_json={"status": "healthy"},
    ),
    LightCheck(
        name="paper",
        group="internal",
        url=_url("paper", "/health"),
        expect_json={"status": "ok"},
    ),
    LightCheck(
        name="intelflow",
        group="internal",
        url=_url("intelflow", "/health"),
        expect_json={"status": "ok"},
    ),
    LightCheck(
        name="invest",
        group="internal",
        url=_url("invest", "/health"),
        expect_json={"status": "ok"},
    ),
    # V1 gateway retired (2026-03-08)
    LightCheck(
        name="frontend",
        group="internal",
        url=_url("nginx", "/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-finance",
        group="internal",
        url=_url("nginx", "/finance/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-memvault",
        group="internal",
        url=_url("nginx", "/memvault/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-intelflow",
        group="internal",
        url=_url("nginx", "/intelflow/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-briefing",
        group="internal",
        url=_url("nginx", "/briefing/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-dailyos",
        group="internal",
        url=_url("nginx", "/dailyos/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-paper",
        group="internal",
        url=_url("nginx", "/paper/"),
        expect_contains='<div id="root">',
    ),
    LightCheck(
        name="frontend-docvault",
        group="internal",
        url=_url("nginx", "/docvault/"),
        expect_contains='<div id="root">',
    ),
    # ── external (stations) ──
    LightCheck(
        name="hook-observatory",
        group="external",
        url=_url("hook-observatory"),
    ),
    LightCheck(
        name="session-channel",
        group="external",
        url=_url("session-channel", "/health"),
    ),
    LightCheck(
        name="agent-vista",
        group="external",
        url=_url("agent-vista"),
    ),
    LightCheck(
        name="system-monitor",
        group="external",
        url=_url("system-monitor"),
    ),
    LightCheck(
        name="tmux-webui",
        group="external",
        url=_url("tmux-webui"),
    ),
    LightCheck(
        name="fleet",
        group="external",
        url=_url("fleet", "/health"),
    ),
    LightCheck(
        name="agent-metrics",
        group="external",
        url=_url("agent-metrics", "/health"),
    ),
    # sentinel removed — no longer persistent (scheduled via Cronicle)
    LightCheck(
        name="file-manager",
        group="external",
        url=_url("filebrowser"),
    ),
    LightCheck(
        name="auto-survey",
        group="external",
        url=_url("auto-survey", "/api/people"),
    ),
    # auto-survey-rs: Rust replacement, on-demand (Wed/Fri 10:00-18:00 only)
    # Shares port 10300 with Python auto-survey during migration.
    # optional=True so sentinel reports "skipped" (not "unhealthy") when off-duty.
    # TODO: add time-gate logic in sentinel runner to skip outside Wed/Fri 10-18
    #   suggested: in ws_sentinel_check.py, check weekday/hour before calling this check
    LightCheck(
        name="auto-survey-rs",
        group="external",
        url=_url("auto-survey", "/status"),
        optional=True,
    ),
    LightCheck(
        name="capture-console",
        group="external",
        url=_url("capture-console", "/health"),
    ),
    LightCheck(
        name="anvil",
        group="external",
        url=_url("anvil", "/docs"),
    ),
    LightCheck(
        name="blog",
        group="external",
        url=_url("blog", "/zh/"),
        expect_contains="JonesHong",
    ),
    LightCheck(
        name="cronicle",
        group="external",
        url=_url("cronicle", "/api/app/ping"),
        expect_json={"code": 0},
    ),
    LightCheck(
        name="stt",
        group="external",
        url=_url("stt", "/health"),
    ),
    LightCheck(
        name="ocr",
        group="external",
        url=_url("ocr", "/health"),
        optional=True,  # model loads on-demand, may be slow first call
    ),
    LightCheck(
        name="tts",
        group="external",
        url=_url("tts", "/health"),
        optional=True,
    ),
    LightCheck(
        name="vision",
        group="external",
        url=_url("vision", "/health"),
        optional=True,
    ),
    LightCheck(
        name="voice-gateway",
        group="external",
        url=_url("voice-gateway", "/health"),
        optional=True,
    ),
    LightCheck(
        name="translate",
        group="external",
        url=_url("translate", "/health"),
        optional=True,
    ),
    # ── security ──
    LightCheck(
        name="schema-drift",
        group="system",
        command="/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/check_schema_drift.py --check",
        expect_contains="PASS",
        timeout=15,
        optional=True,
    ),
    LightCheck(
        name="port-security",
        group="system",
        command="/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/port_audit.py --check",
        expect_contains="PASS",
        timeout=_TIMEOUT_SECURITY_SCAN,
    ),
    LightCheck(
        name="process-audit",
        group="system",
        command="/Users/joneshong/.local/bin/python3 /Users/joneshong/workshop/scripts/workshop_orphan_reaper.py --json",
        expect_contains='"count": 0',
        timeout=_TIMEOUT_SECURITY_SCAN,
    ),
]


# ── Playwright run-code checks (fallback) ────────────────────
_PW_ROOT_CHECK = (
    'async (page) => { await page.waitForSelector("#root > *", {timeout:10000}); return "ok"; }'
)
_PW_BODY_CHECK = (
    'async (page) => { await page.waitForSelector("body > *", {timeout:10000}); return "ok"; }'
)
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

# ── Browser JS eval checks (camoufox-cli primary) ────────────
_EVAL_ROOT_CHECK = 'document.querySelector("#root > *") ? "ok" : "NO_ROOT"'
_EVAL_BODY_CHECK = 'document.querySelector("body > *") ? "ok" : "NO_BODY"'
_EVAL_CANVAS_CHECK = (
    'document.querySelector("canvas") ? "ok" : '
    '(document.querySelectorAll("script[type=module]").length > 0 ? "ok" : "NO_CANVAS")'
)


def _pw_module_check(css_class: str) -> str:
    """Playwright run-code: render + no 404 + module content."""
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


def _eval_module_check(css_class: str) -> str:
    """Browser JS eval: render + no 404 + module content."""
    return (
        "(() => {"
        '  if (!document.querySelector("#root > *")) return "NO_ROOT";'
        '  const h = document.querySelector("h1");'
        '  if (h && h.textContent.trim() === "404") return "NOT_FOUND: route renders 404 page";'
        f'  const m = document.querySelector(".{css_class}");'
        f'  if (!m) return "MODULE_MISSING: .{css_class} not found";'
        '  return "ok";'
        "})()"
    )


DEEP_CHECKS: list[DeepCheck] = [
    # ── internal (React #root) ──
    DeepCheck(
        name="frontend-render",
        group="internal",
        url=_url("nginx", "/"),
        playwright_code=_PW_ROOT_CHECK,
        eval_code=_EVAL_ROOT_CHECK,
    ),
    DeepCheck(
        name="frontend-finance-render",
        group="internal",
        url=_url("nginx", "/finance/"),
        playwright_code=_pw_module_check("finance"),
        eval_code=_eval_module_check("finance"),
    ),
    DeepCheck(
        name="frontend-memvault-render",
        group="internal",
        url=_url("nginx", "/memvault/"),
        playwright_code=_pw_module_check("memvault"),
        eval_code=_eval_module_check("memvault"),
    ),
    DeepCheck(
        name="frontend-intelflow-render",
        group="internal",
        url=_url("nginx", "/intelflow/"),
        playwright_code=_pw_module_check("intelflow"),
        eval_code=_eval_module_check("intelflow"),
    ),
    DeepCheck(
        name="frontend-briefing-render",
        group="internal",
        url=_url("nginx", "/briefing/"),
        playwright_code=_pw_module_check("briefing"),
        eval_code=_eval_module_check("briefing"),
    ),
    DeepCheck(
        name="frontend-dailyos-render",
        group="internal",
        url=_url("nginx", "/dailyos/"),
        playwright_code=_pw_module_check("dailyos"),
        eval_code=_eval_module_check("dailyos"),
    ),
    DeepCheck(
        name="frontend-paper-render",
        group="internal",
        url=_url("nginx", "/paper/"),
        playwright_code=_pw_module_check("paper"),
        eval_code=_eval_module_check("paper"),
    ),
    DeepCheck(
        name="frontend-docvault-render",
        group="internal",
        url=_url("nginx", "/docvault/"),
        playwright_code=_pw_module_check("docvault"),
        eval_code=_eval_module_check("docvault"),
    ),
    # ── external (station HTML — body > *) ──
    DeepCheck(
        name="hook-observatory-render",
        group="external",
        url=_url("nginx", "/apps/hook/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="session-channel-render",
        group="external",
        url=_url("nginx", "/apps/channel/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="agent-vista-render",
        group="external",
        url=_url("nginx", "/apps/vista/"),
        playwright_code=_PW_CANVAS_CHECK,
        eval_code=_EVAL_CANVAS_CHECK,
    ),
    DeepCheck(
        name="system-monitor-render",
        group="external",
        url=_url("nginx", "/apps/sysmon/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="tmux-webui-render",
        group="external",
        url=_url("nginx", "/apps/tmux/?readonly=1"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="agent-metrics-render",
        group="external",
        url=_url("nginx", "/apps/agent-metrics/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="sentinel-render",
        group="external",
        url=_url("nginx", "/apps/sentinel/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="auto-survey-render",
        group="external",
        url=_url("nginx", "/apps/survey/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="anvil-render",
        group="external",
        url=_url("nginx", "/apps/anvil/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
    ),
    DeepCheck(
        name="capture-console-render",
        group="external",
        url=_url("nginx", "/capture"),
        playwright_code=_PW_ROOT_CHECK,
        eval_code=_EVAL_ROOT_CHECK,
    ),
    DeepCheck(
        name="cronicle-render",
        group="external",
        url=_url("nginx", "/apps/scheduler/"),
        playwright_code=_PW_BODY_CHECK,
        eval_code=_EVAL_BODY_CHECK,
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
                output = stdout.decode(errors="replace").strip()
                detail = f"exit={proc.returncode}"
                if output:
                    detail += f": {output[:200]}"
                return CheckResult(check.name, "light", "unhealthy", elapsed, detail)

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
        status = "skipped" if check.optional else "unhealthy"
        return CheckResult(
            check.name,
            "light",
            status,
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
        status = "skipped" if check.optional else "timeout"
        return CheckResult(
            check.name, "light", status, (time.monotonic() - start) * 1000, "Timeout"
        )
    except Exception as e:
        status = "skipped" if check.optional else "unhealthy"
        return CheckResult(
            check.name, "light", status, (time.monotonic() - start) * 1000, str(e)[:200]
        )


_SHORT_NAMES = {
    "frontend-render": "fe",
    "frontend-finance-render": "fin",
    "frontend-memvault-render": "mv",
    "frontend-intelflow-render": "if",
    "frontend-briefing-render": "bf",
    "frontend-dailyos-render": "dos",
    "frontend-paper-render": "paper",
    "frontend-docvault-render": "dv",
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


async def _run_deep_cfx(check: DeepCheck, session_id: str) -> CheckResult | None:
    """Try camoufox-cli: open → wait → eval → close. Returns None if cfx unavailable."""
    start = time.monotonic()
    try:
        open_proc = await asyncio.create_subprocess_exec(
            "camoufox-cli",
            "--session",
            session_id,
            "open",
            check.url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(open_proc.communicate(), timeout=15)

        if open_proc.returncode != 0:
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult(check.name, "deep", "unhealthy", elapsed, "camoufox open failed")

        # Wait for SPA render
        wait_proc = await asyncio.create_subprocess_exec(
            "camoufox-cli",
            "--session",
            session_id,
            "wait",
            "5000",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(wait_proc.communicate(), timeout=10)

        # Eval browser JS check
        eval_proc = await asyncio.create_subprocess_exec(
            "camoufox-cli",
            "--session",
            session_id,
            "eval",
            check.eval_code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(eval_proc.communicate(), timeout=check.timeout)
        elapsed = (time.monotonic() - start) * 1000

        if eval_proc.returncode != 0:
            return CheckResult(check.name, "deep", "unhealthy", elapsed, stderr.decode()[:200])

        output = stdout.decode().strip()
        if "ok" in output.lower():
            return CheckResult(check.name, "deep", "healthy", elapsed)
        return CheckResult(check.name, "deep", "unhealthy", elapsed, f"Unexpected: {output[:100]}")

    except FileNotFoundError:
        return None  # Signal caller to try playwright fallback
    except TimeoutError:
        return CheckResult(
            check.name, "deep", "timeout", (time.monotonic() - start) * 1000, "Timeout"
        )
    except Exception as e:
        return CheckResult(
            check.name, "deep", "unhealthy", (time.monotonic() - start) * 1000, str(e)[:200]
        )
    finally:
        try:
            close_proc = await asyncio.create_subprocess_exec(
                "camoufox-cli",
                "--session",
                session_id,
                "close",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(close_proc.communicate(), timeout=5)
        except Exception:
            pass


async def _run_deep_pw(check: DeepCheck, session_id: str) -> CheckResult:
    """Playwright CLI fallback: open → run-code → close."""
    start = time.monotonic()
    try:
        open_proc = await asyncio.create_subprocess_exec(
            "playwright-cli",
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

        code_proc = await asyncio.create_subprocess_exec(
            "playwright-cli",
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
        return CheckResult(check.name, "deep", "unhealthy", elapsed, f"Unexpected: {output[:100]}")

    except TimeoutError:
        return CheckResult(
            check.name, "deep", "timeout", (time.monotonic() - start) * 1000, "Timeout"
        )
    except FileNotFoundError:
        return CheckResult(check.name, "deep", "unhealthy", 0, "Browser CLI not found")
    except Exception as e:
        return CheckResult(
            check.name, "deep", "unhealthy", (time.monotonic() - start) * 1000, str(e)[:200]
        )
    finally:
        try:
            close_proc = await asyncio.create_subprocess_exec(
                "playwright-cli",
                f"-s={session_id}",
                "close",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(close_proc.communicate(), timeout=5)
        except Exception:  # noqa: S110
            pass


async def run_deep_check(check: DeepCheck) -> CheckResult:
    """Execute deep check: camoufox-cli primary, playwright-cli fallback."""
    session_id = f"sn-{_SHORT_NAMES.get(check.name, check.name[:8])}"

    # Try camoufox-cli first (if eval_code is defined)
    if check.eval_code:
        result = await _run_deep_cfx(check, session_id)
        if result is not None:
            return result
        # None = camoufox not found, fall through to playwright

    return await _run_deep_pw(check, session_id)


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
    light skipped → operational (optional service offline)
    """
    # "skipped" = optional service offline → treat as absent
    if light == "skipped":
        light = None
    if light in ("unhealthy", "timeout"):
        return "major_outage"
    if deep in ("unhealthy", "timeout"):
        return "degraded"
    if (light is None or light == "healthy") and (deep is None or deep == "healthy"):
        return "operational"
    return "partial_outage"
