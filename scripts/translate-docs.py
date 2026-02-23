#!/usr/bin/env python3
"""Translate Workshop docs (en → zh-TW) with automatic version tracking.

Tracks changes via content hash in YAML frontmatter. When content changes,
doc_version auto-increments. Translation only runs for version mismatches.

Usage:
    # Translate all docs (recursive scan of docs/ + root .md)
    python3 scripts/translate-docs.py

    # Translate a specific directory
    python3 scripts/translate-docs.py docs/vision/

    # Translate a single file
    python3 scripts/translate-docs.py docs/vision/roadmap.md

    # Force re-translate everything
    python3 scripts/translate-docs.py --force

    # Dry run — show what would change
    python3 scripts/translate-docs.py --dry-run

    # Just update versions (no translation)
    python3 scripts/translate-docs.py --version-only

    # Status — show version comparison table
    python3 scripts/translate-docs.py --status

Structure:
    docs/vision/roadmap.md       → docs/zh-TW/vision/roadmap.zh-TW.md
    docs/architecture/auth.md    → docs/zh-TW/architecture/auth.zh-TW.md
    CLAUDE.md                    → docs/zh-TW/CLAUDE.zh-TW.md
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# --- Constants ---

WORKSHOP_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = WORKSHOP_ROOT / "docs"

# Directories to skip during discovery
EXCLUDE_DIRS = {"zh-TW", "zh-CN", "ja", "ko", "api", "guides", "runbooks"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

LANG_MAP = {
    "zh-TW": "Traditional Chinese (繁體中文)",
    "zh-CN": "Simplified Chinese (简体中文)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
}

TRANSLATE_PROMPT = """Translate the following Markdown document from English to {lang_name}.

Rules:
1. Preserve the YAML frontmatter block (between --- markers) EXACTLY as-is — do NOT translate it
2. Keep ALL Markdown formatting identical (headers, tables, code blocks, lists, links)
3. Keep ALL code blocks, SQL, CLI examples, and technical identifiers unchanged
4. Keep ALL file paths, URLs, module names, and technical terms in original form
5. Only translate natural language prose (descriptions, explanations, rationale)
6. Keep ASCII art diagrams and their structure unchanged
7. Maintain exact same document structure — same sections, same ordering
8. Do not add, remove, or reorder any content
9. Output ONLY the translated document with frontmatter included, no commentary

Document:
{content}"""


# --- Frontmatter helpers ---

def parse_frontmatter(text: str) -> "tuple[dict, str]":
    """Parse YAML frontmatter from markdown. Returns (metadata_dict, body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip()
            if val.isdigit():
                val = int(val)
            meta[key.strip()] = val

    body = text[m.end():]
    return meta, body


def render_frontmatter(meta: dict) -> str:
    """Render metadata dict as YAML frontmatter string."""
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def content_hash(body: str) -> str:
    """Compute short hash of document body (excluding frontmatter)."""
    h = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()
    return h[:8]


# --- File discovery ---

def discover_sources(target: Optional[Path] = None) -> list:
    """Find all translatable .md files."""
    if target and target.is_file():
        return [target.resolve()]

    sources = []

    if target and target.is_dir():
        scan_dir = target.resolve()
    else:
        scan_dir = DOCS_DIR

    # Recursive scan
    for md in sorted(scan_dir.rglob("*.md")):
        try:
            rel = md.relative_to(DOCS_DIR)
            parts = rel.parts
        except ValueError:
            parts = ()

        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        sources.append(md)

    # Also include root-level .md if scanning whole project
    if not target or (target.is_dir() and target.resolve() == DOCS_DIR):
        for md in sorted(WORKSHOP_ROOT.glob("*.md")):
            sources.append(md)

    return sources


def get_target_path(src: Path, lang: str) -> Path:
    """Map source .md path to translation target path.

    docs/vision/roadmap.md → docs/zh-TW/vision/roadmap.zh-TW.md
    CLAUDE.md              → docs/zh-TW/CLAUDE.zh-TW.md
    """
    lang_dir = DOCS_DIR / lang

    if src.is_relative_to(DOCS_DIR):
        rel = src.relative_to(DOCS_DIR)
    else:
        rel = src.relative_to(WORKSHOP_ROOT)

    stem = rel.stem
    new_name = f"{stem}.{lang}.md"
    return lang_dir / rel.parent / new_name


# --- Version management ---

def update_source_version(src: Path, dry_run: bool = False) -> "tuple[int, bool]":
    """Check if source content changed; bump version if needed.

    Returns (current_version, was_bumped).
    """
    text = src.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    current_hash = content_hash(body)
    stored_hash = str(meta.get("content_hash", ""))  # may be parsed as int if all-digit
    version = meta.get("doc_version", 0)

    if current_hash == stored_hash and version > 0:
        return version, False

    # Content changed or first init
    if current_hash != stored_hash:
        new_version = version + 1
    else:
        new_version = version or 1

    meta["doc_version"] = new_version
    meta["content_hash"] = current_hash

    if not dry_run:
        # Ensure exactly one blank line between frontmatter and body
        body_stripped = body.lstrip("\n")
        new_text = render_frontmatter(meta) + "\n" + body_stripped
        src.write_text(new_text, encoding="utf-8")

    return new_version, True


def get_target_version(dst: Path) -> int:
    """Read source_version from translation file. Returns 0 if not exists."""
    if not dst.exists():
        return 0
    text = dst.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(text)
    v = meta.get("source_version", 0)
    return int(v) if isinstance(v, str) and v.isdigit() else (v if isinstance(v, int) else 0)


def set_target_version(dst: Path, version: int):
    """Update source_version and translated_at in target file."""
    text = dst.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    meta["source_version"] = version
    meta["translated_at"] = str(date.today())
    body_stripped = body.lstrip("\n")
    new_text = render_frontmatter(meta) + "\n" + body_stripped
    dst.write_text(new_text, encoding="utf-8")


# --- Translation ---

def translate_file(src: Path, dst: Path, lang_name: str) -> bool:
    """Translate a single file via Gemini CLI."""
    text = src.read_text(encoding="utf-8")
    prompt = TRANSLATE_PROMPT.format(lang_name=lang_name, content=text)

    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode != 0:
            print(f"  ERROR: Gemini CLI failed: {result.stderr.strip()[:200]}")
            return False

        output = result.stdout.strip()

        # Strip markdown fences if Gemini wraps the output
        for prefix in ("```markdown", "```md", "```"):
            if output.startswith(prefix):
                output = output[len(prefix):].strip()
                break
        if output.endswith("```"):
            output = output[:-3].strip()

        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(output + "\n", encoding="utf-8")
        return True

    except subprocess.TimeoutExpired:
        print("  ERROR: Gemini CLI timed out (180s)")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


# --- Commands ---

def cmd_status(sources: list[Path], lang: str):
    """Show version comparison table."""
    print(f"{'File':<55} {'Ver':>4} {'Trans':>6} {'Status':<10}")
    print("-" * 80)

    for src in sources:
        rel = src.relative_to(WORKSHOP_ROOT)
        text = src.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)

        src_ver = meta.get("doc_version", 0)
        current_hash = content_hash(body)
        stored_hash = str(meta.get("content_hash", ""))

        dst = get_target_path(src, lang)
        dst_ver = get_target_version(dst)

        if src_ver == 0:
            status = "NO_META"
        elif current_hash != stored_hash:
            status = "CHANGED"
        elif dst_ver == 0:
            status = "NO_TRANS"
        elif dst_ver < src_ver:
            status = "OUTDATED"
        else:
            status = "OK"

        print(f"{str(rel):<55} {src_ver:>4} {dst_ver:>6} {status:<10}")


def cmd_translate(sources: list[Path], lang: str, lang_name: str,
                  force: bool, dry_run: bool, version_only: bool):
    """Main translate workflow."""
    translated = 0
    skipped = 0
    failed = 0
    bumped = 0

    print(f"Language: {lang_name}")
    print(f"Target:   {DOCS_DIR / lang}/")
    print(f"Sources:  {len(sources)} files")
    print()

    for src in sources:
        rel = src.relative_to(WORKSHOP_ROOT)
        dst = get_target_path(src, lang)

        # Step 1: Update source version
        src_ver, was_bumped = update_source_version(src, dry_run)
        if was_bumped:
            bumped += 1
            print(f"  BUMP    {rel} → v{src_ver}")

        if version_only:
            continue

        # Step 2: Check if translation needed
        dst_ver = get_target_version(dst)
        needs_translate = force or (src_ver != dst_ver)

        if not needs_translate:
            skipped += 1
            continue

        dst_rel = dst.relative_to(WORKSHOP_ROOT)

        if dry_run:
            print(f"  WOULD   {rel} (v{src_ver}) → {dst_rel}")
            translated += 1
            continue

        print(f"  TRANSLATE  {rel} (v{src_ver}) ...", end=" ", flush=True)
        ok = translate_file(src, dst, lang_name)

        if ok:
            set_target_version(dst, src_ver)
            print("OK")
            translated += 1
        else:
            failed += 1

    print()
    parts = []
    if bumped:
        parts.append(f"{bumped} versioned")
    if translated:
        parts.append(f"{translated} translated")
    if skipped:
        parts.append(f"{skipped} up-to-date")
    if failed:
        parts.append(f"{failed} failed")
    print(f"Done: {', '.join(parts) or 'nothing to do'}")

    if failed > 0:
        sys.exit(1)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="Translate Workshop docs with version tracking (Gemini CLI)"
    )
    parser.add_argument(
        "path", nargs="?", default=None,
        help="File or directory to translate (default: all docs/)"
    )
    parser.add_argument(
        "--lang", default="zh-TW", choices=LANG_MAP.keys(),
        help="Target language (default: zh-TW)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-translate all files"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without doing it"
    )
    parser.add_argument(
        "--version-only", action="store_true",
        help="Only update source versions, skip translation"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show version comparison table"
    )
    args = parser.parse_args()

    target = Path(args.path) if args.path else None
    sources = discover_sources(target)

    if not sources:
        print("No .md files found")
        sys.exit(0)

    lang_name = LANG_MAP[args.lang]

    if args.status:
        cmd_status(sources, args.lang)
    else:
        cmd_translate(sources, args.lang, lang_name,
                      args.force, args.dry_run, args.version_only)


if __name__ == "__main__":
    main()
