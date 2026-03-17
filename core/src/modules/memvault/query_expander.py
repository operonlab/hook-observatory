"""Query Expander — HyDE-style query enhancement for better memory retrieval.

Problem: Short queries like "that Python tool" or "我們之前說的" produce poor
embeddings. HyDE generates a hypothetical ideal memory that would match,
then embeds that instead.

Modes:
  1. HyDE: LLM generates hypothetical answer → embed that
  2. Keyword expansion: Extract key terms + synonyms for keyword search
  3. Passthrough: Query is already specific enough, use as-is
"""

import logging
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stop words
# ---------------------------------------------------------------------------

_EN_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "this",
        "that",
        "these",
        "those",
        "it",
        "i",
        "we",
        "you",
        "they",
        "he",
        "she",
        "my",
        "our",
        "your",
        "their",
        "his",
        "her",
        "its",
        "me",
        "us",
        "him",
        "them",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "why",
        "how",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "from",
        "up",
        "down",
        "out",
        "off",
        "over",
        "under",
        "again",
        "then",
        "once",
        "here",
        "there",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "but",
        "and",
        "or",
        "if",
        "as",
        "of",
        "to",
        "s",
        "t",
        "don",
        "doesn",
        "didn",
        "won",
        "wouldn",
        "couldn",
        "shouldn",
        "hasn",
        "hadn",
        "isn",
        "aren",
        "wasn",
        "weren",
    }
)

_CJK_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "也",
        "這",
        "那",
        "都",
        "他",
        "她",
        "們",
        "把",
        "被",
        "讓",
        "給",
        "一",
        "上",
        "很",
        "到",
        "要",
        "去",
        "你",
        "會",
        "著",
        "看",
        "好",
        "嗎",
        "吧",
        "呢",
        "啊",
        "喔",
        "欸",
        "什麼",
        "一個",
        "自己",
        "沒有",
        "可以",
        "因為",
        "所以",
        "但是",
        "如果",
        "然後",
        "現在",
        "這個",
        "那個",
        "這樣",
        "那樣",
        "一些",
        "這些",
        "那些",
        "已經",
        "還是",
        "只是",
        "其實",
    }
)

# ---------------------------------------------------------------------------
# Vague/demonstrative patterns that indicate expansion is useful
# ---------------------------------------------------------------------------

_VAGUE_EN = re.compile(
    r"\b(that|it|this|those|these|the thing|that thing|something|someone"
    r"|the one|what was|what is|which one|how do|how did"
    r"|previously|earlier|before|last time|ago)\b",
    re.IGNORECASE,
)

_VAGUE_CJK = re.compile(
    r"(之前|上次|那個|那件事|那時|哪個|哪種|什麼|那個工具|那個方法"
    r"|我們說的|我們之前|之前說|之前提|之前討論|記得|之前那個)"
)

_QUESTION_EN = re.compile(
    r"\b(what was|what is|what are|which|how do|how did|where is|where was)\b",
    re.IGNORECASE,
)

# CJK range for character detection
_CJK_RANGES = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\u3040-\u309f"
    r"\u30a0-\u30ff\uff00-\uffef\uac00-\ud7af\uf900-\ufaff]"
)

# Specific/technical token patterns (code identifiers, proper nouns)
_SPECIFIC_TOKENS = re.compile(r"[A-Z][a-z]+[A-Z]|[a-z]+_[a-z]+|`[^`]+`|\d{4,}|http[s]?://")

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ExpandedQuery:
    original: str
    expanded_text: str  # For embedding (HyDE output or original)
    keywords: list[str] = field(default_factory=list)  # Extracted keywords for keyword search
    expansion_used: str = "passthrough"  # "hyde" | "keyword" | "passthrough"
    inferred_tags: list[str] = field(default_factory=list)  # NEW: domain routing tags


# ---------------------------------------------------------------------------
# Domain tag inference for query routing
# ---------------------------------------------------------------------------

# Domain signal mapping for query routing
# Each domain has 5-7 signal keywords; query must match >= 2 to activate pre-filter
_DOMAIN_SIGNALS: dict[str, list[str]] = {
    "finance": [
        "報表",
        "預算",
        "帳單",
        "訂閱",
        "營收",
        "支出",
        "expense",
        "budget",
        "subscription",
        "revenue",
        "invoice",
        "transaction",
    ],
    "devops": [
        "docker",
        "nginx",
        "deploy",
        "k8s",
        "pipeline",
        "伺服器",
        "server",
        "container",
        "ci/cd",
        "kubernetes",
    ],
    "ai": [
        "llm",
        "embedding",
        "model",
        "prompt",
        "rag",
        "向量",
        "token",
        "fine-tune",
        "inference",
        "語言模型",
    ],
    "frontend": [
        "react",
        "css",
        "component",
        "rsbuild",
        "pnpm",
        "layout",
        "typescript",
        "前端",
        "ui",
        "tailwind",
    ],
    "invest": [
        "股票",
        "etf",
        "portfolio",
        "殖利率",
        "dividend",
        "持股",
        "投資",
        "基金",
        "報酬率",
    ],
    "planning": [
        "排程",
        "schedule",
        "cronicle",
        "每日",
        "weekly",
        "daily",
        "todo",
        "task",
        "待辦",
    ],
}

_MIN_SIGNAL_MATCH = 2  # Minimum signals to activate domain pre-filter


def _infer_domain_tags(query: str) -> list[str]:
    """Infer domain tags from query for pre-filtering.

    Returns matching domain tags if >= _MIN_SIGNAL_MATCH signals found.
    Returns empty list if uncertain (safe fallback to full search).
    """
    query_lower = query.lower()
    matched = []
    for domain, signals in _DOMAIN_SIGNALS.items():
        count = sum(1 for s in signals if s.lower() in query_lower)
        if count >= _MIN_SIGNAL_MATCH:
            matched.append(domain)
    return matched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def should_expand(query: str) -> bool:
    """Determine if query needs expansion.

    Expand when:
    - Query is short (<30 chars for CJK, <50 for Latin)
    - Query contains pronouns/demonstratives ("that", "it", "那個", "之前的")
    - Query is a question form ("what was", "哪個")

    Don't expand when:
    - Query is already specific (contains proper nouns, code identifiers)
    - Query is a direct memory keyword match ("記住", "remember")
    - Query length > 100 chars (already detailed enough)
    """
    stripped = query.strip()

    # Too short to meaningfully expand
    if len(stripped) < 3:
        return False

    # Very long queries already contain enough context
    if len(stripped) > 100:
        return False

    # Queries with specific/technical tokens are already precise
    if _SPECIFIC_TOKENS.search(stripped):
        return False

    # Direct memory retrieval keywords — user knows what they want
    direct_memory_kw = ["記住", "memorize", "remember that", "store this", "save this"]
    lower = stripped.lower()
    if any(kw in lower for kw in direct_memory_kw):
        return False

    # Detect CJK dominance
    cjk_count = len(_CJK_RANGES.findall(stripped))
    is_cjk_dominant = cjk_count / max(len(stripped), 1) > 0.3

    # Short query thresholds
    if is_cjk_dominant and len(stripped) < 30:
        return True
    if not is_cjk_dominant and len(stripped) < 50:
        return True

    # Vague demonstratives / pronouns
    if _VAGUE_EN.search(stripped) or _VAGUE_CJK.search(stripped):
        return True

    # Question forms
    if _QUESTION_EN.search(stripped):
        return True

    return False


def _build_hyde_prompt(query: str) -> str:
    """Build prompt for hypothetical memory generation.

    Prompt the LLM to generate what an ideal memory entry would look like
    for this query. Short, factual, like a note to self.
    """
    return (
        "You are a memory retrieval assistant. Given a search query, generate a SHORT "
        "hypothetical memory entry (2-3 sentences) that would perfectly answer this query. "
        "Write it as if it were a stored memory note.\n\n"
        f"Query: {query}\n\n"
        "Respond with ONLY the hypothetical memory text, nothing else. "
        "Match the language of the query."
    )


async def expand_query(query: str) -> ExpandedQuery:
    """Expand a query for better retrieval.

    1. Check if expansion is needed (should_expand)
    2. If yes, try HyDE via local LLM (oMLX port 8000)
    3. Extract keywords regardless
    4. Infer domain tags for pre-filtering
    5. Return ExpandedQuery

    Falls back to keyword-only expansion if LLM unavailable.
    """
    keywords = extract_keywords(query)
    inferred_tags = _infer_domain_tags(query)

    if not should_expand(query):
        return ExpandedQuery(
            original=query,
            expanded_text=query,
            keywords=keywords,
            expansion_used="passthrough",
            inferred_tags=inferred_tags,
        )

    # Try HyDE via local LLM
    prompt = _build_hyde_prompt(query)
    hypothetical = await _call_local_llm(prompt, max_tokens=200)

    if hypothetical and hypothetical.strip():
        hyde_text = hypothetical.strip()
        # Also extract keywords from the hypothetical document for richer keyword search
        hyde_keywords = extract_keywords(hyde_text)
        # Merge keywords: original first, then unique additions from hyde
        merged_keywords = list(keywords)
        seen = set(keywords)
        for kw in hyde_keywords:
            if kw not in seen:
                merged_keywords.append(kw)
                seen.add(kw)

        return ExpandedQuery(
            original=query,
            expanded_text=hyde_text,
            keywords=merged_keywords[:8],
            expansion_used="hyde",
            inferred_tags=inferred_tags,
        )

    # LLM unavailable — fall back to keyword-only expansion
    # Use original query but with enriched keyword set
    return ExpandedQuery(
        original=query,
        expanded_text=query,
        keywords=keywords,
        expansion_used="keyword",
        inferred_tags=inferred_tags,
    )


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text for keyword search.

    - Remove stop words (English + Chinese common ones)
    - Keep proper nouns, technical terms, numbers
    - For CJK text, keep 2+ char segments
    - Return top 5-8 keywords
    """
    stripped = text.strip()
    if not stripped:
        return []

    keywords: list[str] = []
    seen: set[str] = set()

    cjk_count = len(_CJK_RANGES.findall(stripped))
    has_cjk = cjk_count > 0

    if has_cjk:
        # Use jieba for CJK tokenization
        try:
            import logging as _logging

            import jieba

            jieba.setLogLevel(_logging.WARNING)
            tokens = list(jieba.cut(stripped))
        except ImportError:
            # Fallback: split on whitespace and extract CJK segments
            tokens = _fallback_cjk_tokenize(stripped)

        for token in tokens:
            token = token.strip()
            if not token:
                continue
            # Keep CJK tokens of 2+ chars that are not stopwords
            token_lower = token.lower()
            if _CJK_RANGES.search(token):
                if len(token) >= 2 and token not in _CJK_STOPWORDS and token not in seen:
                    keywords.append(token)
                    seen.add(token)
            else:
                # Mixed text: also keep Latin tokens
                if (
                    len(token) > 2
                    and token_lower not in _EN_STOPWORDS
                    and re.match(r"[a-zA-Z0-9]", token)
                    and token_lower not in seen
                ):
                    keywords.append(token)
                    seen.add(token_lower)
    else:
        # Pure Latin / English
        for match in re.finditer(r"[a-zA-Z0-9][a-zA-Z0-9_\-\.]*", stripped):
            token = match.group()
            token_lower = token.lower()
            if len(token) > 2 and token_lower not in _EN_STOPWORDS and token_lower not in seen:
                keywords.append(token)
                seen.add(token_lower)

    return keywords[:8]


def _fallback_cjk_tokenize(text: str) -> list[str]:
    """Simple fallback tokenizer when jieba is unavailable.

    Splits on whitespace and punctuation, preserving CJK character groups.
    """
    tokens: list[str] = []
    # Split on whitespace and common punctuation
    parts = re.split(
        r"[\s\u3000\uff0c\u3002\uff01\uff1f\u300c\u300d\u3010\u3011\uff0c\u3002\uff01\uff1f\u300c\u300d\u3010\u3011]+",
        text,
    )
    for part in parts:
        if part:
            # Extract CJK runs and Latin runs separately
            for segment in re.finditer(
                r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+|[a-zA-Z0-9_\-]+",
                part,
            ):
                tokens.append(segment.group())
    return tokens


# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------


async def _call_local_llm(prompt: str, max_tokens: int = 200) -> str | None:
    """Call oMLX local LLM for query expansion. Returns None on failure.

    Uses oMLX port 8000 with a 5-second timeout to keep search fast.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                "http://localhost:8000/v1/chat/completions",
                json={
                    "model": "default",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
    except httpx.TimeoutException:
        logger.debug("oMLX LLM timeout during query expansion — falling back to keyword mode")
    except httpx.ConnectError:
        logger.debug("oMLX LLM unavailable — falling back to keyword mode")
    except Exception:
        logger.exception("Unexpected error during HyDE LLM call")
    return None
