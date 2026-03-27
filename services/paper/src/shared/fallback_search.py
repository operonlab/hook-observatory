"""Fallback search helpers — simplified for paper-svc (no jieba, ILIKE only)."""

from sqlalchemy import Column, or_


def build_ilike_conditions(query: str, *columns: Column) -> list:
    """Build SQLAlchemy ILIKE conditions for keyword fallback search.

    Simplified version: splits on whitespace and builds OR conditions per token.
    """
    tokens = [t.strip() for t in query.split() if t.strip()]
    if not tokens:
        return []

    # Each token must match at least one column (AND across tokens)
    token_conditions = []
    for token in tokens:
        pattern = f"%{token}%"
        col_match = or_(*[col.ilike(pattern) for col in columns])
        token_conditions.append(col_match)
    return token_conditions


def score_text_match(query: str, text: str, tier: str = "hot") -> float:
    """Simple keyword match scoring — returns 0.5 base for any match."""
    if not text or not query:
        return 0.0
    query_lower = query.lower()
    text_lower = text.lower()
    tokens = query_lower.split()
    if not tokens:
        return 0.0
    matched = sum(1 for t in tokens if t in text_lower)
    return 0.5 * (matched / len(tokens))
