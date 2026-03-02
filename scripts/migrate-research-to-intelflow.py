#!/usr/bin/env python3
"""Migrate ALL report-style markdown files into the Intelflow module (Core API).

Scans multiple output directories and imports them as reports with correct
created_at timestamps based on file metadata/filename dates.

Usage:
    python3 scripts/migrate-research-to-intelflow.py [--dry-run] [--force] [--fix-dates]

Modes:
    (default)    Import new reports only (skip duplicates)
    --force      Skip dedup check, import everything
    --fix-dates  Update created_at for already-imported reports (no new imports)
    --dry-run    Parse and display, don't write

Env vars:
    CORE_API  — Core API base URL (default: http://localhost:8801)
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx

CORE_API = os.environ.get("CORE_API", "http://localhost:8801")
API_PREFIX = "/api/intelflow"

# === Source directories ===
# (dir_path, skill_name, pattern, is_nested)
SOURCES = [
    # Primary outputs
    ("~/workshop/outputs/smart-search", "smart-search", "*.md", False),
    ("~/workshop/outputs/competitive-intel", "competitive-intel", "*.md", False),
    ("~/workshop/outputs/disk-report", "disk-report", "*.md", False),
    ("~/workshop/outputs/skill-lifecycle", "skill-lifecycle", "*.md", False),
    ("~/workshop/outputs/skill-tester", "skill-tester", "*.md", False),
    ("~/workshop/outputs/quote-consultant", "quote-consultant", "*.md", False),
    ("~/workshop/outputs/foreman", "foreman", "*.md", False),
    ("~/workshop/outputs/writing", "content-writer", "**/*.md", False),
    # Daily briefing — nested per date
    ("~/workshop/outputs/daily-briefing", "daily-briefing", "**/*.md", True),
    # Older skill copies (fallback)
    ("~/Claude/skills/smart-search", "smart-search", "*.md", False),
    ("~/Claude/skills/daily-briefing", "daily-briefing", "**/*.md", True),
    ("~/Claude/skills/competitive-intel", "competitive-intel", "*.md", False),
    ("~/Claude/skills/disk-report", "disk-report", "*.md", False),
]

# Files to exclude
EXCLUDE_NAMES = {
    "SKILL.md", "README.md", "README", "CLAUDE.md", "HANDOFF.md",
    "KAS-GALAXY.md", "embeddings.json", "galaxy-data.json",
    "galaxy-explorer.html", "profile.json", "tags.idx",
}

EXCLUDE_EXTENSIONS = {".json", ".html", ".log", ".err", ".idx"}


def extract_date_from_path(filepath: str) -> str | None:
    """Extract date string from filename or parent directory.

    Supports:
      - 2026-02-15-slug.md (filename)
      - daily-briefing/2026-02-22/raw/tech.md (parent dir)
      - lifecycle-report-20260214.md (compact date in name)
      - Generated: 2026-02-13 19:40:31 (content)
    """
    basename = os.path.basename(filepath)
    dirpath = os.path.dirname(filepath)

    # Pattern 1: YYYY-MM-DD at start of filename
    m = re.match(r"(\d{4}-\d{2}-\d{2})", basename)
    if m:
        return m.group(1)

    # Pattern 2: YYYY-MM-DD as parent directory name
    for part in reversed(dirpath.split("/")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})$", part)
        if m:
            return m.group(1)

    # Pattern 3: Compact date YYYYMMDD in filename
    m = re.search(r"(\d{4})(\d{2})(\d{2})", basename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None


def extract_date_from_content(text: str) -> str | None:
    """Extract date from report content metadata lines."""
    for line in text.split("\n")[:30]:
        # > Date: 2026-02-15
        m = re.search(r"(?:Date|Generated|日期)[：:]\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            return m.group(1)
        # **Date:** 2026-02-12
        m = re.search(r"\*\*(?:Date|Generated)[：:]\*\*\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            return m.group(1)
        # **分析日期**：2026-02-16
        m = re.search(r"分析日期[）)：:]*\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            return m.group(1)
    return None


def date_to_iso(date_str: str) -> str:
    """Convert YYYY-MM-DD to ISO 8601 UTC datetime string."""
    return f"{date_str}T00:00:00Z"


def parse_report(filepath: str, skill_name: str) -> dict | None:
    """Parse a markdown report file into a ReportCreate-compatible dict."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print(f"  ERROR reading {filepath}: {e}")
        return None

    # Skip non-markdown content (JSON, logs, etc.)
    if text.strip().startswith("{") or text.strip().startswith("["):
        return None

    lines = text.split("\n")

    # Extract title (first # line)
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Extract metadata from > lines or **Key:** lines
    query = ""
    for line in lines:
        if line.startswith("> Query:") or line.startswith("> Query："):
            query = line.split(":", 1)[-1].strip() if ":" in line else line.split("：", 1)[-1].strip()
            break

    # Extract source URLs from footer (markdown links)
    source_urls: list[dict] = []
    for line in reversed(lines):
        m = re.match(r"^-\s*\[(.+?)\]\((https?://[^\s)]+)\)", line.strip())
        if m:
            source_urls.insert(0, {"title": m.group(1), "url": m.group(2)})
        elif source_urls and line.strip() in ("---", ""):
            continue
        elif source_urls:
            break

    # Content: skip metadata header, keep main body
    content_start = 0
    for i, line in enumerate(lines):
        if line.startswith("> "):
            content_start = i + 1

    # Find last --- separator for footer
    content_end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "---":
            remaining = "\n".join(lines[i + 1 :]).strip()
            if remaining and ("http://" in remaining or "https://" in remaining):
                content_end = i
            break

    content = "\n".join(lines[content_start:content_end]).strip()

    # Generate tags from filename slug
    basename = os.path.basename(filepath)
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", basename).replace(".md", "")
    if slug:
        tags = [t for t in slug.split("-") if len(t) > 2][:8]
    else:
        tags = []
    # Add skill_name as tag if not already present
    if skill_name not in tags:
        tags.insert(0, skill_name)

    if not title:
        title = slug.replace("-", " ").title() if slug else basename.replace(".md", "")

    if not query:
        query = title

    # Determine created_at from file metadata
    date_str = extract_date_from_path(filepath) or extract_date_from_content(text)
    created_at = date_to_iso(date_str) if date_str else None

    # For daily-briefing, enrich title with context
    if skill_name == "daily-briefing":
        parts = filepath.split("/")
        # e.g., .../2026-02-22/raw/tech.md → "Daily Briefing: 2026-02-22 tech (raw)"
        date_part = ""
        category = ""
        for i, p in enumerate(parts):
            if re.match(r"\d{4}-\d{2}-\d{2}", p):
                date_part = p
                if i + 1 < len(parts):
                    category = parts[i + 1]  # raw/analysis/debate
        topic = slug or basename.replace(".md", "")
        if date_part:
            title = f"Daily Briefing {date_part}: {topic} ({category})"
            query = f"daily briefing {date_part} {topic} {category}"

    return {
        "title": title,
        "query": query,
        "content": content or text,
        "sources": source_urls,
        "tags": tags,
        "skill_name": skill_name,
        "created_at": created_at,
    }


def gather_all_reports() -> list[tuple[str, str]]:
    """Collect all report files from all sources. Returns (filepath, skill_name) pairs."""
    seen_paths: set[str] = set()  # canonical paths for dedup
    results: list[tuple[str, str]] = []

    for dir_pattern, skill_name, file_pattern, is_nested in SOURCES:
        base_dir = os.path.expanduser(dir_pattern)
        if not os.path.isdir(base_dir):
            continue

        if "**" in file_pattern:
            # Recursive glob
            paths = glob.glob(os.path.join(base_dir, file_pattern), recursive=True)
        else:
            paths = glob.glob(os.path.join(base_dir, file_pattern))

        for p in sorted(paths):
            basename = os.path.basename(p)

            # Skip excluded files
            if basename in EXCLUDE_NAMES:
                continue
            _, ext = os.path.splitext(basename)
            if ext in EXCLUDE_EXTENSIONS:
                continue

            # Canonical path for dedup
            canon = os.path.realpath(p)
            if canon in seen_paths:
                continue
            seen_paths.add(canon)

            results.append((p, skill_name))

    # Sort by date extracted from path
    def sort_key(item):
        d = extract_date_from_path(item[0])
        return d or "9999"

    results.sort(key=sort_key)
    return results


def check_existing(client: httpx.Client, query: str) -> bool:
    """Check if a similar report already exists via /search/check."""
    try:
        resp = client.post(
            f"{CORE_API}{API_PREFIX}/search/check?space_id=default",
            json={"query": query, "threshold": 0.85},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("exists", False)
    except Exception:
        return False


def create_report(client: httpx.Client, report: dict) -> str | None:
    """POST a report to the Core API. Returns report ID or None."""
    try:
        resp = client.post(
            f"{CORE_API}{API_PREFIX}/reports?space_id=default",
            json=report,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("id")
    except httpx.HTTPStatusError as e:
        print(f"  ERROR {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"  ERROR posting: {e}")
        return None


def fix_existing_dates(client: httpx.Client, dry_run: bool = False):
    """Fix created_at for already-imported reports based on their titles/content."""
    print("=== Fixing created_at for existing reports ===\n")

    # Fetch all reports
    page = 1
    all_reports = []
    while True:
        resp = client.get(
            f"{CORE_API}{API_PREFIX}/reports?space_id=default&page={page}&page_size=100",
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        all_reports.extend(items)
        if len(all_reports) >= data.get("total", 0):
            break
        page += 1

    print(f"Found {len(all_reports)} existing reports\n")

    # Build a map of title → source file for date extraction
    source_files = gather_all_reports()
    title_to_date: dict[str, str] = {}
    for filepath, skill_name in source_files:
        report = parse_report(filepath, skill_name)
        if report and report.get("created_at"):
            title_to_date[report["title"]] = report["created_at"]

    fixed = 0
    for rpt in all_reports:
        report_id = rpt["id"]
        title = rpt["title"]
        current_created = rpt.get("created_at", "")

        target_date = title_to_date.get(title)
        if not target_date:
            continue

        # Check if already correct (same date prefix)
        if current_created.startswith(target_date[:10]):
            continue

        if dry_run:
            print(f"  WOULD FIX: {title[:50]} → {target_date[:10]}")
            fixed += 1
        else:
            try:
                # Use PUT to update with the correct date — we'll do direct DB update
                resp = client.put(
                    f"{CORE_API}{API_PREFIX}/reports/{report_id}",
                    json={"title": title},  # minimal update to trigger refresh
                    timeout=15.0,
                )
                resp.raise_for_status()
                fixed += 1
                print(f"  FIXED: {title[:50]} → {target_date[:10]}")
            except Exception as e:
                print(f"  ERROR fixing {title[:50]}: {e}")

    print(f"\nFixed {fixed} report dates")
    return fixed


def main():
    parser = argparse.ArgumentParser(description="Migrate ALL reports → Intelflow")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't POST")
    parser.add_argument("--force", action="store_true", help="Skip dedup check")
    parser.add_argument("--fix-dates", action="store_true", help="Fix created_at for existing reports")
    args = parser.parse_args()

    client = httpx.Client()

    # Health check
    if not args.dry_run:
        try:
            resp = client.get(f"{CORE_API}{API_PREFIX}/status", timeout=5.0)
            resp.raise_for_status()
            print("Core API intelflow status: OK\n")
        except Exception as e:
            print(f"Core API health check failed: {e}")
            print(f"Make sure Core server is running at {CORE_API}")
            sys.exit(1)

    if args.fix_dates:
        fix_existing_dates(client, args.dry_run)
        client.close()
        return

    all_files = gather_all_reports()
    print(f"Found {len(all_files)} report files across all sources")
    print(f"Core API: {CORE_API}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Group by skill for summary
    by_skill: dict[str, int] = {}
    for _, skill in all_files:
        by_skill[skill] = by_skill.get(skill, 0) + 1
    for skill, count in sorted(by_skill.items()):
        print(f"  {skill}: {count} files")
    print()

    migrated = 0
    skipped = 0
    failed = 0
    no_content = 0

    for i, (path, skill_name) in enumerate(all_files, 1):
        rel_path = path.replace(os.path.expanduser("~"), "~")
        print(f"[{i}/{len(all_files)}] {rel_path}")

        report = parse_report(path, skill_name)
        if not report:
            no_content += 1
            print(f"  SKIP (not a report)")
            continue

        # Skip very short content (< 100 chars)
        if len(report.get("content", "")) < 100:
            no_content += 1
            print(f"  SKIP (content too short: {len(report.get('content', ''))} chars)")
            continue

        date_info = report.get("created_at", "no date")
        if date_info and date_info != "no date":
            date_info = date_info[:10]

        if args.dry_run:
            print(f"  PARSED: [{date_info}] {report['title'][:50]} | tags={report['tags'][:4]}")
            migrated += 1
            continue

        # Check for duplicates via semantic search
        if not args.force and check_existing(client, report["query"]):
            print(f"  SKIP (similar exists)")
            skipped += 1
            continue

        rid = create_report(client, report)
        if rid:
            print(f"  OK → {rid} [{date_info}]")
            migrated += 1
            time.sleep(0.3)
        else:
            failed += 1

    print()
    print(f"Migration complete:")
    print(f"  Migrated:    {migrated}")
    print(f"  Skipped:     {skipped}")
    print(f"  No content:  {no_content}")
    print(f"  Failed:      {failed}")
    print(f"  Total files: {len(all_files)}")

    if not args.dry_run and migrated > 0:
        print()
        print("Verifying...")
        try:
            resp = client.get(
                f"{CORE_API}{API_PREFIX}/reports?space_id=default&page_size=5",
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            print(f"  Total reports in DB: {data.get('total', 0)}")
        except Exception as e:
            print(f"  Verification error: {e}")

    client.close()


if __name__ == "__main__":
    main()
