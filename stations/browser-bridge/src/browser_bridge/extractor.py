"""ResultExtractor — extract AI response from raw DOM text.

Handles two concerns:
1. Prompt marker extraction: Use the prompt as an anchor to find where
   the AI response begins in the full page text.
2. UI artifact cleaning: Remove button labels, timers, navigation text,
   and other "ghost text" that appears in innerText but isn't part of
   the actual response.

Patterns learned from grok-bridge analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CleaningRule:
    """A rule for removing UI artifacts from extracted text."""

    # Truncate text at this marker (rfind, keep everything before)
    truncate_markers: list[str] = field(default_factory=list)
    # Remove lines matching these regexes
    line_filters: list[str] = field(default_factory=list)
    # Remove substrings matching these regexes
    substring_filters: list[str] = field(default_factory=list)


# Default cleaning rules (common across providers)
DEFAULT_CLEANING_RULES = CleaningRule(
    truncate_markers=[],
    line_filters=[
        r"^[0-9]+(\.[0-9]+)?s$",  # timing markers like "1.3s"
        r"^[0-9]+ sources$",  # "5 sources"
    ],
    substring_filters=[
        r"\n{3,}",  # collapse 3+ newlines to 2
    ],
)

# Grok-specific cleaning rules
GROK_CLEANING_RULES = CleaningRule(
    truncate_markers=[
        # English UI
        "\nAsk anything",
        "\nDeepSearch",
        "\nThink Harder",
        "\nThink\n",
        "\nAttach",
        "\nGrok",
        "\nFast\n",
        "\nAuto\n",
        "\nUpgrade to",
        # Chinese UI (zh-TW)
        "\n深度思考",
        "\n快速\n",
        "\n自動\n",
        "\n升級至",
        "\n解鎖進階功能",
        "\n免費試用",
        "\n提交\n",
        "\n附加\n",
        "\n選擇模型",
    ],
    line_filters=[
        r"^[0-9]+(\.[0-9]+)?秒$",  # "1.1秒"
        r"^[0-9]+(\.[0-9]+)?s$",  # "1.3s"
        r"^[0-9]+ sources$",
        r"^(Share|Compare|Make it|Explain|Toggle|Like|Dislike)",
        r"^(Are you satisfied|Get notified|Expert|Quick Answer)",
        r"^(Submit|Model select|Start dictation|Enter voice mode|Private|Imagine)$",
        r"^(Explain .+|.+ basics)$",  # suggested follow-up prompts
    ],
    substring_filters=[
        r"\n{3,}",
    ],
)

# NotebookLM-specific cleaning rules
NOTEBOOKLM_CLEANING_RULES = CleaningRule(
    truncate_markers=[
        "\nAdd source",
        "\nNotebook guide",
        "\nAudio Overview",
    ],
    line_filters=[
        r"^(Loading|Generating|Processing)\.\.\.$",
    ],
    substring_filters=[
        r"\n{3,}",
    ],
)

# Registry for provider-specific rules
PROVIDER_RULES: dict[str, CleaningRule] = {
    "grok": GROK_CLEANING_RULES,
    "notebooklm": NOTEBOOKLM_CLEANING_RULES,
}


class ResultExtractor:
    """Extract and clean AI responses from raw DOM text.

    Usage:
        extractor = ResultExtractor(provider="grok")
        response = extractor.extract(full_page_text, original_prompt)
    """

    def __init__(self, provider: str = "") -> None:
        self.rules = PROVIDER_RULES.get(provider, DEFAULT_CLEANING_RULES)

    def extract(self, body: str, prompt: str, marker_length: int = 60) -> str:
        """Extract AI response from full page text.

        Uses the prompt as a marker to find where the response begins,
        then applies cleaning rules.

        Args:
            body: Full document.body.innerText content.
            prompt: The original user prompt (used as anchor).
            marker_length: How many chars of prompt to use as marker.

        Returns:
            Cleaned response text.
        """
        # Step 1: Find response using prompt marker
        raw = self._extract_after_prompt(body, prompt, marker_length)

        # Step 2: Apply cleaning rules
        cleaned = self._apply_rules(raw)

        return cleaned.strip()

    def _extract_after_prompt(self, body: str, prompt: str, marker_length: int) -> str:
        """Split body text at prompt marker, return everything after."""
        if not prompt:
            return body

        marker = prompt[:marker_length]
        parts = body.split(marker)

        if len(parts) >= 2:
            # Take everything after the last occurrence of the marker
            return parts[-1]
        return body

    def _apply_rules(self, text: str) -> str:
        """Apply cleaning rules to remove UI artifacts."""
        result = text

        # Truncate at markers (rfind = last occurrence, keep before)
        for marker in self.rules.truncate_markers:
            idx = result.rfind(marker)
            if idx > 0:
                result = result[:idx]

        # Filter out matching lines
        if self.rules.line_filters:
            lines = result.split("\n")
            filtered_lines = []
            for line in lines:
                stripped = line.strip()
                if any(re.match(p, stripped) for p in self.rules.line_filters):
                    continue
                filtered_lines.append(line)
            result = "\n".join(filtered_lines)

        # Apply substring filters
        for pattern in self.rules.substring_filters:
            result = re.sub(pattern, "\n\n", result)

        return result
