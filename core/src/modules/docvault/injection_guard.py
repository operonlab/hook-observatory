"""DocVault Injection Guard — document content safety checks.

Prevents injection attacks via document content that could:
  1. Manipulate LLM system prompts during QA synthesis
  2. Inject malicious instructions into chunk embeddings
  3. Smuggle prompt injection via document metadata/titles

Follows memvault's injection guard pattern adapted for document context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Known prompt injection patterns (case-insensitive)
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?above",
    r"you\s+are\s+now\s+(?:a|an)\s+\w+",
    r"system\s*:\s*you\s+are",
    r"<\s*system\s*>",
    r"\[\s*INST\s*\]",
    r"BEGIN\s+INJECTION",
    r"OVERRIDE\s+SAFETY",
    r"<<\s*SYS\s*>>",
    r"human:\s*assistant:",
    r"\\n\\nHuman:",
    r"jailbreak",
    r"DAN\s+mode",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]

# Suspicious metadata keys that shouldn't appear in document metadata
_SUSPICIOUS_META_KEYS = {
    "system_prompt", "instructions", "role", "persona",
    "override", "inject", "payload", "exec", "eval",
}

# Maximum allowed content length for a single chunk (prevent resource exhaustion)
MAX_CHUNK_LENGTH = 50_000  # 50KB


@dataclass
class GuardResult:
    """Result of an injection guard check."""

    safe: bool
    violations: list[str]
    sanitized_content: str | None = None


def check_content(content: str, context: str = "content") -> GuardResult:
    """Check text content for injection patterns.

    Args:
        content: Text to check.
        context: Description for logging (e.g., "title", "chunk", "metadata").

    Returns:
        GuardResult with safety assessment and any violations found.
    """
    violations: list[str] = []

    if not content:
        return GuardResult(safe=True, violations=[])

    # Length check
    if len(content) > MAX_CHUNK_LENGTH:
        violations.append(
            f"{context}: content exceeds max length ({len(content)} > {MAX_CHUNK_LENGTH})"
        )

    # Pattern matching
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(content)
        if match:
            violations.append(
                f"{context}: injection pattern detected: '{match.group()[:50]}'"
            )

    if violations:
        logger.warning(
            "Injection guard: %d violations in %s",
            len(violations), context,
        )

    return GuardResult(
        safe=len(violations) == 0,
        violations=violations,
    )


def check_metadata(metadata: dict[str, Any] | None) -> GuardResult:
    """Check document metadata for suspicious keys."""
    if not metadata:
        return GuardResult(safe=True, violations=[])

    violations: list[str] = []

    for key in metadata:
        if key.lower() in _SUSPICIOUS_META_KEYS:
            violations.append(f"metadata: suspicious key '{key}'")

        # Check nested string values for injection
        value = metadata[key]
        if isinstance(value, str) and len(value) > 100:
            content_check = check_content(value, context=f"metadata.{key}")
            violations.extend(content_check.violations)

    return GuardResult(
        safe=len(violations) == 0,
        violations=violations,
    )


def check_document(
    title: str,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    chunks: list[str] | None = None,
) -> GuardResult:
    """Full document injection guard check.

    Checks title, content, metadata, and individual chunks.
    Returns aggregated result.
    """
    all_violations: list[str] = []

    # Title check
    title_result = check_content(title, context="title")
    all_violations.extend(title_result.violations)

    # Content check
    if content:
        content_result = check_content(content, context="raw_content")
        all_violations.extend(content_result.violations)

    # Metadata check
    meta_result = check_metadata(metadata)
    all_violations.extend(meta_result.violations)

    # Chunk checks
    if chunks:
        for i, chunk in enumerate(chunks):
            chunk_result = check_content(chunk, context=f"chunk[{i}]")
            all_violations.extend(chunk_result.violations)

    if all_violations:
        logger.warning(
            "Document injection guard: %d total violations for '%s'",
            len(all_violations), title[:50],
        )

    return GuardResult(
        safe=len(all_violations) == 0,
        violations=all_violations,
    )


def sanitize_for_embedding(text: str) -> str:
    """Sanitize text before embedding to prevent injection via vector space.

    Strips known injection patterns while preserving semantic content.
    """
    sanitized = text
    for pattern in _COMPILED_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized
