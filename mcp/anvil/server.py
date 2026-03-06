#!/Users/joneshong/.local/bin/python3
"""Anvil MCP Server -- SDK adapter for Claude Code integration.

8 tools: anvil_stats, anvil_catalog, anvil_test_skill, anvil_scan_skill,
         anvil_eval_skill, anvil_skill_detail, anvil_register_skill, anvil_sync_skills.

All logic lives in workshop.clients.anvil (SDK layer).

Usage:
    python3 mcp/anvil/server.py

Configure in ~/.claude.json:
    "anvil": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/anvil/server.py"],
        "env": {}
    }
"""

import asyncio

from mcp.server.fastmcp import FastMCP
from workshop.clients.anvil import AnvilClient

mcp = FastMCP("anvil")


def _client():
    return AnvilClient()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_stats(data: dict, skill_name: str) -> str:
    """Format usage statistics as markdown."""
    if skill_name:
        parts = [
            f"## Stats: {data.get('skill_name', skill_name)}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Invocations | {data.get('total_invocations', 0)} |",
            f"| Avg Duration | {data.get('avg_duration_ms', '-')} ms |",
            f"| Failure Rate | {data.get('failure_rate', 0):.1f}% |",
        ]
        daily = data.get("daily_counts", [])
        if daily:
            parts.append("")
            parts.append("### Daily Trend")
            parts.append("| Day | Count |")
            parts.append("|-----|-------|")
            for d in daily:
                parts.append(f"| {d.get('day', '?')} | {d.get('count', 0)} |")
        errors = data.get("common_errors", [])
        if errors:
            parts.append("")
            parts.append("### Common Errors")
            parts.append("| Error | Count |")
            parts.append("|-------|-------|")
            for e in errors:
                parts.append(f"| {e.get('error_message', '?')[:60]} | {e.get('count', 0)} |")
        return "\n".join(parts)
    else:
        parts = [
            "## Global Stats",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Invocations | {data.get('total_invocations', 0)} |",
            f"| Total Skills | {data.get('total_skills', 0)} |",
            f"| Avg Success Rate | {data.get('avg_success_rate', 0):.1f}% |",
        ]
        top = data.get("top_skills", [])
        if top:
            parts.append("")
            parts.append("### Top Skills")
            parts.append("| Skill | Count | Success Rate |")
            parts.append("|-------|-------|-------------|")
            for s in top:
                rate = (
                    f"{s.get('success_rate', 0):.1f}%" if s.get("success_rate") is not None else "-"
                )
                parts.append(f"| {s.get('skill_name', '?')} | {s.get('count', 0)} | {rate} |")
        trend = data.get("trend_7d", [])
        if trend:
            parts.append("")
            parts.append("### 7-Day Trend")
            parts.append("| Day | Count |")
            parts.append("|-----|-------|")
            for t in trend:
                parts.append(f"| {t.get('day', '?')} | {t.get('count', 0)} |")
        return "\n".join(parts)


def _format_catalog(data: dict) -> str:
    """Format skill catalog as markdown table."""
    items = data.get("items", [])
    if not items:
        return "No skills found."
    total = data.get("total", len(items))
    parts = [
        f"## Skill Catalog ({total} total)",
        "",
        "| Name | Version | Status | Health | Tags |",
        "|------|---------|--------|--------|------|",
    ]
    for s in items:
        tags = ", ".join(s.get("tags", [])) if s.get("tags") else "-"
        health = f"{s.get('health_score', 0):.0f}" if s.get("health_score") is not None else "-"
        parts.append(
            f"| {s.get('name', '?')} | {s.get('version', '-')} | "
            f"{s.get('status', '?')} | {health} | {tags} |"
        )
    return "\n".join(parts)


def _format_test_results(data: dict) -> str:
    """Format T1-T5 structural test results."""
    parts = [
        f"## Test Results: {data.get('skill_name', '?')}",
        "",
        "| Test | Description | Result |",
        "|------|-------------|--------|",
    ]
    tests = data.get("tests", [])
    if tests:
        for t in tests:
            icon = "PASS" if t.get("passed") else "FAIL"
            parts.append(f"| {t.get('id', '?')} | {t.get('description', '')} | {icon} |")
    else:
        # Fallback: format as generic key-value
        for key, value in data.items():
            if key not in ("skill_name",):
                parts.append(f"| {key} | - | {value} |")

    passed = sum(1 for t in tests if t.get("passed"))
    total = len(tests)
    parts.append("")
    parts.append(f"**Result**: {passed}/{total} passed")

    errors = data.get("errors", [])
    if errors:
        parts.append("")
        parts.append("### Errors")
        for e in errors:
            parts.append(f"- {e}")

    return "\n".join(parts)


def _format_scan_results(data: dict) -> str:
    """Format S1-S3 security scan results."""
    parts = [
        f"## Security Scan: {data.get('skill_name', '?')}",
        "",
    ]
    findings = data.get("findings", [])
    if not findings:
        parts.append("No security findings.")
    else:
        parts.append("| Check | Severity | Finding |")
        parts.append("|-------|----------|---------|")
        for f in findings:
            parts.append(
                f"| {f.get('check', '?')} | {f.get('severity', '?')} | "
                f"{f.get('message', '')[:80]} |"
            )
    parts.append("")
    parts.append(f"**Overall**: {data.get('status', 'unknown')}")
    return "\n".join(parts)


def _format_eval(data: dict) -> str:
    """Format evaluation summary."""
    parts = [
        f"## Evaluation: {data.get('skill_name', '?')}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| ID | {data.get('id', '-')} |",
        f"| Version | {data.get('version', '-')} |",
        f"| Status | {data.get('status', '-')} |",
        f"| Benchmark Score | {data.get('benchmark_score', '-')} |",
    ]
    ts = data.get("run_timestamp", "")
    if ts:
        parts.append(f"| Run Time | {ts} |")
    return "\n".join(parts)


def _format_skill_detail(data: dict) -> str:
    """Format detailed skill information."""
    parts = [
        f"## Skill: {data.get('name', '?')}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Version | {data.get('version', '-')} |",
        f"| Status | {data.get('status', '-')} |",
        f"| Description | {(data.get('description') or '-')[:80]} |",
        f"| Health Score | {data.get('health_score', '-')} |",
        f"| Invocation Count | {data.get('invocation_count', 0)} |",
        f"| Success Rate | {data.get('success_rate', '-')} |",
        f"| Latest Eval Score | {data.get('latest_eval_score', '-')} |",
        f"| Created | {data.get('created_at', '-')} |",
        f"| Updated | {data.get('updated_at', '-')} |",
    ]
    tags = data.get("tags", [])
    if tags:
        parts.append(f"| Tags | {', '.join(str(t) for t in tags)} |")
    io_schema = data.get("io_schema")
    if io_schema:
        parts.append("")
        parts.append("### I/O Schema")
        inputs = io_schema.get("input", [])
        if inputs:
            parts.append("**Input:**")
            for inp in inputs:
                parts.append(f"- `{inp.get('mime', '?')}`: {inp.get('description', '')}")
        outputs = io_schema.get("output", [])
        if outputs:
            parts.append("**Output:**")
            for out in outputs:
                parts.append(f"- `{out.get('mime', '?')}`: {out.get('description', '')}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def anvil_stats(skill_name: str = "", period: str = "7d") -> str:
    """Get skill usage statistics. Leave skill_name empty for global stats."""

    def _run():
        with _client() as c:
            if skill_name:
                return c.get_skill_stats(skill_name)
            return c.get_stats()

    result = await asyncio.to_thread(_run)
    return _format_stats(result, skill_name)


@mcp.tool()
async def anvil_catalog(status: str = "active") -> str:
    """List all registered skills with metadata."""

    def _run():
        with _client() as c:
            return c.list_skills(status=status)

    result = await asyncio.to_thread(_run)
    return _format_catalog(result)


@mcp.tool()
async def anvil_test_skill(name: str) -> str:
    """Run T1-T5 structural tests on a skill."""

    def _run():
        with _client() as c:
            return c.test_skill_structure(name)

    result = await asyncio.to_thread(_run)
    return _format_test_results(result)


@mcp.tool()
async def anvil_scan_skill(name: str) -> str:
    """Run security scan (S1-S3) on a skill."""

    def _run():
        with _client() as c:
            return c.scan_skill_security(name)

    result = await asyncio.to_thread(_run)
    return _format_scan_results(result)


@mcp.tool()
async def anvil_eval_skill(name: str, mode: str = "grader") -> str:
    """Trigger skill evaluation. Modes: grader, regression, full."""

    def _run():
        with _client() as c:
            return c.trigger_eval(name, mode=mode)

    result = await asyncio.to_thread(_run)
    return _format_eval(result)


@mcp.tool()
async def anvil_skill_detail(name: str) -> str:
    """Get detailed information about a specific skill."""

    def _run():
        with _client() as c:
            return c.get_skill(name)

    result = await asyncio.to_thread(_run)
    return _format_skill_detail(result)


@mcp.tool()
async def anvil_register_skill(
    name: str, version: str = "", description: str = "", tags: str = ""
) -> str:
    """Register or update a skill in the Anvil registry."""

    def _run():
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        with _client() as c:
            return c.register_skill(
                name,
                version=version or None,
                description=description or None,
                tags=tag_list or None,
            )

    result = await asyncio.to_thread(_run)
    return f"Registered skill: {result.get('name', name)} (v{result.get('version', '?')})"


@mcp.tool()
async def anvil_sync_skills() -> str:
    """Scan ~/.claude/skills/ and register all skills in the Anvil registry."""

    def _run():
        with _client() as c:
            skills = c.scan_skills_dir()
            registered = 0
            errors = []
            for s in skills:
                try:
                    c.register_skill(
                        s["name"],
                        version=s.get("version"),
                        description=s.get("description"),
                        tags=s.get("tags"),
                    )
                    registered += 1
                except Exception as e:
                    errors.append(f"{s['name']}: {e}")
            return {
                "total_found": len(skills),
                "registered": registered,
                "errors": errors,
            }

    result = await asyncio.to_thread(_run)
    parts = [f"Synced {result['registered']}/{result['total_found']} skills"]
    if result.get("errors"):
        parts.append(f"\nErrors ({len(result['errors'])}):")
        for err in result["errors"][:10]:
            parts.append(f"  - {err}")
    return "\n".join(parts)


if __name__ == "__main__":
    mcp.run()
