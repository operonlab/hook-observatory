"""Shared text utilities — CJK detection, jieba tokenization, multi-term query building.

Extracted from memvault/services.py and sparse_tokenizer.py for cross-module reuse.
Used by: memvault, intelflow, fallback_search.
"""

import re
from collections import Counter

# CJK Unicode ranges (CJK Unified + Extension A + Compatibility + Kana + Hangul)
_CJK_RANGES = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\u3040-\u309f"
    r"\u30a0-\u30ff\uff00-\uffef\uac00-\ud7af\uf900-\ufaff]"
)

# Common CJK stopwords (query-level, not document-level)
_CJK_QUERY_STOPWORDS = frozenset({
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "都",
    "一", "一個", "上", "也", "很", "到", "要", "去", "你",
    "會", "著", "沒有", "看", "好", "自己", "這", "他", "她",
    "嗎", "吧", "呢", "啊", "喔", "欸", "那", "什麼",
})

# Lazy-load jieba
_jieba = None


def _get_jieba():
    global _jieba
    if _jieba is None:
        import logging

        import jieba

        jieba.setLogLevel(logging.WARNING)
        _jieba = jieba
    return _jieba


def is_cjk(text: str) -> bool:
    """Check if text contains any CJK characters."""
    return bool(_CJK_RANGES.search(text))


def is_cjk_dominant(text: str, threshold: float = 0.3) -> bool:
    """Check if text is predominantly CJK characters.

    Args:
        text: Input text.
        threshold: Ratio of CJK chars to total length (default 0.3 = 30%).
    """
    if not text:
        return False
    cjk_count = len(_CJK_RANGES.findall(text))
    return cjk_count / len(text) > threshold


def jieba_tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    """Tokenize text using jieba for CJK, regex for English.

    Returns deduplicated, lowercased tokens in appearance order.
    """
    text = text.lower().strip()
    if not text:
        return []

    tokens = []
    seen = set()

    if is_cjk(text):
        jieba = _get_jieba()
        for word in jieba.cut(text):
            word = word.strip()
            if not word or len(word) == 0:
                continue
            if remove_stopwords and word in _CJK_QUERY_STOPWORDS:
                continue
            if word not in seen:
                tokens.append(word)
                seen.add(word)
    else:
        for match in re.finditer(r"[a-zA-Z0-9_]+", text):
            word = match.group().lower()
            if len(word) <= 1:
                continue
            if word not in seen:
                tokens.append(word)
                seen.add(word)

    return tokens


def compute_keyword_score(
    query_tokens: list[str],
    text: str,
    k1: float = 1.5,
    b: float = 0.75,
    avgdl: int = 100,
) -> float:
    """Compute BM25-lite TF score for a query against text.

    Lightweight scoring without global IDF — suitable for PostgreSQL
    fallback where we don't have Qdrant's full BM25 sparse vectors.

    Returns a score in [0, 1] range, normalized by max possible score.
    """
    text_lower = text.lower()

    if is_cjk(text):
        # CJK: count token occurrences
        doc_tokens = jieba_tokenize(text_lower, remove_stopwords=False)
    else:
        doc_tokens = re.findall(r"[a-zA-Z0-9_]+", text_lower)

    if not doc_tokens or not query_tokens:
        return 0.0

    doc_len = len(doc_tokens)
    tf_counts = Counter(doc_tokens)
    total_score = 0.0

    for token in query_tokens:
        tf = tf_counts.get(token, 0)
        if tf == 0:
            # Partial match for CJK (substring check)
            if is_cjk(token):
                tf = text_lower.count(token)
            if tf == 0:
                continue

        # BM25 TF component
        tf_score = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avgdl))
        total_score += tf_score

    # Normalize: divide by number of query terms for [0, ~2.5] range → cap at 1.0
    if query_tokens:
        normalized = total_score / len(query_tokens)
        return min(normalized / 2.5, 1.0)  # 2.5 = max single-term BM25 TF
    return 0.0
