#!/Users/joneshong/.local/bin/python3
"""
One-time migration: cannibalization.json → intelflow reports

Usage:
    python3 migrate-cannibalize-to-intelflow.py           # create reports via API
    python3 migrate-cannibalize-to-intelflow.py --dry-run  # preview only
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "http://127.0.0.1:8801/api/intelflow/reports"
# Always read from the main workshop vendor dir (canonical source of truth).
# Override via CANNIBALIZE_JSON env var if needed.
_default_json = Path.home() / "workshop" / "vendor" / "cannibalization.json"
CANNIBALIZE_JSON = Path(
    __import__("os").environ.get("CANNIBALIZE_JSON", str(_default_json))
)


def build_content(entry: dict) -> str:
    """Build well-structured markdown from a cannibalization entry."""
    lines = []

    name = entry.get("name", entry["id"])
    lines.append(f"# 蠶食評估報告：{name}\n")  # noqa: RUF001

    # Metadata
    lines.append("## 基本資訊\n")
    lines.append("| 欄位 | 值 |")
    lines.append("|------|---|")
    lines.append(f"| ID | `{entry['id']}` |")
    lines.append(f"| 類型 | {entry.get('type', '—')} |")
    lines.append(f"| 狀態 | {entry.get('status', '—')} |")
    lines.append(f"| 來源 URL | {entry.get('origin_url', '—')} |")
    if entry.get("upstream_ref"):
        lines.append(f"| Upstream Ref | {entry['upstream_ref']} |")
    lines.append(f"| 蠶食日期 | {entry.get('cannibalized_on', '—')} |")

    pinned = entry.get("pinned_at", {})
    if pinned:
        pin_parts = []
        if pinned.get("version"):
            pin_parts.append(f"version={pinned['version']}")
        if pinned.get("commit"):
            pin_parts.append(f"commit={pinned['commit']}")
        if pinned.get("date"):
            pin_parts.append(f"date={pinned['date']}")
        lines.append(f"| 鎖定版本 | {', '.join(pin_parts) if pin_parts else '—'} |")

    lines.append("")

    # Notes (summary paragraph)
    notes = entry.get("notes", "").strip()
    if notes:
        lines.append("## 摘要\n")
        lines.append(notes)
        lines.append("")

    # Extractions table
    extractions = entry.get("extractions", [])
    if extractions:
        lines.append("## 蠶食模式清單\n")
        lines.append("| 模式 | 來源路徑 | 目標路徑 | 改寫說明 |")
        lines.append("|------|---------|---------|---------|")
        for ex in extractions:
            pattern = ex.get("pattern", "").replace("|", "\\|")
            src = ex.get("source_path", "").replace("|", "\\|")
            tgt = ex.get("target_path", "").replace("|", "\\|")
            adapt = ex.get("adaptation", "").replace("|", "\\|")
            lines.append(f"| {pattern} | `{src}` | `{tgt}` | {adapt} |")
        lines.append("")
    else:
        lines.append("## 蠶食模式清單\n")
        lines.append("_無（僅評估，未提取模式）_\n")  # noqa: RUF001

    # Drift info
    drift = entry.get("drift", {})
    if drift:
        lines.append("## Drift 追蹤\n")
        lines.append("| 欄位 | 值 |")
        lines.append("|------|---|")
        lines.append(f"| 偵測方式 | {drift.get('check_method', '—')} |")
        lines.append(f"| 最後檢查 | {drift.get('latest_checked', '—')} |")
        latest_up = drift.get("latest_upstream") or "—"
        lines.append(f"| 最新 Upstream | {latest_up} |")
        lines.append(f"| Drift 等級 | {drift.get('drift_level', '—')} |")
        lines.append("")

    return "\n".join(lines)


def build_payload(entry: dict) -> dict:
    name = entry.get("name", entry["id"])
    eid = entry["id"]
    etype = entry.get("type", "unknown")
    status = entry.get("status", "unknown")
    origin_url = entry.get("origin_url", "")

    tags = ["cannibalize", etype, status, eid]
    # Remove empty/duplicate tags
    tags = list(dict.fromkeys(t for t in tags if t))

    sources = []
    if origin_url:
        sources.append({"url": origin_url, "title": name, "type": etype})

    return {
        "title": f"蠶食評估: {name}",
        "query": f"{eid} 蠶食評估",
        "content": build_content(entry),
        "sources": sources,
        "tags": tags,
        "skill_name": "cannibalize",
    }


def create_report(payload: dict, dry_run: bool) -> str | None:
    """POST to intelflow API. Returns report ID or None on failure."""
    if dry_run:
        print(f"\n[DRY-RUN] Would POST to {API_URL}")
        print(f"  title : {payload['title']}")
        print(f"  query : {payload['query']}")
        print(f"  tags  : {payload['tags']}")
        print(f"  sources: {[s['url'] for s in payload['sources']]}")
        print(f"  content preview ({len(payload['content'])} chars):")
        preview = payload["content"][:300].replace("\n", " ↵ ")
        print(f"    {preview}…")
        return "DRY-RUN"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
            report_id = body.get("id") or body.get("report_id") or str(body)
            return report_id
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"  [ERROR] HTTP {e.code}: {err_body[:200]}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"  [ERROR] Connection failed: {e.reason}", file=sys.stderr)
        return None


def main():
    dry_run = "--dry-run" in sys.argv

    if not CANNIBALIZE_JSON.exists():
        print(f"[FATAL] Cannot find {CANNIBALIZE_JSON}", file=sys.stderr)
        sys.exit(1)

    with open(CANNIBALIZE_JSON, encoding="utf-8") as f:
        data = json.load(f)

    sources = data.get("sources", [])
    print(f"Loaded {len(sources)} sources from cannibalization.json")
    if dry_run:
        print("[DRY-RUN MODE] No API calls will be made.\n")

    results = []
    skipped = []

    for entry in sources:
        eid = entry["id"]
        name = entry.get("name", eid)

        # Skip ghost-os (already migrated)
        if "ghost" in eid.lower():
            print(f"  SKIP  {eid} ({name}) — already migrated (ghost)")
            skipped.append(eid)
            continue

        print(f"  POST  {eid} ({name}) …", end=" ", flush=True)
        payload = build_payload(entry)
        report_id = create_report(payload, dry_run)

        if report_id is not None:
            print(f"OK  id={report_id}")
            results.append({"id": eid, "report_id": report_id})
        else:
            print("FAILED")
            results.append({"id": eid, "report_id": None, "error": True})

    print(f"\n{'='*60}")
    print(f"Summary: {len(results)} processed, {len(skipped)} skipped")
    succeeded = [r for r in results if not r.get("error")]
    failed = [r for r in results if r.get("error")]
    print(f"  Succeeded : {len(succeeded)}")
    print(f"  Failed    : {len(failed)}")
    if succeeded:
        print("\nCreated report IDs:")
        for r in succeeded:
            print(f"  {r['id']:30s} → {r['report_id']}")
    if failed:
        print("\nFailed entries:")
        for r in failed:
            print(f"  {r['id']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
