"""BM25-style sparse vector tokenizer for Qdrant.

Generates {token_id: weight} sparse vectors using simple TF-based scoring.
Supports Chinese (jieba) and English (whitespace + stemming-like normalization).
IDF is approximated per-document since we don't maintain a global corpus stat.
"""

import logging
import math
import re
from collections import Counter

logger = logging.getLogger(__name__)

# Lazy-load jieba to avoid import overhead when not needed
_jieba = None


def _get_jieba():
    global _jieba
    if _jieba is None:
        import jieba

        jieba.setLogLevel(logging.WARNING)
        _jieba = jieba
    return _jieba


# CJK Unicode ranges
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_]+")

# Common stopwords (English + Chinese)
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "not", "no", "nor", "so", "yet", "both", "either", "neither", "this",
    "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一個", "上", "也", "很", "到", "說", "要", "去", "你",
    "會", "著", "沒有", "看", "好", "自己", "這", "他", "她",
})

# BM25 parameters
_K1 = 1.5
_B = 0.75
_AVG_DOC_LEN = 200  # approximate average document length in tokens


def _has_cjk(text: str) -> bool:
    return bool(_CJK_PATTERN.search(text))


def tokenize(text: str) -> list[str]:
    """Tokenize text into normalized tokens (Chinese + English)."""
    text = text.lower().strip()
    tokens = []

    if _has_cjk(text):
        jieba = _get_jieba()
        for word in jieba.cut(text):
            word = word.strip()
            if word and word not in _STOPWORDS and len(word) > 0:
                tokens.append(word)
    else:
        for match in _WORD_PATTERN.finditer(text):
            word = match.group().lower()
            if word not in _STOPWORDS and len(word) > 1:
                tokens.append(word)

    return tokens


def text_to_sparse_vector(text: str) -> dict[int, float]:
    """Convert text to a sparse vector using BM25-like TF scoring.

    Returns {token_hash: weight} suitable for Qdrant SparseVector.
    Token IDs are generated via hash to avoid maintaining a vocabulary.
    """
    tokens = tokenize(text)
    if not tokens:
        return {}

    doc_len = len(tokens)
    tf_counts = Counter(tokens)
    sparse = {}

    for token, tf in tf_counts.items():
        # BM25 TF component: tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl/avgdl))
        tf_score = (tf * (_K1 + 1)) / (tf + _K1 * (1 - _B + _B * doc_len / _AVG_DOC_LEN))

        # Simple IDF approximation: log(1 + 1/tf) — penalize very common terms
        idf_approx = math.log(1 + 1.0 / tf) + 1.0

        weight = tf_score * idf_approx

        # Use hash as token ID (Qdrant sparse vectors use integer keys)
        # Mask to positive 32-bit range for Qdrant compatibility
        token_id = hash(token) & 0x7FFFFFFF
        sparse[token_id] = weight

    return sparse
