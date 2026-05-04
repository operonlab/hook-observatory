#!/usr/bin/env python3
"""
ws_memvault_verification_review.py — one-shot follow-up review of
ws-memvault-promote-verified weekly job's first observation period.

Reads the last 14 KGVerificationRunLog rows, summarises trends, and writes
a markdown report to outputs/memvault/dry_run_review.md plus a Bark push
so 少爺 can decide whether to flip MEMVAULT_PROMOTE_VERIFIED_DRY_RUN=0.

Scheduled one-shot via schedules/manifest.json (ws-memvault-verification-review)
on 2026-05-17 09:00 — disable the entry after it fires.

Output:
  ~/workshop/outputs/memvault/dry_run_review.md  (overwrites; latest review)
  Bark push (best-effort)
"""

from __future__ import annotations

import asyncio
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

OUT_DIR = Path.home() / "workshop" / "outputs" / "memvault"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_FILE = OUT_DIR / "dry_run_review.md"

BARK_URL = os.environ.get("BARK_URL", "http://127.0.0.1:8090")
BARK_KEY = os.environ.get("BARK_KEY", "")


def bark_notify(title: str, body: str) -> None:
    """Best-effort Bark push (silent on failure)."""
    if not BARK_KEY:
        return
    try:
        url = (
            f"{BARK_URL}/{BARK_KEY}/"
            f"{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
            f"?group=memvault-verification&sound=minuet"
        )
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


def _classify(promoted_avg: float, demoted_avg: float, dry_count: int) -> tuple[str, str]:
    """Return (verdict, recommendation) — same heuristic as plan §G."""
    if dry_count == 0:
        return ("NO_RUNS", "weekly job 沒跑過 → 檢查 Cronicle / launchd 是否啟動。")
    if promoted_avg == 0 and demoted_avg == 0:
        return (
            "NO_SIGNAL",
            "promoted=0 + demoted=0 → CRAG verdict 可能沒在 production query path 真的回流。"
            "檢查 _record_implicit_feedback 是否觸發；確認 SearchFeedbackService.record_implicit_batch 真的寫入。",
        )
    if demoted_avg > 10:
        return (
            "DEMOTE_HIGH",
            f"demoted_avg={demoted_avg:.1f} > 10 → 先別切 production；"
            "review 被 disputed 的 triples 或 raise DEMOTE_INCORRECT_THRESHOLD。",
        )
    if 5 <= promoted_avg <= 50 and demoted_avg < 10:
        return (
            "READY",
            "promoted_avg / demoted_avg 都在合理範圍 → 建議切 production：\n"
            "  export MEMVAULT_PROMOTE_VERIFIED_DRY_RUN=0\n"
            "  （或在 schedules/manifest.json 的 job env 區設）",
        )
    return (
        "MARGINAL",
        f"promoted_avg={promoted_avg:.1f} / demoted_avg={demoted_avg:.1f} 在邊緣，"
        "再觀察一週或先把 CORRECT_COUNT_THRESHOLD 從 3 降到 2 看促進晉升。",
    )


async def _run() -> int:
    sys.path.insert(0, str(Path.home() / "workshop" / "core"))
    from sqlalchemy import select
    from src.modules.memvault.kg_models import KGVerificationRunLog
    from src.shared.database import async_session_factory

    async with async_session_factory() as db:
        stmt = (
            select(KGVerificationRunLog).order_by(KGVerificationRunLog.started_at.desc()).limit(14)
        )
        rows = list((await db.execute(stmt)).scalars().all())

    now = datetime.now(UTC)
    if not rows:
        verdict = "NO_RUNS"
        rec = "weekly job 沒跑過 → 檢查 Cronicle / launchd。"
        promoted_avg = demoted_avg = 0.0
        dry_count = apply_count = 0
    else:
        dry_count = sum(1 for r in rows if r.dry_run)
        apply_count = len(rows) - dry_count
        promoted_avg = sum(r.promoted_count for r in rows) / len(rows)
        demoted_avg = sum(r.demoted_count for r in rows) / len(rows)
        verdict, rec = _classify(promoted_avg, demoted_avg, dry_count)

    lines: list[str] = [
        "# Memvault verification — dry_run 觀察期 review",
        "",
        f"**Generated**: {now.isoformat(timespec='seconds')}",
        f"**Audit rows scanned**: {len(rows)} (limit 14)",
        f"**Dry-run runs**: {dry_count}",
        f"**Apply runs**: {apply_count}",
        f"**Avg promoted / run**: {promoted_avg:.2f}",
        f"**Avg demoted / run**: {demoted_avg:.2f}",
        "",
        f"## Verdict: `{verdict}`",
        "",
        rec,
        "",
        "## Last runs",
        "",
        "| started_at | dry_run | candidates | promoted | demoted |",
        "|------------|---------|------------|----------|---------|",
    ]
    for r in rows[:14]:
        lines.append(
            f"| {r.started_at.isoformat(timespec='seconds')} "
            f"| {r.dry_run} | {r.candidates_scanned} | {r.promoted_count} | {r.demoted_count} |"
        )
    lines.append("")
    lines.append("## Next step")
    lines.append("")
    lines.append(
        "Read this report, then either:\n"
        "1. flip `MEMVAULT_PROMOTE_VERIFIED_DRY_RUN=0` if verdict=READY；\n"
        "2. tune thresholds in `core/src/modules/memvault/kg_verification.py` if verdict in {DEMOTE_HIGH, MARGINAL}；\n"
        "3. debug the CRAG backflow path if verdict=NO_SIGNAL；\n"
        "4. enable `ws-memvault-promote-verified` in Cronicle if verdict=NO_RUNS。"
    )

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] report written: {REPORT_FILE}")

    bark_notify(
        f"📊 memvault verification review — {verdict}",
        f"avg promoted={promoted_avg:.1f} demoted={demoted_avg:.1f} "
        f"({len(rows)} runs)；詳見 outputs/memvault/dry_run_review.md",
    )
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_run())
    except Exception as e:  # pragma: no cover
        print(f"FATAL: {e!r}")
        bark_notify(
            "⚠️ memvault verification review 失敗",
            f"{type(e).__name__}: {e}"[:200],
        )
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
