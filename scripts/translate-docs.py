#!/usr/bin/env python3
"""Translate Workshop .md files to any target language without mutating sources.

Two strategies based on file location:
  - docs/ files   → mirror to docs-<lang>/  (centralized architecture docs)
  - other files   → in-place sibling        (module-level READMEs etc.)

Tracks changes via source content hash stored in translation files.
Translation only runs when source hash mismatches or target is missing.

Usage:
    # Translate all .md files to zh-TW (default)
    python3 scripts/translate-docs.py

    # Translate to a specific language
    python3 scripts/translate-docs.py --lang ja
    python3 scripts/translate-docs.py --lang en

    # Translate a specific file
    python3 scripts/translate-docs.py docs/vision/roadmap.md
    python3 scripts/translate-docs.py core/README.md

    # Force re-translate everything
    python3 scripts/translate-docs.py --force

    # Dry run — show what would change
    python3 scripts/translate-docs.py --dry-run

    # Just mirror/create target files (no translation)
    python3 scripts/translate-docs.py --version-only

    # Status — show version comparison table
    python3 scripts/translate-docs.py --status

    # Status for a specific language
    python3 scripts/translate-docs.py --status --lang ja

Output mapping:
    docs/vision/roadmap.md       → docs-en/vision/roadmap.md      (mirror)
    docs/architecture/auth.md    → docs-ja/architecture/auth.md    (mirror)
    core/README.md               → core/README.en.md               (in-place)
    stations/envkit/README.md    → stations/envkit/README.ja.md    (in-place)
    CLAUDE.md                    → CLAUDE.en.md                    (in-place)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import signal
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# --- Constants ---

WORKSHOP_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = WORKSHOP_ROOT / "docs"

# Subdirectories to skip within docs/
EXCLUDE_DOCS_SUBDIRS = {"api", "guides", "runbooks"}

# Directories to skip during global discovery (dependencies, build artifacts, etc.)
GLOBAL_EXCLUDE_DIRS = {
    "node_modules", ".venv", "backup", ".git", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

# Match translation output directories: docs-en/, docs-ja/, etc.
DOCS_LANG_DIR_RE = re.compile(r"^docs-[a-zA-Z]")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Language display names for prompts
LANG_NAMES = {
    "en": "English",
    "zh-TW": "Traditional Chinese",
    "zh-CN": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

# Match already-translated sibling files: README.en.md, v2-blueprint.zh-tw.md, etc.
_LANG_SUFFIXES = "|".join(re.escape(k) for k in LANG_NAMES)
TRANSLATED_FILE_RE = re.compile(rf"\.({_LANG_SUFFIXES})\.md$", re.IGNORECASE)

TRANSLATE_PROMPT = """Translate the following Markdown document from {source_lang_name} to {target_lang_name}.

Rules:
1. Preserve the YAML frontmatter block (between --- markers) EXACTLY as-is — do NOT translate it
2. Keep ALL Markdown formatting identical (headers, tables, code blocks, lists, links)
3. Keep ALL code blocks, SQL, CLI examples, and technical identifiers unchanged
4. Keep ALL file paths, URLs, module names, and technical terms in original form
5. Only translate natural language prose (descriptions, explanations, rationale)
6. Keep ASCII art diagrams and their structure unchanged
7. Maintain exact same document structure — same sections, same ordering
8. Do not add, remove, or reorder any content
9. If some content is already in the target language, keep it as-is
10. Output ONLY the translated document with frontmatter included, no commentary

Document:
{content}"""

# Known MCP stderr noise patterns (non-fatal)
MCP_NOISE_RE = re.compile(
    r"("
    r"Error during discovery for MCP server|"
    r"MCP error -\d+|"
    r"Connection closed|"
    r"Loaded cached credentials|"
    r"could not determine executable to run|"
    r"supports tool updates|"
    r"supports resource updates|"
    r"listening for chang"
    r")",
    re.IGNORECASE,
)

LATIN_TARGETS = {"en", "fr", "de", "es"}

# Dynamic timeout: BASE + content_length / CHARS_PER_SEC, capped at MAX
TIMEOUT_BASE_S = 60       # minimum timeout for any file
TIMEOUT_CHARS_PER_SEC = 100  # ~1KB = 10s additional
TIMEOUT_MAX_S = 600       # 10 minute hard cap


# --- Frontmatter helpers ---

def parse_frontmatter(text: str) -> tuple[dict, str]:
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

def discover_sources(target: Optional[Path] = None) -> list[Path]:
    """Find all translatable .md files in the workshop.

    Scans the entire WORKSHOP_ROOT, skipping:
    - Dependency/build dirs (node_modules, .venv, __pycache__, etc.)
    - Translation output dirs (docs-en/, docs-ja/, etc.)
    - Already-translated sibling files (README.en.md, etc.)
    - Excluded docs subdirs (api/, guides/, runbooks/)
    """
    if target and target.is_file():
        return [target.resolve()]

    if target and target.is_dir():
        scan_dir = target.resolve()
    else:
        scan_dir = WORKSHOP_ROOT

    sources = []
    for md in sorted(scan_dir.rglob("*.md")):
        rel = md.relative_to(WORKSHOP_ROOT)
        parts = rel.parts

        # Skip dependency/build directories
        if any(p in GLOBAL_EXCLUDE_DIRS for p in parts):
            continue

        # Skip translation output directories (docs-en/, docs-ja/, etc.)
        if parts and DOCS_LANG_DIR_RE.match(parts[0]):
            continue

        # Skip excluded subdirs within docs/
        if parts and parts[0] == "docs" and any(p in EXCLUDE_DOCS_SUBDIRS for p in parts):
            continue

        # Skip already-translated sibling files (README.en.md, etc.)
        if TRANSLATED_FILE_RE.search(md.name):
            continue

        sources.append(md)

    return sources


def is_docs_source(src: Path) -> bool:
    """Check if source belongs to docs/ (uses mirror strategy)."""
    try:
        src.relative_to(DOCS_DIR)
        return True
    except ValueError:
        return False


def get_target_dir(lang: str) -> Path:
    """Get target directory for a language: docs-<lang>/"""
    return WORKSHOP_ROOT / f"docs-{lang}"


def get_target_path(src: Path, lang: str) -> Path:
    """Map source .md path to translation target path.

    docs/ files  → mirror:    docs/vision/roadmap.md → docs-en/vision/roadmap.md
    other files  → in-place:  core/README.md         → core/README.en.md
    """
    if is_docs_source(src):
        # Mirror strategy for docs/
        target_dir = get_target_dir(lang)
        rel = src.relative_to(DOCS_DIR)
        return target_dir / rel
    else:
        # In-place sibling strategy for module files
        return src.parent / f"{src.stem}.{lang}.md"


# --- Sync metadata ---

def get_source_hash(src: Path) -> str:
    """Compute source hash from source body (never mutates source)."""
    text = src.read_text(encoding="utf-8")
    _, body = parse_frontmatter(text)
    return content_hash(body)


def get_target_source_hash(dst: Path) -> str:
    """Read source_hash from translation file. Returns empty string if missing."""
    if not dst.exists():
        return ""
    text = dst.read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(text)
    return str(meta.get("source_hash", ""))


def get_lang_name(lang_code: str) -> str:
    """Return human-readable language name for prompt text."""
    return LANG_NAMES.get(lang_code, lang_code)


def needs_retranslate_due_to_suspect_copy(src: Path, dst: Path, target_lang: str) -> bool:
    """Detect stale target file that appears to be an untranslated source copy.

    If source and target bodies are identical while language differs, force re-translate.
    """
    if not dst.exists():
        return False

    src_text = src.read_text(encoding="utf-8")
    src_meta, src_body = parse_frontmatter(src_text)
    src_lang = str(src_meta.get("target_lang", "en"))

    dst_text = dst.read_text(encoding="utf-8")
    _, dst_body = parse_frontmatter(dst_text)

    if src_lang == target_lang:
        return False

    if src_body.strip() == dst_body.strip():
        return True

    # Guardrail: for Latin-script targets, a high CJK ratio likely means
    # translation did not actually happen or preserved the wrong language.
    if target_lang in LATIN_TARGETS:
        letters = [ch for ch in dst_body if ch.isalpha()]
        if len(letters) >= 80:
            cjk_letters = sum(1 for ch in letters if "\u4e00" <= ch <= "\u9fff")
            if (cjk_letters / len(letters)) > 0.10:
                return True

    return False


def mirror_source_to_target(src: Path, dst: Path, dry_run: bool = False) -> bool:
    """Mirror source file to target path with identical filename and structure."""
    src_text = src.read_text(encoding="utf-8")
    if dst.exists():
        dst_text = dst.read_text(encoding="utf-8")
        if dst_text == src_text:
            return False
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src_text, encoding="utf-8")
    return True


def set_target_metadata(dst: Path, source_hash: str, source_lang: str, target_lang: str):
    """Update metadata in translated file for future hash-based sync."""
    text = dst.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    meta["source_hash"] = source_hash
    meta["source_lang"] = source_lang
    meta["target_lang"] = target_lang
    meta["translated_at"] = str(date.today())
    body_stripped = body.lstrip("\n")
    new_text = render_frontmatter(meta) + "\n" + body_stripped
    dst.write_text(new_text, encoding="utf-8")


# --- Translation ---

def _strip_cli_noise(text: str) -> str:
    """Remove CLI hook output and other noise from Gemini CLI stdout."""
    noise_patterns = re.compile(
        r"^("
        r"Created execution plan for .*|"
        r"Expanding hook command:.*|"
        r"Hook \w+ completed.*|"
        r"Running hook:.*"
        r")$"
    )
    lines = text.split("\n")
    cleaned = [ln for ln in lines if not noise_patterns.match(ln.strip())]
    return "\n".join(cleaned)


def _is_mcp_noise_only(stderr: str) -> bool:
    """Check if stderr contains only MCP server noise (non-fatal errors)."""
    if not stderr.strip():
        return True
    # Remove ANSI escape sequences that may be emitted by CLI wrappers.
    ansi_re = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
    for line in stderr.strip().splitlines():
        line = ansi_re.sub("", line).strip()
        if not line:
            continue
        if not MCP_NOISE_RE.search(line):
            return False
    return True


def _looks_like_markdown(text: str) -> bool:
    """Quick heuristic: does the output look like valid markdown content?"""
    if len(text.strip()) < 20:
        return False
    # Should contain at least one markdown heading or frontmatter
    return bool(re.search(r"(^#{1,6}\s|^---\s*$)", text, re.MULTILINE))


def _compute_timeout(content_length: int) -> int:
    """Compute dynamic timeout based on content length (in chars)."""
    timeout = TIMEOUT_BASE_S + content_length // TIMEOUT_CHARS_PER_SEC
    return min(timeout, TIMEOUT_MAX_S)


def translate_file(src: Path, dst: Path, lang: str) -> bool:
    """Translate a single file via Gemini CLI."""
    text = src.read_text(encoding="utf-8")
    src_meta, _ = parse_frontmatter(text)
    source_lang = str(src_meta.get("target_lang", "en"))

    timeout = _compute_timeout(len(text))

    prompt = TRANSLATE_PROMPT.format(
        source_lang_name=get_lang_name(source_lang),
        target_lang_name=get_lang_name(lang),
        content=text,
    )

    try:
        proc = subprocess.Popen(
            ["gemini", "-p", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except KeyboardInterrupt:
            # Ensure child process group is terminated when user presses Ctrl+C.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            raise
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = proc.communicate(timeout=3)
            except Exception:
                stdout, stderr = "", ""
            print(f"\n  ERROR: Gemini CLI timed out ({timeout}s)")
            return False

        result = subprocess.CompletedProcess(
            args=["gemini", "-p", prompt],
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

        output = _strip_cli_noise(result.stdout).strip()

        # Handle non-zero exit: if stderr is only MCP noise and stdout has
        # valid markdown, treat as success (Gemini MCP server errors are non-fatal)
        if result.returncode != 0:
            if _is_mcp_noise_only(result.stderr) and _looks_like_markdown(output):
                # MCP noise only — ignore stderr, use stdout
                pass
            else:
                # Real error
                stderr_preview = result.stderr.strip()[:300]
                print(f"\n  ERROR: Gemini CLI failed (exit {result.returncode}): {stderr_preview}")
                return False

        if not _looks_like_markdown(output):
            print(f"\n  ERROR: Gemini returned invalid output ({len(output)} chars)")
            return False

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

    except KeyboardInterrupt:
        raise
    except FileNotFoundError:
        print(f"\n  ERROR: 'gemini' command not found. Install Gemini CLI first.")
        return False
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return False


# --- Commands ---

def _print_status_line(src: Path, lang: str):
    """Print a single status line for a source file."""
    rel = src.relative_to(WORKSHOP_ROOT)
    src_hash = get_source_hash(src)
    dst = get_target_path(src, lang)
    dst_hash = get_target_source_hash(dst)

    if not dst.exists():
        status = "NO_TRANS"
    elif dst_hash != src_hash:
        status = "OUTDATED"
    elif needs_retranslate_due_to_suspect_copy(src, dst, lang):
        status = "SUSPECT"
    else:
        status = "OK"

    print(f"  {str(rel):<53} {src_hash:<10} {status:<10}")


def cmd_status(sources: list[Path], lang: str):
    """Show version comparison table for a specific language."""
    lang_name = get_lang_name(lang)
    target_dir = get_target_dir(lang)

    docs_sources = [s for s in sources if is_docs_source(s)]
    module_sources = [s for s in sources if not is_docs_source(s)]

    print(f"Language:  {lang_name} ({lang})")
    print(f"Total:     {len(sources)} source files")
    print()

    if docs_sources:
        print(f"=== docs/ → {target_dir.relative_to(WORKSHOP_ROOT)}/ (mirror) [{len(docs_sources)} files] ===")
        print(f"  {'File':<53} {'Hash':<10} {'Status':<10}")
        print(f"  {'-' * 73}")
        for src in docs_sources:
            _print_status_line(src, lang)
        print()

    if module_sources:
        print(f"=== modules → *.{lang}.md (in-place) [{len(module_sources)} files] ===")
        print(f"  {'File':<53} {'Hash':<10} {'Status':<10}")
        print(f"  {'-' * 73}")
        for src in module_sources:
            _print_status_line(src, lang)
        print()


def cmd_translate(sources: list[Path], lang: str,
                  force: bool, dry_run: bool, version_only: bool):
    """Main translate workflow."""
    translated = 0
    skipped = 0
    failed = 0
    mirrored = 0

    lang_name = get_lang_name(lang)
    target_dir = get_target_dir(lang)

    docs_count = sum(1 for s in sources if is_docs_source(s))
    module_count = len(sources) - docs_count

    print(f"Target:    {lang_name} ({lang})")
    print(f"Sources:   {len(sources)} files ({docs_count} docs/ → {target_dir.relative_to(WORKSHOP_ROOT)}/, {module_count} modules → *.{lang}.md)")
    print()

    for src in sources:
        rel = src.relative_to(WORKSHOP_ROOT)
        dst = get_target_path(src, lang)

        src_hash = get_source_hash(src)
        dst_hash = get_target_source_hash(dst)
        needs_translate = force or (src_hash != dst_hash)
        if not needs_translate and needs_retranslate_due_to_suspect_copy(src, dst, lang):
            needs_translate = True
            print(f"  RETRY   {rel} (detected untranslated copy)")

        # Step 1: mirror only when target is missing or a translation refresh is needed.
        should_mirror = version_only or (not dst.exists()) or needs_translate
        did_mirror = False
        if should_mirror:
            did_mirror = mirror_source_to_target(src, dst, dry_run=dry_run)
        if did_mirror:
            mirrored += 1
            print(f"  MIRROR  {rel} → {dst.relative_to(WORKSHOP_ROOT)}")

        if version_only:
            continue

        # Step 2: translate only when needed
        if not needs_translate:
            skipped += 1
            continue

        dst_rel = dst.relative_to(WORKSHOP_ROOT)

        if dry_run:
            print(f"  WOULD   {rel} ({src_hash}) → {dst_rel}")
            translated += 1
            continue

        print(f"  TRANSLATE  {rel} ({src_hash}) ...", end=" ", flush=True)
        ok = translate_file(src, dst, lang)

        if ok:
            src_text = src.read_text(encoding="utf-8")
            src_meta, _ = parse_frontmatter(src_text)
            source_lang = str(src_meta.get("target_lang", "en"))
            set_target_metadata(dst, src_hash, source_lang, lang)
            print("OK")
            translated += 1
        else:
            failed += 1

    print()
    parts = []
    if mirrored:
        parts.append(f"{mirrored} mirrored")
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
        description="Translate all workshop .md files: docs/ mirror to docs-<lang>/, others in-place as *.lang.md"
    )
    parser.add_argument(
        "path", nargs="?", default=None,
        help="File or directory to translate (default: all .md files in workshop)"
    )
    parser.add_argument(
        "--lang", default="zh-TW",
        help="Target language code (default: zh-TW). Examples: zh-TW, ja, ko, zh-CN, es, fr, de"
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
        help="Only create target files (mirror/sibling), skip translation"
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

    try:
        if args.status:
            cmd_status(sources, args.lang)
        else:
            cmd_translate(sources, args.lang, args.force, args.dry_run, args.version_only)
    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl+C).")
        sys.exit(130)


if __name__ == "__main__":
    main()
