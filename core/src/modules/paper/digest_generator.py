"""Structured digest generation for arXiv papers using Haiku LLM extraction.

Each paper generates a digest with:
- one_liner: single sentence summary
- key_findings: list of 3-5 concrete findings
- workshop_relevance: high/medium/low
- applicable_modules: which Workshop modules can apply this research
- actionable_insight: what to actually do with this
- effort_estimate: rough implementation effort (e.g., "1d", "3d", "1w")
- confidence: 0.0-1.0 extraction quality estimate
- model_used: actual LLM model name recorded for version tracking

Confidence gate: confidence < 0.5 means extraction is weak / paper not applicable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

DIGEST_SYSTEM_PROMPT = """\
You are a technical research analyst for Workshop, a personal modular monolith platform.

Workshop modules:
- memvault: LLM memory, semantic search, knowledge graph, pgvector embeddings (1024d Qwen3)
- intelflow: RSS feeds, daily briefings, intelligence digests
- capture: universal natural-language intake, LLM enrichment, routing
- paper: academic paper management (this module)
- taskflow: quests, tasks, dispatch, rewards
- ideagraph: sparks, idea links, knowledge graph
- finance: transactions, budgets, subscriptions
- auth: authentication, sessions, spaces, permissions
- notify: multi-channel notifications
- invest: investment tracking, portfolio analysis
- dailyos: daily operating system, planning, marvin AI assistant

Tech stack: Python 3.12 / FastAPI / PostgreSQL + pgvector / Redis / React 19 / MLX embeddings.

Your job: extract structured insights from academic paper abstracts so that less experienced \
readers can quickly understand what this paper means for Workshop's development roadmap.

Be concrete and direct. If a paper is not relevant to Workshop, say so with low confidence. \
Never fabricate findings not supported by the abstract.
"""

# ── Extraction tool schema ────────────────────────────────────────────────────

_DIGEST_TOOL: dict = {
    "name": "extract_paper_digest",
    "description": "Extract structured digest from an academic paper for Workshop relevance",
    "input_schema": {
        "type": "object",
        "properties": {
            "one_liner": {
                "type": "string",
                "description": (
                    "One sentence (max 120 chars) summarizing "
                    "the paper's core contribution"
                ),
            },
            "key_findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-5 concrete, specific findings from "
                    "the paper (not vague statements)"
                ),
            },
            "workshop_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": (
                    "high: directly applicable to Workshop development now; "
                    "medium: interesting but not immediately actionable; "
                    "low: tangentially related or too theoretical"
                ),
            },
            "applicable_modules": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Workshop module names that could directly apply this research "
                    "(e.g., ['memvault', 'intelflow']). Empty list if none."
                ),
            },
            "actionable_insight": {
                "type": "string",
                "description": (
                    "Specific, concrete action: what to implement or investigate "
                    "based on this paper. Start with a verb. Empty string if not actionable."
                ),
            },
            "effort_estimate": {
                "type": "string",
                "description": (
                    "Rough implementation effort for the actionable insight: "
                    "0.5d, 1d, 2d, 3d, 1w, 2w, or '' if not applicable"
                ),
            },
            "confidence": {
                "type": "number",
                "description": (
                    "0.0-1.0: your confidence in this extraction. "
                    "< 0.5 if abstract is unclear, highly theoretical, or not relevant. "
                    "0.5-0.7 for medium relevance. 0.8+ only for directly applicable work."
                ),
            },
        },
        "required": [
            "one_liner",
            "key_findings",
            "workshop_relevance",
            "applicable_modules",
            "actionable_insight",
            "effort_estimate",
            "confidence",
        ],
    },
}

# ── Default model sentinel ────────────────────────────────────────────────────

_UNKNOWN_MODEL = "claude-haiku-unknown"


# ── Core extraction function ──────────────────────────────────────────────────


async def generate_digest(
    title: str,
    abstract: str,
    arxiv_id: str | None = None,
) -> dict | None:
    """Generate a structured digest for a single paper using Haiku LLM extraction.

    Args:
        title: Paper title.
        abstract: Paper abstract text.
        arxiv_id: Optional arXiv ID for logging context.

    Returns:
        Dict with: one_liner, key_findings, workshop_relevance, applicable_modules,
        actionable_insight, effort_estimate, confidence, model_used.
        Returns None if extraction fails completely.

        Confidence gate: if confidence < 0.5, the digest is still returned
        (caller decides whether to persist) but marked as low-confidence.
    """
    from core.src.shared.llm_haiku import haiku_extract

    paper_id = arxiv_id or title[:40]

    user_message = f"""Paper: {title}

Abstract:
{abstract}

Extract a structured digest for Workshop relevance. Be concrete and specific."""

    logger.info("digest_generator: extracting digest for %s", paper_id)

    result = await haiku_extract(
        user_message=user_message,
        tool=_DIGEST_TOOL,
        system=DIGEST_SYSTEM_PROMPT,
    )

    if result is None:
        logger.warning("digest_generator: haiku_extract returned None for %s", paper_id)
        return None

    # Validate required fields
    required = [
        "one_liner",
        "key_findings",
        "workshop_relevance",
        "applicable_modules",
        "actionable_insight",
        "effort_estimate",
        "confidence",
    ]
    missing = [f for f in required if f not in result]
    if missing:
        logger.warning(
            "digest_generator: missing fields %s for %s — returning None",
            missing,
            paper_id,
        )
        return None

    # Coerce and validate types
    confidence = float(result.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))

    key_findings = result.get("key_findings", [])
    if isinstance(key_findings, str):
        key_findings = [key_findings]
    key_findings = [str(f) for f in key_findings[:5]]  # max 5

    applicable_modules = result.get("applicable_modules", [])
    if isinstance(applicable_modules, str):
        applicable_modules = [applicable_modules]
    applicable_modules = [str(m) for m in applicable_modules]

    workshop_relevance = result.get("workshop_relevance", "low")
    if workshop_relevance not in ("high", "medium", "low"):
        workshop_relevance = "low"

    # Detect actual model used (Haiku tmux pane may echo model in output)
    # haiku_extract doesn't return model info directly; record the configured model
    # The tmux pane uses CLAUDE_CMD which includes --model haiku
    model_used = _resolve_model_name()

    if confidence < 0.5:
        logger.info(
            "digest_generator: low confidence %.2f for %s (relevance=%s)",
            confidence,
            paper_id,
            workshop_relevance,
        )

    digest = {
        "one_liner": str(result.get("one_liner", ""))[:200],
        "key_findings": key_findings,
        "workshop_relevance": workshop_relevance,
        "applicable_modules": applicable_modules,
        "actionable_insight": str(result.get("actionable_insight", ""))[:500],
        "effort_estimate": str(result.get("effort_estimate", ""))[:10],
        "confidence": confidence,
        "model_used": model_used,
    }

    logger.info(
        "digest_generator: digest ready for %s — relevance=%s confidence=%.2f model=%s",
        paper_id,
        digest["workshop_relevance"],
        digest["confidence"],
        digest["model_used"],
    )
    return digest


def _resolve_model_name() -> str:
    """Resolve the actual model name used by the Haiku tmux capture window.

    Reads from llm_haiku._CLAUDE_CMD to extract the model flag.
    Falls back to a sentinel string if parsing fails.
    """
    try:
        from core.src.shared import llm_haiku

        cmd = llm_haiku._CLAUDE_CMD
        # cmd is like: "CLAUDE_VOICE=0 claude --dangerously-skip-permissions --model haiku"
        parts = cmd.split()
        for i, part in enumerate(parts):
            if part == "--model" and i + 1 < len(parts):
                return f"claude-{parts[i + 1]}"
    except Exception:  # noqa: S110
        pass
    return _UNKNOWN_MODEL


# ── Batch digest generation ───────────────────────────────────────────────────


async def generate_digests_batch(
    papers: list[dict],
    *,
    min_relevance_score: float = 0.3,
    confidence_threshold: float = 0.5,
) -> list[dict]:
    """Generate digests for a batch of papers, filtering by relevance score.

    Papers below min_relevance_score are skipped entirely.
    Digests with confidence < confidence_threshold are flagged but returned.

    Args:
        papers: List of paper dicts (must have title, abstract, optionally arxiv_id).
        min_relevance_score: Skip papers with relevance_score below this threshold.
        confidence_threshold: Flag (not skip) digests below this confidence.

    Returns:
        List of enriched paper dicts with 'digest' key added.
        Papers skipped due to low relevance have no 'digest' key.
    """
    results = []
    skipped = 0

    for paper in papers:
        relevance_score = paper.get("relevance_score", 1.0)
        if relevance_score < min_relevance_score:
            skipped += 1
            results.append(paper)
            continue

        digest = await generate_digest(
            title=paper["title"],
            abstract=paper["abstract"],
            arxiv_id=paper.get("arxiv_id"),
        )

        enriched = dict(paper)
        if digest is not None:
            enriched["digest"] = digest
            if digest["confidence"] < confidence_threshold:
                enriched["digest_flagged"] = True

        results.append(enriched)

    logger.info(
        "digest_generator: processed %d papers, skipped %d (low relevance), generated %d digests",
        len(papers),
        skipped,
        sum(1 for p in results if "digest" in p),
    )
    return results
