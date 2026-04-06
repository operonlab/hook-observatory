"""EnrichmentOp — LLM-powered document enrichment.

Generates summaries, table of contents, and extracts inter-document relations.
Runs after indexing to enhance document metadata.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "Summarize this document in 2-3 concise sentences. "
    "Focus on the main topic and key conclusions.\n\n"
    "Document title: {title}\n"
    "Content (first 3000 chars):\n{content}"
)

TOC_PROMPT = (
    "Extract a table of contents from this document. "
    "Return a JSON array of objects with fields:\n"
    '- "title": section heading\n'
    '- "level": heading level (1-6)\n\n'
    "Document:\n{content}"
)

RELATION_PROMPT = (
    "Given these two document summaries, identify if there "
    "is a relationship between them.\n"
    "Possible relation types: cites, extends, contradicts, "
    "supersedes, related, none.\n\n"
    "Document A: {doc_a_title}\nSummary: {doc_a_summary}\n\n"
    "Document B: {doc_b_title}\nSummary: {doc_b_summary}\n\n"
    "Return a JSON object with fields:\n"
    '- "relation_type": one of the types above\n'
    '- "confidence": 0.0 to 1.0\n'
    '- "evidence": brief explanation\n\n'
    "If no meaningful relationship exists, return "
    '{{"relation_type": "none", "confidence": 0.0, '
    '"evidence": ""}}'
)


class EnrichmentOp:
    """Fixed Op: chunks + document → summary + relations + ToC."""

    @property
    def name(self) -> str:
        return "enrichment"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("raw_content", "doc_title", "document_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("summary", "table_of_contents", "discovered_relations")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raw_content: str = ctx["raw_content"]
        doc_title: str = ctx["doc_title"]

        # Generate summary
        summary = await self._generate_summary(doc_title, raw_content)
        ctx["summary"] = summary

        # Generate ToC
        toc = await self._generate_toc(raw_content)
        ctx["table_of_contents"] = toc

        # Relations are discovered async via event handlers, not inline
        ctx["discovered_relations"] = []

        logger.info(
            "Enrichment: title=%r, summary_len=%d, toc_entries=%d",
            doc_title[:50],
            len(summary),
            len(toc),
        )
        return ctx

    async def _generate_summary(self, title: str, content: str) -> str:
        """Generate document summary via LLM."""
        try:
            from src.shared.llm import acompletion

            prompt = SUMMARY_PROMPT.format(title=title, content=content[:3000])
            response = await acompletion(
                model="haiku",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.1,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Summary generation failed")
            return ""

    async def _generate_toc(self, content: str) -> list[dict[str, Any]]:
        """Extract table of contents via LLM."""
        try:
            from src.shared.llm import acompletion

            prompt = TOC_PROMPT.format(content=content[:5000])
            response = await acompletion(
                model="haiku",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.1,
            )
            text = response.choices[0].message.content.strip()
            # Extract JSON from response
            if "[" in text:
                json_str = text[text.index("[") : text.rindex("]") + 1]
                return json.loads(json_str)
            return []
        except Exception:
            logger.exception("ToC generation failed")
            return []

    @staticmethod
    async def analyze_relation(
        doc_a_title: str,
        doc_a_summary: str,
        doc_b_title: str,
        doc_b_summary: str,
    ) -> dict[str, Any]:
        """Analyze relationship between two documents. Used by event handlers."""
        try:
            from src.shared.llm import acompletion

            prompt = RELATION_PROMPT.format(
                doc_a_title=doc_a_title,
                doc_a_summary=doc_a_summary,
                doc_b_title=doc_b_title,
                doc_b_summary=doc_b_summary,
            )
            response = await acompletion(
                model="haiku",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.1,
            )
            text = response.choices[0].message.content.strip()
            if "{" in text:
                json_str = text[text.index("{") : text.rindex("}") + 1]
                return json.loads(json_str)
            return {"relation_type": "none", "confidence": 0.0, "evidence": ""}
        except Exception:
            logger.exception("Relation analysis failed")
            return {"relation_type": "none", "confidence": 0.0, "evidence": ""}
